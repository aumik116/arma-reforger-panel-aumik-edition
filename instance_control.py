#!/usr/bin/python3
"""Root-owned service helper. Installed by install.sh; never imports panel code."""
import re
import subprocess
import sys


def service_args(action, server_id):
    if action not in ('start', 'stop', 'enable', 'disable', 'diagnostics') or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', server_id):
        raise ValueError('Invalid instance service command')
    if action == 'diagnostics':
        return ['/usr/bin/journalctl', '--unit', f'arma-server@{server_id}.service',
                '--lines', '80', '--no-pager', '--output', 'short-iso']
    return ['/usr/bin/systemctl', action, f'arma-server@{server_id}.service']


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Expected action and instance ID')
    try:
        sys.exit(subprocess.run(service_args(*sys.argv[1:]), timeout=150).returncode)
    except (ValueError, subprocess.TimeoutExpired) as exc:
        sys.exit(str(exc))
