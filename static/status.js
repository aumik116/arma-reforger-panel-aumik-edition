// Server status and control-state synchronization.
let refreshInterval = null;
let countdown = 10;
let busy = false;

let statusPending=null;
function fetchStatus(){
  if(statusPending)return statusPending;
  statusPending=readStatus().finally(()=>statusPending=null);return statusPending;
}
async function readStatus() {
  try {
    updateUI(await readJson(await fetch('/api/status')));
  } catch (error) {
    window.consoleServerRunning = undefined;
    document.getElementById('dot').className = 'dot';
    document.getElementById('status-text').className = 'status-text';
    document.getElementById('status-text').textContent = 'UNAVAILABLE';
    syncServerControls();
    setLog(error.message || 'Connection error', 'error');
  }
}

function updateUI(d) {
  const dot = document.getElementById('dot');
  const txt = document.getElementById('status-text');
  dot.className = 'dot ' + (d.running ? 'online' : 'offline');
  txt.className = 'status-text ' + (d.running ? 'online' : 'offline');
  txt.textContent = d.running ? 'ONLINE' : 'OFFLINE';

  document.getElementById('server-name-display').textContent = d.server_name || '—';
  document.getElementById('workspace-server-name').textContent = d.server_name || 'ARMA REFORGER';
  document.getElementById('ip-port-display').textContent = (d.ip && d.port) ? d.ip + ':' + d.port : '—';
  document.getElementById('map-name').textContent = d.map || '—';
  document.getElementById('uptime-display').textContent = d.running ? (d.uptime || '—') : '—';
  document.getElementById('summary-uptime').textContent = d.running ? (d.uptime || '—') : '—';

  if (d.csrf) CSRF = d.csrf;
  window.consoleServerRunning = d.running;

  // Render the mod list
  updateModLibrary(d.mods || []);
  syncServerControls();
}
