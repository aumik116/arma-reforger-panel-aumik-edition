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
  ['btn-start','btn-stop','btn-reset','btn-persist-flush'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = state;
  });
  if (typeof applyPermissions === 'function') applyPermissions();
  if (typeof syncConsoleControls === 'function') syncConsoleControls(Boolean(window.consoleServerRunning), state);
}

async function serverAction(action) {
  const labels = { start: 'Starting server...', stop: 'Stopping server...', restart: 'Restarting server...' };
  setBusy(true);
  setLog(labels[action], 'info');
  try {
    const r = await postJson('/api/' + action, {});
    if (r.status === 401) { window.location.href = '/login'; return; }
    const d = await r.json();
    if (d.ok) {
      const success = { start: 'Server started', stop: 'Server stopped', restart: 'Server restarted' };
      setLog(success[action], 'ok');
      await new Promise(res => setTimeout(res, 1500));
      await fetchStatus();
    } else {
      setLog('Error: ' + (d.error || 'unknown'), 'error');
    }
  } catch(e) { setLog('Connection error', 'error'); }
  setBusy(false);
}
