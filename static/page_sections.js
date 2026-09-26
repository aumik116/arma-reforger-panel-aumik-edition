// Page-local navigation preserves each workspace's forms and draft state.
let configCategory = 'general';

function selectPageSection(group, key) {
  const selected = byId(`section-tab-${group}-${key}`);
  if (!selected || selected.hidden) return;
  document.querySelectorAll(`[data-section-group="${group}"]`).forEach(button => {
    const active = button === selected;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(`[data-section-content="${group}"]`).forEach(panel => {
    panel.hidden = panel.id !== `section-${group}-${key}`;
  });
  if (group === 'config') { configCategory = key; applyConfigCategory(); }
  if (group === 'mods' && key === 'presets') loadPresets().catch(error => setLog(error.message, 'error'));
  if (group === 'mods' || group === 'mod-review') { renderModUpdates(); refreshModMetadata(); }
  if (group === 'admin' && key === 'activity') setActivityScope('all');
  if (group === 'admin' && key === 'maintenance') { loadConfigBackups(); loadSoftware(); }
  if (group === 'persistence' && key === 'backups') syncBackupSource();
}

function applyConfigCategory() {
  ['general', 'gameplay', 'connection'].forEach(key => { byId('section-config-' + key).hidden = key !== configCategory; });
  document.querySelectorAll('#config-category-fields [data-config-category]').forEach(card => {
    card.hidden = card.dataset.configCategory !== configCategory;
  });
}

function setActivityScope(scope) {
  byId('activity-all').hidden = scope !== 'all';
  byId('activity-mods').hidden = scope !== 'mods';
  ['all', 'mods'].forEach(key => byId('activity-scope-' + key).setAttribute('aria-pressed', String(scope === key)));
  if (scope === 'mods') loadModHistory(true);
  else loadActivity();
}

function openModHistory() {
  selectPanelTab(byId('tab-administration'));
  selectPageSection('admin', 'activity');
  setActivityScope('mods');
}

function openModPresets() {
  selectPanelTab(byId('tab-mods'));
  selectPageSection('mods', 'presets');
}

function syncBackupSource() {
  const source = byId('persistence-startup-select');
  const target = byId('persistence-backup-source');
  target.replaceChildren(...[...source.children].map(child => child.cloneNode(true)));
  target.value = source.value;
}

function chooseBackupSource() {
  byId('persistence-startup-select').value = byId('persistence-backup-source').value;
  updateStartupSaveButton();
}

document.querySelectorAll('[data-section-group]').forEach(button => {
  button.addEventListener('click', () => selectPageSection(button.dataset.sectionGroup, button.dataset.sectionKey));
  button.addEventListener('keydown', event => {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    const tabs = [...document.querySelectorAll(`[data-section-group="${button.dataset.sectionGroup}"]`)].filter(tab => !tab.hidden);
    let index = tabs.indexOf(button);
    index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault();
    tabs[index].click(); tabs[index].focus();
  });
});

// Collapse the overflow menu after choosing an action.
document.querySelectorAll('.action-menu button').forEach(button => {
  button.addEventListener('click', () => { button.closest('details').open = false; });
});
