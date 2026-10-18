import concurrent.futures
from pathlib import Path
import tempfile
import unittest

from server_registry import ServerRegistry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.database = self.base / 'panel.sqlite3'
        self.root = self.base / 'instances'
        self.registry = ServerRegistry(self.database, self.root)

    def test_persistence_and_isolated_layout(self):
        first = self.registry.register('main', 'Main')
        second = self.registry.register('training', 'Training')
        self.assertEqual(first.service_name, 'arma-server@main.service')
        self.assertEqual(first.paths['profile'], self.root / 'main' / 'profile')
        self.assertNotEqual(first.paths['config'], second.paths['config'])
        self.assertFalse(first.directory.exists())  # Registration is not provisioning.
        self.assertEqual(ServerRegistry(self.database, self.root).get('main'), first)
        self.assertEqual(len(self.registry.list()), 2)

    def test_validation_and_atomic_conflict(self):
        self.registry.register('main', 'Main', game_port=2300)
        for kwargs in [dict(game_port=2300), dict(query_port=2300),
                       dict(game_port=True), dict(rcon_port=65536),
                       dict(game_port=2400, rcon_port=2400)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.registry.register('other', 'Other', **kwargs)
        for server_id in ['../escape', 'UPPER', 'bad/name', '-bad', 'a' * 33]:
            with self.assertRaises(ValueError):
                self.registry.register(server_id, 'Bad')
        with self.assertRaises(ValueError):
            self.registry.register('main', 'Duplicate')
        self.assertEqual(len(self.registry.list()), 1)
        self.registry.register('other', 'Other', game_port=2400)

    def test_existing_directories_and_root_changes_rejected(self):
        (self.root / 'occupied').mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.registry.register('occupied', 'Occupied')
        with self.assertRaises(ValueError):
            ServerRegistry(self.database, self.base / 'different')

    def test_parallel_allocation_reserves_unique_ports(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.registry.register(f'server-{i}', f'Server {i}'), range(8)))
        ports = [port for server in results for port in (server.game_port, server.query_port, server.rcon_port)]
        self.assertEqual(len(ports), len(set(ports)))


if __name__ == '__main__':
    unittest.main()
