"""Linux process metrics and bounded, position-based console reads."""
import base64
import json
import os
import threading
import time
import sys
import hashlib
import shutil
import math
import statistics
import re


def read_cpu_frequency():
    """Mean OS-reported logical CPU frequency in MHz; absent on some VMs."""
    try:
        with open('/proc/cpuinfo') as stream:
            values = [float(line.split(':', 1)[1]) for line in stream
                      if line.split(':', 1)[0].strip() == 'cpu MHz']
        values = [value for value in values if math.isfinite(value) and value > 0]
        return round(statistics.mean(values), 1) if values else None
    except (OSError, ValueError):
        return None


class ServerFPS:
    """Read newly appended native logStats records, never revive old log samples."""
    empty_sample = dict(server_fps=None, player_count=None, ai_count=None, vehicle_count=None,
                        frame_time_avg=None, frame_time_max=None)

    def __init__(self):
        self.lock = threading.Lock()
        self.identity = None
        self.cursor = None
        self.value = None
        self.seen_at = 0
        self.last_poll = None

    def read(self, path, pid):
        with self.lock:
            now = time.monotonic()
            identity = (path, pid)
            if identity != self.identity or not pid or (self.last_poll is not None and now - self.last_poll > 15):
                self.identity, self.cursor, self.value = identity, None, None
            self.last_poll = now
            message = 'Waiting for fresh FPS statistics; restart the game after updating to enable them'
            if not pid:
                return dict(self.empty_sample, fps_message='Server is offline')
            try:
                if path:
                    result = read_console(path, self.cursor, initial_lines=1)
                    self.cursor = result['cursor']
                    if result['reset']:
                        self.value = None
                    else:
                        for line in result['lines']:
                            match = re.search(r'\bFPS:\s*([0-9]+(?:\.[0-9]+)?),\s*frame time\s*\(', line)
                            if match:
                                value = float(match[1])
                                if math.isfinite(value):
                                    sample = dict(self.empty_sample, server_fps=value)
                                    patterns = {
                                        'player_count': r'\bPlayer:\s*(\d+)\s*(?:,|$)',
                                        'ai_count': r'\bAI:\s*(\d+)\s*(?:,|$)',
                                        'vehicle_count': r'\bVeh:\s*\d+\s*\((\d+)\)',
                                        'frame_time_avg': r'\bframe time\s*\(avg:\s*([0-9]+(?:\.[0-9]+)?)\s*ms',
                                        'frame_time_max': r'\bframe time\s*\([^)]*\bmax:\s*([0-9]+(?:\.[0-9]+)?)\s*ms',
                                    }
                                    for key, pattern in patterns.items():
                                        field = re.search(pattern, line)
                                        if field:
                                            number = int(field[1]) if key.endswith('_count') else float(field[1])
                                            if math.isfinite(number):
                                                sample[key] = number
                                    self.value, self.seen_at = sample, now
                    # A backlog may contain historical samples, not current measurements.
                    if result['more']:
                        self.value = None
            except (OSError, ValueError):
                self.cursor, self.value = None, None
            if self.value is not None and now - self.seen_at <= 15:
                return dict(self.value, fps_message='Live statistics from native server performance log')
            return dict(self.empty_sample, fps_message=message)


