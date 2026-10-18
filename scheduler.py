"""Durable, explicitly claimed scheduled operations; no browser timers."""
import math
import sqlite3
import time
from datetime import datetime, timedelta, time as daytime

from contextlib import contextmanager

ACTIONS = {'restart', 'update', 'backup'}


def calendar_next(row, now):
    today=datetime.fromtimestamp(now).date()
    hour,minute=map(int,row['local_time'].split(':'))
    for offset in range(15):
        date=today+timedelta(days=offset)
        if row['recurrence']=='weekly' and date.weekday()!=row['weekday']:
            continue
        candidate=datetime.combine(date,daytime(hour,minute))
        stamp=candidate.timestamp()
        # Skip nonexistent DST times; ambiguous times run once, using the first occurrence.
        if datetime.fromtimestamp(stamp).replace(tzinfo=None)!=candidate.replace(tzinfo=None):
            continue
        if stamp>now:
            return stamp
    raise ValueError('No valid calendar occurrence within two weeks')


def schedule_values(data,now):
    name,action,run_at=data.get('name'),data.get('action'),data.get('run_at')
    if 'local_run_at' in data:
        try:
            local=datetime.strptime(data['local_run_at'],'%Y-%m-%dT%H:%M')
            run_at=local.timestamp()
            if datetime.fromtimestamp(run_at)!=local: raise ValueError()
        except (ValueError,TypeError,OverflowError):
            raise ValueError('Choose a valid first run on the server clock') from None
    repeat=data.get('interval_seconds',0)
    recurrence=data.get('recurrence','interval')

    if not isinstance(name,str) or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):
        raise ValueError('Enter a schedule name of 1–80 printable characters')
    if not isinstance(action,str) or action not in ACTIONS:
        raise ValueError('Choose restart, update or backup')
    if type(repeat) is not int or repeat<0 or repeat>30*86400 or repeat and (repeat<3600 or repeat%3600):
        raise ValueError('Repeat every 1–720 whole hours, or choose once')
    if recurrence not in ('interval','daily','weekly'):
        raise ValueError('Choose once, interval, daily or weekly')
    lead=360 if action in {'restart','update'} else 60
    if type(run_at) not in (int,float) or not math.isfinite(run_at) or not now+lead<=run_at<=now+366*86400:
        raise ValueError(f'First run must be at least {lead//60} minutes ahead and within a year')
    local=datetime.fromtimestamp(run_at)
    if recurrence!='interval': repeat=0
    return dict(name=name.strip(),action=action,run_at=run_at,interval_seconds=repeat,recurrence=recurrence,
                local_time=local.strftime('%H:%M'),weekday=local.weekday())


