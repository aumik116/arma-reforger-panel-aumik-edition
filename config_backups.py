"""Private snapshots of the server JSON before panel-managed writes."""
import difflib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path


MAX_BACKUPS = 20
NAME_RE = re.compile(r'^\d{8}T\d{12}Z-[0-9a-f]{8}\.json$')


def _directory(config_path, create=False):
    target = Path(config_path).resolve().parent / '.panel-config-backups'
    if target.is_symlink():
        raise ValueError('Configuration backup directory cannot be a link')
    if create:
        target.mkdir(mode=0o700, exist_ok=True)
        os.chmod(target, 0o700)
    if target.exists() and not target.is_dir():
        raise ValueError('Configuration backup location is not a directory')
    return target


def _files(config_path):
    directory = _directory(config_path)
    if not directory.exists():
        return []
    return sorted((item for item in directory.iterdir() if NAME_RE.fullmatch(item.name) and item.is_file() and not item.is_symlink()),
                  key=lambda item: item.name, reverse=True)


def backup_current(config_path):
    """Keep the existing bytes before a write; abort the write if backup fails."""
    source = Path(config_path)
    if not source.exists():
        return None
    original = source.read_bytes()
    directory = _directory(config_path, create=True)
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + secrets.token_hex(4) + '.json'
    target = directory / name
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    for old in _files(config_path)[MAX_BACKUPS:]:
        old.unlink()
    return name


def list_backups(config_path):
    result = []
    for path in _files(config_path):
        try:
            config = json.loads(path.read_text(encoding='utf-8-sig'))
            game = config['game']
            result.append(dict(name=path.name, created_at=path.stat().st_mtime,
                               scenario=game.get('scenarioId', ''), mod_count=len(game.get('mods', []))))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def load_backup(config_path, name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError('Invalid configuration backup')
    path = _directory(config_path) / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('Configuration backup not found')
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict) or not isinstance(config.get('game'), dict):
            raise ValueError('Invalid configuration backup')
        return config
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Cannot read configuration backup') from exc


def preview(current, backup):
    before = json.dumps(current, indent=2, ensure_ascii=False).splitlines()
    after = json.dumps(backup, indent=2, ensure_ascii=False).splitlines()
    diff = '\n'.join(difflib.unified_diff(before, after, fromfile='Current config', tofile='Selected backup', lineterm=''))
    return diff[:120000], len(diff) > 120000