class HostMetrics:
    """Shared interval samples; disk counters belong to the server filesystem device."""
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = {}
        self.cached = {}
        self.sampled_at = None

    def read(self, directory):
        with self.lock:
            now = time.monotonic()
            if self.sampled_at is not None and now - self.sampled_at < 1:
                return dict(self.cached)
            result = dict(network_rx=None, network_tx=None, disk_read=None,
                          disk_write=None, disk_free=None,
                          disk_total=None, disk_used_percent=None)
            def rate(key, counters):
                old = self.previous.get(key)
                self.previous[key] = (now, counters)
                if old is None or now <= old[0] or any(a < b for a, b in zip(counters, old[1])):
                    return None
                return [(a - b) / (now - old[0]) for a, b in zip(counters, old[1])]
            try:
                interfaces = {}
                with open('/proc/net/dev') as stream:
                    for line in stream:
                        if ':' not in line:
                            continue
                        name, values = line.split(':', 1)
                        if name.strip() == 'lo':
                            continue
                        fields = values.split()
                        interfaces[name.strip()] = (int(fields[0]), int(fields[8]))
                identity = tuple(sorted(interfaces))
                speeds = rate(('network', identity), tuple(sum(v[i] for v in interfaces.values()) for i in (0, 1)))
                if speeds:
                    result.update(network_rx=speeds[0] * 8 / 1e6, network_tx=speeds[1] * 8 / 1e6)
            except (OSError, ValueError, IndexError):
                self.previous = {k: v for k, v in self.previous.items() if k[0] != 'network'}
            try:
                usage = shutil.disk_usage(directory)
                result.update(disk_free=usage.free, disk_total=usage.total,
                              disk_used_percent=100 * usage.used / usage.total)
                device = os.stat(directory).st_dev
                major, minor = os.major(device), os.minor(device)
                with open('/proc/diskstats') as stream:
                    for line in stream:
                        f = line.split()
                        if (int(f[0]), int(f[1])) != (major, minor):
                            continue
                        # Linux diskstats sectors are always 512 bytes.
                        speeds = rate(('disk', device), (int(f[5]), int(f[9])))
                        if speeds:
                            result.update(disk_read=speeds[0] * 512 / 1048576,
                                          disk_write=speeds[1] * 512 / 1048576)
                        break
            except (OSError, ValueError, IndexError, AttributeError):
                self.previous = {k: v for k, v in self.previous.items() if k[0] != 'disk'}
            self.sampled_at, self.cached = now, result
            return dict(result)


def read_game_telemetry(path, running):
    """Optional game-side exporter: reject stale, oversized or invalid samples."""
    result = dict(server_fps=None, ping_median=None, ping_p95=None,
                  telemetry_message='Game telemetry exporter not configured')
    if not running:
        return dict(result, telemetry_message='Server is offline')
    if not path:
        return result
    try:
        with open(path, encoding='utf-8') as stream:
            sample = json.loads(stream.read(65537))
        timestamp = sample['timestamp']
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not -5 <= time.time() - timestamp <= 15:
            raise ValueError('Stale sample')
        def valid(value):
            return type(value) in (int, float) and math.isfinite(value) and value >= 0
        fps = sample.get('server_fps')
        pings = sample.get('player_pings_ms', [])
        if fps is not None and not valid(fps):
            raise ValueError('Invalid FPS')
        if not isinstance(pings, list) or not all(valid(p) for p in pings):
            raise ValueError('Invalid pings')
        result.update(server_fps=fps, telemetry_message='Live game telemetry')
        if pings:
            result.update(ping_median=statistics.median(pings),
                          ping_p95=sorted(pings)[math.ceil(len(pings) * .95) - 1])
    except (OSError, ValueError, KeyError, TypeError):
        result['telemetry_message'] = 'Game telemetry unavailable or older than 15 seconds'
    return result


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
    server_config = settings.get('SERVER_CONFIG', directory + '/config.json')
    args = [binary, '-config', server_config, '-logStats', '1000']
    try:
        with open(server_config, encoding='utf-8-sig') as stream:
            config = json.load(stream)
        properties = (config.get('game') or {}).get('gameProperties') or {}
        if (properties.get('missionHeader') or {}).get('m_eSaveTypes') != 0:
            persistence = properties.get('persistence') or {}
            if persistence.get('loadSessionSave', True):
                args.append('-loadSessionSave')
            if persistence.get('keepSessionSave', False):
                args.append('-keepSessionSave')
    except (OSError, ValueError, TypeError):
        pass
    if settings.get('MAX_FPS', '').strip():
        args.append('-maxFPS=' + settings['MAX_FPS'].strip())
    os.chdir(directory)
    os.execv(binary, args)


if __name__ == '__main__':
    launch_server(sys.argv[1])
