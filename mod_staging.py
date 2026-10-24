"""An additions-only Workshop queue, with choices for pins on running servers."""
import copy
import json
import time
from pathlib import Path
from flask import g, jsonify, request
from mod_validation import normalize_mod_entry
from server_software import write_state


def install(api):
    from panel_features import MUTATIONS
    MUTATIONS.update(mod_draft_save='mods',mod_draft_apply='mods',mod_draft_queue='mods')

    def path():return Path(api._STATE_DIR)/'.mod-draft.json'
    def draft():
        try:return json.loads(path().read_text())
        except FileNotFoundError:return None
    def additions(saved,current):
        if not saved:return []
        existing={row['modId'].upper() for row in current}
        # Read older full-list drafts as additions only; never remove active mods.
        base={row['modId'].upper() for row in saved.get('base',[])}
        return [row for row in saved.get('entries',saved.get('mods',[])) if row['modId'].upper() not in existing|base]
    def save(entries,sizes,choices=None):
        if not entries:
            path().unlink(missing_ok=True);return None
        saved=dict(entries=entries,sizes=sizes,version_choices=choices if choices is not None else (draft() or {}).get('version_choices',{}),updated=time.time());write_state(path(),saved);return saved

    def resolve_versions(mods,current,choices):
        if not isinstance(choices,dict):raise ValueError('Invalid version choices')
        before={row['modId'].upper():row for row in current}
        candidates={row['modId'].upper():row for row in mods if not row.get('version') and before.get(row['modId'].upper())!=row}
        conflicts={};actor=g.user
        sources=[(server.id,server.name) for server in api.server_registry.list() if server.state=='ready']
        if not api.manager_mode:sources.append(('', 'Existing server'))
        for identity,name in sources:
            if not api.server_permissions(actor,identity):continue
            try:
                with api.operator_tools.selected(identity):
                    if not api.get_server_pid():continue
                    game=api.read_config()['game']
                    for row in game.get('mods',[]):
                        key=row['modId'].upper();version=row.get('version')
                        if key not in candidates or not version:continue
                        options=conflicts.setdefault(key,dict(modId=key,name=candidates[key].get('name') or key,versions={}))
                        options['versions'].setdefault(version,[]).append(game.get('name') or name)
            except (OSError,ValueError,api.ConfigReadError):continue
        missing=[];result=copy.deepcopy(mods)
        for key,conflict in conflicts.items():
            selected=choices.get(key)
            if selected is not None and not isinstance(selected,str):raise ValueError('Invalid selected version')
            if selected is None or selected and selected not in conflict['versions']:
                missing.append(dict(conflict,versions=[dict(version=version,servers=names) for version,names in conflict['versions'].items()]));continue
            if not isinstance(selected,str):raise ValueError('Invalid selected version')
            for row in result:
                if row['modId'].upper()==key:
                    if selected:row['version']=selected
                    else:row.pop('version',None)
        return result,missing
    api.resolve_mod_version_choices=resolve_versions

    @api.app.get('/api/mods/draft')
    def mod_draft_get():
        if 'mods' not in g.permissions:return jsonify(ok=False,error='Mod management permission required'),403
        saved=draft();entries=additions(saved,api.read_config()['game'].get('mods',[]));sizes=(saved or {}).get('sizes',{})
        return jsonify(ok=True,entries=entries,sizes=sizes,revision=(saved or {}).get('updated'))

    @api.app.post('/api/mods/draft/save')
    def mod_draft_save():
        data=request.get_json();saved=draft()
        if data.get('revision')!=(saved or {}).get('updated'):return jsonify(ok=False,error='Queue changed. Reopen it.'),409
        rows=data.get('mods');current=api.read_config()['game'].get('mods',[])
        if not isinstance(rows,list) or len(rows)>2000:return jsonify(ok=False,error='Invalid queue'),400
        normalized=[normalize_mod_entry(row) for row in rows]
        allowed={row['modId'].upper():row for row in additions(saved,current)}
        if any(row is None or allowed.get(row['modId'])!=row for row in normalized) or len({row['modId'] for row in normalized})!=len(rows):
            return jsonify(ok=False,error='Only queued additions can be removed here. Refresh the queue.'),400
        result=save(normalized,(saved or {}).get('sizes',{}))
        return jsonify(ok=True,revision=(result or {}).get('updated'))

    @api.app.post('/api/mods/draft/queue')
    def mod_draft_queue():
        data=request.get_json();saved=draft();current=api.read_config()['game'].get('mods',[])
        try:
            asset=api.workshop.detail(data.get('modId',''))
            if any(row['modId'].upper()==asset['modId'] for row in current):return jsonify(ok=True,already_configured=True)
            entries=additions(saved,current);mods=current+entries;instance=api.selected_instance()
            plan=api.workshop.preview(mods,(g.user['id'],instance.id if instance else ''),asset['modId'],'add',dependencies=True)
            choices=dict((saved or {}).get('version_choices',{}))
            supplied=data.get('version_choices',{})
            if not isinstance(supplied,dict):raise ValueError('Invalid version choices')
            choices.update(supplied)
            planned,conflicts=resolve_versions(plan['mods'],current,choices)
            if conflicts:return jsonify(ok=True,needs_version_choice=True,conflicts=conflicts)
            if len(planned)>2000:raise ValueError('The queue cannot exceed 2,000 mods.')
            existing={row['modId'].upper() for row in current}
            entries=[row for row in planned if row['modId'].upper() not in existing]
            sizes=dict((saved or {}).get('sizes',{}));sizes[asset['modId']]={'bytes':asset['size'],'version':''}
            for release in asset['versions']:
                if any(row['modId']==asset['modId'] and row.get('version')==release['version'] for row in entries):
                    sizes[asset['modId']]={'bytes':release.get('size'),'version':release['version']}
            pending=list(asset['dependencies']);visited=0
            while pending:
                dependency=pending.pop();visited+=1
                if visited>1024:break
                identity=str((dependency.get('asset') or {}).get('id','')).upper()
                if identity:sizes[identity]={'bytes':dependency.get('totalFileSize'),'version':''}
                pending.extend(dependency.get('dependencies',[]))
            result=save(entries,sizes,choices)
            return jsonify(ok=True,count=len(entries),revision=(result or {}).get('updated'))
        except (ValueError,KeyError,TypeError) as exc:return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/mods/draft/apply')
    def mod_draft_apply():
        saved=draft();data=request.get_json()
        if not saved or data.get('revision')!=saved['updated']:return jsonify(ok=False,error='Queue changed. Reopen it.'),409
        if api.software_manager.busy():return jsonify(ok=False,error='Wait for the server software job to finish.'),409
        config=api.read_config();current=config['game'].get('mods',[]);entries=additions(saved,current)
        try:
            supplied=data.get('version_choices',{})
            if not isinstance(supplied,dict):raise ValueError('Invalid version choices')
            choices={**saved.get('version_choices',{}),**supplied}
            mods,conflicts=resolve_versions(current+entries,current,choices)
        except ValueError as exc:return jsonify(ok=False,error=str(exc)),400
        if conflicts:return jsonify(ok=True,needs_version_choice=True,conflicts=conflicts)
        config['game']['mods']=mods;api.write_config(config);path().unlink(missing_ok=True)
        return jsonify(ok=True,restart_required=bool(api.get_server_pid()))
