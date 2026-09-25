// Accounts, mod presets, player roster and activity history.
let currentAccount = {permissions: []};
let savedPresets = [];
let accountRows = [];
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
    'tab-configuration': 'Manage server settings, scenarios and software updates.',
    'tab-network': 'Watch node traffic, tune view distances and check UDP listeners.',
    'tab-files': 'Browse server logs and edit mod-created profile configuration files.',
    'tab-persistence': 'Manage the game’s built-in save settings and save-file maintenance.',
    'tab-mods': 'Manage Workshop mods, imports and saved presets.',
    'tab-administration': 'Manage your account, permissions and activity.'
  }[tab.id];
  window.scrollTo({top:0});
  if (['tab-configuration', 'tab-persistence'].includes(tab.id) && can('configure') && typeof loadConfiguration === 'function') {
    byId(tab.id === 'tab-persistence' ? 'persistence-savebar-slot' : 'configuration-savebar-slot').append(byId('shared-config-savebar'));
    loadConfiguration();
  }
  if (tab.id === 'tab-configuration' && can('admin_config') && typeof loadConfigBackups === 'function') loadConfigBackups();
  if (tab.id === 'tab-persistence') fetchPersistence();
  if (tab.id === 'tab-network' && typeof openNetworkPanel === 'function') openNetworkPanel();
  if (tab.id === 'tab-files' && typeof openFilesPanel === 'function') openFilesPanel();
  if (tab.id === 'tab-console' && typeof fetchLogs === 'function') fetchLogs(30);
  if (tab.id === 'tab-dashboard') {
    requestAnimationFrame(() => { cpuChart.resize(); ramChart.resize(); networkChart.resize(); diskChart.resize(); Object.values(extraCharts).forEach(chart => chart.resize()); });
    fetchMetrics();
  }
}

function openPanelSection(panel, target) {
  selectPanelTab(byId('tab-' + panel));
  requestAnimationFrame(() => {
    byId(target).focus({preventScroll:true});
    byId(target).scrollIntoView({block:'center'});
  });
}

const mobileNavigation = window.matchMedia('(max-width: 700px)');
function updateNavigationOrientation() {
  document.querySelector('.panel-tabs').setAttribute('aria-orientation', mobileNavigation.matches ? 'horizontal' : 'vertical');
}
mobileNavigation.addEventListener('change', updateNavigationOrientation);
updateNavigationOrientation();

