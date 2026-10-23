"""Explicit mod-list drafts; active configuration stays untouched until applied."""
import json
import time
from pathlib import Path
from flask import g, jsonify, request
from mod_validation import normalize_mod_entry
from server_software import write_state


def install(api):
    from panel_features import MUTATIONS
    MUTATIONS.update(mod_draft_save='mods',mod_draft_apply='mods',mod_draft_discard='mods',mod_draft_queue='mods')

    def path():return Path(api._STATE_DIR)/'.mod-draft.json'
    def draft():
        try:return json.loads(path().read_text())
        except FileNotFoundError:return None

    @api.app.get('/api/mods/draft')
    def mod_draft_get():
        if 'mods' not in g.permissions:return jsonify(ok=False,error='Mod management permission required'),403
        current=api.read_config()['game'].get('mods',[])
        return jsonify(ok=True,current=current,draft=draft())

    @api.app.post('/api/mods/draft/save')
    def mod_draft_save():
        data=request.get_json(); rows=data.get('mods')
        if not isinstance(rows,list) or len(rows)>2000:return jsonify(ok=False,error='Provide at most 2,000 mods.'),400
        normalized=[normalize_mod_entry(row) for row in rows]
        if any(row is None for row in normalized) or len({row['modId'] for row in normalized})!=len(rows):
            return jsonify(ok=False,error='Invalid or duplicate mod IDs, names or versions.'),400
        existing=draft(); current=api.read_config()['game'].get('mods',[])
        if data.get('revision')!=(existing or {}).get('updated'):
            return jsonify(ok=False,error='Another staff member changed this draft. Reopen it.'),409
        write_state(path(),dict(base=existing['base'] if existing else current,mods=normalized,sizes=(existing or {}).get('sizes',{}),updated=time.time()))
        return jsonify(ok=True,draft=draft())

    @api.app.post('/api/mods/draft/queue')
    def mod_draft_queue():
        data=request.get_json();saved=draft()
        current=api.read_config()['game'].get('mods',[])
        if saved and saved['base']!=current:
            return jsonify(ok=False,error='Active mods changed. Review and discard the old queue before adding more.'),409
        try:
            asset=api.workshop.detail(data.get('modId',''))
            mods=(saved or {}).get('mods',current)
            instance=api.selected_instance()
            plan=api.workshop.preview(mods,(g.user['id'],instance.id if instance else ''),asset['modId'],'add',dependencies=True)
            if len(plan['mods'])>2000:raise ValueError('The queue cannot exceed 2,000 mods.')
            sizes=dict((saved or {}).get('sizes',{}))
            sizes[asset['modId']]={'bytes':asset['size'],'version':''}
            pending=list(asset['dependencies']);visited=0
            while pending:
                dependency=pending.pop();visited+=1
                if visited>1024:break
                identity=str((dependency.get('asset') or {}).get('id','')).upper()
                if identity:sizes[identity]={'bytes':dependency.get('totalFileSize'),'version':''}
                pending.extend(dependency.get('dependencies',[]))
            write_state(path(),dict(base=(saved or {}).get('base',current),mods=plan['mods'],sizes=sizes,updated=time.time()))
            return jsonify(ok=True,count=len(plan['mods']))
        except (ValueError,KeyError,TypeError) as exc:return jsonify(ok=False,error=str(exc)),400

    @api.app.post('/api/mods/draft/discard')
    def mod_draft_discard():
        if request.get_json().get('revision')!=(draft() or {}).get('updated'):
            return jsonify(ok=False,error='Draft changed. Reopen it before discarding.'),409
        path().unlink(missing_ok=True)
        return jsonify(ok=True)

    @api.app.post('/api/mods/draft/apply')
    def mod_draft_apply():
        saved=draft()
        if not saved or request.get_json().get('revision')!=saved['updated']:
            return jsonify(ok=False,error='Draft changed or no longer exists. Reopen it.'),409
        if api.software_manager.busy():return jsonify(ok=False,error='Wait for the server software job to finish.'),409
        if api.get_server_pid():return jsonify(ok=False,error='Stop the server before applying the draft. No automatic restart is performed.'),409
        config=api.read_config()
        if config['game'].get('mods',[])!=saved['base']:
            return jsonify(ok=False,error='Active mods changed since this draft was created. Discard it and start a new draft.'),409
        config['game']['mods']=saved['mods'];api.write_config(config)
        path().unlink(missing_ok=True)
        return jsonify(ok=True)
