// Start polling only after page features are initialized.
async function doLogout() {
  await postJson('/logout', {});
  window.location.href = '/login';
}

function startCountdown() {
  countdown = 10;
  document.getElementById('refresh-timer').textContent = countdown;
  clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    countdown--;
    document.getElementById('refresh-timer').textContent = countdown;
    if (countdown <= 0) { fetchStatus(); loadNotifications(); countdown = 10; }
  }, 1000);
}

setInterval(() => { if (!window.liveMetrics?.healthy()) fetchMetrics(); }, 10000);
document.addEventListener('live-metrics', event => {
  const data = event.detail.servers[selectedServerId];
  if (!data) { window.liveMetrics.last = 0; return; }
  fetchMetrics(data);
  fetchNetworkMetrics(data);
  window.consoleServerRunning = data.running;
  document.getElementById('dot').className = 'dot ' + (data.running ? 'online' : 'offline');
  const status = document.getElementById('status-text');
  status.className = 'status-text ' + (data.running ? 'online' : 'offline');
  status.textContent = data.running ? 'ONLINE' : 'OFFLINE';
  for (const id of ['uptime-display', 'summary-uptime']) document.getElementById(id).textContent = data.uptime;
  document.getElementById('summary-players').textContent = data.players ?? '—';
  syncServerControls();
});
fetchMetrics();
startLogStream();
fetchStatus().then(() => { fetchPersistence(); startCountdown(); });

loadNotifications();
