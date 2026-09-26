// Compare snapshots, then apply only explicit selections.
const serverComparison = {data:null, signature:null, selected:{missing:new Set(),extra:new Set(),versions:new Set()}, stale:false, request:0, draft:null, source:'server', category:'missing', page:1};
const comparisonLabels = {missing:'Missing from your server', extra:'Extra on your server', versions:'Version differences'};
function comparisonStatus(message) { modEl('mods-compare-status').textContent=message; }
function setComparisonSource(source) {
  ++serverComparison.request;clearServerComparison();comparisonStatus('Paste a source mod list or choose an ArmaHQ server to compare.');
  serverComparison.source=source;
  ['server','json'].forEach(name=>modEl('mods-compare-source-'+name).setAttribute('aria-pressed',String(name===source)));
  modEl('mods-compare-search').hidden=source!=='server';modEl('mods-compare-json').hidden=source!=='json';
}
function clearServerComparison() {
  serverComparison.data=null;serverComparison.draft=null;
  Object.values(serverComparison.selected).forEach(set=>set.clear());updateComparisonButton();
  ['mods-compare-summary','mods-compare-note','mods-compare-tools'].forEach(id=>modEl(id).hidden=true);
  modEl('mods-compare-differences').replaceChildren();modEl('mods-compare-results').replaceChildren();
}
function selectedComparisonChanges() {
  return Object.fromEntries(Object.entries(serverComparison.selected).map(([kind,ids])=>[kind,[...ids]]));
}
function updateComparisonButton() {
  const counts=Object.values(serverComparison.selected).reduce((total,set)=>total+set.size,0);
  const button=modEl('mods-compare-review');
  button.textContent=counts?`Review ${counts} selected changes`:'Review selected changes';
  button.disabled=!can('mods') || !counts || serverComparison.stale || !serverComparison.data;
}
function invalidateServerComparison(signature) {
  if(!serverComparison.data || signature===serverComparison.signature)return;
  serverComparison.stale=true;
  comparisonStatus('Your configured mod list changed. Compare again before applying changes.');updateComparisonButton();
}
modEl('mods-compare-search').addEventListener('submit',async event=>{
  event.preventDefault();const query=modEl('mods-compare-query').value.trim();
  if(/^https?:\/\//i.test(query) || /^[0-9a-f-]{36}$/i.test(query))return compareServerMods(query);
  const request=++serverComparison.request,button=modEl('mods-compare-find');button.disabled=true;
  clearServerComparison();
  comparisonStatus('Searching ArmaHQ…');modEl('mods-compare-results').replaceChildren();
  try {
    const result=await getFeature('/api/mods/servers/search?q='+encodeURIComponent(query));
    if(request!==serverComparison.request)return;
    comparisonStatus(`${result.total} servers found.${result.total>30?' Showing the first 30; narrow your search to see others.':''}`);
    for(const server of result.servers){
      const row=document.createElement('div');row.className='mods-compare-result';
      const detail=document.createElement('div'),name=document.createElement('strong'),info=document.createElement('small');
      name.textContent=server.name;info.textContent=`${server.address} · ${server.players??'?'} players · ${server.modCount??'?'} mods`;
      detail.append(name,info);row.append(detail,modButton('Compare',()=>compareServerMods(server.id)));modEl('mods-compare-results').append(row);
    }
  }catch(error){if(request===serverComparison.request)comparisonStatus(error.message);}
  finally{button.disabled=false;}
});
modEl('mods-compare-json').addEventListener('submit',event=>{event.preventDefault();comparePastedMods();});
async function compareServerMods(reference) { return runModComparison(reference, null); }
async function comparePastedMods() { return runModComparison(null, modEl('mods-compare-json-input').value); }
async function runModComparison(reference,payload) {
  const request=++serverComparison.request;
  clearServerComparison();serverComparison.category='missing';serverComparison.page=1;modEl('mods-compare-filter').value='';
  const button=modEl(reference?'mods-compare-find':'mods-compare-json-button');button.disabled=true;
  comparisonStatus(reference?'Reading the server’s reported mod list…':'Comparing pasted JSON…');
  try {
    await fetchStatus();
    let data;
    if(reference)data=await getFeature('/api/mods/servers/compare?server='+encodeURIComponent(reference));
    else {
      const response=await postJson('/api/mods/compare-json',{payload});data=await response.json();
      if(!response.ok)throw new Error(data.error||'Could not compare JSON');
    }
    if(request!==serverComparison.request)return;
    serverComparison.data=data;serverComparison.signature=JSON.stringify(data.localMods);serverComparison.stale=false;
    if(reference)modEl('mods-compare-query').value=data.server.url;
    renderServerComparison();invalidateServerComparison(modLibrary.signature);
  }catch(error){if(request===serverComparison.request)comparisonStatus(error.message);}
  finally{button.disabled=false;}
}
function renderServerComparison() {
  const data=serverComparison.data;
  const summary=modEl('mods-compare-summary');summary.replaceChildren();summary.hidden=false;
  const heading=document.createElement('div');heading.className='mods-compare-source';
  const title=document.createElement(data.server.url?'a':'strong');title.textContent=data.server.name;
  if(data.server.url){title.href=data.server.url;title.target='_blank';title.rel='noopener noreferrer';}
  const detail=document.createElement('small');detail.textContent=`${data.server.address?data.server.address+' · ':''}${data.remoteCount} source mods · ${data.shared} shared`;
  heading.append(title,detail);summary.append(heading);
  for(const kind of ['missing','extra','versions']){
    const tile=document.createElement('div'),count=document.createElement('strong'),label=document.createElement('span');
    count.textContent=data[kind].length;label.textContent=comparisonLabels[kind];tile.append(count,label);summary.append(tile);
  }
  const date=data.server.updated,timestamp=typeof date==='number'?new Date(date*(date<1e12?1000:1)):date?new Date(date):null;
  const freshness=data.server.url?`${timestamp&&!isNaN(timestamp)?'ArmaHQ details updated '+timestamp.toLocaleString()+'.':'ArmaHQ update time unavailable.'} Data is cached for up to one minute.`:'Source: pasted JSON.';
  comparisonStatus(`Compared ${new Date(data.comparedAt*1000).toLocaleString()}. ${freshness} Selections expire after 15 minutes.`);
  modEl('mods-compare-note').hidden=false;
  modEl('mods-compare-note').textContent=(data.server.url?'ArmaHQ data may lag behind the server. ':'')+'“Latest” means your config has no version pin; it does not report the installed version. Adding a mod uses the source version when provided. Only your mod list changes; mods download when the game server starts.';
  modEl('mods-compare-tools').hidden=false;
  for(const kind of ['missing','extra','versions']){
    modEl('mods-compare-filter-'+kind).textContent=`${kind==='missing'?'Missing':kind==='extra'?'Extras':'Versions'} (${data[kind].length})`;
  }
  renderComparisonRows();
}
function filterComparison(category) { serverComparison.category=category;serverComparison.page=1;renderComparisonRows(); }
function searchComparison() { serverComparison.page=1;renderComparisonRows(); }
function renderComparisonRows() {
  const data=serverComparison.data;if(!data)return;
  const kind=serverComparison.category;
  ['missing','extra','versions'].forEach(k=>modEl('mods-compare-filter-'+k).setAttribute('aria-pressed',String(kind===k)));
  const query=modEl('mods-compare-filter').value.toLowerCase().trim();
  const rows=data[kind].filter(m=>`${m.name||''} ${m.modId}`.toLowerCase().includes(query)),pages=Math.max(1,Math.ceil(rows.length/20));
  serverComparison.page=Math.min(serverComparison.page,pages);const start=(serverComparison.page-1)*20;
  const container=modEl('mods-compare-differences');container.replaceChildren();
    const section=document.createElement('section');section.className='mods-compare-group';
    const heading=document.createElement('h4');heading.textContent=`${comparisonLabels[kind]} (${data[kind].length})`;section.append(heading);
    const note=document.createElement('p');note.className='feature-note';
    note.textContent=kind==='missing'?'Select only the mods you want to add.':kind==='extra'?'These may be intentional, or the source may have dropped them. Select only extras you want to remove.':'Select a row to match the source version, including pinning a mod currently set to Latest.';section.append(note);
    for(const mod of rows.slice(start,start+20)){
      const row=document.createElement('label');row.className='mods-update-row';
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.disabled=!can('mods');checkbox.checked=serverComparison.selected[kind].has(mod.modId);
      checkbox.setAttribute('aria-label',`${kind==='missing'?'Add':kind==='extra'?'Remove':'Match version for'} ${mod.name||mod.modId}`);
      checkbox.onchange=()=>{if(checkbox.checked)serverComparison.selected[kind].add(mod.modId);else serverComparison.selected[kind].delete(mod.modId);updateComparisonButton();};
      const info=document.createElement('span');info.className='mods-update-info';const name=document.createElement('strong'),id=document.createElement('code');name.textContent=mod.name||mod.modId;id.textContent=mod.modId;info.append(name,id);
      const version=document.createElement('span');version.className='mods-update-versions';version.textContent=kind==='versions'?`${mod.localVersion||'Latest (unpinned)'} → ${mod.remoteVersion}`:kind==='missing'?`Add · ${mod.version||'Version unavailable — Latest'}`:`Remove · ${mod.version||'Latest (unpinned)'}`;
      row.append(checkbox,info,version);section.append(row);
    }
    if(!rows.length){const empty=document.createElement('p');empty.className='feature-note';empty.textContent=query?'No differences match your search.':'No differences in this category.';section.append(empty);}
    const footer=document.createElement('div');footer.className='mods-compare-tools';
    const range=document.createElement('span');range.className='feature-note';range.textContent=`Showing ${rows.length?start+1:0}–${Math.min(start+20,rows.length)} of ${rows.length}`;
    const previous=modButton('Previous',()=>{serverComparison.page--;renderComparisonRows();});previous.disabled=serverComparison.page<=1;
    const next=modButton('Next',()=>{serverComparison.page++;renderComparisonRows();});next.disabled=serverComparison.page>=pages;
    footer.append(range,previous,next);section.append(footer);
    container.append(section);
  updateComparisonButton();
}
function reviewServerModChanges() {
  if(!serverComparison.data || serverComparison.stale)return;
  const selected=selectedComparisonChanges();if(!Object.values(selected).some(ids=>ids.length))return;
  serverComparison.draft={token:serverComparison.data.token,selected};
  const preview=modEl('mods-compare-preview');preview.replaceChildren();
  for(const kind of ['missing','extra','versions'])for(const id of selected[kind]){
    const mod=serverComparison.data[kind].find(m=>m.modId===id),row=document.createElement('div');row.className='mods-update-preview-row';
    const name=document.createElement('strong'),action=document.createElement('span');name.textContent=mod.name||id;
    action.textContent=kind==='missing'?`ADD · ${mod.version||'Latest'}`:kind==='extra'?'REMOVE':`${mod.localVersion||'Latest'} → ${mod.remoteVersion}`;
    row.append(name,action);preview.append(row);
  }
  modEl('mods-compare-error').textContent='';modEl('mods-compare-dialog').showModal();
}
async function applyServerModChanges() {
  if(!serverComparison.draft)return;
  const button=modEl('mods-compare-save');button.disabled=true;
  try {
    const result=await changeFeature('/api/mods/servers/apply',serverComparison.draft);
    modEl('mods-compare-dialog').close();clearServerComparison();
    const message=`${result.counts.missing} added · ${result.counts.extra} removed · ${result.counts.versions} version pins changed. Restart the game server to apply. Compare again to review remaining differences.`;
    setLog(message,'ok');comparisonStatus(message);await fetchStatus();
  }catch(error){modEl('mods-compare-error').textContent=error.message;}
  finally{button.disabled=false;}
}
