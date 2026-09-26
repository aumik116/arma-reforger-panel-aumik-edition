"""Read public ArmaHQ snapshots and apply explicitly selected mod differences."""
import copy
from mod_validation import normalize_mod_entry
import json
import re
import secrets
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://www.armahq.com'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class StaleComparison(ValueError):
    pass


def server_id(reference):
    if not isinstance(reference, str):
        raise ValueError('Paste an ArmaHQ server URL')
    reference = reference.strip()
    if re.fullmatch(UUID, reference, re.I):
        return reference.lower()
    parsed = urlparse(reference)
    if parsed.scheme != 'https' or parsed.netloc.lower() not in {'armahq.com', 'www.armahq.com'}:
        raise ValueError('Use an https://www.armahq.com/servers/… URL')
    match = re.fullmatch('/servers/(' + UUID + ')/?', parsed.path, re.I)
    if not match:
        raise ValueError('The URL must point to an individual ArmaHQ server')
    return match.group(1).lower()


def normalize_remote_mods(mods, source='ArmaHQ'):
    if not isinstance(mods, list) or len(mods) > 2000:
        raise ValueError(f'{source} must contain a complete mod array (maximum 2,000 mods)')
    result, seen = [], set()
    for item in mods:
        normalized = normalize_mod_entry(item)
        if normalized is None:
            raise ValueError(f'{source} contains an invalid mod ID, name or version')
        mod_id = normalized['modId']
        if mod_id in seen:
            raise ValueError(f'{source} contains duplicate mod IDs; remove duplicates before comparing')
        seen.add(mod_id)
        normalized.setdefault('name', mod_id)
        result.append(normalized)
    return result


def parse_server_page(html, expected_id):
    # Decode Next.js flight strings as JSON. Never evaluate website scripts.
    parts = []
    for script in re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S | re.I):
        match = re.search(r'self\.__next_f\.push\((\[.*\])\)\s*;?$', script.strip(), re.S)
        if match:
            try:
                frame = json.loads(match.group(1))
                if len(frame) >= 2 and isinstance(frame[1], str):
                    parts.append(frame[1])
            except (ValueError, TypeError):
                continue
    flight = ''.join(parts)
    for match in re.finditer(r'"initialServer"\s*:\s*', flight):
        try:
            record, _ = json.JSONDecoder().raw_decode(flight[match.end():])
        except ValueError:
            continue
        if not isinstance(record, dict) or str(record.get('id', '')).lower() != expected_id:
            continue
        mods = normalize_remote_mods(record.get('mods'))
        count = record.get('modCount')
        if type(count) is int and count != len(mods):
            raise ValueError('ArmaHQ mod list is incomplete; no changes can be made')
        return {'id': expected_id, 'name': str(record.get('name') or expected_id)[:256],
                'address': str(record.get('hostAddress') or '')[:128],
                'updated': record.get('detailsUpdatedAt') or record.get('updatedAt'),
                'url': BASE + '/servers/' + expected_id, 'mods': mods}
    raise ValueError('ArmaHQ server details are unavailable or its page format has changed')


def differences(local, remote):
    ours = {str(m.get('modId', '')).upper(): m for m in local}
    theirs = {m['modId']: m for m in remote}
    return {'missing': [m for key, m in theirs.items() if key not in ours],
            'extra': [{**m, 'modId': key} for key, m in ours.items() if key not in theirs],
            'versions': [{'modId': key, 'name': m.get('name') or ours[key].get('name') or key,
                          'localVersion': ours[key].get('version', ''), 'remoteVersion': m['version']}
                         for key, m in theirs.items() if key in ours and m.get('version') and m['version'] != ours[key].get('version', '')],
            'shared': len(ours.keys() & theirs.keys())}


