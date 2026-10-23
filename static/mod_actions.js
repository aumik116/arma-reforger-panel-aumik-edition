// Mod add, remove and import actions.
async function addMod() {
  const modId   = document.getElementById('mod-id').value.trim();
  const modName = document.getElementById('mod-name').value.trim();
  const modVer  = document.getElementById('mod-version').value.trim();
  if (!modId)   { setLog('Mod ID is required', 'error'); return; }
  if (!modName) { setLog('Mod name is required', 'error'); return; }
  document.getElementById('btn-add-mod').disabled = true;
  setLog('Adding mod…', 'info');
  try {
    const r = await postJson('/api/mods/add', { modId, name: modName, version: modVer });
    const d = await r.json();
    if (d.ok) {
      setLog(`Mod "${modName}" added`, 'ok');
      document.getElementById("mods-add-dialog").close();
      document.getElementById('mod-id').value = '';
      document.getElementById('mod-name').value = '';
      document.getElementById('mod-version').value = '';
      document.getElementById('mods-restart-notice').classList.toggle('visible', d.restart_required);
      await fetchStatus();
    } else {
      setLog('Error: ' + (d.error || 'unknown'), 'error');
    }
  } catch(e) { setLog('Connection error', 'error'); }
  document.getElementById('btn-add-mod').disabled = false;
}

function removeMod(modId) { openModRemoval([modId]); }
let modRemovalDraft=null,modRemovalBusy=false;
function closeModRemoval(){if(!modRemovalBusy)document.getElementById('mods-remove-dialog').close();}
function openModRemoval(ids){
 const dialog=document.getElementById('mods-remove-dialog'),form=document.getElementById('mods-remove-form');
 const mods=modLibrary.mods.filter(m=>ids.includes(m.modId));if(!mods.length)return;
 modRemovalDraft={ids:mods.map(m=>m.modId),expected:JSON.parse(JSON.stringify(modLibrary.mods)),reviewed:false};form.reset();document.getElementById('mods-remove-dependencies').replaceChildren();document.getElementById('mods-remove-confirm').textContent='Confirm removal';
 document.getElementById('mods-remove-error').textContent='';document.getElementById('mods-remove-summary').textContent=`Remove ${mods.length} mod${mods.length===1?'':'s'} from this server?`;
 const list=document.getElementById('mods-remove-list');list.replaceChildren();for(const mod of mods){const item=document.createElement('li');item.textContent=(mod.name||mod.modId)+' · '+mod.modId;list.append(item);}
 const complete=document.getElementById('mods-remove-complete');complete.disabled=!can('admin_config')||window.consoleServerRunning!==false;
 document.getElementById('mods-remove-restriction').textContent=!can('admin_config')?'Complete removal requires server administrator permission.':window.consoleServerRunning!==false?'Stop the server before using complete removal.':'Known dependencies will be listed for your review. You can remove them anyway.';
 dialog.showModal();form.querySelector('[value="config"]').focus();
}
document.getElementById('mods-remove-form').addEventListener('change',event=>{if(event.target.name==='removal'&&modRemovalDraft){modRemovalDraft.reviewed=false;document.getElementById('mods-remove-dependencies').replaceChildren();document.getElementById('mods-remove-confirm').textContent='Confirm removal';}});
document.getElementById('mods-remove-close').onclick=closeModRemoval;document.getElementById('mods-remove-cancel').onclick=closeModRemoval;
document.getElementById('mods-remove-dialog').addEventListener('cancel',event=>{event.preventDefault();closeModRemoval();});
document.getElementById('mods-remove-form').onsubmit=async event=>{
 event.preventDefault();if(modRemovalBusy||!modRemovalDraft)return;modRemovalBusy=true;
 const button=document.getElementById('mods-remove-confirm');button.disabled=true;document.getElementById('mods-remove-error').textContent='';
 try{
  const mode=new FormData(event.target).get('removal');
  if(!modRemovalDraft.reviewed){
   const preview=await readJson(await postJson('/api/mods/remove-bulk',{modIds:modRemovalDraft.ids,expected:modRemovalDraft.expected,mode,preview:true}));
   modRemovalDraft.reviewed=true;
   const region=document.getElementById('mods-remove-dependencies');region.replaceChildren();
   if(preview.dependencies.length){
    const heading=document.createElement('p');heading.textContent='These remaining mods depend on your selection:';region.append(heading);
    const list=document.createElement('ul');for(const dependency of preview.dependencies){const item=document.createElement('li');item.textContent=dependency.name+' ('+dependency.modId+') — required by: '+dependency.required_by.join(', ');list.append(item);}region.append(list);
    const include=document.createElement('button');include.type='button';include.textContent='Also remove dependent mods';
    include.onclick=()=>{const ids=new Set(modRemovalDraft.ids);for(const dependency of preview.dependencies)for(const dependent of dependency.dependents)ids.add(dependent.modId);document.getElementById('mods-remove-dialog').close();openModRemoval([...ids]);document.querySelector('#mods-remove-form [name="removal"][value="'+mode+'"]').checked=true;};region.append(include);
    if(preview.metadata_incomplete){const note=document.createElement('p');note.textContent='Some metadata is missing; other dependencies may be unknown.';region.append(note);}
    button.textContent='Remove anyway';region.scrollIntoView({block:'nearest'});return;
   }
  }
  const result=await readJson(await postJson('/api/mods/remove-bulk',{modIds:modRemovalDraft.ids,expected:modRemovalDraft.expected,mode}));
  modRemovalDraft.ids.forEach(id=>selectedMods.delete(id));updateModLibrary(result.mods);
  document.getElementById('mods-restart-notice').classList.toggle('visible',result.restart_required);
  document.getElementById('mods-remove-dialog').close();setLog(result.warning||`${result.removed} mod(s) removed${mode==='complete'?' completely':' from configuration'}.`,result.warning?'error':'ok');
  if(typeof loadDownloadedMods==='function')loadDownloadedMods(true);await fetchStatus();
 }catch(error){document.getElementById('mods-remove-error').textContent=error.message;}
 finally{modRemovalBusy=false;button.disabled=false;}
};

