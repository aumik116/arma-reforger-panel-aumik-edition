// Built-in save settings, save points and named backups.
function _fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B','KB','MB','GB']; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function _fmtAge(ts) {
  if (!ts) return 'never';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function _renderPersistStats(s) {
  const overdue = s.running && s.enabled && s.autoSaveInterval > 0 &&
    (!s.saves?.newest_save || Date.now() / 1000 - s.saves.newest_save > Math.max(1800, s.autoSaveInterval * 180));
  if ('autoSaveInterval' in s) {
    const items = [['Autosave configured', s.enabled === false ? 'Disabled' : s.autoSaveInterval === 0 ? 'Periodic saves off' : `Every ${s.autoSaveInterval} minutes`], ['Startup loading', s.loadSessionSave === false ? 'Off' : 'Latest save'], ['Latest world save in profile', s.saves?.newest_save ? new Date(s.saves.newest_save * 1000).toLocaleString() : 'Not detected'], ['World save files', String(s.saves?.world_files || 0)]];
    const summary = document.getElementById('persistence-summary'); summary.replaceChildren();
    for (const [label, value] of items) { const tile=document.createElement('div'), heading=document.createElement('span'), text=document.createElement('strong'); heading.textContent=label;text.textContent=value;tile.append(heading,text);summary.append(tile); }
    if (overdue) {
      const note = document.createElement('p'); note.className = 'persistence-warning';
      note.textContent = 'No recent world save detected. The interval is configured, but this does not confirm the current scenario is saving. Check the scenario and server logs.';
      summary.append(note);
    }
  }
  const el = document.getElementById('persist-stats');
  if (!s.saves) { el.textContent = ''; return; }
  const { path, exists, total, buckets } = s.saves;
  if (!exists || !total || total.count === 0) {
    el.innerHTML = `No files found under <code>${escHtml(path || '')}</code>. Autosave is only configured; this does not confirm that the scenario is saving.`;
    return;
  }
  const bucketLabel = { game: 'World session (game)', session: 'World session (session)', sessions: 'World sessions', playersave: 'Player saves', settings: 'Settings' };
  const rows = ['game', 'session', 'sessions', 'playersave', 'settings']
    .filter(k => buckets && buckets[k] && buckets[k].count > 0)
    .map(k => `${bucketLabel[k]}: ${buckets[k].count} file${buckets[k].count === 1 ? '' : 's'}, ${_fmtBytes(buckets[k].bytes)} (newest ${_fmtAge(buckets[k].newest)})`)
    .join(' · ');
  const classified = Object.values(buckets || {}).reduce((sum, bucket) => sum + bucket.count, 0);
  const other = total.count - classified;
  const details = [rows, other > 0 && `Other: ${other} file${other === 1 ? '' : 's'}`].filter(Boolean).join(' · ');
  const warning = overdue ? '<br><strong>No recent world save detected.</strong> The configured interval does not prove the current scenario is saving. Check the scenario and server logs.' :
    !s.saves.newest_save ? '<br>No world save point detected in this folder.' : '';
  el.innerHTML = `<code>${escHtml(path)}</code><br>${details || 'No save files'}${warning}`;
}

let selectedStartupSave = '';
function updateStartupSaveButton() {
  const button = document.getElementById('persistence-startup-save');
  const value = document.getElementById('persistence-startup-select').value;
  button.disabled = value === selectedStartupSave;
  if (typeof syncBackupSource === 'function') syncBackupSource();
  document.getElementById('persistence-backup-button').disabled = !value || !document.getElementById('persistence-backup-name').value.trim();
}