class ScheduleStore:
    def __init__(self, database):
        self.database = str(database)
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY, server_id TEXT NOT NULL, owner_id INTEGER NOT NULL,
                    name TEXT NOT NULL, action TEXT NOT NULL, run_at REAL NOT NULL,
                    interval_seconds INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                    deleted INTEGER NOT NULL DEFAULT 0, warning5 INTEGER NOT NULL DEFAULT 0,
                    warning1 INTEGER NOT NULL DEFAULT 0, warning_error TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS schedule_runs (
                    id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL, server_id TEXT NOT NULL,
                    scheduled_for REAL NOT NULL, started REAL NOT NULL, finished REAL,
                    state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS player_history (
                    server_id TEXT NOT NULL, identity TEXT NOT NULL, name TEXT NOT NULL,
                    first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                    PRIMARY KEY(server_id,identity));
                CREATE TABLE IF NOT EXISTS scheduler_health (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), heartbeat REAL NOT NULL);
            ''')
            columns={row[1] for row in conn.execute('PRAGMA table_info(schedules)')}
            for name,definition in [('recurrence',"TEXT NOT NULL DEFAULT 'interval'"),('local_time',"TEXT NOT NULL DEFAULT '00:00'"),('weekday','INTEGER NOT NULL DEFAULT 0')]:
                if name not in columns: conn.execute(f'ALTER TABLE schedules ADD COLUMN {name} {definition}')
            run_columns={row[1] for row in conn.execute('PRAGMA table_info(schedule_runs)')}
            for name in ('schedule_name','schedule_action'):
                if name not in run_columns: conn.execute(f"ALTER TABLE schedule_runs ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            conn.execute("UPDATE schedule_runs SET schedule_name=COALESCE((SELECT name FROM schedules WHERE schedules.id=schedule_id),'') WHERE schedule_name=''")
            conn.execute("UPDATE schedule_runs SET schedule_action=COALESCE((SELECT action FROM schedules WHERE schedules.id=schedule_id),'') WHERE schedule_action=''")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, server_id, owner_id, data, now=None):
        now = time.time() if now is None else now
        values=schedule_values(data,now)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT count(*) FROM schedules WHERE server_id=? AND deleted=0', (server_id,)).fetchone()[0] >= 100:
                raise ValueError('Keep at most 100 schedules per server')
            return conn.execute('INSERT INTO schedules(server_id,owner_id,name,action,run_at,interval_seconds,recurrence,local_time,weekday) VALUES(?,?,?,?,?,?,?,?,?)',
                                (server_id,owner_id,*values.values())).lastrowid

    def update(self,server_id,schedule_id,owner_id,data,now=None):
        values=schedule_values(data,time.time() if now is None else now)
        with self.connect() as conn:
            result=conn.execute('UPDATE schedules SET owner_id=?,name=?,action=?,run_at=?,interval_seconds=?,recurrence=?,local_time=?,weekday=?,enabled=1,warning5=0,warning1=0,warning_error=? WHERE id=? AND server_id=? AND deleted=0',
                (owner_id,*values.values(),'',schedule_id,server_id))
            if not result.rowcount: raise ValueError('Schedule not found on this server')

    def runs(self,server_id,before=0,state='',search=''):
        if type(before) is not int or before<0 or state not in ('','success','failed','interrupted','running') or not isinstance(search,str) or len(search)>120:
            raise ValueError('Invalid run-history filters')
        with self.connect() as conn:
            rows=[dict(row) for row in conn.execute("SELECT r.*,COALESCE(NULLIF(r.schedule_name,''),s.name) AS name,COALESCE(NULLIF(r.schedule_action,''),s.action) AS action FROM schedule_runs r JOIN schedules s ON s.id=r.schedule_id WHERE r.server_id=? AND (?=0 OR r.id<?) AND (?='' OR r.state=?) AND COALESCE(NULLIF(r.schedule_name,''),s.name) LIKE ? ORDER BY r.id DESC LIMIT 51",
                (server_id,before,before,state,state,'%'+search+'%'))]
        for row in rows:
            for field in ('scheduled_for','started','finished'):
                row[field+'_local']=datetime.fromtimestamp(row[field]).strftime('%Y-%m-%d %H:%M:%S') if row[field] else '—'
        return rows

    def list(self, server_id):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute('SELECT * FROM schedules WHERE server_id=? AND deleted=0 ORDER BY run_at,id', (server_id,))]
            for row in rows: row['local_run_at']=datetime.fromtimestamp(row['run_at']).strftime('%Y-%m-%dT%H:%M')
            runs = [dict(row) for row in conn.execute("SELECT r.*,COALESCE(NULLIF(r.schedule_name,''),s.name) AS name,COALESCE(NULLIF(r.schedule_action,''),s.action) AS action FROM schedule_runs r JOIN schedules s ON s.id=r.schedule_id WHERE r.server_id=? ORDER BY r.id DESC LIMIT 50", (server_id,))]
        return rows, runs

    def change(self, server_id, schedule_id, enabled=None, remove=False, now=None):
        now = time.time() if now is None else now
        if not remove and type(enabled) is not bool:
            raise ValueError('Enabled must be true or false')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM schedules WHERE id=? AND server_id=? AND deleted=0', (schedule_id, server_id)).fetchone()
            if row is None:
                raise ValueError('Schedule not found on this server')
            # Pausing/removing affects future runs, never interrupts a running update.
            if enabled and row['run_at'] < now + (360 if row['action'] != 'backup' else 60):
                threshold=now+(360 if row['action']!='backup' else 60)
                if row['recurrence']!='interval': next_run=calendar_next(row,threshold)
                elif row['interval_seconds']:
                    repeat=row['interval_seconds'];next_run=row['run_at']+(int((threshold-row['run_at'])//repeat)+1)*repeat
                else: raise ValueError('This run is too close or has passed. Edit it with a future time.')
                conn.execute('UPDATE schedules SET run_at=? WHERE id=?',(next_run,schedule_id))
            conn.execute('UPDATE schedules SET enabled=?,deleted=?,warning5=0,warning1=0,warning_error=? WHERE id=?',
                         (int(bool(enabled) and not remove), int(remove), '', schedule_id))

    def pending(self, now):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM schedules WHERE enabled=1 AND deleted=0 AND run_at<=? ORDER BY run_at,id', (now+300,))]

    def warning(self, row, minutes, pid, error=''):
        field = 'warning5' if minutes == 5 else 'warning1'
        with self.connect() as conn:
            conn.execute(f'UPDATE schedules SET {field}=?,warning_error=? WHERE id=? AND run_at=? AND enabled=1 AND deleted=0',
                         (pid, error[:500], row['id'], row['run_at']))

    def claim(self, row, now):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute('SELECT * FROM schedules WHERE id=? AND enabled=1 AND deleted=0 AND run_at=?', (row['id'],row['run_at'])).fetchone()
            if current is None or current['run_at'] > now:
                return None
            repeat = current['interval_seconds']
            calendar=current['recurrence']!='interval'
            next_run = calendar_next(current,now) if calendar else current['run_at'] + ((int((now-current['run_at'])//repeat)+1)*repeat if repeat else 0)
            conn.execute('UPDATE schedules SET run_at=?,enabled=?,warning5=0,warning1=0,warning_error=? WHERE id=?',
                         (next_run, int(bool(repeat) or calendar), '', row['id']))
            run_id = conn.execute('INSERT INTO schedule_runs(schedule_id,server_id,scheduled_for,started,state,schedule_name,schedule_action) VALUES(?,?,?,?,?,?,?)',
                                  (row['id'],row['server_id'],row['run_at'],now,'running',current['name'],current['action'])).lastrowid
            return dict(current, run_id=run_id)

    def finish(self, run_id, state, message):
        with self.connect() as conn:
            conn.execute('UPDATE schedule_runs SET state=?,message=?,finished=? WHERE id=?', (state,message[:1500],time.time(),run_id))

    def recover(self):
        with self.connect() as conn:
            conn.execute("UPDATE schedule_runs SET state='interrupted',message='Panel stopped during this run. Check the server before retrying.',finished=? WHERE state='running'", (time.time(),))

    def heartbeat(self, write=False):
        with self.connect() as conn:
            if write:
                conn.execute('INSERT INTO scheduler_health VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET heartbeat=excluded.heartbeat',(time.time(),))
            row=conn.execute('SELECT heartbeat FROM scheduler_health WHERE singleton=1').fetchone()
        return bool(row and time.time()-row[0]<30)

    def observe(self, server_id, snapshot):
        if not snapshot.get('available'):
            return
        observed = snapshot.get('checked_at', time.time())
        with self.connect() as conn:
            for player in snapshot.get('players', []):
                identity, name = str(player.get('identity', '')), str(player.get('name', ''))
                if identity and len(identity) <= 128 and name and len(name) <= 256:
                    conn.execute('INSERT INTO player_history VALUES(?,?,?,?,?) ON CONFLICT(server_id,identity) DO UPDATE SET name=excluded.name,last_seen=max(last_seen,excluded.last_seen)',
                                 (server_id,identity,name,observed,observed))

    def history(self, server_id, search, offset):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM player_history WHERE server_id=? AND (name LIKE ? OR identity LIKE ?) ORDER BY last_seen DESC,identity LIMIT 51 OFFSET ?',
                                                      (server_id,'%'+search+'%','%'+search+'%',offset))]
