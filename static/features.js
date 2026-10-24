// Accounts, mod presets, player roster and activity history.
let currentAccount = {permissions: []};
let roster = [];
let activityCursor = null;
const can = permission => currentAccount.permissions.includes(permission);
const byId = id => document.getElementById(id);

function selectPanelTab(tab) {
  document.querySelectorAll('.panel-tab').forEach(button => {
    const selected = button === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    byId(button.getAttribute('aria-controls')).hidden = !selected;
  });
  document.body.classList.toggle('mods-active', tab.id === 'tab-mods');
  byId('page-title').textContent = tab.textContent;
  byId('page-description').textContent = {
    'tab-dashboard': 'Monitor your server and manage the action.',
    'tab-console': 'Inspect live output, player events and RCON responses.',
    'tab-startup':'Manage launch settings and inspect startup health.',
    'tab-players':'Connected players, moderation and searchable history for this server.',
    'tab-scheduler':'Schedule server controls, broadcasts, updates and configuration backups.',
    'tab-configuration': 'Manage server identity, gameplay, connections and security.',
    'tab-network': 'Watch node traffic, tune view distances and check UDP listeners.',
    'tab-files': 'Browse server files, upload profile files and restore deleted items.',
    'tab-persistence': 'Manage the game’s built-in save settings and save-file maintenance.',
    'tab-mods': 'Manage Workshop mods, imports and saved presets.',
    'tab-administration': 'Manage your account, permissions and activity.'
  }[tab.id];
  document.body.classList.remove('navigation-open');
  byId('mobile-nav-toggle').setAttribute('aria-expanded','false');
  byId('mobile-nav-current').textContent=tab.textContent;
  if(mobileNavigation.matches)byId('mobile-nav-toggle').focus({preventScroll:true});
  window.scrollTo({top:0});
  if(tab.id==='tab-startup'&&typeof loadStartup==='function')loadStartup();
  if(tab.id==='tab-players'&&typeof loadOperatorPlayers==='function')loadOperatorPlayers(true);
  if(tab.id==='tab-scheduler'&&typeof loadSchedules==='function')loadSchedules();
  if (['tab-configuration', 'tab-persistence'].includes(tab.id) && can('configure') && typeof loadConfiguration === 'function') {
    byId(tab.id === 'tab-persistence' ? 'persistence-savebar-slot' : 'configuration-savebar-slot').append(byId('shared-config-savebar'));
    loadConfiguration();
  }
  if (tab.id === 'tab-administration' && can('admin_config') && !byId('section-admin-maintenance').hidden) { loadConfigBackups(); loadSoftware(); }
  if (tab.id === 'tab-persistence') fetchPersistence();
  if (tab.id === 'tab-network' && typeof openNetworkPanel === 'function') openNetworkPanel();
  if (tab.id === 'tab-files' && typeof openFilesPanel === 'function') openFilesPanel();
  if (tab.id === 'tab-console' && typeof fetchLogs === 'function') fetchLogs(30);
  if (tab.id === 'tab-mods') { renderModUpdates(); refreshModMetadata(); }
  if (tab.id === 'tab-dashboard') {
    requestAnimationFrame(() => { playersChart.resize(); cpuChart.resize(); ramChart.resize(); networkChart.resize(); diskChart.resize(); Object.values(extraCharts).forEach(chart => chart.resize()); });
    fetchMetrics();if(byId('player-details-disclosure').open)loadPlayers();
  }
}

function openPanelSection(panel, target) {
  selectPanelTab(byId('tab-' + panel));
  requestAnimationFrame(() => {
    if(!target||!byId(target))return;
    byId(target).focus({preventScroll:true});
    byId(target).scrollIntoView({block:'center'});
  });
}

const mobileNavigation = window.matchMedia('(max-width: 700px)');
function updateNavigationOrientation() {
  document.querySelector('.panel-tabs').setAttribute('aria-orientation', mobileNavigation.matches ? 'horizontal' : 'vertical');
}
byId('mobile-nav-toggle').onclick=()=>{const open=document.body.classList.toggle('navigation-open');byId('mobile-nav-toggle').setAttribute('aria-expanded',String(open));};
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('navigation-open')){document.body.classList.remove('navigation-open');byId('mobile-nav-toggle').setAttribute('aria-expanded','false');byId('mobile-nav-toggle').focus();}});
mobileNavigation.addEventListener('change', updateNavigationOrientation);
updateNavigationOrientation();

document.querySelectorAll('.panel-tab').forEach(tab => {
  tab.addEventListener('click', () => selectPanelTab(tab));
  tab.addEventListener('keydown', event => {
    const tabs = [...document.querySelectorAll('.panel-tab')].filter(button => !button.hidden);
    const index = tabs.indexOf(tab);
    let next;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    tabs[next].focus();
    selectPanelTab(tabs[next]);
  });
});

async function getFeature(url) {
  return readPanelData(url);
}

async function changeFeature(url, data) {
  const response = await postJson(url, data);
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed');
  setLog(result.restart_required ? 'Saved. Restart the server to apply these changes.' : 'Saved successfully', 'ok');
  if (result.restart_required) byId('mods-restart-notice').classList.add('visible');
  return result;
}

function applyPermissions() {
  document.querySelectorAll('[data-permission]').forEach(el => {
    el.hidden = !can(el.dataset.permission);
  });
  byId('users-controls').disabled = !can('users');
  byId('users-restricted').hidden = can('users');
  byId('configuration-readonly').hidden = can('configure');
  byId('mods-readonly').hidden = can('mods');
  ['btn-start', 'btn-stop', 'btn-reset'].forEach(id => {
    if (!can('control')) byId(id).disabled = true;
  });
}

