// Use full page navigation when switching to discard old instance form/log state.
document.addEventListener('DOMContentLoaded', () => {
  const setupPage = document.body.hasAttribute('data-setup-page');
  const dialog = document.getElementById('instances-dialog');
  const switcher = document.getElementById('instance-switcher');
  const form = document.getElementById('create-instance');
  const result = document.getElementById('instance-result');
  let cloneSource=new URLSearchParams(location.search).get('clone')||'';
  let cloneRequest=0,cloneLoading=false;
  let admin = false, jobId = '', poll = null, startupId = '';
  const go = id => { location.href = id ? '/?server=' + encodeURIComponent(id) : '/?legacy=1'; };
  function option(value, label) { const node = document.createElement('option'); node.value = value; node.textContent = label; return node; }
  async function load() {
    const response = await fetch('/api/servers');
    if (!response.ok) throw new Error('Could not load servers');
    const data = await response.json();
    switcher.replaceChildren();
    if (data.legacy_server) switcher.append(option('', data.legacy_server.name));
    const copy = document.getElementById('instance-copy'), copyValue = copy.value;
    copy.replaceChildren(option('', 'Defaults'));
    if (data.legacy_server) copy.append(option('__existing__', 'Copy existing server settings and mods'));
    const list = document.getElementById('instance-list'); list.replaceChildren();
    for (const server of data.servers) {
      if (server.state === 'ready') {
        switcher.append(option(server.id, server.name)); copy.append(option(server.id, server.name));
      }
      const row = document.createElement('div'); row.className = 'instance-row';
      const title = document.createElement('strong'); title.textContent = server.name;
      const detail = document.createElement('span'); detail.className = 'feature-note';
      detail.textContent = `${server.state} · Game ${server.game_port} · Query ${server.query_port} · RCON ${server.rcon_port}`;
      row.append(title, detail);
      if (server.state === 'ready') { const manage = document.createElement('button'); manage.textContent = 'Manage'; manage.onclick = () => go(server.id); row.append(manage); }
      else if (admin) { const progress = document.createElement('button'); progress.textContent = 'Progress / retry'; progress.onclick = () => { jobId = server.id; showJob().catch(error => result.textContent = error.message); }; row.append(progress); }
      if (admin) {
        const remove = document.createElement('button'); remove.textContent = 'Remove';
        remove.onclick = async () => {
          const confirmation = prompt(`Stop and remove ${server.name}? Files will be archived on the VM. Type its ID: ${server.id}`);
          if (confirmation === null) return;
          remove.disabled = true;
          try {
            const response = await postJson(`/api/servers/${encodeURIComponent(server.id)}/delete`, {confirm_id:confirmation});
            const body = await response.json(); if (!response.ok) throw new Error(body.error);
            if (selectedServerId === server.id) { location.href = '/servers'; return; }
            if (jobId === server.id) jobId = '';

            result.textContent = body.archived ? `Server removed. Files retained at ${body.archived}` : 'Server removed.';
            await load();
          } catch (error) { result.textContent = error.message; remove.disabled = false; }
        }; row.append(remove);
      }
      list.append(row);
    }
    if (!data.servers.length) list.textContent = data.legacy_server ? 'No managed instances yet. Select your existing server above.' : 'No servers yet. Create your first server below.';
    if (selectedServerId && !data.servers.some(s => s.id === selectedServerId && s.state === 'ready')) {
      switcher.append(option(selectedServerId, 'Selected instance unavailable'));
    }
    switcher.value = selectedServerId; copy.value = copyValue;
    if(cloneSource){copy.value=cloneSource;cloneSource='';await prepareClone(true);}
  }
  async function prepareClone(suggest=false){
    const source=document.getElementById('instance-copy').value,serial=++cloneRequest;
    if(!source){cloneLoading=false;result.textContent='';if(setupPage)document.querySelector('#create-instance h3').textContent='Create server';return;}
    cloneLoading=true;
    let data;try{data=await readJson(await fetch('/api/clone-source',{headers:{'X-Server-ID':source==='__existing__'?'':source}}));}finally{if(serial===cloneRequest)cloneLoading=false;}
    if(serial!==cloneRequest)return;
    document.getElementById('instance-players').value=data.max_players;document.getElementById('instance-fps').value=data.max_fps;
    if(suggest){
      document.getElementById('instance-name').value=(data.name+' copy').slice(0,80);
      let base=(source==='__existing__'?'server':source).slice(0,24),id=base+'-copy',suffix=2;
      while(Array.from(document.getElementById('instance-copy').options).some(option=>option.value===id)){id=base+'-copy-'+suffix++;}
      document.getElementById('instance-id').value=id;
      for(const name of ['game_port','query_port','rcon_port'])form.elements[name].value='';
    }
    result.textContent=`Cloning ${data.name}: ${data.mod_count} mods and its scenario/settings. Ports are allocated separately. Passwords, game admins and saves are not copied.`;
    if(setupPage)document.querySelector('#create-instance h3').textContent='Clone server';
  }
  document.getElementById('instance-copy').onchange=()=>prepareClone().catch(error=>result.textContent=error.message);
  async function showJob() {
    const response = await fetch(`/api/servers/${encodeURIComponent(jobId)}/provision`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Could not load provisioning progress');
    result.replaceChildren(document.createTextNode(job.message));
    const output = document.getElementById('instance-job-output'); output.hidden = false;
    output.textContent = (job.startup_output ? 'STARTUP DIAGNOSTICS\n' + job.startup_output + '\n\nINSTALLATION OUTPUT\n' : '') + job.output;
    if (job.state === 'failed' || job.state === 'interrupted') {
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn-logout'; retry.textContent = 'Retry installation';
      retry.onclick = async () => {
        retry.disabled = true;
        try { const res = await postJson(`/api/servers/${encodeURIComponent(jobId)}/provision/retry`, {}); const body = await res.json(); if (!res.ok) throw new Error(body.error); await showJob(); }
        catch (error) { result.textContent = error.message; }
      }; result.append(document.createTextNode(' '), retry);
    }
    if (job.state === 'ready') { const readyId = jobId; jobId = ''; await load(); if (setupPage) go(readyId); }
  }
  document.getElementById('manage-instances').onclick = () => { if (!dialog.open) dialog.showModal(); load().catch(error => result.textContent = error.message); };
  document.getElementById('close-instances').onclick = () => dialog.close();
  switcher.onchange = () => go(switcher.value);
  form.onsubmit = async event => {
    event.preventDefault();if(cloneLoading){result.textContent='Wait for the source configuration to load.';return;} const submit = form.querySelector('[type=submit]'); submit.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(form));
      for (const key of ['max_players', 'max_fps', 'game_port', 'query_port', 'rcon_port']) { if (data[key] === '') delete data[key]; else data[key] = Number(data[key]); }
      const response = await postJson('/api/servers', data), body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Creation failed');
      jobId = body.server_id; form.reset(); await load(); await showJob();
    } catch (error) { result.textContent = error.message; await load().catch(() => {}); }
    finally { submit.disabled = false; }
  };
  fetch('/api/me').then(response => response.json()).then(async account => {
    admin = (account.panel_permissions || account.permissions || []).includes('users'); form.hidden = !admin; await load();
    jobId=new URLSearchParams(location.search).get('server')||'';if(jobId)await showJob();
  }).catch(error => result.textContent = error.message);
  poll = setInterval(() => { if (dialog.open && jobId) showJob().catch(error => result.textContent = error.message); }, 2500);
  window.addEventListener('pagehide', () => clearInterval(poll));
});
