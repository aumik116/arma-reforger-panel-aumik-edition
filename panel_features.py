"""Accounts, permissions, saved mod sets, and durable panel activity history."""
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

import bcrypt
from flask import g, jsonify, request, session, redirect

ROLES = {
    "viewer": {"view"},
    "operator": {"view", "control", "logs"},
    "manager": {"view", "control", "logs", "configure", "mods", "activity"},
    "admin": {"view", "control", "logs", "configure", "mods", "activity", "users"},
}
MUTATIONS = {
    "api_start": "control", "api_stop": "control", "api_restart": "control",
    "api_config": "configure", "api_persistence_set": "configure",
    "api_persistence_flush": "configure", "api_scenarios_rescan": "mods",
    "api_mods_add": "mods", "api_mods_remove": "mods", "api_mods_import": "mods",
    "presets_save": "mods", "presets_apply": "mods", "presets_delete": "mods",
    "users_save": "users", "users_delete": "users", "account_password": "view",
}


def install(api):
    app = api.app
    path = api._cfg.get("PANEL_DATA_FILE", os.path.join(api._BASE_DIR, ".panel-data.sqlite3"))
    lock = threading.RLock()

    @contextmanager
    def db():
        conn = sqlite3.connect(path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                password TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS presets (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
                mods TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, outcome TEXT NOT NULL, details TEXT NOT NULL);
        """)
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            conn.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                         ("admin", api.PANEL_PASSWORD_HASH, "admin"))
    os.chmod(path, 0o600)

    def audit(actor, action, outcome, details=None):
        with db() as conn:
            conn.execute("INSERT INTO activity(ts,actor,action,outcome,details) VALUES(?,?,?,?,?)",
                         (time.time(), actor, action, outcome, json.dumps(details or {})))

    def authenticate(username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        hashed = user["password"] if user else api.PANEL_PASSWORD_HASH
        try:
            valid = bcrypt.checkpw(password.encode(), hashed.encode())
        except (ValueError, TypeError):
            valid = False
        return dict(user) if valid and user and user["enabled"] else None

    api.authenticate_user = authenticate
    api.audit_event = audit

    def metric_events():
        # Only non-sensitive labels are exposed to dashboard viewers.
        with db() as conn:
            rows = conn.execute("""SELECT id,ts,action FROM activity
                WHERE outcome='success' AND ts >= ? AND action IN
                ('api_start','api_stop','api_restart','api_mods_add','api_mods_remove',
                 'api_mods_import','presets_apply') ORDER BY id DESC LIMIT 50""",
                (time.time() - 3600,)).fetchall()
        return [dict(row) for row in rows]

    api.metric_events = metric_events

    @app.before_request
    def authorize():
        if request.endpoint in {"login", "static", "manifest", "service_worker"}:
            return
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (session.get("user_id"),)).fetchone()
        if not user or not user["enabled"] or user["version"] != session.get("user_version"):
            session.clear()
            if request.path.startswith("/api/") or request.method != "GET":
                return jsonify(error="Please sign in", ok=False), 401
            return redirect("/login")
        g.user = dict(user)
        g.permissions = ROLES[user["role"]]
        needed = MUTATIONS.get(request.endpoint) if request.method == "POST" else {
            "api_logs": "logs", "users_list": "users", "activity_list": "activity",
            "api_persistence_get": "configure",
        }.get(request.endpoint, "view")
        if needed and needed not in g.permissions:
            return jsonify(ok=False, error="Your account does not have permission for this action"), 403
        if request.method == "POST":
            if request.is_json and not isinstance(request.get_json(silent=True), dict):
                return jsonify(ok=False, error="Request body must be a JSON object"), 400
            data = request.get_json(silent=True) or {}
            if "id" in data and (type(data["id"]) is not int or data["id"] < 1):
                return jsonify(ok=False, error="Invalid record ID"), 400
            err = api._csrf_required()
            if err:
                return err
            lock.acquire()
            g.mutation_lock = True
            g.before_config = api.read_config()
            g.audit_actor = user["username"]
            g.audit_details = {}
            if request.endpoint == "api_persistence_set":
                g.audit_details = {k: data[k] for k in ("enabled", "autoSaveInterval", "hiveId") if k in data}

    @app.teardown_request
    def release_lock(exc):
        if g.pop("mutation_lock", False):
            lock.release()

    @app.after_request
    def record_action(response):
        response.headers["Cache-Control"] = "no-store"
        if request.method == "POST" and request.endpoint in MUTATIONS and hasattr(g, "audit_actor"):
            result = response.get_json(silent=True) or {}
            ok = response.status_code < 400 and result.get("ok") is True
            details = g.audit_details
            if ok:
                before = g.before_config.get("game", {})
                after = api.read_config().get("game", {})
                old = {m.get("modId"): m for m in before.get("mods", [])}
                new = {m.get("modId"): m for m in after.get("mods", [])}
                if old != new:
                    details["added_mods"] = [new[k] for k in new.keys() - old.keys()]
                    details["removed_mods"] = [old[k] for k in old.keys() - new.keys()]
                    details["updated_mods"] = [new[k] for k in old.keys() & new.keys() if old[k] != new[k]]
                changed = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k) and k != "mods"]
                if changed:
                    details["changed_fields"] = changed  # Never store passwords or config values.
            audit(g.audit_actor, request.endpoint, "success" if ok else "failed", details)
        return response

    @app.get("/api/me")
    def account_me():
        return jsonify(username=g.user["username"], role=g.user["role"], permissions=sorted(g.permissions))

    def body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def password_hash(value):
        if not isinstance(value, str) or len(value) < 10 or len(value.encode()) > 72:
            raise ValueError("Passwords must contain at least 10 characters and at most 72 UTF-8 bytes")
        return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()

    @app.post("/api/account/password")
    def account_password():
        data = body()
        if not authenticate(g.user["username"], data.get("current_password", "")):
            return jsonify(ok=False, error="Current password is incorrect"), 400
        try:
            hashed = password_hash(data.get("password"))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        with db() as conn:
            conn.execute("UPDATE users SET password=?,version=version+1 WHERE id=?", (hashed, g.user["id"]))
        session["user_version"] += 1
        return jsonify(ok=True)

    @app.get("/api/users")
    def users_list():
        with db() as conn:
            rows = conn.execute("SELECT id,username,role,enabled FROM users ORDER BY username").fetchall()
        return jsonify(users=[dict(row) for row in rows], roles=list(ROLES))

    @app.post("/api/users")
    def users_save():
        data = body()
        username, role = data.get("username", ""), data.get("role", "viewer")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username) or not isinstance(role, str) or role not in ROLES:
            return jsonify(ok=False, error="Use a 3–32 character username (letters, numbers, _, . or -) and a valid role"), 400
        if not isinstance(data.get("enabled", True), bool):
            return jsonify(ok=False, error="Enabled must be true or false"), 400
        enabled = int(data.get("enabled", True))
        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT * FROM users WHERE id=?", (data.get("id"),)).fetchone()
                if data.get("id") is not None and not existing:
                    return jsonify(ok=False, error="Account not found"), 404
                if existing:
                    if existing["id"] == g.user["id"] and (not enabled or role != "admin"):
                        return jsonify(ok=False, error="You cannot disable or demote your own administrator account"), 400
                    if existing["role"] == "admin" and existing["enabled"] and (not enabled or role != "admin"):
                        count = conn.execute("SELECT count(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]
                        if count <= 1:
                            return jsonify(ok=False, error="Keep at least one enabled administrator"), 400
                    hashed = password_hash(data["password"]) if data.get("password") else existing["password"]
                    conn.execute("UPDATE users SET username=?,role=?,enabled=?,password=?,version=version+1 WHERE id=?",
                                 (username, role, enabled, hashed, existing["id"]))
                    if existing["id"] == g.user["id"]:
                        session["user_version"] += 1
                else:
                    conn.execute("INSERT INTO users(username,password,role,enabled) VALUES(?,?,?,?)",
                                 (username, password_hash(data.get("password")), role, enabled))
        except (ValueError, sqlite3.IntegrityError) as exc:
            return jsonify(ok=False, error="Username is already in use" if isinstance(exc, sqlite3.IntegrityError) else str(exc)), 400
        g.audit_details = {"username": username, "role": role, "enabled": bool(enabled)}
        return jsonify(ok=True)

    @app.post("/api/users/delete")
    def users_delete():
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id=?", (body().get("id"),)).fetchone()
            if not user:
                return jsonify(ok=False, error="Account not found"), 404
            if user["id"] == g.user["id"]:
                return jsonify(ok=False, error="You cannot delete your own account"), 400
            if user["role"] == "admin" and user["enabled"]:
                count = conn.execute("SELECT count(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0]
                if count <= 1:
                    return jsonify(ok=False, error="Keep at least one enabled administrator"), 400
            conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
        g.audit_details = {"username": user["username"]}
        return jsonify(ok=True)

    @app.get("/api/presets")
    def presets_list():
        with db() as conn:
            rows = conn.execute("SELECT * FROM presets ORDER BY name").fetchall()
        active = api.read_config().get("game", {}).get("mods", [])
        return jsonify(presets=[dict(row, mods=json.loads(row["mods"]), active=json.loads(row["mods"]) == active) for row in rows])

    @app.post("/api/presets")
    def presets_save():
        data = body()
        name = data.get("name", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            return jsonify(ok=False, error="Enter a preset name of 1–80 characters"), 400
        mods = api.read_config().get("game", {}).get("mods", [])
        with db() as conn:
            if data.get("id") is not None:
                if not conn.execute("SELECT 1 FROM presets WHERE id=?", (data["id"],)).fetchone():
                    return jsonify(ok=False, error="Preset not found"), 404
            try:
                if data.get("id") is None:
                    conn.execute("INSERT INTO presets(name,mods,updated_by,updated_at) VALUES(?,?,?,?)",
                                 (name.strip(), json.dumps(mods), g.user["username"], time.time()))
                else:
                    conn.execute("UPDATE presets SET name=?,mods=?,updated_by=?,updated_at=? WHERE id=?",
                                 (name.strip(), json.dumps(mods), g.user["username"], time.time(), data["id"]))
            except sqlite3.IntegrityError:
                return jsonify(ok=False, error="A preset with this name already exists"), 400
        g.audit_details = {"preset": name.strip(), "mod_count": len(mods)}
        return jsonify(ok=True)

    @app.post("/api/presets/apply")
    def presets_apply():
        with db() as conn:
            row = conn.execute("SELECT * FROM presets WHERE id=?", (body().get("id"),)).fetchone()
        if not row:
            return jsonify(ok=False, error="Preset not found"), 404
        cfg = api.read_config()
        cfg.setdefault("game", {})["mods"] = json.loads(row["mods"])
        api.write_config(cfg)
        g.audit_details = {"preset": row["name"]}
        return jsonify(ok=True, restart_required=api.get_server_pid() is not None)

    @app.post("/api/presets/delete")
    def presets_delete():
        with db() as conn:
            row = conn.execute("SELECT * FROM presets WHERE id=?", (body().get("id"),)).fetchone()
            if not row:
                return jsonify(ok=False, error="Preset not found"), 404
            conn.execute("DELETE FROM presets WHERE id=?", (row["id"],))
        g.audit_details = {"preset": row["name"]}
        return jsonify(ok=True)

    @app.get("/api/activity")
    def activity_list():
        try:
            before = int(request.args.get("before", "0"))
        except ValueError:
            return jsonify(ok=False, error="Invalid activity cursor"), 400
        with db() as conn:
            rows = conn.execute("SELECT * FROM activity WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT 51", (before, before)).fetchall()
        return jsonify(events=[dict(row, details=json.loads(row["details"])) for row in rows[:50]],
                       next_before=rows[49]["id"] if len(rows) > 50 else None)

    from player_query import PlayerQuery
    query = PlayerQuery()

    @app.get("/api/players")
    def players_list():
        if not api.get_server_pid():
            query.clear()
            return jsonify(available=True, players=[], message="Server is offline")
        return jsonify(query.read(api.read_config().get("rcon", {}), api._cfg))
