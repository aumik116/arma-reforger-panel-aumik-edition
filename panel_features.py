"""Accounts, permissions, saved mod sets, and durable panel activity history."""
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

import bcrypt
import config_backups
import player_query
from config_editor import revision
from flask import g, jsonify, request, session, redirect

ROLES = {
    "viewer": {"view"},
    "operator": {"view", "control", "logs"},
    "manager": {"view", "control", "logs", "configure", "mods", "activity"},
    "admin": {"view", "control", "logs", "configure", "mods", "activity", "users", "admin_config"},
}
MUTATIONS = {
    "notifications_save": "admin_config", "notifications_test": "admin_config",
    'workshop_apply': 'mods',
    'files_create': 'admin_config', 'files_upload': 'admin_config', 'files_rename': 'admin_config',
    'files_delete': 'admin_config', 'files_restore': 'admin_config',
    'startup_save':'admin_config', 'players_admin_save':'admin_config',
    'schedules_save':'admin_config', 'schedules_change':'admin_config',
    'account_preferences_save': 'view',
    'servers_create': 'users', 'server_provision_retry': 'admin_config',
    'server_delete': 'admin_config', 'server_startup_save': 'admin_config',
    "rcon_command": "admin_config",
    "software_check": "admin_config", "software_update": "admin_config",
    "api_start": "control", "api_stop": "control", "api_restart": "control",
    "api_config": "configure", "api_persistence_set": "admin_config",
    "config_editor_save": "configure", "config_editor_validate": "configure",
    "admin_label_save": "admin_config",
    "api_persistence_flush": "admin_config", "api_persistence_startup_save": "admin_config",
    "api_persistence_named_save": "admin_config", "api_scenarios_rescan": "mods",
    "api_mods_add": "mods", "api_mods_remove": "mods", "api_mods_import": "mods", "api_mods_edit": "mods", "api_mods_update_pins": "mods",
    "api_mods_server_apply": "mods",
    "presets_save": "mods", "presets_apply": "mods", "presets_delete": "mods",
    "config_backup_restore": "admin_config",
    "users_save": "users", "users_delete": "users", "account_password": "view",
    "files_preview": "admin_config", "files_save": "admin_config",
}


