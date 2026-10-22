"""Unit-scoped staff permissions and rosters; server controls remain explicit grants."""
from contextlib import contextmanager
import csv
from datetime import date, timedelta
import io
import json
import re
import sqlite3
import time

from flask import abort, g, jsonify, request, send_from_directory

UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
CAPABILITIES = ('roster', 'staff')
FIELDS = ('game_name', 'discord', 'identity', 'status', 'rank', 'section', 'position', 'joined_on', 'loa_until', 'notes', 'last_promo', 'certificates')


def text(value, name, limit=120, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError(f'{name}: use text up to {limit} characters')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{name} is required')
    return value


def install(api):
    database = api.server_registry.database

    @contextmanager
    def db():
        conn = sqlite3.connect(database, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                tag TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS unit_servers (
                unit_id INTEGER NOT NULL, server_id TEXT NOT NULL,
                PRIMARY KEY(unit_id,server_id));
            CREATE TABLE IF NOT EXISTS unit_staff (
                unit_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('staff','admin')),
                capabilities TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(unit_id,user_id));
            CREATE TABLE IF NOT EXISTS unit_roster (
                id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL,
                game_name TEXT NOT NULL, discord TEXT NOT NULL DEFAULT '', identity TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active', rank TEXT NOT NULL DEFAULT '',
                section TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '',
                joined_on TEXT NOT NULL DEFAULT '', loa_until TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS unit_roster_identity ON unit_roster(unit_id,identity) WHERE identity!='';
            CREATE INDEX IF NOT EXISTS unit_roster_unit ON unit_roster(unit_id,archived);
            CREATE TABLE IF NOT EXISTS unit_structure (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                parent_id INTEGER, kind TEXT NOT NULL CHECK(kind IN ('group','section','billet')),
                name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS unit_structure_parent ON unit_structure(unit_id,parent_id,sort_order);
            CREATE TABLE IF NOT EXISTS unit_primary_slots (
                unit_id INTEGER NOT NULL, member_id INTEGER PRIMARY KEY,
                billet_id INTEGER NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS unit_roster_deleted_ids (id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS unit_member_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                author_name TEXT NOT NULL, created_at REAL NOT NULL, note TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_member_notes_member ON unit_member_notes(unit_id,member_id,id);

        ''')
        for table, column, definition in [('units','catalog',"TEXT NOT NULL DEFAULT '{}'"),('unit_roster','last_promo',"TEXT NOT NULL DEFAULT ''"),('unit_roster','certificates',"TEXT NOT NULL DEFAULT ''"),('unit_roster','panel_user_id','INTEGER')]:
            if column not in {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS unit_roster_panel_user ON unit_roster(unit_id,panel_user_id) WHERE panel_user_id IS NOT NULL')
        owner_id = conn.execute('SELECT user_id FROM panel_owner WHERE singleton=1').fetchone()[0]

    def panel_admin():
        return g.user['id'] == owner_id or bool(g.user['panel_admin'])

    def hosting_access(conn):
        return panel_admin() or bool(g.user['access_all']) or bool(conn.execute('SELECT 1 FROM user_server_roles WHERE user_id=? LIMIT 1',(g.user['id'],)).fetchone())

    def unit_only_user():
        with db() as conn:
            return not hosting_access(conn) and bool(conn.execute('SELECT 1 FROM unit_staff WHERE user_id=? LIMIT 1',(g.user['id'],)).fetchone())

    api.unit_only_user=unit_only_user

    def access(conn, unit_id, capability=None):
        unit = conn.execute('SELECT * FROM units WHERE id=?', (unit_id,)).fetchone()
        if not unit:
            abort(404, description='Unit not found')
        if panel_admin():
            return unit
        membership = conn.execute('SELECT * FROM unit_staff WHERE unit_id=? AND user_id=?', (unit_id,g.user['id'])).fetchone()
        if not membership:
            abort(404, description='Unit not found')
        if capability and membership['role'] != 'admin' and capability not in json.loads(membership['capabilities']):
            abort(403, description='Your unit role does not allow this change')
        return unit

    def revision(conn, unit_id, data):
        if type(data.get('revision')) is not int:
            raise ValueError('Reload the unit before saving')
        if not conn.execute('UPDATE units SET revision=revision+1 WHERE id=? AND revision=?', (unit_id,data['revision'])).rowcount:
            abort(409, description='This unit changed. Reload it before saving your changes.')

    def validate_staff(role, capabilities):
        if role not in ('staff','admin') or not isinstance(capabilities,list) or any(c not in CAPABILITIES for c in capabilities):
            raise ValueError('Choose Staff or Unit administrator and valid permissions')
        # Managing staff is an administrator responsibility, never a staff checkbox.
        if role == 'staff' and 'staff' in capabilities:
            raise ValueError('Only unit administrators can manage unit staff')

    def protect_admin(conn, unit_id, user_id, new_role):
        previous = conn.execute('SELECT role FROM unit_staff WHERE unit_id=? AND user_id=?', (unit_id,user_id)).fetchone()
        if user_id == owner_id and g.user['id'] != owner_id:
            abort(403, description='Only the Owner can change their unit membership')
        if previous and previous['role'] == 'admin' and new_role != 'admin':
            remaining = conn.execute("SELECT count(*) FROM unit_staff s JOIN users u ON u.id=s.user_id WHERE s.unit_id=? AND s.role='admin' AND u.enabled=1 AND s.user_id!=?", (unit_id,user_id)).fetchone()[0]
            if not remaining:
                raise ValueError('Keep at least one enabled unit administrator')

    def save_user_units(conn, user_id, assignments, revisions=None):
        """Called inside the existing account-save transaction, before commit."""
        if not isinstance(assignments,list) or len(assignments)>100:
            raise ValueError('Choose valid unit memberships')
        desired = {}
        for item in assignments:
            if not isinstance(item,dict) or type(item.get('unit_id')) is not int:
                raise ValueError('Choose valid unit memberships')
            unit_id = item['unit_id']
            if unit_id in desired:
                raise ValueError('A unit can only be assigned once')
            access(conn, unit_id, 'staff')
            validate_staff(item.get('role'), item.get('capabilities',[]))
            desired[unit_id] = item
        existing = {r['unit_id'] for r in conn.execute('SELECT unit_id FROM unit_staff WHERE user_id=?',(user_id,))}
        for unit_id in existing | desired.keys():
            if revisions is not None:
                current=conn.execute('SELECT revision FROM units WHERE id=?',(unit_id,)).fetchone()
                if not isinstance(revisions,dict) or not current or revisions.get(str(unit_id))!=current['revision']:
                    abort(409,description='Unit membership changed. Reopen the account editor.')
            item = desired.get(unit_id)
            protect_admin(conn,unit_id,user_id,item['role'] if item else None)
            conn.execute('DELETE FROM unit_staff WHERE unit_id=? AND user_id=?',(unit_id,user_id))
            if item:
                conn.execute('INSERT INTO unit_staff VALUES(?,?,?,?)',(unit_id,user_id,item['role'],json.dumps(item.get('capabilities',[]))))
            conn.execute('UPDATE units SET revision=revision+1 WHERE id=?',(unit_id,))

    def protect_account(conn, user_id):
        if conn.execute('SELECT enabled FROM users WHERE id=?',(user_id,)).fetchone()['enabled']:
            return
        for row in conn.execute("SELECT unit_id FROM unit_staff WHERE user_id=? AND role='admin'",(user_id,)):
            protect_admin(conn,row['unit_id'],user_id,None)

    api.save_user_units = save_user_units
    api.protect_unit_account = protect_account

    endpoints = {'units_list','units_save','unit_detail','unit_roster_save','unit_staff_save',
                 'unit_identities','unit_roster_export','unit_health','units_page','unit_catalog_save','unit_position_rename','unit_member_record','unit_member_note_save','unit_roster_delete','unit_structure_save','unit_structure_delete','unit_structure_order','unit_primary_assign'}
    api.PANEL_WIDE_ENDPOINTS.update(endpoints)

    @api.app.errorhandler(400)
    @api.app.errorhandler(403)
    @api.app.errorhandler(404)
    @api.app.errorhandler(409)
    def unit_error(error):
        if request.endpoint in endpoints or request.endpoint=='users_save':
            return jsonify(ok=False,error=error.description),error.code
        return error

    @api.app.get('/units')
    def units_page():
        return send_from_directory(api._BASE_DIR,'units.html')

    @api.app.get('/api/units')
    def units_list():
        with db() as conn:
            rows = conn.execute('SELECT * FROM units ORDER BY name').fetchall() if panel_admin() else conn.execute('SELECT u.* FROM units u JOIN unit_staff s ON s.unit_id=u.id WHERE s.user_id=? ORDER BY u.name',(g.user['id'],)).fetchall()
            result = []
            for row in rows:
                member = conn.execute('SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?',(row['id'],g.user['id'])).fetchone()
                result.append(dict(row,role='admin' if panel_admin() else member['role'],capabilities=list(CAPABILITIES) if panel_admin() or member['role']=='admin' else json.loads(member['capabilities']),
                    servers=[r['server_id'] for r in conn.execute('SELECT server_id FROM unit_servers WHERE unit_id=?',(row['id'],))]))
            # Only disclose server names linked to visible units, plus explicit server grants.
            visible = {s for row in result for s in row['servers']}
            servers = [dict(id=s.id,name=s.name) for s in api.server_registry.list() if panel_admin() or s.id in visible or api.server_permissions(g.user,s.id)]
            if not api.manager_mode and (panel_admin() or '' in visible or api.server_permissions(g.user,'')):
                servers.insert(0,dict(id='',name='Existing server'))
            has_hosting_access=hosting_access(conn)
        return jsonify(units=result,servers=servers,panel_admin=panel_admin(),hosting_access=has_hosting_access,user_id=g.user['id'])

    @api.app.post('/api/units')
    def units_save():
        if not panel_admin():
            abort(403,description='Only panel administrators can create or edit units and server links')
        data = request.get_json()
        try:
            name = text(data.get('name'),'Unit name',80,True)
            tag = text(data.get('tag',''),'Unit tag',16)
            links = data.get('servers',[])
            known = {s.id for s in api.server_registry.list()} | (set() if api.manager_mode else {''})
            if not isinstance(links,list) or any(not isinstance(s,str) or s not in known for s in links):
                raise ValueError('Choose existing servers')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                unit_id = data.get('id')
                if unit_id is None:
                    unit_id = conn.execute('INSERT INTO units(name,tag) VALUES(?,?)',(name,tag)).lastrowid
                    conn.execute("INSERT INTO unit_staff(unit_id,user_id,role) VALUES(?,?,'admin')",(unit_id,g.user['id']))
                else:
                    if type(unit_id) is not int:
                        raise ValueError('Choose a valid unit')
                    access(conn,unit_id)
                    revision(conn,unit_id,data)
                    conn.execute('UPDATE units SET name=?,tag=? WHERE id=?',(name,tag,unit_id))
                conn.execute('DELETE FROM unit_servers WHERE unit_id=?',(unit_id,))
                conn.executemany('INSERT INTO unit_servers VALUES(?,?)',[(unit_id,s) for s in set(links)])
            g.audit_details = dict(unit_id=unit_id,name=name,servers=links)
            return jsonify(ok=True,id=unit_id)
        except (ValueError,sqlite3.IntegrityError) as exc:
            return jsonify(ok=False,error='Unit name is already in use' if isinstance(exc,sqlite3.IntegrityError) else str(exc)),400

    def catalog_values(raw):
        if not isinstance(raw,dict):
            raise ValueError('Choose valid rank and qualification settings')
        certificates = raw.get('certificates',[])
        if not isinstance(certificates,list) or len(certificates)>100:
            raise ValueError('Keep at most 100 qualifications')
        certificates = [text(c,'Qualification',80,True) for c in certificates]
        if len(set(c.casefold() for c in certificates)) != len(certificates) or any(';' in c for c in certificates):
            raise ValueError('Use unique qualification names without semicolons')
        positions=raw.get('positions',[])
        if not isinstance(positions,list) or len(positions)>100:
            raise ValueError('Keep at most 100 positions')
        positions=[text(p,'Position',80,True) for p in positions]
        if len(set(p.casefold() for p in positions))!=len(positions) or any(';' in p for p in positions):
            raise ValueError('Use unique position names without semicolons')
        def requirements(values):
            if not isinstance(values,list) or any(c not in certificates for c in values):
                raise ValueError('Select qualifications from this unit’s catalog')
            return sorted(set(values))
        paygrades = raw.get('paygrades',[]); ranks = raw.get('ranks',[])
        if not isinstance(paygrades,list) or not isinstance(ranks,list) or len(paygrades)>50 or len(ranks)>100:
            raise ValueError('Keep at most 50 paygrades and 100 ranks')
        grades = []
        for item in paygrades:
            if not isinstance(item,dict) or type(item.get('days')) is not int or not 0<=item['days']<=36500:
                raise ValueError('Time in grade must be 0–36500 whole days')
            grades.append(dict(name=text(item.get('name'),'Paygrade',40,True),days=item['days'],certificates=requirements(item.get('certificates',[]))))
        grade_names = {r['name'] for r in grades}
        if len(grade_names)!=len(grades):
            raise ValueError('Paygrade names must be unique')
        result = []
        for item in ranks:
            if not isinstance(item,dict):
                raise ValueError('Choose valid ranks')
            name = text(item.get('name'),'Rank',80,True)
            grade = text(item.get('paygrade'),'Paygrade',40,True)
            if grade not in grade_names:
                raise ValueError('Every rank needs a defined paygrade')
            result.append(dict(name=name,paygrade=grade,next_rank=text(item.get('next_rank',''),'Next rank',80),certificates=requirements(item.get('certificates',[]))))
        by_name = {r['name']:r for r in result}
        if len(by_name)!=len(result):
            raise ValueError('Rank names must be unique')
        for rank in result:
            seen = {rank['name']}; target = rank['next_rank']
            while target:
                if target not in by_name or target in seen:
                    raise ValueError('Next-rank paths must reference existing ranks without cycles')
                seen.add(target); target=by_name[target]['next_rank']
        return dict(certificates=certificates,positions=positions,paygrades=grades,ranks=result)

    @api.app.post('/api/units/<int:unit_id>/catalog')
    def unit_catalog_save(unit_id):
        data=request.get_json()
        try:
            catalog=catalog_values(data.get('catalog'))
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); access(conn,unit_id,'staff'); revision(conn,unit_id,data)
                used=[dict(r) for r in conn.execute('SELECT rank,certificates,position FROM unit_roster WHERE unit_id=?',(unit_id,))]
                names={r['name'] for r in catalog['ranks']}
                for row in used:
                    if row['rank'] and row['rank'] not in names or any(c not in catalog['certificates'] for c in row['certificates'].split(';') if c):
                        raise ValueError('A rank or qualification is used by a roster record. Update those records before removing it.')
                conn.execute('UPDATE units SET catalog=? WHERE id=?',(json.dumps(catalog),unit_id))
            g.audit_details=dict(unit_id=unit_id,change='rank and qualification catalog')
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/positions/rename')
    def unit_position_rename(unit_id):
        data=request.get_json()
        try:
            old=text(data.get('old'),'Existing position',80,True)
            new=text(data.get('name'),'Position name',80,True)
            if ';' in new:
                raise ValueError('Position names cannot contain semicolons')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                unit=access(conn,unit_id,'staff'); revision(conn,unit_id,data)
                catalog=json.loads(unit['catalog']); positions=catalog.get('positions',[])
                if old not in positions or any(p.casefold()==new.casefold() for p in positions if p!=old):
                    raise ValueError('Choose an existing position and a unique new name')
                catalog['positions']=[new if p==old else p for p in positions]
                conn.execute("UPDATE unit_structure SET name=? WHERE unit_id=? AND kind='billet' AND name=?",(new,unit_id,old))
                conn.execute('UPDATE units SET catalog=? WHERE id=?',(json.dumps(catalog),unit_id))
                for member in conn.execute('SELECT id,position FROM unit_roster WHERE unit_id=?',(unit_id,)).fetchall():
                    assigned=member['position'].split(';')
                    if old in assigned:
                        conn.execute('UPDATE unit_roster SET position=?,updated_at=? WHERE id=?',(';'.join(new if p==old else p for p in assigned),time.time(),member['id']))
            g.audit_details=dict(unit_id=unit_id,old_position=old,new_position=new)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    def promotion(member,catalog):
        ranks={r['name']:r for r in catalog.get('ranks',[])}
        current=ranks.get(member['rank'],{}); target=ranks.get(current.get('next_rank'))
        if not target:
            return dict(next_rank='',next_date='',missing=[],eligible=False)
        grade=next(g for g in catalog['paygrades'] if g['name']==target['paygrade'])
        held=set(member['certificates'].split(';'))
        missing=sorted((set(grade['certificates'])|set(target['certificates']))-held)
        due=(date.fromisoformat(member['last_promo'])+timedelta(days=grade['days'])).isoformat() if member['last_promo'] else ''
        return dict(next_rank=target['name'],next_date=due,missing=missing,eligible=bool(due and due<=date.today().isoformat() and not missing and not member['archived']))

    def structure_rows(conn,unit_id):
        return [dict(row) for row in conn.execute('SELECT * FROM unit_structure WHERE unit_id=? ORDER BY sort_order,id',(unit_id,))]

    def structure_node(conn,unit_id,node_id,kind=None):
        if type(node_id) is not int:
            raise ValueError('Choose a valid structure item')
        node=conn.execute('SELECT * FROM unit_structure WHERE unit_id=? AND id=?',(unit_id,node_id)).fetchone()
        if not node or kind and node['kind']!=kind:
            abort(404,description='Structure item not found in this unit')
        return node

    def decorate_slots(conn,unit_id,members,structure=None):
        structure=structure if structure is not None else structure_rows(conn,unit_id)
        by_id={row['id']:row for row in structure}
        assignments={row['member_id']:row['billet_id'] for row in conn.execute('SELECT * FROM unit_primary_slots WHERE unit_id=?',(unit_id,))}
        for member in members:
            slot=by_id.get(assignments.get(member['id']))
            path=[];current=slot
            while current:
                path.append(current['name']);current=by_id.get(current['parent_id'])
            member.update(billet_id=slot['id'] if slot else None,billet_name=slot['name'] if slot else '',billet_path=' / '.join(reversed(path)))

    def assign_slot(conn,unit_id,member_id,billet_id):
        member=find_member(conn,unit_id,member_id)
        if billet_id is not None:
            structure_node(conn,unit_id,billet_id,'billet')
            if member['archived']:
                raise ValueError('Restore this member before assigning a primary billet')
            occupied=conn.execute('SELECT member_id FROM unit_primary_slots WHERE unit_id=? AND billet_id=?',(unit_id,billet_id)).fetchone()
            if occupied and occupied['member_id']!=member_id:
                abort(409,description='This billet is already filled. Unassign its current member first.')
        conn.execute('DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?',(unit_id,member_id))
        if billet_id is not None:
            conn.execute('INSERT INTO unit_primary_slots VALUES(?,?,?)',(unit_id,member_id,billet_id))

    @api.app.post('/api/units/<int:unit_id>/structure')
    def unit_structure_save(unit_id):
        data=request.get_json()
        try:
            kind=data.get('kind');name=text(data.get('name'),'Name',80,True)
            if kind not in ('group','section','billet'):
                raise ValueError('Choose a group, section or billet')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE');access(conn,unit_id,'staff');revision(conn,unit_id,data)
                identity=data.get('id');old=structure_node(conn,unit_id,identity) if identity is not None else None
                if old and old['kind']!=kind:
                    raise ValueError('The item type cannot be changed')
                parent=data.get('parent_id')
                if kind=='group':
                    if parent is not None:
                        raise ValueError('Groups must be at the top level')
                else:
                    target=structure_node(conn,unit_id,parent)
                    if target['kind'] not in (('group','section') if kind=='section' else ('section',)):
                        raise ValueError('Sections belong inside groups or sections; billets belong inside sections')
                    ancestors=[]
                    while target:
                        if target['id']==identity:
                            raise ValueError('An item cannot be moved inside itself or its children')
                        ancestors.append(target['id'])
                        target=structure_node(conn,unit_id,target['parent_id']) if target['parent_id'] is not None else None
                    # Keep the editable hierarchy shallow enough to read and navigate.
                    descendants=conn.execute('WITH RECURSIVE tree(id,depth) AS (SELECT id,0 FROM unit_structure WHERE id=? AND unit_id=? UNION ALL SELECT n.id,t.depth+1 FROM unit_structure n JOIN tree t ON n.parent_id=t.id WHERE n.unit_id=?) SELECT COALESCE(MAX(depth),0) FROM tree',(identity,unit_id,unit_id)).fetchone()[0] if old else 0
                    if len(ancestors)+descendants>6:
                        raise ValueError('Use at most six levels below a group')
                if old:
                    order=old['sort_order'] if old['parent_id']==parent else conn.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM unit_structure WHERE unit_id=? AND parent_id IS ?',(unit_id,parent)).fetchone()[0]
                    conn.execute('UPDATE unit_structure SET name=?,parent_id=?,sort_order=? WHERE id=? AND unit_id=?',(name,parent,order,identity,unit_id))
                else:
                    if conn.execute('SELECT count(*) FROM unit_structure WHERE unit_id=?',(unit_id,)).fetchone()[0]>=2000:
                        raise ValueError('Keep at most 2000 structure items per unit')
                    order=conn.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM unit_structure WHERE unit_id=? AND parent_id IS ?',(unit_id,parent)).fetchone()[0]
                    identity=conn.execute('INSERT INTO unit_structure(unit_id,parent_id,kind,name,sort_order) VALUES(?,?,?,?,?)',(unit_id,parent,kind,name,order)).lastrowid
            g.audit_details=dict(unit_id=unit_id,structure_id=identity,kind=kind,name=name,parent_id=parent,before=dict(old) if old else None)
            return jsonify(ok=True,id=identity)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/structure/<int:node_id>/delete')
    def unit_structure_delete(unit_id,node_id):
        data=request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE');access(conn,unit_id,'staff');revision(conn,unit_id,data)
                node=structure_node(conn,unit_id,node_id)
                if data.get('confirm_name')!=node['name']:
                    raise ValueError('Type the item’s name exactly to confirm removal')
                ids=[row[0] for row in conn.execute('WITH RECURSIVE tree(id) AS (SELECT id FROM unit_structure WHERE unit_id=? AND id=? UNION ALL SELECT n.id FROM unit_structure n JOIN tree t ON n.parent_id=t.id WHERE n.unit_id=?) SELECT id FROM tree',(unit_id,node_id,unit_id))]
                marks=','.join('?' for _ in ids)
                released=[row[0] for row in conn.execute(f'SELECT member_id FROM unit_primary_slots WHERE unit_id=? AND billet_id IN ({marks})',(unit_id,*ids))]
                conn.execute(f'DELETE FROM unit_primary_slots WHERE unit_id=? AND billet_id IN ({marks})',(unit_id,*ids))
                conn.execute(f'DELETE FROM unit_structure WHERE unit_id=? AND id IN ({marks})',(unit_id,*ids))
            g.audit_details=dict(unit_id=unit_id,removed_structure=ids,released_members=released,name=node['name'])
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/structure/<int:node_id>/order')
    def unit_structure_order(unit_id,node_id):
        data=request.get_json()
        if data.get('direction') not in ('up','down'):
            return jsonify(ok=False,error='Choose up or down'),400
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE');access(conn,unit_id,'staff');revision(conn,unit_id,data)
                node=structure_node(conn,unit_id,node_id)
                siblings=[row[0] for row in conn.execute('SELECT id FROM unit_structure WHERE unit_id=? AND parent_id IS ? ORDER BY sort_order,id',(unit_id,node['parent_id']))]
                index=siblings.index(node_id);target=index+(-1 if data['direction']=='up' else 1)
                if 0<=target<len(siblings):
                    siblings[index],siblings[target]=siblings[target],siblings[index]
                conn.executemany('UPDATE unit_structure SET sort_order=? WHERE id=? AND unit_id=?',[(i,key,unit_id) for i,key in enumerate(siblings)])
            g.audit_details=dict(unit_id=unit_id,structure_id=node_id,direction=data['direction'])
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/assignment')
    def unit_primary_assign(unit_id):
        data=request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE');access(conn,unit_id,'roster');revision(conn,unit_id,data)
                billet=data.get('billet_id');member=data.get('member_id')
                structure_node(conn,unit_id,billet,'billet')
                if member is None:
                    conn.execute('DELETE FROM unit_primary_slots WHERE unit_id=? AND billet_id=?',(unit_id,billet))
                else:
                    if type(member) is not int:
                        raise ValueError('Choose a roster member')
                    assign_slot(conn,unit_id,member,billet)
            g.audit_details=dict(unit_id=unit_id,billet_id=billet,member_id=member)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/units/<int:unit_id>')
    def unit_detail(unit_id):
        with db() as conn:
            unit = access(conn,unit_id)
            roster = [dict(r) for r in conn.execute('SELECT r.*,u.username AS panel_username,u.enabled AS panel_user_enabled FROM unit_roster r LEFT JOIN users u ON u.id=r.panel_user_id WHERE r.unit_id=? ORDER BY r.archived,r.game_name COLLATE NOCASE,r.id',(unit_id,))]
            membership = conn.execute('SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?',(unit_id,g.user['id'])).fetchone()
            catalog=json.loads(unit['catalog'])
            structure=structure_rows(conn,unit_id)
            decorate_slots(conn,unit_id,roster,structure)
            for member in roster:
                member['promotion']=promotion(member,catalog)
            admin = panel_admin() or membership['role']=='admin'
            accounts = [dict(r) for r in conn.execute('SELECT id,username,enabled FROM users ORDER BY username')] if panel_admin() else [dict(r) for r in conn.execute('SELECT u.id,u.username,u.enabled FROM users u JOIN unit_staff s ON s.user_id=u.id WHERE s.unit_id=? ORDER BY u.username',(unit_id,))]
            staff = [dict(r,capabilities=json.loads(r['capabilities'])) for r in conn.execute('SELECT s.*,u.username,u.enabled FROM unit_staff s JOIN users u ON u.id=s.user_id WHERE unit_id=? ORDER BY username',(unit_id,))] if admin else []
        return jsonify(unit=dict(unit,catalog=catalog),structure=structure,roster=roster,staff=staff,can_edit=admin or 'roster' in json.loads(membership['capabilities']),can_staff=admin,can_delete=admin,accounts=accounts,can_settings=panel_admin())

    def find_member(conn, unit_id, member_id):
        member=conn.execute('SELECT r.*,u.username AS panel_username,u.enabled AS panel_user_enabled FROM unit_roster r LEFT JOIN users u ON u.id=r.panel_user_id WHERE r.unit_id=? AND r.id=?',(unit_id,member_id)).fetchone()
        if not member:
            abort(404,description='Member not found in this unit')
        return member

    @api.app.get('/api/units/<int:unit_id>/roster/<int:member_id>/record')
    def unit_member_record(unit_id,member_id):
        try:
            before=int(request.args.get('before','0'))
            if not 0<=before<=9223372036854775807:
                raise ValueError()
        except ValueError:
            return jsonify(ok=False,error='Choose a valid record history cursor'),400
        with db() as conn:
            unit=access(conn,unit_id)
            member=dict(find_member(conn,unit_id,member_id))
            decorate_slots(conn,unit_id,[member])
            rows=[dict(r) for r in conn.execute('SELECT id,author_name,created_at,note FROM unit_member_notes WHERE unit_id=? AND member_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 51',(unit_id,member_id,before,before))]
            membership=conn.execute('SELECT role,capabilities FROM unit_staff WHERE unit_id=? AND user_id=?',(unit_id,g.user['id'])).fetchone()
            can_write=panel_admin() or membership['role']=='admin' or 'roster' in json.loads(membership['capabilities'])
        return jsonify(member=dict(member,promotion=promotion(member,json.loads(unit['catalog']))),notes=rows[:50],next_before=rows[49]['id'] if len(rows)>50 else None,can_write=can_write,can_delete=panel_admin() or membership['role']=='admin')

    @api.app.post('/api/units/<int:unit_id>/roster/<int:member_id>/record')
    def unit_member_note_save(unit_id,member_id):
        data=request.get_json()
        try:
            note=text(data.get('note'),'Record note',4000,True)
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                access(conn,unit_id,'roster')
                find_member(conn,unit_id,member_id)
                linked=conn.execute('SELECT game_name FROM unit_roster WHERE unit_id=? AND panel_user_id=?',(unit_id,g.user['id'])).fetchone()
                author_name=linked['game_name'] if linked else g.user['username']
                identity=conn.execute('INSERT INTO unit_member_notes(unit_id,member_id,author_id,author_name,created_at,note) VALUES(?,?,?,?,?,?)',(unit_id,member_id,g.user['id'],author_name,time.time(),note)).lastrowid
            g.audit_details=dict(unit_id=unit_id,member_id=member_id,note_id=identity)
            return jsonify(ok=True,id=identity)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    def recorded(conn, unit_id):
        links = [r['server_id'] for r in conn.execute('SELECT server_id FROM unit_servers WHERE unit_id=?',(unit_id,))]
        if not links:
            return []
        marks = ','.join('?' for _ in links)
        return [dict(r) for r in conn.execute(f'SELECT lower(identity) AS identity,name,last_seen FROM player_history WHERE server_id IN ({marks}) ORDER BY last_seen DESC',links) if UUID.fullmatch(r['identity'])]

    @api.app.get('/api/units/<int:unit_id>/identities')
    def unit_identities(unit_id):
        with db() as conn:
            access(conn,unit_id,'roster')
            query = request.args.get('q','').strip().casefold()
            if len(query)>120:
                abort(400,description='Search must be at most 120 characters')
            unique = {}
            for row in recorded(conn,unit_id):
                if row['identity'] not in unique and (query in row['name'].casefold() or query in row['identity']):
                    unique[row['identity']] = row
            rows = list(unique.values())
        return jsonify(players=rows[:100],more=len(rows)>100)

    def member_values(conn,unit_id,data,existing=None):
        values = {field:text(data.get(field,''),field,8000 if field in ('certificates','position') else 2000 if field=='notes' else 120,field=='game_name') for field in FIELDS}
        if values['status'] not in ('active','reserve','loa'):
            raise ValueError('Choose Active, Reserve or LOA')
        identity = values['identity'].lower()
        if identity and (not UUID.fullmatch(identity) or identity != (existing['identity'] if existing else '') and identity not in {r['identity'] for r in recorded(conn,unit_id)}):
            raise ValueError('Choose a recorded UUID from a server linked to this unit')
        values['identity'] = identity
        catalog=json.loads(conn.execute('SELECT catalog FROM units WHERE id=?',(unit_id,)).fetchone()['catalog'])
        certs=[c.strip() for c in values['certificates'].split(';') if c.strip()]
        if any(c not in catalog.get('certificates',[]) for c in certs):
            raise ValueError('Choose qualifications from the unit catalog')
        values['certificates']=';'.join(sorted(set(certs)))
        positions=[p.strip() for p in values['position'].split(';') if p.strip()]
        if any(p not in catalog.get('positions',[]) for p in positions) and values['position']!=(existing['position'] if existing else ''):
            raise ValueError('Choose positions from the unit catalog')
        values['position']=';'.join(sorted(set(positions)))
        if values['rank'] and values['rank'] not in {r['name'] for r in catalog.get('ranks',[])}:
            raise ValueError('Choose a rank from the unit catalog, or leave it blank')
        for field in ('joined_on','loa_until','last_promo'):
            if values[field]:
                try:
                    values[field]=date.fromisoformat(values[field]).isoformat()
                except ValueError:
                    raise ValueError(f'{field}: choose a valid date') from None
        if values['last_promo'] and values['last_promo']>date.today().isoformat():
            raise ValueError('Last promotion date cannot be in the future')
        return values

    @api.app.post('/api/units/<int:unit_id>/roster')
    def unit_roster_save(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                access(conn,unit_id,'roster')
                revision(conn,unit_id,data)
                member_id = data.get('id')
                existing = conn.execute('SELECT * FROM unit_roster WHERE id=? AND unit_id=?',(member_id,unit_id)).fetchone()
                if member_id is not None and not existing:
                    abort(404,description='Member not found in this unit')
                if type(data.get('archived',False)) is not bool:
                    raise ValueError('Choose a valid membership state')
                values = member_values(conn,unit_id,data,existing)
                account_id=data.get('panel_user_id',existing['panel_user_id'] if existing else None)
                if account_id != (existing['panel_user_id'] if existing else None):
                    access(conn,unit_id,'staff')
                if account_id is not None:
                    if type(account_id) is not int or not conn.execute('SELECT 1 FROM users WHERE id=?',(account_id,)).fetchone():
                        raise ValueError('Choose an existing panel account, or leave the member unlinked')
                    unchanged=existing and existing['panel_user_id']==account_id
                    if not unchanged and not panel_admin() and not conn.execute('SELECT 1 FROM unit_staff WHERE unit_id=? AND user_id=?',(unit_id,account_id)).fetchone():
                        raise ValueError('Choose a staff account already assigned to this unit')
                    if conn.execute('SELECT 1 FROM unit_roster WHERE unit_id=? AND panel_user_id=? AND id!=?',(unit_id,account_id,member_id or 0)).fetchone():
                        raise ValueError('That panel account is already linked to a roster member in this unit')
                if existing:
                    conn.execute('UPDATE unit_roster SET '+','.join(f'{k}=?' for k in FIELDS)+',archived=?,panel_user_id=?,updated_at=? WHERE id=? AND unit_id=?',(*values.values(),int(data.get('archived',False)),account_id,time.time(),member_id,unit_id))
                else:
                    # Deleted record URLs must never resolve to a different person.
                    member_id=conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM (SELECT id FROM unit_roster UNION ALL SELECT id FROM unit_roster_deleted_ids)').fetchone()[0]
                    conn.execute('INSERT INTO unit_roster(id,unit_id,'+','.join(FIELDS)+',archived,panel_user_id,created_at,updated_at) VALUES('+','.join('?' for _ in range(len(FIELDS)+6))+')',(member_id,unit_id,*values.values(),int(data.get('archived',False)),account_id,time.time(),time.time()))
                if data.get('archived',False):
                    conn.execute('DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?',(unit_id,member_id))
                elif 'billet_id' in data:
                    assign_slot(conn,unit_id,member_id,data['billet_id'])
            g.audit_details = dict(unit_id=unit_id,member_id=member_id,billet_id=data.get('billet_id'),before={f:existing[f] for f in (*FIELDS,'archived','panel_user_id')} if existing else None,after=dict(values,archived=data.get('archived',False),panel_user_id=account_id))
            return jsonify(ok=True,id=member_id)
        except (ValueError,sqlite3.IntegrityError) as exc:
            return jsonify(ok=False,error='That UUID or panel account already has a roster record in this unit; edit or restore it instead' if isinstance(exc,sqlite3.IntegrityError) else str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/roster/<int:member_id>/delete')
    def unit_roster_delete(unit_id,member_id):
        data=request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                access(conn,unit_id,'staff')
                member=find_member(conn,unit_id,member_id)
                revision(conn,unit_id,data)
                if data.get('confirm_name')!=member['game_name']:
                    raise ValueError('Type the member’s game name exactly to confirm deletion')
                notes=conn.execute('SELECT count(*) FROM unit_member_notes WHERE unit_id=? AND member_id=?',(unit_id,member_id)).fetchone()[0]
                conn.execute('INSERT INTO unit_roster_deleted_ids VALUES(?)',(member_id,))
                conn.execute('DELETE FROM unit_member_notes WHERE unit_id=? AND member_id=?',(unit_id,member_id))
                conn.execute('DELETE FROM unit_primary_slots WHERE unit_id=? AND member_id=?',(unit_id,member_id))
                conn.execute('DELETE FROM unit_roster WHERE unit_id=? AND id=?',(unit_id,member_id))
            g.audit_details=dict(unit_id=unit_id,member_id=member_id,game_name=member['game_name'],deleted_notes=notes)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/units/<int:unit_id>/staff')
    def unit_staff_save(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                access(conn,unit_id,'staff')
                revision(conn,unit_id,data)
                user = conn.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(text(data.get('username'),'Username',32,True),)).fetchone()
                if not user:
                    raise ValueError('No matching panel account. Ask a panel administrator to create it first.')
                role, capabilities = data.get('role'),data.get('capabilities',[])
                if role != 'remove':
                    if not user['enabled']:
                        raise ValueError('Ask a panel administrator to enable this account first')
                    validate_staff(role,capabilities)
                protect_admin(conn,unit_id,user['id'],role)
                conn.execute('DELETE FROM unit_staff WHERE unit_id=? AND user_id=?',(unit_id,user['id']))
                if role != 'remove':
                    conn.execute('INSERT INTO unit_staff VALUES(?,?,?,?)',(unit_id,user['id'],role,json.dumps(capabilities)))
            g.audit_details = dict(unit_id=unit_id,username=user['username'],role=role,capabilities=capabilities)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/units/<int:unit_id>/health')
    def unit_health(unit_id):
        with db() as conn:
            access(conn,unit_id)
            links = [r['server_id'] for r in conn.execute('SELECT server_id FROM unit_servers WHERE unit_id=?',(unit_id,))]
        rows = []
        user=dict(g.user)
        for server_id in links:
            try:
                with api.operator_tools.selected(server_id):
                    pid = api.get_server_pid()
                    cpu,ram = api.get_cpu_ram(pid) if pid else (0,0)
                    rows.append(dict(id=server_id,running=bool(pid),cpu=cpu,ram_process=ram,can_open=bool(api.server_permissions(user,server_id))))
            except (ValueError,KeyError,api.ConfigReadError):
                rows.append(dict(id=server_id,unavailable=True))
        return jsonify(servers=rows)

    def export_cell(value):
        # Spreadsheet formulas must remain literal when the CSV is opened.
        return "'"+str(value) if str(value).lstrip().startswith(('=','+','-','@')) else str(value)

    @api.app.get('/api/units/<int:unit_id>/roster.csv')
    def unit_roster_export(unit_id):
        with db() as conn:
            access(conn,unit_id)
            unit=access(conn,unit_id)
            catalog=json.loads(unit['catalog'])
            rows = [dict(row) for row in conn.execute('SELECT * FROM unit_roster WHERE unit_id=? ORDER BY game_name COLLATE NOCASE',(unit_id,))]
            decorate_slots(conn,unit_id,rows)
        output = io.StringIO(newline=''); writer = csv.writer(output)
        writer.writerow((*FIELDS,'archived','primary_billet','primary_billet_path','next_rank','next_eligible_date','missing_qualifications'))
        for row in rows:
            result=promotion(row,catalog)
            writer.writerow([export_cell(row[f]) for f in (*FIELDS,'archived')]+[export_cell(row['billet_name']),export_cell(row['billet_path']),export_cell(result['next_rank']),result['next_date'],export_cell(';'.join(result['missing']))])
        return api.Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="unit-{unit_id}-roster.csv"'})

