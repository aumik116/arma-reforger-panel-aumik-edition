import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

from runtime_ops import ProcessMetrics, TrafficMetrics, read_console, launch_server


class RuntimeTests(unittest.TestCase):
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
                [binary, '-config', '/test/custom.json', '-loadSessionSave', '-maxFPS=45'])
