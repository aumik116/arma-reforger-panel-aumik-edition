// Explicit draft state: live dashboard polling never changes these inputs.
let configSnapshot = null;
let configRevision = '';
let configChanges = {};
let configGroups = [];
let configPending = false;
let configAdminLabels = {};
const configControls = new Map();

function configGet(object, path) {
  return path.split('.').reduce((value, key) => value && typeof value === 'object' ? value[key] : undefined, object);
}

function configDraft() {
  const draft = structuredClone(configSnapshot);
  for (const [path, value] of Object.entries(configChanges)) {
    const keys = path.split('.');
    let parent = draft;
    for (const key of keys.slice(0, -1)) {
      if (value === null && parent[key] === undefined) { parent = null; break; }
      if (!parent[key] || typeof parent[key] !== 'object' || Array.isArray(parent[key])) parent[key] = {};
      parent = parent[key];
    }
    if (parent) {
      if (value === null) delete parent[keys.at(-1)];
      else parent[keys.at(-1)] = value;
    }
  }
  // Put all settings before the potentially long mod list in preview/copy too.
  if (draft.game && typeof draft.game === 'object' && !Array.isArray(draft.game)) {
    const game = draft.game;
    delete draft.game;
    if (Object.hasOwn(game, 'mods')) {
      const mods = game.mods;
      delete game.mods;
      game.mods = mods;
    }
    draft.game = game;
  }
  return draft;
}

function configElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function configFeedback(message, error = false) {
  byId('config-feedback').textContent = message;
  byId('config-feedback').classList.toggle('config-error', error);
}

function updateConfigDraft() {
  const count = Object.keys(configChanges).length;
  byId('config-dirty').textContent = count ? `${count} unsaved field${count === 1 ? '' : 's'}` : 'No unsaved changes';
  byId('config-save').disabled = !count || configPending;
  byId('config-reset').disabled = !count || configPending;
  const draft = configDraft();
  byId('config-json-text').value = JSON.stringify(draft, null, 2);
  const scenario = configMissions.find(mission => mission.id === draft.game?.scenarioId);
  const summaries = [
    ['Game port', String(draft.bindPort ?? 2001), `A2S ${draft.a2s?.port ?? 'unset'} · RCON ${draft.rcon?.port ?? 'unset'}`],
    ['Public endpoint', `${draft.publicAddress || 'Automatic'}:${draft.publicPort ?? draft.bindPort ?? 2001}`, draft.game?.visible === false ? 'Unlisted server' : 'Listed in server browser'],
    ['Player slots', String(draft.game?.maxPlayers ?? 64), draft.game?.crossPlatform ? 'Crossplay enabled' : 'Configured platforms'],
    ['Scenario', scenario?.name || 'Custom scenario', draft.game?.gameProperties?.battlEye === false ? 'BattlEye disabled' : 'BattlEye enabled']
  ];
  byId('config-summary').replaceChildren(...summaries.map(([label, value, detail]) => {
    const tile = configElement('div', 'config-stat');
    tile.append(configElement('span', '', label), configElement('strong', '', value), configElement('small', '', detail));
    return tile;
  }));
  if (typeof syncNetworkForm === 'function') syncNetworkForm();
}

function configInputValue(spec, input) {
  if (spec.kind === 'bool') return input.checked;
  if (spec.kind === 'int') return input.value === '' ? null : Number(input.value);
  if (spec.kind === 'choice') return input.value || null;
  if (['admins', 'lines'].includes(spec.kind)) return input.value.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
  return input.value;
}

function displayConfigValue(input, spec, value) {
  if (spec.kind === 'scenario') { input.value = configMissions.some(m => m.id === value) ? value : '__custom__'; return; }
  if (spec.kind === 'bool') { input.checked = value === undefined ? !!spec.default : value === true; return; }
  input.value = value === undefined ? '' : Array.isArray(value) ? value.join('\n') : String(value);
}

