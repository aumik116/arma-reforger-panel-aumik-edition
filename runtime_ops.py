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


class TrafficMetrics:
    """Interval rates: host interfaces and physical I/O attributed to the game process."""
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = {}
        self.cached = {}

    def sample(self, key, counters, now):
        old = self.previous.get(key)
        if old and now - old[0] < .5:
            return self.cached[key]
        result = dict(status='warming', first=None, second=None)
        if old:
            common = counters.keys() & old[1].keys()
            if common:
                totals = [0, 0]
                for identity in common:
                    values, before = counters[identity], old[1][identity]
                    if any(a < b for a, b in zip(values, before)):
                        continue
                    for index in range(2):
                        totals[index] += values[index] - before[index]
                result = dict(status='available', first=totals[0] / (now-old[0]), second=totals[1] / (now-old[0]))
        self.previous[key] = (now, counters)
        self.cached[key] = result
        return result

    def read(self, pid):
        with self.lock:
            now = time.monotonic()
            result = {}
            for key in ('network', 'disk'):
                try:
                    counters = {}
                    if key == 'network':
                        with open('/proc/net/dev') as stream:
                            for line in stream:
                                if ':' not in line:
                                    continue
                                interface, values = line.split(':', 1)
                                if interface.strip() == 'lo':
                                    continue
                                values = values.split()
                                counters[interface.strip()] = (int(values[0]), int(values[8]))
                    elif pid:
                        with open(f'/proc/{pid}/stat') as stream:
                            start = stream.read().rsplit(')', 1)[1].split()[19]
                        with open(f'/proc/{pid}/io') as stream:
                            values = dict(line.strip().split(': ', 1) for line in stream if ': ' in line)
                        counters[(pid, start)] = (int(values['read_bytes']), int(values['write_bytes']))
                    if not counters:
                        result[key] = dict(status='stopped' if key == 'disk' and not pid else 'unavailable', first=None, second=None)
                        self.previous.pop(key, None)
                    else:
                        result[key] = self.sample(key, counters, now)
                except (OSError, ValueError, IndexError, KeyError):
                    self.previous.pop(key, None)
                    result[key] = dict(status='unavailable', first=None, second=None)
            return result


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
