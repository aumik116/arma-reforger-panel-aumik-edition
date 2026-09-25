"""Short-lived Reforger BattlEye RCON queries and player-list parsing."""
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
    # Some server versions include a count or column labels after the header,
    # and RCON replies may contain NUL terminators. Neither is a player row.
    text = text.replace('\x00', '').replace('\ufeff', '')
    players = []
    for line in text.splitlines():
        line = re.sub(r'^\s*Players on server:\s*', '', line, flags=re.I)
        match = re.fullmatch(r'\s*(?:Player\s*#?\s*|#\s*)?(\d+)\s*;\s*([^;]+)\s*;\s*(.+?)\s*', line, re.I)
        if match:
            players.append({'id': match[1], 'identity': match[2].strip(), 'name': match[3].strip()})
    if not players:
        cleaned = text.strip().lower()
        empty = (re.fullmatch(r'players on server:\s*(?:0|\(0\))?\s*', cleaned)
                 or cleaned in {'no players connected', 'no players on server', '0 players'})
        if not empty:
            # An actual reply is much more useful than a generic parser error.
            # Keep it short and on one line so the dashboard remains readable.
            excerpt = re.sub(r'\s+', ' ', text).strip()[:160]
            raise ValueError(f'Unrecognized #players reply: {excerpt or "(empty response)"}')
    return players


def query_command(host, port, password, command):
    """Run one command over a short-lived BattlEye RCON connection."""
    if not isinstance(command, str) or not command or len(command) > 256 or any(ord(char) < 32 for char in command):
        raise ValueError('Invalid RCON command')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.connect((host, port))

        def receive(kind, sequence=None, players_reply=False):
            deadline = time.monotonic() + 3
            chunks, total = {}, None
            interim_response = None
            while time.monotonic() < deadline:
                sock.settimeout(max(.01, deadline - time.monotonic()))
                try:
                    payload = unpack(sock.recv(65535))
                except socket.timeout:
                    break
                if payload[0] == 2 and len(payload) >= 2:
                    sock.send(packet(payload[:2]))
                    if players_reply and b'players on server' in payload[2:].lower():
                        return payload[2:]
                    continue
                if payload[0] != kind:
                    continue
                if sequence is None:
                    return payload[1:]
                if len(payload) < 2 or payload[1] != sequence:
                    continue
                content = payload[2:]
                if content[:1] != b'\x00':
                    if players_reply and (not content or b'processing command:' in content.lower()):
                        interim_response = content
                        continue
                    return content
                if len(content) < 3 or content[1] == 0 or content[2] >= content[1]:
                    raise ValueError('Invalid multipart RCON response')
                if total is not None and total != content[1]:
                    raise ValueError('Inconsistent multipart RCON response')
                total = content[1]
                chunks[content[2]] = content[3:]
                if len(chunks) == total:
                    return b''.join(chunks[i] for i in range(total))
            if interim_response is not None:
                return interim_response
            raise TimeoutError('RCON response timed out')

        sock.send(packet(b'\x00' + password.encode('utf-8')))
        if receive(0) != b'\x01':
            raise ValueError('RCON authentication failed')
        try:
            sock.send(packet(b'\x01\x00' + command.encode('utf-8')))
            return receive(1, 0, players_reply=command.lower() == '#players').decode('utf-8', errors='replace')
        finally:
            # Reforger 1.2.1+: release the connection slot after each query.
            sock.send(packet(b'\x01\x01@logout'))


def query_players(host, port, password):
    return parse_players(query_command(host, port, password, '#players'))


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