function renderConfigFields(missions) {
  configControls.clear();
  const container = byId('config-category-fields');
  ['general', 'gameplay', 'connection'].forEach(key => byId('section-config-' + key).replaceChildren());
  byId('config-scenarios')?.remove();
  byId('persistence-settings').replaceChildren();
  const suggestions = document.createElement('datalist');
  suggestions.id = 'config-scenarios';
  for (const mission of missions || []) {
    const option = document.createElement('option');
    option.value = mission.id;
    option.label = mission.name || mission.id;
    suggestions.append(option);
  }
  container.append(suggestions);
  const playerSave = configGroups.flatMap(group => group.fields).find(field => field.path === 'operating.playerSaveTime');
  const displayGroups = configGroups.map(group => ({...group, fields: group.fields.filter(field => field.path !== 'operating.playerSaveTime')}));
  if (playerSave) displayGroups.find(group => group.title === 'Persistence')?.fields.push(playerSave);
  const order = ['Identity', 'Network', 'Access', 'Gameplay', 'Remote console', 'Operating', 'Persistence'];
  displayGroups.map((group, index) => ({group, index})).sort((a,b) => order.indexOf(a.group.title) - order.indexOf(b.group.title)).forEach(({group, index:groupIndex}) => {
    const card = configElement('section', 'config-section');
    card.id = `config-group-${groupIndex}`;
    card.dataset.configCategory = ['Network', 'Remote console'].includes(group.title) ? 'connection' : ['Gameplay', 'Operating'].includes(group.title) ? 'gameplay' : 'general';
    const heading = configElement('div', 'config-section-heading');
    const titles = configElement('div');
    titles.append(configElement('h3', '', group.title), configElement('p', '', group.description));
    heading.append(titles);
    card.append(heading);
    const grid = configElement('div', 'config-fields-grid');
    group.fields.forEach((spec, fieldIndex) => {
      const row = configElement('div', 'config-field');
      if (spec.kind === 'bool') row.classList.add('config-field-boolean');
      const id = `cfg-${groupIndex}-${fieldIndex}`;
      const label = configElement('label', '', spec.label);
      label.htmlFor = id;
      let input;
      if (spec.kind === 'bool') {
        input = document.createElement('input');
        input.type = 'checkbox';
        input.setAttribute('role', 'switch');
      } else if (spec.kind === 'scenario') {
        input = document.createElement('select');
        populateScenarioOptions(input, configGet(configSnapshot, spec.path));
      } else if (spec.kind === 'choice') {
        input = document.createElement('select');
        input.add(new Option('Engine default' + (spec.default !== undefined ? ` (${spec.default ? 'on' : 'off'})` : ''), ''));
        if (spec.kind === 'bool') {
          input.add(new Option('Enabled', 'true'));
          input.add(new Option('Disabled', 'false'));
        } else for (const value of spec.choices) input.add(new Option(value, value));
      } else if (['admins', 'lines'].includes(spec.kind)) {
        input = document.createElement('textarea');
        input.rows = 3;
      } else {
        input = document.createElement('input');
        input.type = spec.kind === 'int' ? 'number' : spec.kind === 'password' ? 'password' : 'text';
        if (spec.kind === 'int') {
          input.min = spec.minimum; input.max = spec.maximum; input.step = 1;
          input.placeholder = spec.default !== undefined ? `Default: ${spec.default}` : 'Engine default';
        } else input.maxLength = spec.maximum || 2048;
        if (spec.kind === 'password') input.autocomplete = 'new-password';
        if (spec.kind === 'scenario') input.setAttribute('list', suggestions.id);
      }
      input.id = id;
      input.required = !!spec.required;
      input.setAttribute('aria-describedby', id + '-help');
      const original = configGet(configSnapshot, spec.path);
      displayConfigValue(input, spec, original);
      if (spec.redacted) { input.value = ''; input.placeholder = 'Hidden · Admin only'; }
      const actions = configElement('div', 'config-field-actions');
      const state = configElement('span', 'config-field-state', spec.read_only ? 'Read-only · Admin only' : original === undefined ? 'Using engine default' : 'Configured');
      actions.append(state);
      if (spec.kind === 'scenario') {
        const custom = configElement('input'); custom.type = 'text'; custom.placeholder = '{GUID}Missions/Custom.conf';
        custom.setAttribute('aria-label', 'Custom scenario resource');
        const isCustom = !configMissions.some(mission => mission.id === original);
        custom.hidden = !isCustom; custom.value = isCustom ? original || '' : '';
        actions.append(custom);
        input.addEventListener('change', () => {
          custom.hidden = input.value !== '__custom__';
          changed(input.value === '__custom__' ? custom.value : input.value);
        });
        custom.addEventListener('input', () => changed(custom.value));
        const rescan = configElement('button', '', 'Rescan installed scenarios'); rescan.type = 'button';
        rescan.onclick = async () => {
          rescan.disabled = true;
          try {
            const response = await postJson('/api/scenarios/rescan', {});
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || 'Scenario scan failed');
            configMissions = data.missions;
            populateScenarioOptions(input, configGet(configDraft(), spec.path));
            suggestions.replaceChildren(...configMissions.map(mission => {
              const option = document.createElement('option'); option.value = mission.id; option.label = mission.name || mission.id; return option;
            }));
            configFeedback(`Found ${configMissions.length} scenarios. Your draft is unchanged.`);
          } catch (error) { configFeedback(error.message, true); }
          finally { rescan.disabled = false; }
        };
        actions.append(rescan);
      }
      if (spec.kind === 'password' && !spec.redacted) {
        const show = configElement('button', '', 'Show'); show.type = 'button';
        show.setAttribute('aria-label', 'Show ' + spec.label.toLowerCase());
        show.onclick = () => { input.type = input.type === 'password' ? 'text' : 'password'; show.textContent = input.type === 'password' ? 'Show' : 'Hide'; };
        actions.append(show);
      }
      function changed(value) {
        if (spec.read_only) return;
        if ((value === null && original === undefined) || JSON.stringify(value) === JSON.stringify(original)) delete configChanges[spec.path];
        else configChanges[spec.path] = value;
        row.classList.toggle('is-dirty', Object.hasOwn(configChanges, spec.path));
        state.textContent = value === null ? 'Using engine default' : 'Configured';
        updateConfigDraft();
        configFeedback('Draft updated. Validate and save when ready.');
      }
      if (!spec.required && !spec.read_only) {
        const reset = configElement('button', '', 'Use default'); reset.type = 'button';
        reset.setAttribute('aria-label', 'Use default for ' + spec.label.toLowerCase());
        reset.onclick = () => { displayConfigValue(input, spec, undefined); changed(null); input.dispatchEvent(new Event('change')); };
        actions.append(reset);
      }
      if (spec.kind !== 'scenario') input.addEventListener('input', () => changed(configInputValue(spec, input)));
      const hint = configElement('small', 'config-field-help', spec.help || (spec.kind === 'int' ? `${spec.minimum}–${spec.maximum}. Leave unset to use the engine default.` : 'Only edited values are written to configuration.'));
      hint.id = id + '-help';
      if (!spec.help) hint.classList.add('config-hint-default');
      row.append(label, input, actions, hint);
      if (spec.kind === 'admins') {
        const names = configElement('div', 'config-admin-names');
        const note = configElement('p', 'config-field-help', 'Save a name for a UUID below. Names are panel labels; administrator access is controlled by the ID list above.');
        const identityLabel = configElement('label', '', 'UUID / Steam ID for name');
        const identityInput = configElement('input'); identityInput.type = 'text';
        identityInput.id = id + '-label-identity'; identityInput.placeholder = 'Paste UUID or Steam ID';
        identityLabel.htmlFor = identityInput.id;
        const nameLabel = configElement('label', '', 'Player name');
        const nameInput = configElement('input'); nameInput.type = 'text'; nameInput.maxLength = 80;
        nameInput.id = id + '-label-name'; nameInput.placeholder = 'e.g. Ranger One';
        nameLabel.htmlFor = nameInput.id;
        const save = configElement('button', 'config-button', 'Save name'); save.type = 'button';
        const list = configElement('div', 'config-admin-list');
        function renderNames() {
          list.replaceChildren();
          const ids = [...new Set(configInputValue(spec, input))];
          for (const identity of ids) {
            const entry = configElement('button', 'config-admin-entry'); entry.type = 'button';
            entry.append(configElement('strong', '', configAdminLabels[identity.toLowerCase()] || 'Name not set'), configElement('span', '', identity));
            entry.onclick = () => { identityInput.value = identity; nameInput.value = configAdminLabels[identity.toLowerCase()] || ''; nameInput.focus(); };
            list.append(entry);
          }
        }
        identityInput.addEventListener('change', () => {
          const saved = configAdminLabels[identityInput.value.trim().toLowerCase()];
          if (saved !== undefined) nameInput.value = saved;
        });
        save.onclick = async () => {
          save.disabled = true;
          try {
            const identity = identityInput.value.trim();
            const response = await postJson('/api/admin-labels', {identity, name:nameInput.value});
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || 'Could not save name');
            configAdminLabels[identity.toLowerCase()] = data.name;
            nameInput.value = data.name; renderNames();
            configFeedback('Administrator name saved. Access is unchanged.');
          } catch (error) { configFeedback(error.message, true); }
          finally { save.disabled = false; }
        };
        names.append(note, nameLabel, nameInput, identityLabel, identityInput, save, list);
        input.addEventListener('input', renderNames);
        input.addEventListener('change', renderNames);
        renderNames(); row.append(names);
      }

      if (spec.read_only) {
        row.classList.add('config-field-locked');
        row.querySelectorAll('input, select, textarea, button').forEach(control => { control.disabled = true; });
      }
      grid.append(row);
      configControls.set(spec.path, {spec, input});
    });
    card.append(grid);
    (group.title === 'Persistence' ? byId('persistence-settings') : byId('section-config-' + card.dataset.configCategory)).append(card);
  });
  if (typeof applyConfigCategory === 'function') applyConfigCategory();
}

