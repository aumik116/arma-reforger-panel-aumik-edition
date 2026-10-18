"""Detached, file-locked local instance provisioning with persistent progress."""
import copy
import json
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import tempfile
import shutil
from contextlib import ExitStack

from server_registry import ServerRegistry
from server_software import APP_ID, installed_build, steam_command, write_state

CONTROL = '/etc/arma-panel/instance-control.py'
DEFAULT_SCENARIO = '{ECC61978EDCC2B5A}Missions/23_Campaign.conf'


def seed_installation(source, destination):
    """Copy game assets into independent files; Steam verifies the result."""
    source, destination = Path(source), Path(destination)
    if not (source / 'ArmaReforgerServer').is_file():
        return 0
    def ignore_links(directory, names):
        return [name for name in names if (Path(directory) / name).is_symlink()]
    copied = 0
    for item in source.iterdir():
        if item.is_symlink():
            continue
        if item.is_dir() and item.name.lower() in ('addons', 'battleye', 'lib', 'bin'):
            shutil.copytree(item, destination / item.name, dirs_exist_ok=True, ignore=ignore_links)
            copied += 1
        elif item.is_file() and (item.name == 'ArmaReforgerServer' or re.fullmatch(r'.+\.so(?:\.[0-9]+)*', item.name)):
            shutil.copy2(item, destination / item.name)
            copied += 1
    manifest = source / 'steamapps' / f'appmanifest_{APP_ID}.acf'
    if manifest.is_file() and not manifest.is_symlink() and not manifest.parent.is_symlink():
        (destination / 'steamapps').mkdir(exist_ok=True)
        shutil.copy2(manifest, destination / 'steamapps' / manifest.name)
    return copied


def available(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False


def instance_config(server, source=None, max_players=64):
    if type(max_players) is not int or not 1 <= max_players <= 128:
        raise ValueError('Player limit must be between 1 and 128')
    if source is not None and (not isinstance(source, dict) or not isinstance(source.get('game'), dict)
                               or not isinstance(source['game'].get('gameProperties', {}), dict)):
        raise ValueError('Source configuration has an invalid game section')
    config = copy.deepcopy(source or {'game': {'scenarioId': DEFAULT_SCENARIO, 'mods': [],
        'visible': True, 'crossPlatform': True, 'supportedPlatforms': ['PLATFORM_PC', 'PLATFORM_XBL', 'PLATFORM_PSN']}})
    config.update(bindAddress='0.0.0.0', bindPort=server.game_port,
                  publicAddress='', publicPort=server.game_port,
                  a2s={'address':'0.0.0.0', 'port':server.query_port},
                  rcon={'address':'127.0.0.1', 'port':server.rcon_port,
                        'password':secrets.token_hex(16), 'permission':'admin'})
    config['game'].update(name=server.name, maxPlayers=max_players, password='', passwordAdmin='')
    persistence = config['game'].get('gameProperties', {}).get('persistence')
    if isinstance(persistence, dict):
        persistence['hiveId'] = 0
    return config


def service_command(action, server_id):
    # The root-owned helper validates both arguments; no shell or arbitrary units.
    result = subprocess.run(['sudo', '-n', CONTROL, action, server_id],
                            capture_output=True, text=True, timeout=150)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Instance service command failed. Run the updated installer and check the service journal.')


def lock_job(directory, filename='.provision.lock'):
    import fcntl
    stream = open(directory / filename, 'a+')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except BlockingIOError:
        stream.close()
        raise ValueError('Provisioning is already running')


def status(registry, server_id):
    server = registry.get(server_id)
    path = server.directory / '.provision.json'
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {'state':server.state, 'message':'No provisioning job has run.'}
    if server.state == 'failed' and state.get('state') == 'provisioning':
        state.update(state='failed', message='Provisioning could not launch. Retry to resume.')
    if server.state == 'ready':
        state.update(state='ready', message='Installation complete. Instance is ready to manage.')
    if state.get('state') == 'failed' and 'startup_output' not in state and (
            state.get('startup_attempted') or 'startup' in state.get('message', '').lower()):
        try:
            result = subprocess.run(['sudo', '-n', CONTROL, 'diagnostics', server_id],
                                    capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                state['startup_output'] = result.stdout[-65536:]
                write_state(path, state)
            else:
                state['startup_output'] = 'Could not read startup journal: ' + result.stderr.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            state['startup_output'] = 'Could not read startup journal: ' + str(exc)
    log = server.directory / 'provision.log'
    try:
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 32768))
            state['output'] = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', stream.read(32768).decode('utf-8', errors='replace'))
    except OSError:
        state['output'] = ''
    if server.state == 'provisioning':
        try:
            lock = lock_job(server.directory)
        except ValueError:
            pass
        else:
            lock.close()
            state.update(state='interrupted', message='Provisioning was interrupted. Retry to resume the download.')
    return state


