// Dashboard chart creation and metric polling.
const MAX_POINTS = 60;

function makeChartData(color) {
  return {
    labels: Array(MAX_POINTS).fill(''),
    datasets: [{
      data: Array(MAX_POINTS).fill(null),
      borderColor: color,
      backgroundColor: color + '18',
      borderWidth: 1.5,
      pointRadius: 0,
      fill: true,
      tension: 0.4,
    }]
  };
}

const chartOpts = (max) => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: { legend: { display: false }, tooltip: { enabled: false } },
  scales: {
    x: { display: false },
    y: {
      display: true,
      min: 0, max: max,
      grid: { color: '#1e253022', drawBorder: false },
      ticks: {
        color: '#5a6070', font: { size: 9 }, maxTicksLimit: 3,
        callback: v => v + '%'
      }
    }
  }
});

const cpuChart = new Chart(document.getElementById('chart-cpu'), {
  type: 'line',
  data: makeChartData('#4c9fd6'),
  options: chartOpts(100)
});

const ramChart = new Chart(document.getElementById('chart-ram'), {
  type: 'line',
  data: makeChartData('#c8a84b'),
  options: chartOpts(100)
});

function trafficChart(id, unit) {
  const data = makeChartData('#c8a84b');
  data.datasets.push(makeChartData('#4caf7d').datasets[0]);
  const options = chartOpts(undefined);
  options.scales.y.ticks.callback = value => value + ' ' + unit;
  return new Chart(document.getElementById(id), {type:'line', data, options});
}
const networkChart = trafficChart('chart-network', 'Mbps');
const diskChart = trafficChart('chart-disk', 'MiB/s');

function renderTraffic(sample, chart, ids, statusId, factor, unit, scope) {
  const available = sample?.status === 'available';
  [sample?.first, sample?.second].forEach((value, index) => {
    const rate = available && Number.isFinite(value) ? value * factor : null;
    document.getElementById(ids[index]).textContent = rate === null ? '—' : rate.toFixed(2) + ' ' + unit;
    const values = chart.data.datasets[index].data;
    values.push(rate); if (values.length > MAX_POINTS) values.shift();
  });
  document.getElementById(statusId).textContent = available ? scope : sample?.status === 'warming' ? 'Collecting first interval…' : sample?.status === 'stopped' ? 'Server stopped' : 'Metrics unavailable';
  chart.update('none');
}

function pushChart(chart, value) {
  chart.data.datasets[0].data.push(value);
  if (chart.data.datasets[0].data.length > MAX_POINTS)
    chart.data.datasets[0].data.shift();
  chart.update('none');
}

