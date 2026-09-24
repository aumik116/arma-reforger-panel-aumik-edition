import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from player_query import packet, unpack, parse_players, query_players, PlayerQuery


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(Path(__file__).resolve().parents[1] / 'app.py', self.root / 'app.py')
        self.config = self.root / 'server.json'
        self.config.write_text(json.dumps({'game': {'name': 'Test', 'password': 'game-secret',
            'passwordAdmin': 'admin-secret', 'mods': [], 'scenarioId': 'original'}}))
        (self.root / 'config.env').write_text(f'PANEL_PASSWORD=test-password\nSERVER_CONFIG={self.config}\n')
        spec = importlib.util.spec_from_file_location('test_app', self.root / 'app.py')
        self.module = importlib.util.module_from_spec(spec)
        sys.modules['test_app'] = self.module
        spec.loader.exec_module(self.module)
        self.module.app.testing = True
        self.module.get_server_pid = lambda: None
        self.module.all_scenarios_cached = lambda: []
        self.admin = self.login('admin')

    def login(self, username, password='test-password'):
        client = self.module.app.test_client()
        response = client.post('/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200, response.json)
        return client

    def post(self, client, path, data=None):
        csrf = client.get('/api/csrf').json['csrf']
        return client.post(path, json=data or {}, headers={'X-CSRF-Token': csrf})

    def create(self, name, role):
        result = self.post(self.admin, '/api/users', {'username': name, 'password':'test-password', 'role': role})
        self.assertTrue(result.json['ok'], result.json)
        return next(u for u in self.admin.get('/api/users').json['users'] if u['username'] == name)

    def test_roles_are_enforced_and_secrets_are_redacted(self):
        from panel_features import MUTATIONS, ROLES
        routes = {rule.endpoint: rule.rule for rule in self.module.app.url_map.iter_rules()}
        for role in ['viewer', 'operator', 'manager']:
            self.create(role, role)
            client = self.login(role)
            for endpoint, permission in MUTATIONS.items():
                if permission not in ROLES[role]:
                    result = self.post(client, routes[endpoint])
                    self.assertEqual(result.status_code, 403, (role, endpoint, result.json))
            status = client.get('/api/status').json
            self.assertEqual(status['password_admin'], '')
        self.assertEqual(self.module.app.test_client().get('/api/status').status_code, 401)

    def test_config_writer_keeps_mods_at_bottom_without_changing_values(self):
        config = {'game': {'mods': [{'modId': 'B'}, {'modId': 'A'}],
                           'gameProperties': {'persistence': {'hiveId': 200}}, 'name': 'Test'},
                  'operating': {'custom': True}, 'customRoot': {'keep': 42}}
        original = json.dumps(config)
        self.module.write_config(config)
        saved = json.loads(self.config.read_text())
        self.assertEqual(saved, config)
        self.assertEqual(list(saved)[-1], 'game')
        self.assertEqual(list(saved['game'])[-1], 'mods')
        self.assertEqual(json.dumps(config), original)

    def test_software_routes_and_start_interlock(self):
        manager = self.module.software_manager
        self.create('software-manager', 'manager')
        client = self.login('software-manager')
        self.assertEqual(client.get('/api/software').status_code, 403)
        with patch.object(manager, 'launch') as launch:
            result = self.post(self.admin, '/api/software/check')
            self.assertEqual(result.status_code, 202)
            launch.assert_called_once_with('check', 'admin')
        with patch.object(manager, 'launch', side_effect=ValueError('Stop server')):
            self.assertEqual(self.post(self.admin, '/api/software/update').status_code, 409)
        with patch.object(manager, 'busy', return_value=True), patch.object(self.module, 'start_server') as start, patch.object(self.module, 'stop_server') as stop:
            for route in ['/api/start', '/api/restart']:
                self.assertEqual(self.post(self.admin, route).status_code, 409)
            start.assert_not_called()
            stop.assert_not_called()

    def test_csrf_and_old_shared_sessions_rejected(self):
        self.assertEqual(self.admin.post('/api/start', json={}).status_code, 403)
        self.assertEqual(self.admin.post('/api/software/update', json={}).status_code, 403)
        client = self.module.app.test_client()
        with client.session_transaction() as session:
            session['logged_in'] = True
        self.assertEqual(client.get('/api/status').status_code, 401)

    def test_manager_field_permissions_and_secret_redaction(self):
        from config_editor import FIELDS, MANAGER_FIELDS
        self.create('manager', 'manager')
        manager = self.login('manager')
        cfg = json.loads(self.config.read_text())
        cfg['rcon'] = {'address': '127.0.0.1', 'password': 'rcon-secret', 'port': 19999}
        cfg['game']['gameProperties'] = {'persistence': {'hiveId': 12, 'autoSaveInterval': 10}}
        self.config.write_text(json.dumps(cfg))
        loaded = manager.get('/api/config/editor').json
        self.assertNotIn('passwordAdmin', loaded['config']['game'])
        self.assertNotIn('password', loaded['config']['rcon'])
        self.assertEqual(loaded['config']['game']['password'], 'game-secret')
        specs = {f['path']: f for group in loaded['groups'] for f in group['fields']}
        for path in FIELDS.keys() - MANAGER_FIELDS:
            self.assertTrue(specs[path]['read_only'], path)
            for route in ('/api/config/editor', '/api/config/validate'):
                response = self.post(manager, route, {'revision': loaded['revision'], 'changes': {path: None, 'game.name': 'Must not save'}})
                self.assertEqual(response.status_code, 403, (path, route))
        self.assertEqual(json.loads(self.config.read_text()), cfg)
        for route in ('/api/config/validate', '/api/config/editor'):
            response = self.post(manager, route, {'revision': loaded['revision'], 'changes': {
                'game.name': 'Managed server', 'game.gameProperties.persistence.autoSaveInterval': 15}})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertNotIn('admin-secret', response.get_data(as_text=True))
            self.assertNotIn('rcon-secret', response.get_data(as_text=True))
        saved = json.loads(self.config.read_text())
        self.assertEqual(saved['game']['passwordAdmin'], 'admin-secret')
        self.assertEqual(saved['rcon']['password'], 'rcon-secret')
        self.assertEqual(saved['game']['gameProperties']['persistence']['hiveId'], 12)
        self.assertEqual(saved['game']['gameProperties']['persistence']['autoSaveInterval'], 15)
        self.assertEqual(self.post(manager, '/api/config', {'password_admin': 'blocked', 'server_name': 'Must not save'}).status_code, 403)
        self.assertEqual(self.post(manager, '/api/persistence', {'enabled': False}).status_code, 403)
        with patch.object(self.module, '_flush_saves') as flush:
            self.assertEqual(self.post(manager, '/api/persistence/flush').status_code, 403)
            flush.assert_not_called()
        self.assertEqual(json.loads(self.config.read_text()), saved)
        admin_loaded = self.admin.get('/api/config/editor').json
        self.assertEqual(admin_loaded['config']['rcon']['password'], 'rcon-secret')
        self.assertEqual(self.post(self.admin, '/api/config/editor', {'revision': admin_loaded['revision'], 'changes': {'bindPort': 2400}}).status_code, 200)

    def test_console_rcon_command_is_admin_only_and_uses_configured_listener(self):
        self.create('operator', 'operator')
        operator = self.login('operator')
        self.assertEqual(self.post(operator, '/api/rcon/command', {'command': '#players'}).status_code, 403)
        self.assertEqual(self.post(self.admin, '/api/rcon/command', {'command': '#players'}).status_code, 409)
        cfg = json.loads(self.config.read_text())
        cfg['rcon'] = {'address':'0.0.0.0', 'port':19999, 'password':'rcon-secret', 'permission':'admin'}
        self.config.write_text(json.dumps(cfg))
        self.module.get_server_pid = lambda: 12
        with patch('player_query.query_command', return_value='Players on server:') as send:
            response = self.post(self.admin, '/api/rcon/command', {'command': '#players'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['output'], 'Players on server:')
        send.assert_called_once_with('127.0.0.1', 19999, 'rcon-secret', '#players')
        self.assertEqual(self.post(self.admin, '/api/rcon/command', {'command': '#login secret'}).status_code, 400)

    def test_owner_is_protected_from_added_admins_and_survives_rename(self):
        owner = self.admin.get('/api/me').json
        self.assertTrue(owner['is_owner'])
        self.create('secondadmin', 'admin')
        added = self.login('secondadmin')
        self.assertFalse(added.get('/api/me').json['is_owner'])
        for overrides in ({'username': 'taken'}, {'password': 'changed-password'}, {'role': 'viewer'}, {'enabled': False}, {}):
            response = self.post(added, '/api/users', dict(id=owner['id'], username='admin', role='admin', enabled=True) | overrides)
            self.assertEqual(response.status_code, 403, response.json)
        self.assertEqual(self.post(added, '/api/users/delete', {'id': owner['id']}).status_code, 403)
        for overrides in ({'role': 'manager'}, {'enabled': False}):
            self.assertEqual(self.post(self.admin, '/api/users', dict(id=owner['id'], username='admin', role='admin', enabled=True) | overrides).status_code, 400)
        self.assertEqual(self.post(self.admin, '/api/users/delete', {'id': owner['id']}).status_code, 400)
        renamed = self.post(self.admin, '/api/users', {'id': owner['id'], 'username': 'founder', 'role': 'admin', 'enabled': True, 'password': 'owner-new-password'})
        self.assertTrue(renamed.json['ok'], renamed.json)
        self.assertTrue(self.login('founder', 'owner-new-password').get('/api/me').json['is_owner'])
        spoof = self.post(added, '/api/users', {'username': 'admin', 'role': 'admin', 'password': 'test-password', 'is_owner': True})
        self.assertTrue(spoof.json['ok'])
        self.assertFalse(self.login('admin').get('/api/me').json['is_owner'])
        # Simulate upgrading/restarting an existing database: immutable ID, not name.
        spec = importlib.util.spec_from_file_location('reloaded_owner_app', self.root / 'app.py')
        restarted = importlib.util.module_from_spec(spec)
        sys.modules['reloaded_owner_app'] = restarted
        spec.loader.exec_module(restarted)
        client = restarted.app.test_client()
        self.assertEqual(client.post('/login', json={'username': 'founder', 'password': 'owner-new-password'}).status_code, 200)
        self.assertTrue(client.get('/api/me').json['is_owner'])
        self.assertEqual(client.get('/api/me').json['id'], owner['id'])

    def test_mod_edit_reorder_preserve_fields_and_reject_stale_list(self):
        mods = [{'modId': 'ABC', 'name': 'First', 'version': '1', 'required': False}, {'modId': 'DEF', 'name': 'Second'}]
        cfg = json.loads(self.config.read_text())
        cfg['game']['mods'] = mods
        self.config.write_text(json.dumps(cfg))
        changed = self.post(self.admin, '/api/mods/edit', {'modId': 'ABC', 'expected': mods, 'name': 'Updated', 'version': ''})
        self.assertEqual(changed.status_code, 200)
        result = json.loads(self.config.read_text())
        self.assertEqual(result['game']['mods'][0], {'modId': 'ABC', 'name': 'Updated', 'required': False})
        self.assertEqual(result['game']['scenarioId'], 'original')
        stale = self.post(self.admin, '/api/mods/edit', {'modId': 'ABC', 'expected': mods, 'direction': 1})
        self.assertEqual(stale.status_code, 409)
        moved = self.post(self.admin, '/api/mods/edit', {'modId': 'ABC', 'expected': result['game']['mods'], 'direction': 1})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(json.loads(self.config.read_text())['game']['mods'][1]['modId'], 'ABC')

    def test_metadata_only_reads_configured_mods(self):
        with patch.object(self.module._mod_metadata, 'get') as fetch:
            self.assertEqual(self.admin.get('/api/mods/metadata?modId=ABC').status_code, 404)
            fetch.assert_not_called()
            cfg = json.loads(self.config.read_text())
            cfg['game']['mods'] = [{'modId': 'ABC'}]
            self.config.write_text(json.dumps(cfg))
            fetch.return_value = {'status': 'available', 'sizes': {'1.0': 1024}}
            self.assertEqual(self.admin.get('/api/mods/metadata?modId=abc').json['sizes']['1.0'], 1024)
            fetch.assert_called_once_with('ABC')

    def test_config_editor_preserves_unknown_fields_and_rejects_stale_drafts(self):
        cfg = json.loads(self.config.read_text())
        cfg['customExtension'] = {'keep': [1, 2]}
        cfg['game']['mods'] = [{'modId': 'ABC123', 'required': False}]
        self.config.write_text(json.dumps(cfg))
        loaded = self.admin.get('/api/config/editor').json
        payload = {'revision': loaded['revision'], 'changes': {
            'game.maxPlayers': 96, 'game.gameProperties.disableThirdPerson': True,
            'game.gameProperties.persistence.saveRetention': 12, 'publicPort': 2002}}
        validated = self.post(self.admin, '/api/config/validate', payload)
        self.assertTrue(validated.json['ok'], validated.json)
        self.assertEqual(json.loads(self.config.read_text()), cfg)
        saved = self.post(self.admin, '/api/config/editor', payload)
        self.assertTrue(saved.json['ok'], saved.json)
        result = json.loads(self.config.read_text())
        self.assertEqual(result['customExtension'], cfg['customExtension'])
        self.assertEqual(result['game']['mods'], cfg['game']['mods'])
        self.assertEqual(result['game']['maxPlayers'], 96)
        self.assertEqual(result['publicPort'], 2002)
        self.assertEqual(self.post(self.admin, '/api/config/editor', payload).status_code, 409)

    def test_config_editor_validation_and_secret_access(self):
        loaded = self.admin.get('/api/config/editor').json
        initial = self.config.read_text()
        for changes in [
            {'game.maxPlayers': True}, {'game.maxPlayers': 129},
            {'game.gameProperties.networkViewDistance': 200},
            {'game.gameProperties.serverMinGrassDistance': 20},
            {'game.admins': ['bad-id']}, {'game.visible': 'true'},
            {'rcon.password': 'has spaces'}, {'rcon.maxClients': 5},
            {'game.mods': []}, {'publicPort': 0}, {'publicAddress': 'not-an-address'},
            {'game.scenarioId': 'not-a-resource'}, {'game.name': None},
        ]:
            response = self.post(self.admin, '/api/config/editor', {'revision':loaded['revision'], 'changes':changes})
            self.assertEqual(response.status_code, 400, (changes, response.json))
            self.assertEqual(self.config.read_text(), initial)
        self.create('configviewer', 'viewer')
        viewer = self.login('configviewer')
        self.assertEqual(viewer.get('/api/config/editor').status_code, 403)
        self.assertEqual(self.module.app.test_client().get('/api/config/editor').status_code, 401)
        self.assertEqual(self.admin.post('/api/config/editor', json={'revision':loaded['revision'], 'changes':{}}).status_code, 403)

    def test_config_editor_custom_scenario_rcon_and_defaults(self):
        loaded = self.admin.get('/api/config/editor').json
        payload = {'revision':loaded['revision'], 'changes': {
            'game.scenarioId':'{1234567890ABCDEF}Missions/Custom.conf',
            'rcon.address':'127.0.0.1', 'rcon.password':'unique-test-secret',
            'rcon.permission':'monitor', 'rcon.port':19999,
            'game.maxPlayers':64}}
        saved = self.post(self.admin, '/api/config/editor', payload)
        self.assertTrue(saved.json['ok'], saved.json)
        self.assertNotIn('unique-test-secret', json.dumps(self.admin.get('/api/activity').json))
        reset = self.post(self.admin, '/api/config/editor', {'revision':saved.json['revision'], 'changes':{'game.maxPlayers':None}})
        self.assertTrue(reset.json['ok'])
        self.assertNotIn('maxPlayers', reset.json['config']['game'])
        self.assertEqual(reset.json['config']['rcon']['password'], 'unique-test-secret')

    def test_config_editor_refuses_corrupt_existing_file(self):
        self.config.write_text('{broken')
        self.assertEqual(self.admin.get('/api/config/editor').status_code, 400)
        result = self.post(self.admin, '/api/config/editor', {'changes':{'game.maxPlayers':32}})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.config.read_text(), '{broken')

    def test_admin_name_labels_persist_without_changing_access(self):
        original = self.config.read_text()
        identity = '12345678-abcd-abcd-abcd-123456789012'
        result = self.post(self.admin, '/api/admin-labels', {'identity':identity, 'name':'Ranger One'})
        self.assertTrue(result.json['ok'])
        self.assertEqual(self.admin.get('/api/config/editor').json['admin_labels'][identity], 'Ranger One')
        self.assertEqual(self.config.read_text(), original)
        self.assertEqual(self.post(self.admin, '/api/admin-labels', {'identity':'bad', 'name':'Name'}).status_code, 400)
        self.assertEqual(self.post(self.admin, '/api/admin-labels', {'identity':identity, 'name':['bad']}).status_code, 400)

    def test_forwarded_headers_cannot_bypass_login_limit(self):
        self.module._LOGIN_BUCKETS.clear()
        client = self.module.app.test_client()
        for i in range(6):
            response = client.post('/login', json={'username': 'admin', 'password': 'wrong'},
                                   headers={'X-Forwarded-For': f'198.51.100.{i}'})
            self.assertEqual(response.status_code, 401 if i < 5 else 429)

    def test_unreadable_config_is_not_overwritten(self):
        token = self.admin.get('/api/csrf').json['csrf']
        for contents in ['{broken', '[]', '{"game": null}']:
            self.config.write_text(contents)
            response = self.admin.post('/api/config', json={'password': 'new'}, headers={'X-CSRF-Token': token})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(self.config.read_text(), contents)

    def test_dashboard_metrics_and_safe_event_labels(self):
        self.module.audit_event('admin', 'api_restart', 'success', {'private': 'hidden'})
        self.module.audit_event('admin', 'api_mods_add', 'failed')
        self.create('observer', 'viewer')
        viewer = self.login('observer')
        with patch.object(self.module._host_metrics, 'read', return_value={'network_rx': 2.5, 'disk_free': 1024}):
            response = viewer.get('/api/metrics')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['network_rx'], 2.5)
        self.assertIsNone(response.json['server_fps'])
        self.assertEqual(len(response.json['events']), 1)
        self.assertEqual(set(response.json['events'][0]), {'id', 'ts', 'action'})
        self.assertEqual(self.module.app.test_client().get('/api/metrics').status_code, 401)

    def test_disable_revoke_and_self_protection(self):
        user = self.create('helper', 'operator')
        client = self.login('helper')
        result = self.post(self.admin, '/api/users', dict(user, enabled=False))
        self.assertTrue(result.json['ok'])
        self.assertEqual(client.get('/api/status').status_code, 401)
        admin = next(u for u in self.admin.get('/api/users').json['users'] if u['username'] == 'admin')
        self.assertEqual(self.post(self.admin, '/api/users', dict(admin, enabled=True, role='viewer')).status_code, 400)
        self.assertEqual(self.post(self.admin, '/api/users/delete', {'id':admin['id']}).status_code, 400)

    def test_password_change_and_old_session_revocation(self):
        other = self.login('admin')
        result = self.post(self.admin, '/api/account/password', {'current_password':'test-password','password':'updated-password'})
        self.assertTrue(result.json['ok'])
        self.assertEqual(other.get('/api/status').status_code, 401)
        self.assertEqual(self.admin.get('/api/status').status_code, 200)
        self.login('admin', 'updated-password')

    def test_deleted_account_session_cannot_access_replacement_account(self):
        user = self.create('temporary', 'viewer')
        client = self.login('temporary')
        self.post(self.admin, '/api/users/delete', {'id':user['id']})
        replacement = self.create('replacement', 'admin')
        self.assertNotEqual(user['id'], replacement['id'])
        self.assertEqual(client.get('/api/status').status_code, 401)

    def test_bad_input_is_rejected(self):
        self.assertEqual(self.post(self.admin, '/api/users', {'username':'valid','role':[]}).status_code, 400)
        self.assertEqual(self.post(self.admin, '/api/users/delete', {'id':[]}).status_code, 400)
        self.assertEqual(self.admin.post('/login', json=['bad']).status_code, 400)

    def test_preset_roundtrip_and_activity_survive_reinitialization(self):
        self.assertTrue(self.post(self.admin, '/api/mods/add', {'modId':'ABC123','name':'Test mod','version':'1.0'}).json['ok'])
        self.assertTrue(self.post(self.admin, '/api/presets', {'name':'Weekend'}).json['ok'])
        preset = self.admin.get('/api/presets').json['presets'][0]
        self.post(self.admin, '/api/mods/remove', {'modId':'ABC123'})
        self.module.get_server_pid = lambda: 123
        result = self.post(self.admin, '/api/presets/apply', {'id':preset['id']})
        self.assertTrue(result.json['restart_required'])
        cfg = json.loads(self.config.read_text())
        self.assertEqual(cfg['game']['mods'][0]['version'], '1.0')
        self.assertEqual(cfg['game']['scenarioId'], 'original')
        self.assertTrue(self.admin.get('/api/presets').json['presets'][0]['active'])
        self.post(self.admin, '/api/config', {'password':'new-secret'})
        events = self.admin.get('/api/activity').json['events']
        self.assertNotIn('new-secret', json.dumps(events))
        self.assertTrue(any(e['details'].get('added_mods') for e in events))
        self.assertTrue(all(e['actor'] == 'admin' for e in events))
        import sqlite3
        with sqlite3.connect(self.root / '.panel-data.sqlite3') as db:
            self.assertGreater(db.execute('SELECT count(*) FROM activity').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT name FROM presets').fetchone()[0], 'Weekend')
        db.close()

    def test_preset_validation_and_failed_actions(self):
        self.assertEqual(self.post(self.admin, '/api/presets', {'name':''}).status_code, 400)
        self.assertEqual(self.post(self.admin, '/api/presets/apply', {'id':999}).status_code, 404)
        self.post(self.admin, '/api/presets', {'name':'empty'})
        self.assertEqual(self.post(self.admin, '/api/presets', {'name':'EMPTY'}).status_code, 400)
        event = self.admin.get('/api/activity').json['events'][0]
        self.assertEqual(event['outcome'], 'failed')

    def test_server_actions_audited_and_no_real_processes_started(self):
        with patch.object(self.module, 'start_server'), patch.object(self.module, 'stop_server'):
            self.assertTrue(self.post(self.admin, '/api/start').json['ok'])
            self.module.get_server_pid = lambda: 42
            self.assertTrue(self.post(self.admin, '/api/stop').json['ok'])
            self.assertTrue(self.post(self.admin, '/api/restart').json['ok'])
        actions = {e['action'] for e in self.admin.get('/api/activity').json['events']}
        self.assertTrue({'api_start','api_stop','api_restart'} <= actions)

    def test_start_checks_survival_and_service_errors(self):
        from types import SimpleNamespace
        with patch.object(self.module.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='permission denied')):
            with self.assertRaisesRegex(RuntimeError, 'permission denied'):
                self.module.service_command('start')
        with patch.object(self.module, 'service_command') as command, patch.object(self.module.time, 'sleep'):
            with patch.object(self.module, 'get_server_pid', side_effect=[42] * 9):
                self.module.start_server()
                command.assert_called_with('start')
            with patch.object(self.module, 'get_server_pid', side_effect=[42, None]):
                with self.assertRaisesRegex(RuntimeError, 'exited during startup'):
                    self.module.start_server()
            with patch.object(self.module, 'get_server_pid', return_value=None), \
                 patch.object(self.module.time, 'monotonic', side_effect=[0, 11]):
                with self.assertRaisesRegex(RuntimeError, 'did not start'):
                    self.module.start_server()

    def test_stop_waits_and_restart_does_not_start_after_timeout(self):
        with patch.object(self.module, 'service_command') as command, \
             patch.object(self.module.os, 'kill') as kill, patch.object(self.module.time, 'sleep'), \
             patch.object(self.module, 'get_server_pid', side_effect=[42, 42, None]):
            self.module.stop_server()
            command.assert_called_once_with('stop')
            kill.assert_called_once_with(42, 15)
        with patch.object(self.module, 'service_command'), patch.object(self.module.os, 'kill'), \
             patch.object(self.module, 'get_server_pid', return_value=42), \
             patch.object(self.module.time, 'monotonic', side_effect=[0, 61]), \
             patch.object(self.module, 'start_server') as start:
            result = self.post(self.admin, '/api/restart')
            self.assertFalse(result.json['ok'])
            self.assertIn('still stopping', result.json['error'])
            start.assert_not_called()


