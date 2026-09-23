import tempfile
import os
import json
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

from runtime_ops import ProcessMetrics, TrafficMetrics, HostMetrics, ServerFPS, read_game_telemetry, read_console, launch_server, read_cpu_frequency


class RuntimeTests(unittest.TestCase):
    def test_cpu_frequency_average_and_unavailable(self):
        with patch('builtins.open', mock_open(read_data='cpu MHz : 2400.0\ncpu MHz : 3600.0\ncpu MHz : 0\n')):
            self.assertEqual(read_cpu_frequency(), 3000.0)
        with patch('builtins.open', side_effect=OSError):
            self.assertIsNone(read_cpu_frequency())
        with patch('builtins.open', mock_open(read_data='model name : CPU\n')):
            self.assertIsNone(read_cpu_frequency())

    def test_traffic_interval_resets_and_unavailable(self):
        metrics = TrafficMetrics()
        self.assertEqual(metrics.sample('network', {'eth0':(100,200)}, 1)['status'], 'warming')
        self.assertEqual(metrics.sample('network', {'eth0':(300,600)}, 3), dict(status='available',first=100,second=200))
        self.assertEqual(metrics.sample('network', {'eth0':(999,999)}, 3.1)['first'], 100)
        self.assertEqual(metrics.sample('network', {'eth0':(10,10)}, 4)['first'], 0)
        self.assertEqual(metrics.sample('disk', {(5,'old'):(100,100)}, 1)['status'], 'warming')
        self.assertEqual(metrics.sample('disk', {(5,'new'):(200,200)}, 2)['status'], 'warming')
        with patch('builtins.open', side_effect=PermissionError):
            self.assertEqual(metrics.read(5)['network']['status'], 'unavailable')
            self.assertEqual(metrics.read(None)['disk']['status'], 'stopped')

    def test_traffic_reads_host_and_process_counters(self):
        from io import StringIO
        metrics = TrafficMetrics()
        fields = ['0'] * 22; fields[19] = '123'
        def opened(path):
            return StringIO({'/proc/net/dev':'lo: 999 0 0 0 0 0 0 0 999\neth0: 100 0 0 0 0 0 0 0 200\n',
                '/proc/5/stat':'5 (arma) ' + ' '.join(fields),
                '/proc/5/io':'read_bytes: 1024\nwrite_bytes: 2048\n'}[path])
        with patch('builtins.open', side_effect=opened):
            result = metrics.read(5)
        self.assertEqual(result['disk']['status'], 'warming')
        self.assertEqual(metrics.previous['network'][1], {'eth0':(100,200)})
        self.assertEqual(metrics.previous['disk'][1], {(5,'123'):(1024,2048)})

    def test_native_fps_freshness_partial_lines_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'console.log'
            path.write_bytes(b'FPS: 60.0, frame time (avg: 16.7 ms)\n')
            reader = ServerFPS()
            with patch('runtime_ops.time.monotonic', return_value=10):
                self.assertIsNone(reader.read(str(path), 12)['server_fps'])
                with path.open('ab') as stream:
                    stream.write(b'FPS: 42.5, frame time (avg: 23.5 ms)')
                self.assertIsNone(reader.read(str(path), 12)['server_fps'])
                with path.open('ab') as stream:
                    stream.write(b'\n')
                self.assertEqual(reader.read(str(path), 12)['server_fps'], 42.5)
            with patch('runtime_ops.time.monotonic', return_value=26):
                with path.open('ab') as stream:
                    stream.write(b'Unrelated fresh log message\n')
                self.assertIsNone(reader.read(str(path), 12)['server_fps'])
                with path.open('ab') as stream:
                    stream.write(b'FPS: 0.0, frame time (avg: 1000 ms)\n')
                self.assertEqual(reader.read(str(path), 12)['server_fps'], 0)
                self.assertIsNone(reader.read(str(path), 13)['server_fps'])
                self.assertIsNone(reader.read(str(path), None)['server_fps'])

    def test_host_rates_and_counter_reset(self):
        from types import SimpleNamespace
        metrics = HostMetrics()
        def sample(rx, sectors, operations, milliseconds):
            def opened(path):
                data = (f'eth0: {rx} 0 0 0 0 0 0 0 {rx} 0 0 0 0 0 0 0\n'
                        if path == '/proc/net/dev' else
                        f'8 1 sda1 {operations} 0 {sectors} {milliseconds} 0 0 0 0 0 0 0\n')
                return mock_open(read_data=data)()
            return opened
        with patch('runtime_ops.time.monotonic', side_effect=[1, 3, 5]), \
             patch('runtime_ops.shutil.disk_usage', return_value=SimpleNamespace(free=25, used=75, total=100)), \
             patch('runtime_ops.os.stat', return_value=SimpleNamespace(st_dev=1)), \
             patch('runtime_ops.os.major', create=True, return_value=8), \
             patch('runtime_ops.os.minor', create=True, return_value=1):
            with patch('builtins.open', side_effect=sample(1000, 100, 10, 20)):
                self.assertIsNone(metrics.read('/server')['network_rx'])
            with patch('builtins.open', side_effect=sample(1001000, 4196, 14, 40)):
                result = metrics.read('/server')
                self.assertEqual(result['network_rx'], 4)
                self.assertEqual(result['disk_read'], 1)
                self.assertEqual(result['disk_used_percent'], 75)
            with patch('builtins.open', side_effect=sample(0, 0, 0, 0)):
                result = metrics.read('/server')
                self.assertIsNone(result['network_rx'])
                self.assertIsNone(result['disk_read'])

    def test_game_telemetry_freshness_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'telemetry.json'
            with patch('runtime_ops.time.time', return_value=100):
                path.write_text(json.dumps(dict(timestamp=99, server_fps=58, player_pings_ms=[10, 20, 100])))
                result = read_game_telemetry(path, True)
                self.assertEqual((result['server_fps'], result['ping_median'], result['ping_p95']), (58, 20, 100))
                self.assertIsNone(read_game_telemetry(path, False)['server_fps'])
                for sample in [dict(timestamp=80, server_fps=58), dict(timestamp=99, server_fps=-1),
                               dict(timestamp=99, player_pings_ms=[float('nan')]), [], None]:
                    path.write_text(json.dumps(sample))
                    self.assertIsNone(read_game_telemetry(path, True)['server_fps'])

    def test_console_bursts_repeated_lines_and_partial_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'console.log'
            path.write_bytes(b'old\n')
            first = read_console(path)
            with path.open('ab') as stream:
                stream.write(b'repeated\n' * 300 + b'partial')
            result = read_console(path, first['cursor'])
            self.assertEqual(result['lines'], ['repeated'] * 300)
            self.assertEqual(read_console(path, result['cursor'])['lines'], [])
            with path.open('ab') as stream:
                stream.write(b' complete\n')
            self.assertEqual(read_console(path, result['cursor'])['lines'], ['partial complete'])

    def test_console_rotation_truncation_and_bounded_catchup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'console.log'
            path.write_bytes(b'old\n')
            first = read_console(path)
            path.write_bytes(b'new content longer than old\n')
            result = read_console(path, first['cursor'])
            self.assertTrue(result['reset'])
            self.assertEqual(result['lines'], ['new content longer than old'])
            path.rename(Path(directory) / 'previous.log')
            path.write_bytes(b'rotated\n')
            result = read_console(path, result['cursor'])
            self.assertTrue(result['reset'])
            with path.open('ab') as stream:
                stream.write(b'x\n' * 500)
            lines = []
            while True:
                result = read_console(path, result['cursor'], limit=64)
                lines.extend(result['lines'])
                if not result['more']:
                    break
            self.assertEqual(lines, ['x'] * 500)
            self.assertTrue(read_console(path, 'invalid')['reset'])

    def test_cpu_interval_and_reused_pid(self):
        def stat(ticks, start=1):
            fields = ['0'] * 22
            fields[11], fields[19], fields[21] = str(ticks), str(start), '256'
            return '12 (name with spaces) ' + ' '.join(fields)
        metrics = ProcessMetrics()
        with patch('runtime_ops.os.sysconf', create=True, side_effect=lambda key: 4096 if key == 'SC_PAGE_SIZE' else 100), \
             patch('runtime_ops.os.cpu_count', return_value=4), \
             patch('runtime_ops.time.monotonic', side_effect=[1, 2, 2.1, 3]):
            with patch('builtins.open', mock_open(read_data=stat(100))):
                self.assertEqual(metrics.read(12), (0, 1))
            with patch('builtins.open', mock_open(read_data=stat(200))):
                self.assertEqual(metrics.read(12), (25, 1))
                self.assertEqual(metrics.read(12), (25, 1))
            with patch('builtins.open', mock_open(read_data=stat(2, start=2))):
                self.assertEqual(metrics.read(12), (0, 1))

    def test_service_launcher_uses_saved_configuration(self):
        with patch('builtins.open', mock_open(read_data='SERVER_DIR=/test/server\nSERVER_CONFIG=/test/custom.json\nMAX_FPS=45\n')), \
             patch('runtime_ops.os.chdir') as chdir, patch('runtime_ops.os.execv') as execute:
            launch_server('/test/config.env')
            chdir.assert_called_once_with('/test/server')
            binary = os.path.join('/test/server', 'ArmaReforgerServer')
            execute.assert_called_once_with(binary,
                [binary, '-config', '/test/custom.json', '-logStats', '1000', '-maxFPS=45'])

    def test_service_launcher_adds_native_persistence_flags_from_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / 'config.env'
            config = root / 'server.json'
            env.write_text(f'SERVER_DIR={directory}\nSERVER_CONFIG={config}\nMAX_FPS=60\n')
            config.write_text(json.dumps({'game': {'gameProperties': {'persistence': {
                'loadSessionSave': True, 'keepSessionSave': True}}}}))
            with patch('runtime_ops.os.chdir') as chdir, patch('runtime_ops.os.execv') as execute:
                launch_server(str(env))
            binary = os.path.join(directory, 'ArmaReforgerServer')
            chdir.assert_called_once_with(directory)
            execute.assert_called_once_with(binary,
                [binary, '-config', str(config), '-logStats', '1000',
                 '-loadSessionSave', '-keepSessionSave', '-maxFPS=60'])
