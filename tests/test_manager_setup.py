import shutil
from pathlib import Path
import unittest
import json
from unittest.mock import patch
import server_provisioning as provision
import test_panel
from server_provisioning import validate_public_address


class ManagerSetupTests(unittest.TestCase):
    manager_mode = True
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login
    post = test_panel.PanelTests.post

    def test_manager_paths_require_a_selected_server(self):
        for setting in ('SERVER_DIR', 'SERVER_CONFIG', 'LOG_DIR', 'PROFILE_DIR', 'WORKSHOP_DIR', '_SCAN_CACHE_FILE'):
            with self.subTest(setting=setting), self.assertRaises(self.module.ConfigReadError):
                str(getattr(self.module, setting))
        with patch('server_software.shutil.which', return_value=None), \
             patch('server_software.os.path.isfile', return_value=False):
            self.assertIsNone(self.module.software_manager.executable())

    def test_empty_manager_does_not_invent_legacy_server(self):
        self.config.unlink()
        response = self.admin.get('/')
        self.assertEqual(response.location, '/servers')
        servers = self.admin.get('/api/servers').json
        self.assertTrue(servers['manager_mode'])
        self.assertIsNone(servers['legacy_server'])
        self.assertEqual(servers['servers'], [])
        self.assertEqual(self.admin.get('/api/status').status_code, 409)
        self.assertTrue(self.admin.get('/api/status').json['setup_required'])
        shutil.copy(Path(__file__).resolve().parents[1] / 'setup.html', self.root / 'setup.html')
        self.assertEqual(self.admin.get('/setup').status_code, 200)
        self.assertIn(b'create-instance', self.admin.get('/setup').data)
        self.assertNotEqual(self.module.app.test_client().get('/setup').status_code, 200)

    def test_server_overview_is_authenticated_and_logout_needs_no_server(self):
        shutil.copy(Path(__file__).resolve().parents[1] / 'servers.html', self.root / 'servers.html')
        self.assertEqual(self.admin.get('/servers').status_code, 200)
        self.assertNotEqual(self.module.app.test_client().get('/servers').status_code, 200)
        self.assertEqual(self.post(self.admin, '/logout').status_code, 200)

    def test_address_validation(self):
        self.assertEqual(validate_public_address(' 203.0.113.4 '), '203.0.113.4')
        self.assertEqual(validate_public_address(''), '')
        for value in ('hostname', '::1', '300.1.1.1', None):
            with self.assertRaises(ValueError):
                validate_public_address(value)

    def test_first_creation_with_no_legacy_config_and_invalid_address_is_atomic(self):
        self.config.unlink()
        payload = {'server_id':'first', 'name':'First', 'public_address':'bad-address'}
        with patch.object(provision.sys, 'platform', 'linux'), \
             patch.object(provision.Path, 'is_file', return_value=True), \
             patch.object(self.module.software_manager._get_current_object(), 'executable', return_value='/steamcmd'), \
             patch.object(provision, 'available', return_value=True), patch.object(provision, 'launch') as launch:
            self.assertEqual(self.post(self.admin, '/api/servers', payload).status_code, 400)
            self.assertEqual(self.module.server_registry.list(), [])
            payload['public_address'] = '203.0.113.42'
            response = self.post(self.admin, '/api/servers', payload)
            self.assertEqual(response.status_code, 202, response.json)
        server = self.module.server_registry.get('first')
        options = json.loads((server.directory / '.provision-options.json').read_text())
        self.assertEqual(options['seed_directory'], '')
        self.assertEqual(options['seed_state_directory'], '')
        self.assertEqual(json.loads(server.paths['config'].read_text())['publicAddress'], '203.0.113.42')
        self.assertEqual(server.game_port, 2001)
        launch.assert_called_once()
        self.module.server_registry.set_state('first', 'ready')
        self.assertEqual(self.admin.get('/').location, '/servers')

    def test_panel_accounts_are_independent_of_server_config(self):
        self.config.unlink()
        with patch.object(self.module, 'read_config', side_effect=AssertionError('Panel action read game config')):
            created = self.post(self.admin, '/api/users', {'username':'Texas','password':'test-password','role':'viewer'})
            self.assertEqual(created.status_code, 200, created.json)
            user = next(row for row in self.admin.get('/api/users').json['users'] if row['username'] == 'Texas')
            viewer = self.login('Texas')
            self.assertEqual(self.post(viewer, '/api/users', {'username':'Denied','password':'test-password'}).status_code,403)
            self.assertEqual(self.admin.post('/api/users',json={'username':'NoCsrf','password':'test-password'}).status_code,403)
            changed = self.post(self.admin, '/api/users', {'id':user['id'],'username':'Texas','role':'operator'})
            self.assertEqual(changed.status_code,200,changed.json)
            self.assertEqual(self.post(self.admin, '/api/preferences', {'theme':'forest'}).status_code,200)
            password = self.post(self.admin, '/api/account/password', {'current_password':'test-password','password':'new-test-password'})
            self.assertEqual(password.status_code,200,password.json)
            deleted = self.post(self.admin, '/api/users/delete', {'id':user['id']})
            self.assertEqual(deleted.status_code,200,deleted.json)
            events = self.admin.get('/api/activity').json['events']
            for action in ('users_save','users_delete','account_password'):
                self.assertTrue(any(event['action'] == action and event['outcome'] == 'success' for event in events))
