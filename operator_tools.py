"""Player history, fixed startup settings and scheduled local-server operations."""
from pathlib import Path
from datetime import datetime
import os
import re
import sys
import threading
import time
from contextlib import contextmanager

from flask import g, jsonify, request

import config_backups
from config_editor import apply_changes, revision
import player_query
import startup_settings
from scheduler import ScheduleStore, WARNED_ACTIONS


class OperatorTools:
    def __init__(self, api):
        self.api = api
        self.store = ScheduleStore(api.server_registry.database)
        self.active = set()
        self.active_lock = threading.Lock()

    @contextmanager
    def selected(self, server_id):
        with self.api.app.test_request_context('/internal/scheduled-operation'):
            if not server_id and self.api.manager_mode:
                raise ValueError('This installation has no unmanaged default server')
            if server_id:
                server = self.api.server_registry.get(server_id)
                if server.state != 'ready':
                    raise ValueError('Server is not ready')
                g.server_instance = server
            yield

    def authorized(self, row):
        with self.store.connect() as conn:
            owner = conn.execute('SELECT * FROM users WHERE id=?', (row['owner_id'],)).fetchone()
        if not owner or not owner['enabled'] or 'admin_config' not in self.api.server_permissions(dict(owner),row['server_id']):
            raise ValueError('Schedule owner no longer has administrator access')
        return owner['username']

    def broadcast(self, text):
        api = self.api
        config = api.read_config().get('rcon') or {}
        if config.get('permission', 'monitor') != 'admin':
            raise ValueError('Warnings require admin RCON permission and Server Admin Tools #message support')
        password = api._cfg.get('RCON_PASSWORD') or config.get('password')
        if not password:
            raise ValueError('Warnings require working RCON')
        host = api._cfg.get('RCON_HOST') or config.get('address') or '127.0.0.1'
        output = player_query.query_command('127.0.0.1' if host == '0.0.0.0' else host,
            int(api._cfg.get('RCON_PORT') or config.get('port', 19999)), password, '#message '+text)
        if any(word in output.lower() for word in ('unknown', 'not found', 'error', 'denied', 'invalid', 'unsupported')):
            raise ValueError('Server rejected the warning broadcast; check Server Admin Tools and RCON')

    def warn(self, row, now):
        remaining = row['run_at'] - now
        for minutes, earliest in ((5, 240), (1, 30)):
            field = 'warning5' if minutes == 5 else 'warning1'
            if not row[field] and remaining <= minutes*60:
                pid, error = -1, ''
                try:
                    self.authorized(row)
                    with self.selected(row['server_id']):
                        running = self.api.get_server_pid()
                        if running and remaining >= earliest:
                            self.broadcast(f'Scheduled server {row["action"]} in {minutes} minute'+('s.' if minutes != 1 else '.'))
                            pid = running
                        else:
                            error = 'Warning window missed or server was offline'
                except Exception as exc:
                    error = str(exc)
                self.store.warning(row, minutes, pid, error)

    def execute(self, row):
        api, state, message, actor = self.api, 'failed', '', 'scheduler'
        try:
            actor = self.authorized(row)
            with self.selected(row['server_id']):
                lock = api.operation_lock._get_current_object()
                if not lock.acquire(blocking=False):
                    raise ValueError('Another panel operation is active; run skipped')
                try:
                    if time.time() - row['scheduled_for'] > 90:
                        raise ValueError('Scheduled time was missed; this run was not replayed')
                    if api.software_manager.busy():
                        raise ValueError('Server software is already being updated')
                    pid = api.get_server_pid()
                    if row['action'] in WARNED_ACTIONS and pid and (row['warning5'] != pid or row['warning1'] != pid):
                        raise ValueError('Required 5-minute and 1-minute warnings were not delivered to this server process')
                    if row['action'] == 'start':
                        if pid: message='Server is already running; no second start sent.'
                        else: api.start_server();message='Server started; process health checked.'
                    elif row['action'] == 'stop':
                        if pid: api.stop_server();message='Server stopped after advance warnings.'
                        else: message='Server is already stopped.'
                    elif row['action'] == 'broadcast':
                        if not pid: raise ValueError('Server is offline; broadcast skipped')
                        self.broadcast(row['broadcast'])
                        message='Broadcast sent through admin RCON. Verify in-game delivery.'
                    elif row['action'] == 'restart':
                        if not pid:
                            raise ValueError('Server is offline; scheduled restart does not start stopped servers')
                        api.stop_server()
                        api.start_server()
                        message = 'Server restarted; process health checked. Mission/network readiness is separate.'
                    elif row['action'] == 'update':
                        if pid:
                            api.stop_server()
                        api.software_manager.launch('update', actor)
                        deadline = time.monotonic()+1900
                        while api.software_manager.busy():
                            if time.monotonic() >= deadline:
                                raise RuntimeError('Update timed out; server remains stopped for review')
                            time.sleep(2)
                        result = api.software_manager.status()
                        if result.get('state') != 'success':
                            raise RuntimeError(result.get('message', 'Update failed; server remains stopped'))
                        if pid:
                            api.start_server()
                        message = 'Game updated. '+('Previously running server restarted.' if pid else 'Previously stopped server remains stopped.')
                    else:
                        if config_backups.backup_current(api.SERVER_CONFIG) is None:
                            raise ValueError('Server configuration is missing')
                        message = 'Server configuration backed up. Game/world files were not included.'
                    state = 'success'
                finally:
                    lock.release()
        except Exception as exc:
            message = str(exc)
        finally:
            try:
                self.store.finish(row['run_id'], state, message)
                api.audit_event(actor, 'scheduled_'+row['action'], state,
                                {'server_id':row['server_id'] or None,'schedule_id':row['id'],'run_id':row['run_id']})
            finally:
                with self.active_lock:
                    self.active.discard(row['server_id'])

    def tick(self, now=None, dispatch=None):
        now = time.time() if now is None else now
        for row in self.store.pending(now):
            if row['run_at'] > now:
                if row['action'] in WARNED_ACTIONS:
                    self.warn(row, now)
                continue
            with self.active_lock:
                busy = row['server_id'] in self.active
                claimed = self.store.claim(row, now)
                if claimed and not busy:
                    self.active.add(row['server_id'])
            if claimed:
                claimed['scheduled_for'] = claimed['run_at']
                if busy:
                    self.store.finish(claimed['run_id'], 'failed', 'Another scheduled operation is running on this server')
                elif dispatch:
                    dispatch(claimed)
                else:
                    threading.Thread(target=self.execute, args=(claimed,), daemon=True).start()

    def collect_players(self):
        for server_id in ([] if self.api.manager_mode else [''])+[s.id for s in self.api.server_registry.list() if s.state == 'ready']:
            try:
                with self.selected(server_id):
                    self.api.player_snapshot()
            except Exception:
                # A failed query must never erase history or stop the scheduler.
                pass

    def start(self):
        if sys.platform != 'linux':
            return
        def loop():
            import fcntl
            path = Path(self.api._BASE_DIR)/'.scheduler.lock'
            with path.open('a+') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                self.store.recover()
                def collect_loop():
                    while True:
                        try:
                            self.collect_players()
                        except Exception as exc:
                            self.api.app.logger.exception('Player history poll failed: %s',exc)
                        time.sleep(30)
                threading.Thread(target=collect_loop,name='panel-player-history',daemon=True).start()
                while True:
                    try:
                        self.store.heartbeat(write=True)
                        self.tick()
                    except Exception as exc:
                        self.api.app.logger.exception('Scheduled operation poll failed: %s', exc)
                    time.sleep(5)
        threading.Thread(target=loop, name='panel-scheduler', daemon=True).start()