const metricDefinitions = [
  ['fps', 'Server simulation FPS', ['FPS'], 'FPS', 'Waiting for native server performance statistics'],
  ['ping', 'Player latency', ['Median', '95th percentile'], 'ms', 'Requires game telemetry; unavailable with no ping samples'],
];
const extraCharts = {};
const eventMarkers = {
  id: 'panelEvents',
  afterDraw(chart) {
    const events = chart.panelEvents || [];
    const times = chart.sampleTimes || [];
    const {ctx, chartArea} = chart;
    if (!chartArea) return;
    ctx.save(); ctx.strokeStyle = '#c8a84b'; ctx.setLineDash([3, 4]);
    for (const event of events) {
      const index = times.findIndex(t => t != null && t >= event.ts);
      const first = times.find(t => t != null);
      if (index < 0 || event.ts < first) continue;
      const x = chart.scales.x.getPixelForValue(index);
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
    }
    ctx.restore();
  }
};
Chart.register(eventMarkers);
for (const [id, title, series, unit, description] of metricDefinitions) {
  const card = document.createElement('div'); card.className = 'chart-card';
  card.innerHTML = `${id === 'ping' ? '<div class="wip-banner" id="latency-wip"><strong>WIP</strong><span>Player latency needs a working game telemetry source.</span></div>' : ''}<div class="chart-header"><div><div class="chart-title">${title}</div>
    <div class="chart-sub" id="metric-${id}-value">Unavailable</div></div></div>
    <div class="chart-wrap" style="height:120px"><canvas id="chart-${id}" role="img" aria-label="${title}"></canvas></div><p class="feature-note" id="metric-${id}-note">${description}</p>`;
  if (id === 'fps') { const value = document.createElement('div'); value.className='chart-value ram'; value.id='server-fps-value'; value.textContent='— FPS'; card.querySelector('.chart-header').append(value); }
  document.getElementById('extra-metrics').append(card);
  const options = chartOpts(undefined);
  options.scales.y.ticks.callback = v => v + ' ' + unit;
  options.plugins.legend = {display: series.length > 1, labels: {color:'#8a909d', boxWidth:10}};
  options.plugins.tooltip = {enabled:true};
  const data = makeChartData('#4c9fd6');
  data.datasets = series.map((label, i) => ({...makeChartData(i ? '#78b88b' : '#c8a84b').datasets[0], label, tension:0, fill:false}));
  extraCharts[id] = new Chart(card.querySelector('canvas'), {type:'line', data, options});
}
function updateExtraMetrics(d) {
  document.getElementById('server-fps-value').textContent = Number.isFinite(d?.server_fps) ? d.server_fps.toFixed(1) + ' FPS' : '— FPS';
  document.getElementById('cpu-frequency').textContent = Number.isFinite(d?.cpu_frequency_mhz) ? (d.cpu_frequency_mhz / 1000).toFixed(2) + ' GHz' : '— GHz';
  document.getElementById('cpu-frequency').title = Number.isFinite(d?.cpu_frequency_mhz) ? 'Average frequency reported by the OS across logical CPUs' : 'CPU frequency unavailable from this host';
  document.getElementById('ram-capacity').textContent = d?.ram_total > 0 && Number.isFinite(d?.ram_used) ? (d.ram_used / 1024).toFixed(1) + ' / ' + (d.ram_total / 1024).toFixed(1) + ' GiB' : '— / — GiB';
  for (const [id, value] of [['ai-count', d?.ai_count], ['vehicle-count', d?.vehicle_count]]) {
    const counter = document.getElementById(id);
    counter.textContent = Number.isFinite(value) ? Math.round(value).toLocaleString() : '—';
    counter.title = Number.isFinite(value) ? 'Latest server count' : 'Count unavailable';
  }
  const now = d?.ts ?? Date.now() / 1000;
  const values = {
    fps:[d?.server_fps], network:[d?.network_rx, d?.network_tx],
    disk:[d?.disk_read, d?.disk_write], ping:[d?.ping_median, d?.ping_p95]
  };
  const events = d?.events || [];
  for (const [id, , series, unit] of metricDefinitions) {
    const chart = extraCharts[id];
    chart.data.labels.push(new Date(now * 1000).toLocaleTimeString()); chart.data.labels.shift();
    chart.sampleTimes = [...(chart.sampleTimes || Array(MAX_POINTS).fill(null)), now].slice(-MAX_POINTS);
    chart.panelEvents = events;
    chart.data.datasets.forEach((set, i) => {
      set.data.push(Number.isFinite(values[id][i]) ? values[id][i] : null); set.data.shift();
    });
    document.getElementById(`metric-${id}-value`).textContent = series.map((label,i) => `${label}: ${Number.isFinite(values[id][i]) ? values[id][i].toFixed(1) + (unit ? ' ' + unit : '') : 'Unavailable'}`).join(' · ');
    chart.update('none');
  }
  for (const chart of [cpuChart, ramChart]) {
    chart.sampleTimes = [...(chart.sampleTimes || Array(MAX_POINTS).fill(null)), now].slice(-MAX_POINTS);
    chart.panelEvents = events;
  }
  document.getElementById('metric-fps-note').textContent = d?.fps_message || 'FPS statistics unavailable';
  document.getElementById('latency-wip').hidden = Number.isFinite(d?.ping_median) || Number.isFinite(d?.ping_p95);
  document.getElementById('metric-ping-note').textContent = d?.telemetry_message || 'Player latency unavailable';
  const available = Number.isFinite(d?.disk_free) && d.disk_total > 0;
  const low = available && (d.disk_used_percent >= 90 || d.disk_free < 5 * 1024 ** 3);
  document.getElementById('disk-space-gauge').hidden = !available;
  document.getElementById('disk-space-gauge').value = available ? d.disk_used_percent : 0;
  document.getElementById('disk-space-text').textContent = available ? `${(d.disk_free / 1024 ** 3).toFixed(1)} GiB free of ${(d.disk_total / 1024 ** 3).toFixed(1)} GiB (${d.disk_used_percent.toFixed(1)}% used)` : 'Disk space unavailable';
  document.getElementById('disk-space-alert').textContent = low ? 'Low disk space: less than 10% or 5 GiB remaining. Free space before updating mods or creating saves.' : '';
  document.getElementById('disk-space-alert').style.color = low ? '#ef7777' : '';
  const names = {api_start:'Server start', api_stop:'Server stop', api_restart:'Server restart', presets_apply:'Mod preset applied', api_mods_add:'Mod added', api_mods_remove:'Mod removed', api_mods_import:'Mods imported'};
  document.getElementById('metric-events').textContent = events.length ? events.slice(0,5).map(e => `${new Date(e.ts * 1000).toLocaleTimeString()} — ${names[e.action] || e.action}`).join(' · ') : 'No recent panel events.';
}

// ─── Metrics polling ─────────────────────────────────────────────────────────
let metricsPending = false;
async function fetchMetrics() {
  if (metricsPending || document.hidden || document.getElementById('panel-dashboard').hidden) return;
  metricsPending = true;
  try {
    const r = await fetch('/api/metrics');
    if (r.status === 401) { window.location.href = '/login'; return; }
    if (!r.ok) throw new Error('Metrics request failed');
    const d = await r.json();
    updateExtraMetrics(d);

    const ramPct = d.ram_total > 0 ? Math.round(d.ram_used / d.ram_total * 100) : 0;

    document.getElementById('cpu-val').textContent = (d.cpu ?? 0).toFixed(1) + '%';
    document.getElementById('ram-val').textContent = ramPct + '%';
    document.getElementById('proc-cpu-sub').textContent = 'Arma: ' + (d.running ? (d.cpu ?? 0).toFixed(1) + '%' : '—%');
    document.getElementById('proc-ram-sub').textContent = 'Arma: ' + (d.running ? (d.ram_process ?? 0) + ' MB / ' + d.ram_total + ' MB' : '— MB');

    pushChart(cpuChart, d.cpu ?? 0);
    pushChart(ramChart, ramPct);
    renderTraffic(d.network, networkChart, ['net-rx','net-tx'], 'net-state', 8 / 1000000, 'Mbps', 'All non-loopback interfaces; includes other host traffic');
    renderTraffic(d.disk, diskChart, ['disk-read','disk-write'], 'disk-state', 1 / 1048576, 'MiB/s', 'Storage reads/writes attributed to the game process');
  } catch(e) {
    updateExtraMetrics(null);
    renderTraffic(null, networkChart, ['net-rx','net-tx'], 'net-state', 1, 'Mbps', '');
    renderTraffic(null, diskChart, ['disk-read','disk-write'], 'disk-state', 1, 'MiB/s', '');
  }
  finally { metricsPending = false; }
}



// ─── SSE Log stream ───────────────────────────────────────────────────────────