class RconTests(unittest.TestCase):
    def test_parse_names_and_unavailable_responses(self):
        rows = parse_players('Players on server:\n1 ; identity-1 ; Aumik\n2 ; identity-2 ; Name with spaces')
        self.assertEqual([p['name'] for p in rows], ['Aumik', 'Name with spaces'])
        self.assertEqual(parse_players('Players on server:'), [])
        with self.assertRaises(ValueError):
            parse_players('Insufficient permissions')
        with self.assertRaises(ValueError):
            unpack(packet(b'hello')[:-1] + b'x')

    def test_protocol_multipart_and_server_message_ack(self):
        from unittest.mock import MagicMock
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.side_effect = [packet(b'\x00\x01'), packet(b'\x02\x09notice'),
            packet(b'\x01\x00\x00\x02\x01Aumik'), packet(b'\x01\x00\x00\x02\x00Players on server:\n1 ; guid ; ')]
        with patch('player_query.socket.socket', return_value=sock):
            result = query_players('127.0.0.1',19999,'secret')
        self.assertEqual(result[0]['name'], 'Aumik')
        sent = [unpack(call.args[0]) for call in sock.send.call_args_list]
        self.assertIn(b'\x02\x09', sent)
        self.assertIn(b'\x01\x01@logout', sent)

    def test_missing_configuration_is_not_zero_players(self):
        result = PlayerQuery().read({}, {})
        self.assertFalse(result['available'])


if __name__ == '__main__':
    unittest.main()