document.querySelectorAll('.panel-tab').forEach((tab, index, tabs) => {
  tab.addEventListener('click', () => selectPanelTab(tab));
  tab.addEventListener('keydown', event => {
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
  const response = await fetch(url);
  if (response.status === 401) { location.href = '/login'; throw new Error('Please sign in'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
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

async function loadPlayers() {
  try {
    const data = await getFeature('/api/players');
    const selected = byId('player-select').value;
    roster = data.players;
    byId('player-summary').textContent = data.available ? `${roster.length} connected` : 'Player list unavailable';
    byId('player-message').textContent = data.message;
    byId('player-select').replaceChildren(new Option(roster.length ? 'Select a player' : 'No players to display', ''));
    roster.forEach(p => byId('player-select').add(new Option(p.name, p.identity)));
    byId('player-select').value = roster.some(p => p.identity === selected) ? selected : '';
    showPlayer();
  } catch (error) {
    roster = [];
    byId('player-select').replaceChildren(new Option('Unavailable', ''));
    byId('player-summary').textContent = 'Player list unavailable';
    byId('player-message').textContent = error.message;
    showPlayer();
  }
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

async function loadPresets() {
  const data = await getFeature('/api/presets');
  savedPresets = data.presets;
  const selected = byId('preset-select').value;
  byId('preset-select').replaceChildren(new Option('Select a saved mod preset', ''));
  savedPresets.forEach(p => byId('preset-select').add(new Option(`${p.name} · ${p.scenario_name || 'Mods only'} · ${p.mods.length} mods${p.active ? ' · Active' : ''}`, p.id)));
  byId('preset-select').value = selected;
  showPreset();
}

function showPreset() {
  const p = savedPresets.find(p => String(p.id) === byId('preset-select').value);
  byId('preset-details').textContent = p ? `${p.scenario_name ? `Scenario: ${p.scenario_name}` : 'Legacy preset: mods only'} · ${p.mods.length} mods · Saved by ${p.updated_by}${p.mods.length ? ` · ${p.mods.slice(0, 6).map(m => m.name || m.modId).join(', ')}${p.mods.length > 6 ? ` and ${p.mods.length - 6} more` : ''}` : ''}` : '';
}

async function savePreset(overwrite = false) {
  try {
    const selected = savedPresets.find(p => String(p.id) === byId('preset-select').value);
    if (overwrite && !selected) throw new Error('Select a preset to overwrite');
    if (overwrite && !confirm(`Replace the scenario and mods saved in "${selected.name}" with the current configuration?`)) return;
    await changeFeature('/api/presets', {name: overwrite ? selected.name : byId('preset-name').value.trim(), ...(overwrite ? {id:selected.id} : {})});
    byId('preset-name').value = '';
    await loadPresets();
  } catch (e) { setLog(e.message, 'error'); }
}

async function presetAction(action) {
  try {
    const selected = savedPresets.find(p => String(p.id) === byId('preset-select').value);
    if (!selected) throw new Error('Select a preset first');
    if (action === 'apply' && Object.keys(configChanges).length) throw new Error('Save or discard your unsaved configuration edits before applying a preset.');
    const target = selected.scenario_name ? `scenario and mod list` : 'mod list';
    if (!confirm(action === 'apply' ? `Replace the configured ${target} with "${selected.name}"? Restart a running server afterward to use it.` : `Delete preset "${selected.name}"?`)) return;
    await changeFeature(`/api/presets/${action}`, {id: selected.id});
    await fetchStatus();
    if (action === 'apply' && can('configure')) await loadConfiguration(true);
    await loadPresets();
  } catch (e) { setLog(e.message, 'error'); }
}

async function loadUsers() {
  const data = await getFeature('/api/users');
  accountRows = data.users;
  byId('users-list').replaceChildren();
  accountRows.forEach(user => {
    const row = document.createElement('div'); row.className = 'feature-row';
    const label = document.createElement('span');
    label.textContent = `${user.username} · ${user.is_owner ? 'Owner' : user.role}${user.enabled ? '' : ' · Disabled'}`;
    row.append(label);
    if (user.is_owner && user.id !== currentAccount.id) {
      const note = document.createElement('small'); note.textContent = 'Protected Owner account';
      row.append(note); byId('users-list').append(row); return;
    }
    const edit = document.createElement('button'); edit.className = 'btn-save'; edit.textContent = 'Edit';
    edit.onclick = () => {
      byId('user-id').value = user.id; byId('user-name').value = user.username;
      byId('user-role').value = user.role; byId('user-enabled').checked = !!user.enabled;
      byId('user-role').disabled = !!user.is_owner; byId('user-enabled').disabled = !!user.is_owner;
      byId('user-password').value = ''; byId('user-save').textContent = 'Update account';
    };
    row.append(edit);
    if (user.id !== currentAccount.id && !user.is_owner) {
      const remove = document.createElement('button'); remove.className = 'btn-save'; remove.textContent = 'Delete';
      remove.onclick = async () => {
        if (!confirm(`Delete account "${user.username}"? Its activity history will remain.`)) return;
        try { await changeFeature('/api/users/delete', {id:user.id}); await loadUsers(); }
        catch (e) { setLog(e.message, 'error'); }
      };
      row.append(remove);
    }
    byId('users-list').append(row);
  });
}

function resetUserForm() {
  byId('user-id').value = ''; byId('user-name').value = ''; byId('user-password').value = '';
  byId('user-role').value = 'viewer'; byId('user-enabled').checked = true;
  byId('user-role').disabled = false; byId('user-enabled').disabled = false;
  byId('user-save').textContent = 'Create account';
}

async function saveUser() {
  try {
    const data = {username:byId('user-name').value.trim(), password:byId('user-password').value,
      role:byId('user-role').value, enabled:byId('user-enabled').checked};
    if (byId('user-id').value) data.id = Number(byId('user-id').value);
    await changeFeature('/api/users', data);
    if (data.id === currentAccount.id) {
      currentAccount = await getFeature('/api/me');
      byId('account-label').textContent = `${currentAccount.username} · ${currentAccount.is_owner ? 'Owner' : currentAccount.role}`;
    }
    resetUserForm(); await loadUsers();
  } catch (e) { setLog(e.message, 'error'); }
}

async function changePassword() {
  try {
    await changeFeature('/api/account/password', {current_password:byId('current-password').value, password:byId('new-password').value});
    byId('current-password').value = ''; byId('new-password').value = '';
  } catch (e) { setLog(e.message, 'error'); }
}

const actionNames = {
  login:'Signed in', api_start:'Start server', api_stop:'Stop server', api_restart:'Restart server',
  api_config:'Change server configuration', api_mods_add:'Add mod', api_mods_remove:'Remove mod',
  api_mods_import:'Import mods', api_persistence_set:'Change persistence', api_persistence_flush:'Delete saves',
  api_scenarios_rescan:'Rescan scenarios', presets_save:'Save preset', presets_apply:'Apply preset',
  presets_delete:'Delete preset', users_save:'Save account', users_delete:'Delete account', account_password:'Change password'
};

async function loadActivity(older = false) {
  try {
    const data = await getFeature('/api/activity' + (older && activityCursor ? `?before=${activityCursor}` : ''));
    if (!older) byId('activity-list').replaceChildren();
    for (const event of data.events) {
      const row = document.createElement('div'); row.className = 'activity-entry';
      const title = document.createElement('strong');
      title.textContent = `${new Date(event.ts * 1000).toLocaleString('en-US')} · ${event.actor} · ${actionNames[event.action] || event.action} · ${event.outcome}`;
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
    await Promise.all([loadPlayers(), loadPresets(), can('users') ? loadUsers() : Promise.resolve(), can('activity') ? loadActivity() : Promise.resolve()]);
    setInterval(loadPlayers, 10000);
  } catch(e) { setLog(e.message, 'error'); }
}
document.addEventListener('panel-change', event => {
  if (can('activity')) loadActivity();
  if (event.detail.startsWith('/api/mods/')) loadPresets().catch(e => setLog(e.message, 'error'));
});
initFeatures();

async function copyPlayerUuid() {
  const field = byId('player-uuid');
  if (!field.value) return;
  try { await navigator.clipboard.writeText(field.value); byId('uuid-copy-status').textContent = 'UUID copied'; }
  catch (_) { field.focus(); field.select(); byId('uuid-copy-status').textContent = 'Press Ctrl+C to copy the selected UUID.'; }
}
