"""Durable, explicitly claimed scheduled operations; no browser timers."""
import math
import sqlite3
import time
from contextlib import contextmanager

ACTIONS = {'restart', 'update', 'backup'}


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
        name, action, run_at = data.get('name'), data.get('action'), data.get('run_at')
        repeat = data.get('interval_seconds', 0)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError('Enter a schedule name of 1–80 printable characters')
        if not isinstance(action, str) or action not in ACTIONS:
            raise ValueError('Choose restart, update or backup')
        if type(repeat) is not int or repeat < 0 or repeat > 30*86400 or (repeat and (repeat < 3600 or repeat % 3600)):
            raise ValueError('Repeat every 1–720 whole hours, or choose once')
        lead = 360 if action in {'restart', 'update'} else 60
        if type(run_at) not in (int, float) or not math.isfinite(run_at) or not now + lead <= run_at <= now + 366*86400:
            raise ValueError(f'First run must be at least {lead//60} minutes ahead and within a year')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT count(*) FROM schedules WHERE server_id=? AND deleted=0', (server_id,)).fetchone()[0] >= 100:
                raise ValueError('Keep at most 100 schedules per server')
            return conn.execute('INSERT INTO schedules(server_id,owner_id,name,action,run_at,interval_seconds) VALUES(?,?,?,?,?,?)',
                                (server_id, owner_id, name.strip(), action, run_at, repeat)).lastrowid

    def list(self, server_id):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute('SELECT * FROM schedules WHERE server_id=? AND deleted=0 ORDER BY run_at,id', (server_id,))]
            runs = [dict(row) for row in conn.execute('SELECT r.*,s.name,s.action FROM schedule_runs r JOIN schedules s ON s.id=r.schedule_id WHERE r.server_id=? ORDER BY r.id DESC LIMIT 50', (server_id,))]
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
                raise ValueError('This run is too close or has passed. Create a new schedule with a future time.')
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
            next_run = current['run_at'] + ((int((now-current['run_at'])//repeat)+1)*repeat if repeat else 0)
            conn.execute('UPDATE schedules SET run_at=?,enabled=?,warning5=0,warning1=0,warning_error=? WHERE id=?',
                         (next_run, int(bool(repeat)), '', row['id']))
            run_id = conn.execute('INSERT INTO schedule_runs(schedule_id,server_id,scheduled_for,started,state) VALUES(?,?,?,?,?)',
                                  (row['id'],row['server_id'],row['run_at'],now,'running')).lastrowid
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
