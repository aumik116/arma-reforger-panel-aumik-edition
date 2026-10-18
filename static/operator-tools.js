// Selected-server tools reuse authenticated requests and the existing config writer.
let playerHistoryOffset = 0;
let operatorPlayersPending = false;
let operatorPlayerSearchTimer;
let startupDirty = false;
let startupPending = false;
let schedulePending = false;
let scheduleReady = false;
let scheduleEditing=null;
let scheduleJobs=[];
let scheduleDefaultRun='';
let scheduleRunCursor=null;
let scheduleRunsOlder=false;
let scheduleRunsRequest=0;

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
    if(!startupDirty){byId('operator-startup-fps').value=data.max_fps;byId('operator-startup-cpus').value=data.resources.cpus;byId('operator-startup-memory-high').value=data.resources.memory_high_mb;byId('operator-startup-memory-max').value=data.resources.memory_max_mb;}
    startupFacts('operator-startup-health',[
      ['Game process',data.running?'Running':'Stopped'],['Service',data.service],
      ['Game executable',data.binary_exists?'Present':'Missing'],['Steam build',data.software.installed_build||'Unavailable'],
      ['VM logical CPUs',data.cpu_count||'Unavailable'],['Resource enforcement',data.resource_supported?'Linux helper · applies on next start':'Preview only; requires Linux'],['Saved FPS cap',data.max_fps||'Uncapped'],['Native performance log','Every 1 second']
    ]);
    startupFacts('operator-startup-paths',[['Game directory',data.server_path],['Configuration',data.config_path],['Profile',data.profile_path],['Logs',data.logs_path]]);
    byId('operator-startup-output').textContent=data.output.length?data.output.join('\n'):'No recent game log output. Open Console after starting the server.';
  }catch(error){byId('operator-startup-feedback').textContent=error.message;}
  finally{startupPending=false;}
}
for(const id of ['operator-startup-fps','operator-startup-cpus','operator-startup-memory-high','operator-startup-memory-max'])byId(id).addEventListener('input',()=>{startupDirty=true;byId('operator-startup-save').disabled=false;});
byId('operator-startup-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=byId('operator-startup-save');button.disabled=true;
  try{await changeFeature('/api/startup',{max_fps:Number(byId('operator-startup-fps').value),cpus:byId('operator-startup-cpus').value.trim(),memory_high_mb:Number(byId('operator-startup-memory-high').value),memory_max_mb:Number(byId('operator-startup-memory-max').value)});startupDirty=false;byId('operator-startup-feedback').textContent='Saved. Applies on the next game-server start.';await loadStartup();}
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
    if(!scheduleEditing&&!byId('schedule-name').value&&!byId('schedule-time').dataset.edited){byId('schedule-time').value=data.default_run;}
    byId('schedule-timezone').textContent='Server clock: '+data.server_time.replace('T',' ')+' · Restart/update: allow 6 minutes for warnings; backup: 1 minute.';
    scheduleDefaultRun=data.default_run;
    scheduleJobs=data.schedules;
    const list=byId('schedule-list');list.replaceChildren();
    for(const job of data.schedules){
      const row=operationElement('div','','operator-row'),info=document.createElement('div');
      info.append(operationElement('strong',job.name),operationElement('small',`${job.action} · ${job.local_run_at.replace('T',' ')} server time · ${job.recurrence&&job.recurrence!=='interval'?job.recurrence+' '+job.local_time+' server time':job.interval_seconds?'Every '+job.interval_seconds/3600+' hours':'Once'} · ${job.enabled?'Enabled':'Paused / completed'}`));
      if(job.warning_error)info.append(operationElement('small','Warning: '+job.warning_error));row.append(info);
      const toggle=operationElement('button',job.enabled?'Pause':'Enable','config-button');toggle.onclick=()=>{toggle.blur();changeSchedule(job.id,{enabled:!job.enabled});};
      const remove=operationElement('button','Remove','config-button');remove.onclick=()=>{if(confirm(`Remove schedule "${job.name}"? This does not interrupt an already running operation.`)){remove.blur();changeSchedule(job.id,{remove:true});}};
      const edit=operationElement('button','Edit','config-button');edit.onclick=()=>editSchedule(job);
      row.append(edit,toggle,remove);list.append(row);
    }
    if(!data.schedules.length)list.append(operationElement('p','No schedules for this server.','feature-note'));
    if(!scheduleRunsOlder)await loadScheduleRuns();
  }catch(error){byId('schedule-feedback').textContent=error.message;}
  finally{schedulePending=false;}
}
byId('schedule-timezone').textContent='Schedules follow the server clock.';
byId('schedule-time').addEventListener('input',()=>byId('schedule-time').dataset.edited='1');
byId('schedule-time').value='';
byId('schedule-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!scheduleReady)return;const button=byId('schedule-save');button.disabled=true;
  try{const repeat=byId('schedule-repeat').value;const data={name:byId('schedule-name').value,action:byId('schedule-action').value,local_run_at:byId('schedule-time').value,interval_seconds:(repeat==='custom'?Number(byId('schedule-custom-hours').value):Number(repeat)||0)*3600,recurrence:['daily','weekly'].includes(repeat)?repeat:'interval'};await changeFeature(scheduleEditing?`/api/schedules/${scheduleEditing}`:'/api/schedules',{...data,...(scheduleEditing?{edit:true}:{})});resetScheduleEdit();byId('schedule-feedback').textContent='Schedule saved on this server.';byId('schedule-name').value='';await loadSchedules();}
  catch(error){byId('schedule-feedback').textContent=error.message;button.disabled=!scheduleReady;}
});
setInterval(()=>{if(!byId('panel-players').hidden)loadOperatorPlayers();if(!byId('panel-scheduler').hidden)loadSchedules();},10000);

