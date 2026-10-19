"""Validated per-server launch options; managed paths and ports stay in config."""
import json
import os
from pathlib import Path
import shutil
import sys

DEFAULTS = dict(no_sound=False, no_throw=False, force_update=False, single_threaded=False,
                ai_limit=None, ai_partial_sim=None, log_stats_ms=1000)


def validate(data):
    if not isinstance(data, dict) or set(data) - DEFAULTS.keys():
        raise ValueError('Unsupported launch settings')
    result = {**DEFAULTS, **data}
    for key in ('no_sound', 'no_throw', 'force_update', 'single_threaded'):
        if type(result[key]) is not bool:
            raise ValueError(f'{key} must be enabled or disabled')
    for key, low, high in [('ai_limit', 0, 10000), ('ai_partial_sim', 1, 64), ('log_stats_ms', 1000, 10000)]:
        value = result[key]
        if value is None and key != 'log_stats_ms':
            continue
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be a whole number from {low} to {high}')
    return result


def load(registry, server_id):
    with registry.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS server_launch_options (server_id TEXT PRIMARY KEY, options TEXT NOT NULL)')
        row = conn.execute('SELECT options FROM server_launch_options WHERE server_id=?', (server_id,)).fetchone()
    return validate(json.loads(row[0]) if row else {})


def save(registry, server_id, data):
    options = validate(data)
    load(registry, server_id)
    with registry.connect() as conn:
        conn.execute('INSERT INTO server_launch_options VALUES(?,?) ON CONFLICT(server_id) DO UPDATE SET options=excluded.options', (server_id, json.dumps(options)))


def arguments(options):
    options = validate(options)
    args = ['-logStats', str(options['log_stats_ms'])]
    for key, flag in [('no_sound','-noSound'),('no_throw','-noThrow'),('force_update','-forceUpdate'),('single_threaded','-singleThreadedUpdate')]:
        if options[key]: args.append(flag)
    for key, flag in [('ai_limit','-aiLimit'),('ai_partial_sim','-aiPartialSim')]:
        if options[key] is not None: args.extend([flag, str(options[key])])
    return args


def diagnostics(api):
    from config_editor import FIELDS, validate_value
    from network_status import udp_listener_status
    rows = []
    def check(label, state, message): rows.append(dict(label=label, state=state, message=message))
    binary = Path(str(api.SERVER_DIR)) / api.SERVER_BINARY
    check('Game executable', 'ok' if binary.is_file() and (sys.platform!='linux' or os.access(binary,os.X_OK)) else 'error',
          'Installed and executable' if binary.is_file() and (sys.platform!='linux' or os.access(binary,os.X_OK)) else 'Missing or not executable. Install/validate the game files in Administration → Maintenance.')
    try:
        config = api.read_config()
    except api.ConfigReadError:
        check('Server configuration', 'error', 'Missing, unreadable or invalid JSON. Repair the server configuration file before starting.')
        config = None
    if config is not None:
        errors = []
        for path, spec in FIELDS.items():
            value = config
            for part in path.split('.'):
                if not isinstance(value,dict) or part not in value: value=None;break
                value=value[part]
            if value is not None:
                try: validate_value(spec,value)
                except ValueError as exc: errors.append(str(exc))
        check('Configuration fields', 'error' if errors else 'ok', '; '.join(errors[:8]) if errors else 'Known fields pass panel validation. The game remains the final schema validator.')
        check('Scenario', 'ok' if config.get('game',{}).get('scenarioId') else 'error',
              'Scenario is configured; installed resources are checked by the game at startup.' if config.get('game',{}).get('scenarioId') else 'Choose a scenario in Server config or Mods.')
        for section in ('rcon','a2s'):
            if config.get(section) is not None and not isinstance(config[section],dict):
                check(section.upper()+' structure','error','Must be a JSON object. Repair this section in Server config.')
        rcon=config.get('rcon') if isinstance(config.get('rcon'),dict) else {}
        a2s=config.get('a2s') if isinstance(config.get('a2s'),dict) else {}
        ready=rcon.get('permission')=='admin' and bool(api._cfg.get('RCON_PASSWORD') or rcon.get('password'))
        check('Admin RCON', 'ok' if ready else 'warn', 'Configured; use Players or Console to test the connection.' if ready else 'Configure admin RCON for moderation and scheduled warnings. Restart after changing it.')
        pid=api.get_server_pid()
        ports=[('Game',config.get('bindPort',2001)),('Query',a2s.get('port'))]
        if rcon.get('password'): ports.append(('RCON',rcon.get('port',19999)))
        for name,port in ports:
            if port is None: continue
            state=udp_listener_status(pid,port) if sys.platform=='linux' else 'unknown'
            message=f'UDP {port}: {state}. External router/firewall reachability is not tested.'
            level='ok' if state=='bound' else 'warn' if pid and state=='not bound' else 'info'
            if not pid and sys.platform=='linux':
                try:
                    occupied=False
                    for family in ('udp','udp6'):
                        table=Path('/proc/net')/family
                        if table.exists():
                            occupied |= any(int(line.split()[1].rsplit(':',1)[1],16)==port for line in table.read_text().splitlines()[1:] if len(line.split())>2)
                    if occupied: level='error';message=f'UDP {port} is already bound while this server is stopped. Check for another server using this port.'
                except (OSError,ValueError): pass
            check(name+' listener',level,message)
    try:
        folder=Path(str(api.SERVER_DIR))
        while not folder.exists() and folder!=folder.parent: folder=folder.parent
        free=shutil.disk_usage(folder).free
        check('Free storage','warn' if free<10_000_000_000 else 'ok',f'{free/1e9:.1f} GB free on the game filesystem. Updates and Workshop downloads need additional space.')
    except OSError: check('Free storage','info','Could not read filesystem usage.')
    if sys.platform=='linux':
        try: supported=b'def limit_args(' in Path('/etc/arma-panel/instance-control.py').read_bytes()[:16384]
        except OSError: supported=False
        check('Resource helper','ok' if supported else 'warn','Resource-limit helper installed.' if supported else 'Run install.sh --update before using CPU or memory limits.')
    check('Public connectivity','info','A running process or bound port does not prove that players can join. Check Network and test from outside the VM network.')
    return rows
