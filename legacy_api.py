"""Compatibility endpoints for older panel clients; use the current field schema."""
from flask import g, jsonify, request
from config_editor import FIELDS, MANAGER_FIELDS, apply_changes


def install(api):
    def save_changes(config, changes, **extra):
        if 'admin_config' not in g.permissions and set(changes) - MANAGER_FIELDS:
            return jsonify(ok=False, error='Admin only: protected configuration fields'), 403
        try:
            api.write_config(apply_changes(config, changes))
            return jsonify(ok=True, restart_required=api.get_server_pid() is not None, **extra)
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400
        except OSError:
            return jsonify(ok=False, error='Unable to save configuration'), 503

    @api.app.post('/api/config')
    def api_config():
        data = request.get_json(silent=True) or {}
        aliases = {'server_name':'game.name', 'scenario_id':'game.scenarioId',
                   'password':'game.password', 'password_admin':'game.passwordAdmin'}
        changes = {path:data[key] for key,path in aliases.items() if key in data}
        if not changes:
            return jsonify(ok=False, error='No changes'), 400
        if 'scenario_id' in data and (not isinstance(data['scenario_id'], str) or data['scenario_id'] not in {m['id'] for m in api.all_scenarios_cached()}):
            return jsonify(ok=False, error='Unknown scenario'), 400
        return save_changes(api.read_config(), changes)

    @api.app.post('/api/persistence')
    def api_persistence_set():
        data = request.get_json(silent=True) or {}
        if type(data.get('enabled')) is not bool:
            return jsonify(ok=False, error='enabled must be a boolean'), 400
        config = api.read_config()
        header = config.setdefault('game', {}).setdefault('gameProperties', {}).setdefault('missionHeader', {})
        changes = {}
        if data['enabled']:
            if header.get('m_eSaveTypes') == 0:
                header.pop('m_eSaveTypes')
            block = api._get_persistence_block(config) or {}
            for key in ('autoSaveInterval', 'saveRetention', 'hiveId', 'loadSessionSave', 'keepSessionSave'):
                path = 'game.gameProperties.persistence.' + key
                if key in data:
                    changes[path] = data[key]
                elif key not in block:
                    # Defaults do not grant a manager permission to choose a hive.
                    if key != 'hiveId' or 'admin_config' in g.permissions:
                        changes[path] = FIELDS[path]['default']
        else:
            header['m_eSaveTypes'] = 0
        return save_changes(config, changes, enabled=data['enabled'])
