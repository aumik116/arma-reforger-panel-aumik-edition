"""
Arma Reforger Panel
https://github.com/aumik116/arma-reforger-panel-aumik-edition
Original project by Mateusz Gołębiewski:
https://github.com/mateuszgolebiewski-code/arma-reforger-panel

Developed with AI assistance using OpenAI Codex. Fork modifications:
  - Bcrypt-hashed admin password + constant-time verification + rate limiting
  - CSRF protection on state-changing routes
  - Persistent SECRET_KEY (sessions survive panel restart)
  - Bulk mod import via pasted JSON array or uploaded JSON file
  - Auto-discovery of scenarios from addon metadata and resource databases
"""

from flask import Flask, request, jsonify, session, redirect, Response, send_from_directory, g
import bcrypt
import hmac
import re
import secrets
import subprocess
import os
import json
import threading
import time
import glob
import sys
import tempfile
from runtime_ops import ProcessMetrics, TrafficMetrics, HostMetrics, ServerFPS, read_game_telemetry, read_console, read_cpu_frequency
from network_status import udp_listener_status

# ─── CONFIG ───────────────────────────────────────────────────────────────────

def load_env(path="config.env"):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_cfg = load_env(os.path.join(_BASE_DIR, "config.env"))

# Backwards-compatible password handling: prefer the bcrypt hash; if only the
# plaintext PANEL_PASSWORD is set (old configs), hash it in-memory at startup.
PANEL_PASSWORD_HASH = _cfg.get("PANEL_PASSWORD_HASH", "").strip()
_LEGACY_PLAINTEXT   = _cfg.get("PANEL_PASSWORD", "").strip()
if not PANEL_PASSWORD_HASH and _LEGACY_PLAINTEXT:
    PANEL_PASSWORD_HASH = bcrypt.hashpw(_LEGACY_PLAINTEXT.encode(), bcrypt.gensalt()).decode()
    print("[panel] WARNING: config.env uses legacy plaintext PANEL_PASSWORD. "
          "Re-run install.sh --update or replace it with PANEL_PASSWORD_HASH=...", flush=True)
if not PANEL_PASSWORD_HASH:
    PANEL_PASSWORD_HASH = bcrypt.hashpw(b"changeme", bcrypt.gensalt()).decode()
    print("[panel] WARNING: no panel password set. Defaulting to 'changeme'.", flush=True)

PANEL_PORT     = int(_cfg.get("PANEL_PORT", 8888))
SERVER_DIR     = _cfg.get("SERVER_DIR",    "/home/arma/server")
SERVER_CONFIG  = _cfg.get("SERVER_CONFIG", "/home/arma/server/config.json")
LOG_DIR        = _cfg.get("LOG_DIR",       "/home/arma/.config/ArmaReforger/logs")
WORKSHOP_DIR   = _cfg.get("WORKSHOP_DIR",  os.path.expanduser("~/.local/share/Arma Reforger/addons"))
# Where Reforger writes session saves. The real layout produced by the server
# under install.sh defaults is `{LOG_DIR_parent}/profile/.save/`, e.g.
# `/home/arma/.config/ArmaReforger/profile/.save/{game,playersave,settings}/`.
# Override with PROFILE_DIR in config.env if your install differs.
PROFILE_DIR    = _cfg.get(
    "PROFILE_DIR",
    os.path.join(os.path.dirname(LOG_DIR.rstrip("/")) or "/home/arma/.config/ArmaReforger", "profile"),
)
SERVER_BINARY  = "./ArmaReforgerServer"
MAX_FPS        = _cfg.get("MAX_FPS", "").strip()

def build_server_args():
    """Build the panel launch command from env and the native game settings."""
    args = ["-config", SERVER_CONFIG, "-logStats", "1000"]
    try:
        args.extend(_native_persistence_startup_args(read_config()))
    except Exception:
        # A broken config is reported by the normal configuration/startup path;
        # do not prevent diagnostics from constructing a safe base command.
        pass
    if MAX_FPS:
        args.append(f"-maxFPS={MAX_FPS}")
    return args

# Persistent secret key so sessions survive panel restarts.
_SECRET_FILE = os.path.join(_BASE_DIR, ".panel-secret")
def _load_or_create_secret():
    try:
        if os.path.exists(_SECRET_FILE):
            with open(_SECRET_FILE, "rb") as f:
                data = f.read().strip()
                if len(data) >= 32:
                    return data
    except OSError:
        pass
    data = secrets.token_bytes(48)
    try:
        with open(_SECRET_FILE, "wb") as f:
            f.write(data)
        os.chmod(_SECRET_FILE, 0o600)
    except OSError as e:
        print(f"[panel] WARNING: could not persist session secret ({e}); using ephemeral one.", flush=True)
    return data

app = Flask(__name__, static_folder='static')
app.secret_key = _load_or_create_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=False,  # set True if you put HTTPS in front
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # 2 MB cap on uploads
)


# ─── SECURITY HELPERS ─────────────────────────────────────────────────────────

def _client_ip():
    # Forwarded headers are client-controlled unless a trusted proxy validates them.
    return request.remote_addr or "unknown"


_LOGIN_BUCKETS: dict[str, list[float]] = {}
_LOGIN_WINDOW_SEC = 60.0
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCK = threading.Lock()

def _login_rate_ok(ip: str) -> bool:
    now = time.monotonic()
    with _LOGIN_LOCK:
        for key in list(_LOGIN_BUCKETS):
            bucket = [t for t in _LOGIN_BUCKETS[key] if now - t < _LOGIN_WINDOW_SEC]
            if bucket:
                _LOGIN_BUCKETS[key] = bucket
            else:
                del _LOGIN_BUCKETS[key]
        bucket = _LOGIN_BUCKETS.setdefault(ip, [])
        if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
            return False
        bucket.append(now)
        return True


def _verify_password(plain: str) -> bool:
    if not plain:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), PANEL_PASSWORD_HASH.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _ensure_csrf() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf"] = tok
    return tok


def _csrf_required() -> Response | None:
    """Check CSRF token from header or body. Returns an error Response or None."""
    expected = session.get("csrf")
    supplied = (
        request.headers.get("X-CSRF-Token", "")
        or (request.get_json(silent=True) or {}).get("_csrf", "")
        or request.form.get("_csrf", "")
    )
    if not isinstance(expected, str) or not isinstance(supplied, str) or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify({"ok": False, "error": "CSRF token invalid"}), 403
    return None


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp

# ─── MISSIONS ─────────────────────────────────────────────────────────────────
#
# Hardcoded Bohemia/vanilla scenarios used as a fallback when the dedicated
# server install can't be scanned (e.g. SERVER_DIR misconfigured). When the
# server install IS scannable, dynamic discovery from its addons folder
# supersedes this list.