function renderStartupSave(s) {
  const select = document.getElementById('persistence-startup-select');
  selectedStartupSave = s.selectedSave?.uuid || '';
  select.replaceChildren(new Option('Latest save for this scenario', ''));
  const named = new Set();
  if ((s.namedSaves || []).length) {
    const group = document.createElement('optgroup'); group.label = 'Named backups';
    for (const backup of s.namedSaves) {
      if (!backup.available) continue;
      named.add(backup.uuid);
      group.append(new Option(`${backup.name} · ${backup.uuid}`, backup.uuid));
    }
    select.append(group);
  }
  const recent = document.createElement('optgroup'); recent.label = 'Detected game saves';
  for (const point of s.savePoints || []) {
    if (named.has(point.uuid)) continue;
    const date = new Date(point.modified * 1000).toLocaleString();
    recent.append(new Option(`${date} · ${point.uuid} · ${point.relative_path}`, point.uuid));
  }
  select.append(recent);
  if (selectedStartupSave && ![...select.options].some(option => option.value === selectedStartupSave)) {
    select.add(new Option(`Pinned archive · ${selectedStartupSave}`, selectedStartupSave));
  }
  select.value = selectedStartupSave;
  updateStartupSaveButton();
  if (typeof syncBackupSource === 'function') syncBackupSource();
  const status = document.getElementById('persistence-startup-status');
  status.textContent = selectedStartupSave ?
    `Pinned ${selectedStartupSave} for this scenario. The preserved copy survives normal save retention.${s.loadSessionSave === false ? ' Enable Load latest session in the settings above before restarting.' : ''}` :
    `Using the latest save for this scenario.${(s.savePoints || []).length ? '' : ' No selectable save points were found in this profile yet.'}`;
  const list = document.getElementById('persistence-backup-list');
  list.replaceChildren();
  const backups = s.namedSaves || [];
  if (!backups.length) list.textContent = 'No named backups kept for this scenario.';
  for (const backup of backups) {
    const row = document.createElement('div'); row.className = 'persistence-backup-row';
    const detail = document.createElement('div');
    const name = document.createElement('strong'); name.textContent = backup.name;
    const meta = document.createElement('small');
    meta.textContent = `${new Date(backup.captured_at * 1000).toLocaleString()} · ${backup.uuid}${backup.available ? '' : ' · archive missing'}`;
    detail.append(name, meta); row.append(detail);
    if (backup.available && can('admin_config')) {
      const use = document.createElement('button'); use.type = 'button'; use.className = 'config-button';
      use.textContent = 'Select for startup';
      use.onclick = () => { select.value = backup.uuid; selectPageSection('persistence', 'saves'); updateStartupSaveButton(); select.focus(); };
      row.append(use);
    }
    list.append(row);
  }
}

async function backupSelectedSave() {
  const uuid = document.getElementById('persistence-startup-select').value;
  const name = document.getElementById('persistence-backup-name').value.trim();
  const button = document.getElementById('persistence-backup-button');
  if (!uuid || !name) { document.getElementById('persistence-startup-status').textContent = 'Select a save point and enter a backup name.'; return; }
  button.disabled = true;
  try {
    const response = await postJson('/api/persistence/named-save', {uuid, name});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Could not keep the backup');
    document.getElementById('persistence-backup-name').value = '';
    await fetchPersistence();
    document.getElementById('persistence-startup-select').value = uuid;
    updateStartupSaveButton();
    setLog('Named save backup kept. Select it as the startup save when ready.', 'ok');
  } catch (error) {
    document.getElementById('persistence-startup-status').textContent = error.message;
    button.disabled = false;
  }
}

async function saveStartupSave() {
  const button = document.getElementById('persistence-startup-save');
  button.disabled = true;
  try {
    const response = await postJson('/api/persistence/startup-save', {uuid: document.getElementById('persistence-startup-select').value});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Could not save startup choice');
    await fetchPersistence();
    setLog(result.restart_required ? 'Startup save selected. Restart the server to use it.' : 'Startup save selected for the next start.', 'ok');
  } catch (error) {
    document.getElementById('persistence-startup-status').textContent = error.message;
    updateStartupSaveButton();
  }
}

async function fetchPersistence() {
  if (typeof can === 'function' && !can('configure')) return;
  try {
    const response = await fetch('/api/persistence');
    if (response.ok) {
      const data = await response.json();
      _renderPersistStats(data);
      renderStartupSave(data);
    }
  } catch(e) { /* Status refresh can retry later. */ }
}

async function flushPersistence() {
  if (!confirm('Delete world-session saves (.save/game and .save/session[s]) and per-player saves (.save/playersave)? Server settings are kept. The next launch starts a fresh world. This cannot be undone.')) return;
  setBusy(true);
  setLog('Flushing saves...', 'info');
  try {
    const r = await postJson('/api/persistence/flush', {});
    const d = await r.json();
    if (d.ok) {
      setLog(`Removed ${d.removed} save file${d.removed === 1 ? '' : 's'}`, 'ok');
      await fetchPersistence();
    } else {
      setLog('Flush failed: ' + (d.error || 'unknown'), 'error');
    }
  } catch (e) { setLog('Connection error', 'error'); }
  setBusy(false);
}
