import concurrent.futures
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from flask import g
import test_panel


class InstanceTests(unittest.TestCase):
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login

    def instance(self, server_id):
        registry = self.module.server_registry
        server = registry.register(server_id, server_id)
        for key in ('server', 'profile', 'logs', 'workshop'):
            server.paths[key].mkdir(parents=True)
        server.paths['config'].write_text(json.dumps({'game': {
            'name': server_id, 'scenarioId': 'original', 'mods': []}}))
        # Provisioning will own this transition; no public create endpoint yet.
        with registry.connect() as conn:
            conn.execute("UPDATE server_instances SET state='ready' WHERE id=?", (server_id,))
        return registry.get(server_id)

    def test_auth_selection_and_config_write_isolation(self):
        first, second = self.instance('first'), self.instance('second')
        self.assertEqual(self.module.app.test_client().get('/api/servers').status_code, 401)
        self.assertEqual(len(self.admin.get('/api/servers').json['servers']), 2)
        self.assertEqual(self.admin.get('/api/status', headers={'X-Server-ID':'missing'}).status_code, 404)
        self.module.server_registry.register('pending', 'Pending')
        self.assertEqual(self.admin.get('/api/status', headers={'X-Server-ID':'pending'}).status_code, 409)
        csrf = self.admin.get('/api/csrf').json['csrf']
        response = self.admin.post('/api/config', json={'server_name':'Changed'},
            headers={'X-Server-ID':'first', 'X-CSRF-Token':csrf})
        self.assertTrue(response.json['ok'], response.json)
        self.assertEqual(json.loads(first.paths['config'].read_text())['game']['name'], 'Changed')
        self.assertEqual(json.loads(second.paths['config'].read_text())['game']['name'], 'second')
        self.assertEqual(json.loads(self.config.read_text())['game']['name'], 'Test')
        self.assertEqual(self.admin.post('/api/config', json={'server_name':'No CSRF'},
            headers={'X-Server-ID':'second'}).status_code, 403)

    def test_concurrent_contexts_keep_paths_and_caches_separate(self):
        servers = [self.instance('first'), self.instance('second')]
        barrier = threading.Barrier(2)
        def read(server):
            with self.module.app.test_request_context('/api/status'):
                g.server_instance = server
                self.module._LAST_SCAN_RESULT['scenarios'] = [server.id]
                barrier.wait(timeout=5)
                return (self.module.read_config()['game']['name'],
                        list(self.module._LAST_SCAN_RESULT['scenarios']),
                        str(self.module._SCAN_CACHE_FILE),
                        str(self.module.software_manager.path))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(read, servers))
        for server, result in zip(servers, results):
            self.assertEqual(result[0], server.id)
            self.assertEqual(result[1], [server.id])
            self.assertEqual(Path(result[2]).parent, server.directory)
            self.assertEqual(Path(result[3]).parent, server.directory)

    def test_service_commands_target_selected_unit(self):
        server = self.instance('first')
        with self.module.app.test_request_context('/api/start'):
            g.server_instance = server
            with patch.object(self.module.subprocess, 'run') as run:
                run.return_value.returncode = 0
                self.module.service_command('start')
                self.assertEqual(run.call_args.args[0][-2:], ['start', server.id])
            with self.assertRaises(ValueError):
                self.module.service_command('enable')

    def test_state_files_credentials_and_events_are_scoped(self):
        first, second = self.instance('first'), self.instance('second')
        for server in (first, second):
            log = server.paths['logs'] / 'logs_2026-10-17'
            log.mkdir()
            (log / 'console.log').write_text(server.id + '\n')
            self.module.audit_event('admin', 'api_start', 'success', {'server_id':server.id})
        self.module.audit_event('admin', 'api_start', 'success', {})
        with self.module.app.test_request_context('/api/logs'):
            g.server_instance = first
            self.assertEqual(Path(self.module.get_latest_log()).read_text(), 'first\n')
            self.assertEqual(len(self.module.metric_events()), 1)

            self.assertEqual(self.module._candidate_addon_roots(),
                [(str(first.paths['workshop']), False), (str(first.paths['server']), True)])
            self.assertEqual(self.module._cfg['FILE_BACKUP_DIR'], str(first.paths['backups']))
            self.assertNotIn('RCON_PASSWORD', self.module._cfg)
        with self.module.app.test_request_context('/api/logs'):
            g.server_instance = second
            self.assertEqual(Path(self.module.get_latest_log()).read_text(), 'second\n')
            self.assertEqual(len(self.module.metric_events()), 1)

    def test_direct_file_download_preserves_instance_selection(self):
        first, second = self.instance('first'), self.instance('second')
        for server in (first, second):
            (server.paths['profile'] / 'sample.txt').write_text(server.id)
        response = self.admin.get('/api/files/download?root=profile&path=sample.txt&_server=first')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, b'first')


if __name__ == '__main__':
    unittest.main()
