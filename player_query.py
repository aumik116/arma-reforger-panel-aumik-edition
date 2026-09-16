"""Read-only Reforger #players query over the BattlEye RCON protocol."""
import re
import socket
import struct
import threading
import time
import zlib


def packet(payload):
    data = b'\xff' + payload
    return b'BE' + struct.pack('<I', zlib.crc32(data)) + data


def unpack(data):
    if len(data) < 8 or data[:2] != b'BE' or data[6] != 255:
        raise ValueError('Invalid RCON packet')
    if struct.unpack('<I', data[2:6])[0] != zlib.crc32(data[6:]):
        raise ValueError('Invalid RCON checksum')
    return data[7:]


def parse_players(text):
    """Native #players rows: player number ; identity ID ; player name."""
    players = []
    for line in text.splitlines():
        line = re.sub(r'^\s*Players on server:\s*', '', line, flags=re.I)
        match = re.fullmatch(r'\s*(?:Player\s*#?|#)?(\d+)\s*;\s*([^;]+)\s*;\s*(.+?)\s*', line, re.I)
        if match:
            players.append({'id': match[1], 'identity': match[2].strip(), 'name': match[3].strip()})
    if not players:
        cleaned = text.strip().lower()
        if not re.fullmatch(r'players on server:\s*(?:0|\(0\))?\s*', cleaned) and cleaned not in {'no players connected', 'no players on server', '0 players'}:
            raise ValueError('Player response was not recognized; check RCON permissions and server version')
    return players


def query_players(host, port, password):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.connect((host, port))

        def receive(kind, sequence=None):
            deadline = time.monotonic() + 3
            chunks, total = {}, None
            while time.monotonic() < deadline:
                sock.settimeout(max(.01, deadline - time.monotonic()))
                payload = unpack(sock.recv(65535))
                if payload[0] == 2 and len(payload) >= 2:
                    sock.send(packet(payload[:2]))
                    continue
                if payload[0] != kind:
                    continue
                if sequence is None:
                    return payload[1:]
                if len(payload) < 2 or payload[1] != sequence:
                    continue
                content = payload[2:]
                if content[:1] != b'\x00':
                    return content
                if len(content) < 3 or content[1] == 0 or content[2] >= content[1]:
                    raise ValueError('Invalid multipart RCON response')
                if total is not None and total != content[1]:
                    raise ValueError('Inconsistent multipart RCON response')
                total = content[1]
                chunks[content[2]] = content[3:]
                if len(chunks) == total:
                    return b''.join(chunks[i] for i in range(total))
            raise TimeoutError('RCON response timed out')

        sock.send(packet(b'\x00' + password.encode('utf-8')))
        if receive(0) != b'\x01':
            raise ValueError('RCON authentication failed')
        try:
            sock.send(packet(b'\x01\x00#players'))
            return parse_players(receive(1, 0).decode('utf-8', errors='replace'))
        finally:
            # Reforger 1.2.1+: release the connection slot after each query.
            sock.send(packet(b'\x01\x01@logout'))


class PlayerQuery:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0
        self.first_seen = {}

    def clear(self):
        with self.lock:
            self.cached = None
            self.first_seen.clear()

    def read(self, rcon, settings):
        with self.lock:
            if self.cached and time.monotonic() - self.cached_at < 10:
                return self.cached
            password = settings.get('RCON_PASSWORD') or rcon.get('password')
            host = settings.get('RCON_HOST') or rcon.get('address') or '127.0.0.1'
            if host == '0.0.0.0':
                host = '127.0.0.1'
            try:
                if not password:
                    raise ValueError('Enable RCON in server config to display connected players')
                port = int(settings.get('RCON_PORT') or rcon.get('port', 19999))
                players = query_players(host, port, password)
                now = time.time()
                self.first_seen = {p['identity']: self.first_seen.get(p['identity'], now) for p in players}
                for player in players:
                    player['first_seen'] = self.first_seen[player['identity']]
                self.cached = dict(available=True, players=players, checked_at=now, message='Live player list')
            except (OSError, ValueError) as exc:
                self.cached = dict(available=False, players=[], message=str(exc))
            self.cached_at = time.monotonic()
            return self.cached
