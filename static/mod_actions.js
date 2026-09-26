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

async function removeMod(modId) {
  if (!confirm('Remove this mod from the configuration?')) return;
  setLog('Removing mod…', 'info');
  try {
    const r = await postJson('/api/mods/remove', { modId });
    const d = await r.json();
    if (d.ok) {
      setLog('Mod removed', 'ok');
      document.getElementById('mods-restart-notice').classList.toggle('visible', d.restart_required);
      await fetchStatus();
    } else {
      setLog('Error: ' + (d.error || 'unknown'), 'error');
    }
  } catch(e) { setLog('Connection error', 'error'); }
}

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
