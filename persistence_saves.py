"""Discover and pin Reforger session save points for repeatable starts."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
SAVE_ROOTS = (".save", "save", "saves")
EXCLUDED_BUCKETS = {"playersave", "settings"}
STATE_NAME = ".panel-save-selection.json"
ARCHIVE_DIR = ".panel-save-archives"


def _uuid_from_meta(data):
    if not isinstance(data, dict):
        return None
    preferred = {"uuid", "saveuuid", "saveid", "savepointid", "id"}
    for key, value in data.items():
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized in preferred and isinstance(value, str) and UUID_RE.fullmatch(value):
            return value.lower()
    for value in data.values():
        if isinstance(value, dict):
            found = _uuid_from_meta(value)
            if found:
                return found
    matches = {value.lower() for value in data.values()
               if isinstance(value, str) and UUID_RE.fullmatch(value)}
    return next(iter(matches)) if len(matches) == 1 else None


def _meta_uuid(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        return _uuid_from_meta(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, UnicodeError):
        return None


def list_save_points(profile_dir):
    """Return usable save points; unrelated settings/player files are omitted."""
    profile = Path(profile_dir).resolve()
    points = {}
    for root_name in SAVE_ROOTS:
        root = profile / root_name
        if not root.is_dir() or root.is_symlink():
            continue
        for meta in root.rglob("meta-info.json"):
            relative = meta.relative_to(profile)
            if any(part.lower() in EXCLUDED_BUCKETS for part in relative.parts[1:-1]):
                continue
            if meta.is_symlink() or any(parent.is_symlink() for parent in meta.parents if parent != profile):
                continue
            uuid = _meta_uuid(meta)
            if not uuid:
                continue
            try:
                modified = meta.stat().st_mtime
            except OSError:
                continue
            point = {"uuid": uuid, "modified": modified,
                     "relative_path": str(meta.parent.relative_to(profile)).replace("\\", "/")}
            if uuid not in points or modified > points[uuid]["modified"]:
                points[uuid] = point
    return sorted(points.values(), key=lambda item: item["modified"], reverse=True)


def _state_path(panel_dir):
    return Path(panel_dir) / STATE_NAME


def read_state(panel_dir):
    try:
        state = json.loads(_state_path(panel_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "pins": {}, "snapshots": {}}
    if not isinstance(state, dict) or not isinstance(state.get("pins"), dict) or not isinstance(state.get("snapshots", {}), dict):
        raise ValueError("The saved startup selection is invalid")
    state.setdefault("snapshots", {})
    return state


def selection_for(panel_dir, scenario_id):
    return read_state(panel_dir)["pins"].get(scenario_id)


def named_saves_for(panel_dir, scenario_id):
    saved = read_state(panel_dir)["snapshots"].get(scenario_id, {})
    return sorted(({**item, "uuid": uuid,
                    "available": _meta_uuid(_archive_path(panel_dir, scenario_id, uuid) / "meta-info.json") == uuid}
                   for uuid, item in saved.items()),
                  key=lambda item: item.get("captured_at", 0), reverse=True)


def _write_state(panel_dir, state):
    path = _state_path(panel_dir)
    handle, name = tempfile.mkstemp(prefix=".save-selection-", dir=panel_dir)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _archive_path(panel_dir, scenario_id, uuid):
    key = hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:16]
    return Path(panel_dir) / ARCHIVE_DIR / key / uuid


def _manifest(root):
    files = []
    for directory, dirs, names in os.walk(root):
        for name in dirs + names:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Save point contains a symbolic link")
        for name in names:
            file = Path(directory) / name
            stat = file.stat()
            files.append((str(file.relative_to(root)), stat.st_size, stat.st_mtime_ns))
    return sorted(files)


def _capture_point(panel_dir, profile_dir, scenario_id, uuid, state):
    if not isinstance(uuid, str) or not UUID_RE.fullmatch(uuid):
        raise ValueError("Invalid save point UUID")
    uuid = uuid.lower()
    point = next((item for item in list_save_points(profile_dir) if item["uuid"] == uuid), None)
    if point is None:
        saved = state["snapshots"].get(scenario_id, {}).get(uuid)
        if saved and _meta_uuid(_archive_path(panel_dir, scenario_id, uuid) / "meta-info.json") == uuid:
            return {"uuid": uuid, "relative_path": saved["relative_path"]}
        raise ValueError("Save point not found in the configured game profile")
    source = Path(profile_dir).resolve() / point["relative_path"]
    archive = _archive_path(panel_dir, scenario_id, uuid)
    if archive.exists() and _meta_uuid(archive / "meta-info.json") != uuid:
        raise ValueError("Existing save backup is invalid; it cannot be selected")
    if not archive.is_dir():
        archive.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(archive.parent, 0o700)
        temporary = Path(tempfile.mkdtemp(prefix=".save-copy-", dir=archive.parent))
        try:
            before = _manifest(source)
            shutil.copytree(source, temporary, dirs_exist_ok=True)
            if before != _manifest(source) or _meta_uuid(temporary / "meta-info.json") != uuid:
                raise ValueError("Save point changed during capture; wait for autosave to finish and retry")
            os.replace(temporary, archive)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return point


def save_named_point(panel_dir, profile_dir, scenario_id, uuid, name):
    """Keep a named copy of a completed autosave outside game retention."""
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError("Enter a backup name of 1 to 80 characters")
    state = read_state(panel_dir)
    point = _capture_point(panel_dir, profile_dir, scenario_id, uuid, state)
    saved = state["snapshots"].setdefault(scenario_id, {})
    previous = saved.get(point["uuid"], {})
    saved[point["uuid"]] = {"name": name.strip(), "relative_path": point["relative_path"],
                             "captured_at": previous.get("captured_at", time.time())}
    _write_state(panel_dir, state)
    return saved[point["uuid"]]


def set_startup_save(panel_dir, profile_dir, scenario_id, uuid):
    """Pin a point for this scenario, keeping a copy outside game retention."""
    state = read_state(panel_dir)
    if not uuid:
        state["pins"].pop(scenario_id, None)
        _write_state(panel_dir, state)
        return None
    point = _capture_point(panel_dir, profile_dir, scenario_id, uuid, state)
    saved = state["snapshots"].setdefault(scenario_id, {})
    saved.setdefault(point["uuid"], {
        "name": "Save " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "relative_path": point["relative_path"], "captured_at": time.time()})
    state["pins"][scenario_id] = {"uuid": point["uuid"],
                                   "relative_path": point["relative_path"],
                                   "selected_at": time.time()}
    _write_state(panel_dir, state)
    return state["pins"][scenario_id]


def _target_path(profile_dir, relative_path):
    relative = Path(relative_path)
    if relative.is_absolute() or len(relative.parts) < 2 or relative.parts[0] not in SAVE_ROOTS or ".." in relative.parts:
        raise ValueError("Invalid saved save-point location")
    if any(part.lower() in EXCLUDED_BUCKETS for part in relative.parts[1:]):
        raise ValueError("Invalid saved save-point location")
    profile = Path(profile_dir).resolve()
    target = profile / relative
    if not target.resolve().is_relative_to(profile):
        raise ValueError("Save-point location leaves the game profile")
    return target


def prepare_startup_save(panel_dir, profile_dir, scenario_id):
    """Restore a retained point if game retention removed it; return its UUID."""
    selected = selection_for(panel_dir, scenario_id)
    if not selected:
        return None
    uuid = selected.get("uuid")
    if not isinstance(uuid, str) or not UUID_RE.fullmatch(uuid):
        raise ValueError("Invalid pinned save point UUID")
    uuid = uuid.lower()
    archive = _archive_path(panel_dir, scenario_id, uuid)
    if not archive.is_dir() or _meta_uuid(archive / "meta-info.json") != uuid:
        raise RuntimeError("Pinned save point archive is missing or invalid; select another save before starting")
    target = _target_path(profile_dir, selected.get("relative_path", ""))
    if target.exists():
        if not target.is_dir() or _meta_uuid(target / "meta-info.json") != uuid:
            raise RuntimeError("Pinned save point location has changed; select another save before starting")
        return uuid
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".save-restore-", dir=target.parent))
    try:
        shutil.copytree(archive, temporary, dirs_exist_ok=True)
        if _meta_uuid(temporary / "meta-info.json") != uuid:
            raise RuntimeError("Could not restore the pinned save point")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return uuid
