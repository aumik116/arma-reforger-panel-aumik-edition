// Server lifecycle actions and operation feedback.
function setLog(msg, type = 'info') {
  const dialogStatus = document.querySelector('dialog[open] .mods-dialog-status');
  if (dialogStatus) dialogStatus.textContent = msg;
  const el = document.getElementById('log-msg');
  el.className = 'log-entry ' + type;
  const ts = new Date().toLocaleTimeString('en-US');
  el.textContent = '[' + ts + '] ' + msg;
}

function setBusy(state) {
  busy = state;
  syncServerControls();
}

function syncServerControls() {
  const running = window.consoleServerRunning;
  const known = typeof running === 'boolean';
  document.getElementById('btn-start').disabled = busy || !known || running;
  document.getElementById('btn-stop').disabled = busy || !known || !running;
  document.getElementById('btn-reset').disabled = busy || !known;
  document.getElementById('btn-persist-flush').disabled = busy;
  if (typeof applyPermissions === 'function') applyPermissions();
  if (typeof syncConsoleControls === 'function') syncConsoleControls(running, busy);
}

async function serverAction(action) {
  const labels = { start: 'Starting server...', stop: 'Stopping server...', restart: 'Restarting server...' };
  if (busy || !labels[action]) return;
  const name = document.getElementById('server-name-display').textContent || 'this server';
  if (action !== 'start' && !confirm(`${action === 'stop' ? 'Stop' : 'Restart'} ${name}? Connected players will be disconnected.`)) return;
  setBusy(true);
  setLog(labels[action], 'info');
  try {
    await controlServer(action);
    const success = { start: 'Server started', stop: 'Server stopped', restart: 'Server restarted' };
    setLog(success[action], 'ok');
    await fetchStatus();
  } catch (error) { setLog(error.message || 'Connection error', 'error'); }
  finally { setBusy(false); }
}