AVAILABLE_MISSIONS = [
    # Everon
    {"id": "{ECC61978EDCC2B5A}Missions/23_Campaign.conf",              "name": "Conflict — Everon"},
    {"id": "{C700DB41F0C546E1}Missions/23_Campaign_NorthCentral.conf", "name": "Conflict — Northern Everon"},
    {"id": "{28802845ADA64D52}Missions/23_Campaign_SWCoast.conf",      "name": "Conflict — Southern Everon"},
    {"id": "{94992A3D7CE4FF8A}Missions/23_Campaign_Western.conf",      "name": "Conflict — Western Everon"},
    {"id": "{FDE33AFE2ED7875B}Missions/23_Campaign_Montignac.conf",    "name": "Conflict — Montignac"},
    {"id": "{0220741028718E7F}Missions/23_Campaign_HQC_Everon.conf",   "name": "Conflict: HQ Commander — Everon"},
    {"id": "{59AD59368755F41A}Missions/21_GM_Eden.conf",               "name": "Game Master — Everon"},
    {"id": "{DFAC5FABD11F2390}Missions/26_CombatOpsEveron.conf",       "name": "Combat Ops — Everon"},
    # Capture & Hold
    {"id": "{3F2E005F43DBD2F8}Missions/CAH_Briars_Coast.conf",         "name": "Capture & Hold — Briars Coast"},
    {"id": "{F1A1BEA67132113E}Missions/CAH_Castle.conf",               "name": "Capture & Hold — Montfort Castle"},
    {"id": "{589945FB9FA7B97D}Missions/CAH_Concrete_Plant.conf",       "name": "Capture & Hold — Concrete Plant"},
    {"id": "{9405201CBD22A30C}Missions/CAH_Factory.conf",              "name": "Capture & Hold — Almara Factory"},
    {"id": "{1CD06B409C6FAE56}Missions/CAH_Forest.conf",               "name": "Capture & Hold — Simon's Wood"},
    {"id": "{7C491B1FCC0FF0E1}Missions/CAH_LeMoule.conf",              "name": "Capture & Hold — Le Moule"},
    {"id": "{6EA2E454519E5869}Missions/CAH_Military_Base.conf",        "name": "Capture & Hold — Camp Blake"},
    # Showcase / SP
    {"id": "{C47A1A6245A13B26}Missions/SP01_ReginaV2.conf",            "name": "Elimination"},
    {"id": "{0648CDB32D6B02B3}Missions/SP02_AirSupport.conf",          "name": "Air Support"},
    # Arland
    {"id": "{C41618FD18E9D714}Missions/23_Campaign_Arland.conf",       "name": "Conflict — Arland"},
    {"id": "{68D1240A11492545}Missions/23_Campaign_HQC_Arland.conf",   "name": "Conflict: HQ Commander — Arland"},
    {"id": "{2BBBE828037C6F4B}Missions/22_GM_Arland.conf",             "name": "Game Master — Arland"},
    {"id": "{DAA03C6E6099D50F}Missions/24_CombatOps.conf",             "name": "Combat Ops — Arland"},
    # Kolguyev
    {"id": "{F45C6C15D31252E6}Missions/27_GM_Cain.conf",               "name": "Game Master — Kolguyev"},
    {"id": "{BB5345C22DD2B655}Missions/23_Campaign_HQC_Cain.conf",     "name": "Conflict: HQ Commander — Kolguyev"},
    {"id": "{CB347F2F10065C9C}Missions/CombatOpsCain.conf",            "name": "Combat Ops — Kolguyev"},
    {"id": "{2B4183DF23E88249}Missions/CAH_Morton.conf",               "name": "Capture & Hold — Morton"},
    # Operation Omega
    {"id": "{10B8582BAD9F7040}Missions/Scenario01_Intro.conf",         "name": "Operation Omega 01: Over The Hills And Far Away"},
    {"id": "{1D76AF6DC4DF0577}Missions/Scenario02_Steal.conf",         "name": "Operation Omega 02: Radio Check"},
    {"id": "{D1647575BCEA5A05}Missions/Scenario03_Villa.conf",         "name": "Operation Omega 03: Light In The Dark"},
    {"id": "{6D224A109B973DD8}Missions/Scenario04_Sabotage.conf",      "name": "Operation Omega 04: Red Silence"},
    {"id": "{FA2AB0181129CB16}Missions/Scenario05_Hill.conf",          "name": "Operation Omega 05: Cliffhanger"},
]
# Add a "source" tag so the UI can group by origin.
for _m in AVAILABLE_MISSIONS:
    _m.setdefault("source", "vanilla")


# Friendly display names for scenarios discovered via .rdb (which only gives
# us the filename, not the publisher's display name). Used as an override when
# the .rdb scan finds a known scenario ID. Anything not listed here falls back
# to the cleaned-up filename derived from the path.
_SCENARIO_NAME_OVERRIDES = {
    # RHS — Status Quo
    "{AAD43C10045857C1}Missions/RHS_Conflict.conf":              ("Conflict — Everon (RHS)",                 64),
    "{B694A77592CB69E0}Missions/RHS_ConflictWithoutAIs.conf":    ("Conflict — Everon, no AI (RHS)",          64),
    "{9909DB7ECEA05535}Missions/RHS_Conflict_East.conf":         ("Conflict — Everon East (RHS)",            40),
    "{2F5DD5ACC14120A9}Missions/RHS_Conflict_NorthCentral.conf": ("Conflict — Everon North Central (RHS)",   64),
    "{57B154A20B8B283E}Missions/RHS_Conflict_SWCoast.conf":      ("Conflict — Everon SW Coast (RHS)",        64),
    "{367A7800D147878A}Missions/RHS_Conflict_West.conf":         ("Conflict — Everon West (RHS)",            40),
    "{7577640CD42A00BD}Missions/RHS_Conflict_Arland.conf":       ("Conflict — Arland (RHS)",                 64),
    "{C5EAD55037EB4751}Missions/RHS_CombatOps_MSV.conf":         ("Combat Ops — Arland, MSV vs FIA (RHS)",   16),
    "{D10B11A71A36FCF5}Missions/RHS_CombatOps_USMC_vs_MSV.conf": ("Combat Ops — Arland, USMC vs MSV (RHS)",  16),
    "{68A6FBF43B801FF6}Missions/RHS_ShowcaseBasic.conf":         ("Showcase Mission (RHS)",                   6),
    "{217436B52D34E4BD}Missions/RHS_Showcase_GM.conf":           ("Showcase Mission, Game Master (RHS)",     36),
}


# ─── SCENARIO AUTO-DISCOVERY (workshop meta) ─────────────────────────────────
#
# Reforger workshop mods unpack to <WORKSHOP_DIR>/<Name>_<HEXID>/. Each addon
# ships a `meta` file (UTF-8-with-BOM JSON) that contains the workshop
# metadata, including a `versions[].scenarios[]` array. Each scenario entry
# is a dict with at least `name` and `gameId` (the full {HEX16}Missions/...
# .conf identifier we need). This is far more reliable than scanning the
# binary .pak file — and the `meta` file is tiny, so the scan is instant.
#
# We cache results per addon dir by `meta` mtime to avoid re-reading the same
# file if nothing changed.

_SCENARIO_GAME_ID_RE = re.compile(r'^\{[0-9A-Fa-f]{16}\}.+\.conf$')
_SCAN_CACHE_FILE = os.path.join(_BASE_DIR, ".scenario-cache.json")