// ─── Bulk import (paste or file upload) ──────────────────────────────────────
async function importModsFromTextarea() {
  const txt = document.getElementById('mods-import-text').value;
  if (!txt.trim()) { setLog('Paste a JSON array first', 'error'); return; }
  const mode = document.getElementById('mods-import-mode').value;
  await _importMods({ payload: txt, mode });
}

async function importModsFromFile(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  if (f.size > 2 * 1024 * 1024) { setLog('File too large (max 2 MB)', 'error'); return; }
  const mode = document.getElementById('mods-import-mode').value;
  setLog(`Uploading ${f.name}…`, 'info');
  const fd = new FormData();
  fd.append('file', f, f.name);
  fd.append('mode', mode);
  try {
    const r = await postForm('/api/mods/import', fd);
    const d = await r.json();
    _afterImport(d);
  } catch(e) { setLog('Upload error', 'error'); }
  input.value = '';
}

async function _importMods(body) {
  setLog('Importing mods…', 'info');
  try {
    const r = await postJson('/api/mods/import', body);
    const d = await r.json();
    _afterImport(d);
  } catch(e) { setLog('Connection error', 'error'); }
}

function _afterImport(d) {
  if (d.ok) {
    let msg = d.message || `${d.imported} mods imported`;
    if (d.skipped && d.skipped.length) {
      msg += ` (${d.skipped.length} skipped: ${d.skipped.slice(0, 3).join('; ')}${d.skipped.length > 3 ? '…' : ''})`;
    }
    setLog(msg, 'ok');
    document.getElementById("mods-import-dialog").close();
    document.getElementById('mods-import-text').value = '';
    document.getElementById('mods-restart-notice').classList.toggle('visible', d.restart_required);
    fetchStatus();
  } else {
    setLog('Import failed: ' + (d.error || 'unknown'), 'error');
  }
}
