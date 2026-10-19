"""Server-scoped file browsing, profile editing, uploads and recoverable deletion."""
import difflib
import hashlib
import json
import os
import secrets
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import g, jsonify, request, send_file


READ_SUFFIXES = {'.json', '.conf', '.cfg', '.ini', '.txt', '.xml', '.yaml', '.yml', '.toml', '.md', '.log'}
EDIT_SUFFIXES = READ_SUFFIXES - {'.log'}
MAX_READ = 1024 * 1024
MAX_EDIT = 512 * 1024
MAX_UPLOAD = 50 * 1024 * 1024
MAX_ENTRIES = 500


class FileAccessError(ValueError):
    pass


def _parts(relative):
    if not isinstance(relative, str) or len(relative) > 1024 or relative.startswith(('/', '\\')) or '\\' in relative:
        raise FileAccessError('Invalid file path')
    if not relative:
        return []
    parts = relative.split('/')
    if any(part in ('', '.', '..') or part.startswith('.panel-') or part.endswith((' ', '.')) or ':' in part or any(ord(ch) < 32 for ch in part) for part in parts):
        raise FileAccessError('Invalid file path')
    return parts


def _root(api, key):
    roots = {'profile': api.PROFILE_DIR, 'logs': api.LOG_DIR, 'server-config': api.SERVER_CONFIG,
             'workshop': api.WORKSHOP_DIR, 'server': api.SERVER_DIR,
             'backups': api._cfg.get('FILE_BACKUP_DIR') or Path(api._STATE_DIR) / '.file-backups'}
    if not isinstance(key, str) or key not in roots:
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
    backup_root = Path(api._cfg.get('FILE_BACKUP_DIR') or Path(api._STATE_DIR) / '.file-backups')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_root / key / Path(*_parts(relative)).parent / f'{Path(relative).name}.{stamp}.{revision[:8]}.bak'
    backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with backup.open('xb') as stream:
        os.chmod(backup, 0o600)
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    return backup


def _fingerprint(target):
    info = target.stat()
    return f'{info.st_ino}:{info.st_size}:{info.st_mtime_ns}'


def _destination(api, key, relative, create_parents=False):
    parts = _parts(relative)
    if key != 'profile' or not parts:
        raise FileAccessError('Only game profile files can be changed here')
    if create_parents:
        for depth in range(1, len(parts)):
            parent = _target(api, key, '/'.join(parts[:depth - 1]))
            try:
                (parent / parts[depth - 1]).mkdir(mode=0o750)
            except FileExistsError:
                pass
            # Check existing directories too: never follow a symlink.
            if not _target(api, key, '/'.join(parts[:depth])).is_dir():
                raise FileAccessError('Upload path contains a file instead of a folder')
    parent = _target(api, key, '/'.join(parts[:-1]))
    if not parent.is_dir():
        raise FileAccessError('Select a destination folder')
    result = parent / parts[-1]
    if result.exists() or result.is_symlink():
        raise FileAccessError('A file or folder already has that name. Rename it or move it to Trash first.')
    return result


def _mutable(api, key, relative, revision):
    if key != 'profile' or not _parts(relative):
        raise FileAccessError('Only game profile files can be changed here')
    target = _target(api, key, relative)
    config = Path(api.SERVER_CONFIG).resolve()
    if target == config or target.is_dir() and target in config.parents:
        raise FileAccessError('Use Server config to manage the main server configuration')
    if target.is_file() and os.path.samefile(target, config):
        raise FileAccessError('Use Server config to manage the main server configuration')
    if not target.is_dir() and not target.is_file():
        raise FileAccessError('Only regular files and folders can be changed')
    if revision != _fingerprint(target):
        raise FileAccessError('File or folder changed. Refresh before trying again.')
    return target


def _trash_root(api):
    return _root(api, 'profile') / '.panel-trash'


def _trash_entries(api):
    folder = _trash_root(api)
    if folder.is_symlink():
        raise FileAccessError('Trash location cannot be a link')
    entries = []
    if folder.exists():
        for record in folder.glob('*/record.json'):
            if record.parent.is_symlink() or record.is_symlink():
                continue
            try:
                data = json.loads(record.read_text(encoding='utf-8'))
                if (record.parent / 'content').exists():
                    entries.append(dict(token=record.parent.name, path=data['path'], deleted=data['deleted']))
            except (OSError, ValueError, KeyError):
                continue
    return sorted(entries, key=lambda row: row['deleted'], reverse=True)[:MAX_ENTRIES]