def _scan_cache_load():
    try:
        with open(_SCAN_CACHE_FILE) as f:
            data = json.load(f)
        return data.get("mods", {}), data.get("mtimes", {})
    except (OSError, json.JSONDecodeError):
        return {}, {}


def _scan_cache_save(mods, mtimes):
    try:
        with open(_SCAN_CACHE_FILE, "w") as f:
            json.dump({"mods": mods, "mtimes": mtimes, "saved_at": time.time()}, f)
    except OSError as e:
        print(f"[panel] WARNING: could not write scenario cache: {e}", flush=True)


_SCAN_LOCK = threading.Lock()
_LAST_SCAN_RESULT: dict = {"scenarios": [], "diag": None, "ts": 0.0}


def _candidate_addon_roots():
    """Locations to scan for addons. Each entry is (path, is_vanilla).
    `is_vanilla=True` means anything found there is Bohemia-shipped game
    content (the dedicated server's bundled addons), not a workshop mod."""
    home = os.path.dirname(SERVER_DIR.rstrip("/")) if SERVER_DIR else os.path.expanduser("~")
    if not home or home == "/":
        home = os.path.expanduser("~arma") if os.path.isdir("/home/arma") else os.path.expanduser("~")

    roots = []
    # Workshop mod dirs (downloaded via SteamCMD / the game)
    if WORKSHOP_DIR:
        roots.append((WORKSHOP_DIR, False))
    roots.extend([
        (os.path.join(home, ".local/share/Arma Reforger/profile/addons"), False),
        (os.path.join(home, ".local/share/Arma Reforger/addons"),         False),
        (os.path.join(home, ".config/Arma Reforger/addons"),              False),
        (os.path.join(home, ".config/ArmaReforger/addons"),               False),
    ])
    # Bohemia-shipped game content (Conflict, GM, CAH, Operation Omega, etc.)
    if SERVER_DIR:
        roots.extend([
            (os.path.join(SERVER_DIR, "Addons"), True),
            (os.path.join(SERVER_DIR, "addons"), True),
            (SERVER_DIR,                          True),  # falls back to walking server install
        ])
    seen, out = set(), []
    for path, vanilla in roots:
        if path and path not in seen and os.path.isdir(path):
            seen.add(path)
            out.append((path, vanilla))
    return out


def _find_addons(root, max_depth=4):
    """Walk `root` up to `max_depth` levels and yield (addon_dir, meta_or_None,
    rdb_or_None) for every directory that looks like a Reforger addon (i.e.
    contains a `meta` JSON, a `resourceDatabase.rdb`, or an `addon.gproj`)."""
    if not root or not os.path.isdir(root):
        return
    root = os.path.abspath(root)
    base_depth = root.rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        depth = dirpath.rstrip("/").count("/") - base_depth
        if depth >= max_depth:
            dirnames[:] = []
        meta_file = os.path.join(dirpath, "meta") if "meta" in filenames else None
        rdb_file = os.path.join(dirpath, "resourceDatabase.rdb") if "resourceDatabase.rdb" in filenames else None
        gproj = "addon.gproj" in filenames
        if meta_file or rdb_file or gproj:
            # Don't descend into addon dirs further (their inner files aren't more addons)
            dirnames[:] = []
            if meta_file or rdb_file:
                yield dirpath, meta_file, rdb_file


def _addon_name_from_gproj(addon_dir):
    """Pull a friendly display name from addon.gproj (TITLE or ID field)."""
    gproj = os.path.join(addon_dir, "addon.gproj")
    if not os.path.isfile(gproj):
        return None
    try:
        with open(gproj, encoding="utf-8", errors="replace") as f:
            text = f.read(2048)
    except OSError:
        return None
    m = re.search(r'TITLE\s+"([^"]+)"', text) or re.search(r'ID\s+"([^"]+)"', text)
    return m.group(1).strip() if m else None


_RDB_PATH_RE = re.compile(rb'Missions/[A-Za-z0-9_./\-]+\.conf')

def _scenarios_from_rdb(rdb_path, source_label):
    """Fallback: parse `resourceDatabase.rdb` for scenario records.

    The dedicated-server workshop downloader strips `meta.versions[].scenarios`
    on Linux (just an empty list), so we can't rely on the JSON for those.
    The .rdb file ships next to data.pak in every addon and contains the
    asset directory in a simple length-prefixed binary format. Each scenario
    asset record looks like:
        <4-byte LE length>  <path bytes>  <\\0>  <6-byte padding>  <8-byte LE GUID>  …
    where the LE length equals len(path) + 1 (counting the null terminator).
    The 8-byte GUID is little-endian, so we reverse it for the {HEX16} display.

    We rely on the path-prefix `Missions/` to filter for scenarios, then
    validate each candidate by checking the length prefix matches; this
    rejects stray substring hits in unrelated records.
    """
    try:
        with open(rdb_path, "rb") as f:
            data = f.read()
    except OSError:
        return []

    out = []
    seen = set()
    for m in _RDB_PATH_RE.finditer(data):
        ps, pe = m.start(), m.end()
        if ps < 4:
            continue
        path_len_field = int.from_bytes(data[ps - 4:ps], "little")
        if path_len_field != (pe - ps) + 1:
            continue  # not a length-prefixed record — likely a substring inside something else
        if pe >= len(data) or data[pe] != 0:
            continue
        guid_start = pe + 7  # 1 null byte + 6-byte padding
        if guid_start + 8 > len(data):
            continue
        guid_bytes = data[guid_start:guid_start + 8]
        # Reject obviously-bogus GUIDs (all-zero / all-0xFF fillers).
        if guid_bytes == b"\x00" * 8 or guid_bytes == b"\xff" * 8:
            continue
        guid_hex = guid_bytes[::-1].hex().upper()  # little-endian → big-endian display
        path_str = m.group(0).decode("ascii", errors="replace")
        sid = "{" + guid_hex + "}" + path_str
        if sid in seen:
            continue
        seen.add(sid)
        out.append({
            "id": sid,
            "name": path_str.split("/")[-1].replace(".conf", ""),
            "description": "",
            "player_count": None,
            "source": source_label or "mod",
        })
    return out


