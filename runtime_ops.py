"""Linux process metrics and bounded, position-based console reads."""
import base64
import json
import os
import threading
import time
import sys
import hashlib


class ProcessMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = None
        self.cpu = 0.0

    def read(self, pid):
        with self.lock:
            with open(f'/proc/{pid}/stat') as stream:
                fields = stream.read().rsplit(')', 1)[1].split()
            # fields begin at stat field 3; starttime distinguishes reused PIDs.
            ticks = int(fields[11]) + int(fields[12])
            identity = (pid, fields[19])
            ram = round(int(fields[21]) * os.sysconf('SC_PAGE_SIZE') / 1048576, 1)
            now = time.monotonic()
            old = self.previous
            if old is None or old[0] != identity:
                self.cpu = 0.0
            elif now - old[1] < 0.5:
                return self.cpu, ram
            else:
                elapsed = now - old[1]
                self.cpu = round(max(0, min(100, (ticks - old[2]) /
                    os.sysconf('SC_CLK_TCK') / elapsed / (os.cpu_count() or 1) * 100)), 1)
            self.previous = (identity, now, ticks)
            return self.cpu, ram


def read_console(path, cursor=None, initial_lines=80, limit=262144):
    """Opaque cursor never supplies a path. Read at most 256 KiB per request."""
    with open(path, 'rb') as stream:
        stat = os.fstat(stream.fileno())
        identity = [os.path.abspath(path), stat.st_dev, stat.st_ino]
        offset = None
        if cursor:
            try:
                value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if value[:3] == identity and type(value[3]) is int and 0 <= value[3] <= stat.st_size:
                    stream.seek(max(0, value[3] - 64))
                    anchor = stream.read(min(64, value[3]))
                    if hashlib.sha256(anchor).hexdigest() == value[4]:
                        offset = value[3]
            except (ValueError, TypeError, IndexError, UnicodeError):
                pass
        reset = offset is None
        if reset:
            offset = max(0, stat.st_size - limit)
        stream.seek(offset)
        raw = stream.read(limit)
        # Hold incomplete lines until the next poll, except an oversized line.
        end = raw.rfind(b'\n') + 1
        if end == 0 and len(raw) == limit:
            end = len(raw)
        consumed = raw[:end]
        lines = consumed.decode('utf-8', errors='replace').splitlines()
        if reset:
            if offset and lines:
                lines = lines[1:]
            lines = lines[-initial_lines:]
        next_offset = offset + end
        stream.seek(max(0, next_offset - 64))
        anchor = hashlib.sha256(stream.read(min(64, next_offset))).hexdigest()
        token = base64.urlsafe_b64encode(json.dumps(identity + [next_offset, anchor]).encode()).decode()
        return dict(lines=lines, cursor=token, reset=reset,
                    more=next_offset < stat.st_size and end > 0, path=path)


def launch_server(config_path):
    settings = {}
    with open(config_path, encoding='utf-8') as stream:
        for line in stream:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                settings[key.strip()] = value.strip().strip('"').strip("'")
    directory = settings.get('SERVER_DIR', '/home/arma/server')
    binary = os.path.join(directory, 'ArmaReforgerServer')
    args = [binary, '-config', settings.get('SERVER_CONFIG', directory + '/config.json'), '-loadSessionSave']
    if settings.get('MAX_FPS', '').strip():
        args.append('-maxFPS=' + settings['MAX_FPS'].strip())
    os.chdir(directory)
    os.execv(binary, args)


if __name__ == '__main__':
    launch_server(sys.argv[1])