def launch(registry, server_id, executable):
    server = registry.get(server_id)
    if server.state == 'ready':
        raise ValueError('Server is already provisioned')
    lock = lock_job(server.directory)
    try:
        repair_rcon_password(server)
        registry.set_state(server_id, 'provisioning')
        write_state(server.directory / '.provision.json',
                    {'state':'provisioning', 'message':'Starting game installation…'})
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), registry.database,
                          str(registry.root), server_id, executable, str(lock.fileno())],
                         pass_fds=(lock.fileno(),), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        registry.set_state(server_id, 'failed')
        raise
    finally:
        lock.close()


def repair_rcon_password(server):
    """Repair overlong passwords generated by the initial provisioning release."""
    path = server.paths['config']
    config = json.loads(path.read_text())
    rcon = config.get('rcon', {})
    password = rcon.get('password') if isinstance(rcon, dict) else None
    if not isinstance(password, str) or len(password) <= 32:
        return False
    from config_backups import backup_current
    backup_current(path)
    rcon['password'] = secrets.token_hex(16)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(config, stream, indent=2)
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return True


def worker(database, root, server_id, executable, lock_fd):
    registry = ServerRegistry(database, root)
    server = registry.get(server_id)
    state_path = server.directory / '.provision.json'
    def progress(state, message):
        registry.set_state(server_id, state)
        write_state(state_path, {'state':state, 'message':message, 'updated':time.time(),
                                 'startup_attempted':started})
    started = False
    try:
        options_path = server.directory / '.provision-options.json'
        if not (server.paths['server'] / 'ArmaReforgerServer').is_file():
            try:
                options = json.loads(options_path.read_text())
            except (OSError, ValueError):
                options = {}
            if options.get('seed_directory'):
                progress('provisioning', 'Copying existing game files before Steam validation…')
                try:
                    with lock_job(Path(options['seed_state_directory']), '.software-job.lock'):
                        seed_installation(options['seed_directory'], server.paths['server'])
                except (OSError, ValueError, shutil.Error):
                    # Missing/busy source: Steam fills any incomplete local copy.
                    pass
        progress('provisioning', 'Downloading and validating the game server…')
        with (server.directory / 'provision.log').open('w') as log:
            result = subprocess.run(steam_command(executable, str(server.paths['server']), 'update')[:-1]
                                    + ['validate', '+quit'], stdout=log, stderr=subprocess.STDOUT, timeout=7200)
        binary = server.paths['server'] / 'ArmaReforgerServer'
        # A successful exit or old binary alone is not sufficient.
        with (server.directory / 'provision.log').open('rb') as stream:
            stream.seek(max(0, stream.seek(0, 2) - 131072))
            output = stream.read().decode('utf-8', errors='replace')
        if result.returncode or not binary.is_file() or not os.access(binary, os.X_OK) or not installed_build(server.paths['server']) or (
            f"Success! App '{APP_ID}' fully installed" not in output and
            f"Success! App '{APP_ID}' already up to date" not in output):
            raise ValueError('Game installation was not verified. Review the installation output and retry.')
        if any(not available(port) for port in (server.game_port, server.query_port, server.rcon_port)):
            raise ValueError('An assigned port is now occupied. Stop the conflicting service before retrying.')
        progress('provisioning', 'Starting the new server…')
        service_command('enable', server_id)
        started = True
        service_command('start', server_id)
        time.sleep(4)
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', server.service_name],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ValueError('Server exited during startup. Review its console before retrying.')
        progress('ready', 'Installation complete. Server process is running; mission loading may still be in progress.')
    except Exception as exc:
        if started:
            try:
                service_command('stop', server_id)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
        progress('failed', str(exc))
    finally:
        os.close(int(lock_fd))


