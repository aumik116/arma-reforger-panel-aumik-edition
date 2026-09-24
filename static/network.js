// Node-wide bandwidth and game-process UDP listeners, with shared config drafts.
const networkLeverPaths = {
  'network-view-distance': 'game.gameProperties.networkViewDistance',
  'network-server-distance': 'game.gameProperties.serverMaxViewDistance',
  'network-max-players': 'game.maxPlayers'
};
let networkInfo = null;
let networkChartView = null;
let networkMetricsPending = false;
let networkConfigPending = false;
let networkConfigLoadedAt = 0;

function networkActive() {
  return !document.hidden && !byId('panel-network').hidden;
}

function createNetworkChartView() {
  if (networkChartView || typeof Chart === 'undefined') return;
  networkChartView = new Chart(byId('network-bandwidth-chart'), {
    type: 'line',
    data: {labels: [], datasets: [
      {label:'Up Mbps', data:[], borderColor:'#e2bb68', backgroundColor:'transparent', borderWidth:2, pointRadius:0, tension:.25, spanGaps:false},
      {label:'Down Mbps', data:[], borderColor:'#77bba7', backgroundColor:'transparent', borderWidth:2, pointRadius:0, tension:.25, spanGaps:false}
    ]},
    options: {responsive:true, maintainAspectRatio:false, animation:false, interaction:{mode:'index', intersect:false},
      plugins:{legend:{display:false}, tooltip:{callbacks:{label:item => `${item.dataset.label}: ${item.parsed.y?.toFixed(2) ?? '—'}`}}},
      scales:{x:{grid:{color:'#252927'}, ticks:{color:'#85877f', maxTicksLimit:6, maxRotation:0}},
        y:{beginAtZero:true, grid:{color:'#252927'}, ticks:{color:'#85877f', callback:value => `${value} Mbps`}}}}
  });
}

function syncNetworkForm() {
  const source = configSnapshot && can('configure') ? configDraft() : null;
  for (const [id, path] of Object.entries(networkLeverPaths)) {
    const fallback = path.endsWith('networkViewDistance') ? networkInfo?.network_view_distance
      : path.endsWith('serverMaxViewDistance') ? networkInfo?.server_view_distance : networkInfo?.max_players;
    const value = source ? configGet(source, path) ?? fallback : fallback;
    const input = byId(id);
    if (value !== undefined && value !== null) input.value = String(value);
  }
  byId('network-tuning-fields').disabled = !can('configure') || !configSnapshot || configPending;
  byId('network-save').disabled = configPending || !Object.values(networkLeverPaths).some(path => Object.hasOwn(configChanges, path));
  byId('network-feedback').textContent = can('configure') ? byId('network-feedback').textContent : 'A Manager or Administrator can change these settings.';
}

function updateNetworkLever(event) {
  const input = event.target;
  const path = networkLeverPaths[input.id];
  if (!path || !configSnapshot || !can('configure')) return;
  if (!input.checkValidity()) { input.reportValidity(); return; }
  const value = Number(input.value);
  const original = configGet(configSnapshot, path);
  if (value === original) delete configChanges[path];
  else configChanges[path] = value;
  renderConfigFields(configMissions);
  updateConfigDraft();
  byId('network-feedback').textContent = 'Unsaved network settings. Saving applies after the next game server restart.';
  byId('network-feedback').classList.remove('error');
}

Object.keys(networkLeverPaths).forEach(id => byId(id).addEventListener('change', updateNetworkLever));

async function saveNetworkLevers(event) {
  event.preventDefault();
  if (!configSnapshot || configPending || !can('configure')) return;
  const changes = Object.fromEntries(Object.values(networkLeverPaths)
    .filter(path => Object.hasOwn(configChanges, path)).map(path => [path, configChanges[path]]));
  if (!Object.keys(changes).length) return;
  for (const id of Object.keys(networkLeverPaths)) {
    if (!byId(id).checkValidity()) { byId(id).reportValidity(); return; }
  }
  configPending = true;
  syncNetworkForm();
  try {
    const response = await postJson('/api/config/editor', {revision:configRevision, changes});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not save network settings');
    configSnapshot = data.config;
    configRevision = data.revision;
    for (const path of Object.keys(changes)) delete configChanges[path];
    renderConfigFields(configMissions);
    updateConfigDraft();
    byId('network-feedback').textContent = 'Saved. Restart the game server to apply these settings.';
    byId('network-feedback').classList.remove('error');
    networkConfigLoadedAt = 0;
    fetchNetworkConfig();
  } catch (error) {
    byId('network-feedback').textContent = error.message;
    byId('network-feedback').classList.add('error');
  } finally {
    configPending = false;
    byId('config-fields').disabled = false;
    byId('persistence-fields').disabled = false;
    syncNetworkForm();
  }
}

