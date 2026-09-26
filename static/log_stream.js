// Live output ingestion for the dashboard and console.
let evtSource = null;

function colorLine(line) {
  const l = line.toLowerCase();
  if (l.includes('(e):') || l.includes('error'))  return 'err';
  if (l.includes('(w):') || l.includes('warning')) return 'warn';
  if (l.includes('online game') || l.includes('server registered')) return 'ok';
  if (line.startsWith('[---'))  return 'sep';
  return '';
}

function isPerformanceLog(text) {
  return /^\s*\d{2}:\d{2}:\d{2}\.\d+\s+(?:DEFAULT\s*:\s*FPS:\s*\d+(?:\.\d+)?,\s*frame time\s*\(|WORLD\s*:\s*(?:UpdateEntities|Frame)\s*$)/.test(text);
}

function togglePerformanceLogs() {
  const show = document.getElementById('show-performance-logs').checked;
  document.getElementById('log-output').classList.toggle('hide-performance', !show);
  const consoleToggle = document.getElementById('console-performance');
  if (consoleToggle) consoleToggle.checked = show;
  if (typeof refreshConsoleView === 'function') refreshConsoleView();
  try { localStorage.setItem('panel-show-performance-logs', String(show)); } catch (_) {}
}
try {
  document.getElementById('show-performance-logs').checked = localStorage.getItem('panel-show-performance-logs') === 'true';
} catch (_) {}
togglePerformanceLogs();

function appendLog(text) {
  const el = document.getElementById('log-output');
  const span = document.createElement('span');
  span.className = 'log-line ' + colorLine(text) + (isPerformanceLog(text) ? ' performance-log' : '');
  span.textContent = text;
  span.hidden = !text.toLowerCase().includes(document.getElementById('console-search').value.toLowerCase());
  el.appendChild(span);
  if (typeof renderConsoleLine === 'function') renderConsoleLine(text);
  // Auto-scroll only when the user is near the bottom
  if (!document.getElementById('pause-console-scroll').checked && el.scrollHeight - el.scrollTop < el.clientHeight + 120) {
    el.scrollTop = el.scrollHeight;
  }
  // Limit lines in the DOM
  const lines = el.querySelectorAll('.log-line');
  if (lines.length > 800) lines[0].remove();
}

function filterConsole() {
  const query = document.getElementById('console-search').value.toLowerCase();
  document.querySelectorAll('#log-output .log-line').forEach(line => { line.hidden = !line.textContent.toLowerCase().includes(query); });
}

function clearLog() {
  document.getElementById('log-output').innerHTML = '';
  if (typeof resetConsoleLog === 'function') resetConsoleLog();
}

function startLogStream() {
  if (evtSource) clearInterval(evtSource);

  // Fetch the last 80 lines immediately
  fetchLogs(80);

  // Then poll every 2 seconds for new lines
  evtSource = setInterval(() => fetchLogs(30), 2000);
  document.getElementById('log-live-dot').classList.remove('off');
}

let logCursor = '';
let logsPending = false;
async function fetchLogs(count) {
  if (logsPending || (typeof can === 'function' && !can('logs'))) return;
  logsPending = true;
  try {
    // Bounded catch-up batches keep busy logs moving without overlapping polls.
    for (let batch = 0; batch < 4; batch++) {
      const r = await fetch(`/api/logs?lines=${count}&cursor=${encodeURIComponent(logCursor)}`);
      if (!r.ok) return;
      const d = await r.json();
      if (d.error || !d.lines) return;
      if (d.reset) clearLog();
      d.lines.forEach(line => appendLog(line));
      if (d.cursor) logCursor = d.cursor;
      if (typeof refreshConsoleView === 'function') refreshConsoleView();
      if (typeof syncConsoleControls === 'function') syncConsoleControls(Boolean(window.consoleServerRunning), busy);
      if (!d.more) break;
    }
  } catch(e) {
    document.getElementById('console-live-dot').classList.add('off');
    document.getElementById('console-live-label').textContent = 'Disconnected';
  }
  finally { logsPending = false; }
}



// ─── Status polling ───────────────────────────────────────────────────────────
