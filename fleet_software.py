"""Host-wide Steam checks and selected-server updates with one shared download."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from server_software import APP_ID, installed_build, parse_vdf, steam_command, write_state
from server_provisioning import lock_job, seed_installation


def public_install(directory):
    manifest = Path(directory) / 'steamapps' / f'appmanifest_{APP_ID}.acf'
    if manifest.exists():
        state = parse_vdf(manifest.read_text())['AppState']
        branch = state.get('UserConfig', {}).get('BetaKey', 'public')
        if branch and branch.lower() != 'public':
            raise ValueError('Custom beta installations must be updated outside the panel.')


def plain_directory(path):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError('Software directories must not redirect through symlinks.')
    return path


class FleetSoftware:
    def __init__(self, api):
        self.api = api
        self.base = Path(api._BASE_DIR)
        self.path = self.base / '.fleet-software.json'
        self.cache = api.server_registry.root / '.software-cache'

    def busy(self):
        if sys.platform != 'linux':
            return False
        try:
            with lock_job(self.base, '.fleet-software.lock'):
                return False
        except ValueError:
            return True

    def state(self):
        try:
            state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            state = {'state': 'idle', 'message': 'No fleet software job has run.', 'servers': []}
        state['busy'] = self.busy()
        if state.get('state') == 'running' and not state['busy']:
            state.update(state='interrupted', message='Update interrupted. Review affected servers before starting them; retry the update to validate their files.')
            for row in state.get('servers', []):
                if row['state'] not in ('success', 'failed'):
                    row.update(state='interrupted', message='Job interrupted; installation not confirmed.')
        return state

    def eligible(self, user):
        api = self.api
        targets = [(s.id, s.name) for s in api.server_registry.list() if s.state == 'ready']
        if not api.manager_mode:
            targets.insert(0, ('', 'Existing server'))
        result = []
        for server_id, name in targets:
            if 'admin_config' not in api.server_permissions(user, server_id):
                continue
            with api.operator_tools.selected(server_id):
                reason = ''
                try:
                    public_install(api.SERVER_DIR)
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    reason = str(exc) if isinstance(exc, ValueError) else 'Installation manifest needs repair before updating.'
                result.append(dict(id=server_id, name=name, installed_build=installed_build(api.SERVER_DIR),
                                   running=bool(api.get_server_pid()), busy=api.software_manager.busy(),
                                   update_allowed=not reason, update_reason=reason))
        return result

    def status(self, user):
        state = self.state()
        targets = self.eligible(user)
        allowed = {row['id'] for row in targets}
        state['servers'] = [row for row in state.get('servers', []) if row['id'] in allowed]
        # Worker output may contain paths for other instances; never expose it here.
        state.pop('output', None)
        state.pop('owner_id', None)
        state.pop('actor', None)
        return dict(state, targets=targets, supported=sys.platform == 'linux',
                    steamcmd_available=bool(self.api.software_manager.executable()))

    def launch(self, action, user, ids=None):
        api = self.api
        if sys.platform != 'linux':
            raise ValueError('Software updates require the Linux host.')
        executable = api.software_manager.executable()
        if not executable:
            raise ValueError('SteamCMD not found. Configure STEAMCMD_PATH.')
        eligible = {row['id']: row for row in self.eligible(user)}
        if not eligible:
            raise PermissionError('Server administrator access is required.')
        if action == 'update':
            if not isinstance(ids, list) or not ids or len(ids) > 128 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('Select 1–128 distinct servers to update.')
            if any(i not in eligible for i in ids):
                raise PermissionError('Every selected server must be ready and you must have server administrator access.')
        else:
            ids = []
        with ExitStack() as stack:
            global_lock = stack.enter_context(lock_job(self.base, '.fleet-software.lock'))
            descriptors = [global_lock.fileno()]
            rows = []
            # Coordinate with scheduled and interactive operations before handing locks to the worker.
            for server_id in sorted(ids):
                with api.operator_tools.selected(server_id):
                    operation = api.operation_lock._get_current_object()
                    if not operation.acquire(blocking=False):
                        raise ValueError('Another server operation is active. Retry when it finishes.')
                    stack.callback(operation.release)
                    with api.operator_tools.active_lock:
                        if server_id in api.operator_tools.active:
                            raise ValueError('A selected server has a scheduled operation in progress.')
                    directory = plain_directory(api.SERVER_DIR)
                    cache = plain_directory(self.cache)
                    if directory == cache or directory in cache.parents or cache in directory.parents:
                        raise ValueError('Shared download directory must be separate from every game installation.')
                    if not directory.is_dir():
                        raise ValueError('A selected installation directory is missing.')
                    public_install(directory)
                    for filename in ('.provision.lock', '.software-job.lock'):
                        lock = stack.enter_context(lock_job(Path(str(api._STATE_DIR)), filename))
                        descriptors.append(lock.fileno())
                    row = eligible[server_id]
                    rows.append(dict(id=server_id, name=row['name'], state='queued',
                                     was_running=bool(api.get_server_pid()), message='Waiting for shared download.'))
            previous = self.state()
            state = dict(state='running', action=action, owner_id=user['id'], actor=user['username'],
                         started=time.time(), message='Checking Steam…' if action == 'check' else 'Preparing shared download…',
                         servers=rows, latest_build=previous.get('latest_build'), checked_at=previous.get('checked_at'))
            write_state(self.path, state)
            try:
                subprocess.Popen([sys.executable, os.path.abspath(__file__), ','.join(map(str, descriptors))],
                    pass_fds=tuple(descriptors), start_new_session=True, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(self.base))
            except Exception:
                state.update(state='failed', message='Could not launch software worker.')
                for row in rows:
                    row.update(state='failed', message='Not updated; no stop requested.')
                write_state(self.path, state)
                raise


def run_steam(executable, directory, action, descriptors):
    args = steam_command(executable, str(directory), action)
    if action == 'update':
        args = args[:-1] + ['validate', '+quit']
    # Inherit the job locks so a killed panel worker cannot unlock an active Steam process.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(args, cwd=os.path.dirname(executable), stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, pass_fds=tuple(descriptors), start_new_session=True)
        try:
            deadline = time.monotonic() + (7200 if action == 'update' else 180)
            while process.poll() is None:
                if time.monotonic() > deadline or os.fstat(output.fileno()).st_size > 16 * 1024 * 1024:
                    raise RuntimeError('SteamCMD exceeded its time or output limit.')
                time.sleep(1)
        except BaseException:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        output.seek(0)
        text = output.read(16 * 1024 * 1024).decode('utf-8', errors='replace')
        if process.returncode:
            raise RuntimeError(f'SteamCMD exited with code {process.returncode}; retry the job.')
        if action == 'check':
            build = parse_vdf(text)[APP_ID]['depots']['branches']['public']['buildid']
            if not str(build).isdigit():
                raise ValueError('Steam returned an invalid public build ID.')
            return str(build)
        binary = Path(directory) / 'ArmaReforgerServer'
        build = installed_build(directory)
        if not build or not binary.is_file() or not os.access(binary, os.X_OK) or not any(
                message in text for message in (f"Success! App '{APP_ID}' fully installed", f"Success! App '{APP_ID}' already up to date")):
            raise RuntimeError('Steam did not confirm a complete installation; server will remain stopped.')
        return build


def worker(api, descriptors):
    manager = api.fleet_software
    state = json.loads(manager.path.read_text())
    def save(message):
        state['message'] = message
        write_state(manager.path, state)
    try:
        cache = plain_directory(manager.cache)
        cache.mkdir(parents=True, exist_ok=True)
        executable = api.software_manager.executable()
        if not executable:
            raise ValueError('SteamCMD is unavailable.')
        save('Checking Steam…' if state['action'] == 'check' else 'Downloading and validating shared game files; servers remain online…')
        build = run_steam(executable, cache, state['action'], descriptors)
        state.update(latest_build=build, checked_at=time.time())
        if state['action'] == 'update':
            for row in state['servers']:
                try:
                    api.operator_tools.authorized({'owner_id':state['owner_id'], 'server_id':row['id']})
                    with api.operator_tools.selected(row['id']):
                        directory = plain_directory(api.SERVER_DIR)
                        public_install(directory)
                        row.update(state='stopping', message='Stopping server before copying files.')
                        save('Updating selected servers…')
                        api.stop_server()
                        row.update(state='copying', message='Copying the shared game download.')
                        save('Updating selected servers…')
                        seed_installation(cache, directory)
                        row.update(state='validating', message='Validating copied files with Steam.')
                        save('Updating selected servers…')
                        actual = run_steam(executable, directory, 'update', descriptors)
                        if actual != build:
                            raise RuntimeError('Steam release changed during the update. Retry before starting this server.')
                        if row['was_running']:
                            row.update(state='restarting', message='Restarting previously running server.')
                            save('Updating selected servers…')
                            api.start_server()
                        row.update(state='success', installed_build=actual,
                                   message='Updated and restarted; process health confirmed.' if row['was_running'] else 'Updated; remains stopped.')
                except Exception as exc:
                    message = str(exc)
                    if row['state'] in ('copying', 'validating', 'restarting'):
                        try:
                            with api.operator_tools.selected(row['id']):
                                api.stop_server()
                            message += ' Server remains stopped.'
                        except Exception as stop_error:
                            message += ' Could not confirm the server is stopped: ' + str(stop_error)
                    row.update(state='failed', message=message)
                finally:
                    save('Updating selected servers…')
                    api.audit_event(state['actor'], 'fleet_software_server_update', row['state'],
                                    {'server_id':row['id'] or None, 'build':build, 'restarted':row['was_running'] and row['state']=='success'})
        failed = any(row['state'] == 'failed' for row in state['servers'])
        state['state'] = 'failed' if failed else 'success'
        save('Some servers could not be updated. Review each result before starting or retrying.' if failed else
             'Public Steam build checked.' if state['action'] == 'check' else 'Selected server updates completed.')
    except Exception as exc:
        state['state'] = 'failed'
        for row in state['servers']:
            if row['state'] == 'queued':
                row.update(state='failed', message='Not updated; no stop requested.')
        save(str(exc))
    finally:
        state['finished'] = time.time()
        write_state(manager.path, state)
        for descriptor in descriptors:
            os.close(descriptor)


def install(api):
    from flask import g, jsonify, request
    manager = api.fleet_software = FleetSoftware(api)
    api.PANEL_WIDE_ENDPOINTS.update({'fleet_software_status', 'fleet_software_check', 'fleet_software_update'})

    @api.app.get('/api/fleet/software')
    def fleet_software_status():
        return jsonify(manager.status(g.user))

    @api.app.post('/api/fleet/software/check')
    def fleet_software_check():
        return launch('check')

    @api.app.post('/api/fleet/software/update')
    def fleet_software_update():
        return launch('update')

    def launch(action):
        try:
            data = request.get_json(silent=True) or {}
            if action == 'update' and data.get('confirm') is not True:
                raise ValueError('Confirm the selected-server update and restart behavior.')
            ids = data.get('server_ids')
            manager.launch(action, g.user, ids)
            g.audit_details = {'server_ids': ids if action == 'update' else [], 'scope':'server_software_only'}
            return jsonify(ok=True), 202
        except PermissionError as exc:
            return jsonify(ok=False, error=str(exc)), 403
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409


if __name__ == '__main__':
    import app
    worker(app, [int(value) for value in sys.argv[1].split(',')])
