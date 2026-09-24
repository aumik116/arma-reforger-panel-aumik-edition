import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from network_status import udp_listener_status


class NetworkStatusTests(unittest.TestCase):
    def test_udp_port_must_belong_to_game_process(self):
        with tempfile.TemporaryDirectory() as root:
            net = Path(root, 'net')
            fd = Path(root, '123', 'fd')
            net.mkdir()
            fd.mkdir(parents=True)
            header = 'sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n'
            rows = '0: 00000000:07D1 00000000:0000 07 0 0 0 0 0 4321\n'
            (net / 'udp').write_text(header + rows)
            (net / 'udp6').write_text(header)
            (fd / '5').touch()
            with patch('network_status.os.readlink', return_value='socket:[4321]'):
                self.assertEqual(udp_listener_status(123, 2001, root), 'bound')
                self.assertEqual(udp_listener_status(123, 19999, root), 'not bound')
            self.assertEqual(udp_listener_status(None, 2001, root), 'offline')
            self.assertEqual(udp_listener_status(123, None, root), 'not configured')
            (net / 'udp').unlink()
            self.assertEqual(udp_listener_status(123, 2001, root), 'not bound')
            (net / 'udp6').unlink()
            self.assertEqual(udp_listener_status(123, 2001, root), 'unknown')
