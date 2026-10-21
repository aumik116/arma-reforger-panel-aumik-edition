"""Read-only inventory of the selected server's downloaded Workshop assets."""
import json
import os
from pathlib import Path
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from storage_usage import scan_storage


def mod_id(value):
    return value.upper() if isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{1,32}', value) else None


def read_metadata(folder):
    path = folder / 'meta'
    if path.is_symlink():
        return {}
    try:
        with path.open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return {}
        data = json.loads(raw.decode('utf-8-sig'))
        meta = data.get('meta', data)
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError, UnicodeError, AttributeError):
        return {}


def dependency_ids(nodes):
    if not isinstance(nodes, list):
        return None
    result = set()
    pending = list(nodes)
    visited = 0
    while pending:
        node = pending.pop(); visited += 1
        if visited > 1024:
            return None
        if isinstance(node, str):
            identity = mod_id(node)
        elif isinstance(node, dict):
            asset = node.get('asset') or {}
            identity = mod_id(node.get('modId') or node.get('id') or (asset.get('id') if isinstance(asset, dict) else None))
            nested = node.get('dependencies', [])
            if not isinstance(nested, list):
                return None
            pending.extend(nested)
        else:
            return None
        if not identity:
            return None
        result.add(identity)
    return sorted(result)


def scan_downloads(root):
    root = Path(root).absolute()
    if root.resolve() != root:
        raise ValueError('Workshop directory redirects through a link; inventory is unavailable.')
    if not root.is_dir():
        return dict(mods=[], partial=False, checked=time.time(), message='The configured Workshop directory does not exist yet.')
    rows = []; partial = False; visited = 0
    pending = [(root, 0)]; deadline = time.monotonic() + 10
    while pending:
        folder, depth = pending.pop()
        if time.monotonic() >= deadline or visited >= 10000 or len(rows) >= 1000:
            partial = True; break
        visited += 1
        if folder.is_symlink():
            partial = True; continue
        try:
            meta = read_metadata(folder)
            identity = mod_id(meta.get('id') or meta.get('modId'))
            suffix = re.search(r'(?:^|_)([0-9a-fA-F]{8,32})$', folder.name)
            if not identity and suffix:
                identity = suffix[1].upper()
            has_assets = any((folder / marker).is_file() and not (folder / marker).is_symlink()
                             for marker in ('meta', 'addon.gproj', 'data.pak', 'resourceDatabase.rdb'))
            if folder != root and (has_assets or identity):
                versions = meta.get('versions')
                version = versions[0] if isinstance(versions, list) and versions and isinstance(versions[0], dict) else {}
                raw_version = version.get('version') or meta.get('version') or ''
                deps = version.get('dependencies', meta.get('dependencies'))
                name = meta.get('name')
                rows.append(dict(modId=identity, name=name[:200] if isinstance(name, str) and name else folder.name,
                                 path=folder.relative_to(root).as_posix(), version=str(raw_version)[:64],
                                 dependencies=dependency_ids(deps)))
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if visited >= 10000 or time.monotonic() >= deadline:
                        partial = True; break
                    if entry.is_symlink():
                        partial = True; continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < 4:
                            pending.append((Path(entry.path), depth + 1))
                        else:
                            partial = True
        except OSError:
            partial = True
    sizes = scan_storage([(str(i), row['name'], root / row['path']) for i,row in enumerate(rows)], seconds=10, max_entries=100000)
    for size, row in zip(sizes['categories'], rows):
        row.update(bytes=size['bytes'], size_partial=bool(size['partial'] or size['errors']))
    partial = partial or sizes['status'] != 'ready'
    return dict(mods=rows, partial=partial, checked=time.time(), message='')


def classify(inventory, configured):
    direct = {str(mod.get('modId', '')).upper() for mod in configured}
    by_id = {}
    for row in inventory['mods']:
        if row['modId']:
            by_id.setdefault(row['modId'], []).append(row)
    required = set(direct); pending = list(direct)
    complete = not inventory['partial']
    for mod in configured:
        wanted = mod.get('version')
        candidates = by_id.get(str(mod.get('modId', '')).upper(), [])
        if wanted and not any(row['version'] == wanted for row in candidates):
            complete = False
    while pending:
        identity = pending.pop()
        candidates = by_id.get(identity, [])
        if not candidates:
            complete = False
        for row in candidates:
            deps = row['dependencies']
            if deps is None:
                complete = False; continue
            for dependency in deps:
                if dependency not in required:
                    required.add(dependency); pending.append(dependency)
    result = []
    for row in inventory['mods']:
        identity = row['modId']
        usage = 'configured' if identity in direct else 'dependency' if identity in required else 'not_required' if identity and complete else 'unverified'
        public = {key:value for key,value in row.items() if key != 'dependencies'}
        result.append(dict(public, usage=usage, configured=identity in direct))
    return dict(inventory, mods=result, dependencies_complete=complete)


def install(api):
    from flask import jsonify, request
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mod-inventory')
    cache = {}; lock = threading.Lock()

    @api.app.get('/api/mods/downloaded')
    def mods_downloaded():
        instance = api.selected_instance()
        key = instance.id if instance else ''
        root = str(api.WORKSHOP_DIR)
        with lock:
            previous = cache.get(key)
            if previous and not previous[1].done():
                return jsonify(ok=True, status='pending')
            if previous and previous[2] == root and request.args.get('refresh') != '1' and time.monotonic()-previous[0] < 300:
                try:
                    inventory = previous[1].result()
                except (ValueError, OSError):
                    return jsonify(ok=False, error='Could not inspect the configured Workshop directory.'), 409
            else:
                if sum(not item[1].done() for item in cache.values()) >= 8:
                    return jsonify(ok=False, error='Inventory scanner is busy. Try again shortly.'), 503
                cache[key] = (time.monotonic(), pool.submit(scan_downloads, root), root)
                for old in list(cache):
                    if len(cache) > 128 and cache[old][1].done():
                        cache.pop(old)
                return jsonify(ok=True, status='pending')
        return jsonify(ok=True, status='ready', **classify(inventory, api.read_config().get('game', {}).get('mods', [])))