class ArmaHQCompare:
    def __init__(self):
        self.lock = threading.RLock()
        self.cache = {}
        self.snapshots = {}

    def _fetch(self, path, limit=8 * 1024 * 1024):
        with self.lock:
            cached = self.cache.get(path)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
        # Network I/O must not hold the snapshot lock used by reviewed changes.
        request = Request(BASE + path, headers={'User-Agent': 'ArmaReforgerPanel/3.0', 'Accept': 'application/json,text/html'})
        try:
            with build_opener(NoRedirect).open(request, timeout=12) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('ArmaHQ response is too large')
            result = raw.decode('utf-8')
        except (OSError, UnicodeError) as exc:
            raise ValueError('Could not reach ArmaHQ. Try again later or check the server URL.') from exc
        with self.lock:
            self.cache[path] = (time.monotonic(), result)
            while len(self.cache) > 32:
                self.cache.pop(next(iter(self.cache)))
            return result

    def search(self, query):
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 120:
            raise ValueError('Enter at least two characters of a server name or address')
        data = json.loads(self._fetch('/api/servers/list'))
        records = data if isinstance(data, list) else data.get('servers') if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise ValueError('ArmaHQ server search is unavailable')
        query = query.strip().casefold()
        found = []
        for record in records:
            if not isinstance(record, dict) or not re.fullmatch(UUID, str(record.get('id', '')), re.I):
                continue
            name, address = str(record.get('name', '')), str(record.get('hostAddress', ''))
            if query not in (name + ' ' + address).casefold():
                continue
            found.append({'id': record['id'], 'name': name[:256], 'address': address[:128],
                          'players': record.get('playerCount'), 'modCount': record.get('modCount')})
        return {'servers': found[:30], 'total': len(found)}

    def compare(self, reference, local, owner):
        sid = server_id(reference)
        server = parse_server_page(self._fetch('/servers/' + sid), sid)
        return self._comparison(server, local, owner)

    def compare_json(self, payload, local, owner):
        if isinstance(payload, str):
            if len(payload) > 200000:
                raise ValueError('Pasted JSON is too large (maximum 200 KB)')
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise ValueError('Paste valid JSON: a mod array or a server config containing game.mods') from exc
        if isinstance(payload, dict):
            game = payload.get('game')
            payload = game.get('mods') if isinstance(game, dict) else payload.get('mods')
        mods = normalize_remote_mods(payload, 'Pasted JSON')
        return self._comparison({'id': None, 'name': 'Pasted JSON', 'url': None,
                                 'address': '', 'updated': None, 'mods': mods}, local, owner)

    def _comparison(self, server, local, owner):
        diff = differences(local, server['mods'])
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.snapshots = {k: v for k, v in self.snapshots.items() if time.monotonic() - v['at'] < 900}
            while len(self.snapshots) >= 64:
                self.snapshots.pop(next(iter(self.snapshots)))
            self.snapshots[token] = {'at': time.monotonic(), 'owner': owner,
                                     'local': copy.deepcopy(local), 'server': server, 'diff': diff}
        return {'token': token, 'localMods': copy.deepcopy(local), 'server': {k: v for k, v in server.items() if k != 'mods'},
                'remoteCount': len(server['mods']), 'comparedAt': time.time(), **diff}

    def apply(self, token, selected, local, owner):
        with self.lock:
            snapshot = self.snapshots.get(token) if isinstance(token, str) else None
            if not snapshot or snapshot['owner'] != owner or time.monotonic() - snapshot['at'] >= 900:
                raise StaleComparison('Comparison expired. Compare the server again before applying changes.')
            if local != snapshot['local']:
                raise StaleComparison('Your mod list changed. Compare again before applying changes.')
            if not isinstance(selected, dict):
                raise ValueError('Choose individual mod changes')
            choices = {}
            for kind in ('missing', 'extra', 'versions'):
                ids = selected.get(kind, [])
                if not isinstance(ids, list) or len(ids) > 2000 or any(not isinstance(i, str) for i in ids):
                    raise ValueError('Invalid selected mod IDs')
                choices[kind] = {i.upper() for i in ids}
                allowed = {m['modId'] for m in snapshot['diff'][kind]}
                if not choices[kind] <= allowed:
                    raise StaleComparison('Selected changes do not match this comparison. Compare again.')
            if not any(choices.values()):
                raise ValueError('Select at least one change')
            remote = {m['modId']: m for m in snapshot['server']['mods']}
            mods = []
            for mod in local:
                key = str(mod.get('modId', '')).upper()
                if key in choices['extra']:
                    continue
                item = copy.deepcopy(mod)
                if key in choices['versions']:
                    item['version'] = remote[key]['version']
                mods.append(item)
            mods.extend(copy.deepcopy(m) for m in snapshot['server']['mods'] if m['modId'] in choices['missing'])
            return mods, {kind: len(ids) for kind, ids in choices.items()}
