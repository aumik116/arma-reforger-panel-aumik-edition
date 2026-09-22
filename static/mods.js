// Configured mod library. Polling preserves local search, pagination and edit drafts.
const modLibrary = {mods:[], signature:null, page:1, size:8, sort:'order', reorder:false, edit:null, historyCursor:null, metadata:new Map()};
const modEl = id => document.getElementById(id);
let modView = 'cards';
function setModView(view) {
  modView = ['cards','list','details'].includes(view) ? view : 'cards';
  modEl('mods-list').classList.toggle('mods-list-view', modView === 'list');
  modEl('mods-list').classList.toggle('mods-details-view', modView === 'details');
  ['cards','list','details'].forEach(mode => modEl('mods-view-' + mode).setAttribute('aria-pressed', String(modView === mode)));
  try { localStorage.setItem('mods-view', modView); } catch (_) {}
}
let savedModView = 'cards';
try { savedModView = localStorage.getItem('mods-view') || 'cards'; } catch (_) {}
setModView(savedModView);
try { const size = Number(localStorage.getItem('mods-page-size')); if ([8,16,24,48].includes(size)) modLibrary.size = size; } catch (_) {}
modEl('mods-per-page').value = String(modLibrary.size);
modEl('mods-per-page').addEventListener('change', event => {
  modLibrary.size = Number(event.target.value); modLibrary.page = 1;
  try { localStorage.setItem('mods-page-size', String(modLibrary.size)); } catch (_) {}
  drawModLibrary();
});
modEl('mods-search').addEventListener('input', () => { modLibrary.page = 1; drawModLibrary(); });
function updateModLibrary(mods) {
  const signature = JSON.stringify(mods);
  if (signature === modLibrary.signature) return;
  modLibrary.signature = signature; modLibrary.mods = mods;
  modEl('mods-count').textContent = `${mods.length} configured`;
  modEl('mods-tab-configured').textContent = `Configured (${mods.length})`;
  drawModLibrary();
  refreshModMetadata();
}
function modButton(text, action, className='') {
  const b = document.createElement('button'); b.type='button'; b.textContent=text; b.className=className; b.onclick=action; return b;
}
function drawModLibrary() {
  const search = modEl('mods-search').value.trim().toLowerCase();
  let mods = modLibrary.mods.filter(m => `${m.name || ''} ${m.modId}`.toLowerCase().includes(search));
  if (modLibrary.sort === 'name') mods = [...mods].sort((a,b) => (a.name || a.modId).localeCompare(b.name || b.modId));
  const pages = Math.max(1, Math.ceil(mods.length / modLibrary.size));
  modLibrary.page = Math.min(modLibrary.page, pages);
  const start = (modLibrary.page - 1) * modLibrary.size;
  const grid = modEl('mods-list'); grid.replaceChildren();
  const heading = document.createElement('div'); heading.className = 'mods-details-heading';
  ['Name','Mod ID','Version','Size','Actions'].forEach(label => { const cell=document.createElement('span');cell.textContent=label;heading.append(cell); });
  grid.append(heading);
  mods.slice(start, start + modLibrary.size).forEach(mod => {
    const card = document.createElement('article'); card.className='mod-tile';card.dataset.modId=mod.modId;
    const art = document.createElement('div'); art.className='mod-art';
    art.innerHTML='<span class="mod-badge">Configured</span><span class="mod-art-label">Preview unavailable</span>';
    const size=document.createElement('span');size.className='mod-size';art.append(size);
    applyModMetadata(art,mod);
    const body = document.createElement('div'); body.className='mod-body';
    const title = document.createElement('h3'); title.textContent=mod.name || mod.modId; title.title=title.textContent;
    const meta = document.createElement('div'); meta.className='mod-meta';
    const id = document.createElement('code'); id.textContent=mod.modId; id.title=mod.modId;
    const version = document.createElement('span'); version.className='mod-version'+(mod.version ? ' pinned' : ''); version.textContent=mod.version ? `Pinned · ${mod.version}` : 'Latest';
    meta.append(id,version);
    const controls = document.createElement('div'); controls.className='mod-controls';
    controls.append(modButton('Details', () => openModDetails(mod)));
    const link = document.createElement('a'); link.href='https://reforger.armaplatform.com/workshop/'+encodeURIComponent(mod.modId); link.target='_blank'; link.rel='noopener noreferrer'; link.textContent='↗'; link.setAttribute('aria-label',`View ${title.textContent} on Workshop`); controls.append(link);
    const remove = modButton('Remove', () => removeMod(mod.modId),'mod-remove'); remove.dataset.permission='mods'; controls.append(remove);
    body.append(title,meta,controls);
    if (modLibrary.reorder && can('mods')) {
      const index = modLibrary.mods.indexOf(mod), moves=document.createElement('div'); moves.className='mod-move';
      const up=modButton('← Earlier',()=>moveConfiguredMod(mod.modId,-1)); up.disabled=index===0;
      const down=modButton('Later →',()=>moveConfiguredMod(mod.modId,1)); down.disabled=index===modLibrary.mods.length-1;
      moves.append(up,down); body.append(moves);
    }
    card.append(art,body); grid.append(card);
  });
  if (!mods.length) { const empty=document.createElement('p'); empty.className='mods-empty'; empty.textContent=search ? 'No mods match your search.' : 'No mods configured. Add a mod or import a JSON list to get started.'; grid.append(empty); }
  modEl('mods-range').textContent=`Showing ${mods.length ? start+1 : 0}–${Math.min(start+modLibrary.size,mods.length)} of ${mods.length}`;
  const pagination=modEl('mods-pagination'); pagination.replaceChildren();
  const pageButton=(label,page)=>{ const b=modButton(label,()=>{modLibrary.page=page;drawModLibrary();}); b.disabled=page<1 || page>pages; return b; };
  pagination.append(pageButton('Previous',modLibrary.page-1));
  const visible=new Set([1,pages,modLibrary.page-1,modLibrary.page,modLibrary.page+1]); let last=0;
  [...visible].filter(p=>p>=1&&p<=pages).sort((a,b)=>a-b).forEach(p=>{ if(last && p-last>1) { const gap=document.createElement('span'); gap.textContent='…'; pagination.append(gap); } const b=pageButton(String(p),p); if(p===modLibrary.page)b.setAttribute('aria-current','page'); pagination.append(b);last=p; });
  pagination.append(pageButton('Next',modLibrary.page+1));
  drawModTotal();
  if (typeof applyPermissions==='function') applyPermissions();
}
function modSize(mod) {
  const data=modLibrary.metadata.get(String(mod.modId).toUpperCase());
  const size=data?.sizes?.[mod.version || data.current_version];
  return Number.isFinite(size) && size>=0 ? size : null;
}
function applyModMetadata(art,mod) {
  const metadata=modLibrary.metadata.get(String(mod.modId).toUpperCase());
  if(metadata?.thumbnail && art.dataset.thumbnail!==metadata.thumbnail) {
    art.dataset.thumbnail=metadata.thumbnail;art.querySelector('img')?.remove();
    const img=document.createElement('img');img.src=metadata.thumbnail;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';
    img.onload=()=>art.classList.add('has-image');img.onerror=()=>{img.remove();art.classList.remove('has-image');};art.prepend(img);
  }
  const bytes=modSize(mod);
  art.querySelector('.mod-size').textContent=bytes===null?(metadata?.status==='unavailable'?'Size unknown':metadata?.status==='available'?'Version size unknown':'Loading size…'):formatModSize(bytes);
}
function formatModSize(bytes) {
  const units=['B','KiB','MiB','GiB','TiB'];let unit=0;
  while(bytes>=1024&&unit<units.length-1){bytes/=1024;unit++;}
  return `${bytes.toLocaleString(undefined,{maximumFractionDigits:unit?1:0})} ${units[unit]}`;
}
function drawModTotal() {
  const seen=new Set();let total=0,known=0,count=0;
  for(const mod of modLibrary.mods){const key=String(mod.modId).toUpperCase();if(seen.has(key))continue;seen.add(key);count++;const size=modSize(mod);if(size!==null){total+=size;known++;}}
  modEl('mods-total').textContent=count===0?'Estimated mod download: 0 B':known===count?`Estimated mod download: ${formatModSize(total)}`:`Known size: ${formatModSize(total)} · ${count-known} unknown`;
  modEl('mods-total').title='Total across all configured mods, using the selected version. Excludes dependencies not in this list. Cached Workshop sizes; actual download varies with files a player already has.';
}
let modMetadataLoading=false;
async function refreshModMetadata() {
  if(modMetadataLoading || modEl('panel-mods').hidden)return;
  const ids=[...new Set(modLibrary.mods.map(m=>String(m.modId).toUpperCase()))].filter(id=>{const m=modLibrary.metadata.get(id);return !m || m.status==='pending' || Date.now()-m.fetched>(m.status==='available'?3600000:300000);}).slice(0,16);
  if(!ids.length)return;modMetadataLoading=true;
  try {
    await Promise.all(ids.map(async id=>{try {const response=await fetch('/api/mods/metadata?modId='+encodeURIComponent(id));if(!response.ok)throw new Error();const data=await response.json();modLibrary.metadata.set(id,{...data,fetched:Date.now()});}catch(_){modLibrary.metadata.set(id,{status:'unavailable',fetched:Date.now()});}}));
    // Update only metadata nodes so focused controls survive background reads.
    document.querySelectorAll('#mods-list .mod-tile').forEach(card=>{const mod=modLibrary.mods.find(m=>m.modId===card.dataset.modId);if(mod)applyModMetadata(card.querySelector('.mod-art'),mod);});
    drawModTotal();
  }finally{modMetadataLoading=false;}
}
setInterval(()=>{if(!document.hidden)refreshModMetadata();},2000);
function sortModLibrary(sort) {
  modLibrary.sort=sort; modLibrary.page=1;
  ['order','name'].forEach(s=>modEl('mods-sort-'+s).setAttribute('aria-pressed',String(s===sort)));
  drawModLibrary();
}
function toggleModReorder() {
  modLibrary.reorder=!modLibrary.reorder;
  modEl('mods-reorder').setAttribute('aria-pressed',String(modLibrary.reorder)); modEl('mods-reorder-help').hidden=!modLibrary.reorder;
  if(modLibrary.reorder) { modEl('mods-search').value=''; sortModLibrary('order'); } else drawModLibrary();
}
function selectModView(view) {
  ['configured','presets','history'].forEach(name=>{ const active=name===view; modEl('mods-'+name).hidden=!active; const tab=modEl('mods-tab-'+name);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1; });
  if(view==='presets') loadPresets().catch(e=>setLog(e.message,'error'));
  if(view==='history') loadModHistory(true);
}
document.querySelectorAll('.mods-tabs [role="tab"]').forEach(tab=>tab.addEventListener('keydown',event=>{
  const tabs=[...document.querySelectorAll('.mods-tabs [role="tab"]')].filter(t=>!t.hidden); let index=tabs.indexOf(tab);
  if(event.key==='ArrowRight')index=(index+1)%tabs.length; else if(event.key==='ArrowLeft')index=(index+tabs.length-1)%tabs.length; else if(event.key==='Home')index=0; else if(event.key==='End')index=tabs.length-1; else return;
  event.preventDefault();tabs[index].click();tabs[index].focus();
}));
function openModDialog(type) {
  const dialog=modEl('mods-'+type+'-dialog');
  let status=dialog.querySelector('.mods-dialog-status');
  if(!status){status=document.createElement('p');status.className='mods-dialog-status';status.setAttribute('role','status');dialog.append(status);}
  status.textContent='';dialog.showModal();
}
function exportModLibrary() {
  const url=URL.createObjectURL(new Blob([JSON.stringify(modLibrary.mods,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='configured-mods.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function copyModLibrary() {
  try {await navigator.clipboard.writeText(modLibrary.mods.map(m=>`${m.name||m.modId} — ${m.modId}${m.version?' · '+m.version:''}`).join('\n'));setLog('Mod list copied','ok');}catch(_){setLog('Clipboard unavailable. Use Export JSON instead.','error');}
}
function openModDetails(mod) {
  modLibrary.edit={modId:mod.modId,expected:JSON.parse(JSON.stringify(modLibrary.mods))};
  modEl('mods-details-title').textContent=mod.name||'Mod details';modEl('mods-detail-id').textContent=mod.modId;
  modEl('mods-detail-name').value=mod.name||'';modEl('mods-detail-version').value=mod.version||'';
  modEl('mods-detail-name').readOnly=!can('mods');modEl('mods-detail-version').readOnly=!can('mods');modEl('mods-detail-result').textContent='';openModDialog('details');
}
async function saveModDetails() {
  const button=modEl('mods-detail-save');button.disabled=true;
  try {await changeFeature('/api/mods/edit',{...modLibrary.edit,name:modEl('mods-detail-name').value.trim(),version:modEl('mods-detail-version').value.trim()});await fetchStatus();modEl('mods-details-dialog').close();}
  catch(e){modEl('mods-detail-result').textContent=e.message;}finally{button.disabled=false;}
}
let modMovePending=false;
async function moveConfiguredMod(modId,direction) {
  if(modMovePending)return;modMovePending=true;
  try {await changeFeature('/api/mods/edit',{modId,direction,expected:modLibrary.mods});await fetchStatus();}catch(e){setLog(e.message,'error');await fetchStatus();}finally{modMovePending=false;}
}
let modHistoryLoading=false;
async function loadModHistory(reset) {
  if(modHistoryLoading)return;modHistoryLoading=true;
  const container=modEl('mods-history-events'),more=modEl('mods-history-more');
  if(reset){container.replaceChildren();modLibrary.historyCursor=null;}
  more.disabled=true;
  try {
    const data=await getFeature('/api/activity'+(modLibrary.historyCursor?'?before='+modLibrary.historyCursor:''));
    container.querySelector('.mods-history-empty')?.remove();
    const labels={api_mods_add:'Add mod',api_mods_remove:'Remove mod',api_mods_import:'Import mods',api_mods_edit:'Edit mods',presets_save:'Save preset',presets_apply:'Apply preset',presets_delete:'Delete preset'};
    data.events.filter(e=>/mod|preset/.test(e.action)).forEach(e=>{const row=document.createElement('article');const title=document.createElement('div');title.textContent=`${e.actor} · ${labels[e.action]||'Mod change'} · ${e.outcome}`;const time=document.createElement('small');time.textContent=new Date(e.ts*1000).toLocaleString();row.append(title,time);container.append(row);});
    modLibrary.historyCursor=data.next_before;more.hidden=!data.next_before;
    if(!container.children.length){const empty=document.createElement('p');empty.className='mods-history-empty';empty.textContent=data.next_before?'No mod events in this batch. Load more to check older activity.':'No mod activity found.';container.append(empty);}
  }catch(e){setLog(e.message,'error');const error=document.createElement('p');error.textContent=e.message;container.append(error);}finally{more.disabled=false;modHistoryLoading=false;}
}
