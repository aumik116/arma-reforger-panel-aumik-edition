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
            self.assertEqual(status['password_admin'], 'admin-secret' if role == 'manager' else '')
        self.assertEqual(self.module.app.test_client().get('/api/status').status_code, 401)

    def test_csrf_and_old_shared_sessions_rejected(self):
        self.assertEqual(self.admin.post('/api/start', json={}).status_code, 403)
        client = self.module.app.test_client()
        with client.session_transaction() as session:
            session['logged_in'] = True
        self.assertEqual(client.get('/api/status').status_code, 401)

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
