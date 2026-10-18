// Selected-server tools reuse authenticated requests and the existing config writer.
let playerHistoryOffset = 0;
let operatorPlayersPending = false;
let operatorPlayerSearchTimer;
let startupDirty = false;
let startupPending = false;
let schedulePending = false;
let scheduleReady = false;

function operationElement(tag, text, className='') {
  const el=document.createElement(tag);el.textContent=text;el.className=className;return el;
}
const operationDate = value => value ? new Date(value*1000).toLocaleString() : '—';

async function loadOperatorPlayers(force=false) {
  if (byId('panel-players').hidden || operatorPlayersPending) return;
  if (!force && byId('operator-player-rows').contains(document.activeElement)) return;
  operatorPlayersPending=true;
  try {
    const history=!byId('section-player-history').hidden;
    const search=byId('operator-player-search').value.trim();
    const [live,stored,access] = await Promise.all([
      history ? null : getFeature('/api/players'),
      history ? getFeature(`/api/players/history?q=${encodeURIComponent(search)}&offset=${playerHistoryOffset}`) : null,
      can('admin_config') ? getFeature('/api/players/admins') : null
    ]);
    const rows=history ? stored.players : live.players.filter(p=>`${p.name} ${p.identity}`.toLowerCase().includes(search.toLowerCase()));
    byId('operator-player-status').textContent=history ? 'History for the selected server' : live.message;
    const body=byId('operator-player-rows');body.replaceChildren();
    for(const player of rows) {
      const row=document.createElement('tr');
      const identity=String(player.identity);
      row.append(operationElement('td',player.name));
      const idCell=document.createElement('td');idCell.append(operationElement('code',identity));row.append(idCell);
      row.append(operationElement('td',operationDate(player.first_seen)),operationElement('td',history?operationDate(player.last_seen):'Connected now'));
      const actions=document.createElement('td');
      const copy=operationElement('button','Copy identity','config-button');copy.type='button';
      copy.onclick=async()=>{try{await navigator.clipboard.writeText(identity);byId('operator-player-feedback').textContent='Identity copied';}catch(_){byId('operator-player-feedback').textContent='Copy this identity manually: '+identity;}};
      actions.append(copy);
      if(access && /^(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|\d{17})$/i.test(identity)) {
        const granted=access.admins.some(id=>id.toLowerCase()===identity.toLowerCase());
        const button=operationElement('button',granted?'Remove game admin':'Grant game admin','config-button');button.type='button';
        button.onclick=async()=>{
          if(!confirm(`${granted?'Remove':'Grant'} in-game administrator access for ${player.name}? A game-server restart is required.`))return;
          button.disabled=true;
          try{await changeFeature('/api/players/admin',{identity,grant:!granted,revision:access.revision});byId('operator-player-feedback').textContent='Game administrator list saved. Restart the server to apply it.';await loadOperatorPlayers(true);}
          catch(error){byId('operator-player-feedback').textContent=error.message;}
          finally{button.disabled=false;}
        };
        actions.append(button);
      }
      row.append(actions);body.append(row);
    }
    if(!rows.length){const cell=operationElement('td',history?'No matching player history yet.':'No matching connected players.');cell.colSpan=5;const row=document.createElement('tr');row.append(cell);body.append(row);}
    byId('player-history-previous').disabled=!history||playerHistoryOffset===0;
    byId('player-history-next').disabled=!history||stored.next_offset===null;
    byId('player-history-page').textContent=history?`Page ${playerHistoryOffset/50+1}`:`${rows.length} connected`;
  } catch(error) {byId('operator-player-feedback').textContent=error.message;}
  finally{operatorPlayersPending=false;}
}

function playerHistoryPage(direction){playerHistoryOffset=Math.max(0,playerHistoryOffset+direction*50);loadOperatorPlayers(true);}
byId('operator-player-search').addEventListener('input',()=>{clearTimeout(operatorPlayerSearchTimer);playerHistoryOffset=0;operatorPlayerSearchTimer=setTimeout(()=>loadOperatorPlayers(true),250);});