def _scenarios_from_meta(meta_path):
    """Parse a workshop `meta` file and return a list of scenario dicts:
       [{id, name, description, player_count, source}, ...]
       The `meta` file is UTF-8 with BOM and contains the workshop publisher
       metadata. Scenarios appear under meta.versions[].scenarios[].
    """
    try:
        with open(meta_path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return [], None

    m = (data.get("meta") or {})
    mod_name = (m.get("name") or "").strip()

    # Pull scenarios from the latest version (versions[0]) — that's what's installed.
    versions = m.get("versions") or []
    raw_scenarios = []
    if versions and isinstance(versions, list):
        raw_scenarios = versions[0].get("scenarios") or []
    if not raw_scenarios:
        # Some older meta layouts have a top-level scenarios array.
        raw_scenarios = m.get("scenarios") or []
    if not isinstance(raw_scenarios, list):
        return [], mod_name

    out = []
    for s in raw_scenarios:
        if not isinstance(s, dict):
            continue
        sid = (s.get("gameId") or "").strip()
        if not sid or not _SCENARIO_GAME_ID_RE.match(sid):
            continue
        out.append({
            "id":           sid,
            "name":         (s.get("name") or sid.split("/")[-1].replace(".conf", "")).strip(),
            "description":  (s.get("description") or "").strip()[:300],
            "player_count": s.get("playerCount") if isinstance(s.get("playerCount"), int) else None,
            "source":       mod_name or "mod",
        })
    return out, mod_name


def _apply_name_override(scenario):
    """If we have a curated friendly name for this scenario ID, use it."""
    override = _SCENARIO_NAME_OVERRIDES.get(scenario["id"])
    if override:
        scenario["name"] = override[0]
        if override[1] and not scenario.get("player_count"):
            scenario["player_count"] = override[1]
    return scenario


def _discover_locked(force_rescan):
    """Actual scan work. Caller must hold _SCAN_LOCK."""
    diag = {"candidates_tried": [], "addons_scanned": 0,
            "mods_with_scenarios": 0, "scenarios_total": 0, "errors": []}

    cache_mods, cache_mtimes = ({}, {}) if force_rescan else _scan_cache_load()
    fresh_mods, fresh_mtimes = {}, {}

    seen_addon_dirs = set()
    addons_scanned = 0

    for root, is_vanilla in _candidate_addon_roots():
        diag["candidates_tried"].append({"path": root, "vanilla": is_vanilla})
        for addon_dir, meta_path, rdb_path in _find_addons(root):
            real_dir = os.path.realpath(addon_dir)
            if real_dir in seen_addon_dirs:
                continue
            seen_addon_dirs.add(real_dir)
            addons_scanned += 1

            # Cache key tracks both files so we re-scan if either changes.
            cache_key = real_dir
            try:
                meta_mtime = os.path.getmtime(meta_path) if meta_path else 0
                rdb_mtime  = os.path.getmtime(rdb_path) if rdb_path else 0
                mtime = max(meta_mtime, rdb_mtime)
            except OSError as e:
                diag["errors"].append(f"{cache_key}: stat failed ({e})")
                continue

            if cache_mtimes.get(cache_key) == mtime and cache_key in cache_mods:
                fresh_mods[cache_key] = cache_mods[cache_key]
                fresh_mtimes[cache_key] = mtime
                continue

            scenarios = []
            mod_name = None
            # 1. Try the workshop meta JSON first (gives us the publisher's
            #    display names + player counts when populated).
            if meta_path:
                scenarios, mod_name = _scenarios_from_meta(meta_path)
            # 2. Fall back to the .rdb scan when the meta has no scenarios
            #    (Linux dedi strips them) or when there's no meta at all
            #    (Bohemia's bundled vanilla addons).
            if not scenarios and rdb_path:
                if not mod_name:
                    mod_name = _addon_name_from_gproj(addon_dir) or os.path.basename(addon_dir)
                source = "vanilla" if is_vanilla else mod_name
                scenarios = _scenarios_from_rdb(rdb_path, source)
            # 3. Force-tag everything found in the server install dir as vanilla.
            if is_vanilla:
                for s in scenarios:
                    s["source"] = "vanilla"
            # 4. Single-scenario mods are usually named after their scenario.
            #    The .rdb fallback only knows the filename (e.g.
            #    "MontfordFortress"), but the workshop name is the friendly
            #    one ("Fortress"). When a mod publishes exactly one scenario
            #    and we have an addon display name, prefer that — unless an
            #    explicit override is already in place.
            if len(scenarios) == 1 and not is_vanilla and mod_name:
                if scenarios[0]["id"] not in _SCENARIO_NAME_OVERRIDES:
                    scenarios[0]["name"] = mod_name
            # 5. Apply our curated friendly-name overrides (mainly RHS).
            for s in scenarios:
                _apply_name_override(s)

            if scenarios:
                fresh_mods[cache_key] = scenarios
            fresh_mtimes[cache_key] = mtime

    _scan_cache_save(fresh_mods, fresh_mtimes)

    flat = []
    for sids in fresh_mods.values():
        flat.extend(sids)
    diag["addons_scanned"] = addons_scanned
    diag["mods_with_scenarios"] = len(fresh_mods)
    diag["scenarios_total"] = len(flat)
    # Back-compat fields the old UI knew about
    diag["workshop_dir"] = "; ".join(p for p, _ in _candidate_addon_roots()) or None
    diag["metas_found"]  = addons_scanned
    return flat, diag


def discover_mod_scenarios(force_rescan=False):
    """Return (scenarios, diag).
       Lock-protected so concurrent /api/status polls or rescan clicks can't
       launch overlapping scans.  Non-rescan callers get the cached result
       without doing any disk I/O if a scan is already in progress."""
    if not force_rescan:
        # Cheap path: just read the on-disk cache.
        cache_mods, _mtimes = _scan_cache_load()
        if cache_mods:
            flat = []
            for sids in cache_mods.values():
                flat.extend(sids)
            diag = {"workshop_dir": None, "paks_found": len(cache_mods),
                    "scenarios_total": len(flat), "from_cache": True}
            return flat, diag

    if not _SCAN_LOCK.acquire(blocking=force_rescan):
        # Scan in progress and we don't want to block — return whatever we have.
        return _LAST_SCAN_RESULT["scenarios"], (_LAST_SCAN_RESULT["diag"] or {"busy": True})
    try:
        scenarios, diag = _discover_locked(force_rescan)
        _LAST_SCAN_RESULT["scenarios"] = scenarios
        _LAST_SCAN_RESULT["diag"] = diag
        _LAST_SCAN_RESULT["ts"] = time.time()
        return scenarios, diag
    finally:
        _SCAN_LOCK.release()


def cached_scenarios():
    """Cheap read for /api/status — never triggers a fresh scan."""
    cache_mods, _mtimes = _scan_cache_load()
    flat = []
    for sids in cache_mods.values():
        flat.extend(sids)
    return flat


def all_scenarios(force_rescan=False):
    """Vanilla list + auto-discovered, deduped by id (vanilla wins for naming).
       Returns (list, diag)."""
    by_id = {}
    for s in AVAILABLE_MISSIONS:
        by_id[s["id"]] = dict(s)
    discovered, diag = discover_mod_scenarios(force_rescan=force_rescan)
    for s in discovered:
        by_id.setdefault(s["id"], dict(s))
    out = list(by_id.values())
    out.sort(key=lambda s: (s["source"] != "vanilla", s["source"], s["name"]))
    return out, diag


def all_scenarios_cached():
    """Like all_scenarios() but never scans — used by /api/status hot path."""
    by_id = {}
    for s in AVAILABLE_MISSIONS:
        by_id[s["id"]] = dict(s)
    for s in cached_scenarios():
        by_id.setdefault(s["id"], dict(s))
    out = list(by_id.values())
    out.sort(key=lambda s: (s["source"] != "vanilla", s["source"], s["name"]))
    return out


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_server_pid():
    try:
        expected = os.path.realpath(os.path.join(SERVER_DIR, SERVER_BINARY))
        for entry in glob.glob('/proc/[0-9]*/exe'):
            try:
                if os.path.realpath(entry) == expected:
                    return int(entry.split('/')[2])
            except OSError:
                continue
        return None
    except Exception:
        return None

def get_process_uptime(pid):
    try:
        r = subprocess.run(["ps", "-o", "etimes=", "-p", str(pid)], capture_output=True, text=True)
        return int(r.stdout.strip())
    except Exception:
        return 0

def format_uptime(seconds):
    if seconds < 60:    return f"{seconds}s"
    if seconds < 3600:  return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

def get_cpu_count():
    try:
        r = subprocess.run(["nproc"], capture_output=True, text=True)
        return max(1, int(r.stdout.strip()))
    except Exception:
        return 1

_process_metrics = ProcessMetrics()
_traffic_metrics = TrafficMetrics()
_host_metrics = HostMetrics()
_server_fps = ServerFPS()


def get_cpu_ram(pid):
    try:
        return _process_metrics.read(pid)
    except Exception:
        return 0.0, 0.0

def get_system_ram():
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {l.split()[0].rstrip(":"): int(l.split()[1]) for l in lines if len(l.split()) >= 2}
        total = round(mem["MemTotal"] / 1024, 1)
        used  = round((mem["MemTotal"] - mem["MemAvailable"]) / 1024, 1)
        return used, total
    except Exception:
        return 0, 0

def get_latest_log():
    try:
        dirs = sorted(glob.glob(f"{LOG_DIR}/logs_*"), reverse=True)
        if not dirs:
            return None
        path = os.path.join(dirs[0], "console.log")
        return path if os.path.exists(path) else None
    except Exception:
        return None

class ConfigReadError(RuntimeError):
    pass


@app.errorhandler(ConfigReadError)
def config_read_error(error):
    return jsonify(ok=False, error=str(error)), 503


def read_config():
    try:
        with open(SERVER_CONFIG, encoding='utf-8-sig') as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict) or not isinstance(cfg.get('game'), dict):
            raise ValueError('Expected a configuration object with a game object')
        return cfg
    except (OSError, ValueError) as exc:
        raise ConfigReadError('Server configuration cannot be read. Repair the file before saving changes.') from exc

