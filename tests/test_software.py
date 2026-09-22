import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from server_software import APP_ID, SoftwareManager, installed_build, parse_vdf, steam_command

class SoftwareTests(unittest.TestCase):
    def test_build_and_public_branch_parsing(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / 'steamapps' / f'appmanifest_{APP_ID}.acf'
            manifest.parent.mkdir()
            self.assertIsNone(installed_build(root))
            manifest.write_text('"AppState" { "appid" "1874900" "buildid" "12345" }')
            self.assertEqual(installed_build(root), '12345')
            manifest.write_text('"AppState" { "appid" "wrong" "buildid" "12345" }')
            self.assertIsNone(installed_build(root))
        data = parse_vdf('Steam console\n"1874900" { "depots" { "branches" { "public" { "buildid" "456" } "experimental" { "buildid" "999" } } } }')
        self.assertEqual(data[APP_ID]['depots']['branches']['public']['buildid'], '456')
        with self.assertRaises(ValueError):
            parse_vdf('"AppState" {')

    def test_fixed_commands_do_not_validate_or_accept_shell_input(self):
        args = steam_command('/steam/steamcmd.sh', '/srv/game dir', 'update')
        self.assertLess(args.index('+force_install_dir'), args.index('+login'))
        self.assertIn('/srv/game dir', args)
        self.assertEqual(args[-3:], ['+app_update', APP_ID, '+quit'])
        self.assertNotIn('validate', args)
        with self.assertRaises(ValueError):
            steam_command('/steam/steamcmd.sh', '/srv/game', 'delete')

    def test_running_and_overlapping_jobs_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            api = SimpleNamespace(_BASE_DIR=root, SERVER_DIR=root, _cfg={}, get_server_pid=Mock(return_value=42), service_command=Mock())
            manager = SoftwareManager(api)
            lock = Mock()
            with patch('server_software.sys.platform', 'linux'), patch.object(manager, 'executable', return_value='/steamcmd.sh'), patch.object(manager, 'acquire', return_value=lock), patch('server_software.subprocess.Popen') as popen:
                with self.assertRaisesRegex(ValueError, 'Stop the game'):
                    manager.launch('update', 'admin')
                popen.assert_not_called()
                api.service_command.assert_not_called()
                lock.close.assert_called_once()
            with patch('server_software.sys.platform', 'linux'), patch.object(manager, 'executable', return_value='/steamcmd.sh'), patch.object(manager, 'acquire', return_value=None):
                with self.assertRaisesRegex(ValueError, 'already running'):
                    manager.launch('check', 'admin')