let configMissions = [];
function populateScenarioOptions(select, current) {
  select.replaceChildren();
  const groups = new Map();
  for (const mission of configMissions) {
    const source = mission.source === 'vanilla' || !mission.source ? 'Built-in scenarios' : mission.source;
    if (!groups.has(source)) { const group = document.createElement('optgroup'); group.label = source; groups.set(source, group); select.append(group); }
    groups.get(source).append(new Option(mission.name || mission.id, mission.id));
  }
  select.add(new Option('Custom scenario…', '__custom__'));
  select.value = configMissions.some(mission => mission.id === current) ? current : '__custom__';
}
async function loadConfiguration(force = false) {
  if (!can('configure') || configPending || (configSnapshot && !force)) return;
  configPending = true;
  byId('config-fields').disabled = true; byId('persistence-fields').disabled = true;
  byId('config-loading').textContent = 'Loading server configuration…';
  try {
    const data = await getFeature('/api/config/editor');
    configSnapshot = data.config; configRevision = data.revision;
    configGroups = data.groups; configMissions = data.missions; configChanges = {}; configAdminLabels = data.admin_labels || {};
    byId('config-json-description').textContent = can('admin_config')
      ? 'Read-only preview of the complete draft, including mods and custom fields. Passwords are included.'
      : 'Read-only preview of your draft, including mods and custom fields. Admin and RCON passwords are omitted. The join password is included.';
    byId('config-json-text').setAttribute('aria-label', can('admin_config') ? 'Complete configuration JSON' : 'Configuration JSON with admin secrets omitted');
    renderConfigFields(configMissions);
    byId('config-loading').textContent = data.rcon_overridden ? 'RCON connection overrides in config.env are active. Editing the server listener does not update those overrides.' : 'Unset fields use engine defaults. Custom fields and the mod list are preserved.';
    byId('config-fields').disabled = false; byId('persistence-fields').disabled = false;
    updateConfigDraft();
    configFeedback('Changes apply on the next server start. Saving does not restart it.');
    fetchPersistence();
  } catch (error) { byId('config-loading').textContent = error.message; }
  finally { configPending = false; if (typeof syncNetworkForm === 'function') syncNetworkForm(); }
}

