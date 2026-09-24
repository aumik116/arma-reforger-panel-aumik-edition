"""Scoped text-file browser for game profile configs and server logs."""
import difflib
import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import g, jsonify, request, send_file


READ_SUFFIXES = {'.json', '.conf', '.cfg', '.ini', '.txt', '.xml', '.yaml', '.yml', '.toml', '.md', '.log'}
EDIT_SUFFIXES = READ_SUFFIXES - {'.log'}
MAX_READ = 1024 * 1024
MAX_EDIT = 512 * 1024
MAX_DOWNLOAD = 50 * 1024 * 1024
MAX_ENTRIES = 500


class FileAccessError(ValueError):
    pass


def _parts(relative):
    if not isinstance(relative, str) or len(relative) > 1024 or relative.startswith(('/', '\\')) or '\\' in relative:
        raise FileAccessError('Invalid file path')
    if not relative:
        return []
    parts = relative.split('/')
    if any(part in ('', '.', '..') or ':' in part or any(ord(ch) < 32 for ch in part) for part in parts):
        raise FileAccessError('Invalid file path')
    return parts


def _root(api, key):
    roots = {'profile': api.PROFILE_DIR, 'logs': api.LOG_DIR, 'server-config': api.SERVER_CONFIG}
    if key not in roots:
        raise FileAccessError('Unknown file location')
    return Path(roots[key]).resolve(strict=True)


def _target(api, key, relative):
    parts = _parts(relative)
    base = _root(api, key)
    if key == 'server-config':
        if parts:
            raise FileAccessError('Invalid file path')
        return base
    if not base.is_dir():
        raise FileAccessError('File location is not a directory')
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise FileAccessError('Links cannot be opened from Files')
    resolved = current.resolve(strict=True)
    if os.path.commonpath((str(base), str(resolved))) != str(base):
        raise FileAccessError('File is outside this location')
    return resolved


def _editable(api, key, target):
    if key != 'profile' or target.suffix.lower() not in EDIT_SUFFIXES:
        return False
    try:
        return not os.path.samefile(target, api.SERVER_CONFIG)
    except OSError:
        return target != Path(api.SERVER_CONFIG).resolve()


def _text(api, key, relative, limit=MAX_READ):
    target = _target(api, key, relative)
    if not target.is_file() or target.suffix.lower() not in READ_SUFFIXES:
        raise FileAccessError('This file type cannot be opened in the editor')
    if target.stat().st_size > limit:
        raise FileAccessError('File is too large for the editor; download it instead')
    with target.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or b'\0' in raw:
        raise FileAccessError('File is too large or is not plain text')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise FileAccessError('Only UTF-8 text files can be opened') from exc
    return target, raw, content


def _encoded(content, original):
    # Textarea normalizes line endings. Retain an existing BOM and CRLF style.
    normalized = content.replace('\r\n', '\n').replace('\r', '\n')
    if b'\r\n' in original and original.count(b'\n') == original.count(b'\r\n'):
        normalized = normalized.replace('\n', '\r\n')
    return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + normalized.encode('utf-8')


def _review(api, data):
    if not isinstance(data, dict):
        raise FileAccessError('Invalid request')
    key, relative, content, revision = (data.get(field) for field in ('root', 'path', 'content', 'revision'))
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_EDIT:
        raise FileAccessError('Edited text must be at most 512 KiB')
    target, original, old_text = _text(api, key, relative, MAX_EDIT)
    if not _editable(api, key, target):
        raise FileAccessError('This file is read-only in Files')
    current_revision = hashlib.sha256(original).hexdigest()
    if revision != current_revision:
        raise FileAccessError('File changed on disk. Reload it before saving.')
    if target.suffix.lower() == '.json':
        try:
            json.loads(content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, TypeError) as exc:
            raise FileAccessError('Invalid JSON: ' + str(exc)) from exc
    updated = _encoded(content, original)
    diff_lines = difflib.unified_diff(old_text.splitlines(), content.splitlines(),
                                      fromfile='On disk', tofile='Your edit', lineterm='')
    diff = '\n'.join(diff_lines)
    truncated = len(diff) > 120000
    return target, original, updated, current_revision, diff[:120000], truncated


