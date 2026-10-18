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

    def test_empty_manager_does_not_invent_legacy_server(self):
        self.config.unlink()
        response = self.admin.get('/')
        self.assertEqual(response.location, '/setup')
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
        self.assertEqual(json.loads(server.paths['config'].read_text())['publicAddress'], '203.0.113.42')
        self.assertEqual(server.game_port, 2001)
        launch.assert_called_once()
        self.module.server_registry.set_state('first', 'ready')
        self.assertEqual(self.admin.get('/').location, '/?server=first')
