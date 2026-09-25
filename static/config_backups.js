// Administrator-only server configuration history and reviewed restore.
let reviewedConfigBackup = null;

function clearConfigBackupReview() {
  reviewedConfigBackup = null;
  byId('config-backup-diff').hidden = true;
  byId('config-backup-diff').textContent = '';
  byId('config-backup-restore').disabled = true;
  byId('config-backup-review').disabled = !byId('config-backup-select').value;
  byId('config-backup-status').textContent = '';
}

async function loadConfigBackups() {
  if (!can('admin_config')) return;
  const select = byId('config-backup-select');
  const selected = select.value;
  clearConfigBackupReview();
  try {
    const data = await getFeature('/api/config/backups');
    select.replaceChildren(new Option(data.backups.length ? 'Choose a saved version' : 'No backups yet', ''));
    for (const backup of data.backups) {
      const scenario = configMissions.find(item => item.id === backup.scenario)?.name || backup.scenario.split('/').pop() || 'No scenario';
      const label = `${new Date(backup.created_at * 1000).toLocaleString()} · ${scenario} · ${backup.mod_count} mods`;
      select.add(new Option(label, backup.name));
    }
    select.value = data.backups.some(item => item.name === selected) ? selected : '';
    byId('config-backup-review').disabled = !select.value;
    byId('config-backup-status').textContent = data.backups.length ? `${data.backups.length} recent versions available.` : 'A backup will be created before the next panel-managed configuration change.';
  } catch (error) {
    select.replaceChildren(new Option('Backups unavailable', ''));
    byId('config-backup-status').textContent = error.message;
  }
}

async function reviewConfigBackup() {
  const name = byId('config-backup-select').value;
  if (!name) return;
  clearConfigBackupReview();
  try {
    const data = await getFeature(`/api/config/backups/preview?name=${encodeURIComponent(name)}`);
    byId('config-backup-diff').textContent = data.diff || 'This backup matches the current configuration.';
    byId('config-backup-diff').hidden = false;
    reviewedConfigBackup = {name, current_revision:data.current_revision, backup_revision:data.backup_revision};
    byId('config-backup-restore').disabled = !data.diff || data.truncated;
    byId('config-backup-status').textContent = data.truncated ? 'Review is too large to display completely; this backup cannot be restored from the panel.' : 'Review the changes before restoring. Passwords may appear in the diff.';
  } catch (error) { byId('config-backup-status').textContent = error.message; }
}

async function restoreConfigBackup() {
  const reviewed = reviewedConfigBackup;
  if (!reviewed || reviewed.name !== byId('config-backup-select').value) return;
  if (Object.keys(configChanges).length) {
    byId('config-backup-status').textContent = 'Save or discard your unsaved configuration edits before restoring a backup.';
    return;
  }
  if (!confirm('Restore this reviewed server configuration? The current config will be backed up first. Restart the game server afterward to apply the restored settings.')) return;
  byId('config-backup-restore').disabled = true;
  try {
    const response = await postJson('/api/config/backups/restore', reviewed);
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Restore failed');
    await loadConfiguration(true);
    await fetchStatus();
    await loadPresets();
    await loadConfigBackups();
    byId('config-backup-status').textContent = 'Configuration restored. Restart the game server to apply it.';
  } catch (error) { byId('config-backup-status').textContent = error.message; }
}
