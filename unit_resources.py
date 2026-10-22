"""Unit reference libraries, awards, campaign participation and measured analytics."""
from datetime import date, datetime, timedelta, timezone
import json
import sqlite3
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import abort, g, jsonify, request
from units import text


def install(api, db, access, revision, panel_admin, endpoints):
    with db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS unit_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL, category TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL DEFAULT '',
                slots TEXT NOT NULL DEFAULT '[]', archived INTEGER NOT NULL DEFAULT 0,
                updated_by TEXT NOT NULL, updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_references_unit ON unit_references(unit_id,kind,archived,id);
            CREATE TABLE IF NOT EXISTS unit_award_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS unit_member_awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, award_id INTEGER NOT NULL,
                award_name TEXT NOT NULL, image_url TEXT NOT NULL DEFAULT '',
                awarded_on TEXT NOT NULL, issuer TEXT NOT NULL, citation TEXT NOT NULL,
                campaign_id INTEGER, state TEXT NOT NULL DEFAULT 'active',
                revoked_by TEXT NOT NULL DEFAULT '', revoked_on REAL,
                revoke_reason TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_member_awards_member ON unit_member_awards(unit_id,member_id,id);
            CREATE UNIQUE INDEX IF NOT EXISTS unit_campaign_award_once ON unit_member_awards(unit_id,member_id,campaign_id) WHERE campaign_id IS NOT NULL AND state='active';
            CREATE TABLE IF NOT EXISTS unit_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL, starts_on TEXT NOT NULL DEFAULT '', ends_on TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT 'UTC', event_ids TEXT NOT NULL DEFAULT '[]',
                threshold INTEGER NOT NULL DEFAULT 50, award_id INTEGER,
                state TEXT NOT NULL DEFAULT 'active');
            CREATE TABLE IF NOT EXISTS unit_resource_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                object_kind TEXT NOT NULL, object_id INTEGER NOT NULL, member_id INTEGER,
                actor TEXT NOT NULL, created_at REAL NOT NULL, action TEXT NOT NULL,
                before_value TEXT NOT NULL, after_value TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_resource_audit_object ON unit_resource_audit(unit_id,object_kind,object_id,id);
            CREATE TABLE IF NOT EXISTS unit_strength_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                observed REAL NOT NULL, active INTEGER NOT NULL, reserve INTEGER NOT NULL,
                loa INTEGER NOT NULL, total INTEGER NOT NULL, movement TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_strength_time ON unit_strength_history(unit_id,observed,id);
            CREATE TABLE IF NOT EXISTS unit_membership_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, starts REAL NOT NULL, ends REAL, source TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_membership_span_unit ON unit_membership_spans(unit_id,starts,ends);
        ''')

    def actor(conn, unit_id):
        row = conn.execute('SELECT game_name FROM unit_roster WHERE unit_id=? AND panel_user_id=?', (unit_id, g.user['id'])).fetchone()
        return row['game_name'] if row else g.user['username']

    def permissions(conn, unit_id):
        if panel_admin():
            return dict(references=True, awards=True, campaigns=True)
        row = conn.execute('SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?', (unit_id, g.user['id'])).fetchone()
        caps = json.loads(row['capabilities']) if row else []
        return {key: bool(row and (row['role'] == 'admin' or key in caps)) for key in ('references', 'awards', 'campaigns')}

    def audit(conn, unit_id, kind, object_id, action, before, after, reason='', member_id=None):
        conn.execute('INSERT INTO unit_resource_audit(unit_id,object_kind,object_id,member_id,actor,created_at,action,before_value,after_value,reason) VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (unit_id, kind, object_id, member_id, actor(conn, unit_id), time.time(), action, json.dumps(before), json.dumps(after), reason))

    def get_row(conn, table, unit_id, object_id):
        if type(object_id) is not int or not 1<=object_id<=9223372036854775807:
            raise ValueError('Choose a valid record')
        row = conn.execute(f'SELECT * FROM {table} WHERE unit_id=? AND id=?', (unit_id, object_id)).fetchone()
        if not row:
            abort(404, description='Record not found in this unit')
        return dict(row)

    def url(value, label):
        value = text(value, label, 2000)
        if value:
            try:
                parsed = urlsplit(value)
                if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
                    raise ValueError()
            except ValueError:
                raise ValueError(f'{label}: use an HTTP or HTTPS address without embedded credentials') from None
        return value

    def day(value, label, past=False):
        try:
            parsed = date.fromisoformat(value)
            if not 2000 <= parsed.year <= 2100 or past and parsed > date.today():
                raise ValueError()
            return parsed.isoformat()
        except (ValueError, TypeError):
            raise ValueError(f'{label}: choose a valid date' + (' on or before today' if past else '')) from None

    def zone(value):
        try:
            return ZoneInfo(text(value, 'Timezone', 80, True))
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Choose an IANA timezone such as America/New_York') from None

    def number(value, label, low, high):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{label}: choose a whole number from {low} to {high}')
        return value

    def archive(data):
        if type(data.get('archived', False)) is not bool:
            raise ValueError('Archived must be true or false')
        return int(data.get('archived', False))

    def strength(conn, unit_id, before=None, after=None, baseline=False):
        counts = {r['status']: r['n'] for r in conn.execute('SELECT status,count(*) AS n FROM unit_roster WHERE unit_id=? AND archived=0 GROUP BY status', (unit_id,))}
        values = tuple(counts.get(key, 0) for key in ('active', 'reserve', 'loa'))
        previous = conn.execute('SELECT * FROM unit_strength_history WHERE unit_id=? ORDER BY id DESC LIMIT 1', (unit_id,)).fetchone()
        movement = 'baseline' if baseline else 'status'
        was = before is not None and not before['archived']; now_member = after is not None and not after['archived']
        if not was and now_member:
            movement = 'added' if before is None else 'restored'
        elif was and not now_member:
            movement = 'removed' if after is None else 'archived'
        now = time.time()
        if was != now_member:
            member_id = (after or before)['id']
            if now_member:
                conn.execute('INSERT INTO unit_membership_spans(unit_id,member_id,starts,source) VALUES(?,?,?,?)', (unit_id, member_id, now, movement))
            else:
                conn.execute('UPDATE unit_membership_spans SET ends=? WHERE unit_id=? AND member_id=? AND ends IS NULL', (now, unit_id, member_id))
        if baseline or not previous or tuple(previous[k] for k in ('active', 'reserve', 'loa')) != values:
            conn.execute('INSERT INTO unit_strength_history(unit_id,observed,active,reserve,loa,total,movement) VALUES(?,?,?,?,?,?,?)', (unit_id, now, *values, sum(values), movement))
    api.record_unit_strength = strength
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for unit in conn.execute('SELECT id FROM units').fetchall():
            if not conn.execute('SELECT 1 FROM unit_strength_history WHERE unit_id=?', (unit['id'],)).fetchone():
                strength(conn, unit['id'], baseline=True)
                baseline_time=conn.execute('SELECT observed FROM unit_strength_history WHERE unit_id=? ORDER BY id LIMIT 1',(unit['id'],)).fetchone()[0]
                conn.executemany("INSERT INTO unit_membership_spans(unit_id,member_id,starts,source) VALUES(?,?,?,'baseline')", [(unit['id'], m['id'], baseline_time) for m in conn.execute('SELECT id FROM unit_roster WHERE unit_id=? AND archived=0', (unit['id'],)).fetchall()])

    names = {'unit_library', 'unit_reference', 'unit_reference_save', 'unit_awards', 'unit_award_save', 'unit_award_grant', 'unit_award_revoke', 'unit_campaigns', 'unit_campaign', 'unit_campaign_save', 'unit_analytics', 'unit_member_awards'}
    endpoints.update(names); api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS
    MUTATIONS.update({name: 'view' for name in ('unit_reference_save', 'unit_award_save', 'unit_award_grant', 'unit_award_revoke', 'unit_campaign_save')})

    @api.app.get('/api/units/<int:unit_id>/library')
    def unit_library(unit_id):
        try:
            kind = request.args.get('kind', 'sop'); search = text(request.args.get('q', ''), 'Search', 120)
            category = text(request.args.get('category', ''), 'Category', 80)
            if kind not in ('sop', 'loadout'):
                raise ValueError('Choose SOPs or loadouts')
            offset = number(int(request.args.get('offset', '0')), 'Offset', 0, 1000000)
            with db() as conn:
                unit = access(conn, unit_id)
                rows = [dict(r) for r in conn.execute("SELECT id,kind,title,category,role,substr(body,1,200) AS excerpt,url,image_url,archived,updated_by,updated_at FROM unit_references WHERE unit_id=? AND kind=? AND archived=? AND (?='' OR category=?) AND (title LIKE ? OR body LIKE ? OR role LIKE ? OR category LIKE ?) ORDER BY title COLLATE NOCASE,id LIMIT 51 OFFSET ?", (unit_id, kind, int(request.args.get('archived') == '1'), category, category, *['%'+search+'%']*4, offset))]
                categories = [r[0] for r in conn.execute('SELECT DISTINCT category FROM unit_references WHERE unit_id=? AND kind=? ORDER BY category COLLATE NOCASE', (unit_id, kind))]
                return jsonify(items=rows[:50], next_offset=offset+50 if len(rows)>50 else None, categories=categories, revision=unit['revision'], permissions=permissions(conn, unit_id))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.get('/api/units/<int:unit_id>/library/<int:reference_id>')
    def unit_reference(unit_id, reference_id):
        with db() as conn:
            unit = access(conn, unit_id); row = get_row(conn, 'unit_references', unit_id, reference_id)
            row['slots'] = json.loads(row['slots'])
            history = [dict(r) for r in conn.execute("SELECT id,actor,created_at,action,reason FROM unit_resource_audit WHERE unit_id=? AND object_kind='reference' AND object_id=? ORDER BY id DESC LIMIT 50", (unit_id, reference_id))]
            return jsonify(item=row, history=history, revision=unit['revision'], permissions=permissions(conn, unit_id))

    @api.app.post('/api/units/<int:unit_id>/library')
    def unit_reference_save(unit_id):
        data = request.get_json()
        try:
            kind = data.get('kind')
            if kind not in ('sop', 'loadout'):
                raise ValueError('Choose SOP or loadout')
            title = text(data.get('title'), 'Title', 120, True); category = text(data.get('category', 'General'), 'Category', 80, True)
            role = text(data.get('role', ''), 'Role', 120); body = text(data.get('body', ''), 'Content', 20000)
            link = url(data.get('url', ''), 'Reference link'); image = url(data.get('image_url', ''), 'Image URL')
            slots = data.get('slots', [])
            if not isinstance(slots, list) or len(slots)>40:
                raise ValueError('Keep at most 40 loadout slots')
            clean = []
            for slot in slots:
                if not isinstance(slot, dict):
                    raise ValueError('Choose valid loadout slots')
                clean.append({key: text(slot.get(key, ''), key, 120 if key=='slot' else 2000, key=='slot') for key in ('slot','standard','alternatives','notes')})
            if kind == 'sop':
                clean = []
                if not body and not link:
                    raise ValueError('Enter SOP content or a reference link')
            elif not body and not clean and not link and not image:
                raise ValueError('Enter loadout slots, notes or a reference link')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn, unit_id, 'references'); revision(conn, unit_id, data)
                old = get_row(conn, 'unit_references', unit_id, data['id']) if 'id' in data else None
                if old and old['kind'] != kind:
                    raise ValueError('The reference type cannot be changed')
                if not old and conn.execute('SELECT count(*) FROM unit_references WHERE unit_id=?', (unit_id,)).fetchone()[0]>=1000:
                    raise ValueError('Keep at most 1000 references per unit')
                values = (kind, title, category, role, body, link, image, json.dumps(clean), archive(data), actor(conn, unit_id), time.time())
                if old:
                    conn.execute('UPDATE unit_references SET kind=?,title=?,category=?,role=?,body=?,url=?,image_url=?,slots=?,archived=?,updated_by=?,updated_at=? WHERE id=?', (*values,old['id']))
                    reference_id = old['id']
                else:
                    reference_id = conn.execute('INSERT INTO unit_references(unit_id,kind,title,category,role,body,url,image_url,slots,archived,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (unit_id,*values)).lastrowid
                audit(conn, unit_id, 'reference', reference_id, 'updated' if old else 'created', old, get_row(conn,'unit_references',unit_id,reference_id))
            g.audit_details = dict(unit_id=unit_id, reference_id=reference_id, change='reference saved')
            return jsonify(ok=True, id=reference_id)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def awards_list(conn, unit_id, member_id=None):
        before = number(int(request.args.get('before', '0')), 'History cursor', 0, 9223372036854775807)
        rows = [dict(r) for r in conn.execute('SELECT a.*,r.game_name FROM unit_member_awards a JOIN unit_roster r ON r.id=a.member_id AND r.unit_id=a.unit_id WHERE a.unit_id=? AND (? IS NULL OR a.member_id=?) AND (?=0 OR a.id<?) ORDER BY a.id DESC LIMIT 51', (unit_id,member_id,member_id,before,before))]
        return dict(grants=rows[:50], next_before=rows[49]['id'] if len(rows)>50 else None)

    @api.app.get('/api/units/<int:unit_id>/awards')
    def unit_awards(unit_id):
        try:
            with db() as conn:
                unit=access(conn,unit_id)
                member_id = number(int(request.args['member_id']), 'Member', 1, 9223372036854775807) if 'member_id' in request.args else None
                catalog=[dict(r) for r in conn.execute('SELECT * FROM unit_award_catalog WHERE unit_id=? ORDER BY archived,name COLLATE NOCASE,id',(unit_id,))]
                members=[dict(r) for r in conn.execute('SELECT id,game_name,archived FROM unit_roster WHERE unit_id=? ORDER BY archived,game_name COLLATE NOCASE',(unit_id,))]
                return jsonify(catalog=catalog,members=members,permissions=permissions(conn,unit_id),revision=unit['revision'],today=date.today().isoformat(),**awards_list(conn,unit_id,member_id))
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/units/<int:unit_id>/roster/<int:member_id>/awards')
    def unit_member_awards(unit_id,member_id):
        try:
            with db() as conn:
                access(conn,unit_id); get_row(conn,'unit_roster',unit_id,member_id)
                return jsonify(**awards_list(conn,unit_id,member_id))
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/awards/catalog')
    def unit_award_save(unit_id):
        data=request.get_json()
        try:
            name=text(data.get('name'),'Award name',120,True); description=text(data.get('description',''),'Description',4000)
            image=url(data.get('image_url',''),'Image URL')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn,unit_id,'awards'); revision(conn,unit_id,data)
                old=get_row(conn,'unit_award_catalog',unit_id,data['id']) if 'id' in data else None
                if not old and conn.execute('SELECT count(*) FROM unit_award_catalog WHERE unit_id=?',(unit_id,)).fetchone()[0]>=200:
                    raise ValueError('Keep at most 200 awards per unit')
                if old:
                    conn.execute('UPDATE unit_award_catalog SET name=?,description=?,image_url=?,archived=? WHERE id=?',(name,description,image,archive(data),old['id'])); award_id=old['id']
                else:
                    award_id=conn.execute('INSERT INTO unit_award_catalog(unit_id,name,description,image_url,archived) VALUES(?,?,?,?,?)',(unit_id,name,description,image,archive(data))).lastrowid
                audit(conn,unit_id,'award_catalog',award_id,'saved',old,get_row(conn,'unit_award_catalog',unit_id,award_id))
            g.audit_details=dict(unit_id=unit_id,award_id=award_id,change='award catalog saved')
            return jsonify(ok=True,id=award_id)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    def campaign_events(conn, campaign):
        if campaign['mode']=='range':
            tz=ZoneInfo(campaign['timezone'])
            start=datetime.combine(date.fromisoformat(campaign['starts_on']),datetime.min.time(),tz).timestamp()
            end=datetime.combine(date.fromisoformat(campaign['ends_on'])+timedelta(days=1),datetime.min.time(),tz).timestamp()
            return [dict(r) for r in conn.execute('SELECT * FROM unit_events WHERE unit_id=? AND starts>=? AND starts<? ORDER BY starts,id',(campaign['unit_id'],start,end))]
        ids=json.loads(campaign['event_ids'])
        if not ids:
            return []
        marks=','.join('?' for _ in ids)
        return [dict(r) for r in conn.execute(f'SELECT * FROM unit_events WHERE unit_id=? AND id IN ({marks}) ORDER BY starts,id',(campaign['unit_id'],*ids))]

    def campaign_results(conn, campaign):
        events=campaign_events(conn,campaign); finalized=[e for e in events if e['tracked'] and e['state']=='finalized']
        members={}
        for event in finalized:
            for row in conn.execute('SELECT m.*,r.game_name AS current_name FROM unit_event_members m LEFT JOIN unit_roster r ON r.id=m.member_id AND r.unit_id=? WHERE m.event_id=?',(campaign['unit_id'],event['id'])):
                member=members.setdefault(row['member_id'],dict(member_id=row['member_id'],game_name=row['current_name'] or row['game_name'],has_record=row['current_name'] is not None,present=0,credited_present=0,counted=0,unknown=0,excused=0))
                if row['outcome']=='present':
                    member['present']+=1
                if row['status']!='loa' and row['outcome']!='excused':
                    member['counted']+=1
                    member['credited_present']+=row['outcome']=='present'
                if row['outcome']=='unknown':
                    member['unknown']+=1
                if row['outcome']=='excused':
                    member['excused']+=1
        awarded={r[0] for r in conn.execute("SELECT member_id FROM unit_member_awards WHERE unit_id=? AND campaign_id=? AND state='active'",(campaign['unit_id'],campaign['id']))}
        for member in members.values():
            member['rate']=round(member['credited_present']/member['counted']*100,1) if member['counted'] else None
            member['eligible']=bool(member['counted'] and member['credited_present']*100>=campaign['threshold']*member['counted'])
            member['awarded']=member['member_id'] in awarded
        closes=datetime.combine(date.fromisoformat(campaign['ends_on'])+timedelta(days=1),datetime.min.time(),ZoneInfo(campaign['timezone'])).timestamp() if campaign['mode']=='range' else 0
        return dict(window_closed=closes<=time.time(),events=events,finalized=len(finalized),pending=sum(e['tracked'] and e['state']=='scheduled' for e in events),members=sorted(members.values(),key=lambda m:m['game_name'].casefold()))

    @api.app.get('/api/units/<int:unit_id>/campaigns')
    def unit_campaigns(unit_id):
        with db() as conn:
            unit=access(conn,unit_id)
            rows=[dict(r) for r in conn.execute('SELECT * FROM unit_campaigns WHERE unit_id=? ORDER BY id DESC',(unit_id,))]
            events=[dict(r) for r in conn.execute('SELECT id,name,starts,state,tracked FROM unit_events WHERE unit_id=? ORDER BY starts DESC LIMIT 1000',(unit_id,))]
            awards=[dict(r) for r in conn.execute('SELECT * FROM unit_award_catalog WHERE unit_id=? ORDER BY archived,name',(unit_id,))]
            return jsonify(campaigns=rows,events=events,awards=awards,revision=unit['revision'],permissions=permissions(conn,unit_id))

    @api.app.get('/api/units/<int:unit_id>/campaigns/<int:campaign_id>')
    def unit_campaign(unit_id,campaign_id):
        with db() as conn:
            unit=access(conn,unit_id); campaign=get_row(conn,'unit_campaigns',unit_id,campaign_id)
            return jsonify(campaign=campaign,results=campaign_results(conn,campaign),revision=unit['revision'],permissions=permissions(conn,unit_id))

    @api.app.post('/api/units/<int:unit_id>/campaigns')
    def unit_campaign_save(unit_id):
        data=request.get_json()
        try:
            name=text(data.get('name'),'Campaign name',120,True); description=text(data.get('description',''),'Description',4000)
            mode=data.get('mode'); state=data.get('state','active'); tz=zone(data.get('timezone','UTC'))
            if mode not in ('range','manual') or state not in ('active','completed','archived'):
                raise ValueError('Choose a campaign grouping and state')
            starts=ends=''
            if mode=='range':
                starts=day(data.get('starts_on'),'Start date'); ends=day(data.get('ends_on'),'End date')
                if ends<starts:
                    raise ValueError('End date must follow the start date')
            ids=data.get('event_ids',[])
            if not isinstance(ids,list) or len(ids)>500 or any(type(i) is not int for i in ids) or len(set(ids))!=len(ids):
                raise ValueError('Choose at most 500 distinct events')
            if mode=='manual' and not ids:
                raise ValueError('Select at least one event')
            threshold=number(data.get('threshold',50),'Participation threshold',1,100)
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn,unit_id,'campaigns'); revision(conn,unit_id,data)
                for event_id in ids:
                    get_row(conn,'unit_events',unit_id,event_id)
                award_id=data.get('award_id')
                if award_id is not None:
                    get_row(conn,'unit_award_catalog',unit_id,award_id)
                old=get_row(conn,'unit_campaigns',unit_id,data['id']) if 'id' in data else None
                if not old and conn.execute('SELECT count(*) FROM unit_campaigns WHERE unit_id=?',(unit_id,)).fetchone()[0]>=200:
                    raise ValueError('Keep at most 200 campaigns per unit')
                values=(name,description,mode,starts,ends,str(tz),json.dumps(ids if mode=='manual' else []),threshold,award_id,state)
                if old:
                    conn.execute('UPDATE unit_campaigns SET name=?,description=?,mode=?,starts_on=?,ends_on=?,timezone=?,event_ids=?,threshold=?,award_id=?,state=? WHERE id=?',(*values,old['id'])); campaign_id=old['id']
                else:
                    campaign_id=conn.execute('INSERT INTO unit_campaigns(unit_id,name,description,mode,starts_on,ends_on,timezone,event_ids,threshold,award_id,state) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(unit_id,*values)).lastrowid
                audit(conn,unit_id,'campaign',campaign_id,'saved',old,get_row(conn,'unit_campaigns',unit_id,campaign_id))
            g.audit_details=dict(unit_id=unit_id,campaign_id=campaign_id,change='campaign saved')
            return jsonify(ok=True,id=campaign_id)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/awards/grant')
    def unit_award_grant(unit_id):
        data=request.get_json()
        try:
            awarded_on=day(data.get('awarded_on'),'Award date',past=True); citation=text(data.get('citation'),'Citation',4000,True)
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn,unit_id,'awards'); revision(conn,unit_id,data)
                member=get_row(conn,'unit_roster',unit_id,data.get('member_id')); award=get_row(conn,'unit_award_catalog',unit_id,data.get('award_id'))
                if award['archived']:
                    raise ValueError('Restore this award before issuing it')
                campaign_id=data.get('campaign_id')
                if campaign_id is not None:
                    campaign=get_row(conn,'unit_campaigns',unit_id,campaign_id)
                    if campaign['state']!='completed' or campaign['award_id']!=award['id']:
                        raise ValueError('Complete the campaign and select its award before granting campaign credit')
                    if campaign['mode']=='range':
                        closes=datetime.combine(date.fromisoformat(campaign['ends_on'])+timedelta(days=1),datetime.min.time(),ZoneInfo(campaign['timezone'])).timestamp()
                        if closes>time.time():
                            raise ValueError('Wait until the campaign date window ends before issuing its award')
                    results=campaign_results(conn,campaign)
                    participant=next((m for m in results['members'] if m['member_id']==member['id']),None)
                    if results['pending'] or not participant or not participant['eligible'] or participant['awarded']:
                        raise ValueError('Finalize campaign attendance and recheck eligibility; this member may already have the award')
                elif conn.execute("SELECT 1 FROM unit_member_awards WHERE unit_id=? AND member_id=? AND award_id=? AND state='active'",(unit_id,member['id'],award['id'])).fetchone() and data.get('additional') is not True:
                    raise ValueError('This member already holds the award. Confirm an additional award explicitly.')
                grant_id=conn.execute('INSERT INTO unit_member_awards(unit_id,member_id,award_id,award_name,image_url,awarded_on,issuer,citation,campaign_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(unit_id,member['id'],award['id'],award['name'],award['image_url'],awarded_on,actor(conn,unit_id),citation,campaign_id,time.time())).lastrowid
                audit(conn,unit_id,'member_award',grant_id,'granted',None,get_row(conn,'unit_member_awards',unit_id,grant_id),member_id=member['id'])
            g.audit_details=dict(unit_id=unit_id,member_id=member['id'],award_id=award['id'],campaign_id=campaign_id,change='award granted')
            return jsonify(ok=True,id=grant_id)
        except (ValueError,sqlite3.IntegrityError) as exc:
            return jsonify(ok=False,error='This campaign award is already recorded' if isinstance(exc,sqlite3.IntegrityError) else str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/awards/<int:grant_id>/revoke')
    def unit_award_revoke(unit_id,grant_id):
        data=request.get_json()
        try:
            reason=text(data.get('reason'),'Revocation reason',1000,True)
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn,unit_id,'awards'); revision(conn,unit_id,data)
                old=get_row(conn,'unit_member_awards',unit_id,grant_id)
                if old['state']!='active':
                    raise ValueError('This award is already revoked')
                conn.execute("UPDATE unit_member_awards SET state='revoked',revoked_by=?,revoked_on=?,revoke_reason=? WHERE id=?",(actor(conn,unit_id),time.time(),reason,grant_id))
                audit(conn,unit_id,'member_award',grant_id,'revoked',old,get_row(conn,'unit_member_awards',unit_id,grant_id),reason,old['member_id'])
            g.audit_details=dict(unit_id=unit_id,member_id=old['member_id'],award_id=old['award_id'],change='award revoked')
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/units/<int:unit_id>/analytics')
    def unit_analytics(unit_id):
        try:
            tz=zone(request.args.get('timezone','UTC'))
            end_day=day(request.args.get('end',datetime.now(tz).date().isoformat()),'End date')
            start_day=day(request.args.get('start',(date.fromisoformat(end_day)-timedelta(days=89)).isoformat()),'Start date')
            first=date.fromisoformat(start_day); last=date.fromisoformat(end_day)
            if not 0<=(last-first).days<=365 or last>datetime.now(tz).date():
                raise ValueError('Choose up to 366 days ending today or earlier')
            start=datetime.combine(first,datetime.min.time(),tz).timestamp(); end=datetime.combine(last+timedelta(days=1),datetime.min.time(),tz).timestamp(); end=min(end,time.time())
            with db() as conn:
                access(conn,unit_id)
                snapshots=[dict(r) for r in conn.execute('SELECT * FROM unit_strength_history WHERE unit_id=? AND observed<=? ORDER BY observed,id',(unit_id,end))]
                initial=conn.execute('SELECT min(observed) FROM unit_strength_history WHERE unit_id=?',(unit_id,)).fetchone()[0]
                effective=min(end,max(start,initial)) if initial is not None else end
                cohort={r[0] for r in conn.execute('SELECT member_id FROM unit_membership_spans WHERE unit_id=? AND starts<=? AND (ends IS NULL OR ends>?)',(unit_id,effective,effective))}
                retained={r[0] for r in conn.execute('SELECT member_id FROM unit_membership_spans WHERE unit_id=? AND starts<=? AND (ends IS NULL OR ends>?)',(unit_id,end,end))}
                series=[]; index=0; latest=None; cursor=first
                while cursor<=last:
                    boundary=min(datetime.combine(cursor+timedelta(days=1),datetime.min.time(),tz).timestamp(),end)
                    while index<len(snapshots) and snapshots[index]['observed']<=boundary:
                        latest=snapshots[index];index+=1
                    series.append(dict(day=cursor.isoformat(),active=latest['active'] if latest else None,reserve=latest['reserve'] if latest else None,loa=latest['loa'] if latest else None,total=latest['total'] if latest else None));cursor+=timedelta(days=1)
                movements={r['movement']:r['n'] for r in conn.execute("SELECT movement,count(*) AS n FROM unit_strength_history WHERE unit_id=? AND observed>=? AND observed<=? AND movement!='baseline' GROUP BY movement",(unit_id,start,end))}
                turnout=[]
                for event in conn.execute("SELECT id,name,starts FROM unit_events WHERE unit_id=? AND starts>=? AND starts<? AND state='finalized' AND tracked=1 ORDER BY starts,id",(unit_id,start,end)):
                    rows=conn.execute('SELECT outcome,expected,count(*) AS n FROM unit_event_members WHERE event_id=? GROUP BY outcome,expected',(event['id'],)).fetchall()
                    present=sum(r['n'] for r in rows if r['outcome']=='present'); counted=sum(r['n'] for r in rows if r['expected'] and r['outcome'] in ('present','absent')); expected_present=sum(r['n'] for r in rows if r['expected'] and r['outcome']=='present')
                    turnout.append(dict(event, present=present,counted=counted,rate=round(expected_present/counted*100,1) if counted else None,unknown=sum(r['n'] for r in rows if r['outcome']=='unknown')))
                ranks=[dict(r) for r in conn.execute("SELECT rank_track,rank,count(*) AS n FROM unit_roster WHERE unit_id=? AND archived=0 GROUP BY rank_track,rank ORDER BY rank_track,rank",(unit_id,))]
            return jsonify(start=start_day,end=end_day,timezone=str(tz),tracking_since=initial,strength=series,movements=movements,cohort=len(cohort),retained=len(cohort & retained),retention=round(len(cohort & retained)/len(cohort)*100,1) if cohort else None,turnout=turnout,ranks=ranks)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400