function resetScheduleEdit(){scheduleEditing=null;delete byId('schedule-time').dataset.edited;byId('schedule-save').textContent='Create schedule';byId('schedule-cancel-edit').hidden=true;}
function editSchedule(job){
  scheduleEditing=job.id;byId('schedule-name').value=job.name;byId('schedule-action').value=job.action;
  byId('schedule-time').value=job.local_run_at||'';byId('schedule-time').dataset.edited='1';
  const calendar=job.recurrence&&job.recurrence!=='interval';byId('schedule-repeat').value=calendar?job.recurrence:job.interval_seconds?'custom':'0';byId('schedule-custom-hours').value=job.interval_seconds/3600||24;
  byId('schedule-custom-field').hidden=byId('schedule-repeat').value!=='custom';byId('schedule-save').textContent='Save schedule';byId('schedule-cancel-edit').hidden=false;
  byId('schedule-feedback').textContent='Editing '+job.name+'. Saving follows the server clock and enables the schedule. Choose a future first run.';byId('schedule-form').scrollIntoView({block:'nearest'});
}
byId('schedule-repeat').onchange=()=>{byId('schedule-custom-field').hidden=byId('schedule-repeat').value!=='custom';};
byId('schedule-cancel-edit').onclick=()=>{resetScheduleEdit();byId('schedule-name').value='';byId('schedule-feedback').textContent='Edit cancelled.';};
async function loadScheduleRuns(older=false){
  const serial=++scheduleRunsRequest;
  if(!older){scheduleRunsOlder=false;scheduleRunCursor=null;}
  const query=new URLSearchParams({before:older?scheduleRunCursor||0:0,state:byId('schedule-run-state').value,search:byId('schedule-run-search').value});
  try{
    const data=await getFeature('/api/schedules/runs?'+query);if(serial!==scheduleRunsRequest)return;const holder=byId('schedule-runs');if(!older)holder.replaceChildren();
    for(const run of data.runs){const row=operationElement('div','','operator-row');const info=document.createElement('div');info.append(operationElement('strong',`${run.name} · ${run.state}`),operationElement('small','Scheduled '+run.scheduled_for_local+' · started '+run.started_local+' (server time)'),operationElement('small',run.message||'Operation is running…'));row.append(info);if(['failed','interrupted'].includes(run.state)){const retry=operationElement('button','Prepare retry','config-button');retry.onclick=()=>{editSchedule({id:null,name:run.name+' retry',action:run.action,local_run_at:scheduleDefaultRun,interval_seconds:0,recurrence:'interval'});resetScheduleEdit();byId('schedule-feedback').textContent='Prepared a one-off retry 15 minutes ahead. Review and create it; the original schedule is unchanged.';};row.append(retry);}holder.append(row);}
    if(!holder.children.length)holder.append(operationElement('p','No matching scheduled runs.','feature-note'));
    scheduleRunCursor=data.next_cursor;byId('schedule-runs-more').hidden=!data.next_cursor;if(older)scheduleRunsOlder=true;
  }catch(error){byId('schedule-feedback').textContent=error.message;}
}
byId('schedule-run-state').onchange=()=>loadScheduleRuns();
byId('schedule-runs-more').onclick=()=>loadScheduleRuns(true);
