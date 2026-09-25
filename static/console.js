// A focused view of the live server log and RCON.
const consoleEntries = [];
let consoleLevel = 'all';
let consoleAutoscroll = true;
let consoleView = 'logs';
let consoleSource = '';
let consoleEvent = '';
let consoleHideRcon = false;
let consoleRegex = false;
let consoleSearchError = '';
const consoleEventPatterns = {
  connect: /\bconnect(?:ed|ing|ion)?\b|\bjoined\b/i,
  disconnect: /\bdisconnect(?:ed|ing|ion)?\b|\bleft\b/i,
  kill: /\bkill(?:ed|ing|s)?\b|\bdeath\b|\bdied\b/i,
  chat: /\bchat\b|\bmessage\b/i,
};
const consoleCommandHistory = [];
let consoleHistoryIndex = 0;

function consoleEntry(text) {
  const match = /^\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([A-Z][A-Z0-9_ ]{1,18}?)(?:\s+\([A-Z]\))?\s*:\s*(.*)$/.exec(text);
  const source = match ? match[2].trim() : '';
  const marked = colorLine(text);
  const level = marked === 'err' || marked === 'warn' ? marked : /\bDEBUG\b|\(D\):/.test(text) ? 'debug' : 'info';
  return {text, time: match ? match[1] : '', source, message: match ? match[3] : text,
    level, performance: isPerformanceLog(text), rcon: /\bRCON\b/i.test(text)};
}

function consoleRow(entry) {
  const row = document.createElement('div');
  row.className = 'console-row ' + entry.level;
  row.dataset.level = entry.level || 'other';
  row.dataset.performance = String(entry.performance);
  row.dataset.rcon = String(entry.rcon);
  row.dataset.text = entry.text.toLowerCase();
  row.dataset.original = entry.text;
  row.dataset.source = entry.source;
  for (const [className, value] of [['console-row-time', entry.time], ['console-row-source', entry.source], ['console-row-message', entry.message]]) {
    const span = document.createElement('span');
    span.className = className;
    span.textContent = className === 'console-row-source' ? entry.source.slice(0, 3) || 'LOG' : value;
    if (className === 'console-row-source') {
      span.title = entry.source ? `Filter ${entry.source}` : 'Unclassified log line';
      span.setAttribute('role', 'button');
      span.tabIndex = 0;
      span.onclick = () => setConsoleSource(entry.source);
      span.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setConsoleSource(entry.source); } };
    }
    row.append(span);
  }
  return row;
}

function isConsolePlayerEvent(entry) {
  return /\bplayer\b/i.test(entry.text) &&
    (consoleEventPatterns.connect.test(entry.text) || consoleEventPatterns.disconnect.test(entry.text));
}

function renderConsoleErrorGroups() {
  const output = document.getElementById('console-errors-output');
  const groups = new Map();
  for (const entry of consoleEntries) {
    if (entry.level !== 'err') continue;
    const key = entry.source + '\n' + entry.message;
    const group = groups.get(key) || {entry, count:0};
    group.entry = entry;
    group.count++;
    groups.set(key, group);
  }
  output.replaceChildren();
  if (!groups.size) {
    const empty = document.createElement('p');
    empty.className = 'console-tab-empty';
    empty.append('No errors', document.createElement('br'));
    const detail = document.createElement('span');
    detail.textContent = 'Errors will be grouped and counted here';
    empty.append(detail);
    output.append(empty);
    return;
  }
  for (const {entry, count} of [...groups.values()].reverse()) {
    const row = document.createElement('div');
    row.className = 'console-error-group';
    const badge = document.createElement('span');
    badge.className = 'console-error-count';
    badge.textContent = count + '×';
    const body = document.createElement('div');
    const message = document.createElement('strong');
    message.textContent = entry.message;
    const detail = document.createElement('small');
    detail.textContent = [entry.source, entry.time && 'Latest ' + entry.time].filter(Boolean).join(' · ');
    body.append(message, detail);
    row.append(badge, body);
    output.append(row);
  }
}

function renderConsoleLine(text) {
  const entry = consoleEntry(text);
  consoleEntries.push(entry);
  let removedError = false;
  if (consoleEntries.length > 800) {
    const removed = consoleEntries.shift();
    document.querySelector('#console-log-output .console-row')?.remove();
    if (isConsolePlayerEvent(removed)) document.querySelector('#console-player-list .console-row')?.remove();
    removedError = removed.level === 'err';
  }
  const output = document.getElementById('console-log-output');
  const nearBottom = output.scrollHeight - output.scrollTop < output.clientHeight + 120;
  output.append(consoleRow(entry));
  if (isConsolePlayerEvent(entry)) document.getElementById('console-player-list').append(consoleRow(entry));
  document.getElementById('console-player-message').hidden = Boolean(document.getElementById('console-player-list').children.length);
  if (entry.level === 'err' || removedError) renderConsoleErrorGroups();
  if (consoleAutoscroll && nearBottom) output.scrollTop = output.scrollHeight;
}