let playersPending = false;
async function loadPlayers() {
  if (playersPending) return;
  playersPending = true;
  try {
    const data = await getFeature('/api/players');
    const selected = byId('player-select').value;
    roster = data.players;
    byId('summary-players').textContent = data.available ? roster.length : '—';
    pushChart(playersChart, data.available ? roster.length : null);
    byId('player-summary').textContent = data.available ? `${roster.length} connected` : 'Player list unavailable';
    byId('player-message').textContent = data.message;
    byId('player-select').replaceChildren(new Option(roster.length ? 'Select a player' : 'No players to display', ''));
    roster.forEach(p => byId('player-select').add(new Option(p.name, p.identity)));
    const list = byId('dashboard-player-list'); list.replaceChildren();
    for (const player of roster) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'dashboard-player';
      const avatar = document.createElement('span'); avatar.className = 'dashboard-player-avatar'; avatar.textContent = player.name.slice(0,1).toUpperCase();
      const text = document.createElement('span'); text.textContent = player.name;
      const detail = document.createElement('small'); detail.textContent = 'Player #' + player.id; text.append(detail);
      button.append(avatar, text);
      button.onclick = () => { byId('player-select').value = player.identity; byId('player-details-disclosure').open = true; showPlayer(); };
      list.append(button);
    }
    byId('player-select').value = roster.some(p => p.identity === selected) ? selected : '';
    showPlayer();
  } catch (error) {
    roster = [];
    byId('dashboard-player-list').replaceChildren();
    byId('player-select').replaceChildren(new Option('Unavailable', ''));
    byId('summary-players').textContent = '—';
    pushChart(playersChart, null);
    byId('player-summary').textContent = 'Player list unavailable';
    byId('player-message').textContent = error.message;
    showPlayer();
  } finally {playersPending=false;}
}

function showPlayer() {
  const player = roster.find(p => p.identity === byId('player-select').value);
  const hasUuid = player && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(player.identity);
  byId('player-uuid-field').hidden = !player;
  byId('copy-player-uuid').disabled = !hasUuid;
  byId('uuid-copy-status').textContent = '';
  byId('player-uuid').value = hasUuid ? player.identity : '';
  byId('player-uuid').placeholder = 'Unavailable — no UUID reported';
  byId('player-details').textContent = player ?
    `Username: ${player.name} · Player ID: ${player.id}${hasUuid ? '' : ` · Identity: ${player.identity}`} · First observed by panel: ${new Date(player.first_seen * 1000).toLocaleString('en-US')}` : '';
}

function loadPresets() { return window.loadUnifiedPresets?.() || Promise.resolve(); }

async function loadActivity(older = false) {
  try {
    const data = await getFeature('/api/activity' + (older && activityCursor ? `?before=${activityCursor}` : ''));
    if (!older) byId('activity-list').replaceChildren();
    for (const event of data.events) {
      const row = document.createElement('div'); row.className = 'activity-entry';
      const title = document.createElement('strong');
      title.textContent = `${new Date(event.ts * 1000).toLocaleString('en-US')} · ${event.actor} · ${event.action.replace(/_/g, ' ')} · ${event.outcome}`;
      row.append(title);
      if (Object.keys(event.details).length) {
        const detail = document.createElement('div');
        detail.textContent = Object.entries(event.details).map(([key, value]) => `${key.replaceAll('_',' ')}: ${Array.isArray(value) ? value.map(v => typeof v === 'object' ? `${v.name || v.modId} (${v.modId})` : v).join(', ') || 'none' : value}`).join(' · ');
        row.append(detail);
      }
      byId('activity-list').append(row);
    }
    if (!byId('activity-list').children.length) byId('activity-list').textContent = 'No activity yet.';
    activityCursor = data.next_before;
    byId('activity-more').hidden = !activityCursor;
  } catch (e) { setLog(e.message, 'error'); }
}

async function initFeatures() {
  try {
    currentAccount = await getFeature('/api/me');
    byId('account-label').textContent = `${currentAccount.username} · ${currentAccount.is_owner ? 'Owner' : currentAccount.role}`;
    applyPermissions();
    document.dispatchEvent(new Event('panel-ready'));
    await Promise.all([loadPlayers(), loadPresets(), can('users') ? loadUsers() : Promise.resolve(), can('activity') ? loadActivity() : Promise.resolve()]);
    setInterval(()=>{if(!document.hidden&&!byId('panel-dashboard').hidden&&byId('player-details-disclosure').open)loadPlayers();},10000);
  } catch(e) { setLog(e.message, 'error'); }
}
document.addEventListener('panel-change', event => {
  if (!document.hidden&&!byId('panel-administration').hidden&&can('activity')) loadActivity();
  if (!byId('section-mods-presets').hidden&&(event.detail.startsWith('/api/mods/')||event.detail.startsWith('/api/operations'))) loadPresets().catch(e => setLog(e.message, 'error'));
});
initFeatures();

async function copyPlayerUuid() {
  const field = byId('player-uuid');
  if (!field.value) return;
  try { await navigator.clipboard.writeText(field.value); byId('uuid-copy-status').textContent = 'UUID copied'; }
  catch (_) { field.focus(); field.select(); byId('uuid-copy-status').textContent = 'Press Ctrl+C to copy the selected UUID.'; }
}

byId('player-details-disclosure').addEventListener('toggle',()=>{if(byId('player-details-disclosure').open&&!document.hidden)loadPlayers();});
