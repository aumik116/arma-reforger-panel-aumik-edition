"""Public Workshop browsing and scoped, optimistic mod-change previews."""
import copy
import json
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener
from flask import g, jsonify, request
from config_editor import FIELDS, validate_value
from mod_metadata import NoRedirect
from mod_validation import normalize_mod_entry

CATEGORIES = 'TERRAINS WEAPONS VEHICLES STRUCTURES CHARACTERS ANIMALS VEGETATION PROPS COMPOSITIONS SCENARIOS_SP SCENARIOS_MP SYSTEMS EFFECTS MISC'.split()
SORTS = {'popularity', 'newest', 'subscribers', 'version_size'}


def mod_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{1,32}', value):
        raise ValueError('Invalid Workshop ID')
    return value.upper()


def normalize_asset(asset):
    image = None
    for preview in asset.get('previews', []):
        url = preview.get('url', '')
        parsed = urlparse(url)
        if parsed.scheme == 'https' and parsed.netloc == 'ar-gcp-cdn.bistudio.com' and parsed.path.startswith('/image/'):
            image = url
            break
    return dict(modId=mod_id(asset['id']), name=asset.get('name', ''),
                author=(asset.get('author') or {}).get('username', ''),
                description=asset.get('description') or asset.get('summary', ''),
                thumbnail=image, rating=asset.get('averageRating'), ratings=asset.get('ratingCount'),
                subscribers=asset.get('subscriberCount'), version=asset.get('currentVersionNumber', ''),
                size=asset.get('currentVersionSize'), tags=[t['name'] for t in asset.get('tags', [])],
                versions=[dict(version=v['version'], size=v.get('totalFileSize'), game=v.get('gameVersion'), date=v.get('createdAt'))
                          for v in asset.get('versions', []) if v.get('published') and v.get('approved')],
                dependencies=asset.get('dependencies', []))