def write_config(cfg):
    from config_editor import order_config
    from config_backups import backup_current
    cfg = order_config(cfg)
    # Replace atomically so readers never see a partially-written configuration.
    folder = os.path.dirname(os.path.abspath(SERVER_CONFIG))
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".panel-config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent="\t")
        if os.path.exists(SERVER_CONFIG):
            os.chmod(temporary, os.stat(SERVER_CONFIG).st_mode & 0o777)
            backup_current(SERVER_CONFIG)
        os.replace(temporary, SERVER_CONFIG)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

# ─── PERSISTENCE ─────────────────────────────────────────────────────────────
#
# Reforger uses scenario-supported save types and JSON persistence defaults.
# Native save-point layouts can include nested directories and binary payloads.

_SAVE_SUBDIRS = (".save", "save", "saves")

def _get_persistence_block(cfg):
    """Read the persistence block at its real schema location:
    `game.gameProperties.persistence`. Returns the block dict or None."""
    gp = (cfg.get("game") or {}).get("gameProperties") or {}
    block = gp.get("persistence")
    return block if isinstance(block, dict) else None

def _set_persistence_block(cfg, block):
    """Write `block` (a dict) at game.gameProperties.persistence, or remove it
    if `block` is None. Also pops any legacy top-level `persistence` key — the
    1.6 server schema rejects it, so its presence is always a bug."""
    cfg.pop("persistence", None)
    gp = cfg.setdefault("game", {}).setdefault("gameProperties", {})
    if block is None:
        gp.pop("persistence", None)
    else:
        gp["persistence"] = block

def _persistence_enabled(cfg=None):
    if cfg is None:
        cfg = read_config()
    return cfg.get('game', {}).get('gameProperties', {}).get('missionHeader', {}).get('m_eSaveTypes') != 0

def _native_persistence_startup_args(cfg):
    """Return compatibility flags for the game's built-in save system.

    The JSON block is authoritative. The flags make panel-launched servers
    behave like older dedicated-server installs while respecting an explicit
    load/keep setting and a mission save-types disable override.
    """
    properties = (cfg.get('game') or {}).get('gameProperties') or {}
    if (properties.get('missionHeader') or {}).get('m_eSaveTypes') == 0:
        return []
    persistence = properties.get('persistence') or {}
    args = []
    if persistence.get('loadSessionSave', True):
        args.append('-loadSessionSave')
    if persistence.get('keepSessionSave', False):
        args.append('-keepSessionSave')
    return args

# Subdirs the flush button targets. `settings/` is intentionally preserved
# because it holds non-session config the server expects to regenerate from.
_FLUSHABLE_SUBDIRS = ("game", "playersave")

def _save_root():
    for sub in _SAVE_SUBDIRS:
        p = os.path.join(PROFILE_DIR, sub)
        if os.path.isdir(p):
            return p
    return os.path.join(PROFILE_DIR, ".save")  # canonical Linux dedicated path

def _scan_dir(path):
    """Return {count, bytes, newest} for files under `path`, or zeros if absent."""
    if not os.path.isdir(path):
        return {"count": 0, "bytes": 0, "newest": None}
    count = 0
    total = 0
    newest = 0.0
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            try:
                st = os.stat(os.path.join(dirpath, fn))
            except OSError:
                continue
            count += 1
            total += st.st_size
            if st.st_mtime > newest:
                newest = st.st_mtime
    return {"count": count, "bytes": total, "newest": newest or None}

def _scan_saves():
    root = _save_root()
    if not os.path.isdir(root):
        return {"path": root, "exists": False, "total": {"count": 0, "bytes": 0, "newest": None}, "buckets": {}}
    buckets = {name: _scan_dir(os.path.join(root, name)) for name in ("game", "playersave", "settings")}
    all_files = _scan_dir(root)
    native_meta = []
    for path in glob.glob(os.path.join(root, "**", "meta-info.json"), recursive=True):
        try:
            if os.path.isfile(path): native_meta.append(os.path.getmtime(path))
        except OSError:
            pass
    total_count = all_files["count"]
    total_bytes = all_files["bytes"]
    newest_vals = [b["newest"] for b in buckets.values() if b["newest"]]
    return {
        "path":    root,
        "exists":  True,
        "buckets": buckets,
        "newest_save": max(native_meta) if native_meta else None,
        "total":   {
            "count":  total_count,
            "bytes":  total_bytes,
            "newest": max(newest_vals) if newest_vals else None,
        },
    }

def _flush_saves():
    """Remove the contents of `.save/game/` and `.save/playersave/` (world
    session + per-player data). `.save/settings/` is left alone — it holds
    non-session config the server regenerates from. Returns the count of files
    deleted."""
    import shutil
    root = _save_root()
    if not os.path.isdir(root):
        return 0
    removed = 0
    for sub in _FLUSHABLE_SUBDIRS:
        bucket = os.path.join(root, sub)
        if not os.path.isdir(bucket):
            continue
        for name in os.listdir(bucket):
            full = os.path.join(bucket, name)
            try:
                if os.path.isdir(full) and not os.path.islink(full):
                    for _dp, _dn, files in os.walk(full):
                        removed += len(files)
                    shutil.rmtree(full)
                else:
                    os.remove(full)
                    removed += 1
            except OSError:
                pass
    return removed


