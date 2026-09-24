"""Best-effort inspection of UDP sockets owned by the game process."""
import os
import re


def udp_listener_status(pid, port, proc_root='/proc'):
    """Return bound, not bound, offline, or unknown without guessing from config."""
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return 'not configured'
    if not pid:
        return 'offline'
    try:
        descriptors = os.listdir(os.path.join(proc_root, str(pid), 'fd'))
        owned = set()
        for descriptor in descriptors:
            try:
                target = os.readlink(os.path.join(proc_root, str(pid), 'fd', descriptor))
            except OSError:
                continue  # A descriptor may close during the scan.
            match = re.fullmatch(r'socket:\[(\d+)\]', target)
            if match:
                owned.add(match[1])
        read_tables = 0
        for family in ('udp', 'udp6'):
            try:
                with open(os.path.join(proc_root, 'net', family), encoding='ascii') as stream:
                    read_tables += 1
                    next(stream, None)
                    for line in stream:
                        fields = line.split()
                        if len(fields) > 9 and fields[9] in owned:
                            local_port = int(fields[1].rsplit(':', 1)[1], 16)
                            if local_port == port:
                                return 'bound'
            except FileNotFoundError:
                continue  # IPv6 may be disabled.
        if not read_tables:
            return 'unknown'
    except (OSError, ValueError, IndexError):
        return 'unknown'
    return 'not bound'