function startupFacts(id, values){const list=byId(id);list.replaceChildren();for(const[label,value]of values){list.append(operationElement('dt',label),operationElement('dd',String(value)));}}
async function loadStartup(){
  if(startupPending||!can('admin_config'))return;
  startupPending=true;
  try{
    const data=await getFeature('/api/startup');
    if(!startupDirty)byId('operator-startup-fps').value=data.max_fps;
    startupFacts('operator-startup-health',[
      ['Game process',data.running?'Running':'Stopped'],['Service',data.service],
      ['Game executable',data.binary_exists?'Present':'Missing'],['Steam build',data.software.installed_build||'Unavailable'],
      ['Saved FPS cap',data.max_fps||'Uncapped'],['Native performance log','Every 1 second']
    ]);
    startupFacts('operator-startup-paths',[['Game directory',data.server_path],['Configuration',data.config_path],['Profile',data.profile_path],['Logs',data.logs_path]]);
    byId('operator-startup-output').textContent=data.output.length?data.output.join('\n'):'No recent game log output. Open Console after starting the server.';
  }catch(error){byId('operator-startup-feedback').textContent=error.message;}
  finally{startupPending=false;}
}
byId('operator-startup-fps').addEventListener('input',()=>{startupDirty=true;byId('operator-startup-save').disabled=false;});
byId('operator-startup-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=byId('operator-startup-save');button.disabled=true;
  try{await changeFeature('/api/startup',{max_fps:Number(byId('operator-startup-fps').value)});startupDirty=false;byId('operator-startup-feedback').textContent='Saved. Applies on the next game-server start.';await loadStartup();}
  catch(error){byId('operator-startup-feedback').textContent=error.message;button.disabled=false;}
});

async function changeSchedule(id,changes){
  try{await changeFeature(`/api/schedules/${id}`,changes);await loadSchedules();}
  catch(error){byId('schedule-feedback').textContent=error.message;}
}
async function loadSchedules(){
  if(schedulePending||!can('admin_config'))return;
  if(byId('schedule-list').contains(document.activeElement))return;
  schedulePending=true;
  try{
    const data=await getFeature('/api/schedules');
    byId('scheduler-support').textContent=!data.supported?'This preview cannot execute schedules. Use the Linux panel service for scheduling.':data.worker_alive?'Scheduler active. Jobs are stored on this VM and run while its panel service is active.':'Scheduler worker is not active. Restart the panel service and inspect its service log before scheduling work.';
    scheduleReady=!!(data.supported&&data.worker_alive);
    byId('schedule-save').disabled=!scheduleReady;
    const list=byId('schedule-list');list.replaceChildren();
    for(const job of data.schedules){
      const row=operationElement('div','','operator-row'),info=document.createElement('div');
      info.append(operationElement('strong',job.name),operationElement('small',`${job.action} · ${operationDate(job.run_at)} · ${job.interval_seconds?'Every '+job.interval_seconds/3600+' hours':'Once'} · ${job.enabled?'Enabled':'Paused / completed'}`));
      if(job.warning_error)info.append(operationElement('small','Warning: '+job.warning_error));row.append(info);
      const toggle=operationElement('button',job.enabled?'Pause':'Enable','config-button');toggle.onclick=()=>{toggle.blur();changeSchedule(job.id,{enabled:!job.enabled});};
      const remove=operationElement('button','Remove','config-button');remove.onclick=()=>{if(confirm(`Remove schedule "${job.name}"? This does not interrupt an already running operation.`)){remove.blur();changeSchedule(job.id,{remove:true});}};
      row.append(toggle,remove);list.append(row);
    }
    if(!data.schedules.length)list.append(operationElement('p','No schedules for this server.','feature-note'));
    const runs=byId('schedule-runs');runs.replaceChildren();
    for(const run of data.runs){const row=operationElement('div','','operator-row'),info=document.createElement('div');info.append(operationElement('strong',`${run.name} · ${run.state}`),operationElement('small',operationDate(run.started)),operationElement('small',run.message||'Operation is running…'));row.append(info);runs.append(row);}
    if(!data.runs.length)runs.append(operationElement('p','No scheduled runs yet.','feature-note'));
  }catch(error){byId('schedule-feedback').textContent=error.message;}
  finally{schedulePending=false;}
}
byId('schedule-timezone').textContent=`Times use your browser timezone (${Intl.DateTimeFormat().resolvedOptions().timeZone}). Restart/update: allow at least 6 minutes for warnings. Config backup: allow 1 minute.`;
const firstRun=new Date(Date.now()+15*60000);firstRun.setMinutes(firstRun.getMinutes()-firstRun.getTimezoneOffset());byId('schedule-time').value=firstRun.toISOString().slice(0,16);
byId('schedule-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!scheduleReady)return;const button=byId('schedule-save');button.disabled=true;
  try{const data={name:byId('schedule-name').value,action:byId('schedule-action').value,run_at:new Date(byId('schedule-time').value).getTime()/1000,interval_seconds:Number(byId('schedule-repeat').value)*3600};await changeFeature('/api/schedules',data);byId('schedule-feedback').textContent='Schedule created on this server.';byId('schedule-name').value='';await loadSchedules();}
  catch(error){byId('schedule-feedback').textContent=error.message;button.disabled=!scheduleReady;}
});
setInterval(()=>{if(!byId('panel-players').hidden)loadOperatorPlayers();if(!byId('panel-scheduler').hidden)loadSchedules();},10000);