async function fetchNetworkConfig() {
  if (!networkActive() || networkConfigPending || Date.now() - networkConfigLoadedAt < 10000) return;
  networkConfigPending = true;
  try {
    networkInfo = await getFeature('/api/network');
    networkConfigLoadedAt = Date.now();
    byId('network-endpoint').textContent = networkInfo.endpoint || 'Public address not configured';
    byId('network-copy').disabled = !networkInfo.endpoint;
    byId('network-endpoint-note').textContent = networkInfo.endpoint
      ? 'Uses the configured public address and game port. Confirm external reachability with your firewall/router.'
      : 'Set a public address under Server config to show a direct-join code.';
    const rows = networkInfo.services.map(service => {
      const row = document.createElement('tr');
      const status = document.createElement('span');
      status.className = 'network-status-' + service.status.replaceAll(' ', '-');
      status.textContent = service.status;
      for (const value of [service.name, service.port ?? '—', 'UDP']) {
        const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell);
      }
      const cell = document.createElement('td'); cell.append(status); row.append(cell);
      return row;
    });
    byId('network-services').replaceChildren(...rows);
    syncNetworkForm();
  } catch (error) {
    byId('network-services').replaceChildren();
    const row = byId('network-services').insertRow();
    const cell = row.insertCell(); cell.colSpan = 4; cell.textContent = error.message;
  } finally { networkConfigPending = false; }
}

async function fetchNetworkMetrics() {
  if (!networkActive() || networkMetricsPending) return;
  networkMetricsPending = true;
  try {
    const data = await getFeature('/api/metrics');
    const up = Number.isFinite(data.network_tx) ? data.network_tx : null;
    const down = Number.isFinite(data.network_rx) ? data.network_rx : null;
    const players = Number.isInteger(data.player_count) ? data.player_count : null;
    const slots = networkInfo?.max_players ?? '—';
    byId('network-up').textContent = up === null ? '—' : `${up.toFixed(2)} Mbps`;
    byId('network-down').textContent = down === null ? '—' : `${down.toFixed(2)} Mbps`;
    byId('network-players').textContent = players === null ? `— / ${slots}` : `${players} / ${slots}`;
    byId('network-per-player').textContent = players && up !== null ? `${(up * 1000 / players).toFixed(0)} kbps` : '—';
    byId('network-per-player-note').textContent = players && up !== null
      ? `Node uplink ÷ ${players} connected · rough estimate` : players === 0 ? 'No connected players' : 'Needs live player count and node traffic';
    byId('network-live').textContent = up !== null || down !== null ? 'LIVE' : 'COLLECTING';
    byId('network-live').classList.toggle('online', up !== null || down !== null);
    createNetworkChartView();
    if (networkChartView) {
      networkChartView.data.labels.push(new Date().toLocaleTimeString());
      networkChartView.data.datasets[0].data.push(up);
      networkChartView.data.datasets[1].data.push(down);
      if (networkChartView.data.labels.length > 60) {
        networkChartView.data.labels.shift();
        networkChartView.data.datasets.forEach(series => series.data.shift());
      }
      networkChartView.update('none');
    }
  } catch (error) {
    byId('network-live').textContent = 'UNAVAILABLE';
    byId('network-live').classList.remove('online');
  } finally { networkMetricsPending = false; }
}

async function copyNetworkEndpoint() {
  if (!networkInfo?.endpoint) return;
  try {
    await navigator.clipboard.writeText(networkInfo.endpoint);
    byId('network-endpoint-note').textContent = 'Direct-join code copied.';
  } catch {
    byId('network-endpoint-note').textContent = 'Clipboard unavailable. Select and copy the address manually.';
  }
}

async function openNetworkPanel() {
  fetchNetworkConfig();
  fetchNetworkMetrics();
  if (can('configure')) await loadConfiguration();
  syncNetworkForm();
  requestAnimationFrame(() => networkChartView?.resize());
}

setInterval(() => { fetchNetworkMetrics(); fetchNetworkConfig(); }, 1000);
