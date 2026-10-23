(() => {
  const button=document.getElementById('mod-draft-open');
  const dialog=document.createElement('dialog');dialog.className='mods-dialog';
  dialog.innerHTML='<div class="mods-dialog-heading"><h3>Review mod queue</h3><button type="button" class="btn-logout" data-close>Close</button></div><p>Queued mods and their known dependencies are saved separately. Ordinary mod actions still change the active configuration. Applying requires a stopped server; downloaded files are retained.</p><p data-summary></p><p data-storage></p><ul data-review></ul><div data-rows></div><button type="button" class="btn-logout" data-add>Add draft mod</button><p data-status role="status"></p><div class="mods-dialog-actions"><button type="button" class="btn-logout" data-save>Save draft</button><button type="button" class="btn-logout" data-discard>Discard draft</button><button type="button" class="btn-save" data-apply>Apply saved draft</button></div>';
  document.body.append(dialog);
  const el=selector=>dialog.querySelector(selector);let state,dirty=false,busy=false;
  const status=text=>el('[data-status]').textContent=text;
  const collect=()=>Array.from(el('[data-rows]').children,row=>Object.fromEntries(Array.from(row.querySelectorAll('input'),input=>[input.name,input.value])));
  function summarize(){
    const rows=collect(), current=new Map(state.current.map(row=>[row.modId,row]));
    const ids=new Set(rows.map(row=>row.modId.toUpperCase()));
    const added=rows.filter(row=>!current.has(row.modId.toUpperCase())).length;
    const removed=state.current.filter(row=>!ids.has(row.modId)).length;
    const changed=rows.filter(row=>current.has(row.modId.toUpperCase())&&['name','version'].some(key=>(row[key]||'')!==(current.get(row.modId.toUpperCase())[key]||''))).length;
    const review=el('[data-review]');review.replaceChildren();
    for(const old of state.current){const next=rows.find(row=>row.modId.toUpperCase()===old.modId);if(!next||['name','version'].some(key=>(next[key]||'')!==(old[key]||''))){const item=document.createElement('li');item.textContent=!next?`Remove: ${old.name||old.modId}`:`Edit: ${old.name||old.modId} → ${next.name||next.modId} (${old.version||'latest'} → ${next.version||'latest'})`;review.append(item);}}
    for(const row of rows.filter(row=>!current.has(row.modId.toUpperCase()))){const item=document.createElement('li');const estimate=state.draft?.sizes?.[row.modId.toUpperCase()];item.textContent=`Add: ${row.name||row.modId} (${row.version||'latest'}) · ${estimate&&estimate.version===(row.version||'')&&Number.isFinite(estimate.bytes)&&estimate.bytes>=0?(estimate.bytes/1e6).toFixed(1)+' MB estimated':'size unknown'}`;review.append(item);}
    const additions=rows.filter(row=>!current.has(row.modId.toUpperCase()));let known=0,unknown=0;
    for(const row of additions){const size=state.draft?.sizes?.[row.modId.toUpperCase()];if(size&&size.version===(row.version||'')&&Number.isFinite(size.bytes)&&size.bytes>=0)known+=size.bytes;else unknown++;}
    el('[data-storage]').textContent=`Additions: ${(known/1e9).toFixed(2)} GB estimated from Workshop metadata${unknown?` + ${unknown} mod(s) with unknown size`:''}. Includes queued dependencies once. This is a logical size estimate, not measured disk use or download traffic; existing downloads and copy-on-write may reduce space needed. Updates, extraction and temporary files may need extra space. Removals do not delete files.`;
    el('[data-summary]').textContent=`${rows.length} draft mods · ${added} added · ${removed} removed · ${changed} edited`;
  }
  function add(row={}){
    const line=document.createElement('div');line.className='mod-draft-row';
    for(const [name,label] of [['modId','Workshop ID'],['name','Mod name'],['version','Version (blank = latest)']]){
      const input=document.createElement('input');input.name=name;input.value=row[name]||'';input.placeholder=label;input.setAttribute('aria-label',label);
      input.oninput=()=>{dirty=true;summarize();};line.append(input);
    }
    const remove=document.createElement('button');remove.type='button';remove.className='btn-logout';remove.textContent='Remove';remove.onclick=()=>{line.remove();dirty=true;summarize();};line.append(remove);el('[data-rows]').append(line);
  }
  async function load(){state=await readJson(await fetch('/api/mods/draft'));el('[data-rows]').replaceChildren();(state.draft?.mods||state.current).forEach(add);dirty=false;summarize();status(state.draft?'Saved draft loaded.':'No saved draft. Start with the active mod list.');}
  function close(){if(!busy&&(!dirty||confirm('Discard unsaved draft edits?')))dialog.close();}
  el('[data-close]').onclick=close;dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  el('[data-add]').onclick=()=>{add();dirty=true;summarize();};
  button.onclick=async()=>{dialog.showModal();try{await load();}catch(error){status(error.message);}};
  document.getElementById('workshop-queue-open').onclick=()=>button.click();
  async function action(kind){
    if(busy||!state)return;
    if(kind==='apply'&&dirty){status('Save your draft edits before applying.');return;}
    if(kind==='discard'&&!confirm('Discard this mod draft?'))return;
    if(kind==='apply'&&!confirm('Apply this saved draft to the stopped server? Review the added, removed and edited rows first.'))return;
    busy=true;dialog.querySelectorAll('button,input').forEach(node=>node.disabled=true);
    try{
      await readJson(await postJson('/api/mods/draft/'+kind,{revision:state.draft?.updated??null,...(kind==='save'?{mods:collect()}:{})}));
      if(kind==='apply'){dirty=false;location.reload();return;}
      await load();if(kind==='save')status('Draft saved. Active configuration is unchanged.');
    }catch(error){status(error.message);}finally{busy=false;dialog.querySelectorAll('button,input').forEach(node=>node.disabled=false);}
  }
  for(const kind of ['save','apply','discard'])el('[data-'+kind+']').onclick=()=>action(kind);
})();
