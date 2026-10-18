document.addEventListener('DOMContentLoaded', () => {
  const rows = document.getElementById('overview-rows'), feedback = document.getElementById('overview-feedback');
  let loading = false, permissions = [], timer;
  const busy = new Set();
  let snapshots = [], measureStorage = false;
  const attention = server => ['failed','unavailable'].includes(server.status);
  const storageSize = bytes => (bytes / 1e9).toFixed(2) + ' GB';
  const workspace = server => server.id ? '/?server=' + encodeURIComponent(server.id) : '/?legacy=1';
  function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
  async function read(url, id) {
    const response = await fetch(url, {headers:id ? {'X-Server-ID':id} : {}, signal:AbortSignal.timeout(8000)});
    const body = await response.json(); if (!response.ok) throw new Error(body.error || 'Request failed'); return body;
  }
  async function inspect(server) {
    if (server.state !== 'ready') return {...server, status:server.state};
    try {
      const status = await read('/api/status', server.id);
      let players = null;
      if (!status.running) players = 0;
      else { try { const roster = await read('/api/players', server.id); if (roster.available) players = roster.players.length; } catch (_) {} }
      let storage = null;
      if (measureStorage) { try { storage = await read('/api/storage', server.id); } catch (_) {} }
      return {...server, storage, ...status, name:status.server_name || server.name, status:status.running ? 'online' : 'offline', players};
    } catch (error) { return {...server, status:'unavailable', error:error.message}; }
  }
  async function action(server, command, button) {
    if (command !== 'start' && !confirm(`${command === 'stop' ? 'Stop' : 'Restart'} ${server.name}? Connected players will be disconnected.`)) return;
    busy.add(server.id); button.disabled = true;
    try {
      // Explicit target per action; never change the page's global server selection.
      if (!CSRF) CSRF = (await read('/api/csrf')).csrf;
      const response = await fetch('/api/' + command, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF,...(server.id ? {'X-Server-ID':server.id} : {})}, body:JSON.stringify({_csrf:CSRF})});
      const body = await response.json(); if (!response.ok || body.ok === false) throw new Error(body.error || 'Operation failed');
      feedback.textContent = `${server.name}: ${command} requested.`;
    } catch (error) { feedback.textContent = error.message; }
    finally { busy.delete(server.id); button.disabled = false; await refresh(false); }
  }
  function render(servers) {
    rows.replaceChildren();
    const query = document.getElementById('overview-search').value.trim().toLowerCase();
    const filter = document.getElementById('overview-filter').value;
    const visible = servers.filter(server =>
      [server.name, server.ip, server.port, server.game_port, server.query_port].join(' ').toLowerCase().includes(query) &&
      (filter === 'all' || filter === server.status || filter === 'attention' && attention(server) || filter === 'installing' && ['provisioning','registered','installing'].includes(server.status)));
    for (const server of visible) {
      const row = element('tr', '');
      const status = element('td',''); status.append(element('span',server.status,'server-state state-' + server.status)); row.append(status);
      const name = element('td',''); name.append(element('strong',server.name));
      if (server.ip && server.ip !== '—') name.append(element('small',server.ip + ':' + (server.port || server.game_port || '—')));
      if (server.map) name.append(element('small',server.map));
      name.append(element('small',server.error || (server.port || server.game_port ? `Game ${server.port || server.game_port} · Query ${server.query_port || '—'}` : 'Existing server'))); row.append(name);
      for (const value of [server.players ?? '—', typeof server.cpu === 'number' ? server.cpu.toFixed(1)+'%' : '—', typeof server.ram_process === 'number' ? (server.ram_process/1024).toFixed(2)+' GiB' : '—',server.uptime || '—']) row.append(element('td',value));
      const storage = server.storage;
      row.append(element('td', storage && Number.isFinite(storage.total_bytes) ? storageSize(storage.total_bytes) + (storage.status === 'partial' ? ' (partial)' : '') : storage?.status === 'pending' ? 'Measuring…' : '—'));
      const actions = element('td',''); actions.className = 'manager-actions';
      if ((server.permissions || []).includes('control') && ['online','offline'].includes(server.status)) {
        const command = server.running ? 'stop' : 'start';
        const button = element('button',server.running ? '■ Stop' : '▶ Start','btn-logout'); button.disabled = busy.has(server.id); button.onclick = () => action(server,command,button); actions.append(button);
        if (server.running) { const restart = element('button','Restart','btn-logout'); restart.disabled = busy.has(server.id); restart.onclick = () => action(server,'restart',restart); actions.append(restart); }
      }
      if (server.state === 'ready') { const manage = element('a','Manage →','manager-link'); manage.href = workspace(server); actions.append(manage); }
      else if (permissions.includes('admin_config')) { const progress = element('a','Progress / retry','manager-link'); progress.href = '/setup'; actions.append(progress); }
      row.append(actions); rows.append(row);
    }
    if (!visible.length) { const empty = element('td',servers.length ? 'No servers match these filters.' : 'No servers are assigned to your account.'); empty.colSpan = 8; const row = element('tr',''); row.append(empty); rows.append(row); }
    const alerts = document.getElementById('overview-alerts'); alerts.replaceChildren();
    const problems = servers.filter(attention); alerts.hidden = !problems.length;
    for (const server of problems) { const link = element('a',server.name + ': ' + (server.error || 'Installation failed. Open progress to review and retry.')); link.href = server.state === 'ready' ? workspace(server) : '/setup'; alerts.append(link); }
    document.getElementById('overview-alert-count').textContent = problems.length;
    const measured = servers.filter(server => Number.isFinite(server.cpu));
    document.getElementById('overview-cpu').textContent = measured.length ? measured.reduce((sum,server)=>sum+server.cpu,0).toFixed(1)+'%' + (measured.length < servers.length ? '+' : '') : '—';
    const ram = servers.filter(server => Number.isFinite(server.ram_process));
    document.getElementById('overview-ram').textContent = ram.length ? (ram.reduce((sum,server)=>sum+server.ram_process,0)/1024).toFixed(2)+' GiB' + (ram.length < servers.length ? '+' : '') : '—';
    document.getElementById('overview-total').textContent = servers.length;
    document.getElementById('overview-online').textContent = servers.filter(s => s.status === 'online').length;
    const known = servers.filter(s => s.players !== null && s.players !== undefined);
    document.getElementById('overview-players').textContent = known.length ? known.reduce((total,s) => total+s.players,0) + (known.length < servers.length ? '+' : '') : '—';
  }
  async function refresh(report = true) {
    if (loading) return; loading = true;
    const button = document.getElementById('overview-refresh'); button.disabled = true;
    try {
      const data = await read('/api/servers');
      const servers = [...(data.legacy_server ? [{id:'',name:data.legacy_server.name,state:'ready',permissions:data.legacy_server.permissions}] : []),...data.servers];
      if (!rows.children.length) render(servers.map(server => ({...server,status:server.state === 'ready' ? 'checking' : server.state}))); 
      // Three concurrent checks keep a host with many instances responsive.
      const results = new Array(servers.length); let next = 0;
      await Promise.all(Array.from({length:Math.min(3,servers.length)},async () => { while (next < servers.length) { const index = next++; results[index] = await inspect(servers[index]); } }));
      snapshots = results; render(snapshots);
      if (report) feedback.textContent = servers.length ? 'Updated ' + new Date().toLocaleTimeString() : 'No servers yet. Create your first server to get started.';
    } catch (error) { feedback.textContent = error.message; }
    finally { loading = false; button.disabled = false; }
  }
  document.getElementById('overview-search').oninput = () => render(snapshots);
  document.getElementById('overview-filter').onchange = () => render(snapshots);
  document.getElementById('overview-storage').onclick = () => { measureStorage = true; refresh(); };
  document.getElementById('overview-refresh').onclick = () => refresh();
  document.getElementById('overview-logout').onclick = async () => { await postJson('/logout',{}); location.href = '/login'; };
  read('/api/me').then(account => { permissions = account.panel_permissions || account.permissions || []; document.getElementById('overview-account').textContent = account.username; document.getElementById('overview-create').hidden = !permissions.includes('admin_config'); return refresh(); }).catch(error => feedback.textContent = error.message);
  timer = setInterval(() => { if (!document.hidden) refresh(); },10000);
  window.addEventListener('pagehide',() => clearInterval(timer));
});
