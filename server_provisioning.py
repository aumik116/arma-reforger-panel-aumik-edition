"""Detached, file-locked local instance provisioning with persistent progress."""
import copy
import ipaddress
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
    def copy_asset(item, target):
        if item.is_symlink():
            return
        if target.is_symlink():
            raise ValueError('Game asset destination must not be a symlink: ' + target.name)
        if item.is_dir():
            target.mkdir(exist_ok=True)
            for child in item.iterdir():
                copy_asset(child, target / child.name)
        elif item.is_file():
            # Replace each inode, rather than overwriting a hard-linked installation.
            fd, temporary = tempfile.mkstemp(prefix='.game-copy-', dir=target.parent)
            os.close(fd)
            try:
                shutil.copy2(item, temporary)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    copied = 0
    for item in source.iterdir():
        if item.is_symlink():
            continue
        if item.is_dir() and item.name.lower() in ('addons', 'battleye', 'lib', 'bin'):
            copy_asset(item, destination / item.name)
            copied += 1
        elif item.is_file() and (item.name == 'ArmaReforgerServer' or re.fullmatch(r'.+\.so(?:\.[0-9]+)*', item.name)):
            copy_asset(item, destination / item.name)
            copied += 1
    manifest = source / 'steamapps' / f'appmanifest_{APP_ID}.acf'
    if manifest.is_file() and not manifest.is_symlink() and not manifest.parent.is_symlink():
        if (destination / 'steamapps').is_symlink():
            raise ValueError('Steam manifest directory must not be a symlink')
        (destination / 'steamapps').mkdir(exist_ok=True)
        copy_asset(manifest, destination / 'steamapps' / manifest.name)
    return copied


def available(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('0.0.0.0', port))
        return True
    except OSError:
        return False


def validate_public_address(value):
    if not isinstance(value, str):
        raise ValueError('Public address must be an IPv4 address or blank')
    value = value.strip()
    try:
        if value:
            ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError('Public address must be an IPv4 address or blank') from None
    return value


