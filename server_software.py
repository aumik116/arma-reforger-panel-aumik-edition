"""Fixed-command SteamCMD jobs; Linux file lock survives panel restarts."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

APP_ID = '1874900'


def parse_vdf(text):
    tokens = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"|([{}])', text)
    root, stack, key = {}, [], None
    current = root
    for word, brace in tokens:
        if brace == '{':
            child = {}
            current[key] = child
            stack.append(current)
            current, key = child, None
        elif brace == '}':
            if not stack:
                raise ValueError('Invalid Steam manifest')
            current, key = stack.pop(), None
        elif key is None:
            key = word
        else:
            current[key], key = word, None
    if stack:
        raise ValueError('Incomplete Steam manifest')
    return root


def installed_build(directory):
    try:
        state = parse_vdf((Path(directory) / 'steamapps' / f'appmanifest_{APP_ID}.acf').read_text())['AppState']
        if state.get('appid') == APP_ID and str(state.get('buildid', '')).isdigit():
            return state['buildid']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def steam_command(executable, directory, action):
    args = [executable, '+@ShutdownOnFailedCommand', '1', '+@NoPromptForPassword', '1',
            '+force_install_dir', directory, '+login', 'anonymous']
    if action == 'update':
        return args + ['+app_update', APP_ID, '+quit']
    if action == 'check':
        return args + ['+app_info_update', '1', '+app_info_print', APP_ID, '+quit']
    raise ValueError('Unknown software action')


def write_state(path, state):
    temporary = str(path) + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as stream:
        json.dump(state, stream)
    os.replace(temporary, path)


class SoftwareManager:
    def __init__(self, api):
        self.api = api
        self.path = Path(api._BASE_DIR) / '.software-job.json'
        self.lock_path = Path(api._BASE_DIR) / '.software-job.lock'

    def executable(self):
        configured = self.api._cfg.get('STEAMCMD_PATH')
        candidates = [configured] if configured else [str(Path(self.api.SERVER_DIR).parent / 'steamcmd' / 'steamcmd.sh'), shutil.which('steamcmd'), '/usr/games/steamcmd']
        return next((p for p in candidates if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)

    def acquire(self):
        import fcntl
        stream = open(self.lock_path, 'a+')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return stream
        except BlockingIOError:
            stream.close()
            return None

    def busy(self):
        if sys.platform != 'linux':
            return False
        stream = self.acquire()
        if stream is None:
            return True
        stream.close()
        return False

    def status(self):
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {'state': 'idle', 'output': '', 'message': 'No software job has run.'}
        busy = self.busy()
        if state.get('state') == 'running' and not busy:
            state.update(state='interrupted', message='Job interrupted. Check the installation before starting the server.')
        state.update(busy=busy, installed_build=installed_build(self.api.SERVER_DIR),
                     server_running=bool(self.api.get_server_pid()), supported=sys.platform == 'linux',
                     steamcmd_available=bool(self.executable()))
        return state

    def launch(self, action, actor):
        if sys.platform != 'linux':
            raise ValueError('SteamCMD jobs require the Linux production host.')
        executable = self.executable()
        if not executable:
            raise ValueError('SteamCMD not found. Set STEAMCMD_PATH in config.env to its executable path.')
        if not os.path.isabs(self.api.SERVER_DIR) or not os.path.isdir(self.api.SERVER_DIR):
            raise ValueError('SERVER_DIR must be an existing absolute directory.')
        lock = self.acquire()
        if lock is None:
            raise ValueError('A software job is already running.')
        try:
            if action == 'update':
                manifest = Path(self.api.SERVER_DIR) / 'steamapps' / f'appmanifest_{APP_ID}.acf'
                if manifest.exists():
                    app_state = parse_vdf(manifest.read_text())['AppState']
                    branch = app_state.get('UserConfig', {}).get('BetaKey', 'public')
                    if branch and branch.lower() != 'public':
                        raise ValueError('Custom beta installations must be updated outside the panel.')
                if self.api.get_server_pid():
                    raise ValueError('Stop the game server before updating.')
                # Cancel pending systemd automatic restarts as well as checking the PID.
                self.api.service_command('stop')
                if self.api.get_server_pid():
                    raise ValueError('The game server is still running.')
            state = {'state': 'running', 'action': action, 'actor': actor, 'started': time.time(),
                     'message': 'Starting SteamCMD…', 'output': ''}
            write_state(self.path, state)
            try:
                subprocess.Popen([sys.executable, os.path.abspath(__file__), str(self.path), executable,
                                  self.api.SERVER_DIR, action, str(lock.fileno())],
                                 pass_fds=(lock.fileno(),), start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                state.update(state='failed', message='Could not launch SteamCMD worker.')
                write_state(self.path, state)
                raise
        finally:
            lock.close()


def worker(path, executable, directory, action, lock_fd):
    state = json.loads(Path(path).read_text())
    process = None
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(steam_command(executable, directory, action), cwd=os.path.dirname(executable),
                                       stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                       pass_fds=(lock_fd,), start_new_session=True)
            deadline = time.monotonic() + (1800 if action == 'update' else 180)
            while True:
                returncode = process.poll()
                size = os.fstat(output.fileno()).st_size
                text = os.pread(output.fileno(), min(size, 65536), max(0, size - 65536)).decode('utf-8', errors='replace')
                state.update(output=text[-16000:], message='SteamCMD is running…')
                write_state(path, state)
                if returncode is not None:
                    break
                if time.monotonic() > deadline or size > 8 * 1024 * 1024:
                    raise RuntimeError('SteamCMD exceeded its time or output limit.')
                time.sleep(1)
            if process.returncode != 0:
                raise RuntimeError(f'SteamCMD exited with code {process.returncode}. Review the output and retry.')
            if action == 'check':
                text = os.pread(output.fileno(), min(size, 8 * 1024 * 1024), 0).decode('utf-8', errors='replace')
                data = parse_vdf(text)
                build = data[APP_ID]['depots']['branches']['public']['buildid']
                if not str(build).isdigit():
                    raise ValueError('Invalid public build ID')
                state.update(latest_build=build, checked_at=time.time(), message='Public Steam build checked.')
            else:
                if f"Success! App '{APP_ID}' fully installed." not in text or not installed_build(directory):
                    raise RuntimeError('SteamCMD did not confirm a complete installation. Review output before starting.')
                state['message'] = 'Update completed. The game server remains stopped.'
            state['state'] = 'success'
    except Exception as exc:
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        state.update(state='failed', message=str(exc))
    finally:
        state['finished'] = time.time()
        write_state(path, state)
        os.close(lock_fd)


def install(api):
    from flask import jsonify, g
    manager = SoftwareManager(api)
    api.software_manager = manager

    @api.app.get('/api/software')
    def software_status():
        return jsonify(manager.status())

    @api.app.post('/api/software/check')
    def software_check():
        return launch('check')

    @api.app.post('/api/software/update')
    def software_update():
        return launch('update')

    def launch(action):
        try:
            manager.launch(action, g.user['username'])
            return jsonify(ok=True), 202
        except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
            return jsonify(ok=False, error=str(exc)), 409


if __name__ == '__main__':
    worker(*sys.argv[1:5], int(sys.argv[5]))
