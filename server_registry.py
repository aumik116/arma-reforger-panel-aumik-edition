"""Persistent local-instance identities and port reservations.

Registration reserves an instance; it does not download software or start services.
Paths and service names are derived from validated IDs, never supplied by clients.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import json


@dataclass(frozen=True)
class ServerInstance:
    id: str
    name: str
    game_port: int
    query_port: int
    rcon_port: int
    state: str
    directory: Path
    max_fps: int = 60

    @property
    def service_name(self):
        return f'arma-server@{self.id}.service'

    @property
    def paths(self):
        return {key: self.directory / relative for key, relative in {
            'server': 'server', 'config': 'config.json', 'profile': 'profile',
            'logs': 'logs', 'workshop': 'workshop', 'backups': 'backups',
        }.items()}


class ServerRegistry:
    def __init__(self, database, instance_root, legacy_config=None):
        self.database = str(database)
        self.root = Path(instance_root).resolve()
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS server_instances (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'registered'
                        CHECK(state IN ('registered','provisioning','ready','failed')));
                CREATE TABLE IF NOT EXISTS server_ports (
                    server_id TEXT NOT NULL REFERENCES server_instances(id),
                    kind TEXT NOT NULL CHECK(kind IN ('game','query','rcon')),
                    port INTEGER NOT NULL UNIQUE CHECK(port BETWEEN 1024 AND 65535),
                    PRIMARY KEY(server_id, kind));
                CREATE TABLE IF NOT EXISTS server_registry_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS server_startup (
                    server_id TEXT PRIMARY KEY REFERENCES server_instances(id),
                    max_fps INTEGER NOT NULL CHECK(max_fps BETWEEN 0 AND 1000));
            ''')
            conn.execute('INSERT OR IGNORE INTO server_registry_settings VALUES (?,?)',
                         ('instance_root', str(self.root)))
            stored = conn.execute('SELECT value FROM server_registry_settings WHERE key=?',
                                  ('instance_root',)).fetchone()[0]
            if stored != str(self.root):
                raise ValueError('Instance root differs from the registered root')
            if legacy_config is not None:
                conn.execute('INSERT INTO server_registry_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                             ('legacy_config', str(Path(legacy_config).resolve())))

    @staticmethod
    def config_ports(config, defaults=None):
        if not isinstance(config, dict) or any(not isinstance(config.get(key, {}), dict) for key in ('a2s', 'rcon')):
            raise ValueError('Invalid server endpoint configuration')
        defaults = defaults or {'game': 2001}
        ports = {'game': config.get('bindPort', defaults.get('game')),
                 'query': config.get('a2s', {}).get('port', defaults.get('query')),
                 'rcon': config.get('rcon', {}).get('port', defaults.get('rcon'))}
        for port in ports.values():
            if port is not None and (type(port) is not int or not 1 <= port <= 65535):
                raise ValueError('Invalid configured UDP port')
        return {kind: port for kind, port in ports.items() if port is not None}

    def occupied_config_ports(self, conn, exclude=None):
        """Reserve stopped servers too, including configs edited outside the panel."""
        used = {row[0] for row in conn.execute(
            'SELECT port FROM server_ports WHERE server_id != ?', (exclude or '',))}
        paths = [(row[0], self.root / row[0] / 'config.json') for row in
                 conn.execute('SELECT id FROM server_instances') if row[0] != exclude]
        legacy = conn.execute("SELECT value FROM server_registry_settings WHERE key='legacy_config'").fetchone()
        if legacy and exclude != '__existing__':
            paths.append(('__existing__', Path(legacy[0])))
        for server_id, path in paths:
            if not path.exists():
                continue  # A registered instance may not have its config yet.
            try:
                config = json.loads(path.read_text(encoding='utf-8-sig'))
                defaults = None if server_id == '__existing__' else dict(conn.execute(
                    'SELECT kind,port FROM server_ports WHERE server_id=?', (server_id,)))
                used.update(self.config_ports(config, defaults).values())
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f'Cannot reserve ports: repair configuration for {server_id}') from exc
        return used

    @contextmanager
    def config_write(self, server_id, config, previous, port_available):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            defaults = dict(conn.execute('SELECT kind,port FROM server_ports WHERE server_id=?', (server_id,))) or None
            ports = self.config_ports(config, defaults)
            old = self.config_ports(previous, defaults)
            if ports != old or (defaults and ports != defaults):
                if len(set(ports.values())) != len(ports):
                    raise ValueError('Each endpoint requires a distinct port')
                if set(ports.values()) & self.occupied_config_ports(conn, exclude=server_id):
                    raise ValueError('Port is reserved by another server, including stopped servers')
                if any(not port_available(p) for p in set(ports.values()) - set(old.values())):
                    raise ValueError('Port is occupied by another process')
            if defaults:
                if set(ports) != {'game', 'query', 'rcon'} or any(p < 1024 for p in ports.values()):
                    raise ValueError('Managed server ports must be between 1024 and 65535')
                conn.execute('DELETE FROM server_ports WHERE server_id=?', (server_id,))
                conn.executemany('INSERT INTO server_ports VALUES (?,?,?)',
                                 [(server_id, kind, port) for kind, port in ports.items()])
            yield

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _instance(self, conn, server_id):
        row = conn.execute('SELECT * FROM server_instances WHERE id=?', (server_id,)).fetchone()
        if row is None:
            raise KeyError(server_id)
        ports = dict(conn.execute('SELECT kind,port FROM server_ports WHERE server_id=?', (server_id,)))
        startup = conn.execute('SELECT max_fps FROM server_startup WHERE server_id=?', (server_id,)).fetchone()
        directory = self.root / row['id']
        if directory.resolve() != directory:
            raise ValueError('Instance directory must not redirect through a symlink')
        return ServerInstance(row['id'], row['name'], ports['game'], ports['query'],
                              ports['rcon'], row['state'], directory, startup[0] if startup else 60)

    def resources(self, server_id):
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS server_resources (server_id TEXT PRIMARY KEY,cpus TEXT NOT NULL,memory_high_mb INTEGER NOT NULL,memory_max_mb INTEGER NOT NULL)')
            row=conn.execute('SELECT cpus,memory_high_mb,memory_max_mb FROM server_resources WHERE server_id=?',(server_id,)).fetchone()
        return dict(row) if row else dict(cpus='',memory_high_mb=0,memory_max_mb=0)

    def set_resources(self, server_id, data):
        from instance_control import normalize_limits
        value=normalize_limits(data.get('cpus',''),data.get('memory_high_mb',0),data.get('memory_max_mb',0))
        self.resources(server_id)
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO server_resources VALUES(?,?,?,?)',(server_id,value['cpus'],value['memory_high_mb'],value['memory_max_mb']))

    def get(self, server_id):
        with self.connect() as conn:
            return self._instance(conn, server_id)

    def list(self):
        with self.connect() as conn:
            ids = [row[0] for row in conn.execute('SELECT id FROM server_instances ORDER BY id')]
            return [self._instance(conn, server_id) for server_id in ids]

    def register(self, server_id, name, *, game_port=None, query_port=None, rcon_port=None, port_available=None, max_fps=60):
        self.validate_max_fps(max_fps)
        if not isinstance(server_id, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', server_id):
            raise ValueError('ID must be 1–32 lowercase letters, digits or hyphens, starting with a letter')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Name must contain 1–80 printable characters')
        requested = {'game': game_port, 'query': query_port, 'rcon': rcon_port}
        for port in requested.values():
            if port is not None and (type(port) is not int or not 1024 <= port <= 65535):
                raise ValueError('Ports must be integers between 1024 and 65535')
        explicit = [port for port in requested.values() if port is not None]
        if len(explicit) != len(set(explicit)):
            raise ValueError('Each endpoint requires a distinct port')
        directory = self.root / server_id
        if directory.exists() or directory.is_symlink():
            raise ValueError('Instance directory already exists; importing is a separate operation')
        with self.connect() as conn:
            # Serialize allocation across threads and panel processes.
            conn.execute('BEGIN IMMEDIATE')
            used = self.occupied_config_ports(conn)
            if used.intersection(explicit):
                raise ValueError('Port is already reserved by another server')
            if port_available and any(not port_available(port) for port in explicit):
                raise ValueError('Port is occupied by another process')
            used.update(explicit)
            for kind, start in [('game', 2001), ('query', 17777), ('rcon', 19999)]:
                if requested[kind] is None:
                    port = next((p for p in range(start, 65536) if p not in used
                                 and (port_available is None or port_available(p))), None)
                    if port is None:
                        raise ValueError('No available ports in the allocation range')
                    requested[kind] = port
                    used.add(port)
            try:
                conn.execute('INSERT INTO server_instances(id,name) VALUES (?,?)', (server_id, name.strip()))
                conn.executemany('INSERT INTO server_ports VALUES (?,?,?)',
                                 [(server_id, kind, port) for kind, port in requested.items()])
                conn.execute('INSERT INTO server_startup VALUES (?,?)', (server_id, max_fps))
            except sqlite3.IntegrityError as exc:
                raise ValueError('Server ID or port is already registered') from exc
            return self._instance(conn, server_id)

    def set_state(self, server_id, state):
        if state not in ('registered', 'provisioning', 'ready', 'failed'):
            raise ValueError('Invalid provisioning state')
        with self.connect() as conn:
            if conn.execute('UPDATE server_instances SET state=? WHERE id=?', (state, server_id)).rowcount != 1:
                raise KeyError(server_id)

    @staticmethod
    def validate_max_fps(value):
        if type(value) is not int or not 0 <= value <= 1000:
            raise ValueError('FPS cap must be an integer between 0 and 1000 (0 disables the cap)')

    def set_max_fps(self, server_id, value):
        self.validate_max_fps(value)
        with self.connect() as conn:
            self._instance(conn, server_id)
            conn.execute('INSERT INTO server_startup VALUES (?,?) ON CONFLICT(server_id) DO UPDATE SET max_fps=excluded.max_fps',
                         (server_id, value))

    def existing_max_fps(self, default=''):
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM server_registry_settings WHERE key='existing_max_fps'").fetchone()
        value = int(row[0]) if row else int(default or 0)
        self.validate_max_fps(value)
        return value

    def set_existing_max_fps(self, value):
        self.validate_max_fps(value)
        with self.connect() as conn:
            conn.execute("INSERT INTO server_registry_settings VALUES('existing_max_fps',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(value),))

    def remove(self, server_id):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._instance(conn, server_id)
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedules'").fetchone():
                conn.execute('UPDATE schedules SET enabled=0,deleted=1 WHERE server_id=?',(server_id,))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='server_resources'").fetchone():
                conn.execute('DELETE FROM server_resources WHERE server_id=?',(server_id,))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='server_launch_options'").fetchone():
                conn.execute('DELETE FROM server_launch_options WHERE server_id=?',(server_id,))
            conn.execute('DELETE FROM server_startup WHERE server_id=?', (server_id,))
            conn.execute('DELETE FROM server_ports WHERE server_id=?', (server_id,))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mod_download_index'").fetchone():
                conn.execute('DELETE FROM mod_download_index WHERE server_id=?',(server_id,))
            conn.execute('DELETE FROM server_instances WHERE id=?', (server_id,))