function resetConsoleLog() {
  consoleEntries.length = 0;
  document.getElementById('console-log-output').replaceChildren();
  document.getElementById('console-player-list').replaceChildren();
  document.getElementById('console-player-message').hidden = false;
  renderConsoleErrorGroups();
  refreshConsoleView();
}

function refreshConsoleView() {
  const searchText = document.getElementById('console-keyword').value.trim();
  const search = searchText.toLowerCase();
  const showPerformance = document.getElementById('console-performance').checked;
  let matchesSearch = row => row.dataset.text.includes(search);
  consoleSearchError = '';
  if (consoleRegex && search) {
    try {
      const expression = new RegExp(searchText, 'i');
      matchesSearch = row => expression.test(row.dataset.original);
    } catch (_) {
      consoleSearchError = 'Invalid regular expression';
      matchesSearch = () => false;
    }
  }
  document.getElementById('console-keyword').setAttribute('aria-invalid', String(Boolean(consoleSearchError)));
  let visible = 0;
  for (const row of document.querySelectorAll('#console-log-output .console-row')) {
    const match = (consoleLevel === 'all' || row.dataset.level === consoleLevel) &&
      (!consoleSource || row.dataset.source === consoleSource) &&
      (!consoleEvent || consoleEventPatterns[consoleEvent].test(row.dataset.original)) &&
      (!consoleHideRcon || row.dataset.rcon !== 'true') &&
      (showPerformance || row.dataset.performance !== 'true') && matchesSearch(row);
    row.hidden = !match;
    if (match) visible++;
  }
  const counts = {err:0, warn:0, info:0, debug:0};
  for (const entry of consoleEntries) counts[entry.level]++;
  for (const [kind, count] of Object.entries(counts)) document.getElementById('console-count-' + kind).textContent = count;
  document.getElementById('console-error-count').textContent = counts.err;
  const playerEvents = consoleEntries.filter(isConsolePlayerEvent).length;
  document.getElementById('console-player-count').textContent = playerEvents;
  document.getElementById('console-visible-count').textContent = consoleView === 'players' ?
    `${playerEvents} player events` : consoleView === 'errors' ?
    `${counts.err} errors · ${document.querySelectorAll('.console-error-group').length} groups` :
    `${visible}/${consoleEntries.length} recent entries`;
  updateConsoleFilterNote();
}

