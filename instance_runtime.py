"""Request-local server selection without mutating process-wide settings."""
from pathlib import Path
import threading

from flask import g, has_request_context, jsonify, request
from werkzeug.local import LocalProxy

from server_registry import ServerRegistry


class ScopedPath:
    """A request-local path with no integer protocol (unlike LocalProxy)."""
    def __init__(self, getter):
        self.getter = getter

    def __fspath__(self):
        return str(self.getter())

    def __str__(self):
        return self.__fspath__()

    def __bool__(self):
        return bool(self.getter())

    def __getattr__(self, name):
        return getattr(str(self), name)


def install(api):
    panel_settings = dict(api._cfg)
    database = panel_settings.get('PANEL_DATA_FILE', str(Path(api._BASE_DIR) / '.panel-data.sqlite3'))
    registry = ServerRegistry(database, panel_settings.get('INSTANCE_ROOT', str(Path(api._BASE_DIR) / 'instances')))
    api.server_registry = registry
    states, state_lock = {}, threading.Lock()

    def selected():
        return getattr(g, 'server_instance', None) if has_request_context() else None

    def state_value(key, factory, default):
        instance = selected()
        if instance is None:
            return default
        with state_lock:
            state = states.setdefault(instance.id, {})
            if key not in state:
                state[key] = factory()
            return state[key]

    def scoped(key, factory, default):
        return LocalProxy(lambda: state_value(key, factory, default))

    api.instance_scoped = scoped
    api.selected_instance = selected
    def clear_state(server_id):
        with state_lock:
            states.pop(server_id, None)
    api.clear_instance_state = clear_state
    for setting, path in [('SERVER_DIR', 'server'), ('SERVER_CONFIG', 'config'),
                          ('LOG_DIR', 'logs'), ('PROFILE_DIR', 'profile'), ('WORKSHOP_DIR', 'workshop')]:
        default = getattr(api, setting)
        setattr(api, setting, ScopedPath(lambda path=path, default=default:
            str(selected().paths[path]) if selected() else default))
    api._STATE_DIR = ScopedPath(lambda: str(selected().directory) if selected() else api._BASE_DIR)

    def settings():
        instance = selected()
        if instance is None:
            return panel_settings
        # Never inherit another server's RCON credentials, telemetry or file roots.
        result = {key: value for key, value in panel_settings.items()
                  if key in ('STEAMCMD_PATH', 'PANEL_DATA_FILE')}
        result.update(FILE_BACKUP_DIR=str(instance.paths['backups']),
                      GAME_TELEMETRY_FILE=str(instance.directory / 'telemetry.json'),
                      MAX_FPS=str(instance.max_fps) if instance.max_fps else '')
        return result

    api._cfg = LocalProxy(settings)
    api._SCAN_CACHE_FILE = ScopedPath(lambda: str(Path(api._STATE_DIR) / '.scenario-cache.json'))
    for key, factory in [('_SCAN_LOCK', threading.Lock),
                         ('_LAST_SCAN_RESULT', lambda: {'scenarios': [], 'diag': None, 'ts': 0.0}),
                         ('_process_metrics', api.ProcessMetrics), ('_traffic_metrics', api.TrafficMetrics),
                         ('_host_metrics', api.HostMetrics), ('_server_fps', api.ServerFPS),
                         ('_armahq_compare', api.ArmaHQCompare), ('_mod_metadata', api.ModMetadata)]:
        setattr(api, key, scoped(key, factory, getattr(api, key)))

    @api.app.before_request
    def select_instance():
        metadata_target = request.endpoint in {'server_delete', 'server_startup_save'}
        if not metadata_target and request.endpoint in getattr(api, 'PROVISIONING_ENDPOINTS', set()):
            return
        if request.endpoint in {'account_me', 'account_password', 'users_list', 'users_save',
                                'account_preferences', 'account_preferences_save',
                                'users_delete', 'admin_label_save', 'activity_list',
                                'presets_delete'}:
            return  # Panel-wide mutations retain their shared lock.
        if not request.path.startswith('/api/') or request.path == '/api/servers':
            return
        server_id = request.view_args['server_id'] if metadata_target else request.headers.get('X-Server-ID')
        if server_id is None and request.endpoint == 'files_download':
            server_id = request.args.get('_server')
        if server_id is None:
            return  # Existing single-server API remains available during integration.
        try:
            instance = registry.get(server_id)
        except KeyError:
            g.instance_selection_error = (jsonify(ok=False, error='Unknown server'), 404)
            return
        except ValueError as exc:
            g.instance_selection_error = (jsonify(ok=False, error=str(exc)), 409)
            return
        if instance.state != 'ready' and request.endpoint != 'server_delete':
            g.instance_selection_error = (jsonify(ok=False, error='Server is not provisioned', state=instance.state), 409)
            return
        g.server_instance = instance

    @api.app.get('/api/servers')
    def servers_list():
        return jsonify(servers=[dict(id=s.id, name=s.name, state=s.state,
            game_port=s.game_port, query_port=s.query_port, rcon_port=s.rcon_port, max_fps=s.max_fps)
            for s in registry.list()])
