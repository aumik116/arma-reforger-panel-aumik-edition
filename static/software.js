// Software jobs are admin-only and continue independently of this page.
let softwarePending = false;
async function loadSoftware() {
  if (softwarePending || !can('admin_config') || document.hidden || document.getElementById('panel-configuration').hidden) return;
  softwarePending = true;
  try {
    const response = await fetch('/api/software');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to read software status');
    document.getElementById('software-build').textContent = `Installed Steam build: ${data.installed_build || 'Unavailable — local Steam manifest not found'}`;
    document.getElementById('software-latest').textContent = data.latest_build ? `Public Steam build: ${data.latest_build} · ${data.installed_build === data.latest_build ? 'Up to date' : data.installed_build ? 'Build differs from installed version' : 'Installed build unknown'} · Checked ${new Date(data.checked_at * 1000).toLocaleString()}` : 'Available public build: not checked';
    document.getElementById('software-status').textContent = !data.supported ? 'Software updates are available on the Linux production host.' : !data.steamcmd_available ? 'SteamCMD not found. Configure STEAMCMD_PATH in config.env.' : `${data.message}${data.server_running ? ' Stop the game server to enable updates.' : ''}`;
    document.getElementById('software-output').textContent = data.output || 'No output yet.';
    document.getElementById('software-check').disabled = data.busy || !data.supported || !data.steamcmd_available;
    document.getElementById('software-update').disabled = data.busy || data.server_running || !data.supported || !data.steamcmd_available;
  } catch (error) {
    document.getElementById('software-status').textContent = error.message;
  } finally { softwarePending = false; }
}
async function runSoftwareJob(action) {
  if (action === 'update' && !confirm('Update the stopped game server to the public Steam release? It will remain stopped afterward.')) return;
  document.getElementById('software-check').disabled = true;
  document.getElementById('software-update').disabled = true;
  try {
    const response = await postJson('/api/software/' + action, {});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Could not start software job');
    await loadSoftware();
  } catch (error) {
    await loadSoftware();
    document.getElementById('software-status').textContent = error.message;
  }
}
setInterval(loadSoftware, 2000);
loadSoftware();