function setConsoleLevel(level) {
  consoleLevel = consoleLevel === level ? 'all' : level;
  document.querySelectorAll('[data-console-level]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.consoleLevel === consoleLevel)));
  setConsoleView('logs');
  refreshConsoleView();
}

function setConsoleSource(source) {
  consoleSource = consoleSource === source ? '' : source;
  updateConsoleFilterNote();
  refreshConsoleView();
}

function updateConsoleFilterNote() {
  if (consoleView !== 'logs') return;
  const filters = [consoleSource && `Source: ${consoleSource}`, consoleEvent && `Event: ${consoleEvent}`, consoleHideRcon && 'RCON hidden'].filter(Boolean);
  document.getElementById('console-footer-note').textContent =
    `Click source tags to filter · Recent server output${filters.length ? ' · ' + filters.join(' · ') : ''} · ${consoleRegex ? 'Regex' : 'Keyword'} search${consoleSearchError ? ' · ' + consoleSearchError : ''}`;
}

function setConsoleEvent(event) {
  consoleEvent = consoleEvent === event ? '' : event;
  for (const name of Object.keys(consoleEventPatterns)) {
    document.getElementById('console-' + name).setAttribute('aria-pressed', String(consoleEvent === name));
  }
  document.getElementById('console-event-clear').hidden = !consoleEvent;
  setConsoleView('logs');
  updateConsoleFilterNote();
  refreshConsoleView();
}

function toggleConsoleRegex() {
  consoleRegex = !consoleRegex;
  document.getElementById('console-regex').setAttribute('aria-pressed', String(consoleRegex));
  refreshConsoleView();
}

function toggleConsoleRcon() {
  consoleHideRcon = !consoleHideRcon;
  document.getElementById('console-hide-rcon').setAttribute('aria-pressed', String(consoleHideRcon));
  refreshConsoleView();
}

function setConsoleView(view) {
  consoleView = view;
  for (const name of ['logs', 'players', 'errors']) {
    const selected = name === view;
    document.getElementById('console-tab-' + name).setAttribute('aria-selected', String(selected));
    document.getElementById('console-view-' + name).hidden = !selected;
  }
  document.getElementById('console-filters').hidden = view !== 'logs';
  document.getElementById('console-footer-note').textContent = view === 'players' ?
    'Player joins and leaves from recent server logs' : view === 'errors' ?
    'Repeated error messages grouped by source and text' : '';
  refreshConsoleView();
}

function toggleConsoleAutoscroll() {
  consoleAutoscroll = !consoleAutoscroll;
  const button = document.getElementById('console-autoscroll');
  button.setAttribute('aria-pressed', String(consoleAutoscroll));
  button.textContent = consoleAutoscroll ? 'Auto-scroll on' : 'Auto-scroll off';
  if (consoleAutoscroll) {
    const output = document.getElementById('console-log-output');
    output.scrollTop = output.scrollHeight;
  }
}

function toggleConsolePerformance() {
  document.getElementById('show-performance-logs').checked = document.getElementById('console-performance').checked;
  togglePerformanceLogs();
  refreshConsoleView();
}

function exportConsoleLog() {
  const lines = consoleView === 'players' ? consoleEntries.filter(isConsolePlayerEvent).map(entry => entry.text) :
    consoleView === 'errors' ? consoleEntries.filter(entry => entry.level === 'err').map(entry => entry.text) :
    [...document.querySelectorAll('#console-log-output .console-row')].filter(row => !row.hidden).map(row => row.dataset.original);
  const data = new Blob([lines.join('\n') + (lines.length ? '\n' : '')], {type:'text/plain'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(data);
  link.download = `reforger-console-${new Date().toISOString().replaceAll(':', '-')}.txt`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function syncConsoleControls(running, pending) {
  document.getElementById('console-live-dot').classList.toggle('off', !running);
  document.getElementById('console-live-label').textContent = running ? 'LIVE' : 'SERVER OFFLINE';
}

function insertConsoleCommand(command) {
  const input = document.getElementById('console-command-input');
  input.value = command;
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.focus();
  input.setSelectionRange(command.length, command.length);
}

async function runConsoleCommand(event) {
  event.preventDefault();
  const input = document.getElementById('console-command-input');
  const button = document.getElementById('console-command-submit');
  const output = document.getElementById('console-command-output');
  const command = input.value.trim();
  if (!command) return;
  consoleCommandHistory.push(command);
  if (consoleCommandHistory.length > 30) consoleCommandHistory.shift();
  consoleHistoryIndex = consoleCommandHistory.length;
  button.disabled = true;
  output.hidden = false;
  output.textContent = 'Sending…';
  try {
    const response = await postJson('/api/rcon/command', {command});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Command failed');
    output.textContent = result.output || 'Command sent. The server returned no text.';
  } catch (error) { output.textContent = error.message; }
  finally { button.disabled = !input.value.trim(); }
}

async function runConsoleBroadcast(event) {
  event.preventDefault();
  const input = document.getElementById('console-broadcast-input');
  const message = input.value.trim();
  if (!message) return;
  const button = document.getElementById('console-broadcast-submit');
  const output = document.getElementById('console-command-output');
  button.disabled = true;
  output.hidden = false;
  output.textContent = 'Sending broadcast…';
  try {
    const response = await postJson('/api/rcon/command', {command: '#message ' + message});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Broadcast failed');
    output.textContent = result.output || 'Broadcast command sent.';
    input.value = '';
  } catch (error) { output.textContent = error.message; }
  finally { button.disabled = !input.value.trim(); }
}

document.getElementById('console-performance').checked = document.getElementById('show-performance-logs').checked;
document.getElementById('console-broadcast-input').addEventListener('input', event => {
  document.getElementById('console-broadcast-submit').disabled = !event.target.value.trim();
});
document.getElementById('console-command-input').addEventListener('input', event => {
  document.getElementById('console-command-submit').disabled = !event.target.value.trim();
});
document.getElementById('console-command-input').addEventListener('keydown', event => {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
  event.preventDefault();
  consoleHistoryIndex = Math.min(consoleCommandHistory.length, Math.max(0,
    consoleHistoryIndex + (event.key === 'ArrowUp' ? -1 : 1)));
  event.target.value = consoleCommandHistory[consoleHistoryIndex] || '';
  document.getElementById('console-command-submit').disabled = !event.target.value.trim();
});
refreshConsoleView();
