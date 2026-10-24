// Version choices are shared by Add now and the additions-only queue.
window.chooseModVersions=conflicts=>new Promise(resolve=>{
  const dialog=document.createElement('dialog');dialog.className='mods-dialog mod-pin-dialog';dialog.setAttribute('aria-labelledby','mod-pin-title');
  dialog.innerHTML='<h3 id="mod-pin-title">A running server uses a pinned version</h3><p>Use the latest release, or match a pin below.</p><div data-choices></div><div class="mod-queue-footer"><button type="button" class="btn-logout" data-cancel>Cancel</button><button type="button" class="mod-primary" data-continue>Continue</button></div>';
  const selects=[];
  for(const conflict of conflicts){
    const label=document.createElement('label');label.className='mod-pin-choice';label.append(document.createTextNode(conflict.name));
    const select=document.createElement('select');select.append(new Option('Latest release',''));
    for(const option of conflict.versions)select.append(new Option(`Pin v${option.version} · ${option.servers.join(', ')}`,option.version));
    label.append(select);dialog.querySelector('[data-choices]').append(label);selects.push([conflict.modId,select]);
  }
  let done=false;function finish(value){if(done)return;done=true;dialog.close();dialog.remove();resolve(value);}
  dialog.querySelector('[data-cancel]').onclick=()=>finish(null);
  dialog.querySelector('[data-continue]').onclick=()=>finish(Object.fromEntries(selects.map(([id,select])=>[id,select.value])));
  dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null);});document.body.append(dialog);PanelUI.open(dialog);
});
window.postWithModVersionChoice=async(url,body)=>{
  let choices={...(body.version_choices||{})};
  for(;;){
    const result=await readJson(await postJson(url,{...body,version_choices:choices}));
    if(!result.needs_version_choice)return result;
    const selected=await window.chooseModVersions(result.conflicts);if(selected===null)return null;choices={...choices,...selected};
  }
};
(() => {
  const button=document.getElementById('mod-draft-open');
  const dialog=document.createElement('dialog');dialog.className='mods-dialog mod-queue-dialog';dialog.setAttribute('aria-labelledby','mod-queue-title');
  dialog.innerHTML='<h3 id="mod-queue-title">Review queue</h3><div class="card mod-queue-storage"><svg class="ui-icon" aria-hidden="true"><use href="/static/icons.svg#disk"></use></svg><div><div class="chart-value" data-bytes>—</div><div class="card-label">Estimated size of additions</div><small data-count></small></div></div><p class="feature-note" data-estimate-note></p><div class="mod-queue-list" data-rows></div><p role="status" data-status></p><div class="mod-queue-footer"><button type="button" class="btn-logout" data-cancel>Cancel</button><button type="button" class="mod-primary" data-apply>Add queued mods</button></div>';
  document.body.append(dialog);const el=selector=>dialog.querySelector(selector);let state=null,busy=false;
  const size=bytes=>bytes>=1e9?(bytes/1e9).toFixed(2)+' GB':(bytes/1e6).toFixed(1)+' MB';
  function render(){
    const rows=state.entries;el('[data-rows]').replaceChildren();let total=0,unknown=0;
    for(const mod of rows){
      const estimate=state.sizes[mod.modId.toUpperCase()];const known=estimate&&estimate.version===(mod.version||'')&&Number.isFinite(estimate.bytes)&&estimate.bytes>=0;
      if(known)total+=estimate.bytes;else unknown++;

    }
    PanelUI.modRows(el('[data-rows]'),rows,{sizes:state.sizes,remove:removeEntry});
    if(!rows.length)el('[data-rows]').textContent='No mods queued. Use Add to queue on Workshop cards.';
    el('[data-bytes]').textContent=size(total)+(unknown?' + unknown':'');el('[data-count]').textContent=`${rows.length} mod${rows.length===1?'':'s'} to add${unknown?' · '+unknown+' size'+(unknown===1?'':'s')+' unavailable':''}`;
    el('[data-estimate-note]').textContent='Workshop size estimate, including queued dependencies. Actual disk use varies with existing files and copy-on-write.';
    el('[data-apply]').disabled=busy||!rows.length;
  }
  async function load(){state=await readJson(await fetch('/api/mods/draft'));render();}
  function lock(value){busy=value;dialog.querySelectorAll('button').forEach(button=>button.disabled=value);if(!value&&state)render();}
  async function removeEntry(id){
    if(busy)return;lock(true);el('[data-status]').textContent='';
    try{await readJson(await postJson('/api/mods/draft/save',{revision:state.revision,mods:state.entries.filter(row=>row.modId!==id)}));await load();}
    catch(error){el('[data-status]').textContent=error.message;}finally{lock(false);}
  }
  const close=()=>{if(!busy)dialog.close();};el('[data-cancel]').onclick=close;dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  button.onclick=async()=>{state=null;el('[data-status]').textContent='Loading queue…';el('[data-rows]').replaceChildren();PanelUI.open(dialog);lock(true);try{await load();el('[data-status]').textContent='';}catch(error){el('[data-status]').textContent=error.message;}finally{lock(false);if(!state)el('[data-apply]').disabled=true;}};
  document.getElementById('workshop-queue-open').onclick=()=>button.click();
  el('[data-apply]').onclick=async()=>{
    if(busy||!state?.entries.length)return;lock(true);el('[data-status]').textContent='Adding queued mods…';
    try{
      const result=await window.postWithModVersionChoice('/api/mods/draft/apply',{revision:state.revision});
      if(result===null){el('[data-status]').textContent='No changes made.';return;}
      dialog.close();await fetchStatus();modEl('workshop-status').textContent=result.restart_required?'Queued mods added. Restart the server when ready to load them.':'Queued mods added. They will load on the next start.';
    }catch(error){el('[data-status]').textContent=error.message;}finally{lock(false);}
  };
})();
