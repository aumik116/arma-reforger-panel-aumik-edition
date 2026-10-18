import json
import unittest
from unittest.mock import patch

import test_instances
import test_panel
from config_editor import revision


class PortUpdateTests(unittest.TestCase):
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login
    instance = test_instances.InstanceTests.instance

    def edit(self, server, changes):
        config = json.loads(server.paths['config'].read_text())
        csrf = self.admin.get('/api/csrf').json['csrf']
        return self.admin.post('/api/config/editor',
            json={'revision': revision(config), 'changes': changes},
            headers={'X-Server-ID': server.id, 'X-CSRF-Token': csrf})

    def test_stopped_existing_ports_are_reserved(self):
        config = json.loads(self.config.read_text())
        config.update(bindPort=2001, a2s={'port':17777}, rcon={'port':19999})
        self.config.write_text(json.dumps(config))
        registry = self.module.server_registry
        server = registry.register('new', 'New', port_available=lambda p: True)
        self.assertEqual((server.game_port, server.query_port, server.rcon_port), (2002,17778,20000))
        with self.assertRaises(ValueError):
            registry.register('bad', 'Bad', game_port=2001)

    def test_edit_synchronizes_registry_and_rejects_collisions(self):
        first, second = self.instance('first'), self.instance('second')
        with patch('server_provisioning.available', return_value=True):
            self.assertEqual(self.edit(first, {'bindPort':2400, 'publicPort':2400}).status_code, 200)
            self.assertEqual(self.module.server_registry.get(first.id).game_port, 2400)
            before = second.paths['config'].read_bytes()
            self.assertEqual(self.edit(second, {'bindPort':2400}).status_code, 400)
            self.assertEqual(second.paths['config'].read_bytes(), before)
            self.assertEqual(self.edit(first, {'bindPort':2001}).status_code, 400)

    def test_failed_config_write_rolls_back_reservation(self):
        first = self.instance('first')
        before = first.paths['config'].read_bytes()
        with patch('server_provisioning.available', return_value=True), patch('config_backups.backup_current', side_effect=OSError('disk full')):
            self.assertEqual(self.edit(first, {'bindPort':2400}).status_code, 500)
        self.assertEqual(self.module.server_registry.get(first.id).game_port, first.game_port)
        self.assertEqual(first.paths['config'].read_bytes(), before)

    def test_external_edits_and_busy_ports_are_not_reallocated(self):
        first = self.instance('first')
        config = json.loads(first.paths['config'].read_text())
        config['bindPort'] = 2400
        first.paths['config'].write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            self.module.server_registry.register('other', 'Other', game_port=2400)
        with patch('server_provisioning.available', return_value=False):
            self.assertEqual(self.edit(first, {'bindPort':2500}).status_code, 400)

    def test_existing_server_cannot_take_managed_port(self):
        first = self.instance('first')
        with self.assertRaises(ValueError):
            config = self.module.read_config()
            config['bindPort'] = first.game_port
            self.module.write_config(config)

