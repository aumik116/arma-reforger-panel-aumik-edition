// User-facing workflows share existing permission checks and server selection.
(() => {
  const node=(tag,text,className)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;};
  const button=(text,action,permission)=>{const element=node('button',text,'btn-logout');element.type='button';element.onclick=action;if(permission){element.dataset.permission=permission;element.hidden=true;}return element;};
  function modal(title){
    const dialog=node('dialog',undefined,'mods-dialog experience-dialog');const header=node('div',undefined,'mods-dialog-heading');
    const heading=node('h2',title);heading.id='experience-title-'+document.querySelectorAll('.experience-dialog').length;dialog.setAttribute('aria-labelledby',heading.id);
    header.append(heading,button('Close',()=>dialog.close()));dialog.append(header);document.body.append(dialog);return dialog;
  }
  const message=error=>error instanceof Error?error.message:String(error);
  const date=value=>value?new Date(value*1000).toLocaleString():'—';
  const duration=seconds=>`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`;
  const safeDraft=()=>{if(Object.keys(configChanges).length)throw new Error('Save or discard your unsaved configuration edits first.');};

  // Installed scenario gallery.
  const gallery=modal('Choose a scenario'),galleryToolbar=node('div',undefined,'workshop-toolbar');
  const search=node('input');search.type='search';search.placeholder='Search maps and missions';search.setAttribute('aria-label','Search scenarios');
  const source=node('select');source.setAttribute('aria-label','Scenario source');source.append(new Option('All sources',''),new Option('Built-in','vanilla'),new Option('Workshop','workshop'));
  const galleryStatus=node('p');galleryStatus.setAttribute('role','status');const galleryGrid=node('div',undefined,'experience-gallery');
  galleryToolbar.append(search,source,button('Refresh',()=>loadGallery()),button('Rescan installed scenarios',async()=>{
    try{galleryStatus.textContent='Scanning installed scenarios…';await readJson(await postJson('/api/scenarios/rescan',{}));await loadGallery();}catch(error){galleryStatus.textContent=message(error);}
  },'mods'));gallery.append(galleryToolbar,node('p','Select a scenario from this server’s installed content. Changes are saved to configuration and take effect on the next start/restart. Workshop thumbnails appear when available.','feature-note'),galleryStatus,galleryGrid);
  let galleryData=null,gallerySerial=0,galleryTimer;
  function renderGallery(){
    galleryGrid.replaceChildren();const term=search.value.toLowerCase();
    const rows=galleryData.scenarios.filter(row=>(!source.value||(source.value==='vanilla'?row.source==='vanilla':row.source!=='vanilla'))&&`${row.name} ${row.source} ${row.description||''}`.toLowerCase().includes(term));
    for(const row of rows){
      const card=node('article',undefined,'experience-scenario');
      if(row.thumbnail){const image=node('img');image.src=row.thumbnail;image.alt='';image.loading='lazy';image.referrerPolicy='no-referrer';image.onerror=()=>image.remove();card.append(image);}
      card.append(node('h3',row.name),node('p',(row.source==='vanilla'?'Built-in':row.source)+(row.player_count?' · '+row.player_count+' players':''),'feature-note'));
      if(row.description)card.append(node('p',row.description));
      if(row.id===galleryData.current)card.append(node('strong','Currently configured'));
      if(row.source!=='vanilla'&&!row.owner_mod)card.append(node('p','Required mod could not be identified locally. Check the configured mod list before starting.','feature-note'));
      if(row.needs_mod)card.append(node('p','Also adds '+row.source+' to configured mods.','feature-note'));
      const choose=button(row.id===galleryData.current?'Selected':row.needs_mod?'Use scenario + add mod':'Use scenario',async()=>{
        try{
          safeDraft();if(!confirm(`Use “${row.name}”${row.needs_mod?' and add its Workshop mod to configuration':''}? A running server needs a restart afterward.`))return;
          choose.disabled=true;await readJson(await postJson('/api/scenarios/choose',{scenario:row.id,revision:galleryData.revision}));
          galleryStatus.textContent='Scenario saved. Start or restart the server when ready.';await fetchStatus();if(can('configure'))await loadConfiguration(true);await loadGallery();
        }catch(error){galleryStatus.textContent=message(error);}finally{choose.disabled=row.id===galleryData.current;}
      });choose.disabled=row.id===galleryData.current||!can('configure')||(row.needs_mod&&!can('mods'));card.append(choose);galleryGrid.append(card);
    }
    if(!rows.length)galleryGrid.append(node('p','No matching scenarios. Try another filter or rescan installed files.'));
  }
  async function loadGallery(attempt=0){
    if(attempt>0&&galleryGrid.contains(document.activeElement)){galleryTimer=setTimeout(()=>loadGallery(attempt),3000);return;}
    const serial=++gallerySerial;clearTimeout(galleryTimer);galleryStatus.textContent='Loading scenarios…';
    try{
      const data=await readJson(await fetch('/api/scenarios/gallery'));if(serial!==gallerySerial||!gallery.open)return;galleryData=data;renderGallery();
      galleryStatus.textContent=`${data.scenarios.length} scenarios available${data.diagnostics?.busy?' · scan is still running':''}`;
      if(attempt<4&&data.scenarios.some(row=>row.status==='pending'))galleryTimer=setTimeout(()=>loadGallery(attempt+1),3000);
    }catch(error){if(serial===gallerySerial)galleryStatus.textContent=message(error);}
  }
  gallery.addEventListener('close',()=>{clearTimeout(galleryTimer);gallerySerial++;});search.oninput=source.onchange=()=>{if(galleryData)renderGallery();};
  const openGallery=()=>{gallery.showModal();loadGallery();};
  const scenarioToolbar=node('div',undefined,'workshop-toolbar');scenarioToolbar.append(button('Browse maps & scenarios',openGallery,'configure'),button('Operation presets',()=>{selectPanelTab(document.getElementById('tab-mods'));document.getElementById('section-tab-mods-presets').click();},'mods'));
  document.getElementById('panel-configuration').prepend(scenarioToolbar);
  document.getElementById('workshop-search-form').append(button('Browse installed scenarios',openGallery,'configure'));

  // Durable per-player sessions; separate from aggregate first/last-seen history.
  const sessions=node('details',undefined,'card');sessions.append(node('summary','Player sessions · visits and playtime'));
  sessions.append(node('p','Sessions are based on successful player samples, normally every 30 seconds. Times and duration are approximate; brief visits may be missed. Query failures do not count as departures, and gaps over 90 seconds start a new observation. Earlier first/last-seen history cannot be converted into sessions.','feature-note'));
  const sessionToolbar=node('form',undefined,'workshop-toolbar'),sessionSearch=node('input');sessionSearch.type='search';sessionSearch.maxLength=80;sessionSearch.placeholder='Search name or identity';sessionSearch.setAttribute('aria-label','Search player sessions');
  sessionToolbar.append(sessionSearch,button('Search',()=>loadSessions()),button('Refresh',()=>loadSessions()));sessions.append(sessionToolbar);
  const sessionStatus=node('p');sessionStatus.setAttribute('role','status');const sessionWrap=node('div',undefined,'operator-table-wrap'),table=node('table',undefined,'operator-table'),head=node('thead'),header=node('tr');
  for(const title of ['Player','Joined (observed)','Last seen','Observed playtime','Status'])header.append(node('th',title));head.append(header);table.append(head);const sessionBody=node('tbody');table.append(sessionBody);sessionWrap.append(table);sessions.append(sessionStatus,sessionWrap);
  let sessionCursor=null,sessionSerial=0;
  const older=button('Load older visits',()=>loadSessions(true));older.hidden=true;sessions.append(older);document.getElementById('panel-players').append(sessions);
  async function loadSessions(append=false){
    const serial=++sessionSerial;sessionStatus.textContent='Loading sessions…';older.disabled=true;
    try{
      const data=await readJson(await fetch('/api/players/sessions?'+new URLSearchParams({q:sessionSearch.value,before:append?sessionCursor||0:0})));if(serial!==sessionSerial)return;
      if(!append)sessionBody.replaceChildren();
      for(const visit of data.sessions){const row=node('tr'),name=node('td',visit.name);name.append(node('small',visit.identity,'experience-identity'));row.append(name);for(const value of [date(visit.joined),date(visit.last_seen),duration(visit.duration),visit.ended?visit.outcome:visit.stale?'Observation paused':'Connected at last sample'])row.append(node('td',value));sessionBody.append(row);}
      sessionCursor=data.next_cursor;older.hidden=!sessionCursor;sessionStatus.textContent=sessionBody.children.length?'Observed sessions for this server.':'No matching visits recorded yet.';
    }catch(error){sessionStatus.textContent=message(error);}finally{if(serial===sessionSerial)older.disabled=false;}
  }
  sessions.ontoggle=()=>{if(sessions.open)loadSessions();};sessionToolbar.onsubmit=event=>{event.preventDefault();loadSessions();};

  // Operation presets include gameplay settings as well as scenario/mod selections.
  const operations=node('section',undefined,'card');operations.append(node('h3','Operation presets'),node('p','Save this server’s scenario, mods, player limit, visibility, crossplay, gameplay and AI settings together. Ports, credentials, administrator identities, saves and persistence settings stay with the server. Switch operations while stopped.','feature-note'));
  const opsToolbar=node('div',undefined,'workshop-toolbar'),opsSelect=node('select');opsSelect.setAttribute('aria-label','Operation preset');const opsName=node('input');opsName.maxLength=80;opsName.placeholder='New operation name';opsName.setAttribute('aria-label','New operation preset name');
  const opsStatus=node('p');opsStatus.setAttribute('role','status');let presets=[],opsBusy=false;
  opsToolbar.append(opsSelect,button('Refresh',()=>loadOperations()));operations.append(opsToolbar);
  const opsActions=node('div',undefined,'workshop-toolbar');opsActions.dataset.permission='mods';opsActions.hidden=true;
  opsActions.append(opsName,button('Save current setup',()=>saveOperation(false)),button('Overwrite selected',()=>saveOperation(true)),button('Review / switch',()=>previewOperation()),button('Delete',()=>deleteOperation()));operations.append(opsActions,opsStatus);
  document.getElementById('section-mods-presets').prepend(operations);
  const selectedOperation=()=>presets.find(row=>String(row.id)===opsSelect.value);
  async function loadOperations(){
    try{const selected=opsSelect.value;const data=await readJson(await fetch('/api/operations'));presets=data.presets;opsSelect.replaceChildren(new Option('Select an operation',''));for(const row of presets)opsSelect.append(new Option(`${row.name} · ${row.mods.length} mods${row.active?' · Active':''}`,row.id));opsSelect.value=selected;opsStatus.textContent=presets.length?`${presets.length} saved operations on this server.`:'No saved operations yet. Configure the server, then save the setup here.';}
    catch(error){opsStatus.textContent=message(error);}
  }
  async function saveOperation(overwrite){
    if(opsBusy)return;
    try{safeDraft();if(!can('configure'))throw new Error('Configuration permission is also required.');const selected=selectedOperation();if(overwrite&&!selected)throw new Error('Select an operation first.');if(overwrite&&!confirm(`Overwrite “${selected.name}” with the current setup?`))return;opsBusy=true;await readJson(await postJson('/api/operations/save',overwrite?{id:selected.id,updated:selected.updated,name:selected.name}:{name:opsName.value}));opsName.value='';await loadOperations();opsStatus.textContent='Operation saved from the current configuration.';}
    catch(error){opsStatus.textContent=message(error);}finally{opsBusy=false;}
  }
  async function deleteOperation(){
    if(opsBusy)return;const selected=selectedOperation();if(!selected){opsStatus.textContent='Select an operation first.';return;}if(!confirm(`Delete operation preset “${selected.name}”?`))return;
    opsBusy=true;try{await readJson(await postJson('/api/operations/delete',{id:selected.id,updated:selected.updated}));await loadOperations();}catch(error){opsStatus.textContent=message(error);}finally{opsBusy=false;}
  }
  const review=modal('Review operation switch'),reviewList=node('div'),reviewStatus=node('p');reviewStatus.setAttribute('role','status');let operationPlan=null;
  const applyOperation=button('Apply to stopped server',async()=>{
    if(opsBusy||!operationPlan)return;
    try{safeDraft();opsBusy=true;applyOperation.disabled=true;await readJson(await postJson('/api/operations/apply',{id:operationPlan.id,updated:operationPlan.updated,revision:operationPlan.revision}));review.close();opsStatus.textContent='Operation applied. Start the server when ready.';await fetchStatus();if(can('configure'))await loadConfiguration(true);await loadOperations();}
    catch(error){reviewStatus.textContent=message(error);}finally{opsBusy=false;applyOperation.disabled=false;}
  });review.append(node('p','Review every change below. Applying saves configuration, retains downloaded mod files and uses normal local mod reuse. It does not start the server.','feature-note'),reviewList,reviewStatus,applyOperation);
  async function previewOperation(){
    try{safeDraft();const selected=selectedOperation();if(!selected)throw new Error('Select an operation first.');operationPlan=await readJson(await fetch(`/api/operations/${selected.id}/preview`));reviewList.replaceChildren(node('h3',operationPlan.name));
      for(const change of operationPlan.changes)reviewList.append(node('p',`${change.label}: ${change.before??'Default'} → ${change.after??'Default'}`));
      for(const mod of operationPlan.added)reviewList.append(node('p','Add mod: '+(mod.name||mod.modId)+(mod.version?' · '+mod.version:'')));
      for(const mod of operationPlan.removed)reviewList.append(node('p','Remove from configuration: '+(mod.name||mod.modId)));
      for(const mod of operationPlan.edited)reviewList.append(node('p',`Edit mod: ${mod.before.name||mod.before.modId} (${mod.before.version||'latest'} → ${mod.after.version||'latest'})`));
      if(!operationPlan.changes.length&&!operationPlan.added.length&&!operationPlan.removed.length&&!operationPlan.edited.length)reviewList.append(node('p','This setup is already configured.'));
      reviewStatus.textContent='';applyOperation.disabled=!can('mods')||!can('configure');review.showModal();
    }catch(error){opsStatus.textContent=message(error);}
  }
  document.getElementById('section-tab-mods-presets').addEventListener('click',()=>loadOperations());

  // Announcement composer, backed by the existing durable scheduler and RCON.
  const announcements=modal('Player announcement'),announcementForm=node('form'),delivery=node('select');delivery.setAttribute('aria-label','Delivery');
  delivery.append(new Option('Send now','now'),new Option('Schedule message','later'),new Option('Schedule restart with warnings','restart'));
  const templates=node('select');templates.setAttribute('aria-label','Message template');templates.append(new Option('Choose a message template',''),new Option('Operation begins soon','Operation begins soon. Please prepare and join your assigned group.'),new Option('Training begins soon','Training begins soon. Please follow staff instructions.'),new Option('Maintenance notice','Maintenance is planned shortly. Please finish your current activity.'));
  const text=node('input');text.maxLength=220;text.required=true;text.placeholder='Message to players';text.setAttribute('aria-label','Announcement message');
  const delay=node('input');delay.type='number';delay.min='1';delay.max='1440';delay.value='15';delay.required=true;delay.setAttribute('aria-label','Minutes from now');
  const delayLabel=node('label','Minutes from now');delayLabel.append(delay);delayLabel.hidden=true;
  const textLabel=node('label','Message');textLabel.append(text);const announcementStatus=node('p');announcementStatus.setAttribute('role','status');
  const notice=node('p','Messages require admin RCON and Server Admin Tools #message support. Scheduled messages need the Linux panel service. Restart warnings must be delivered successfully or the scheduler skips the restart.','feature-note');
  const submit=node('button','Send message','btn-save');submit.type='submit';announcementForm.append(delivery,templates,textLabel,delayLabel,notice,announcementStatus,submit);announcements.append(announcementForm);
  templates.onchange=()=>{if(templates.value)text.value=templates.value;};
  delivery.onchange=()=>{const restart=delivery.value==='restart';delayLabel.hidden=delivery.value==='now';delay.min=restart?'6':'1';if(restart&&Number(delay.value)<6)delay.value='6';textLabel.hidden=templates.hidden=restart;text.required=!restart;submit.textContent=restart?'Schedule warned restart':delivery.value==='later'?'Schedule announcement':'Send message';announcementStatus.textContent=restart?'Players receive automatic warnings 5 minutes and 1 minute before the restart.':'';};
  announcementForm.onsubmit=async event=>{
    event.preventDefault();if(delivery.value==='restart'&&!confirm(`Restart this server in ${delay.value} minutes with 5-minute and 1-minute warnings?`))return;submit.disabled=true;
    try{const result=await readJson(await postJson('/api/players/announcement',{mode:delivery.value,message:text.value,minutes:Number(delay.value)}));announcementStatus.textContent=result.message;if(delivery.value==='now')text.value='';}
    catch(error){announcementStatus.textContent=message(error);}finally{submit.disabled=false;}
  };
  const openAnnouncements=()=>{announcementStatus.textContent='';announcements.showModal();};
  for(const target of ['panel-players','panel-scheduler']){const tools=node('div',undefined,'workshop-toolbar');tools.append(button('Player announcement / warned restart',openAnnouncements,'admin_config'));document.getElementById(target).prepend(tools);}
  function permissions(){document.querySelectorAll('.experience-dialog [data-permission],#panel-configuration > .workshop-toolbar [data-permission],#panel-players > .workshop-toolbar [data-permission],#panel-scheduler > .workshop-toolbar [data-permission]').forEach(element=>element.hidden=!can(element.dataset.permission));}
  document.addEventListener('panel-ready',()=>{permissions();loadOperations();});permissions();
})();
