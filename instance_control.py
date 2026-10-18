#!/usr/bin/python3
"""Root-owned service helper. Installed by install.sh; never imports panel code."""
import re
import os
from itertools import groupby
import subprocess
import sys


def service_args(action, server_id):
    if action not in ('start', 'stop', 'enable', 'disable', 'diagnostics') or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', server_id):
        raise ValueError('Invalid instance service command')
    if action == 'diagnostics':
        return ['/usr/bin/journalctl', '--unit', f'arma-server@{server_id}.service',
                '--lines', '80', '--no-pager', '--output', 'short-iso']
    return ['/usr/bin/systemctl', action, f'arma-server@{server_id}.service']


def normalize_limits(cpu, high, maximum):
    if not isinstance(cpu,str) or len(cpu)>256 or type(high) is not int or type(maximum) is not int:
        raise ValueError('Invalid resource limits')
    cpus=set()
    if cpu:
        for part in cpu.split(','):
            if not re.fullmatch(r'[0-9]{1,4}(?:-[0-9]{1,4})?',part):
                raise ValueError('CPUs must be numbers or ranges, for example 0-3,6')
            bounds=[int(value) for value in part.split('-')]
            first,last=bounds[0],bounds[-1]
            if first>last or last>=min(os.cpu_count() or 1,4096):
                raise ValueError('CPU selection exceeds the CPUs available on this VM')
            cpus.update(range(first,last+1))
    if any(value!=0 and not 256<=value<=4194304 for value in (high,maximum)):
        raise ValueError('Memory limits must be 0 (unlimited) or 256–4194304 MB')
    if maximum and high>maximum:
        raise ValueError('The hard memory limit cannot be below the soft target')
    ranges=[]
    for _,group in groupby(enumerate(sorted(cpus)),lambda item:item[1]-item[0]):
        values=[item[1] for item in group]
        ranges.append(str(values[0]) if len(values)==1 else f'{values[0]}-{values[-1]}')
    return dict(cpus=','.join(ranges),memory_high_mb=high,memory_max_mb=maximum)


def limit_args(server_id,cpu,high,maximum):
    if server_id!='__existing__' and not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',server_id):
        raise ValueError('Invalid instance ID')
    if not high.isdigit() or not maximum.isdigit():
        raise ValueError('Invalid memory limit')
    limits=normalize_limits(cpu,int(high),int(maximum))
    unit='arma-server.service' if server_id=='__existing__' else f'arma-server@{server_id}.service'
    return ['/usr/bin/systemctl','set-property','--runtime',unit,'AllowedCPUs='+limits['cpus'].replace(',',' '),
            'MemoryHigh='+str(limits['memory_high_mb']*1000000 or 'infinity'),
            'MemoryMax='+str(limits['memory_max_mb']*1000000 or 'infinity')]


if __name__ == '__main__':
    try:
        if len(sys.argv)==6 and sys.argv[1]=='limits':
            args=limit_args(*sys.argv[2:])
        elif len(sys.argv)==3:
            args=service_args(*sys.argv[1:])
        else:
            raise ValueError('Expected a fixed service action or resource limits')
        sys.exit(subprocess.run(args,timeout=150).returncode)
    except (ValueError, subprocess.TimeoutExpired) as exc:
        sys.exit(str(exc))
