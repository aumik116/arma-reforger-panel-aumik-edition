"""Durable per-server events and bounded Discord delivery, independent of browsers."""
import json
import hashlib
import re
import sqlite3
import threading
import time
import sys
from contextlib import contextmanager
from urllib.request import Request, build_opener
from urllib.error import HTTPError
from flask import g, jsonify, request
from mod_metadata import NoRedirect

FAILURES = {'unexpected_stop', 'start_failed', 'stop_failed', 'update_failed', 'unexpected_restart', 'provision_failed'}
LABELS = {'provision_failed':'Server installation or initial start failed', 'started':'Server started', 'stopped':'Server stopped', 'unexpected_stop':'Server stopped unexpectedly',
          'unexpected_restart':'Server process restarted outside the panel', 'start_failed':'Server failed to start', 'stop_failed':'Server failed to stop',
          'update_success':'Game update completed', 'update_failed':'Game update failed', 'test':'Test notification'}


def validate_webhook(value):
    if not isinstance(value, str) or not re.fullmatch(r'https://discord\.com/api(?:/v\d+)?/webhooks/[0-9]{15,22}/[A-Za-z0-9_-]{30,200}', value):
        raise ValueError('Use a Discord webhook URL beginning https://discord.com/api/webhooks/')
    return value


class Notifications:
    def __init__(self, api):
        self.api = api
        self.database = api.server_registry.database
        with self.db() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS notification_settings (
                    server_id TEXT PRIMARY KEY, webhook TEXT NOT NULL DEFAULT '', routine INTEGER NOT NULL DEFAULT 1,
                    role TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY, server_id TEXT NOT NULL, created REAL NOT NULL, kind TEXT NOT NULL,
                    message TEXT NOT NULL, dedupe TEXT NOT NULL UNIQUE, delivery TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0, target TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notification_observers (
                    server_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, job TEXT NOT NULL DEFAULT '');
            ''')

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.database, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def settings(self, server):
        with self.db() as conn:
            row = conn.execute('SELECT * FROM notification_settings WHERE server_id=?',(server,)).fetchone()
        return dict(row) if row else dict(server_id=server, webhook='', routine=1, role='')

    def save(self, server, data):
        current = self.settings(server)
        if type(data.get('routine')) is not bool or type(data.get('clear_webhook',False)) is not bool:
            raise ValueError('Choose whether routine notifications are enabled')
        role = data.get('role','')
        if not isinstance(role,str) or role and not re.fullmatch(r'[0-9]{15,22}',role):
            raise ValueError('Role mention must be a Discord role ID, or blank')
        url = data.get('webhook','')
        if not isinstance(url,str):
            raise ValueError('Invalid webhook URL')
        url = '' if data.get('clear_webhook') else validate_webhook(url) if url else current['webhook']
        with self.db() as conn:
            conn.execute('INSERT OR REPLACE INTO notification_settings VALUES(?,?,?,?)',(server,url,data['routine'],role))
            # Pending messages never move to a newly selected channel or inherit a new mention.
            conn.execute("UPDATE notifications SET delivery='cancelled' WHERE server_id=? AND delivery='pending'",(server,))

    @staticmethod
    def target(settings):
        return hashlib.sha256((settings["webhook"]+":"+settings["role"]).encode()).hexdigest()

    def emit(self, server, kind, source):
        settings = self.settings(server)
        delivery = 'pending' if settings['webhook'] and (kind in FAILURES or settings['routine'] or kind=='test') else 'local'
        message = LABELS[kind]
        with self.db() as conn:
            if kind in FAILURES and conn.execute('SELECT 1 FROM notifications WHERE server_id=? AND kind=? AND created>?',(server,kind,time.time()-300)).fetchone():
                return
            conn.execute('INSERT OR IGNORE INTO notifications(server_id,created,kind,message,dedupe,delivery,target) VALUES(?,?,?,?,?,?,?)',
                         (server,time.time(),kind,message,f'{server}:{kind}:{source}',delivery,self.target(settings)))
            conn.execute('DELETE FROM notifications WHERE server_id=? AND id NOT IN (SELECT id FROM notifications WHERE server_id=? ORDER BY id DESC LIMIT 1000)',(server,server))

    def baseline(self, server, pid, job=None):
        with self.db() as conn:
            old = conn.execute('SELECT job FROM notification_observers WHERE server_id=?',(server,)).fetchone()
            conn.execute('INSERT OR REPLACE INTO notification_observers VALUES(?,?,?)',(server,pid or 0,job if job is not None else old['job'] if old else ''))

    def observe(self, server, pid, job):
        key = str(job.get('started',''))+':'+str(job.get('state',''))
        with self.db() as conn:
            old = conn.execute('SELECT * FROM notification_observers WHERE server_id=?',(server,)).fetchone()
        if old:
            if old['pid'] and not pid:
                self.emit(server,'unexpected_stop',str(old['pid'])+':'+str(time.time()))
            elif pid and pid != old['pid']:
                self.emit(server,'unexpected_restart' if old['pid'] else 'started',str(pid)+':'+str(time.time()))
            if old['job'] != key and job.get('started') and job.get('action')=='update' and job.get('state') in {'success','failed','interrupted'}:
                self.emit(server,'update_success' if job['state']=='success' else 'update_failed',str(job['started']))
        self.baseline(server,pid,key)

    def deliver(self):
        with self.db() as conn:
            rows = conn.execute("SELECT * FROM notifications WHERE delivery='pending' AND retry_at<=? ORDER BY id LIMIT 4",(time.time(),)).fetchall()
        for row in rows:
            settings = self.settings(row['server_id'])
            if not settings['webhook'] or self.target(settings)!=row['target']:
                status,delay='cancelled',0
            else:
                try:
                    validate_webhook(settings['webhook'])
                    name = self.api.server_registry.get(row['server_id']).name if row['server_id'] else 'Default server'
                    role = settings['role']
                    content=(f'<@&{role}> ' if role else '')+f'{name}: {row["message"]}. See the panel for details.'
                    payload={'content':content[:1900],'allowed_mentions':{'parse':[], 'roles':[role] if role else []}}
                    req=Request(settings['webhook']+'?wait=true',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','User-Agent':'ReforgerServerPanel/1.0'},method='POST')
                    with build_opener(NoRedirect).open(req,timeout=5) as response:
                        if response.status not in (200,204):
                            raise ValueError('Discord rejected notification')
                    status,delay='sent',0
                except HTTPError as exc:
                    status='failed' if exc.code in (400,401,403,404) or row['attempts']>=2 else 'pending'
                    delay=60*(row['attempts']+1)
                    if exc.code==429:
                        try: delay=max(delay,min(3600,float(exc.headers.get('Retry-After','60'))))
                        except ValueError: pass
                except Exception:
                    status,delay=('failed' if row['attempts']>=2 else 'pending'),60*(row['attempts']+1)
            with self.db() as conn:
                conn.execute('UPDATE notifications SET delivery=?, attempts=attempts+1,retry_at=? WHERE id=? AND delivery=\'pending\'',(status,time.time()+delay,row['id']))

    def tick(self):
        servers=[]
        for server in self.api.server_registry.list():
            if server.state=='ready':
                servers.append(server.id)
            elif server.state=='provisioning':
                self.baseline(server.id,0,'provisioning')
            elif server.state=='failed':
                try: stamp=str((server.directory/'.provision.json').stat().st_mtime_ns)
                except OSError: stamp='unknown'
                key='provision-failed:'+stamp
                with self.db() as conn:
                    previous=conn.execute('SELECT job FROM notification_observers WHERE server_id=?',(server.id,)).fetchone()
                if previous and previous['job']!=key:
                    self.emit(server.id,'provision_failed',key)
                self.baseline(server.id,0,key)
        if not self.api.manager_mode:
            servers.insert(0,'')
        for server in servers:
            try:
                with self.api.operator_tools.selected(server):
                    lock=self.api.operation_lock._get_current_object()
                    if not lock.acquire(blocking=False):
                        continue
                    try:
                        with self.api.operator_tools.active_lock:
                            if server in self.api.operator_tools.active:
                                continue
                        self.observe(server,self.api.get_server_pid(),self.api.software_manager.status())
                    finally:
                        lock.release()
            except Exception:
                continue
        self.deliver()

    def start(self):
        if sys.platform!='linux':
            return
        def loop():
            import fcntl
            with open(str(self.database)+'.notifications.lock','a+') as lock:
                try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError: return
                while True:
                    try: self.tick()
                    except Exception: pass
                    time.sleep(10)
        threading.Thread(target=loop,daemon=True,name='notifications').start()


def install(api):
    service=api.notifications=Notifications(api)
    def server_id():
        instance=api.selected_instance()
        return instance.id if instance else ''

    for name, success, failure in [('start_server','started','start_failed'),('stop_server','stopped','stop_failed')]:
        original=getattr(api,name)
        def wrapped(original=original,success=success,failure=failure):
            server=server_id()
            try:
                result=original()
            except Exception:
                try:
                    service.baseline(server,api.get_server_pid())
                    service.emit(server,failure,str(time.time()))
                except Exception: pass
                raise
            try:
                service.baseline(server,api.get_server_pid())
                service.emit(server,success,str(time.time()))
            except Exception:
                pass
            return result
        setattr(api,name,wrapped)

    original_clear=api.clear_server_access
    def clear_notifications(server):
        original_clear(server)
        with service.db() as conn:
            for table in ('notification_settings','notification_observers','notifications'):
                conn.execute(f'DELETE FROM {table} WHERE server_id=?',(server,))
    api.clear_server_access=clear_notifications

    @api.app.after_request
    def notification_operation_result(response):
        if request.endpoint == 'software_update' and request.method == 'POST' and getattr(g,'audit_actor',None):
            result=response.get_json(silent=True) or {}
            if response.status_code>=400 or not result.get('ok'):
                try: service.emit(server_id(),'update_failed',str(time.time()))
                except Exception: pass
        return response

    @api.app.get('/api/notifications')
    def notifications_list():
        with service.db() as conn:
            rows=conn.execute('SELECT id,created,kind,message,delivery,attempts FROM notifications WHERE server_id=? ORDER BY id DESC LIMIT 100',(server_id(),)).fetchall()
        return jsonify(ok=True,events=[dict(row) for row in rows],supported=sys.platform=='linux')

    @api.app.get('/api/notifications/settings')
    def notifications_settings():
        settings=service.settings(server_id())
        return jsonify(ok=True,configured=bool(settings['webhook']),routine=bool(settings['routine']),role=settings['role'],supported=sys.platform=='linux')

    @api.app.post('/api/notifications/settings')
    def notifications_save():
        try:
            service.save(server_id(),request.get_json(silent=True) or {})
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/notifications/test')
    def notifications_test():
        if sys.platform!='linux':
            return jsonify(ok=False,error='Discord delivery requires the Linux panel service'),409
        if not service.settings(server_id())['webhook']:
            return jsonify(ok=False,error='Save a webhook first'),400
        service.emit(server_id(),'test',str(time.time()))
        return jsonify(ok=True)
