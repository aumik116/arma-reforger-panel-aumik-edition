// Server status and control-state synchronization.
let refreshInterval = null;
let countdown = 10;
let busy = false;

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    if (r.status === 401) { window.location.href = '/login'; return; }
    const d = await r.json();
    updateUI(d);
  } catch(e) {
    setLog('Connection error', 'error');
  }
}

function updateUI(d) {
  const dot = document.getElementById('dot');
  const txt = document.getElementById('status-text');
  dot.className = 'dot ' + (d.running ? 'online' : 'offline');
  txt.className = 'status-text ' + (d.running ? 'online' : 'offline');
  txt.textContent = d.running ? 'ONLINE' : 'OFFLINE';

  document.getElementById('server-name-display').textContent = d.server_name || '—';
  document.getElementById('ip-port-display').textContent = (d.ip && d.port) ? d.ip + ':' + d.port : '—';
  document.getElementById('map-name').textContent = d.map || '—';
  document.getElementById('uptime-display').textContent = d.running ? (d.uptime || '—') : '—';

  if (!busy) {
    document.getElementById('btn-start').disabled = d.running;
    document.getElementById('btn-stop').disabled  = !d.running;
    document.getElementById('btn-reset').disabled = false;
  }

  if (d.csrf) CSRF = d.csrf;
  window.consoleServerRunning = d.running;

  // Render the mod list
  updateModLibrary(d.mods || []);
  if (typeof applyPermissions === 'function') applyPermissions();
  if (typeof syncConsoleControls === 'function') syncConsoleControls(d.running, busy);
}
