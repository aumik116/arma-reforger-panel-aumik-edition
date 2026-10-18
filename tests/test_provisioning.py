import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

import test_panel
import test_instances
import server_provisioning as provision
from instance_control import service_args
from server_registry import ServerRegistry
from runtime_ops import launch_server


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.registry = ServerRegistry(self.base / 'panel.sqlite3', self.base / 'instances')
        self.server = self.registry.register('training', 'Training')
        self.server.directory.mkdir(parents=True)
        self.server.paths['server'].mkdir()

    def test_clone_resets_network_credentials_and_persistence_identity(self):
        source = {'game': {'name':'Original', 'mods':[{'modId':'ABCD'}], 'password':'secret',
            'passwordAdmin':'secret', 'gameProperties':{'persistence':{'hiveId':99}}},
            'rcon':{'password':'secret'}, 'publicAddress':'203.0.113.2'}
        config = provision.instance_config(self.server, source, 32)
        self.assertEqual(config['game']['mods'], source['game']['mods'])
        self.assertEqual(config['game']['password'], '')
        self.assertEqual(config['game']['gameProperties']['persistence']['hiveId'], 0)
        self.assertEqual(source['game']['gameProperties']['persistence']['hiveId'], 99)
        self.assertNotEqual(config['rcon']['password'], 'secret')
        self.assertEqual(config['bindPort'], self.server.game_port)
        self.assertEqual(config['rcon']['address'], '127.0.0.1')
        self.assertEqual(config['game']['maxPlayers'], 32)

    def test_helper_rejects_arbitrary_units_actions_and_arguments(self):
        self.assertEqual(service_args('start', 'training')[-1], 'arma-server@training.service')
        for action, server_id in [('restart','training'), ('start','x.service other.service'),
                                  ('stop','../escape'), ('enable','--now'), ('start','')]:
            with self.assertRaises(ValueError):
                service_args(action, server_id)

    def test_occupied_ports_are_skipped_or_rejected(self):
        other = self.registry.register('other', 'Other', port_available=lambda port: port not in (2002, 2003))
        self.assertEqual(other.game_port, 2004)
        with self.assertRaises(ValueError):
            self.registry.register('busy', 'Busy', game_port=2400, port_available=lambda port: False)

    def test_failed_download_does_not_start_service(self):
        with patch.object(provision.subprocess, 'run', return_value=Mock(returncode=1)), \
             patch.object(provision, 'service_command') as control, patch.object(provision.os, 'close'):
            provision.worker(str(self.registry.database), str(self.registry.root), 'training', '/steamcmd', '10')
        self.assertEqual(self.registry.get('training').state, 'failed')
        control.assert_not_called()

    def test_verified_download_autostarts_and_marks_ready(self):
        binary = self.server.paths['server'] / 'ArmaReforgerServer'
        binary.write_text('binary')
        manifest = self.server.paths['server'] / 'steamapps' / 'appmanifest_1874900.acf'
        manifest.parent.mkdir()
        manifest.write_text('"AppState" { "appid" "1874900" "buildid" "123" }')
        def run(args, **kwargs):
            if 'stdout' in kwargs:
                kwargs['stdout'].write("Success! App '1874900' fully installed.")
            return Mock(returncode=0)
        with patch.object(provision.subprocess, 'run', side_effect=run), \
             patch.object(provision.os, 'access', return_value=True), \
             patch.object(provision, 'available', return_value=True), \
             patch.object(provision, 'service_command') as control, \
             patch.object(provision.time, 'sleep'), patch.object(provision.os, 'close'):
            provision.worker(str(self.registry.database), str(self.registry.root), 'training', '/steamcmd', '10')
        self.assertEqual(self.registry.get('training').state, 'ready')
        self.assertEqual([call.args for call in control.call_args_list], [('enable','training'), ('start','training')])

    def test_reprovisioning_ready_server_does_not_change_state(self):
        self.registry.set_state('training', 'ready')
        with self.assertRaises(ValueError):
            provision.launch(self.registry, 'training', '/steamcmd')
        self.assertEqual(self.registry.get('training').state, 'ready')

    def test_instance_launcher_uses_isolated_profile_logs_and_addons(self):
        self.registry.set_state('training', 'ready')
        self.server.paths['config'].write_text(json.dumps({'game':{'gameProperties':{
            'missionHeader':{'m_eSaveTypes':0}}}}))
        env = self.base / 'config.env'
        env.write_text(f'PANEL_DATA_FILE={self.registry.database}\nINSTANCE_ROOT={self.registry.root}\n')
        with patch('runtime_ops.os.chdir'), patch('runtime_ops.os.execv') as execute:
            launch_server(str(env), 'training')
        args = execute.call_args.args[1]
        self.assertEqual(args[args.index('-profile')+1], str(self.server.directory))
        self.assertEqual(args[args.index('-logsDir')+1], str(self.server.paths['logs']))
        self.assertEqual(args[args.index('-addonDownloadDir')+1], str(self.server.paths['workshop']))

    def test_startup_failure_stops_service_and_allows_retry(self):
        binary = self.server.paths['server'] / 'ArmaReforgerServer'
        binary.write_text('binary')
        def run(args, **kwargs):
            if 'stdout' in kwargs:
                kwargs['stdout'].write("Success! App '1874900' fully installed.")
                return Mock(returncode=0)
            return Mock(returncode=3)
        with patch.object(provision.subprocess, 'run', side_effect=run), \
             patch.object(provision, 'installed_build', return_value='123'), \
             patch.object(provision.os, 'access', return_value=True), \
             patch.object(provision, 'available', return_value=True), \
             patch.object(provision, 'service_command') as control, \
             patch.object(provision.time, 'sleep'), patch.object(provision.os, 'close'):
            provision.worker(str(self.registry.database), str(self.registry.root), 'training', '/steamcmd', '10')
        self.assertEqual(self.registry.get('training').state, 'failed')
        self.assertEqual(control.call_args.args, ('stop','training'))

    def test_status_detects_interrupted_worker(self):
        self.registry.set_state('training', 'provisioning')
        with patch.object(provision, 'lock_job', return_value=Mock()):
            state = provision.status(self.registry, 'training')
        self.assertEqual(state['state'], 'interrupted')