class Workshop:
    def __init__(self):
        self.cache = {}
        self.plans = {}
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(4)

    def fetch(self, suffix):
        with self.lock:
            cached = self.cache.get(suffix)
            if cached and time.monotonic() - cached[0] < 300:
                return copy.deepcopy(cached[1])
        if not self.slots.acquire(blocking=False):
            raise ValueError('Workshop is busy. Try again shortly.')
        try:
            req = Request('https://reforger.armaplatform.com/workshop' + suffix,
                          headers={'User-Agent': 'ReforgerServerPanel/1.0', 'Accept': 'text/html'})
            with build_opener(NoRedirect).open(req, timeout=8) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('Workshop response too large')
            match = re.search(r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>', raw.decode(), re.S)
            data = json.loads(match.group(1))['props']['pageProps']
        except Exception as exc:
            raise ValueError('Workshop is unavailable. Try again shortly.') from exc
        finally:
            self.slots.release()
        with self.lock:
            self.cache[suffix] = (time.monotonic(), data)
            while len(self.cache) > 128:
                self.cache.pop(next(iter(self.cache)))
        return copy.deepcopy(data)

    def catalog(self, search='', sort='popularity', category='', page='1'):
        if not isinstance(search, str) or len(search) > 120 or sort not in SORTS or category and category not in CATEGORIES:
            raise ValueError('Invalid Workshop filters')
        if not str(page).isdigit() or not 1 <= int(page) <= 10000:
            raise ValueError('Invalid page')
        params = dict(search=search, sort=sort, page=int(page))
        if category:
            params['tags'] = category
        data = self.fetch('?' + urlencode(params))['assets']
        return dict(items=[normalize_asset(a) for a in data['rows']], count=data['count'], page=int(page))

    def detail(self, value):
        value = mod_id(value)
        data = self.fetch('/' + value)
        asset = normalize_asset(data['asset'])
        if asset['modId'] != value:
            raise ValueError('Workshop ID mismatch')
        asset['scenarios'] = []
        if 'TERRAINS' in {tag.upper() for tag in asset['tags']}:
            for scenario in (data.get('assetVersionDetail') or {}).get('scenarios', []):
                resource = scenario.get('gameId', '')
                try:
                    validate_value(FIELDS['game.scenarioId'], resource)
                except ValueError:
                    continue
                asset['scenarios'].append(dict(id=resource, name=scenario.get('name') or resource,
                    description=scenario.get('description', ''), mode=scenario.get('gameMode', ''), players=scenario.get('playerCount')))
        return asset

    def preview(self, current, identity, value, action, version='', dependencies=False, scenario='', current_scenario=''):
        asset = self.detail(value)
        value = asset['modId']
        if action not in {'add', 'remove'} or type(dependencies) is not bool:
            raise ValueError('Invalid mod action')
        if version and version not in {v['version'] for v in asset['versions']}:
            raise ValueError('This release is not published')
        if dependencies and version and version != asset['version']:
            raise ValueError('Dependency versions are only verified for the latest release. Select Latest or manage dependencies separately.')
        if scenario:
            if action != 'add' or scenario not in {row['id'] for row in asset.get('scenarios', [])}:
                raise ValueError('This scenario is not published by this terrain mod')
            existing = next((m for m in current if str(m.get('modId', '')).upper() == value), None)
            if existing and existing.get('version') and existing['version'] != asset['version']:
                raise ValueError('Scenario metadata describes the latest release. Update this terrain mod before selecting its scenarios.')
            dependencies = True
            version = existing.get('version', '') if existing else ''
        result = copy.deepcopy(current)
        notes = []
        if action == 'remove':
            result = [m for m in result if str(m.get('modId', '')).upper() != value]
            notes.append('Dependencies are retained because other mods may require them. Remove unused dependencies individually.')
        else:
            entries = []
            seen = {}
            def visit(nodes, depth=0):
                if depth > 32:
                    raise ValueError("Dependency tree is too deep")
                for node in nodes:
                    dep = node.get('asset') or {}
                    key = mod_id(dep.get('id', ''))
                    if key == value:
                        raise ValueError('Circular dependency metadata')
                    if key in seen:
                        if seen[key] != node.get('version', ''):
                            raise ValueError('Dependencies require conflicting versions')
                        continue
                    seen[key] = node.get('version', '')
                    if len(seen) > 256:
                        raise ValueError('Dependency tree is too large')
                    if node.get('blocked') or node.get('private') or not node.get('published'):
                        raise ValueError('A required dependency is not publicly available')
                    visit(node.get('dependencies', []), depth + 1)
                    entry = normalize_mod_entry(dict(modId=key, name=dep.get('name', ''), version=node.get('version', '')))
                    if entry is None:
                        raise ValueError('Invalid dependency metadata')
                    existing = next((m for m in current if str(m.get('modId', '')).upper() == key), None)
                    if existing and existing.get('version') and existing['version'] != entry.get('version'):
                        raise ValueError('A dependency has a different pinned version. Resolve its pin before adding dependencies.')
                    if not existing:
                        entries.append(entry)
            if dependencies:
                visit(asset['dependencies'])
            root = normalize_mod_entry(dict(modId=value, name=asset['name'], version=version))
            if root is None:
                raise ValueError('Invalid Workshop mod metadata')
            result = [root if str(m.get('modId', '')).upper() == value else m for m in result]
            if not any(str(m.get('modId', '')).upper() == value for m in current):
                result.append(root)
            result.extend(entries)
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.plans[token] = (time.monotonic(), identity, copy.deepcopy(current), result, current_scenario, scenario)
            while len(self.plans) > 64:
                self.plans.pop(next(iter(self.plans)))
        return dict(ok=True, token=token, mods=result, notes=notes, scenario=scenario)

    def apply(self, token, identity, current, current_scenario=None, configure=False, with_scenario=False):
        if not isinstance(token, str):
            raise ValueError('Preview the change first')
        with self.lock:
            plan = self.plans.get(token)
            if not plan or time.monotonic() - plan[0] > 300 or plan[1] != identity:
                raise ValueError('Preview expired. Preview the change again.')
            if plan[2] != current:
                raise ValueError('The mod list changed. Preview the change again.')
            if plan[5]:
                if not configure:
                    raise ValueError('Changing scenarios requires server configuration permission')
                if plan[4] != current_scenario:
                    raise ValueError('The scenario changed. Preview the change again.')
            return (copy.deepcopy(plan[3]), plan[5]) if with_scenario else copy.deepcopy(plan[3])


def install(api):
    api.workshop = Workshop()
    def identity():
        instance = api.selected_instance()
        return (g.user['id'], instance.id if instance else '')

    @api.app.get('/api/mods/workshop')
    def workshop_catalog():
        try:
            return jsonify(ok=True, **api.workshop.catalog(request.args.get('search', ''), request.args.get('sort', 'popularity'), request.args.get('category', ''), request.args.get('page', '1')))
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get('/api/mods/workshop/<value>')
    def workshop_detail(value):
        try:
            return jsonify(ok=True, asset=api.workshop.detail(value))
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get('/api/mods/workshop/<value>/preview')
    def workshop_preview(value):
        try:
            cfg = api.read_config()
            scenario = request.args.get('scenario', '')
            if scenario and 'configure' not in g.permissions:
                return jsonify(ok=False, error='Changing scenarios requires server configuration permission'), 403
            return jsonify(api.workshop.preview(cfg.get('game', {}).get('mods', []), identity(), value,
                request.args.get('action', 'add'), request.args.get('version', ''), request.args.get('dependencies') == '1',
                scenario, cfg.get('game', {}).get('scenarioId', '')))
        except (ValueError, KeyError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post('/api/mods/workshop/apply')
    def workshop_apply():
        try:
            cfg = api.read_config()
            token = (request.get_json(silent=True) or {}).get('token')
            mods, scenario = api.workshop.apply(token, identity(), cfg.get('game', {}).get('mods', []),
                cfg.get('game', {}).get('scenarioId', ''), 'configure' in g.permissions, with_scenario=True)
            if scenario:
                cfg.setdefault('game', {})['scenarioId'] = scenario
            cfg.setdefault('game', {})['mods'] = mods
            api.write_config(cfg)
            return jsonify(ok=True, mods=mods, restart_required=api.get_server_pid() is not None)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        except OSError:
            return jsonify(ok=False, error='Could not save the mod list'), 503
