// Shared native-dialog behavior and change rows; feature permissions stay at callers.
window.PanelUI = {
  open(dialog) {
    if(!dialog.open)dialog.showModal();
    dialog.scrollTop=0;
    const heading=dialog.querySelector('h2,h3');
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
  },
  confirm(message, title='Confirm action') {
    if(document.querySelector('.panel-confirm[open]'))return Promise.resolve(false);
    return new Promise(resolve=>{
      const dialog=document.createElement('dialog');dialog.className='panel-confirm';dialog.setAttribute('aria-labelledby','panel-confirm-title');
      const heading=document.createElement('h2');heading.id='panel-confirm-title';heading.textContent=title;
      const text=document.createElement('p');text.textContent=message;
      const footer=document.createElement('div');footer.className='panel-dialog-footer';
      const cancel=document.createElement('button');cancel.type='button';cancel.className='btn-logout';cancel.textContent='Cancel';
      const accept=document.createElement('button');accept.type='button';accept.className='btn-save';accept.textContent='Confirm';
      let finished=false;const finish=value=>{if(finished)return;finished=true;dialog.close();dialog.remove();resolve(value);};
      cancel.onclick=()=>finish(false);accept.onclick=()=>finish(true);dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false);});
      footer.append(cancel,accept);dialog.append(heading,text,footer);document.body.append(dialog);dialog.showModal();cancel.focus();
    });
  },
  modChanges(before,after) {
    const old=new Map(before.map(row=>[row.modId.toUpperCase(),row])),next=new Map(after.map(row=>[row.modId.toUpperCase(),row]));const rows=[];
    for(const [id,mod] of next){const previous=old.get(id);if(!previous||JSON.stringify(previous)!==JSON.stringify(mod))rows.push({...mod,kind:previous?'edit':'add',beforeVersion:previous?.version||''});}
    for(const [id,mod] of old)if(!next.has(id))rows.push({...mod,kind:'remove'});
    return rows;
  },
  modRows(holder,rows,{remove,sizes={},summary=false}={}) {
    holder.replaceChildren();
    if(summary&&rows.length){
      const additions=rows.filter(row=>row.kind==='add'),removals=rows.filter(row=>row.kind==='remove'),edits=rows.filter(row=>row.kind==='edit');let bytes=0,unknown=0;
      for(const mod of additions){const size=sizes[mod.modId.toUpperCase()];if(size&&size.version===(mod.version||'')&&Number.isFinite(size.bytes)&&size.bytes>=0)bytes+=size.bytes;else unknown++;}
      const total=document.createElement('p');total.className='mod-change-summary';total.textContent=`${additions.length} additions · ${removals.length} removals · ${edits.length} edits${additions.length?' · '+(bytes/1e9).toFixed(2)+' GB estimated'+(unknown?' + '+unknown+' unknown sizes':''):''}`;holder.append(total);
    }
    for(const mod of rows){
      const row=document.createElement('div');row.className='mod-change-row';const info=document.createElement('div'),name=document.createElement('strong'),detail=document.createElement('small');name.textContent=mod.name||mod.modId;
      const version=mod.version?'Pinned v'+mod.version:'Latest';const estimate=sizes[mod.modId.toUpperCase()];
      detail.textContent=(mod.kind==='remove'?'Remove from configuration':mod.kind==='edit'?`${mod.beforeVersion||'Latest'} → ${version}`:'Add · '+version);
      if(estimate)detail.textContent+=' · '+(estimate.version===(mod.version||'')&&Number.isFinite(estimate.bytes)&&estimate.bytes>=0?(estimate.bytes/1e6).toFixed(1)+' MB estimated':'Size unknown');
      info.append(name,detail);row.append(info);
      if(remove){const action=document.createElement('button');action.type='button';action.className='btn-logout';action.textContent='Remove';action.setAttribute('aria-label','Remove '+(mod.name||mod.modId)+' from queue');action.onclick=()=>remove(mod.modId);row.append(action);}
      holder.append(row);
    }
    if(!rows.length)holder.textContent='No pending mod changes.';
  }
};