def get_map_name(cfg=None):
    try:
        if cfg is None:
            cfg = read_config()
        sid = cfg.get("game", {}).get("scenarioId", "")
        if not sid:
            return "Unknown"
        # Consult the full merged list (vanilla + discovered, with overrides
        # already applied) so the dashboard tile matches the dropdown.
        for m in all_scenarios_cached():
            if m["id"] == sid:
                return m["name"]
        return sid.split("/")[-1].replace(".conf", "")
    except Exception:
        return "Unknown"

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/manifest.json")
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect("/login")
    _ensure_csrf()
    with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
        return f.read()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = _client_ip()
        if not _login_rate_ok(ip):
            return jsonify({"ok": False, "error": "Too many attempts. Wait a minute."}), 429
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(ok=False, error="Request body must be a JSON object"), 400
        # bcrypt is intentionally slow — even on a successful login it adds ~100ms,
        # which is also a natural defense against brute force.
        user = authenticate_user(data.get("username", ""), data.get("password", ""))
        if user:
            session.clear()
            session.permanent = True
            session["logged_in"] = True
            session["user_id"] = user["id"]
            session["user_version"] = user["version"]
            session["login_at"] = int(time.time())
            _ensure_csrf()
            audit_event(user["username"], "login", "success")
            return jsonify({"ok": True, "csrf": session["csrf"]})
        return jsonify({"ok": False, "error": "Invalid username or password"}), 401
    with open(os.path.join(os.path.dirname(__file__), "login.html"), encoding="utf-8") as f:
        return f.read()

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/csrf")
def api_csrf():
    """Front-end fetches a CSRF token after login and on tab refresh."""
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"csrf": _ensure_csrf()})

@app.route("/api/status")
def api_status():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    pid = get_server_pid()
    cfg = read_config()
    cpu, ram = get_cpu_ram(pid) if pid else (0.0, 0.0)
    ram_used, ram_total = get_system_ram()
    missions = all_scenarios_cached()
    return jsonify({
        "running":        pid is not None,
        "pid":            pid,
        "map":            get_map_name(cfg),
        "players":        None,
        "uptime":         format_uptime(get_process_uptime(pid)) if pid else "—",
        "uptime_sec":     get_process_uptime(pid) if pid else 0,
        "server_name":    cfg.get("game", {}).get("name", "—"),
        "ip":             cfg.get("publicAddress", "—"),
        "port":           cfg.get("publicPort", "—"),
        "scenario_id":    cfg.get("game", {}).get("scenarioId", ""),
        "missions":       missions,
        "missions_count": {"vanilla": sum(1 for m in missions if m.get("source") == "vanilla"),
                           "from_mods": sum(1 for m in missions if m.get("source") != "vanilla")},
        "password":       cfg.get("game", {}).get("password", "") if "configure" in g.permissions else "",
        "password_admin": cfg.get("game", {}).get("passwordAdmin", "") if "admin_config" in g.permissions else "",
        "cpu":            cpu,
        "ram_process":    ram,
        "ram_used":       ram_used,
        "ram_total":      ram_total,
        "mods":           cfg.get("game", {}).get("mods", []),
        "csrf":           _ensure_csrf(),
    })

@app.route("/api/scenarios/rescan", methods=["POST"])
def api_scenarios_rescan():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err
    missions, diag = all_scenarios(force_rescan=True)
    return jsonify({
        "ok": True,
        "missions": missions,
        "missions_count": {"vanilla": sum(1 for m in missions if m.get("source") == "vanilla"),
                           "from_mods": sum(1 for m in missions if m.get("source") != "vanilla")},
        "diag": diag,
    })

@app.route("/api/metrics")
def api_metrics():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    pid = get_server_pid()
    cpu, ram = get_cpu_ram(pid) if pid else (0.0, 0.0)
    ram_used, ram_total = get_system_ram()
    return jsonify({
        **_traffic_metrics.read(pid),
        **_host_metrics.read(SERVER_DIR),
        **read_game_telemetry(_cfg.get('GAME_TELEMETRY_FILE'), pid is not None),
        **_server_fps.read(get_latest_log(), pid),
        "events": metric_events(),
        "cpu": cpu, "ram_process": ram,
        "cpu_frequency_mhz": read_cpu_frequency(),
        "ram_used": ram_used, "ram_total": ram_total,
        "running": pid is not None, "ts": int(time.time()),
    })


@app.route('/api/network')
def api_network():
    if not session.get('logged_in'):
        return jsonify(error='unauthorized'), 401
    cfg = read_config()
    game = cfg.get('game') or {}
    props = game.get('gameProperties') or {}
    rcon = cfg.get('rcon') or {}
    a2s = cfg.get('a2s') or {}
    pid = get_server_pid()
    game_port = cfg.get('bindPort', 2001)
    query_port = a2s.get('port', 17777) if a2s else None
    rcon_port = rcon.get('port', 19999) if rcon.get('password') else None
    public_address = cfg.get('publicAddress') or ''
    if public_address in ('0.0.0.0', '::'):
        public_address = ''
    public_port = cfg.get('publicPort') or game_port
    services = [
        dict(name='Game', port=game_port, status=udp_listener_status(pid, game_port)),
        dict(name='A2S / Query', port=query_port, status=udp_listener_status(pid, query_port)),
        dict(name='RCON', port=rcon_port, status=udp_listener_status(pid, rcon_port)),
    ]
    return jsonify(
        running=pid is not None,
        max_players=game.get('maxPlayers', 64),
        network_view_distance=props.get('networkViewDistance', 1500),
        server_view_distance=props.get('serverMaxViewDistance', 1600),
        endpoint=f'{public_address}:{public_port}' if public_address else None,
        services=services,
    )

@app.route("/api/logs")
def api_logs():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        n = max(1, min(800, int(request.args.get("lines", 80))))
    except ValueError:
        return jsonify(error="Invalid line count"), 400
    cursor = request.args.get('cursor', '')
    if len(cursor) > 4096:
        return jsonify(error="Invalid console cursor"), 400
    path = get_latest_log()
    if not path:
        return jsonify({"lines": [], "path": None})
    try:
        return jsonify(read_console(path, cursor, n))
    except Exception as e:
        return jsonify({"lines": [], "error": str(e)})

def _normalize_mod_entry(entry):
    """Validate one mod row. Returns canonical dict or None."""
    if not isinstance(entry, dict):
        return None
    mod_id = str(entry.get("modId", "")).strip()
    if not mod_id or len(mod_id) > 32:
        return None
    if not all(c in "0123456789ABCDEFabcdef" for c in mod_id):
        return None
    out = {"modId": mod_id.upper()}
    name = str(entry.get("name", "")).strip()
    if name:
        if len(name) > 200 or any(c in name for c in "\n\r"):
            return None
        out["name"] = name
    version = str(entry.get("version", "")).strip()
    if version:
        if len(version) > 32 or any(c in version for c in '\n\r"\\'):
            return None
        out["version"] = version
    return out


