"""Unit events, immutable event rosters and reviewed UUID attendance."""
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import abort, g, jsonify, request

from units import text, UUID

OUTCOMES = ('present', 'absent', 'excused', 'unknown')


def install(api, db, access, panel_admin, promotion, endpoints):
    with db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS unit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                series_id TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
                briefing TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
                server_id TEXT NOT NULL, starts REAL NOT NULL, ends REAL NOT NULL,
                timezone TEXT NOT NULL, recurrence TEXT NOT NULL DEFAULT 'none',
                tracked INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'scheduled',
                version INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_events_unit_time ON unit_events(unit_id,starts);
            CREATE INDEX IF NOT EXISTS unit_events_server_time ON unit_events(server_id,starts,ends);
            CREATE TABLE IF NOT EXISTS unit_event_members (
                event_id INTEGER NOT NULL, member_id INTEGER NOT NULL,
                game_name TEXT NOT NULL, identity TEXT NOT NULL, status TEXT NOT NULL,
                expected INTEGER NOT NULL, exemption TEXT NOT NULL DEFAULT '',
                outcome TEXT, reason TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(event_id,member_id));
            CREATE TABLE IF NOT EXISTS unit_event_evidence (
                event_id INTEGER NOT NULL, identity TEXT NOT NULL, name TEXT NOT NULL,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL, samples INTEGER NOT NULL,
                PRIMARY KEY(event_id,identity));
            CREATE TABLE IF NOT EXISTS unit_event_samples (
                event_id INTEGER NOT NULL, observed REAL NOT NULL, available INTEGER NOT NULL,
                PRIMARY KEY(event_id,observed));
            CREATE TABLE IF NOT EXISTS unit_attendance_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                event_id INTEGER NOT NULL, member_id INTEGER, actor TEXT NOT NULL,
                created_at REAL NOT NULL, action TEXT NOT NULL,
                before_value TEXT NOT NULL, after_value TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_attendance_audit_event ON unit_attendance_audit(event_id,id);
        ''')

    names = {'unit_operations', 'unit_events_save', 'unit_event_detail', 'unit_event_change',
             'unit_attendance_save', 'unit_attendance_report', 'unit_attendance_export', 'unit_member_attendance'}
    endpoints.update(names)
    api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS
    MUTATIONS.update({name: 'view' for name in ('unit_events_save', 'unit_event_change', 'unit_attendance_save')})

    def can(conn, unit_id, capability):
        if panel_admin():
            return True
        row = conn.execute('SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?', (unit_id, g.user['id'])).fetchone()
        return bool(row and (row['role'] == 'admin' or capability in json.loads(row['capabilities'])))

    def actor(conn, unit_id):
        row = conn.execute('SELECT game_name FROM unit_roster WHERE unit_id=? AND panel_user_id=?', (unit_id, g.user['id'])).fetchone()
        return row['game_name'] if row else g.user['username']

    def audit(conn, event, action, before, after, reason='', member_id=None):
        conn.execute('INSERT INTO unit_attendance_audit(unit_id,event_id,member_id,actor,created_at,action,before_value,after_value,reason) VALUES(?,?,?,?,?,?,?,?,?)',
                     (event['unit_id'], event['id'], member_id, actor(conn, event['unit_id']), time.time(), action, json.dumps(before), json.dumps(after), reason))

    def event_row(conn, unit_id, event_id):
        row = conn.execute('SELECT * FROM unit_events WHERE id=? AND unit_id=?', (event_id, unit_id)).fetchone()
        if not row:
            abort(404, description='Event not found in this unit')
        return dict(row)

    def check_version(event, data):
        if type(data.get('version')) is not int or data['version'] != event['version']:
            abort(409, description='This event changed. Reopen it before saving.')

    def snapshot(conn, event):
        # Future event rosters follow roster edits. Once the start passes, snapshots never change.
        conn.execute('DELETE FROM unit_event_members WHERE event_id=?', (event['id'],))
        local_day = datetime.fromtimestamp(event['starts'], ZoneInfo(event['timezone'])).date().isoformat()
        for member in conn.execute('SELECT * FROM unit_roster WHERE unit_id=? AND archived=0', (event['unit_id'],)).fetchall():
            if member['joined_on'] and member['joined_on'] > local_day:
                continue
            exempt = 'LOA' if member['status'] == 'loa' else 'Reserve' if member['status'] == 'reserve' else ''
            conn.execute('INSERT INTO unit_event_members(event_id,member_id,game_name,identity,status,expected,exemption) VALUES(?,?,?,?,?,?,?)',
                         (event['id'], member['id'], member['game_name'], member['identity'].lower(), member['status'], int(not exempt), exempt))

    def sync_roster(conn, unit_id):
        for event in conn.execute("SELECT * FROM unit_events WHERE unit_id=? AND starts>? AND state='scheduled'", (unit_id, time.time())).fetchall():
            snapshot(conn, dict(event))
    api.sync_unit_event_roster = sync_roster

    def observe(server_id, sample):
        now = time.time()
        observed = sample.get('checked_at', now)
        if not isinstance(observed, (int, float)) or not math.isfinite(observed) or observed > now + 5 or observed < now - 120:
            return
        available = bool(sample.get('available'))
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            events = conn.execute("SELECT * FROM unit_events WHERE server_id=? AND tracked=1 AND state='scheduled' AND starts<=? AND ends>?", (server_id, observed, observed)).fetchall()
            for event in events:
                inserted = conn.execute('INSERT OR IGNORE INTO unit_event_samples VALUES(?,?,?)', (event['id'], observed, int(available))).rowcount
                if not inserted or not available:
                    continue
                for player in sample.get('players', []):
                    identity = str(player.get('identity', '')).lower()
                    if not UUID.fullmatch(identity):
                        continue
                    name = str(player.get('name', ''))[:256]
                    conn.execute('INSERT INTO unit_event_evidence VALUES(?,?,?,?,?,1) ON CONFLICT(event_id,identity) DO UPDATE SET name=excluded.name,first_seen=min(first_seen,excluded.first_seen),last_seen=max(last_seen,excluded.last_seen),samples=samples+1',
                                 (event['id'], identity, name, observed, observed))
    api.observe_unit_attendance = observe

    def local_start(raw, tz):
        try:
            value = datetime.fromisoformat(raw)
            if value.tzinfo is not None:
                raise ValueError()
            value = value.replace(tzinfo=tz)
            if value.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != value.replace(tzinfo=None):
                raise ValueError()
            return value
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Choose a valid local start time; daylight-saving skipped times cannot be used') from None

    def event_values(conn, unit_id, data):
        name = text(data.get('name'), 'Event name', 120, True)
        category = text(data.get('category', 'Operation'), 'Event type', 60, True)
        briefing = text(data.get('briefing', ''), 'Briefing', 4000)
        location = text(data.get('location', ''), 'Location', 200)
        tz_name = text(data.get('timezone', ''), 'Timezone', 80, True)
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Choose an IANA timezone such as America/New_York') from None
        start = local_start(data.get('starts'), tz)
        duration = data.get('duration')
        if type(duration) is not int or not 5 <= duration <= 1440:
            raise ValueError('Duration must be 5–1440 whole minutes')
        if start.timestamp() < time.time() + 60 or start.timestamp() > time.time() + 366 * 86400:
            raise ValueError('Schedule events at least a minute ahead and within the next year')
        server_id = data.get('server_id')
        if not isinstance(server_id, str) or not conn.execute('SELECT 1 FROM unit_servers WHERE unit_id=? AND server_id=?', (unit_id, server_id)).fetchone():
            raise ValueError('Choose a server linked to this unit')
        if type(data.get('tracked', True)) is not bool:
            raise ValueError('Choose whether to track attendance')
        recurrence = data.get('recurrence', 'none')
        if recurrence not in ('none', 'weekly', 'biweekly', 'monthly'):
            raise ValueError('Choose a supported recurrence')
        count = data.get('count', 1)
        if type(count) is not int or not 1 <= count <= 52:
            raise ValueError('Choose 1–52 occurrences')
        if recurrence == 'none':
            count = 1
        dates = []
        for index in range(count):
            if recurrence == 'monthly':
                month = start.year * 12 + start.month - 1 + index
                year, month = divmod(month, 12)
                value = start.replace(year=year, month=month + 1, day=min(start.day, calendar.monthrange(year, month + 1)[1]))
            else:
                value = start + timedelta(days=index * (14 if recurrence == 'biweekly' else 7))
            value = local_start(value.replace(tzinfo=None).isoformat(), tz)
            if value.timestamp() > time.time() + 366 * 86400:
                raise ValueError('Keep recurring events within the next year')
            dates.append(value.timestamp())
        return dict(name=name, category=category, briefing=briefing, location=location, server_id=server_id,
                    timezone=tz_name, tracked=int(data.get('tracked', True)), recurrence=recurrence), dates, duration * 60

    @api.app.post('/api/units/<int:unit_id>/events')
    def unit_events_save(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn, unit_id, 'events')
                values, starts, duration = event_values(conn, unit_id, data)
                if conn.execute("SELECT count(*) FROM unit_events WHERE unit_id=? AND starts>? AND state='scheduled'", (unit_id, time.time())).fetchone()[0] + len(starts) > 500:
                    raise ValueError('Keep at most 500 upcoming events per unit')
                series = uuid.uuid4().hex
                ids = []
                for start in starts:
                    event_id = conn.execute('INSERT INTO unit_events(unit_id,series_id,name,category,briefing,location,server_id,starts,ends,timezone,tracked,recurrence,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                            (unit_id, series, values['name'], values['category'], values['briefing'], values['location'], values['server_id'], start, start + duration, values['timezone'], values['tracked'], values['recurrence'], time.time())).lastrowid
                    event = event_row(conn, unit_id, event_id)
                    snapshot(conn, event); audit(conn, event, 'created', None, event)
                    ids.append(event_id)
            g.audit_details = dict(unit_id=unit_id, event_ids=ids, change='events created')
            return jsonify(ok=True, ids=ids)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def outcomes(conn, event, member_id=None):
        evidence = {r['identity']: dict(r) for r in conn.execute('SELECT * FROM unit_event_evidence WHERE event_id=?', (event['id'],))}
        result = []
        for row in conn.execute('SELECT * FROM unit_event_members WHERE event_id=? AND (? IS NULL OR member_id=?) ORDER BY game_name COLLATE NOCASE,member_id', (event['id'],member_id,member_id)):
            member = dict(row); seen = evidence.get(member['identity'])
            member['evidence'] = seen
            member['resolved'] = member['outcome'] or ('present' if seen else 'excused' if member['exemption'] == 'LOA' else 'unknown')
            member['manual'] = member['outcome'] is not None and bool(member['reason'])
            result.append(member)
        return result, evidence

    def coverage(conn, event):
        end = min(time.time(), event['ends'])
        samples = [dict(r) for r in conn.execute('SELECT observed,available FROM unit_event_samples WHERE event_id=? ORDER BY observed', (event['id'],))]
        good = [r['observed'] for r in samples if r['available']]
        boundaries = [event['starts'], *good, max(event['starts'], end)]
        largest = max((b - a for a, b in zip(boundaries, boundaries[1:])), default=0)
        return dict(samples=len(samples), successful=len(good), last_sample=samples[-1]['observed'] if samples else None,
                    last_success=good[-1] if good else None, largest_gap_seconds=round(largest),
                    needs_review=bool(end > event['starts'] and (not good or largest > 90 or any(not r['available'] for r in samples))))

    @api.app.get('/api/units/<int:unit_id>/events/<int:event_id>')
    def unit_event_detail(unit_id, event_id):
        with db() as conn:
            access(conn, unit_id); event = event_row(conn, unit_id, event_id)
            members, evidence = outcomes(conn, event)
            linked = {m['identity'] for m in members if m['identity']}
            audit_rows = [dict(r) for r in conn.execute('SELECT * FROM unit_attendance_audit WHERE event_id=? ORDER BY id DESC LIMIT 200', (event_id,))]
            for row in audit_rows:
                row['before_value'] = json.loads(row['before_value']); row['after_value'] = json.loads(row['after_value'])
            return jsonify(event=event, members=members, coverage=coverage(conn, event),
                           unlinked=[e for identity, e in evidence.items() if identity not in linked], audit=audit_rows,
                           can_events=can(conn, unit_id, 'events'), can_attendance=can(conn, unit_id, 'attendance'),
                           future_versions={str(r['id']):r['version'] for r in conn.execute("SELECT id,version FROM unit_events WHERE unit_id=? AND series_id=? AND starts>=? AND (starts>? OR id=?) AND state='scheduled'",(unit_id,event['series_id'],event['starts'],time.time(),event_id))})

    @api.app.post('/api/units/<int:unit_id>/events/<int:event_id>/change')
    def unit_event_change(unit_id, event_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn, unit_id)
                event = event_row(conn, unit_id, event_id); check_version(event, data)
                action = data.get('action'); now = time.time()
                if action in ('finalize', 'reopen'):
                    access(conn, unit_id, 'attendance')
                    reason = text(data.get('reason', ''), 'Review reason', 1000, True)
                    if not event['tracked'] or event['state'] == 'cancelled':
                        raise ValueError('Only attendance-tracked, non-cancelled events can be reviewed')
                    if action == 'finalize' and (event['ends'] > now or event['state'] != 'scheduled'):
                        raise ValueError('Finalize after the event ends')
                    if action == 'reopen' and event['state'] != 'finalized':
                        raise ValueError('Only finalized events can be reopened')
                    state = 'finalized' if action == 'finalize' else 'scheduled'
                    if action == 'finalize':
                        members, _ = outcomes(conn, event)
                        for member in members:
                            conn.execute('UPDATE unit_event_members SET outcome=? WHERE event_id=? AND member_id=?', (member['resolved'], event_id, member['member_id']))
                    conn.execute('UPDATE unit_events SET state=?,version=version+1 WHERE id=?', (state, event_id))
                    audit(conn, event, action, event['state'], state, reason)
                elif action in ('edit', 'cancel'):
                    access(conn, unit_id, 'events')
                    scope = data.get('scope', 'occurrence')
                    if scope not in ('occurrence', 'future'):
                        raise ValueError('Choose this occurrence or future series')
                    if event['state'] != 'scheduled':
                        raise ValueError('Only scheduled or pending events can be cancelled; reopen finalized attendance first')
                    if action == 'edit' and event['starts'] <= now:
                        raise ValueError('Only upcoming scheduled events can be edited')
                    targets = [event] if scope == 'occurrence' else [dict(r) for r in conn.execute("SELECT * FROM unit_events WHERE unit_id=? AND series_id=? AND starts>=? AND (starts>? OR id=?) AND state='scheduled' ORDER BY starts", (unit_id, event['series_id'], event['starts'], now,event_id))]
                    if scope == 'future' and data.get('future_versions') != {str(target['id']):target['version'] for target in targets}:
                        abort(409, description='The event series changed. Reopen it before saving.')
                    if action == 'cancel':
                        reason = text(data.get('reason', ''), 'Cancellation reason', 1000, True)
                        for target in targets:
                            conn.execute("UPDATE unit_events SET state='cancelled',version=version+1 WHERE id=?", (target['id'],))
                            audit(conn, target, 'cancelled', target, dict(target, state='cancelled'), reason)
                    else:
                        slots = targets if scope == 'occurrence' else [dict(r) for r in conn.execute('SELECT * FROM unit_events WHERE unit_id=? AND series_id=? AND starts>=? ORDER BY starts,id', (unit_id,event['series_id'],event['starts']))]
                        payload = dict(data, count=len(slots), recurrence=event['recurrence'] if scope == 'future' else 'none')
                        values, starts, duration = event_values(conn, unit_id, payload)
                        for target, start in zip(slots, starts):
                            if target['state'] != 'scheduled' or target['starts'] <= now:
                                continue
                            conn.execute('UPDATE unit_events SET name=?,category=?,briefing=?,location=?,server_id=?,starts=?,ends=?,timezone=?,tracked=?,version=version+1 WHERE id=?',
                                         (values['name'], values['category'], values['briefing'], values['location'], values['server_id'], start, start + duration, values['timezone'], values['tracked'], target['id']))
                            updated = event_row(conn, unit_id, target['id']); snapshot(conn, updated)
                            audit(conn, target, 'edited', target, updated)
                else:
                    raise ValueError('Choose edit, cancel, finalize or reopen')
            g.audit_details = dict(unit_id=unit_id, event_id=event_id, change=action)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post('/api/units/<int:unit_id>/events/<int:event_id>/attendance')
    def unit_attendance_save(unit_id, event_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn, unit_id, 'attendance')
                event = event_row(conn, unit_id, event_id); check_version(event, data)
                if event['state'] != 'scheduled' or not event['tracked'] or event['starts'] > time.time():
                    raise ValueError('Review attendance during or after an event; reopen finalized events first')
                reason = text(data.get('reason', ''), 'Correction reason', 1000, True)
                changes = data.get('changes')
                if not isinstance(changes, list) or not 1 <= len(changes) <= 2000:
                    raise ValueError('Choose 1–2000 attendance corrections')
                seen = set()
                effective = {m['member_id']:m['resolved'] for m in outcomes(conn,event)[0]}
                for change in changes:
                    if not isinstance(change, dict) or type(change.get('member_id')) is not int or change.get('outcome') not in OUTCOMES or change['member_id'] in seen:
                        raise ValueError('Choose valid, unique member outcomes')
                    seen.add(change['member_id'])
                    member = conn.execute('SELECT * FROM unit_event_members WHERE event_id=? AND member_id=?', (event_id, change['member_id'])).fetchone()
                    if not member:
                        raise ValueError('Member is not on this event roster')
                    conn.execute('UPDATE unit_event_members SET outcome=?,reason=? WHERE event_id=? AND member_id=?', (change['outcome'], reason, event_id, change['member_id']))
                    audit(conn, event, 'attendance correction', dict(member,resolved=effective[change['member_id']]), dict(outcome=change['outcome']), reason, change['member_id'])
                conn.execute('UPDATE unit_events SET version=version+1 WHERE id=?', (event_id,))
            g.audit_details = dict(unit_id=unit_id, event_id=event_id, member_ids=sorted(seen), change='attendance corrected')
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def report_data(conn, unit_id):
        month = request.args.get('month', datetime.now(timezone.utc).strftime('%Y-%m'))
        tz_name = request.args.get('timezone', 'UTC')
        try:
            first = date.fromisoformat(month + '-01'); tz = ZoneInfo(tz_name)
            if not 2000 <= first.year <= 2100:
                raise ValueError()
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            start = datetime.combine(first, datetime.min.time(), tz).timestamp()
            end = datetime.combine(last, datetime.min.time(), tz).timestamp()
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError('Choose a valid month and IANA timezone') from None
        events = [dict(r) for r in conn.execute("SELECT * FROM unit_events WHERE unit_id=? AND starts>=? AND starts<? AND tracked=1 AND state!='cancelled' ORDER BY starts,id", (unit_id, start, end))]
        server_filter = request.args.get('server_id')
        if server_filter is not None:
            events = [event for event in events if event['server_id'] == server_filter]
        members = {r['id']:dict(member_id=r['id'],game_name=r['game_name'],cells={},present=0,absent=0,excused=0,unknown=0,last_attended=None) for r in conn.execute('SELECT id,game_name FROM unit_roster WHERE unit_id=? AND archived=0',(unit_id,))}
        for event in events:
            roster, _ = outcomes(conn, event)
            for member in roster:
                row = members.setdefault(member['member_id'], dict(member_id=member['member_id'], game_name=member['game_name'], cells={}, present=0, absent=0, excused=0, unknown=0, last_attended=None))
                status = member['resolved']; final = event['state'] == 'finalized'
                row['cells'][str(event['id'])] = dict(outcome=status, finalized=final, expected=bool(member['expected']), exemption=member['exemption'])
                if final:
                    row[status] += 1
        last_attended = {r['member_id']:r['last_attended'] for r in conn.execute("SELECT m.member_id,max(e.starts) AS last_attended FROM unit_events e JOIN unit_event_members m ON m.event_id=e.id WHERE e.unit_id=? AND e.state='finalized' AND m.outcome='present' GROUP BY m.member_id",(unit_id,))}
        for row in members.values():
            denominator = sum(1 for cell in row['cells'].values() if cell['finalized'] and cell['expected'] and cell['outcome'] in ('present', 'absent'))
            numerator = sum(1 for cell in row['cells'].values() if cell['finalized'] and cell['expected'] and cell['outcome'] == 'present')
            row['rate'] = round(numerator / denominator * 100, 1) if denominator else None
            row['counted_events'] = denominator
            row['last_attended'] = last_attended.get(row['member_id'])
        return dict(month=month, timezone=tz_name, events=events, members=sorted(members.values(), key=lambda r: r['game_name'].casefold()))

    @api.app.get('/api/units/<int:unit_id>/roster/<int:member_id>/attendance')
    def unit_member_attendance(unit_id, member_id):
        with db() as conn:
            access(conn, unit_id)
            if not conn.execute('SELECT 1 FROM unit_roster WHERE unit_id=? AND id=?',(unit_id,member_id)).fetchone():
                abort(404,description='Member not found in this unit')
            records=[]
            for row in conn.execute("SELECT e.* FROM unit_events e JOIN unit_event_members m ON m.event_id=e.id WHERE e.unit_id=? AND m.member_id=? AND e.state!='cancelled' AND e.tracked=1 AND e.starts<=? ORDER BY e.starts DESC LIMIT 50",(unit_id,member_id,time.time())):
                event=dict(row); roster,_=outcomes(conn,event,member_id)
                member=next(m for m in roster if m['member_id']==member_id)
                records.append(dict(event_id=event['id'],name=event['name'],starts=event['starts'],state=event['state'],outcome=member['resolved'],expected=bool(member['expected']),exemption=member['exemption']))
        return jsonify(records=records)

    @api.app.get('/api/units/<int:unit_id>/attendance')
    def unit_attendance_report(unit_id):
        try:
            with db() as conn:
                access(conn, unit_id); result = report_data(conn, unit_id)
            return jsonify(result)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get('/api/units/<int:unit_id>/attendance.csv')
    def unit_attendance_export(unit_id):
        try:
            with db() as conn:
                access(conn, unit_id); report = report_data(conn, unit_id)
            output = io.StringIO(); writer = csv.writer(output)
            def cell(value):
                value = str(value)
                return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
            writer.writerow(['Member', 'Member ID', 'Event', 'Event ID', 'Starts', 'Timezone', 'State', 'Outcome', 'Expected', 'Exemption', 'Monthly rate', 'Last attended'])
            for member in report['members']:
                for event in report['events']:
                    attendance = member['cells'].get(str(event['id']))
                    if attendance:
                        writer.writerow([cell(member['game_name']), member['member_id'], cell(event['name']), event['id'], datetime.fromtimestamp(event['starts'], ZoneInfo(event['timezone'])).isoformat(), event['timezone'], event['state'], attendance['outcome'], attendance['expected'], attendance['exemption'], member['rate'] if member['rate'] is not None else '', datetime.fromtimestamp(member['last_attended'], timezone.utc).isoformat() if member['last_attended'] else ''])
            return api.app.response_class(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="unit-attendance.csv"'})
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get('/api/units/<int:unit_id>/operations')
    def unit_operations(unit_id):
        with db() as conn:
            unit = access(conn, unit_id); now = time.time()
            try:
                month = request.args.get('month', datetime.now(timezone.utc).strftime('%Y-%m'))
                first = date.fromisoformat(month + '-01')
                if not 2000 <= first.year <= 2100:
                    raise ValueError()
                last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
                tz = ZoneInfo(request.args.get('timezone', 'UTC'))
            except (ValueError, ZoneInfoNotFoundError):
                return jsonify(ok=False, error='Choose a valid month and timezone'), 400
            lower = datetime.combine(first, datetime.min.time(), tz).timestamp()
            upper = datetime.combine(last, datetime.min.time(), tz).timestamp()
            events = [dict(r) for r in conn.execute('SELECT * FROM unit_events WHERE unit_id=? AND starts>=? AND starts<? ORDER BY starts,id', (unit_id, lower, upper))]
            upcoming = [dict(r) for r in conn.execute("SELECT * FROM unit_events WHERE unit_id=? AND ends>? AND state='scheduled' ORDER BY starts LIMIT 8", (unit_id, now))]
            pending = [dict(r) for r in conn.execute("SELECT * FROM unit_events WHERE unit_id=? AND ends<=? AND tracked=1 AND state='scheduled' ORDER BY ends DESC LIMIT 20", (unit_id, now))]
            roster = [dict(r) for r in conn.execute('SELECT * FROM unit_roster WHERE unit_id=? AND archived=0', (unit_id,))]
            assigned = {r[0] for r in conn.execute('SELECT member_id FROM unit_primary_slots WHERE unit_id=?', (unit_id,))}
            slots = conn.execute("SELECT count(*) FROM unit_structure WHERE unit_id=? AND kind='billet'", (unit_id,)).fetchone()[0]
            catalog = json.loads(unit['catalog'])
            eligible = [dict(id=m['id'], game_name=m['game_name'], **promotion(m, catalog)) for m in roster if promotion(m, catalog)['eligible']]
            return jsonify(events=events, upcoming=upcoming, pending=pending,
                           summary=dict(members=len(roster), active=sum(m['status']=='active' for m in roster), reserve=sum(m['status']=='reserve' for m in roster), loa=sum(m['status']=='loa' for m in roster), vacancies=max(0, slots-len(assigned)), unassigned=sum(m['id'] not in assigned for m in roster)),
                           eligible=eligible, can_events=can(conn, unit_id, 'events'), can_attendance=can(conn, unit_id, 'attendance'))
