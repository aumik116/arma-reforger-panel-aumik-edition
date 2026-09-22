"""Named snapshots of game-written persistence files; never manufactures a game save."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import uuid

MAX_BYTES = 1024 ** 3
MAX_FILES = 10000
MAX_SNAPSHOTS = 30


def safe_tree(root):
    root = Path(root)
    files, total = [], 0
    if not root.exists():
        return files
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in ['.'] + dirs + names:
            path = Path(directory) if name == '.' else Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('Save directories must not contain symbolic links or junctions.')
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ValueError('Only ordinary save files are supported.')
        for name in names:
            path = Path(directory) / name
            total += path.stat().st_size
            files.append(path)
            if len(files) > MAX_FILES or total > MAX_BYTES:
                raise ValueError('Save snapshot exceeds the 1 GiB or 10,000 file limit.')
    return files


def fingerprint(root):
    result = {}
    for path in safe_tree(root):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


class SaveLibrary:
    def __init__(self, api):
        self.api = api
        self.base = Path(api._BASE_DIR) / '.save-library'

    def context(self):
        from server_software import installed_build
        game = self.api.read_config().get('game', {})
        return {'scenario': game.get('scenarioId', ''), 'mods': game.get('mods', []),
                'hive': (game.get('gameProperties', {}).get('persistence') or {}).get('hiveId', 0),
                'build': installed_build(self.api.SERVER_DIR)}

    def root(self):
        persistence = self.api.read_config().get('game', {}).get('gameProperties', {}).get('persistence') or {}
        if persistence.get('databases') or persistence.get('storages'):
            raise ValueError('Custom persistence storage requires its own backup tools.')
        profile = Path(self.api.PROFILE_DIR).absolute()
        root = Path(self.api._save_root()).absolute()
        if profile.is_symlink() or getattr(profile, 'is_junction', lambda: False)():
            raise ValueError('Profile directory must not be a symbolic link or junction.')
        if root.parent != profile or root.name not in self.api._SAVE_SUBDIRS:
            raise ValueError('Save directory must be a recognized directory directly inside PROFILE_DIR.')
        safe_tree(root)
        return root

    def stopped(self):
        if self.api.software_manager.busy():
            raise ValueError('Wait for the software job to finish.')
        if self.api.get_server_pid():
            raise ValueError('Wait for a game autosave, then stop the server before capturing or restoring a setup.')
        # Cancel scheduled systemd restarts before handling save files.
        self.api.service_command('stop')
        if self.api.get_server_pid():
            raise ValueError('The server is still running.')

    def listing(self):
        snapshots = []
        if self.base.exists():
            if self.base.is_symlink():
                raise ValueError('Snapshot library must not be a symbolic link.')
            for path in self.base.iterdir():
                if re.fullmatch(r'[a-f0-9]{32}', path.name) and path.is_dir() and not path.is_symlink():
                    try:
                        meta = json.loads((path / 'metadata.json').read_text(encoding='utf-8'))
                        snapshots.append({k: meta[k] for k in ('snapshot', 'name', 'created', 'actor', 'count', 'bytes', 'context')})
                    except (OSError, ValueError, KeyError):
                        continue
        return sorted(snapshots, key=lambda row: row['created'], reverse=True)

    def capture(self, name, actor, allow_empty=False):
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Enter a setup name of 1–80 characters.')
        if len(self.listing()) >= MAX_SNAPSHOTS:
            raise ValueError('The library is full (30 snapshots). Archive old snapshots on the host before adding more.')
        root = self.root()
        files = safe_tree(root)
        if not files and not allow_empty:
            raise ValueError('No save files found. Create a save in-game first; the panel cannot force Camp Neptune to save.')
        if not allow_empty and not any(p.name == 'meta-info.json' for p in files):
            raise ValueError('No native save-point metadata found. Wait for a scenario autosave and verify PROFILE_DIR.')
        self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.capture-', dir=self.base))
        key = uuid.uuid4().hex
        try:
            before = fingerprint(root)
            if root.exists():
                shutil.copytree(root, staging / 'files')
            else:
                (staging / 'files').mkdir()
            hashes = fingerprint(staging / 'files')
            if hashes != before or before != fingerprint(root):
                raise ValueError('Save files changed during capture. No snapshot was saved.')
            meta = {'snapshot': key, 'name': name.strip(), 'created': time.time(), 'actor': actor,
                    'count': len(files), 'bytes': sum(p.stat().st_size for p in files),
                    'context': self.context(), 'hashes': hashes}
            (staging / 'metadata.json').write_text(json.dumps(meta), encoding='utf-8')
            staging.rename(self.base / key)
            return meta
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def restore(self, key, actor):
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key):
            raise ValueError('Invalid snapshot identifier.')
        if self.base.is_symlink() or (self.base / key).is_symlink():
            raise ValueError('Invalid snapshot path.')
        snapshot = self.base / key
        safe_tree(snapshot)
        meta = json.loads((snapshot / 'metadata.json').read_text(encoding='utf-8'))
        if meta['context'] != self.context():
            raise ValueError('Scenario, mods, persistence hive or game build differs. Restore the matching configuration/build first.')
        source = snapshot / 'files'
        if not source.is_dir() or fingerprint(source) != meta['hashes']:
            raise ValueError('Snapshot integrity check failed. Nothing was restored.')
        root = self.root()
        backup = self.capture('Before restore · ' + time.strftime('%Y-%m-%d %H:%M:%S'), actor, allow_empty=True)
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=root.parent))
        previous = root.parent / ('.previous-' + uuid.uuid4().hex)
        moved = False
        try:
            shutil.copytree(source, staging / 'files')
            if fingerprint(staging / 'files') != meta['hashes']:
                raise ValueError('Restored copy failed its integrity check.')
            if self.api.get_server_pid():
                raise ValueError('The game server started during restore. Nothing was replaced.')
            if root.exists():
                root.rename(previous)
                moved = True
            try:
                (staging / 'files').rename(root)
            except Exception:
                if moved:
                    previous.rename(root)
                raise
            if moved:
                shutil.rmtree(previous)
            return backup['snapshot']
        finally:
            shutil.rmtree(staging)


def install(api):
    from flask import jsonify, request, g
    library = SaveLibrary(api)
    api.save_library = library

    @api.app.get('/api/saves')
    def saves_list():
        try:
            root = library.root()
            files = safe_tree(root)
            return jsonify(snapshots=library.listing(), context=library.context(), path=str(root),
                           count=len(files), newest=max((p.stat().st_mtime for p in files), default=None),
                           running=bool(api.get_server_pid()), busy=api.software_manager.busy())
        except (OSError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

    @api.app.post('/api/saves/capture')
    def saves_capture():
        try:
            library.stopped()
            meta = library.capture((request.get_json(silent=True) or {}).get('name'), g.user['username'])
            g.audit_details = {'snapshot': meta['snapshot'], 'name': meta['name']}
            return jsonify(ok=True, snapshot=meta['snapshot'])
        except (OSError, ValueError, RuntimeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409

    @api.app.post('/api/saves/restore')
    def saves_restore():
        try:
            library.stopped()
            key = (request.get_json(silent=True) or {}).get('snapshot')
            backup = library.restore(key, g.user['username'])
            g.audit_details = {'snapshot': key, 'rollback_snapshot': backup}
            return jsonify(ok=True, rollback_snapshot=backup, message='Setup restored. Start the server from Dashboard to load it.')
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