def install(api):
    tools = OperatorTools(api)
    api.operator_tools = tools
    def server_id():
        return api.selected_instance().id if api.selected_instance() else ''

    @api.app.get('/api/players/history')
    def players_history():
        try:
            search = request.args.get('q','').strip()
            offset = int(request.args.get('offset',0))
            if len(search)>80 or not 0 <= offset <= 1000000:
                raise ValueError('Invalid search or offset')
            rows = tools.store.history(server_id(),search,offset)
            return jsonify(players=rows[:50],next_offset=offset+50 if len(rows)>50 else None)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/players/admins')
    def players_admins():
        config = api.read_config()
        return jsonify(admins=config.get('game',{}).get('admins',[]),revision=revision(config))

    @api.app.post('/api/players/admin')
    def players_admin_save():
        try:
            data = request.get_json()
            identity = data.get('identity')
            if not isinstance(identity,str) or not re.fullmatch(r'(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|\d{17})',identity) or type(data.get('grant')) is not bool:
                raise ValueError('Choose a player with a UUID or 17-digit Steam ID')
            config = api.read_config()
            if data.get('revision') != revision(config):
                return jsonify(ok=False,error='Configuration changed. Refresh players before changing access.'),409
            admins = config.get('game',{}).get('admins',[])
            if not isinstance(admins,list) or any(not isinstance(value,str) for value in admins):
                raise ValueError('Repair the existing game administrator list in Server config first')
            admins = [value for value in admins if value.lower()!=identity.lower()]
            if data['grant']:
                admins.append(identity)
            api.write_config(apply_changes(config,{'game.admins':admins}))
            g.audit_details = {'identity':identity,'grant':data['grant']}
            return jsonify(ok=True,restart_required=bool(api.get_server_pid()))
        except (ValueError,OSError) as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/startup')
    def startup_get():
        instance = api.selected_instance()
        value = instance.max_fps if instance else api.server_registry.existing_max_fps(api._cfg.get('MAX_FPS',''))
        log = api.get_latest_log()
        from runtime_ops import read_console
        try:
            output = read_console(log,None,initial_lines=30)['lines'] if log else []
        except OSError:
            output = ['The recent log rotated or is unavailable. Refresh diagnostics to try again.']
        return jsonify(launch_options=startup_settings.load(api.server_registry,server_id() or '__existing__'),diagnostics=startup_settings.diagnostics(api),resources=api.server_registry.resources(server_id() or '__existing__'),resource_supported=sys.platform=='linux',cpu_count=os.cpu_count(),max_fps=value,service=instance.service_name if instance else 'arma-server.service',
                       running=bool(api.get_server_pid()),binary_exists=(Path(str(api.SERVER_DIR))/api.SERVER_BINARY).is_file(),
                       config_path=str(api.SERVER_CONFIG),server_path=str(api.SERVER_DIR),profile_path=str(api.PROFILE_DIR),
                       logs_path=str(api.LOG_DIR),output=output,software=api.software_manager.status())

    @api.app.post('/api/startup')
    def startup_save():
        try:
            data=request.get_json()
            value = data.get('max_fps')
            from instance_control import normalize_limits
            current=api.server_registry.resources(server_id() or '__existing__')
            resources=normalize_limits(data.get('cpus',current['cpus']),data.get('memory_high_mb',current['memory_high_mb']),data.get('memory_max_mb',current['memory_max_mb']))
            options=startup_settings.validate(data.get('launch_options',startup_settings.load(api.server_registry,server_id() or '__existing__')))
            api.server_registry.validate_max_fps(value)
            if api.selected_instance():
                api.server_registry.set_max_fps(server_id(),value)
            else:
                api.server_registry.set_existing_max_fps(value)
            api.server_registry.set_resources(server_id() or '__existing__',resources)
            startup_settings.save(api.server_registry,server_id() or '__existing__',options)
            g.audit_details={'max_fps':value,**resources,'launch_options':options}
            return jsonify(ok=True,restart_required=bool(api.get_server_pid()))
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/schedules')
    def schedules_list():
        rows,runs = tools.store.list(server_id())
        return jsonify(server_time=datetime.now().strftime('%Y-%m-%dT%H:%M'),default_run=datetime.fromtimestamp(time.time()+900).strftime('%Y-%m-%dT%H:%M'),schedules=rows,runs=runs,supported=sys.platform=='linux',worker_alive=tools.store.heartbeat())

    @api.app.post('/api/schedules')
    def schedules_save():
        if sys.platform!='linux':
            return jsonify(ok=False,error='Scheduling requires the Linux panel service'),409
        try:
            schedule_id=tools.store.create(server_id(),g.user['id'],request.get_json())
            g.audit_details={'schedule_id':schedule_id,'action':request.get_json().get('action')}
            return jsonify(ok=True,id=schedule_id)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/schedules/runs')
    def schedules_runs():
        try:
            rows=tools.store.runs(server_id(),int(request.args.get('before',0)),request.args.get('state',''),request.args.get('search',''))
            return jsonify(ok=True,runs=rows[:50],next_cursor=rows[49]['id'] if len(rows)>50 else None)
        except (ValueError,TypeError) as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/schedules/<int:schedule_id>')
    def schedules_change(schedule_id):
        try:
            data=request.get_json()
            if data.get('run_now') is True:
                if sys.platform!='linux' or not tools.store.heartbeat():
                    return jsonify(ok=False,error='Run now requires an active Linux scheduler'),409
                identity,warned=tools.store.queue_now(server_id(),schedule_id,g.user['id'])
                g.audit_details={'schedule_id':schedule_id,'queued_id':identity}
                return jsonify(ok=True,message='Queued with 5-minute and 1-minute warnings; runs in 6 minutes.' if warned else 'Queued for the next scheduler tick.',id=identity)
            if data.get('edit') is True:
                tools.store.update(server_id(),schedule_id,g.user['id'],data)
            else:
                tools.store.change(server_id(),schedule_id,enabled=data.get('enabled'),remove=data.get('remove') is True)
            g.audit_details={'schedule_id':schedule_id,'removed':data.get('remove') is True}
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400
