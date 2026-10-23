// Fleet software operations are independent of the selected workspace/server.
document.addEventListener('DOMContentLoaded', () => {
  const el = id => document.getElementById(id);
  const check = el('fleet-software-check'), update = el('fleet-software-update');
  const dialog = el('fleet-update-dialog'), confirm = el('fleet-update-confirm');
  let status = null, reading = false, submitting = false, timer;
  const textNode = (tag, text, className) => {
    const node = document.createElement(tag); node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function buildLabel(target) {
    if (!target.installed_build) return 'Installed build unknown';
    if (!status?.latest_build) return 'Build ' + target.installed_build;
    return `Build ${target.installed_build} · ${target.installed_build === status.latest_build ? 'Current' : 'Differs from public build'}`;
  }
  function renderBuilds() {
    document.querySelectorAll('[data-software-server]').forEach(node => {
      const target = status?.targets.find(row => row.id === node.dataset.softwareServer);
      node.textContent = target ? buildLabel(target) : '';
    });
  }
  function renderStatus() {
    const allowed = status.targets.length > 0;
    check.hidden = update.hidden = !allowed;
    check.disabled = update.disabled = submitting || status.busy || !status.supported || !status.steamcmd_available;
    const panel = el('fleet-software-status');
    panel.hidden = !allowed;
    if(status.busy || status.state === 'failed' || status.state === 'interrupted') panel.open = true;
    el('fleet-software-message').textContent = !status.supported ? 'Software updates require the Linux host.' :
      !status.steamcmd_available ? 'SteamCMD is unavailable. Configure STEAMCMD_PATH on the host.' : status.message;
    el('fleet-software-build').textContent = status.latest_build ? `Public Steam build ${status.latest_build}${status.checked_at ? ' · Checked ' + new Date(status.checked_at * 1000).toLocaleString() : ''}` : 'Public build not checked yet.';
    const results = el('fleet-software-results'); results.replaceChildren();
    for (const row of status.servers || []) {
      const item = textNode('div', '', 'fleet-software-result');
      item.append(textNode('strong', row.name), textNode('span', row.state), textNode('span', row.message));
      if (row.state === 'failed' || row.state === 'interrupted') item.classList.add('fleet-event-error');
      results.append(item);
    }
    renderBuilds();
    selectionChanged();
  }
  async function load() {
    if (reading) return false;
    reading = true;
    try {
      status = await readJson(await fetch('/api/fleet/software', {signal:AbortSignal.timeout(15000)}));
      renderStatus(); return true;
    } catch (error) {
      check.disabled = update.disabled = true;
      el('fleet-software-status').hidden = false;
      el('fleet-software-message').textContent = 'Software status unavailable: ' + error.message;
      confirm.disabled = true;
      return false;
    } finally { reading = false; }
  }
  async function launch(action, body = {}) {
    await readJson(await postJson('/api/fleet/software/' + action, body));
  }
  check.onclick = async () => {
    if (submitting) return;
    submitting = true; check.disabled = update.disabled = true;
    try { await launch('check'); await load(); }
    catch (error) { el('fleet-software-status').hidden = false; el('fleet-software-message').textContent = error.message; }
    finally { submitting = false; check.disabled = update.disabled = !!status?.busy || !status?.supported || !status?.steamcmd_available; }
  };
  const boxes = () => Array.from(el('fleet-update-targets').querySelectorAll('input[type="checkbox"]'));
  function selectionChanged() {
    const selected = boxes().filter(box => box.checked && !box.disabled);
    const running = selected.filter(box => box.dataset.running === 'true').length;
    el('fleet-update-selection').textContent = selected.length ? `${selected.length} selected · ${running} currently running` : 'No servers selected';
    confirm.disabled = submitting || !!status?.busy || !selected.length;
  }
  update.onclick = async () => {
    if (!await load() || status.busy) return;
    const targetList = el('fleet-update-targets'); targetList.replaceChildren();
    for (const target of status.targets) {
      const label = textNode('label', '', 'fleet-update-target');
      const box = document.createElement('input'); box.type = 'checkbox'; box.value = target.id;
      box.dataset.running = String(target.running); box.disabled = target.busy || target.update_allowed === false;
      box.onchange = selectionChanged;
      const detail = textNode('div', '');
      detail.append(textNode('strong', target.name), textNode('small', `${target.running ? 'Running — will stop and restart' : 'Stopped — will stay stopped'} · ${buildLabel(target)}${target.busy ? ' · Another software job is active' : ''}${target.update_reason ? ' · ' + target.update_reason : ''}`));
      label.append(box, detail); targetList.append(label);
    }
    el('fleet-update-feedback').textContent = '';
    selectionChanged(); dialog.showModal();
  };
  el('fleet-update-close').onclick = () => dialog.close();
  el('fleet-update-all').onclick = () => { boxes().forEach(box => box.checked = !box.disabled); selectionChanged(); };
  el('fleet-update-none').onclick = () => { boxes().forEach(box => box.checked = false); selectionChanged(); };
  el('fleet-update-form').onsubmit = async event => {
    event.preventDefault();
    const ids = boxes().filter(box => box.checked && !box.disabled).map(box => box.value);
    if (submitting || !ids.length || status?.busy) return;
    submitting = true; confirm.disabled = true;
    try {
      await launch('update', {server_ids:ids, confirm:true}); dialog.close(); await load();
    } catch (error) { el('fleet-update-feedback').textContent = error.message; }
    finally { submitting = false; selectionChanged(); }
  };
  document.addEventListener('fleet-rows-rendered', renderBuilds);
  async function poll() {
    if (!document.hidden) await load();
    timer = setTimeout(poll, status?.busy ? 3000 : 15000);
  }
  poll();
  window.addEventListener('pagehide', () => clearTimeout(timer));
});