@app.route("/api/config", methods=["POST"])
def api_config():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err
    data = request.get_json(silent=True) or {}
    if 'password_admin' in data and 'admin_config' not in g.permissions:
        return jsonify(ok=False, error='Admin only: administrator password'), 403
    cfg  = read_config()
    changed = False
    if "server_name" in data and data["server_name"].strip():
        cfg.setdefault("game", {})["name"] = data["server_name"].strip(); changed = True
    if "scenario_id" in data:
        sid = data["scenario_id"].strip()
        valid_ids = {m["id"] for m in all_scenarios_cached()}
        if sid not in valid_ids:
            return jsonify({"ok": False, "error": "Unknown scenario"})
        cfg.setdefault("game", {})["scenarioId"] = sid; changed = True
    if "password" in data:
        cfg.setdefault("game", {})["password"] = data["password"]; changed = True
    if "password_admin" in data and data["password_admin"].strip():
        cfg.setdefault("game", {})["passwordAdmin"] = data["password_admin"].strip(); changed = True
    if not changed:
        return jsonify({"ok": False, "error": "No changes"})
    try:
        write_config(cfg)
        return jsonify({"ok": True, "restart_required": get_server_pid() is not None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/persistence", methods=["GET"])
def api_persistence_get():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    cfg = read_config()
    block = _get_persistence_block(cfg) or {}
    saves = _scan_saves()
    return jsonify({
        "enabled":          _persistence_enabled(cfg),
        "autoSaveInterval": block.get("autoSaveInterval", 10),
        "saveRetention":    block.get("saveRetention", 10),
        "loadSessionSave":  block.get("loadSessionSave", True),
        "keepSessionSave":  block.get("keepSessionSave", False),
        "hiveId":           block.get("hiveId", 0),
        "scenarioId":       cfg.get("game", {}).get("scenarioId", ""),
        "saves":            saves,
        "profile_dir":      PROFILE_DIR,
    })

@app.route("/api/persistence", methods=["POST"])
def api_persistence_set():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err
    data = request.get_json(silent=True) or {}
    cfg  = read_config()
    enabled = bool(data.get("enabled"))
    if enabled:
        header = cfg.setdefault('game', {}).setdefault('gameProperties', {}).setdefault('missionHeader', {})
        if header.get('m_eSaveTypes') == 0:
            header.pop('m_eSaveTypes')  # Inherit the scenario's supported save types.
        block = _get_persistence_block(cfg) or {}
        integer_fields = {
            "autoSaveInterval": (0, 60),
            "saveRetention": (1, 128),
            "hiveId": (0, 16383),
        }
        defaults = {"autoSaveInterval": 10, "saveRetention": 10, "loadSessionSave": True,
                    "keepSessionSave": False, "hiveId": 0}
        for key, (minimum, maximum) in integer_fields.items():
            if key in data:
                try:
                    value = int(data[key])
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "error": f"{key} must be an integer"})
                if not minimum <= value <= maximum:
                    return jsonify({"ok": False, "error": f"{key} must be between {minimum} and {maximum}"})
                block[key] = value
            else:
                block.setdefault(key, defaults[key])
        for key in ("loadSessionSave", "keepSessionSave"):
            if key in data:
                if type(data[key]) is not bool:
                    return jsonify({"ok": False, "error": f"{key} must be a boolean"})
                block[key] = data[key]
            else:
                block.setdefault(key, defaults[key])
        _set_persistence_block(cfg, block)
    else:
        cfg.setdefault('game', {}).setdefault('gameProperties', {}).setdefault('missionHeader', {})['m_eSaveTypes'] = 0
    try:
        write_config(cfg)
        return jsonify({
            "ok": True,
            "restart_required": get_server_pid() is not None,
            "enabled":           _persistence_enabled(cfg),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/persistence/flush", methods=["POST"])
def api_persistence_flush():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err
    # Refuse to delete saves while the server is running — the game holds file
    # handles and may rewrite them mid-flush, which leaves us with partials.
    if get_server_pid():
        return jsonify({"ok": False, "error": "Stop the server before flushing saves"})
    try:
        removed = _flush_saves()
        return jsonify({"ok": True, "removed": removed, "saves": _scan_saves()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/mods/add", methods=["POST"])
def api_mods_add():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err
    data = request.get_json(silent=True) or {}
    norm = _normalize_mod_entry({"modId": data.get("modId",""), "name": data.get("name",""), "version": data.get("version","")})
    if not norm:
        return jsonify({"ok": False, "error": "Invalid mod entry (modId must be 1-32 hex chars)"})
    if "name" not in norm:
        return jsonify({"ok": False, "error": "name is required for manual entry"})
    cfg  = read_config()
    mods = cfg.setdefault("game", {}).setdefault("mods", [])
    if any(m.get("modId", "").upper() == norm["modId"] for m in mods):
        return jsonify({"ok": False, "error": "Mod with this ID already exists"})
    mods.append(norm)
    try:
        write_config(cfg)
        return jsonify({"ok": True, "restart_required": get_server_pid() is not None, "mods": mods})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/mods/import", methods=["POST"])
def api_mods_import():
    """Bulk-import mods. Accepts either:
       - multipart/form-data with a 'file' part containing a JSON array, plus
         form fields 'mode' (replace|merge) and '_csrf'.
       - application/json with {payload: <text or array>, mode, _csrf}.
    """
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err

    raw = None
    mode = "replace"

    if request.files and "file" in request.files:
        f = request.files["file"]
        try:
            raw = f.read().decode("utf-8")
        except UnicodeDecodeError:
            return jsonify({"ok": False, "error": "File must be UTF-8 encoded JSON"}), 400
        mode = (request.form.get("mode") or "replace").strip().lower()
    else:
        body = request.get_json(silent=True) or {}
        payload = body.get("payload")
        if isinstance(payload, list):
            raw = json.dumps(payload)
        elif isinstance(payload, str):
            raw = payload
        mode = (body.get("mode") or "replace").strip().lower()

    if mode not in ("replace", "merge"):
        return jsonify({"ok": False, "error": "mode must be 'replace' or 'merge'"}), 400
    if not raw or not raw.strip():
        return jsonify({"ok": False, "error": "Empty payload"}), 400

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"Invalid JSON: {e.msg} at line {e.lineno} col {e.colno}"}), 400
    if not isinstance(data, list):
        return jsonify({"ok": False, "error": "Top-level value must be a JSON array"}), 400

    valid = []
    skipped = []
    seen = set()
    for i, entry in enumerate(data):
        norm = _normalize_mod_entry(entry)
        if not norm:
            skipped.append(f"#{i + 1}: invalid")
            continue
        if norm["modId"] in seen:
            skipped.append(f"#{i + 1}: duplicate modId {norm['modId']}")
            continue
        seen.add(norm["modId"])
        valid.append(norm)

    cfg = read_config()
    g   = cfg.setdefault("game", {})

    if mode == "merge":
        existing = list(g.get("mods", []))
        existing_ids = {str(m.get("modId", "")).upper() for m in existing}
        added = 0
        for m in valid:
            if m["modId"] not in existing_ids:
                existing.append(m)
                existing_ids.add(m["modId"])
                added += 1
        g["mods"] = existing
        msg = f"Merged: {added} added, {len(valid) - added} already present"
    else:
        g["mods"] = valid
        msg = f"Replaced full mod list with {len(valid)} entries"

    try:
        write_config(cfg)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({
        "ok": True,
        "message": msg,
        "imported": len(valid),
        "skipped": skipped,
        "mods": g["mods"],
        "restart_required": get_server_pid() is not None,
    })

@app.route("/api/mods/remove", methods=["POST"])
def api_mods_remove():
    if not session.get("logged_in"):
        return jsonify({"error": "unauthorized"}), 401
    err = _csrf_required()
    if err: return err
    data   = request.get_json(silent=True) or {}
    mod_id = data.get("modId", "").strip().upper()
    if not mod_id:
        return jsonify({"ok": False, "error": "Missing modId"})
    cfg  = read_config()
    mods = cfg.get("game", {}).get("mods", [])
    new  = [m for m in mods if str(m.get("modId", "")).upper() != mod_id]
    if len(new) == len(mods):
        return jsonify({"ok": False, "error": "Mod not found"})
    cfg.setdefault("game", {})["mods"] = new
    try:
        write_config(cfg)
        return jsonify({"ok": True, "restart_required": get_server_pid() is not None, "mods": new})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

from mod_metadata import ModMetadata
_mod_metadata = ModMetadata()


@app.get("/api/mods/metadata")
def api_mods_metadata():
    mod_id = request.args.get("modId", "").upper()
    mods = read_config().get("game", {}).get("mods", [])
    if not any(str(m.get("modId", "")).upper() == mod_id for m in mods):
        return jsonify(ok=False, error="Mod is not configured"), 404
    return jsonify(_mod_metadata.get(mod_id))


@app.post("/api/mods/edit")
def api_mods_edit():
    data = request.get_json(silent=True) or {}
    cfg = read_config()
    mods = cfg.get("game", {}).get("mods", [])
    if not isinstance(data.get("expected"), list) or data["expected"] != mods:
        return jsonify(ok=False, error="The mod list changed. Close and reopen this editor to try again."), 409
    mod_id = data.get("modId")
    if not isinstance(mod_id, str):
        return jsonify(ok=False, error="Invalid mod ID"), 400
    index = next((i for i, m in enumerate(mods) if m.get("modId", "").upper() == mod_id.upper()), None)
    if index is None:
        return jsonify(ok=False, error="Mod not found"), 404
    if "direction" in data:
        direction = data["direction"]
        if type(direction) is not int or direction not in (-1, 1) or not 0 <= index + direction < len(mods):
            return jsonify(ok=False, error="Invalid move"), 400
        mods[index], mods[index + direction] = mods[index + direction], mods[index]
    else:
        name, version = data.get("name", ""), data.get("version", "")
        if not isinstance(name, str) or not isinstance(version, str) or len(name) > 200 or len(version) > 32 or any(ord(c) < 32 for c in name + version):
            return jsonify(ok=False, error="Invalid name or version"), 400
        for key, value in (("name", name.strip()), ("version", version.strip())):
            if value:
                mods[index][key] = value
            else:
                mods[index].pop(key, None)
    write_config(cfg)
    return jsonify(ok=True, restart_required=get_server_pid() is not None)


@app.post('/api/mods/update-pins')
def api_mods_update_pins():
    data = request.get_json(silent=True) or {}
    cfg = read_config()
    mods = cfg.get('game', {}).get('mods', [])
    if not isinstance(data.get('expected'), list) or data['expected'] != mods:
        return jsonify(ok=False, error='The mod list changed. Review updates again.'), 409
    changes = data.get('changes')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 300:
        return jsonify(ok=False, error='Select at least one mod to update.'), 400
    by_id = {str(mod.get('modId', '')).upper(): mod for mod in mods}
    if len(by_id) != len(mods):
        return jsonify(ok=False, error='Duplicate mod IDs in configuration. Resolve them before updating pins.'), 409
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            return jsonify(ok=False, error='Invalid update selection.'), 400
        mod_id, old, new = change.get('modId'), change.get('from'), change.get('to')
        if not isinstance(mod_id, str) or not isinstance(old, str) or not isinstance(new, str):
            return jsonify(ok=False, error='Invalid update selection.'), 400
        mod_id = mod_id.upper()
        mod = by_id.get(mod_id)
        if mod_id in seen or mod is None or not old or mod.get('version') != old or old == new:
            return jsonify(ok=False, error='A selected mod changed. Review updates again.'), 409
        if not 1 <= len(new) <= 32 or any(ord(c) < 33 or c in '\\"' for c in new):
            return jsonify(ok=False, error='Invalid Workshop version.'), 400
        metadata = _mod_metadata.get(mod_id)
        if metadata.get('status') != 'available' or metadata.get('current_version') != new:
            return jsonify(ok=False, error='Workshop data changed or is unavailable. Review updates again.'), 409
        seen.add(mod_id)
    for change in changes:
        by_id[change['modId'].upper()]['version'] = change['to']
    try:
        write_config(cfg)
    except OSError:
        return jsonify(ok=False, error='Could not save the server configuration.'), 503
    return jsonify(ok=True, updated=len(changes), restart_required=get_server_pid() is not None)


def service_command(action):
    result = subprocess.run(
        ["sudo", "-n", "/usr/bin/systemctl", action, "arma-server.service"],
        capture_output=True, text=True, timeout=150)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Server service command failed")


def stop_server():
    # systemd stop also cancels scheduled automatic restarts.
    service_command("stop")
    pid = get_server_pid()
    if pid:
        # A game started by the previous panel is outside arma-server.service.
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 60
    while get_server_pid():
        if time.monotonic() >= deadline:
            raise RuntimeError("Server is still stopping; no replacement was started. Check the console.")
        time.sleep(0.25)


def start_server():
    service_command("start")
    # Verify the same process survives an observation window. This is process
    # health, not a claim that mods have loaded or players can connect yet.
    pid = get_server_pid()
    deadline = time.monotonic() + 10
    while not pid and time.monotonic() < deadline:
        time.sleep(0.25)
        pid = get_server_pid()
    if not pid:
        raise RuntimeError("Server did not start. Check the console and journalctl -u arma-server.")
    for _ in range(8):
        time.sleep(0.5)
        if get_server_pid() != pid:
            raise RuntimeError("Server exited during startup. Check the console and journalctl -u arma-server.")


@app.route("/api/start", methods=["POST"])
def api_start():
    try:
        if get_server_pid():
            return jsonify(ok=False, error="Server is already running")
        start_server()
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc))


@app.route("/api/stop", methods=["POST"])
def api_stop():
    try:
        stop_server()
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc))


@app.route("/api/restart", methods=["POST"])
def api_restart():
    try:
        stop_server()
        start_server()
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc))


from config_editor import install as install_config_editor
install_config_editor(sys.modules[__name__])

from panel_features import install as install_features
install_features(sys.modules[__name__])

from file_manager import install as install_file_manager
install_file_manager(sys.modules[__name__])

from server_software import install as install_server_software
install_server_software(sys.modules[__name__])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PANEL_PORT, threaded=True)
