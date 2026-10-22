// Unit events use the same account/session and unit boundaries as the roster.
(() => {
  const el=id=>document.getElementById(id), esc=escHtml;
  const dialog=el('event-dialog'), form=el('event-form');
  let context=null, operations=null, eventDetail=null, save=null, baseline='', saving=false, generation=0, reportGeneration=0, eventGeneration=0;
  const browserZone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  const today=new Date();
  const month=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}`;
  el('operations-month').value=month;el('attendance-month').value=month;el('operations-timezone').value=browserZone;
  const read=async url=>readJson(await fetch(url));
  const write=async(url,data)=>readJson(await postJson(url,data));
  const base=()=>`/api/units/${context.unitId}`;
  const message=text=>{el('units-feedback').textContent=text;};
  const zone=()=>el('operations-timezone').value.trim()||browserZone;
  const query=month=>new URLSearchParams({month,timezone:zone()});
  const serverName=id=>context.listing.servers.find(s=>s.id===id)?.name||'Unavailable server';
  const format=(timestamp,tz=zone())=>new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short',timeZone:tz}).format(new Date(timestamp*1000));
  const localValue=(timestamp,tz)=>{const parts=new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(timestamp*1000));const p=Object.fromEntries(parts.map(p=>[p.type,p.value]));return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;};
  const field=(label,name,value='',type='text')=>`<label class="unit-field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}"></label>`;
  const sign=()=>JSON.stringify([...new FormData(form)]);
  const close=()=>{if(saving)return;if(sign()!==baseline&&!confirm('Discard unsaved event changes?'))return;dialog.close();};
  el('event-dialog-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  function open(title,html,handler=null){
    if(dialog.open)dialog.close();
    el('event-dialog-title').textContent=title;el('event-dialog-body').innerHTML=html;el('event-dialog-error').textContent='';
    el('event-save').hidden=!handler;el('event-save').textContent='Save changes';save=handler;dialog.showModal();baseline=sign();
  }
  form.onsubmit=async e=>{e.preventDefault();if(saving||!save)return;saving=true;el('event-save').disabled=true;
    try{await save();dialog.close();await refresh();message('Changes saved.');}catch(error){el('event-dialog-error').textContent=error.message;}
    finally{saving=false;el('event-save').disabled=false;}
  };
  function eventLink(event){return `<button type="button" class="event-card" data-event="${event.id}"><strong>${esc(event.name)}</strong><span>${esc(format(event.starts))} · ${esc(event.category)}</span><small>${esc(serverName(event.server_id))} · ${event.state==='cancelled'?'Cancelled':event.state==='finalized'?'Finalized':event.ends<Date.now()/1000?'Needs review':event.starts<Date.now()/1000?'In progress':'Scheduled'}${event.recurrence!=='none'?' · Repeats':''}${!event.tracked?' · No attendance':''}</small></button>`;}
  function bindEvents(root){root.querySelectorAll('[data-event]').forEach(button=>button.onclick=()=>openEvent(Number(button.dataset.event)));}
  function renderDashboard(){
    const s=operations.summary;
    el('unit-dashboard-content').innerHTML=`<div class="unit-summary">${[['Members',s.members],['Active',s.active],['Reserve',s.reserve],['LOA',s.loa],['Open billets',s.vacancies],['Unassigned',s.unassigned]].map(([label,count])=>`<span>${label} <strong>${count}</strong></span>`).join('')}</div><div class="unit-dashboard-grid"><section class="unit-block"><h2>Upcoming operations</h2>${operations.upcoming.map(eventLink).join('')||'<p>No upcoming events.</p>'}${operations.can_events?'<button type="button" id="dashboard-new-event">Schedule event</button>':''}</section><section class="unit-block"><h2>Attendance needs review</h2><p class="feature-note">Completed events stay pending until staff review and finalize them.</p>${operations.pending.map(eventLink).join('')||'<p>No events waiting for review.</p>'}</section><section class="unit-block"><h2>Promotion readiness</h2>${operations.eligible.map(m=>`<p><strong>${esc(m.game_name)}</strong> → ${esc(m.next_rank)}<small>Eligible for staff review · ${esc(m.next_date)}</small></p>`).join('')||'<p>No members currently eligible.</p>'}<p class="feature-note">Promotions are manual. Review the member’s record before changing rank.</p></section><section class="unit-block"><h2>Roster health</h2><p>${s.unassigned} member${s.unassigned===1?'':'s'} without a primary billet.</p><p>${s.vacancies} vacant billet${s.vacancies===1?'':'s'}.</p><button type="button" id="dashboard-roster">Open roster</button><p class="feature-note">Groups and billets are optional; a flat roster works without them.</p></section></div>`;
    bindEvents(el('unit-dashboard-content'));el('dashboard-new-event')?.addEventListener('click',()=>eventEditor());
    el('dashboard-roster').onclick=()=>el('unit-tab-roster').click();
  }
  function renderCalendar(){
    const selected=el('operations-month').value;
    const [year,month]=selected.split('-').map(Number), first=new Date(year,month-1,1), days=new Date(year,month,0).getDate();
    const groups=new Map();
    for(const event of operations.events){const day=localValue(event.starts,zone()).slice(0,10);if(!groups.has(day))groups.set(day,[]);groups.get(day).push(event);}
    let html='<div class="unit-calendar" role="list" aria-label="Monthly event calendar">'+['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<div class="calendar-weekday">${d}</div>`).join('');
    html+='<div class="calendar-empty" aria-hidden="true"></div>'.repeat(first.getDay());
    for(let day=1;day<=days;day++){const key=`${selected}-${String(day).padStart(2,'0')}`;html+=`<section class="calendar-day" role="listitem" aria-label="${key}"><strong>${day}</strong>${(groups.get(key)||[]).map(e=>`<button type="button" class="calendar-event ${e.state==='cancelled'?'event-cancelled':''}" data-event="${e.id}"><small>${esc(localValue(e.starts,zone()).slice(11))}</small>${esc(e.name)}</button>`).join('')}</section>`;}
    el('operations-calendar').innerHTML=html+'</div>';bindEvents(el('operations-calendar'));
    el('operations-agenda').innerHTML=`<h2>Month agenda · ${esc(zone())}</h2>${operations.events.map(eventLink).join('')||'<p>No events this month.</p>'}`;bindEvents(el('operations-agenda'));
  }
  async function loadOperations(){
    if(!context)return;const current=context.unitId, token=++generation;
    const data=await read(`${base()}/operations?${query(el('operations-month').value)}`);
    if(context.unitId!==current||token!==generation)return;
    operations=data;el('event-new').hidden=!data.can_events;renderDashboard();renderCalendar();
  }
  async function loadReport(){
    if(!context)return;const current=context.unitId, token=++reportGeneration;
    const params=query(el('attendance-month').value);if(el('attendance-server').value!=='__all__')params.set('server_id',el('attendance-server').value);
    const data=await read(`${base()}/attendance?${params}`);if(context.unitId!==current||token!==reportGeneration)return;
    el('attendance-export').href=`${base()}/attendance.csv?${params}`;
    const finalized=data.events.filter(e=>e.state==='finalized').length;
    el('attendance-summary').innerHTML=`<span>Tracked events <strong>${data.events.length}</strong></span><span>Finalized <strong>${finalized}</strong></span><span>Pending <strong>${data.events.length-finalized}</strong></span><span>Display timezone <strong>${esc(data.timezone)}</strong></span>`;
    el('attendance-report').innerHTML=`<table><thead><tr><th>Member</th>${data.events.map(e=>`<th><button type="button" data-event="${e.id}">${esc(e.name)}</button><small>${esc(format(e.starts))}</small><small>${e.state==='finalized'?'Finalized':'Pending'}</small></th>`).join('')}<th>Attendance rate</th><th>Last attended (all time)</th></tr></thead><tbody>${data.members.map(m=>`<tr><td>${esc(m.game_name)}</td>${data.events.map(e=>{const c=m.cells[e.id];return `<td>${c?`<span class="attendance-outcome outcome-${c.outcome}">${c.outcome[0].toUpperCase()+c.outcome.slice(1)}</span><small>${c.finalized?'':'Pending · '}${esc(c.exemption||'')}${c.expected?'':' · Optional / excused'}</small>`:'—'}</td>`;}).join('')}<td>${m.rate===null?'—':m.rate+'%'}<small>${m.counted_events} counted event${m.counted_events===1?'':'s'}</small></td><td>${m.last_attended?esc(format(m.last_attended)):'Never recorded'}</td></tr>`).join('')||'<tr><td>No members or attendance records in this month.</td></tr>'}</tbody></table>`;
    bindEvents(el('attendance-report'));
  }
  async function refresh(){if(!context)return;await Promise.all([loadOperations(),loadReport()]);}
  function eventEditor(event=null){
    if(saving)return;const futureVersions=eventDetail?.future_versions;
    const editing=!!event, tz=event?.timezone||zone(), start=event?.starts||Math.ceil((Date.now()/1000+3600)/300)*300;
    try{new Intl.DateTimeFormat(undefined,{timeZone:tz});}catch(_){message('Choose a valid IANA timezone, such as America/New_York.');return;}
    const linked=context.listing.units.find(u=>u.id===context.unitId)?.servers||[];
    open(editing?'Edit event':'Schedule event',`<div class="unit-form-grid">${field('Event name','name',event?.name||'')}${field('Event type','category',event?.category||'Operation')}${field('Starts (in event timezone)','starts',localValue(start,tz),'datetime-local')}${field('Timezone','timezone',tz)}${field('Duration (minutes)','duration',event?(event.ends-event.starts)/60:120,'number')}<label class="unit-field">Server<select name="server_id">${linked.map(id=>`<option value="${esc(id)}" ${event?.server_id===id?'selected':''}>${esc(serverName(id))}</option>`).join('')}</select></label>${field('Location / map','location',event?.location||'')}<label class="unit-field wide">Briefing<textarea name="briefing" maxlength="4000">${esc(event?.briefing||'')}</textarea></label>${!editing?'<label class="unit-field">Repeat<select name="recurrence"><option value="none">Does not repeat</option><option value="weekly">Weekly</option><option value="biweekly">Every two weeks</option><option value="monthly">Monthly</option></select></label>'+field('Number of occurrences','count',1,'number'):event.recurrence!=='none'?'<label class="unit-field">Apply changes to<select name="scope"><option value="occurrence">This occurrence only</option><option value="future">This and later scheduled occurrences</option></select></label>':''}</div><label><input type="checkbox" name="tracked" ${event?.tracked===0?'':'checked'}> Track UUID attendance</label><p class="feature-note">Event timezone preserves local start times across daylight-saving changes. Monthly repeats use the last day when needed. Roster changes update future event lists; the list freezes at the start. LOA is excused and Reserve is optional.</p>${!linked.length?'<p class="unit-warn">Link a server in Unit settings before scheduling.</p>':''}`,async()=>{
      const data=Object.fromEntries(new FormData(form));data.duration=Number(data.duration);data.count=Number(data.count||1);data.tracked=new FormData(form).has('tracked');
      if(editing)await write(`${base()}/events/${event.id}/change`,{...data,action:'edit',version:event.version,future_versions:futureVersions});else await write(`${base()}/events`,data);
    });
    form.elements.name.required=true;form.elements.name.maxLength=120;form.elements.category.required=true;form.elements.category.maxLength=60;form.elements.starts.required=true;form.elements.timezone.required=true;
    form.elements.duration.min=5;form.elements.duration.max=1440;form.elements.duration.step=1;
    if(form.elements.count){form.elements.count.min=1;form.elements.count.max=52;form.elements.recurrence.onchange=()=>{form.elements.count.disabled=form.elements.recurrence.value==='none';if(form.elements.recurrence.value!=='none'&&Number(form.elements.count.value)===1)form.elements.count.value=4;};form.elements.count.disabled=true;}
    baseline=sign();
  }
  async function openEvent(id){
    if(saving)return;
    try{
      const current=context.unitId, token=++eventGeneration;const data=await read(`${base()}/events/${id}`);if(current!==context.unitId||token!==eventGeneration)return;eventDetail=data;
      const e=data.event, now=Date.now()/1000, review=data.can_attendance&&e.tracked&&e.state==='scheduled'&&e.starts<=now;
      const c=data.coverage;
      open(e.name,`<div class="event-detail-meta"><span>${esc(e.category)} · ${esc(serverName(e.server_id))}</span><strong>${esc(format(e.starts,e.timezone))} – ${esc(format(e.ends,e.timezone))}</strong><small>${esc(e.timezone)} · ${esc(e.state)}${e.recurrence!=='none'?' · '+esc(e.recurrence)+' series':''}</small><span>${esc(e.location||'No location set')}</span></div>${e.briefing?`<p class="member-record-note">${esc(e.briefing)}</p>`:''}<div class="unit-toolbar">${data.can_events&&e.state==='scheduled'?`${e.starts>now?'<button type="button" id="event-edit">Edit event</button>':''}<button type="button" id="event-cancel">Cancel event</button>`:''}${data.can_attendance&&e.tracked&&e.ends<=now&&e.state!=='cancelled'?`<button type="button" id="event-finalize">${e.state==='finalized'?'Reopen for correction':'Finalize attendance'}</button>`:''}<button type="button" id="event-reload">Refresh evidence</button></div>${e.tracked?`<div class="unit-block ${c.needs_review?'unit-warn':''}"><strong>${e.starts>now?'Collector starts with the event':c.needs_review?'Collector gaps — review required':'Collector observations received'}</strong><p>${c.successful} successful samples / ${c.samples} total · Largest gap ${Math.ceil(c.largest_gap_seconds/60)} min</p><p>Last successful sample: ${c.last_success?esc(format(c.last_success)):'None'}</p><small>Presence is sampled from the live UUID player list about every 30 seconds. Brief connections between samples may need manual confirmation. No observation means Unknown, never an automatic absence.</small></div><h3>Event roster</h3><div class="unit-table event-member-table"><table><thead><tr><th>Member</th><th>Expectation</th><th>UUID evidence</th><th>Outcome</th></tr></thead><tbody>${data.members.map(m=>`<tr><td>${esc(m.game_name)}<small>${esc(m.identity||'No linked UUID at event start')}</small></td><td>${esc(m.exemption||'Expected')}</td><td>${m.evidence?`${esc(format(m.evidence.first_seen))}<small>Last seen ${esc(format(m.evidence.last_seen))} · ${m.evidence.samples} samples</small>`:'Not observed'}</td><td>${review?`<select name="attendance:${m.member_id}" data-attendance-member="${m.member_id}" data-initial="${m.resolved}" aria-label="Attendance for ${esc(m.game_name)}">${['present','absent','excused','unknown'].map(s=>`<option value="${s}" ${m.resolved===s?'selected':''}>${s[0].toUpperCase()+s.slice(1)}</option>`).join('')}</select>`:`<span class="attendance-outcome outcome-${m.resolved}">${esc(m.resolved)}</span>`}${m.reason?`<small>${esc(m.reason)}</small>`:''}${m.manual?'<small>Staff decision</small>':''}</td></tr>`).join('')||'<tr><td colspan="4">No members on this event’s roster.</td></tr>'}</tbody></table></div>${review?'<label class="unit-field">Reason for attendance changes<textarea name="reason" maxlength="1000" placeholder="Required when changing outcomes"></textarea></label>':''}<details class="unit-block"><summary>Unlinked / non-roster UUIDs (${data.unlinked.length})</summary><p class="feature-note">These players are not credited to a member automatically. Link their recorded UUID in the roster for future events; correct this event manually if appropriate.</p>${data.unlinked.map(p=>`<p>${esc(p.name)}<small>${esc(p.identity)} · ${esc(format(p.first_seen))}</small></p>`).join('')||'<p>None observed.</p>'}</details>`:'<p>Attendance tracking is disabled for this event.</p>'}<details class="unit-block"><summary>Event and attendance audit (${data.audit.length}${data.audit.length===200?'+':''})</summary>${data.audit.map(a=>`<div class="event-audit-row"><strong>${esc(a.actor)} · ${esc(a.action)}</strong><small>${esc(format(a.created_at))}${a.member_id?' · Member #'+a.member_id:''}</small>${a.reason?`<p>${esc(a.reason)}</p>`:''}<details><summary>Before / after</summary><pre>${esc(JSON.stringify(a.before_value,null,2))}\n→\n${esc(JSON.stringify(a.after_value,null,2))}</pre></details></div>`).join('')}</details>`,review?async()=>{
        const changes=[...form.querySelectorAll('[data-attendance-member]')].filter(s=>s.value!==s.dataset.initial).map(s=>({member_id:Number(s.dataset.attendanceMember),outcome:s.value}));
        if(!changes.length)throw new Error('Change an outcome first, or close this window.');
        await write(`${base()}/events/${id}/attendance`,{version:e.version,reason:new FormData(form).get('reason'),changes});
      }:null);
      el('event-edit')?.addEventListener('click',()=>eventEditor(e));
      el('event-reload').onclick=()=>{if(sign()!==baseline&&!confirm('Discard unsaved attendance changes and refresh?'))return;openEvent(id);};
      el('event-cancel')?.addEventListener('click',()=>eventAction(e,'cancel'));
      el('event-finalize')?.addEventListener('click',()=>eventAction(e,e.state==='finalized'?'reopen':'finalize'));
      if(review)el('event-save').textContent='Save attendance corrections';
      baseline=sign();
    }catch(error){message(error.message);}
  }
  function eventAction(event,action){
    if(saving)return;const futureVersions=eventDetail?.future_versions;
    if(sign()!==baseline&&!confirm('Discard unsaved attendance changes?'))return;
    const unknown=eventDetail?.members.filter(m=>m.resolved==='unknown').length||0;
    open(action==='cancel'?'Cancel event':action==='finalize'?'Finalize attendance':'Reopen attendance',`<p>${action==='cancel'?'Cancellation preserves the event and its history.':action==='finalize'?`${unknown} member outcome(s) are Unknown. Unknown and Excused outcomes stay outside attendance percentages. Finalizing preserves all outcomes until staff reopen the event.`:'Reopening preserves previous outcomes and requires a reason. Save corrections and finalize again afterward.'}</p>${action==='cancel'&&event.recurrence!=='none'?'<label class="unit-field">Cancel<select name="scope"><option value="occurrence">This occurrence only</option><option value="future">This and later scheduled occurrences</option></select></label>':''}<label class="unit-field">Reason<textarea name="reason" required maxlength="1000"></textarea></label>`,async()=>{const values=Object.fromEntries(new FormData(form));await write(`${base()}/events/${event.id}/change`,{...values,action,version:event.version,future_versions:futureVersions});});
  }
  document.addEventListener('unit-loaded',event=>{if(dialog.open)dialog.close();context=event.detail;el('attendance-server').innerHTML='<option value="__all__">All linked / historical servers</option>'+(context.listing.units.find(u=>u.id===context.unitId)?.servers||[]).map(id=>`<option value="${esc(id)}">${esc(serverName(id))}</option>`).join('');refresh().catch(error=>message(error.message));});
  el('event-new').onclick=()=>eventEditor();el('operations-refresh').onclick=()=>refresh().catch(error=>message(error.message));
  el('attendance-refresh').onclick=()=>loadReport().catch(error=>message(error.message));el('attendance-server').onchange=()=>loadReport().catch(error=>message(error.message));
  el('operations-month').onchange=()=>loadOperations().catch(error=>message(error.message));el('attendance-month').onchange=()=>loadReport().catch(error=>message(error.message));
  setInterval(()=>{if(context&&!document.hidden&&!dialog.open)refresh().catch(error=>message(error.message));},30000);
})();
