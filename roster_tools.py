"""Qualification records, member timelines and explicit roster change previews."""
from datetime import date
import hashlib
import json
import time

from flask import abort, g, jsonify, request

from units import text


def install(api, db, access, revision, promotion, decorate_slots, assign_slot, structure_rows, endpoints):
    def state(conn, unit_id, member_id):
        row = conn.execute('SELECT * FROM unit_roster WHERE unit_id=? AND id=?', (unit_id, member_id)).fetchone()
        if not row:
            abort(404, description='Member not found in this unit')
        member = dict(row)
        decorate_slots(conn, unit_id, [member])
        return {key: member[key] for key in ('id', 'game_name', 'rank', 'rank_track', 'last_promo', 'status', 'archived', 'certificates', 'billet_id', 'billet_path')}

    def author(conn, unit_id):
        row = conn.execute('SELECT game_name FROM unit_roster WHERE unit_id=? AND panel_user_id=?', (unit_id, g.user['id'])).fetchone()
        return row['game_name'] if row else g.user['username']

    def history(conn, unit_id, member_id, kind, before, after, reason='', actor=None):
        conn.execute('INSERT INTO unit_roster_history(unit_id,member_id,kind,actor,created_at,before_value,after_value,reason) VALUES(?,?,?,?,?,?,?,?)',
                     (unit_id, member_id, kind, actor if actor is not None else author(conn, unit_id), time.time(), json.dumps(before), json.dumps(after), reason))

    def award_date(value, allow_unknown=False):
        if allow_unknown and value in ('', None):
            return None
        try:
            parsed = date.fromisoformat(value)
            if parsed > date.today():
                raise ValueError()
            return parsed.isoformat()
        except (ValueError, TypeError):
            raise ValueError('Choose an award date on or before today') from None

    def record_change(conn, unit_id, member_id, before, data=None):
        data = data or {}
        after = state(conn, unit_id, member_id)
        reason = text(data.get('history_reason', ''), 'Change note', 1000)
        if before is None:
            history(conn, unit_id, member_id, 'created', None, after, reason)
        previous = before or {}
        for kind, keys in [('rank', ('rank_track', 'rank', 'last_promo')), ('billet', ('billet_id', 'billet_path')), ('status', ('status', 'archived'))]:
            old = {k: previous.get(k) for k in keys}
            new = {k: after[k] for k in keys}
            if before is not None and old != new:
                history(conn, unit_id, member_id, kind, old, new, reason)
        held = {c for c in after['certificates'].split(';') if c}
        old_held = {c for c in previous.get('certificates', '').split(';') if c}
        for certificate in sorted(old_held - held):
            row = conn.execute('SELECT * FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?', (unit_id, member_id, certificate)).fetchone()
            history(conn, unit_id, member_id, 'qualification_revoked', dict(row) if row else {'certificate': certificate}, None, reason)
            conn.execute('DELETE FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?', (unit_id, member_id, certificate))
        for certificate in sorted(held - old_held):
            awarded_on = award_date(data.get('qualification_awarded_on') or date.today().isoformat())
            notes = text(data.get('qualification_notes', reason), 'Award notes', 1000)
            issuer = text(data.get('qualification_issuer', author(conn, unit_id)), 'Issuing staff name', 120) or None
            conn.execute('INSERT INTO unit_qualification_awards VALUES(?,?,?,?,?,?)', (unit_id, member_id, certificate, awarded_on, issuer, notes))
            history(conn, unit_id, member_id, 'qualification_granted', None, dict(certificate=certificate, awarded_on=awarded_on, issuer=issuer, notes=notes), reason)

        api.record_unit_strength(conn,unit_id,before,after)

    api.roster_state = state
    api.record_roster_change = record_change
    with db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS unit_qualification_awards (
                unit_id INTEGER NOT NULL, member_id INTEGER NOT NULL, certificate TEXT NOT NULL,
                awarded_on TEXT, issuer TEXT, notes TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(unit_id,member_id,certificate));
            CREATE TABLE IF NOT EXISTS unit_roster_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
                created_at REAL NOT NULL, before_value TEXT NOT NULL,
                after_value TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS unit_roster_history_member ON unit_roster_history(unit_id,member_id,id);
        ''')
        conn.execute('BEGIN IMMEDIATE')
        # Existing data is a baseline, not evidence of when or by whom it was awarded.
        for member in conn.execute('SELECT id,unit_id,certificates FROM unit_roster').fetchall():
            if not conn.execute('SELECT 1 FROM unit_roster_history WHERE unit_id=? AND member_id=? LIMIT 1', (member['unit_id'], member['id'])).fetchone():
                history(conn, member['unit_id'], member['id'], 'baseline', None, state(conn, member['unit_id'], member['id']), 'Existing record at upgrade; earlier changes and award dates are unknown.', actor='System')
            for certificate in filter(None, member['certificates'].split(';')):
                conn.execute('INSERT OR IGNORE INTO unit_qualification_awards VALUES(?,?,?,NULL,NULL,?)', (member['unit_id'], member['id'], certificate, 'Existing qualification; original date and issuer unknown.'))

    names = {'unit_roster_tools', 'unit_roster_timeline', 'unit_qualification_save', 'unit_member_promote', 'unit_roster_bulk_preview', 'unit_roster_bulk_apply'}
    endpoints.update(names); api.PANEL_WIDE_ENDPOINTS.update(names)
    from panel_features import MUTATIONS
    MUTATIONS.update({name: 'view' for name in ('unit_qualification_save', 'unit_member_promote', 'unit_roster_bulk_apply')})

    @api.app.get('/api/units/<int:unit_id>/roster-tools')
    def unit_roster_tools(unit_id):
        with db() as conn:
            unit = access(conn, unit_id)
            awards = [dict(r) for r in conn.execute('SELECT * FROM unit_qualification_awards WHERE unit_id=? ORDER BY member_id,certificate', (unit_id,))]
            actor_name=author(conn,unit_id)
        return jsonify(awards=awards, revision=unit['revision'], today=date.today().isoformat(),actor=actor_name)

    @api.app.get('/api/units/<int:unit_id>/roster/<int:member_id>/timeline')
    def unit_roster_timeline(unit_id, member_id):
        try:
            before = int(request.args.get('before', '0'))
            if not 0 <= before <= 9223372036854775807:
                raise ValueError()
        except ValueError:
            return jsonify(ok=False, error='Choose a valid timeline cursor'), 400
        kind=request.args.get('kind','all')
        if kind not in ('all','rank','billet','qualification','status'):
            return jsonify(ok=False,error='Choose a valid timeline filter'),400
        with db() as conn:
            access(conn, unit_id); state(conn, unit_id, member_id)
            rows = [dict(r) for r in conn.execute("SELECT * FROM unit_roster_history WHERE unit_id=? AND member_id=? AND (?=0 OR id<?) AND (?='all' OR kind IN ('baseline','created') OR kind=? OR (?='qualification' AND kind LIKE 'qualification_%')) ORDER BY id DESC LIMIT 51", (unit_id, member_id, before, before,kind,kind,kind))]
        for row in rows:
            row['before_value'] = json.loads(row['before_value']); row['after_value'] = json.loads(row['after_value'])
        return jsonify(entries=rows[:50], next_before=rows[49]['id'] if len(rows) > 50 else None)

    @api.app.post('/api/units/<int:unit_id>/roster/<int:member_id>/qualifications')
    def unit_qualification_save(unit_id, member_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); unit = access(conn, unit_id, 'roster'); revision(conn, unit_id, data)
                before = state(conn, unit_id, member_id)
                certificate = text(data.get('certificate'), 'Qualification', 80, True)
                if certificate not in json.loads(unit['catalog']).get('certificates', []):
                    raise ValueError('Choose a qualification from this unit’s catalog')
                held = set(filter(None, before['certificates'].split(';')))
                action = data.get('action')
                reason = text(data.get('reason', ''), 'Reason', 1000, action == 'revoke')
                if action == 'grant':
                    if certificate in held:
                        raise ValueError('Already held; edit the award details instead')
                    held.add(certificate)
                elif action == 'revoke':
                    if certificate not in held:
                        raise ValueError('This member does not hold that qualification')
                    held.remove(certificate)
                elif action == 'update':
                    if certificate not in held:
                        raise ValueError('Grant the qualification before editing its details')
                    old = conn.execute('SELECT * FROM unit_qualification_awards WHERE unit_id=? AND member_id=? AND certificate=?', (unit_id, member_id, certificate)).fetchone()
                    awarded_on = award_date(data.get('awarded_on'), allow_unknown=True)
                    notes = text(data.get('notes', ''), 'Award notes', 1000)
                    issuer = text(data.get('issuer', old['issuer'] or ''), 'Issuing staff name', 120) or None
                    conn.execute('UPDATE unit_qualification_awards SET awarded_on=?,notes=?,issuer=? WHERE unit_id=? AND member_id=? AND certificate=?', (awarded_on, notes, issuer, unit_id, member_id, certificate))
                    if (old['awarded_on'],old['issuer'],old['notes']) != (awarded_on,issuer,notes):
                        history(conn, unit_id, member_id, 'qualification_updated', dict(old), dict(certificate=certificate, awarded_on=awarded_on, issuer=issuer, notes=notes), reason)
                else:
                    raise ValueError('Choose grant, revoke or update')
                if action != 'update':
                    conn.execute('UPDATE unit_roster SET certificates=?,updated_at=? WHERE unit_id=? AND id=?', (';'.join(sorted(held)), time.time(), unit_id, member_id))
                    record_change(conn, unit_id, member_id, before, dict(history_reason=reason, qualification_awarded_on=data.get('awarded_on'), qualification_notes=data.get('notes', ''),qualification_issuer=data.get('issuer',author(conn,unit_id))))
                api.sync_unit_event_roster(conn, unit_id)
            g.audit_details = dict(unit_id=unit_id, member_id=member_id, qualification=certificate, change=action)
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post('/api/units/<int:unit_id>/roster/<int:member_id>/promote')
    def unit_member_promote(unit_id, member_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); unit = access(conn, unit_id, 'roster'); revision(conn, unit_id, data)
                member = conn.execute('SELECT * FROM unit_roster WHERE unit_id=? AND id=?', (unit_id, member_id)).fetchone()
                if not member:
                    abort(404, description='Member not found in this unit')
                ready = promotion(dict(member), json.loads(unit['catalog']))
                if not ready['eligible'] or data.get('confirm_rank') != ready['next_rank'] or data.get('confirm_date') != date.today().isoformat():
                    raise ValueError('The rank, promotion date or eligibility changed. Reload the review queue before confirming.')
                reason = text(data.get('reason'), 'Promotion review note', 1000, True)
                before = state(conn, unit_id, member_id)
                conn.execute('UPDATE unit_roster SET rank=?,last_promo=?,updated_at=? WHERE unit_id=? AND id=?', (ready['next_rank'], date.today().isoformat(), time.time(), unit_id, member_id))
                record_change(conn, unit_id, member_id, before, dict(history_reason=reason))
                api.sync_unit_event_roster(conn, unit_id)
            g.audit_details = dict(unit_id=unit_id, member_id=member_id, change='manual promotion', before=before['rank'], after=ready['next_rank'])
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def bulk_plan(conn, unit_id, data):
        unit = access(conn, unit_id, 'roster')
        if type(data.get('revision')) is not int or data['revision'] != unit['revision']:
            abort(409, description='This unit changed. Reload the roster and preview again.')
        ids = data.get('members')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Select 1–500 distinct current members')
        action = data.get('action'); reason = text(data.get('reason'), 'Bulk change reason', 1000, True)
        changes = []
        for member_id in sorted(ids):
            before = state(conn, unit_id, member_id)
            if before['archived']:
                raise ValueError('Restore former members before applying bulk changes')
            changes.append(dict(member_id=member_id, name=before['game_name'], before=before, after=dict(before)))
        if action in ('grant', 'revoke'):
            certificate = text(data.get('certificate'), 'Qualification', 80, True)
            if certificate not in json.loads(unit['catalog']).get('certificates', []):
                raise ValueError('Choose a qualification from this unit’s catalog')
            if action == 'grant':
                award_date(data.get('awarded_on'))
            for change in changes:
                held = set(filter(None, change['before']['certificates'].split(';')))
                if action == 'grant':
                    held.add(certificate)
                else:
                    held.discard(certificate)
                change['after']['certificates'] = ';'.join(sorted(held))
        elif action == 'status':
            status = data.get('status')
            if status not in ('active', 'reserve', 'loa'):
                raise ValueError('Choose Active, Reserve or LOA')
            for change in changes:
                change['after']['status'] = status
        elif action in ('section', 'unassign'):
            nodes = structure_rows(conn, unit_id)
            available = []
            if action == 'section':
                target = data.get('section_id')
                if type(target) is not int or not any(n['id'] == target and n['kind'] == 'section' for n in nodes):
                    raise ValueError('Choose a section in this unit')
                descendants = {target}
                for _ in range(7):
                    descendants.update(n['id'] for n in nodes if n['parent_id'] in descendants)
                billets = []
                def visit(parent_id):
                    for node in nodes:
                        if node['parent_id'] == parent_id:
                            if node['kind'] == 'billet':
                                billets.append(node)
                            else:
                                visit(node['id'])
                visit(target)
                occupied = {r[0] for r in conn.execute('SELECT billet_id FROM unit_primary_slots WHERE unit_id=?', (unit_id,))}
                available = [n for n in billets if n['id'] not in occupied]
                by_id = {n['id']: n for n in nodes}
            for change in changes:
                if action == 'section' and change['before']['billet_id'] in descendants:
                    continue
                billet_id = None; path = ''
                if action == 'section':
                    if not available:
                        raise ValueError('There are not enough open billets in the selected section. Add slots or select fewer members.')
                    billet = available.pop(0); billet_id = billet['id']; parts = [billet['name']]; parent = by_id.get(billet['parent_id'])
                    while parent:
                        parts.append(parent['name']); parent = by_id.get(parent['parent_id'])
                    path = ' / '.join(reversed(parts))
                change['after'].update(billet_id=billet_id, billet_path=path)
        else:
            raise ValueError('Choose qualification grant/revoke, status, section move or unassign')
        payload = dict(revision=unit['revision'], action=action, reason=reason, certificate=data.get('certificate'), awarded_on=data.get('awarded_on'), status=data.get('status'), section_id=data.get('section_id'), changes=changes)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return changes, digest

    @api.app.post('/api/units/<int:unit_id>/roster/bulk/preview')
    def unit_roster_bulk_preview(unit_id):
        try:
            with db() as conn:
                # One read transaction keeps the revision and proposed changes consistent.
                conn.execute('BEGIN'); changes, token = bulk_plan(conn, unit_id, request.get_json())
            return jsonify(ok=True, changes=changes, preview_token=token)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @api.app.post('/api/units/<int:unit_id>/roster/bulk/apply')
    def unit_roster_bulk_apply(unit_id):
        data = request.get_json()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE'); changes, token = bulk_plan(conn, unit_id, data)
                if data.get('preview_token') != token:
                    abort(409, description='The preview changed. Review a fresh preview before applying.')
                revision(conn, unit_id, data)
                for change in changes:
                    before = change['before']; after = change['after']; member_id = change['member_id']
                    if before == after:
                        continue
                    conn.execute('UPDATE unit_roster SET certificates=?,status=?,updated_at=? WHERE unit_id=? AND id=?', (after['certificates'], after['status'], time.time(), unit_id, member_id))
                    if before['billet_id'] != after['billet_id']:
                        assign_slot(conn, unit_id, member_id, after['billet_id'])
                    record_change(conn, unit_id, member_id, before, dict(history_reason=data['reason'], qualification_awarded_on=data.get('awarded_on')))
                api.sync_unit_event_roster(conn, unit_id)
            g.audit_details = dict(unit_id=unit_id, member_ids=[c['member_id'] for c in changes], change='bulk '+data['action'])
            return jsonify(ok=True, changed=sum(c['before'] != c['after'] for c in changes))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
