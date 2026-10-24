"""Scenario browsing, scoped operation presets and player announcements."""
import json
import sqlite3
import time
from flask import g, jsonify, request
from config_editor import FIELDS, MANAGER_FIELDS, apply_changes, revision
from mod_metadata import scenario_preview
from mod_validation import normalize_mod_entry

# Portable gameplay settings only; identity, credentials, ports and saves stay local.
OPERATION_FIELDS=sorted(path for path in MANAGER_FIELDS if path not in
    {'game.name','game.password','game.scenarioId'} and '.persistence.' not in path)


def value_at(config,path):
    for key in path.split('.'):
        if not isinstance(config,dict):return None
        config=config.get(key)
    return config


def install(api):
    from panel_features import MUTATIONS
    MUTATIONS.update(scenario_choose='configure',operation_save='mods',operation_apply='mods',operation_delete='mods',player_announcement='admin_config')
    api.PANEL_WIDE_ENDPOINTS.discard('presets_delete')
    with api.server_registry.connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS operation_presets (
            id INTEGER PRIMARY KEY, server_id TEXT NOT NULL, name TEXT NOT NULL,
            settings TEXT NOT NULL, mods TEXT NOT NULL, updated REAL NOT NULL,
            actor TEXT NOT NULL, UNIQUE(server_id,name))''')
        if 'legacy_id' not in {row['name'] for row in conn.execute('PRAGMA table_info(operation_presets)')}:
            conn.execute('ALTER TABLE operation_presets ADD COLUMN legacy_id INTEGER')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS preset_legacy_source ON operation_presets(legacy_id) WHERE legacy_id IS NOT NULL')
        conn.execute('BEGIN IMMEDIATE')
        # Keep the old table as a recovery copy; all active reads/writes use this table.
        for old in conn.execute('SELECT * FROM presets').fetchall():
            if conn.execute('SELECT 1 FROM operation_presets WHERE legacy_id=?',(old['id'],)).fetchone():continue
            chosen={'game.scenarioId':old['scenario_id']} if old['scenario_id'] else {}
            conn.execute('INSERT INTO operation_presets(server_id,name,settings,mods,updated,actor,legacy_id) VALUES(?,?,?,?,?,?,?)',
                ('*legacy*',old['name'],json.dumps(chosen),old['mods'],old['updated_at'],old['updated_by'],old['id']))


    def server_id():return api.selected_instance().id if api.selected_instance() else ''
    def allowed(chosen):return 'mods' in g.permissions and (not chosen or 'configure' in g.permissions)
    def settings(config):return {path:value_at(config,path) for path in OPERATION_FIELDS+['game.scenarioId']}
    def preset(identity):
        with api.server_registry.connect() as conn:
            row=conn.execute("SELECT * FROM operation_presets WHERE server_id IN (?, '*legacy*') AND id=?",(server_id(),identity)).fetchone()
        if not row:raise ValueError('Operation preset not found on this server')
        return dict(row)

    @api.app.get('/api/clone-source')
    def clone_source():
        if 'users' not in g.panel_permissions:return jsonify(ok=False,error='Panel administrator access required'),403
        config=api.read_config();game=config['game'];instance=api.selected_instance()
        return jsonify(ok=True,name=game.get('name','Server'),max_players=game.get('maxPlayers',64),
            max_fps=instance.max_fps if instance else api.server_registry.existing_max_fps(api._cfg.get('MAX_FPS','')),
            scenario=game.get('scenarioId',''),mod_count=len(game.get('mods',[])))

    @api.app.get('/api/scenarios/gallery')
    def scenario_gallery():
        config=api.read_config();missions,diagnostics=api.all_scenarios()
        mods=config['game'].get('mods',[])
        configured={str(row.get('modId','')).upper() for row in mods}
        images={str(row.get('modId','')).upper():api._mod_metadata.get(str(row.get('modId','')).upper()) for row in mods}
        rows=[]
        for mission in missions:
            row=dict(mission)
            row.update(scenario_preview(images,mission['id'],mods))
            owner=mission.get('owner_mod')
            row['needs_mod']=bool(owner and owner not in configured)
            if owner:
                image=api._mod_metadata.get(owner)
                row.update(thumbnail=image.get('thumbnail'),status=image.get('status'))
            rows.append(row)
        return jsonify(ok=True,scenarios=rows,current=config['game'].get('scenarioId'),revision=revision(config),diagnostics=diagnostics)

    @api.app.post('/api/scenarios/choose')
    def scenario_choose():
        config=api.read_config();data=request.get_json()
        if data.get('revision')!=revision(config):return jsonify(ok=False,error='Configuration changed. Refresh the gallery first.'),409
        mission=next((row for row in api.all_scenarios_cached() if row['id']==data.get('scenario')),None)
        if mission is None:
            return jsonify(ok=False,error='Scenario is no longer listed. Rescan installed scenarios.'),400
        owner=mission.get('owner_mod')
        if owner and not any(str(row.get('modId','')).upper()==owner for row in config['game'].get('mods',[])):
            if 'mods' not in g.permissions:return jsonify(ok=False,error='Mod permission is required to add this scenario’s Workshop mod'),403
            entry=normalize_mod_entry({'modId':owner,'name':str(mission.get('source',''))[:200]})
            if entry is None:return jsonify(ok=False,error='Invalid owning mod metadata. Rescan installed scenarios.'),400
            config['game'].setdefault('mods',[]).append(entry)
        api.write_config(apply_changes(config,{'game.scenarioId':data['scenario']}))
        g.audit_details={'scenario':data['scenario']}
        return jsonify(ok=True,restart_required=bool(api.get_server_pid()))

    @api.app.get('/api/players/sessions')
    def player_sessions():
        try:
            search=request.args.get('q','').strip();before=int(request.args.get('before',0))
            if len(search)>80 or not 0<=before<=2**63-1:raise ValueError('Invalid session filter')
            rows=api.operator_tools.store.sessions(server_id(),search,before)
            now=time.time()
            return jsonify(ok=True,sessions=[dict(row,duration=max(0,row['last_seen']-row['joined']),stale=row['ended'] is None and now-row['last_seen']>90) for row in rows[:50]],next_cursor=rows[49]['id'] if len(rows)>50 else None)
        except ValueError as exc:return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/presets',endpoint='presets_list')
    @api.app.get('/api/operations')
    def operation_list():
        with api.server_registry.connect() as conn:
            rows=conn.execute("SELECT * FROM operation_presets WHERE server_id IN (?, '*legacy*') ORDER BY name",(server_id(),)).fetchall()
        current=api.read_config()
        return jsonify(ok=True,presets=[dict(row,settings=json.loads(row['settings']),mods=json.loads(row['mods']),active=all(value_at(current,path)==value for path,value in json.loads(row['settings']).items()) and json.loads(row['mods'])==current['game'].get('mods',[])) for row in rows])

    @api.app.post('/api/presets',endpoint='presets_save')
    @api.app.post('/api/operations/save')
    def operation_save():
        data=request.get_json();name=data.get('name','');kind=data.get('kind','scenario_mods' if request.endpoint=='presets_save' else 'operation')
        if kind not in ('mods','scenario_mods','operation'):return jsonify(ok=False,error='Choose preset contents'),400
        if not allowed({} if kind=='mods' else {'scenario':True}):return jsonify(ok=False,error='Your account cannot save these preset contents'),403
        if not isinstance(name,str) or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):
            return jsonify(ok=False,error='Enter a preset name of 1–80 printable characters'),400
        config=api.read_config();chosen=settings(config) if kind=='operation' else {'game.scenarioId':config['game'].get('scenarioId')} if kind=='scenario_mods' else {}
        try:
            apply_changes(config,chosen)
            mods=config['game'].get('mods',[])
            if not isinstance(mods,list) or any(normalize_mod_entry(row) is None for row in mods):raise ValueError('Repair the active mod list before saving an operation')
            with api.server_registry.connect() as conn:
                if data.get('id') is not None:
                    changed=conn.execute("UPDATE operation_presets SET name=?,settings=?,mods=?,updated=?,actor=? WHERE id=? AND server_id IN (?, '*legacy*') AND updated=?",
                        (name.strip(),json.dumps(chosen),json.dumps(mods),time.time(),g.user['username'],data['id'],server_id(),data.get('updated')))
                    if not changed.rowcount:return jsonify(ok=False,error='Preset changed. Refresh before overwriting.'),409
                else:conn.execute('INSERT INTO operation_presets(server_id,name,settings,mods,updated,actor) VALUES(?,?,?,?,?,?)',(server_id(),name.strip(),json.dumps(chosen),json.dumps(mods),time.time(),g.user['username']))
            g.audit_details={'operation':name.strip()}
            return jsonify(ok=True)
        except sqlite3.IntegrityError:return jsonify(ok=False,error='A preset with that name already exists on this server'),409
        except ValueError as exc:return jsonify(ok=False,error=str(exc)),400

    @api.app.get('/api/operations/<int:identity>/preview')
    def operation_preview(identity):
        try:
            row=preset(identity);config=api.read_config();chosen=json.loads(row['settings'])
            current={mod['modId'].upper():mod for mod in config['game'].get('mods',[])}
            target={mod['modId'].upper():mod for mod in json.loads(row['mods'])}
            sizes={}
            for key,mod in target.items():
                if key in current:continue
                info=api._mod_metadata.get(key);version=mod.get('version') or info.get('current_version','')
                sizes[key]=dict(bytes=info.get('sizes',{}).get(version),version=mod.get('version',''))
            return jsonify(ok=True,sizes=sizes,id=identity,name=row['name'],updated=row['updated'],revision=revision(config),
                changes=[dict(path=path,label=FIELDS[path]['label'],before=value_at(config,path),after=value) for path,value in chosen.items() if value_at(config,path)!=value],
                added=[mod for key,mod in target.items() if key not in current],removed=[mod for key,mod in current.items() if key not in target],
                edited=[dict(before=current[key],after=mod) for key,mod in target.items() if key in current and current[key]!=mod])
        except ValueError as exc:return jsonify(ok=False,error=str(exc)),404

    @api.app.post('/api/presets/apply',endpoint='presets_apply')
    @api.app.post('/api/operations/apply')
    def operation_apply():
        try:
            data=request.get_json();row=preset(data.get('id'));config=api.read_config();chosen=json.loads(row['settings'])
            if not allowed(chosen):return jsonify(ok=False,error='Mod and configuration permissions required for these contents'),403
            if data.get('revision')!=revision(config) or data.get('updated')!=row['updated']:
                return jsonify(ok=False,error='Configuration or preset changed. Preview again.'),409
            if len(chosen)>1 and api.get_server_pid():return jsonify(ok=False,error='Stop the server before switching operations. Start it afterward when ready.'),409
            if api.software_manager.busy():return jsonify(ok=False,error='Wait for the software job to finish.'),409
            mods,conflicts=api.resolve_mod_version_choices(json.loads(row['mods']),config['game'].get('mods',[]),data.get('version_choices',{}))
            if conflicts:return jsonify(ok=True,needs_version_choice=True,conflicts=conflicts)
            config=apply_changes(config,chosen);config['game']['mods']=mods;api.write_config(config)
            g.audit_details={'operation':row['name']}
            return jsonify(ok=True,restart_required=bool(api.get_server_pid()))
        except ValueError as exc:return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/presets/delete',endpoint='presets_delete')
    @api.app.post('/api/operations/delete')
    def operation_delete():
        if 'mods' not in g.permissions:return jsonify(ok=False,error='Mod permission required'),403
        data=request.get_json()
        with api.server_registry.connect() as conn:
            row=conn.execute("SELECT legacy_id FROM operation_presets WHERE server_id IN (?, '*legacy*') AND id=? AND updated=?",(server_id(),data.get('id'),data.get('updated'))).fetchone()
            if row and row['legacy_id'] is not None:conn.execute('DELETE FROM presets WHERE id=?',(row['legacy_id'],))
            result=conn.execute("DELETE FROM operation_presets WHERE server_id IN (?, '*legacy*') AND id=? AND updated=?",(server_id(),data.get('id'),data.get('updated')))
        if not result.rowcount:return jsonify(ok=False,error='Preset changed or was removed. Refresh the list.'),409
        return jsonify(ok=True)

    @api.app.post('/api/players/announcement')
    def player_announcement():
        data=request.get_json();text=data.get('message','');mode=data.get('mode','now');minutes=data.get('minutes',15)
        if not isinstance(text,str) or len(text)>220 or any(ord(c)<32 for c in text) or mode!='restart' and not text.strip():
            return jsonify(ok=False,error='Enter a message of 1–220 printable characters'),400
        if not isinstance(mode,str) or mode not in {'now','later','restart'} or type(minutes) is not int or not 1<=minutes<=1440:
            return jsonify(ok=False,error='Choose a delivery option and 1–1,440 minutes'),400
        try:
            if mode=='now':
                if not api.get_server_pid():raise ValueError('Server is offline')
                api.operator_tools.broadcast(text.strip())
                g.audit_details={'delivery':'now','message':text.strip()}
                return jsonify(ok=True,message='Message sent through RCON. Check in-game delivery.')
            if not api.operator_tools.store.heartbeat():raise ValueError('The scheduler is unavailable. Start the Linux panel service first.')
            if mode=='restart' and minutes<6:raise ValueError('Allow at least 6 minutes for restart warnings')
            if mode=='restart' and not api.get_server_pid():raise ValueError('Server is offline; start it before scheduling a warned restart')
            schedule_id=api.operator_tools.store.create(server_id(),g.user['id'],dict(name='Warned restart' if mode=='restart' else 'Announcement: '+text.strip()[:60],action='restart' if mode=='restart' else 'broadcast',run_at=time.time()+minutes*60+1,broadcast=text.strip() if mode=='later' else ''))
            g.audit_details={'schedule_id':schedule_id,'delivery':mode}
            return jsonify(ok=True,message='Scheduled with automatic 5-minute and 1-minute warnings.' if mode=='restart' else 'Announcement scheduled.',schedule_id=schedule_id)
        except (ValueError,OSError) as exc:return jsonify(ok=False,error=str(exc)),409
