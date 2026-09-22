"""Typed configuration edits; preserve unknown keys and reject stale drafts."""
import copy
import hashlib
import ipaddress
import json
import re


def field(path, label, kind='text', **options):
    return dict(path=path, label=label, kind=kind, **options)


GROUPS = [
    dict(title='Identity', description='Name and scenario shown to your players.', fields=[
        field('game.name', 'Server name', maximum=100, required=True),
        field('game.scenarioId', 'Scenario', 'scenario', required=True,
              help='Choose an installed scenario or enter its full {GUID}Missions/… .conf resource.'),
        field('game.visible', 'Listed in server browser', 'bool', default=True),
    ]),
    dict(title='Access', description='Player slots, platforms and passwords.', fields=[
        field('game.maxPlayers', 'Maximum players', 'int', minimum=1, maximum=128, default=64),
        field('game.crossPlatform', 'Crossplay', 'bool', default=False,
              help='Accept all platforms. Existing supportedPlatforms settings remain untouched.'),
        field('game.password', 'Join password', 'password', help='Empty means no join password.'),
        field('game.passwordAdmin', 'Administrator password', 'password', no_spaces=True),
        field('game.admins', 'In-game administrators', 'admins',
              help='One UUID or 17-digit Steam ID per line. Up to 20 unique entries.'),
    ]),
    dict(title='Network', description='Game and query endpoints. Port changes require matching firewall rules.', fields=[
        field('bindAddress', 'Bind address', 'address', help='Empty lets the engine choose the interface.'),
        field('bindPort', 'Bind port · UDP', 'int', minimum=1, maximum=65535, default=2001),
        field('publicAddress', 'Public address', 'address', allow_local=True, help='Empty uses automatic detection; local uses the local interface.'),
        field('publicPort', 'Public port · UDP', 'int', minimum=1, maximum=65535, default=2001),
        field('a2s.address', 'A2S bind address', 'address'),
        field('a2s.port', 'A2S query port · UDP', 'int', minimum=1, maximum=65535, default=17777),
    ]),
    dict(title='Gameplay', description='Visibility, anti-cheat, camera and voice settings.', fields=[
        field('game.gameProperties.battlEye', 'BattlEye', 'bool', default=True),
        field('game.gameProperties.disableThirdPerson', 'Force first person', 'bool', default=False),
        field('game.gameProperties.serverMaxViewDistance', 'View distance · m', 'int', minimum=500, maximum=10000, default=1600),
        field('game.gameProperties.networkViewDistance', 'Network view distance · m', 'int', minimum=500, maximum=5000, default=1500),
        field('game.gameProperties.serverMinGrassDistance', 'Minimum grass distance · m', 'int', minimum=0, maximum=150, default=0, help='Use 0 for client choice, or 50–150 metres.'),
        field('game.gameProperties.fastValidation', 'Fast validation', 'bool', default=True, help='Keep enabled for public servers.'),
        field('game.gameProperties.VONDisableUI', 'Hide voice UI', 'bool', default=False),
        field('game.gameProperties.VONDisableDirectSpeechUI', 'Hide direct speech UI', 'bool', default=False),
        field('game.gameProperties.VONCanTransmitCrossFaction', 'Cross-faction radio transmission', 'bool', default=False),
    ]),
    dict(title='Remote console', description='RCON uses UDP. Restrict its interface and firewall access to trusted administrators.', fields=[
        field('rcon.address', 'RCON bind address', 'address'),
        field('rcon.port', 'RCON port · UDP', 'int', minimum=1, maximum=65535, default=19999),
        field('rcon.password', 'RCON password', 'password', no_spaces=True, minimum=3, help='At least 3 characters, without spaces. Required when configuring RCON.'),
        field('rcon.permission', 'RCON permission', 'choice', choices=['monitor', 'admin']),
        field('rcon.maxClients', 'Maximum RCON clients', 'int', minimum=1, maximum=16, default=16),
        field('rcon.whitelist', 'Command whitelist', 'lines', help='One command per line. A nonempty list allows only listed commands.'),
        field('rcon.blacklist', 'Command blacklist', 'lines', help='One command per line.'),
    ]),
    dict(title='Operating', description='AI, player saving and backend synchronization.', fields=[
        field('operating.disableAI', 'Disable AI', 'bool', default=False),
        field('operating.aiLimit', 'AI limit', 'int', minimum=-1, maximum=2147483647, default=-1, help='-1 uses no explicit limit.'),
        field('operating.playerSaveTime', 'Player save interval · seconds', 'int', minimum=0, maximum=2147483647, default=120),
        field('operating.lobbyPlayerSynchronise', 'Synchronize lobby players', 'bool', default=True),
        field('operating.disableServerShutdown', 'Keep running after backend disconnect', 'bool', default=False),
    ]),
    dict(title='Persistence', description='Save timing and retention depend on scenario support. The launch command still includes -loadSessionSave.', fields=[
        field('game.gameProperties.persistence.autoSaveInterval', 'Auto-save interval · minutes', 'int', minimum=0, maximum=60, default=10, help='0 disables periodic auto-saves, not all persistence.'),
        field('game.gameProperties.persistence.saveRetention', 'Save points to retain', 'int', minimum=1, maximum=128, default=10),
        field('game.gameProperties.persistence.loadSessionSave', 'Load latest session', 'bool', default=True, help='The existing launch flag also requests session loading.'),
        field('game.gameProperties.persistence.keepSessionSave', 'Keep saves after mission completion', 'bool', default=False),
        field('game.gameProperties.persistence.hiveId', 'Hive ID', 'int', minimum=0, maximum=16383, default=0),
    ]),
]
FIELDS = {item['path']: item for group in GROUPS for item in group['fields']}