def _backup(api, key, relative, original, revision):
    backup_root = Path(api._cfg.get('FILE_BACKUP_DIR') or Path(api._BASE_DIR) / '.file-backups')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_root / key / Path(*_parts(relative)).parent / f'{Path(relative).name}.{stamp}.{revision[:8]}.bak'
    backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with backup.open('xb') as stream:
        os.chmod(backup, 0o600)
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    return backup


def install(api):
    app = api.app

    @app.get('/api/files')
    def files_list():
        key = request.args.get('root', 'profile')
        relative = request.args.get('path', '')
        try:
            target = _target(api, key, relative)
            if key == 'server-config':
                entries = [dict(name=target.name, path='', directory=False,
                                size=target.stat().st_size, modified=target.stat().st_mtime,
                                editable=False)]
                return jsonify(root=key, path='', entries=entries, truncated=False)
            if not target.is_dir():
                raise FileAccessError('Select a folder')
            entries = []
            with os.scandir(target) as scanner:
                for entry in scanner:
                    if entry.name.startswith('.') or entry.is_symlink():
                        continue
                    try:
                        folder = entry.is_dir(follow_symlinks=False)
                        if not folder and (not entry.is_file(follow_symlinks=False) or
                                           Path(entry.name).suffix.lower() not in READ_SUFFIXES):
                            continue
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    path = '/'.join(_parts(relative) + [entry.name])
                    entries.append(dict(name=entry.name, path=path, directory=folder,
                                        size=None if folder else info.st_size, modified=info.st_mtime,
                                        editable=not folder and _editable(api, key, Path(entry.path))))
                    if len(entries) > MAX_ENTRIES:
                        break
            entries.sort(key=lambda item: (not item['directory'], item['name'].lower()))
            return jsonify(root=key, path=relative, entries=entries[:MAX_ENTRIES],
                           truncated=len(entries) > MAX_ENTRIES)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.get('/api/files/content')
    def files_content():
        try:
            key, relative = request.args.get('root', ''), request.args.get('path', '')
            target, raw, content = _text(api, key, relative)
            return jsonify(root=key, path=relative, name=target.name, content=content,
                           revision=hashlib.sha256(raw).hexdigest(), editable=_editable(api, key, target),
                           size=len(raw), modified=target.stat().st_mtime)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.get('/api/files/download')
    def files_download():
        try:
            target = _target(api, request.args.get('root', ''), request.args.get('path', ''))
            if not target.is_file() or target.suffix.lower() not in READ_SUFFIXES:
                raise FileAccessError('This file type cannot be downloaded')
            if target.stat().st_size > MAX_DOWNLOAD:
                raise FileAccessError('Download is limited to 50 MiB')
            return send_file(target, as_attachment=True, download_name=target.name, max_age=0)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.post('/api/files/preview')
    def files_preview():
        try:
            _, _, updated, revision, diff, truncated = _review(api, request.get_json(silent=True))
            return jsonify(ok=True, revision=revision, changed=bool(diff), diff=diff, truncated=truncated)
        except FileAccessError as exc:
            return jsonify(ok=False, error=str(exc)), 409 if 'changed on disk' in str(exc) else 400
        except OSError:
            return jsonify(ok=False, error='Unable to read the file'), 500

    @app.post('/api/files/save')
    def files_save():
        data = request.get_json(silent=True)
        try:
            target, original, updated, revision, diff, _ = _review(api, data)
            if not diff:
                return jsonify(ok=False, error='No changes to save'), 400
            backup = _backup(api, data['root'], data['path'], original, revision)
            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(prefix='.panel-file-', dir=target.parent)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
                os.replace(temporary, target)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            g.audit_details = {'root': data['root'], 'path': data['path'], 'backup': str(backup)}
            return jsonify(ok=True, revision=hashlib.sha256(updated).hexdigest(), backup=str(backup))
        except FileAccessError as exc:
            return jsonify(ok=False, error=str(exc)), 409 if 'changed on disk' in str(exc) else 400
        except OSError:
            return jsonify(ok=False, error='Unable to back up or save the file'), 500