def install(api):
    app = api.app

    @app.errorhandler(413)
    def files_payload_too_large(error):
        return jsonify(ok=False, error='Upload is limited to 50 MiB per file' if request.endpoint == 'files_upload' else 'Request is too large'), 413

    @app.get('/api/files')
    def files_list():
        key = request.args.get('root', 'profile')
        relative = request.args.get('path', '')
        try:
            target = _target(api, key, relative)
            if key == 'server-config':
                entries = [dict(name=target.name, path='', directory=False,
                                size=target.stat().st_size, modified=target.stat().st_mtime,
                                editable=False, text=True, revision=_fingerprint(target))]
                return jsonify(root=key, path='', entries=entries, truncated=False)
            if not target.is_dir():
                raise FileAccessError('Select a folder')
            entries = []
            with os.scandir(target) as scanner:
                for entry in scanner:
                    if entry.name.startswith('.panel-') or entry.is_symlink():
                        continue
                    try:
                        folder = entry.is_dir(follow_symlinks=False)
                        if not folder and not entry.is_file(follow_symlinks=False):
                            continue
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    path = '/'.join(_parts(relative) + [entry.name])
                    entries.append(dict(name=entry.name, path=path, directory=folder,
                                        size=None if folder else info.st_size, modified=info.st_mtime,
                                        editable=not folder and _editable(api, key, Path(entry.path)),
                                        text=not folder and Path(entry.name).suffix.lower() in READ_SUFFIXES,
                                        revision=_fingerprint(Path(entry.path))))
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
            if not target.is_file():
                raise FileAccessError('Select a regular file to download')
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

    @app.post('/api/files/create')
    def files_create():
        data = request.get_json(silent=True) or {}
        try:
            target = _destination(api, data.get('root'), data.get('path'))
            kind = data.get('kind')
            if kind == 'folder':
                target.mkdir(mode=0o750)
            elif kind == 'file':
                if target.suffix.lower() not in EDIT_SUFFIXES:
                    raise FileAccessError('Choose a supported text file extension')
                with target.open('xb') as stream:
                    stream.write(b'{}\n' if target.suffix.lower() == '.json' else b'')
            else:
                raise FileAccessError('Choose file or folder')
            g.audit_details = dict(path=data['path'], kind=kind)
            return jsonify(ok=True)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.post('/api/files/upload')
    def files_upload():
        temporary = None
        try:
            data = request.form
            upload = request.files.get('file')
            if upload is None:
                raise FileAccessError('Select a file to upload')
            target = _destination(api, data.get('root'), data.get('path'),
                                  create_parents=data.get('create_parents') == 'true')
            fd, temporary = tempfile.mkstemp(prefix='.panel-upload-', dir=target.parent)
            total = 0
            with os.fdopen(fd, 'wb') as stream:
                while chunk := upload.stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise FileAccessError('Upload is limited to 50 MiB per file')
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o640)
            # Hard-link installation is atomic and never replaces an existing name.
            os.link(temporary, target)
            g.audit_details = dict(path=data['path'], size=total)
            return jsonify(ok=True)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @app.post('/api/files/rename')
    def files_rename():
        data = request.get_json(silent=True) or {}
        try:
            target = _mutable(api, data.get('root'), data.get('path'), data.get('revision'))
            destination = _destination(api, data.get('root'), data.get('destination'))
            if destination.parent != target.parent:
                raise FileAccessError('Rename keeps the file in its current folder')
            if target.is_file():
                os.link(target, destination)
                target.unlink()
            else:
                target.rename(destination)
            g.audit_details = dict(path=data['path'], destination=data['destination'])
            return jsonify(ok=True)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.post('/api/files/delete')
    def files_delete():
        data = request.get_json(silent=True) or {}
        try:
            target = _mutable(api, data.get('root'), data.get('path'), data.get('revision'))
            trash = _trash_root(api)
            if trash.is_symlink():
                raise FileAccessError('Trash location cannot be a link')
            record = trash / secrets.token_hex(16)
            record.mkdir(mode=0o700, parents=True)
            metadata = dict(path=data['path'], deleted=datetime.now(timezone.utc).isoformat())
            (record / 'record.json').write_text(json.dumps(metadata), encoding='utf-8')
            target.rename(record / 'content')
            g.audit_details = metadata
            return jsonify(ok=True, message='Moved to Trash', token=record.name)
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.get('/api/files/trash')
    def files_trash():
        try:
            return jsonify(ok=True, entries=_trash_entries(api))
        except (FileAccessError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.post('/api/files/restore')
    def files_restore():
        data = request.get_json(silent=True) or {}
        try:
            token = data.get('token')
            if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
                raise FileAccessError('Invalid Trash item')
            trash = _trash_root(api)
            record = trash / token
            if trash.is_symlink() or record.is_symlink() or (record / 'record.json').is_symlink() or (record / 'content').is_symlink():
                raise FileAccessError('Trash item cannot be a link')
            metadata = json.loads((record / 'record.json').read_text(encoding='utf-8'))
            destination = _destination(api, 'profile', metadata['path'])
            content = record / 'content'
            if content.is_file():
                os.link(content, destination)
                content.unlink()
            elif content.is_dir():
                content.rename(destination)
            else:
                raise FileAccessError('Trash item is unavailable')
            (record / 'record.json').unlink()
            record.rmdir()
            g.audit_details = dict(path=metadata['path'])
            return jsonify(ok=True)
        except (FileAccessError, OSError, ValueError, KeyError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