class ProvisionApiTests(unittest.TestCase):
    setUp = test_panel.PanelTests.setUp
    login = test_panel.PanelTests.login
    post = test_panel.PanelTests.post
    create = test_panel.PanelTests.create
    instance = test_instances.InstanceTests.instance

    def test_creation_requires_admin_and_csrf_and_initializes_files(self):
        self.create('operator', 'operator')
        operator = self.login('operator')
        payload = {'server_id':'training', 'name':'Training', 'copy_from':'__existing__'}
        self.assertEqual(self.post(operator, '/api/servers', payload).status_code, 403)
        self.assertEqual(self.admin.post('/api/servers', json=payload).status_code, 403)
        with patch.object(provision.sys, 'platform', 'linux'), \
             patch.object(provision.Path, 'is_file', return_value=True), \
             patch.object(self.module.software_manager._get_current_object(), 'executable', return_value='/steamcmd'), \
             patch.object(provision, 'available', return_value=True), patch.object(provision, 'launch') as launch:
            result = self.post(self.admin, '/api/servers', payload)
        self.assertEqual(result.status_code, 202, result.json)
        instance = self.module.server_registry.get('training')
        config = json.loads(instance.paths['config'].read_text())
        self.assertEqual(config['game']['name'], 'Training')
        self.assertEqual(config['game']['scenarioId'], 'original')
        launch.assert_called_once()
        self.assertEqual(self.post(operator, '/api/servers/training/provision/retry').status_code, 403)
        self.assertEqual(operator.get('/api/servers/training/provision').status_code, 403)

    def test_startup_settings_only_change_target_instance(self):
        self.instance('first')
        self.instance('second')
        result = self.post(self.admin, '/api/servers/first/startup', {'max_fps':45})
        self.assertTrue(result.json['ok'], result.json)
        self.assertEqual(self.module.server_registry.get('first').max_fps, 45)
        self.assertEqual(self.module.server_registry.get('second').max_fps, 60)
        self.assertEqual(self.post(self.admin, '/api/servers/first/startup', {'max_fps':True}).status_code, 400)

    def test_removal_archives_files_and_releases_registry_ports(self):
        server = self.instance('training')
        with patch.object(provision.sys, 'platform', 'linux'), \
             patch.object(provision.Path, 'is_file', return_value=True), \
             patch.object(provision, 'service_command') as control, \
             patch.object(provision, 'lock_job', side_effect=lambda directory, filename='.provision.lock': nullcontext()):
            invalid = self.post(self.admin, '/api/servers/training/delete', {'confirm_id':'wrong'})
            self.assertEqual(invalid.status_code, 409)
            control.assert_not_called()
            response = self.post(self.admin, '/api/servers/training/delete', {'confirm_id':'training'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(server.directory.exists())
        self.assertTrue((Path(response.json['archived']) / 'config.json').is_file())
        with self.assertRaises(KeyError):
            self.module.server_registry.get('training')
        replacement = self.module.server_registry.register('replacement', 'Replacement')
        self.assertEqual(replacement.game_port, server.game_port)
        self.assertEqual([call.args for call in control.call_args_list], [('stop','training'), ('disable','training')])

    def test_busy_job_prevents_removal(self):
        self.instance('training')
        with patch.object(provision.sys, 'platform', 'linux'), \
             patch.object(provision.Path, 'is_file', return_value=True), \
             patch.object(provision, 'service_command') as control, \
             patch.object(provision, 'lock_job', side_effect=ValueError('Job is running')):
            result = self.post(self.admin, '/api/servers/training/delete', {'confirm_id':'training'})
        self.assertEqual(result.status_code, 409)
        control.assert_not_called()
        self.assertEqual(self.module.server_registry.get('training').state, 'ready')


if __name__ == '__main__':
    unittest.main()
