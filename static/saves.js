// Named copies of completed native persistence saves, not remote save requests.
let savesPending = false;
async function loadSetups() {
  if (savesPending || !can('admin_config') || document.hidden || document.getElementById('panel-persistence').hidden) return;
  savesPending = true;
  try {
    const response = await fetch('/api/saves');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not read saves');
    const select = document.getElementById('setup-select'), selected = select.value;
    select.replaceChildren(new Option('Select a saved setup', ''));
    for (const item of data.snapshots) select.add(new Option(`${item.name} · ${new Date(item.created * 1000).toLocaleString()} · ${(item.bytes / 1048576).toFixed(1)} MiB`, item.snapshot));
    if (data.snapshots.some(item => item.snapshot === selected)) select.value = selected;
    document.getElementById('setup-detected').textContent = `${data.count} files detected in ${data.path}. ${data.newest ? 'Latest file write: ' + new Date(data.newest * 1000).toLocaleString() + '.' : 'No save files yet.'} ${data.running ? 'Stop the server after an autosave to capture or restore.' : ''}`;
    document.getElementById('setup-capture').disabled = data.running || data.busy || !data.count;
    document.getElementById('setup-restore').disabled = data.running || data.busy || !select.value;
  } catch (error) {
    document.getElementById('setup-detected').textContent = error.message;
    document.getElementById('setup-capture').disabled = true;
    document.getElementById('setup-restore').disabled = true;
  } finally { savesPending = false; }
}
async function setupAction(action) {
  const name = document.getElementById('setup-name').value.trim();
  const snapshot = document.getElementById('setup-select').value;
  if (action === 'capture' && !name) { document.getElementById('setup-result').textContent = 'Enter a setup name.'; return; }
  if (action === 'restore' && (!snapshot || !confirm('Replace the current persistence files with this setup? A rollback snapshot is created first. The server stays stopped.'))) return;
  document.getElementById('setup-result').textContent = 'Working…';
  document.getElementById('setup-capture').disabled = true;
  document.getElementById('setup-restore').disabled = true;
  try {
    const response = await postJson('/api/saves/' + action, action === 'capture' ? {name} : {snapshot});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Save operation failed');
    document.getElementById('setup-result').textContent = result.message || 'Setup snapshot captured from existing save files.';
  } catch (error) { document.getElementById('setup-result').textContent = error.message; }
  await loadSetups();
}
setInterval(loadSetups, 5000);