def revision(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def validate_value(spec, value):
    label = spec['label']
    kind = spec['kind']
    if value is None:
        if spec.get('required'):
            raise ValueError(f'{label} cannot be removed')
        return
    if kind == 'bool':
        if type(value) is not bool:
            raise ValueError(f'{label} must be true or false')
    elif kind == 'int':
        if type(value) is not int or not spec['minimum'] <= value <= spec['maximum']:
            raise ValueError(f"{label} must be an integer from {spec['minimum']} to {spec['maximum']}")
        if spec['path'].endswith('serverMinGrassDistance') and 0 < value < 50:
            raise ValueError('Grass distance must be 0 or 50–150')
    elif kind in ('lines', 'admins'):
        if not isinstance(value, list) or len(value) > (20 if kind == 'admins' else 128):
            raise ValueError(f'{label}: too many entries or invalid list')
        for entry in value:
            if not isinstance(entry, str) or not entry or len(entry) > 200 or any(c in entry for c in '\r\n\x00'):
                raise ValueError(f'{label}: invalid entry')
            if kind == 'admins' and not re.fullmatch(r'(?:[0-9]{17}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', entry):
                raise ValueError('Administrator IDs must be UUIDs or 17-digit Steam IDs')
        if len(set(value)) != len(value):
            raise ValueError(f'{label}: duplicate entries')
    else:
        if not isinstance(value, str) or len(value) > spec.get('maximum', 2048) or any(c in value for c in '\r\n\x00'):
            raise ValueError(f'{label}: invalid text')
        if spec.get('required') and not value.strip():
            raise ValueError(f'{label} cannot be empty')
        if spec.get('no_spaces') and any(c.isspace() for c in value):
            raise ValueError(f'{label} cannot contain spaces')
        if len(value) < spec.get('minimum', 0):
            raise ValueError(f"{label} needs at least {spec['minimum']} characters")
        if kind == 'choice' and value not in spec['choices']:
            raise ValueError(f'{label}: invalid choice')
        if kind == 'address' and value and not (value == 'local' and spec.get('allow_local')):
            try:
                ipaddress.IPv4Address(value)
            except ValueError:
                raise ValueError(f'{label} must be an IPv4 address or empty') from None
        if kind == 'scenario' and not re.fullmatch(r'\{[0-9a-fA-F]{16}\}[^\r\n]+\.conf', value):
            raise ValueError('Scenario must be a full {16-digit GUID} resource ending in .conf')


def apply_changes(config, changes):
    if not isinstance(changes, dict) or len(changes) > len(FIELDS):
        raise ValueError('Changes must be a field map')
    result = copy.deepcopy(config)
    for path, value in changes.items():
        if path not in FIELDS:
            raise ValueError(f'Unsupported configuration field: {path}')
        validate_value(FIELDS[path], value)
        parts = path.split('.')
        parent = result
        for key in parts[:-1]:
            if key not in parent:
                if value is None:
                    parent = None
                    break
                parent[key] = {}
            if not isinstance(parent[key], dict):
                raise ValueError(f'{key} must be an object; existing configuration was not changed')
            parent = parent[key]
        if parent is not None:
            if value is None:
                parent.pop(parts[-1], None)
            else:
                parent[parts[-1]] = value
    for section in ('rcon', 'a2s'):
        if any(p.startswith(section + '.') for p in changes) and result.get(section):
            block = result[section]
            if 'address' not in block:
                raise ValueError(f'{section.upper()} requires a bind address (empty is allowed)')
            if section == 'rcon':
                validate_value(FIELDS['rcon.password'], block.get('password', ''))
    return result


def install(api):
    from flask import jsonify, request

    def read_strict():
        with open(api.SERVER_CONFIG, encoding='utf-8-sig') as handle:
            config = json.load(handle)
        if not isinstance(config, dict) or not isinstance(config.get('game'), dict):
            raise ValueError('Configuration must contain a game object')
        return config

    @api.app.get('/api/config/editor')
    def config_editor_get():
        try:
            config = read_strict()
            return jsonify(config=config, revision=revision(config), groups=GROUPS,
                           missions=api.all_scenarios_cached(), admin_labels=api.get_admin_labels(),
                           rcon_overridden=any(api._cfg.get(k) for k in ('RCON_HOST', 'RCON_PORT', 'RCON_PASSWORD')))
        except (ValueError, OSError):
            return jsonify(ok=False, error='Cannot read a valid server configuration. Repair the file before editing.'), 400

    def edit(save):
        data = request.get_json(silent=True) or {}
        try:
            config = read_strict()
            if data.get('revision') != revision(config):
                return jsonify(ok=False, error='Configuration changed since you loaded it. Reload before saving; your draft has been kept.'), 409
            updated = apply_changes(config, data.get('changes'))
            if save:
                api.write_config(updated)
            return jsonify(ok=True, config=updated, revision=revision(updated), restart_required=save)
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400
        except OSError:
            return jsonify(ok=False, error='Unable to read or write the configuration file.'), 500

    @api.app.post('/api/config/editor')
    def config_editor_save():
        return edit(True)

    @api.app.post('/api/config/validate')
    def config_editor_validate():
        return edit(False)