function reloadConfiguration() {
  if (Object.keys(configChanges).length && !confirm('Discard your unsaved configuration edits and reload from disk?')) return;
  loadConfiguration(true);
}

function resetConfiguration() {
  if (!confirm('Discard the current unsaved configuration edits?')) return;
  configChanges = {};
  renderConfigFields(configMissions);
  updateConfigDraft();
  configFeedback('Draft reset to the last loaded configuration.');
}

function setConfigurationView(view) {
  for (const mode of ['visual', 'json']) {
    const selected = view === mode;
    byId('config-' + mode).hidden = !selected;
    const tab = byId('config-' + mode + '-tab');
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
}

for (const mode of ['visual', 'json']) byId('config-' + mode + '-tab').addEventListener('keydown', event => {
  if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const target = event.key === 'Home' ? 'visual' : event.key === 'End' ? 'json' : mode === 'visual' ? 'json' : 'visual';
    setConfigurationView(target); byId('config-' + target + '-tab').focus();
  }
});

async function submitConfiguration(save) {
  if (configPending || !configSnapshot) return;
  for (const {spec, input} of configControls.values()) {
    if (Object.hasOwn(configChanges, spec.path) && !input.checkValidity()) {
      selectPanelTab(byId(spec.path.includes('.persistence.') || spec.path === 'operating.playerSaveTime' ? 'tab-persistence' : 'tab-configuration')); setConfigurationView('visual');
      const card = input.closest('[data-config-category]');
      selectPageSection(card?.parentElement.id === 'persistence-settings' ? 'persistence' : 'config', card?.parentElement.id === 'persistence-settings' ? 'settings' : card.dataset.configCategory);
      input.reportValidity(); return;
    }
  }
  configPending = true; byId('config-fields').disabled = true; byId('persistence-fields').disabled = true;
  try {
    const response = await postJson(save ? '/api/config/editor' : '/api/config/validate', {revision:configRevision, changes:configChanges});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Configuration request failed');
    if (save) {
      configSnapshot = data.config; configRevision = data.revision; configChanges = {};
      renderConfigFields(configMissions);
      updateConfigDraft();
      fetchStatus(); fetchPersistence();
    }
    configFeedback(save ? 'Saved. Restart the server to apply these settings.' : 'Changed fields are valid. Scenario resources and mod support are checked by the game on startup.');
  } catch (error) { configFeedback(error.message, true); }
  finally { configPending = false; byId('config-fields').disabled = false; byId('persistence-fields').disabled = false; updateConfigDraft(); }
}

async function copyConfigurationJson() {
  try { await navigator.clipboard.writeText(byId('config-json-text').value); configFeedback(can('admin_config') ? 'Configuration JSON copied. It includes passwords.' : 'Configuration JSON copied. Admin and RCON passwords are omitted; the join password is included.'); }
  catch { byId('config-json-text').focus(); byId('config-json-text').select(); configFeedback('Select and copy the JSON using your keyboard.'); }
}

window.addEventListener('beforeunload', event => {
  if (Object.keys(configChanges).length) { event.preventDefault(); event.returnValue = ''; }
});
