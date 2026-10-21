document.addEventListener('DOMContentLoaded', () => {
  const rows = document.getElementById('overview-rows'), feedback = document.getElementById('overview-feedback');
  let loading = false, permissions = [], timer;
  const busy = new Set();
  let snapshots = [], measureStorage = false, events = [], eventError = '', host = null;
  const transitions = [];
  const charts = [];
  function chart(id, labels, percent) {
    if (typeof Chart === 'undefined') {
      document.getElementById('fleet-chart-note').textContent = 'Charts could not load. Current readings are still available below.';
      return null;
    }
    const instance = new Chart(document.getElementById(id), {
      type:'line', data:{datasets:labels.map(label => ({label, data:[], borderWidth:2, pointRadius:context => context.dataIndex === context.dataset.data.length - 1 ? 2 : 0, pointHitRadius:12, spanGaps:false, tension:0.2}))},
      options:{responsive:true, maintainAspectRatio:false, animation:false, parsing:false,
        interaction:{mode:'index', intersect:false},
        plugins:{legend:{display:labels.length > 1}, tooltip:{callbacks:{title:items => new Date(items[0].parsed.x).toLocaleTimeString(), label:item => `${item.dataset.label}: ${item.parsed.y}${percent ? '%' : ''}`}}},
        scales:{x:{type:'linear', ticks:{maxTicksLimit:5, callback:value => new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}}, y:{min:0, ...(percent ? {max:100} : {ticks:{precision:0}})}}}
    });
    charts.push(instance); return instance;
  }
  const playerChart = chart('fleet-player-chart', ['Players'], false);
  const hostChart = chart('fleet-host-chart', ['CPU', 'Memory'], true);
  function themeCharts() {
    const style = getComputedStyle(document.documentElement);
    for (const instance of charts) {
      instance.data.datasets.forEach((set,index) => { set.borderColor = style.getPropertyValue(index ? '--online' : '--accent').trim(); set.backgroundColor = set.borderColor; });
      instance.options.plugins.legend.labels = {color:style.getPropertyValue('--text').trim(), boxWidth:12, boxHeight:2};
      for (const axis of Object.values(instance.options.scales)) { axis.ticks.color = style.getPropertyValue('--muted').trim(); axis.grid = {color:style.getPropertyValue('--border').trim()}; }
      instance.update('none');
    }
  }
  themeCharts();
  document.addEventListener('panel-theme-change', themeCharts);
  function sample(chart, values, now) {
    if (!chart) return;
    chart.data.datasets.forEach((set,index) => {
      const last = set.data.at(-1);
      if (last && now - last.x > 30000) set.data.push({x:last.x + 10000,y:null});
      set.data.push({x:now, y:Number.isFinite(values[index]) ? values[index] : null});
      set.data = set.data.filter(point => point.x >= now - 1800000).slice(-181);
    });
    chart.options.scales.x.min = now - 1800000; chart.options.scales.x.max = now;
    chart.update('none');
  }
  function renderEvents() {
    const target = document.getElementById('fleet-events'); target.replaceChildren();
    const names = {api_start:'Start requested', api_stop:'Stop requested', api_restart:'Restart requested', software_update:'Server update requested', server_delete:'Server removed', servers_create:'Server created', server_provision_retry:'Installation retried', config_editor_save:'Configuration saved', users_save:'Account permissions updated', players_moderate:'Player moderation', players_admin_save:'Server admins updated'};
    const relevant = events.filter(event => !['login','account_preferences_save','config_editor_validate','files_preview','software_check'].includes(event.action));
    const items = [...relevant.map(event => {
      const serverName = event.details.server_id ? snapshots.find(server => server.id === event.details.server_id)?.name || event.details.server_id : '';
      return {ts:event.ts, text:`${serverName ? serverName + ' · ' : ''}${names[event.action] || event.action.replace(/^api_/, '').replaceAll('_',' ')} · ${event.outcome} · ${event.actor}`, failed:event.outcome === 'failed'};
    }), ...transitions].sort((a,b) => b.ts-a.ts).slice(0,8);
    for (const item of items) {
      const row = element('div','', 'fleet-event');
      const time = element('time', new Date(item.ts*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}));
      time.dateTime = new Date(item.ts*1000).toISOString();
      row.append(element('span',item.text,item.failed ? 'fleet-event-error' : ''), time); target.append(row);
    }
    document.getElementById('fleet-alert-status').textContent = eventError || (items.length ? 'Recent events · no player join/leave notices' : 'No recent alerts');
  }
  const attention = server => ['failed','unavailable'].includes(server.status);
  const storageSize = bytes => (bytes / 1e9).toFixed(2) + ' GB';
  const workspace = server => server.id ? '/?server=' + encodeURIComponent(server.id) : '/?legacy=1';
  function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
  async function read(url, id) {
    return readJson(await fetch(url, {headers:id === undefined ? {} : {'X-Server-ID':id}, signal:AbortSignal.timeout(8000)}));
  }
  async function inspect(server) {
    if (server.state !== 'ready') return {...server, status:server.state};
    try {
      const status = await read('/api/status', server.id);
      let players = null;
      if (!status.running) players = 0;
      else { try { const roster = await read('/api/players', server.id); if (roster.available) players = roster.players.length; } catch (_) {} }
      let preview = null;
      try {
        const image = await read('/api/scenario-preview', server.id);
        if (image.scenario_id === status.scenario_id) preview = image;
      } catch (_) {} // Workshop failures must not hide server status or controls.
      let storage = null;
      if (measureStorage) { try { storage = await read('/api/storage', server.id); } catch (_) {} }
      return {...server, storage, preview, ...status, name:status.server_name || server.name, status:status.running ? 'online' : 'offline', players};
    } catch (error) { return {...server, status:'unavailable', error:error.message}; }
  }
  async function action(server, command, button) {
    if (busy.has(server.id)) return;
    if (command !== 'start' && !confirm(`${command === 'stop' ? 'Stop' : 'Restart'} ${server.name}? Connected players will be disconnected.`)) return;
    busy.add(server.id); button.disabled = true;
    try {
      await controlServer(command, server.id);
      feedback.textContent = `${server.name}: ${command} requested.`;
    } catch (error) { feedback.textContent = error.message; }
    finally { busy.delete(server.id); button.disabled = false; await refresh(false); }
  }
  function render(servers) {
    const focused = rows.contains(document.activeElement) ? document.activeElement : null;
    const focusedServer = focused?.closest('[data-server-id]')?.dataset.serverId;
    const focusedAction = focused?.dataset.action;
    const expanded = new Set(Array.from(rows.querySelectorAll('details[open]')).map(menu => menu.closest('[data-server-id]').dataset.serverId));
    rows.replaceChildren();
    const query = document.getElementById('overview-search').value.trim().toLowerCase();
    const filter = document.getElementById('overview-filter').value;
    const visible = servers.filter(server =>
      [server.name, server.ip, server.port, server.game_port, server.query_port].join(' ').toLowerCase().includes(query) &&
      (filter === 'all' || filter === server.status || filter === 'attention' && attention(server) || filter === 'installing' && ['provisioning','registered','installing'].includes(server.status)));
    for (const server of visible) {
      const row = element('article', '', 'fleet-server-card'); row.dataset.serverId = server.id;
      const art = element('div', '', 'fleet-server-art');
      const fallback = element('span', server.preview?.status === 'pending' ? 'Loading preview…' : 'No preview', 'fleet-art-fallback');
      art.append(fallback);
      if (server.preview?.thumbnail) {
        const image = element('img', ''); image.alt = '';
        image.loading = 'lazy'; image.decoding = 'async'; image.referrerPolicy = 'no-referrer';
        image.onload = () => { fallback.hidden = true; };
        image.onerror = () => { image.remove(); fallback.hidden = false; fallback.textContent = 'No preview'; };
        image.src = server.preview.thumbnail; art.append(image);
      }
      row.append(art);
      const heading = element('div','', 'fleet-card-heading');
      heading.append(element('span',server.status,'server-state state-' + server.status));
      row.append(heading);
      row.append(element('span',server.uptime && server.running ? server.uptime : '—', 'fleet-uptime'));
      const build = element('span', '', 'fleet-build'); build.dataset.softwareServer = server.id; heading.append(build);
      const title = element('h3','');
      const link = element('a',server.name,'fleet-server-title');
      link.href = server.state === 'ready' ? workspace(server) : '/setup?server='+encodeURIComponent(server.id);
      link.dataset.action = 'open'; title.append(link); row.append(title);
      row.append(element('p',server.map || (server.state === 'ready' ? 'Scenario unavailable' : 'Preparing server'), 'fleet-map'));
      row.append(element('p',server.ip && server.ip !== '—' ? server.ip + ':' + (server.port || server.game_port || '—') : 'Game ' + (server.port || server.game_port || '—') + ' · Query ' + (server.query_port || '—'), 'fleet-address'));
      if (server.error) row.append(element('p',server.error,'fleet-event-error'));
      const stats = element('dl','', 'fleet-card-stats');
      for (const [label,value] of [['Players',server.players ?? '—'],['CPU',Number.isFinite(server.cpu) ? server.cpu.toFixed(1)+'%' : '—'],['Memory',Number.isFinite(server.ram_process) ? (server.ram_process/1024).toFixed(2)+' GiB' : '—']]) {
        const stat = element('div',''); stat.append(element('dt',label),element('dd',value)); stats.append(stat);
      }
      row.append(stats);
      if (measureStorage) {
        const storage = server.storage;
        row.append(element('p','Storage · ' + (storage && Number.isFinite(storage.total_bytes) ? storageSize(storage.total_bytes) + (storage.status === 'partial' ? ' (partial)' : '') : storage?.status === 'pending' ? 'Measuring…' : 'Unavailable'), 'fleet-storage'));
      }
      const actions = element('div','', 'manager-actions');
      if ((server.permissions || []).includes('control') && ['online','offline'].includes(server.status)) {
        const command = server.running ? 'stop' : 'start';
        const button = element('button',server.running ? 'Stop' : 'Start','btn-logout action-' + command); button.disabled = busy.has(server.id); button.onclick = () => action(server,command,button); actions.append(button);
        if (server.running) { const restart = element('button','Restart','btn-logout action-restart'); restart.disabled = busy.has(server.id); restart.onclick = () => action(server,'restart',restart); actions.append(restart); }
      }
      if (server.state === 'ready') { const manage = element('a','Open','manager-link'); manage.href = workspace(server); actions.prepend(manage); }
      else if (permissions.includes('admin_config')) { const progress = element('a','Progress / retry','manager-link'); progress.href = '/setup?server='+encodeURIComponent(server.id); actions.append(progress); }
      const more = element('details','','fleet-more'); more.open = expanded.has(server.id);
      const summary = element('summary','More'); summary.dataset.action = 'more'; more.append(summary);
      const menu = element('div','','fleet-more-menu'); more.append(menu);
      if(server.state==='ready'&&(server.permissions||[]).includes('admin_config')){const startup=element('a','Startup','manager-link');startup.href=workspace(server)+'#startup';menu.append(startup);}
      if(server.id&&permissions.includes('admin_config')){const remove=element('button','Remove','btn-logout');remove.disabled=busy.has(server.id);remove.onclick=async()=>{
        const confirmId=prompt('Remove '+server.name+'? Files are retained on the VM. Type its ID: '+server.id);if(confirmId===null)return;
        busy.add(server.id);remove.disabled=true;
        try{const response=await postJson('/api/servers/'+encodeURIComponent(server.id)+'/delete',{confirm_id:confirmId});const body=await response.json();if(!response.ok)throw new Error(body.error);feedback.textContent=server.name+': removed. Files retained on the VM.';}catch(error){feedback.textContent=error.message;}finally{busy.delete(server.id);await refresh(false);}
      };menu.append(remove);}
      if (menu.children.length) actions.append(more);
      actions.querySelectorAll('button,a').forEach(node => { node.dataset.action = node.textContent; });
      row.append(actions); rows.append(row);
    }
    if (!visible.length) rows.append(element('p',servers.length ? 'No servers match these filters.' : permissions.includes('admin_config') ? 'No servers yet. Create your first server to get started.' : 'No servers are assigned to your account.', 'fleet-empty'));
    if (focusedAction) {
      const card = Array.from(rows.children).find(node => node.dataset.serverId === focusedServer);
      Array.from(card?.querySelectorAll('[data-action]') || []).find(node => node.dataset.action === focusedAction)?.focus({preventScroll:true});
    }
    document.dispatchEvent(new Event('fleet-rows-rendered'));
    const alerts = document.getElementById('overview-alerts'); alerts.replaceChildren();
    const problems = servers.filter(attention); alerts.hidden = !problems.length;
    for (const server of problems) { const link = element('a',server.name + ': ' + (server.error || 'Installation failed. Open progress to review and retry.')); link.href = server.state === 'ready' ? workspace(server) : '/setup?server='+encodeURIComponent(server.id); alerts.append(link); }
    document.getElementById('overview-alert-count').textContent = problems.length;
    document.getElementById('overview-cpu').textContent = Number.isFinite(host?.cpu_host) ? host.cpu_host.toFixed(1)+'%' : '—';
    document.getElementById('overview-ram').textContent = host?.ram_total > 0 ? (100*host.ram_used/host.ram_total).toFixed(1)+'%' : '—';
    document.getElementById('overview-ram-detail').textContent = host?.ram_total > 0 ? (host.ram_used/1024).toFixed(1)+' / '+(host.ram_total/1024).toFixed(1)+' GiB' : 'Waiting for a reading';
    document.getElementById('overview-total').textContent = servers.length;
    document.getElementById('overview-online').textContent = servers.filter(s => s.status === 'online').length;
    const known = servers.filter(s => s.players !== null && s.players !== undefined);
    document.getElementById('overview-players').textContent = !servers.length ? '0' : known.length ? known.reduce((total,s) => total+s.players,0) + (known.length < servers.length ? '+' : '') : '—';
  }
  let navigationServers = [];
  const switcher = document.getElementById('fleet-switcher');
  function updateNavigation() {
    const server = navigationServers.find(item => item.id === switcher.value);
    document.querySelectorAll('[data-fleet-panel]').forEach(link => {
      const allowed = server && (server.permissions || []).includes(link.dataset.fleetPermission);
      link.hidden = !allowed;
      if (allowed) link.href = workspace(server) + '#' + link.dataset.fleetPanel;
      else link.removeAttribute('href');
    });
  }
  switcher.onchange = updateNavigation;
  document.getElementById('fleet-nav-toggle').onclick = event => {
    const open = document.body.classList.toggle('navigation-open');
    event.currentTarget.setAttribute('aria-expanded', String(open));
  };
  async function refresh(report = true) {
    if (loading) return; loading = true;
    const button = document.getElementById('overview-refresh'); button.disabled = true;
    try {
      const data = await read('/api/servers');
      const servers = [...(data.legacy_server ? [{id:'',name:data.legacy_server.name,state:'ready',permissions:data.legacy_server.permissions}] : []),...data.servers];
      const previousSelection = switcher.value;
      navigationServers = servers.filter(server => server.state === 'ready');
      switcher.replaceChildren();
      for (const server of navigationServers) {
        const option = element('option', server.name); option.value = server.id; switcher.append(option);
      }
      switcher.disabled = !navigationServers.length;
      if (!navigationServers.length) switcher.append(element('option', 'No ready servers'));
      else if (navigationServers.some(server => server.id === previousSelection)) switcher.value = previousSelection;
      updateNavigation();
      const activityServer = servers.find(server => (server.permissions || []).includes('activity'));
      const canReadActivity = permissions.includes('activity') || !!activityServer;
      const hostResult = await Promise.allSettled([read('/api/host-metrics'), canReadActivity ? read('/api/activity', permissions.includes('activity') ? undefined : activityServer.id) : Promise.resolve(null)]);
      host = hostResult[0].status === 'fulfilled' ? hostResult[0].value : null;
      const activity = hostResult[1];
      events = activity.status === 'fulfilled' ? activity.value?.events || [] : [];
      eventError = activity.status === 'rejected' ? 'Activity unavailable; showing observed status changes' : !canReadActivity ? 'Showing observed status changes; activity history requires permission' : '';
      if (!rows.children.length) render(servers.map(server => ({...server,status:server.state === 'ready' ? 'checking' : server.state}))); 
      // Three concurrent checks keep a host with many instances responsive.
      const results = new Array(servers.length); let next = 0;
      await Promise.all(Array.from({length:Math.min(3,servers.length)},async () => { while (next < servers.length) { const index = next++; results[index] = await inspect(servers[index]); } }));
      for (const server of results) {
        const previous = snapshots.find(item => item.id === server.id);
        if (previous && previous.status !== server.status && previous.status !== 'checking') {
          transitions.unshift({ts:Date.now()/1000, text:`${server.name} · ${previous.status} → ${server.status}`, failed:attention(server)});
        }
      }
      transitions.splice(20);
      snapshots = results;
      const now = Date.now();
      sample(playerChart, [results.every(server => Number.isFinite(server.players)) ? results.reduce((sum,server) => sum+server.players,0) : null], now);
      sample(hostChart, [host?.cpu_host, host?.ram_total > 0 ? 100*host.ram_used/host.ram_total : null], now);
      render(snapshots); renderEvents();
      if (report) feedback.textContent = servers.length ? 'Updated ' + new Date().toLocaleTimeString() : permissions.includes('admin_config') ? 'No servers yet. Create your first server to get started.' : 'No servers are assigned to your account.';
    } catch (error) { feedback.textContent = 'Refresh failed · ' + error.message + '. Displayed server readings may be out of date.'; host = null; sample(playerChart,[null],Date.now()); sample(hostChart,[null,null],Date.now()); }
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