def install(api):
    from flask import g, jsonify, request
    registry = api.server_registry
    api.PROVISIONING_ENDPOINTS = {'servers_create', 'server_provision_status', 'server_provision_retry',
                                'server_delete', 'server_startup_save'}

    def executable():
        if sys.platform != 'linux':
            raise ValueError('Server provisioning requires the Linux host')
        if not Path(CONTROL).is_file():
            raise ValueError('Run the updated installer once to enable instance services')
        path = api.software_manager.executable()
        if not path:
            raise ValueError('SteamCMD is unavailable. Configure STEAMCMD_PATH in config.env')
        return path

    @api.app.post('/api/servers')
    def servers_create():
        try:
            steamcmd = executable()
            data = request.get_json()
            if data.get('copy_from') is not None and not isinstance(data['copy_from'], str):
                raise ValueError('Source server must be a server ID')
            source = None
            seed_directory = str(api.SERVER_DIR)
            seed_state_directory = api._BASE_DIR
            if data.get('copy_from'):
                if data['copy_from'] == '__existing__':
                    source = api.read_config()
                else:
                    origin = registry.get(data['copy_from'])
                    if origin.state != 'ready':
                        raise ValueError('Source server must be provisioned')
                    source = json.loads(origin.paths['config'].read_text())
                    seed_directory = str(origin.paths['server'])
                    seed_state_directory = str(origin.directory)
            if not (Path(seed_directory) / 'ArmaReforgerServer').is_file():
                for origin in registry.list():
                    if origin.state == 'ready' and (origin.paths['server'] / 'ArmaReforgerServer').is_file():
                        seed_directory, seed_state_directory = str(origin.paths['server']), str(origin.directory)
                        break
            limit = data.get('max_players', 64)
            if type(limit) is not int or not 1 <= limit <= 128:
                raise ValueError('Player limit must be between 1 and 128')
            server = registry.register(data.get('server_id'), data.get('name'),
                game_port=data.get('game_port'), query_port=data.get('query_port'),
                rcon_port=data.get('rcon_port'), port_available=available, max_fps=data.get('max_fps', 60))
            try:
                server.directory.mkdir(parents=True, mode=0o700)
                for key in ('server', 'profile', 'logs', 'workshop', 'backups'):
                    server.paths[key].mkdir(mode=0o700)
                config = server.paths['config']
                config.write_text(json.dumps(instance_config(server, source, limit), indent=2))
                config.chmod(0o600)
                options = server.directory / '.provision-options.json'
                options.write_text(json.dumps({'seed_directory':seed_directory,
                                                'seed_state_directory':seed_state_directory}))
                options.chmod(0o600)
                launch(registry, server.id, steamcmd)
            except Exception:
                registry.set_state(server.id, 'failed')
                raise
            g.audit_details = {'server_id':server.id, 'copy_from':data.get('copy_from')}
            return jsonify(ok=True, server_id=server.id), 202
        except (ValueError, KeyError, OSError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get('/api/servers/<server_id>/provision')
    def server_provision_status(server_id):
        try:
            return jsonify(status(registry, server_id))
        except KeyError:
            return jsonify(ok=False, error='Unknown server'), 404

    @api.app.post('/api/servers/<server_id>/startup')
    def server_startup_save(server_id):
        try:
            registry.set_max_fps(server_id, request.get_json().get('max_fps'))
            g.audit_details = {'server_id':server_id, 'max_fps':request.get_json()['max_fps']}
            return jsonify(ok=True, restart_required=bool(api.get_server_pid()))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post('/api/servers/<server_id>/delete')
    def server_delete(server_id):
        try:
            if sys.platform != 'linux' or not Path(CONTROL).is_file():
                raise ValueError('Removal requires the updated Linux installer')
            if request.get_json().get('confirm_id') != server_id:
                raise ValueError('Type the server ID to confirm removal')
            server = registry.get(server_id)
            archived = None
            with ExitStack() as locks:
                if server.directory.exists():
                    locks.enter_context(lock_job(server.directory))
                    locks.enter_context(lock_job(server.directory, '.software-job.lock'))
                service_command('stop', server_id)
                service_command('disable', server_id)
                if server.directory.exists():
                    archive_root = registry.root / '.removed'
                    if archive_root.resolve() != archive_root:
                        raise ValueError('Archive directory must not be a symlink')
                    archive_root.mkdir(mode=0o700, exist_ok=True)
                    archived = archive_root / f'{server_id}-{secrets.token_hex(8)}'
                    server.directory.rename(archived)
                try:
                    registry.remove(server_id)
                except Exception:
                    if archived:
                        archived.rename(server.directory)
                    raise
            api.clear_instance_state(server_id)
            g.audit_details = {'server_id':server_id, 'files_archived':bool(archived)}
            return jsonify(ok=True, archived=str(archived) if archived else None)
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return jsonify(ok=False, error=str(exc)), 409

    @api.app.post('/api/servers/<server_id>/provision/retry')
    def server_provision_retry(server_id):
        try:
            steamcmd = executable()
            server = registry.get(server_id)
            if not server.paths['config'].is_file():
                raise ValueError('Instance configuration is missing; this job cannot be resumed')
            launch(registry, server_id, steamcmd)
            g.audit_details = {'server_id':server_id}
            return jsonify(ok=True), 202
        except KeyError:
            return jsonify(ok=False, error='Unknown server'), 404
        except (ValueError, OSError) as exc:
            return jsonify(ok=False, error=str(exc)), 409


if __name__ == '__main__':
    worker(*sys.argv[1:])