def instance_config(server, source=None, max_players=64, public_address=''):
    public_address = validate_public_address(public_address)

    if type(max_players) is not int or not 1 <= max_players <= 128:
        raise ValueError('Player limit must be between 1 and 128')
    if source is not None and (not isinstance(source, dict) or not isinstance(source.get('game'), dict)
                               or not isinstance(source['game'].get('gameProperties', {}), dict)):
        raise ValueError('Source configuration has an invalid game section')
    config = copy.deepcopy(source or {'game': {'scenarioId': DEFAULT_SCENARIO, 'mods': [],
        'visible': True, 'crossPlatform': True, 'supportedPlatforms': ['PLATFORM_PC', 'PLATFORM_XBL', 'PLATFORM_PSN']}})
    config.update(bindAddress='0.0.0.0', bindPort=server.game_port,
                  publicAddress=public_address, publicPort=server.game_port,
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


def retained_server_folder(registry, relative):
    """Only recognize direct managed-server folders, including the old .removed archive."""
    if not isinstance(relative,str):
        raise ValueError('Choose a retained server folder')
    parts=Path(relative).parts
    if len(parts)==1 and re.fullmatch(r'[a-z][a-z0-9-]{0,31}',parts[0]):
        server_id=parts[0]
        if any(server.id==server_id for server in registry.list()):
            raise ValueError('This server is still registered; use its Remove button')
    elif len(parts)==2 and parts[0]=='.removed':
        match=re.fullmatch(r'([a-z][a-z0-9-]{0,31})-[0-9a-f]{16}',parts[1])
        if not match:raise ValueError('Unrecognized archived server folder')
        server_id=match[1]
    else:
        raise ValueError('Choose a direct retained server folder')
    path=registry.root/relative
    if path.resolve()!=path or not path.is_dir():
        raise ValueError('Folder is missing or redirects through a link')
    if len(parts)==1 and not ((path/'config.json').is_file() or (path/'server'/'ArmaReforgerServer').is_file() or (path/'.provision-options.json').is_file()):
        raise ValueError('Folder does not contain a recognizable panel server')
    return path,server_id


def folder_revision(path):
    info=path.stat()
    return f'{info.st_dev}:{info.st_ino}:{info.st_mtime_ns}'


def purge_server_folder(registry, path):
    """Delete a retained instance, never another registered server or a mounted volume."""
    path,server_id=retained_server_folder(registry,path.relative_to(registry.root).as_posix())
    if sys.platform!='linux' or not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError('Safe server-file cleanup requires Linux')
    # Archived folders can share an ID with a newly created server. Check actual paths too.
    if not any(server.id==server_id for server in registry.list()):
        state=subprocess.run(['/usr/bin/systemctl','show',f'arma-server@{server_id}.service','--property=ActiveState','--property=MainPID','--property=LoadState'],capture_output=True,text=True,timeout=15)
        fields=dict(line.split('=',1) for line in state.stdout.splitlines() if '=' in line)
        missing=fields.get('LoadState')=='not-found'
        if state.returncode and not missing:raise ValueError('Could not verify the old server service state')
        if not missing and (fields.get('ActiveState') not in ('inactive','failed') or fields.get('MainPID','0')!='0'):
            raise ValueError('The old server service is still active; stop it before cleanup')
        if not missing:service_command('disable',server_id)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        for item in ('cwd','exe'):
            try:
                target=(proc/item).resolve(strict=True)
                if target==path or path in target.parents:
                    raise ValueError('A process is still using this server folder; stop it before cleanup')
            except OSError:pass
        try:
            arguments=(proc/'cmdline').read_bytes().split(b'\0')
            if any(argument.decode(errors='replace')==str(path) or argument.decode(errors='replace').startswith(str(path)+'/') for argument in arguments):
                raise ValueError('A process still references this server folder; stop it before cleanup')
        except OSError:pass
    with open('/proc/self/mountinfo') as stream:
        for line in stream:
            mount=line.split()[4]
            mount=re.sub(r'\\([0-7]{3})',lambda match:chr(int(match[1],8)),mount)
            if Path(mount)==path or path in Path(mount).parents:
                raise ValueError('Server folder contains a mounted volume; unmount it before cleanup')
    shutil.rmtree(path)


def install(api):
    from flask import g, jsonify, request
    registry = api.server_registry
    api.PROVISIONING_ENDPOINTS = {'servers_create', 'server_provision_status', 'server_provision_retry',
                                'server_delete', 'server_startup_save','server_removal_info'}

    api.PANEL_WIDE_ENDPOINTS.update({'server_cleanup_list','server_cleanup_delete'})
    from panel_features import MUTATIONS
    MUTATIONS['server_cleanup_delete']='users'

    @api.app.get('/api/server-cleanup')
    def server_cleanup_list():
        if 'users' not in g.panel_permissions:
            return jsonify(ok=False,error='Panel administrator access required'),403
        rows=[];skipped=0
        try:
            candidates=list(registry.root.iterdir()) if registry.root.exists() else []
            archive=registry.root/'.removed'
            if archive.is_dir() and archive.resolve()==archive:candidates+=list(archive.iterdir())
            for path in candidates:
                if path.name.startswith('.') or not path.is_dir():continue
                relative=path.relative_to(registry.root).as_posix()
                try:
                    folder,identity=retained_server_folder(registry,relative)
                    rows.append(dict(folder=relative,path=str(folder),server_id=identity,revision=folder_revision(folder),contents=sorted(child.name for child in folder.iterdir())[:30]))
                except (ValueError,OSError):skipped+=1
            return jsonify(ok=True,root=str(registry.root),folders=rows,skipped=skipped)
        except OSError as exc:return jsonify(ok=False,error=str(exc)),409

    @api.app.post('/api/server-cleanup/delete')
    def server_cleanup_delete():
        try:
            data=request.get_json() or {}
            folder,identity=retained_server_folder(registry,data.get('folder'))
            if data.get('confirm_id')!=identity:raise ValueError('Type the server ID to confirm permanent file deletion')
            if data.get('revision')!=folder_revision(folder):raise ValueError('The folder changed; refresh the cleanup list before deleting')
            with ExitStack() as locks:
                locks.enter_context(lock_job(folder));locks.enter_context(lock_job(folder,'.software-job.lock'))
                purge_server_folder(registry,folder)
            g.audit_details=dict(server_id=identity,deleted_folder=data['folder'])
            return jsonify(ok=True)
        except (ValueError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
            return jsonify(ok=False,error=str(exc)),409

    @api.app.get('/api/servers/<server_id>/removal')
    def server_removal_info(server_id):
        try:
            server=registry.get(server_id)
            return jsonify(ok=True,id=server.id,name=server.name,path=str(server.directory))
        except KeyError:return jsonify(ok=False,error='Server was already removed. Refresh the server list.'),404

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
            seed_directory = '' if api.manager_mode else str(api.SERVER_DIR)
            seed_state_directory = '' if api.manager_mode else api._BASE_DIR
            if data.get('copy_from'):
                if not api.server_permissions(g.user, data['copy_from']):
                    return jsonify(ok=False,error='You do not have access to the source server'),403
                if data['copy_from'] == '__existing__':
                    if api.manager_mode:
                        raise ValueError('This installation has no existing unmanaged server to copy')
                    source = api.read_config()
                else:
                    origin = registry.get(data['copy_from'])
                    if origin.state != 'ready':
                        raise ValueError('Source server must be provisioned')
                    source = json.loads(origin.paths['config'].read_text())
                    seed_directory = str(origin.paths['server'])
                    seed_state_directory = str(origin.directory)
            if not seed_directory or not (Path(seed_directory) / 'ArmaReforgerServer').is_file():
                for origin in registry.list():
                    if origin.state == 'ready' and (origin.paths['server'] / 'ArmaReforgerServer').is_file():
                        seed_directory, seed_state_directory = str(origin.paths['server']), str(origin.directory)
                        break
            limit = data.get('max_players', 64)
            if type(limit) is not int or not 1 <= limit <= 128:
                raise ValueError('Player limit must be between 1 and 128')
            public_address = validate_public_address(data.get('public_address', ''))
            server = registry.register(data.get('server_id'), data.get('name'),
                game_port=data.get('game_port'), query_port=data.get('query_port'),
                rcon_port=data.get('rcon_port'), port_available=available, max_fps=data.get('max_fps', 60))
            try:
                server.directory.mkdir(parents=True, mode=0o700)
                for key in ('server', 'profile', 'logs', 'workshop', 'backups'):
                    server.paths[key].mkdir(mode=0o700)
                config = server.paths['config']
                config.write_text(json.dumps(instance_config(server, source, limit, public_address), indent=2))
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
            delete_files=request.get_json().get('delete_files',False)
            if type(delete_files) is not bool:raise ValueError('Choose a valid file-removal option')
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
            api.clear_server_access(server_id)
            api.clear_instance_state(server_id)
            warning=''
            files_deleted=bool(delete_files and archived is None)
            if delete_files and archived:
                try:
                    purge_server_folder(registry,archived)
                    files_deleted=True
                except (ValueError,OSError,subprocess.SubprocessError) as exc:
                    warning='Server removed, but file cleanup did not finish: '+str(exc)+'. Use Clean up deleted servers to retry.'
            g.audit_details = {'server_id':server_id, 'files_archived':bool(archived) and not files_deleted,'files_deleted':files_deleted,'warning':warning}
            return jsonify(ok=True, archived=str(archived) if archived and not files_deleted else None,files_deleted=files_deleted,warning=warning)
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
