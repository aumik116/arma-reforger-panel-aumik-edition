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

setInterval(fetchMetrics, 1000);
fetchMetrics();
startLogStream();
fetchStatus().then(() => { fetchPersistence(); startCountdown(); });

loadNotifications();