def install(api):
    app = api.app
    path = api._cfg.get("PANEL_DATA_FILE", os.path.join(api._BASE_DIR, ".panel-data.sqlite3"))
    lock = api.instance_scoped('mutation_lock', threading.RLock, threading.RLock())
    api.operation_lock = lock
    preset_lock = threading.RLock()

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
            CREATE TABLE IF NOT EXISTS admin_labels (identity TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS user_preferences (user_id INTEGER PRIMARY KEY, theme TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
                password TEXT NOT NULL, role TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS presets (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
                mods TEXT NOT NULL, scenario_id TEXT, updated_by TEXT NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, outcome TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS panel_owner (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), user_id INTEGER NOT NULL);
        """)
        if 'access_all' not in {row['name'] for row in conn.execute('PRAGMA table_info(users)')}:
            conn.execute('ALTER TABLE users ADD COLUMN access_all INTEGER NOT NULL DEFAULT 1')
        if 'panel_admin' not in {row['name'] for row in conn.execute('PRAGMA table_info(users)')}:
            conn.execute('ALTER TABLE users ADD COLUMN panel_admin INTEGER NOT NULL DEFAULT 0')
            conn.execute("UPDATE users SET panel_admin=1 WHERE role='admin'")
        conn.execute("CREATE TABLE IF NOT EXISTS user_server_roles (user_id INTEGER NOT NULL, server_id TEXT NOT NULL, role TEXT NOT NULL, PRIMARY KEY(user_id,server_id))")
        if 'scenario_id' not in {row['name'] for row in conn.execute('PRAGMA table_info(presets)')}:
            conn.execute('ALTER TABLE presets ADD COLUMN scenario_id TEXT')
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            conn.execute("INSERT INTO users(username,password,role) VALUES(?,?,?)",
                         ("admin", api.PANEL_PASSWORD_HASH, "admin"))
        # The bootstrap account was always ID 1. Never infer ownership from a
        # mutable username or transfer it to another administrator on startup.
        conn.execute("INSERT OR IGNORE INTO panel_owner(singleton,user_id) VALUES(1,1)")
        owner_id = conn.execute("SELECT user_id FROM panel_owner WHERE singleton=1").fetchone()[0]
    os.chmod(path, 0o600)

    def server_permissions(user, server_id):
        with db() as conn:
            override = conn.execute('SELECT role FROM user_server_roles WHERE user_id=? AND server_id=?', (user['id'], server_id or '__existing__')).fetchone()
        if user['id'] == owner_id:
            return set(ROLES[user['role']])
        role = override['role'] if override else user['role'] if user['access_all'] else None
        return (set(ROLES.get(role, set())) - {'users'}) if role else set()

    api.server_permissions = server_permissions
    def clear_server_access(server_id):
        with db() as conn:
            conn.execute('DELETE FROM user_server_roles WHERE server_id=?', (server_id,))
    api.clear_server_access = clear_server_access

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
    def get_admin_labels():
        with db() as conn:
            return {row['identity']: row['name'] for row in conn.execute('SELECT identity,name FROM admin_labels')}
    api.get_admin_labels = get_admin_labels

    @app.post('/api/admin-labels')
    def admin_label_save():
        data = request.get_json(silent=True) or {}
        identity, name = data.get('identity'), data.get('name')
        if not isinstance(identity, str) or not re.fullmatch(r'(?:[0-9]{17}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', identity):
            return jsonify(ok=False, error='Enter a UUID or 17-digit Steam ID'), 400
        if not isinstance(name, str) or len(name) > 80 or any(ord(c) < 32 for c in name):
            return jsonify(ok=False, error='Name must be at most 80 characters without control characters'), 400
        with db() as conn:
            conn.execute('INSERT INTO admin_labels(identity,name) VALUES(?,?) ON CONFLICT(identity) DO UPDATE SET name=excluded.name', (identity.lower(), name.strip()))
        return jsonify(ok=True, name=name.strip())

    def metric_events():
        # Only non-sensitive labels are exposed to dashboard viewers.
        with db() as conn:
            rows = conn.execute("""SELECT id,ts,action,details FROM activity
                WHERE outcome='success' AND ts >= ? AND action IN
                ('api_start','api_stop','api_restart','api_mods_add','api_mods_remove',
                 'api_mods_import','presets_apply') ORDER BY id DESC""",
                (time.time() - 3600,)).fetchall()
        server_id = api.selected_instance().id if api.selected_instance() else None
        return [dict(id=row['id'], ts=row['ts'], action=row['action']) for row in rows
                if json.loads(row['details']).get('server_id') == server_id][:50]

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
        panel_permissions = set(ROLES[user['role']]) if user['id'] == owner_id else (set(ROLES[user['role']]) - {'users'} if user['access_all'] else {'view'}) | ({'users', 'admin_config'} if user['panel_admin'] else set())
        g.panel_permissions = panel_permissions
        g.permissions = panel_permissions
        target = (request.view_args or {}).get('server_id')
        if target is None and request.endpoint in {'account_me','activity_list','admin_label_save'}:
            target = request.headers.get('X-Server-ID')
            if target is None and request.endpoint == 'admin_label_save' and not api.manager_mode:
                target = ''
        server_request = request.path.startswith('/api/') and request.path != '/api/servers' and request.endpoint not in api.PANEL_WIDE_ENDPOINTS
        if target is not None or server_request:
            instance = api.selected_instance()
            target = target if target is not None else instance.id if instance else ''
            g.permissions = server_permissions(dict(user), target)
            if not g.permissions:
                return jsonify(ok=False, error='You do not have access to this server'), 403
            if 'users' in panel_permissions:
                g.permissions.add('users')

        needed = ("view" if request.endpoint == 'api_mods_compare_json' else MUTATIONS.get(request.endpoint)) if request.method == "POST" else {
            'workshop_preview': 'mods',
            'server_provision_status': 'admin_config',
            "notifications_settings": "admin_config",
            "software_status": "admin_config",
            'startup_get':'admin_config', 'players_admins':'admin_config',
            'schedules_list':'admin_config', 'schedules_runs':'admin_config',
            "api_logs": "logs", "users_list": "users", "activity_list": "activity",
            "api_persistence_get": "configure",
            "config_editor_get": "configure",
            "config_backups_list": "admin_config", "config_backup_preview": "admin_config",
            "files_trash": "admin_config", "files_list": "admin_config", "files_content": "admin_config", "files_download": "admin_config",
        }.get(request.endpoint, "view")
        if needed and needed not in g.permissions:
            return jsonify(ok=False, error="Your account does not have permission for this action"), 403
        if hasattr(g, 'instance_selection_error'):
            return g.instance_selection_error
        if request.method == "POST":
            if request.endpoint == "files_upload":
                request.max_content_length = 51 * 1024 * 1024
            if request.is_json and not isinstance(request.get_json(silent=True), dict):
                return jsonify(ok=False, error="Request body must be a JSON object"), 400
            data = request.get_json(silent=True) or {}
            if "id" in data and (type(data["id"]) is not int or data["id"] < 1):
                return jsonify(ok=False, error="Invalid record ID"), 400
            err = api._csrf_required()
            if err:
                return err
            tools = getattr(api, 'operator_tools', None)
            if tools and request.endpoint not in api.PANEL_WIDE_ENDPOINTS and request.endpoint not in {'schedules_save','schedules_change','notifications_save','notifications_test'}:
                selected_id = api.selected_instance().id if api.selected_instance() else ''
                with tools.active_lock:
                    scheduled_busy = selected_id in tools.active
                if scheduled_busy:
                    return jsonify(ok=False,error='A scheduled server operation is running. Wait for it to finish.'),409
            held_lock = preset_lock if request.endpoint in api.PANEL_WIDE_ENDPOINTS or request.endpoint in {'presets_save','schedules_save','schedules_change'} else lock
            if hasattr(held_lock, '_get_current_object'):
                held_lock = held_lock._get_current_object()
            held_lock.acquire()
            g.mutation_lock = held_lock
            if request.endpoint in {"api_start", "api_restart"} and api.software_manager.busy():
                return jsonify(ok=False, error="Wait for the server software job to finish before starting or restarting."), 409
            g.audit_server_config = request.endpoint not in api.PANEL_WIDE_ENDPOINTS and request.endpoint not in getattr(api, 'PROVISIONING_ENDPOINTS', set()) and request.endpoint not in {'notifications_save','notifications_test'}
            g.before_config = api.read_config() if g.audit_server_config else {}
            g.audit_actor = user["username"]
            g.audit_details = {}
            if request.endpoint == "api_persistence_set":
                g.audit_details = {k: data[k] for k in ("enabled", "autoSaveInterval", "saveRetention", "loadSessionSave", "keepSessionSave", "hiveId") if k in data}

    @app.teardown_request
    def release_lock(exc):
        held_lock = g.pop('mutation_lock', None)
        if held_lock is not None:
            held_lock.release()

    @app.after_request
    def record_action(response):
        response.headers["Cache-Control"] = "no-store"
        if request.method == "POST" and request.endpoint in MUTATIONS and hasattr(g, "audit_actor"):
            result = response.get_json(silent=True) or {}
            ok = response.status_code < 400 and result.get("ok") is True
            details = g.audit_details
            if api.selected_instance():
                details['server_id'] = api.selected_instance().id
            if ok:
                before = g.before_config.get("game", {})
                after = api.read_config().get('game', {}) if g.audit_server_config else {}
                old = {m.get("modId"): m for m in before.get("mods", [])}
                new = {m.get("modId"): m for m in after.get("mods", [])}
                if old != new:
                    details["added_mods"] = [new[k] for k in new.keys() - old.keys()]
                    details["removed_mods"] = [old[k] for k in old.keys() - new.keys()]
                    details["updated_mods"] = [new[k] for k in old.keys() & new.keys() if old[k] != new[k]]
                changed = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k) and k != "mods"]
                if changed:
                    details["changed_fields"] = changed  # Never store passwords or config values.
                if request.endpoint == 'config_editor_save':
                    details['changed_fields'] = sorted((request.get_json(silent=True) or {}).get('changes', {}).keys())
            audit(g.audit_actor, request.endpoint, "success" if ok else "failed", details)
        return response

    @app.get("/api/me")
    def account_me():
        if not request.headers.get('X-Server-ID') and not api.manager_mode:
            g.permissions = server_permissions(g.user, '') | (g.panel_permissions & {'users'})
        return jsonify(id=g.user['id'], username=g.user["username"], role=g.user["role"],
                       is_owner=g.user['id'] == owner_id, permissions=sorted(g.permissions), panel_permissions=sorted(g.panel_permissions))

    @app.get('/api/preferences')
    def account_preferences():
        with db() as conn:
            row = conn.execute('SELECT theme FROM user_preferences WHERE user_id=?', (g.user['id'],)).fetchone()
        return jsonify(theme=row['theme'] if row else 'original')

    @app.post('/api/preferences')
    def account_preferences_save():
        theme = (request.get_json(silent=True) or {}).get('theme')
        if theme not in ('original', 'ocean', 'forest', 'light'):
            return jsonify(ok=False, error='Choose a supported theme'), 400
        with db() as conn:
            conn.execute('INSERT INTO user_preferences VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET theme=excluded.theme',
                         (g.user['id'], theme))
        g.audit_details = {'theme':theme}
        return jsonify(ok=True, theme=theme)

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
            rows = conn.execute("SELECT id,username,role,enabled,access_all,panel_admin FROM users ORDER BY username").fetchall()
        with db() as conn:
            assignments = [dict(row) for row in conn.execute('SELECT * FROM user_server_roles')]
        servers = [dict(id=server.id, name=server.name) for server in api.server_registry.list()]
        if not api.manager_mode:
            servers.insert(0, dict(id='__existing__', name='Existing server'))
        return jsonify(users=[dict(row, is_owner=row['id'] == owner_id, access_all=bool(row['access_all']), panel_admin=bool(row['panel_admin']) or row['id']==owner_id,
            server_roles={item['server_id']:item['role'] for item in assignments if item['user_id'] == row['id']}) for row in rows], roles=list(ROLES), servers=servers)

    @app.post("/api/users")
    def users_save():
        data = body()
        username, role = data.get("username", ""), data.get("role", "viewer")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username) or not isinstance(role, str) or role not in ROLES:
            return jsonify(ok=False, error="Use a 3–32 character username (letters, numbers, _, . or -) and a valid role"), 400
        if not isinstance(data.get("enabled", True), bool):
            return jsonify(ok=False, error="Enabled must be true or false"), 400
        enabled = int(data.get("enabled", True))
        access_all, server_roles = data.get('access_all'), data.get('server_roles')
        panel_admin = data.get('panel_admin')
        if panel_admin is not None and type(panel_admin) is not bool:
            return jsonify(ok=False,error='Panel administrator must be true or false'),400
        known_servers = {server.id for server in api.server_registry.list()}
        if not api.manager_mode:
            known_servers.add('__existing__')
        if access_all is not None and type(access_all) is not bool:
            return jsonify(ok=False,error='All-server access must be true or false'),400
        if server_roles is not None and (not isinstance(server_roles,dict) or any(key not in known_servers or not isinstance(value,str) or value not in ROLES for key,value in server_roles.items())):
            return jsonify(ok=False,error='Choose a valid server and role for each assignment'),400

        try:
            with db() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute("SELECT * FROM users WHERE id=?", (data.get("id"),)).fetchone()
                if data.get("id") is not None and not existing:
                    return jsonify(ok=False, error="Account not found"), 404
                if existing:
                    if existing['id'] == owner_id and (access_all is False or server_roles or panel_admin is False):
                        return jsonify(ok=False,error='Owner access cannot be restricted'),400
                    if existing['id'] == owner_id:
                        if g.user['id'] != owner_id:
                            return jsonify(ok=False, error="Only the Owner can change the Owner account"), 403
                        if not enabled or role != 'admin':
                            return jsonify(ok=False, error="The Owner cannot be disabled or demoted"), 400
                    if existing["id"] == g.user["id"] and existing["id"] != owner_id and (not enabled or not (panel_admin if panel_admin is not None else existing["panel_admin"])):
                        return jsonify(ok=False, error="You cannot disable or demote your own administrator account"), 400
                    if existing["panel_admin"] and existing["enabled"] and (not enabled or panel_admin is False):
                        count = conn.execute("SELECT count(*) FROM users WHERE enabled=1 AND (panel_admin=1 OR id=?)",(owner_id,)).fetchone()[0]
                        if count <= 1:
                            return jsonify(ok=False, error="Keep at least one enabled administrator"), 400
                    hashed = password_hash(data["password"]) if data.get("password") else existing["password"]
                    conn.execute("UPDATE users SET username=?,role=?,enabled=?,password=?,version=version+1 WHERE id=?",
                                 (username, role, enabled, hashed, existing["id"]))
                    if existing["id"] == g.user["id"]:
                        session["user_version"] += 1
                else:
                    conn.execute("INSERT INTO users(username,password,role,enabled,access_all) VALUES(?,?,?,?,?)",
                                 (username, password_hash(data.get("password")), role, enabled, int(access_all is True)))
                saved_id = existing['id'] if existing else conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                if panel_admin is not None or not existing or role != existing['role']:
                    conn.execute('UPDATE users SET panel_admin=? WHERE id=?', (int(panel_admin if panel_admin is not None else role == 'admin'),saved_id))
                if existing and access_all is not None:
                    conn.execute('UPDATE users SET access_all=? WHERE id=?', (int(access_all), saved_id))
                if server_roles is not None:
                    conn.execute('DELETE FROM user_server_roles WHERE user_id=?', (saved_id,))
                    conn.executemany('INSERT INTO user_server_roles VALUES(?,?,?)', [(saved_id,key,value) for key,value in server_roles.items()])
        except (ValueError, sqlite3.IntegrityError) as exc:
            return jsonify(ok=False, error="Username is already in use" if isinstance(exc, sqlite3.IntegrityError) else str(exc)), 400
        g.audit_details = {"username": username, "role": role, "enabled": bool(enabled), "access_all":access_all, "server_roles":server_roles, "panel_admin":panel_admin}
        return jsonify(ok=True)

    @app.post("/api/users/delete")
    def users_delete():
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE id=?", (body().get("id"),)).fetchone()
            if not user:
                return jsonify(ok=False, error="Account not found"), 404
            if user['id'] == owner_id:
                return jsonify(ok=False, error="The Owner account cannot be deleted"), 400 if g.user['id'] == owner_id else 403
            if user["id"] == g.user["id"]:
                return jsonify(ok=False, error="You cannot delete your own account"), 400
            if user["panel_admin"] and user["enabled"]:
                count = conn.execute("SELECT count(*) FROM users WHERE enabled=1 AND (panel_admin=1 OR id=?)",(owner_id,)).fetchone()[0]
                if count <= 1:
                    return jsonify(ok=False, error="Keep at least one enabled administrator"), 400
            conn.execute("DELETE FROM user_server_roles WHERE user_id=?", (user["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
        g.audit_details = {"username": user["username"]}
        return jsonify(ok=True)

    @app.get("/api/presets")
    def presets_list():
        with db() as conn:
            rows = conn.execute("SELECT * FROM presets ORDER BY name").fetchall()
        game = api.read_config().get('game', {})
        scenarios = {item['id']: item.get('name') or item['id'] for item in api.all_scenarios_cached()}
        return jsonify(presets=[dict(row, mods=json.loads(row['mods']),
                                     scenario_name=scenarios.get(row['scenario_id'], row['scenario_id']),
                                     active=json.loads(row['mods']) == game.get('mods', []) and
                                     (row['scenario_id'] is None or row['scenario_id'] == game.get('scenarioId'))) for row in rows])

    @app.post("/api/presets")
    def presets_save():
        data = body()
        name = data.get("name", "")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            return jsonify(ok=False, error="Enter a preset name of 1–80 characters"), 400
        game = api.read_config().get('game', {})
        mods, scenario_id = game.get('mods', []), game.get('scenarioId')
        if not isinstance(scenario_id, str) or not scenario_id:
            return jsonify(ok=False, error='Select a scenario before saving a server preset'), 400
        with db() as conn:
            if data.get("id") is not None:
                if not conn.execute("SELECT 1 FROM presets WHERE id=?", (data["id"],)).fetchone():
                    return jsonify(ok=False, error="Preset not found"), 404
            try:
                if data.get("id") is None:
                    conn.execute("INSERT INTO presets(name,mods,scenario_id,updated_by,updated_at) VALUES(?,?,?,?,?)",
                                 (name.strip(), json.dumps(mods), scenario_id, g.user["username"], time.time()))
                else:
                    conn.execute("UPDATE presets SET name=?,mods=?,scenario_id=?,updated_by=?,updated_at=? WHERE id=?",
                                 (name.strip(), json.dumps(mods), scenario_id, g.user["username"], time.time(), data["id"]))
            except sqlite3.IntegrityError:
                return jsonify(ok=False, error="A preset with this name already exists"), 400
        g.audit_details = {"preset": name.strip(), "mod_count": len(mods), "scenario": scenario_id}
        return jsonify(ok=True)

    @app.post("/api/presets/apply")
    def presets_apply():
        with db() as conn:
            row = conn.execute("SELECT * FROM presets WHERE id=?", (body().get("id"),)).fetchone()
        if not row:
            return jsonify(ok=False, error="Preset not found"), 404
        cfg = api.read_config()
        cfg.setdefault("game", {})["mods"] = json.loads(row["mods"])
        if row['scenario_id'] is not None:
            cfg['game']['scenarioId'] = row['scenario_id']
        api.write_config(cfg)
        g.audit_details = {"preset": row["name"], "scenario": row['scenario_id']}
        return jsonify(ok=True, restart_required=api.get_server_pid() is not None)

    @app.get('/api/config/backups')
    def config_backups_list():
        try:
            return jsonify(backups=config_backups.list_backups(api.SERVER_CONFIG))
        except (OSError, ValueError):
            return jsonify(ok=False, error='Unable to list configuration backups'), 500

    @app.get('/api/config/backups/preview')
    def config_backup_preview():
        try:
            current = api.read_config()
            backup = config_backups.load_backup(api.SERVER_CONFIG, request.args.get('name'))
            diff, truncated = config_backups.preview(current, backup)
            return jsonify(diff=diff, truncated=truncated, current_revision=revision(current),
                           backup_revision=revision(backup))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except OSError:
            return jsonify(ok=False, error='Unable to read configuration backup'), 500

    @app.post('/api/config/backups/restore')
    def config_backup_restore():
        data = body()
        try:
            current = api.read_config()
            backup = config_backups.load_backup(api.SERVER_CONFIG, data.get('name'))
            if data.get('current_revision') != revision(current) or data.get('backup_revision') != revision(backup):
                return jsonify(ok=False, error='Configuration or backup changed. Review it again before restoring.'), 409
            if backup == current:
                return jsonify(ok=False, error='The selected backup already matches the current configuration'), 409
            api.write_config(backup)
            g.audit_details = {'backup': data['name']}
            return jsonify(ok=True, restart_required=api.get_server_pid() is not None)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except OSError:
            return jsonify(ok=False, error='Unable to restore configuration backup'), 500

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
            if g.user['id'] == owner_id or 'users' in g.panel_permissions:
                rows = conn.execute("SELECT * FROM activity WHERE (?=0 OR id<?) ORDER BY id DESC LIMIT 51", (before, before)).fetchall()
            else:
                visible = [server.id for server in api.server_registry.list() if server_permissions(g.user,server.id)]
                if not api.manager_mode and server_permissions(g.user,''):
                    visible.append(None)
                marks = ','.join('?' for _ in visible) or 'NULL'
                rows = conn.execute(f"SELECT * FROM activity WHERE (?=0 OR id<?) AND (actor=? OR json_extract(details,'$.server_id') IN ({marks}) OR (? AND json_extract(details,'$.server_id') IS NULL AND action NOT IN ('users_save','users_delete','account_password'))) ORDER BY id DESC LIMIT 51",
                    (before,before,g.user['username'],*visible,None in visible)).fetchall()
        return jsonify(events=[dict(row, details=json.loads(row["details"])) for row in rows[:50]],
                       next_before=rows[49]["id"] if len(rows) > 50 else None)

    query = api.instance_scoped('player_query', player_query.PlayerQuery, player_query.PlayerQuery())

    @app.get("/api/players")
    def players_list():
        return jsonify(player_snapshot())

    def player_snapshot():
        if not api.get_server_pid():
            query.clear()
            return dict(available=True, players=[], message="Server is offline")
        snapshot = query.read(api.read_config().get("rcon", {}), api._cfg)
        tools = getattr(api, 'operator_tools', None)
        if tools:
            tools.store.observe(api.selected_instance().id if api.selected_instance() else '',snapshot)
        return snapshot

    api.player_snapshot = player_snapshot

    @app.post('/api/rcon/command')
    def rcon_command():
        data = request.get_json(silent=True) or {}
        command = data.get('command')
        if not isinstance(command, str) or not 1 <= len(command.strip()) <= 256 or any(ord(char) < 32 for char in command):
            return jsonify(ok=False, error='Enter one RCON command (up to 256 characters).'), 400
        command = command.strip()
        if command.lower().split()[0] in {'#login', '#logout', '@logout'}:
            return jsonify(ok=False, error='Authentication commands are managed by the panel.'), 400
        if not api.get_server_pid():
            return jsonify(ok=False, error='The game server is offline.'), 409
        config = api.read_config().get('rcon') or {}
        settings = api._cfg
        if config.get('permission', 'monitor') != 'admin':
            return jsonify(ok=False, error='Set RCON permission to admin in Server config and restart the game server.'), 409
        password = settings.get('RCON_PASSWORD') or config.get('password')
        if not password:
            return jsonify(ok=False, error='Configure an RCON password first.'), 409
        host = settings.get('RCON_HOST') or config.get('address') or '127.0.0.1'
        if host == '0.0.0.0':
            host = '127.0.0.1'
        try:
            port = int(settings.get('RCON_PORT') or config.get('port', 19999))
            if not 1 <= port <= 65535:
                raise ValueError('Invalid RCON port')
            output = player_query.query_command(host, port, password, command)
            g.audit_details = {'command': command.split()[0]}
            return jsonify(ok=True, output=output[:65536])
        except (OSError, TimeoutError, ValueError) as error:
            return jsonify(ok=False, error=str(error)), 502
