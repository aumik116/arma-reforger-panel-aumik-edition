// Staff workspace. All unit access is also enforced by the API.
(() => {
  const el=id=>document.getElementById(id), esc=escHtml;
  let listing, detail, unitId, dialogSave, baseline='', loading=false, dialogSaving=false;
  const dialog=el('unit-dialog'), form=el('unit-form');
  async function read(url) { return readJson(await fetch(url)); }
  async function write(url,data) { return readJson(await postJson(url,data)); }
  const feedback=message=>{el('units-feedback').textContent=message;};
  const options=(values,selected='',blank='None')=>`<option value="">${esc(blank)}</option>`+values.map(v=>`<option ${v===selected?'selected':''}>${esc(v)}</option>`).join('');
  const field=(label,name,value='',type='text')=>`<label class="unit-field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" maxlength="${name.includes('cert')?8000:name==='notes'?2000:120}"></label>`;
  const checks=(name,values,selected=[])=>`<div class="unit-checks">${values.map(v=>`<label><input type="checkbox" name="${name}" value="${esc(v)}" ${selected.includes(v)?'checked':''}>${esc(v)}</label>`).join('')||'<span class="feature-note">None defined yet.</span>'}</div>`;
  const checked=name=>[...form.querySelectorAll(`input[name="${name}"]:checked`)].map(c=>c.value);
  const values=()=>Object.fromEntries(new FormData(form));
  function signature() { return JSON.stringify([...new FormData(form)]); }
  function closeDialog() { if(dialogSaving)return;if(signature()!==baseline&&!confirm('Discard unsaved changes?'))return;dialog.close(); }
  function openDialog(title,html,save) {
    dialog.dataset.record='';el('unit-dialog-title').textContent=title;el('unit-dialog-body').innerHTML=html;
    el('unit-dialog-error').textContent='';const saveButton=form.querySelector('[type="submit"]');saveButton.hidden=false;saveButton.textContent='Save changes';dialogSave=save;dialog.showModal();baseline=signature();
    form.querySelector('input,select,textarea')?.focus();
  }
  dialog.addEventListener('cancel',e=>{e.preventDefault();closeDialog();});el('unit-dialog-close').onclick=closeDialog;
  form.onsubmit=async e=>{
    e.preventDefault();if(dialogSaving)return;dialogSaving=true;const button=form.querySelector('[type="submit"]');button.disabled=true;
    try { const close=await dialogSave();if(close!==false){dialog.close();await loadListing(unitId);feedback('Changes saved.');}else{baseline=signature();} }
    catch(error) { el('unit-dialog-error').textContent=error.message; }
    finally { button.disabled=false;dialogSaving=false; }
  };
  function unitSettings(create=false) {
    const unit=create?{}:detail.unit, selected=create?[]:listing.units.find(u=>u.id===unitId).servers;
    openDialog(create?'Create unit':'Unit settings',`<div class="unit-form-grid">${field('Unit name','name',unit.name||'')}${field('Short tag','tag',unit.tag||'')}</div><h3>Linked servers</h3><p class="feature-note">Linking a server provides basic health visibility. Server control roles are assigned separately.</p>${checks('servers',listing.servers.map(s=>s.id),selected)}`,async()=>{
      const data=values();const result=await write('/api/units',{name:data.name,tag:data.tag,servers:checked('servers'),...(create?{}:{id:unitId,revision:detail.unit.revision})});unitId=result.id;
    });
    // Use friendly server names while keeping stable IDs in submitted values.
    form.querySelectorAll('[name="servers"]').forEach(input=>input.parentNode.lastChild.textContent=listing.servers.find(s=>s.id===input.value).name);
  }
  async function loadListing(preferred=unitId) {
    if(loading)return;loading=true;
    try {
      listing=await read('/api/units');el('unit-new').hidden=!listing.panel_admin;el('unit-users').hidden=!listing.panel_admin;
      el('unit-select').replaceChildren();
      for(const unit of listing.units){const option=document.createElement('option');option.value=unit.id;option.textContent=unit.name;el('unit-select').append(option);}
      unitId=listing.units.some(u=>u.id===Number(preferred))?Number(preferred):listing.units[0]?.id;
      el('unit-workspace').hidden=!unitId;el('unit-select').disabled=!unitId;
      if(!unitId){feedback(listing.panel_admin?'Create your first unit to start building its roster.':'No units assigned. Ask a panel administrator or unit administrator to add your account.');return;}
      el('unit-select').value=unitId;await loadUnit();
    }catch(error){feedback(error.message);el('unit-workspace').hidden=true;}
    finally{loading=false;}
  }
  async function loadUnit(){
    const requested=unitId;
    el('unit-workspace').hidden=true;
    try{
      const result=await read('/api/units/'+requested);
      if(requested!==unitId)return;
      detail=result;el('unit-workspace').hidden=false;
      const selected=listing.units.find(u=>u.id===unitId);
      el('unit-settings').hidden=!detail.can_settings;el('roster-add').hidden=!detail.can_edit;
      el('catalog-edit').hidden=!detail.can_staff;el('position-rename').hidden=!detail.can_staff;el('unit-tab-staff').hidden=!detail.can_staff;
      if(!detail.can_staff&&!el('unit-staff').hidden)selectTab('roster');
      el('roster-export').href='/api/units/'+unitId+'/roster.csv';
      const section=el('roster-section').value;
      el('roster-section').innerHTML=options([...new Set(detail.roster.map(m=>m.section).filter(Boolean))].sort(),section,'All sections');
      renderRoster();renderCatalog();renderStaff();renderServers(selected);feedback('');
      const params=new URLSearchParams(location.search);params.set('unit',unitId);history.replaceState(null,'','/units?'+params);
    }catch(error){if(requested===unitId){el('unit-workspace').hidden=true;feedback(error.message);}}
  }
  function renderRoster(){
    const query=el('roster-search').value.trim().toLowerCase(),status=el('roster-status').value,section=el('roster-section').value;
    const current=detail.roster.filter(m=>!m.archived);
    el('roster-summary').innerHTML=['active','reserve','loa'].map(s=>`<span>${s==='loa'?'LOA':s[0].toUpperCase()+s.slice(1)} <strong>${current.filter(m=>m.status===s).length}</strong></span>`).join('')+`<span>Current roster <strong>${current.length}</strong></span>`;
    const eligible=current.filter(m=>m.promotion.eligible);
    el('promotion-notice').hidden=!eligible.length;
    el('promotion-notice').innerHTML=`<strong>${eligible.length} member${eligible.length===1?'':'s'} eligible for promotion review</strong><p>${eligible.map(m=>esc(m.game_name)+' → '+esc(m.promotion.next_rank)).join(' · ')}</p><small>Staff approval required. No ranks or promotion dates have been changed.</small>`;
    const rows=detail.roster.filter(m=>(status==='archived'?m.archived:!m.archived&&(!status||m.status===status))&&(!section||m.section===section)&&[m.game_name,m.discord,m.identity,m.panel_username,m.rank,m.section,m.position,m.certificates,m.notes].join(' ').toLowerCase().includes(query));
    const key=el('roster-sort').value;
    rows.sort((a,b)=>key==='promotion'?(a.promotion.next_date||'9999').localeCompare(b.promotion.next_date||'9999')||a.game_name.localeCompare(b.game_name):key==='joined'?(a.joined_on||'9999').localeCompare(b.joined_on||'9999')||a.game_name.localeCompare(b.game_name):a.game_name.localeCompare(b.game_name,undefined,{sensitivity:'base',numeric:true}));
    const ranks=Object.fromEntries((detail.unit.catalog.ranks||[]).map(r=>[r.name,r]));
    el('roster-rows').innerHTML=rows.map(m=>{
      const p=m.promotion;
      return `<tr><td><button type="button" class="member-record-link" data-record="${m.id}">${esc(m.game_name)}</button><small>${esc(m.discord||'Discord not set')}</small><small>${esc(m.identity||'UUID not linked')}</small>${m.panel_username?`<small>Panel: ${esc(m.panel_username)}${m.panel_user_enabled?'':' · Disabled'}</small>`:''}${m.notes?`<small>${esc(m.notes)}</small>`:''}${m.joined_on?`<small>Joined ${esc(m.joined_on)}</small>`:''}</td><td>${m.archived?'Former':m.status==='loa'?'LOA':m.status==='active'?'Active':'Reserve'}${m.status==='loa'&&m.loa_until?`<small>Until ${esc(m.loa_until)}</small>`:''}</td><td>${esc(m.rank||'—')}<small>${esc(ranks[m.rank]?.paygrade||'')}</small></td><td>${esc(m.section||'—')}<small>${esc(m.position.split(';').join(', '))}</small></td><td>${esc(m.certificates.split(';').join(', ')||'—')}</td><td>${esc(m.last_promo||'—')}</td><td>${p.next_rank?`<strong>${esc(p.next_rank)}</strong><small>${p.next_date?esc(p.next_date):'Set last promotion date'}</small><small class="${p.eligible?'unit-good':'unit-warn'}">${p.missing.length?'Needs: '+esc(p.missing.join(', ')):p.eligible?'Eligible for staff review':'Qualifications met'}</small>`:'<small>No next rank configured</small>'}</td><td><button type="button" data-record="${m.id}">Open record</button>${detail.can_edit?`<button data-member="${m.id}">Edit</button>`:''}</td></tr>`;
    }).join('')||'<tr><td colspan="8" class="unit-empty">No members match. Add a member to start.</td></tr>';
    el('roster-rows').querySelectorAll('[data-record]').forEach(b=>b.onclick=()=>memberRecord(Number(b.dataset.record)));
    el('roster-rows').querySelectorAll('[data-member]').forEach(b=>b.onclick=()=>memberEditor(detail.roster.find(m=>m.id===Number(b.dataset.member))));
  }
  async function memberRecord(memberId){
    const requestedUnit=unitId;
    const url=`/api/units/${requestedUnit}/roster/${memberId}/record`;
    try{
      const record=await read(url);
      if(requestedUnit!==unitId||dialog.open)return;
      const m=record.member,p=m.promotion;
      openDialog(`${m.game_name} — member record`,`<div class="member-record-facts"><div><span>Status</span><strong>${m.archived?'Former member':m.status==='loa'?'LOA':m.status==='reserve'?'Reserve':'Active'}</strong></div><div><span>Rank / section</span><strong>${esc([m.rank,m.section].filter(Boolean).join(' · ')||'Not assigned')}</strong></div><div><span>Discord</span><strong>${esc(m.discord||'Not set')}</strong></div><div><span>Panel account</span><strong>${esc(m.panel_username||'Not linked')}</strong></div><div><span>Recorded UUID</span><strong>${esc(m.identity||'Not linked')}</strong></div></div><div class="unit-block"><h3>Positions & qualifications</h3><p>${esc(m.position.split(';').join(', ')||'No positions assigned')}</p><p>${esc(m.certificates.split(';').join(', ')||'No qualifications recorded')}</p></div>${m.notes?`<div class="unit-block"><h3>Roster summary</h3><p class="member-record-note">${esc(m.notes)}</p></div>`:''}${p.next_rank?`<p class="feature-note">Next rank: ${esc(p.next_rank)} · ${p.next_date?esc(p.next_date):'Last promotion date not set'}${p.missing.length?' · Needs '+esc(p.missing.join(', ')):p.eligible?' · Eligible for staff review':''}</p>`:''}<h3>Staff record</h3><p class="feature-note">Dated notes stay with this unit’s member record, including after they leave. Authors use their linked name in this unit. Add a follow-up note to correct an earlier entry.</p><div id="member-record-history"></div><button type="button" id="member-record-more" hidden>Load older notes</button>${record.can_write?'<label class="unit-field">Add a staff note<textarea name="record_note" maxlength="4000" rows="5" placeholder="Training, promotion review, administrative notes…"></textarea></label>':'<p class="feature-note">Your unit role can view this record. Roster editing permission is required to add notes.</p>'}<p id="member-record-status" class="feature-note" role="status"></p>`,async()=>{
        await write(url,{note:form.elements.record_note.value});
        form.elements.record_note.value='';
        try{showNotes(await read(url),false);el('member-record-status').textContent='Note saved.';}
        catch(error){el('member-record-status').textContent='Note saved. Reopen the record to refresh its history.';}
        return false;
      });
      const button=form.querySelector('[type="submit"]');button.textContent='Add note';button.hidden=!record.can_write;
      dialog.dataset.record=requestedUnit+':'+memberId;
      let before;
      function showNotes(data,append){
        if(!dialog.open||dialog.dataset.record!==requestedUnit+':'+memberId||!el('member-record-history'))return;
        if(!append)el('member-record-history').replaceChildren();
        for(const note of data.notes){
          const item=document.createElement('article');item.className='unit-block';
          const heading=document.createElement('div');heading.className='member-record-note-heading';
          const author=document.createElement('strong');author.textContent=note.author_name;
          const date=document.createElement('time');date.dateTime=new Date(note.created_at*1000).toISOString();date.textContent=new Date(note.created_at*1000).toLocaleString();
          const content=document.createElement('p');content.className='member-record-note';content.textContent=note.note;
          heading.append(author,date);item.append(heading,content);el('member-record-history').append(item);
        }
        if(!el('member-record-history').children.length)el('member-record-history').textContent='No staff notes yet.';
        before=data.next_before;el('member-record-more').hidden=!before;
      }
      showNotes(record,false);
      el('member-record-more').onclick=async()=>{
        const button=el('member-record-more');button.disabled=true;
        try{showNotes(await read(url+'?before='+before),true);}
        catch(error){if(dialog.dataset.record===requestedUnit+':'+memberId)el('unit-dialog-error').textContent=error.message;}
        finally{button.disabled=false;}
      };
    }catch(error){feedback(error.message);}
  }
  function memberEditor(member={}){
    const catalog=detail.unit.catalog;
    openDialog(member.id?'Edit roster member':'Add roster member',`<div class="unit-form-grid">${field('Game name','game_name',member.game_name||'')}${field('Discord handle','discord',member.discord||'')}<label class="unit-field wide">Linked panel account<select name="panel_user_id" id="member-panel-account"></select><small>Links this person to their login. Note authors use their game name in this unit. This does not grant unit or server access.</small></label><label class="unit-field wide">Recorded player UUID<input type="search" id="identity-search" placeholder="Find a recorded name or UUID" autocomplete="off"><select name="identity" id="member-identity">${options(member.identity?[member.identity]:[],member.identity||'','Not linked yet')}</select><small id="identity-note">Searches player history on this unit’s linked servers. Leave blank for members not recorded yet.</small></label><label class="unit-field">Status<select name="status">${['active','reserve','loa'].map(s=>`<option value="${s}" ${member.status===s?'selected':''}>${s==='loa'?'LOA':s==='active'?'Active':'Reserve'}</option>`).join('')}</select></label><label class="unit-field">Rank (optional)<select name="rank">${options((catalog.ranks||[]).map(r=>r.name),member.rank||'')}</select></label>${field('Squad / section (optional)','section',member.section||'')}${field('Joined unit','joined_on',member.joined_on||'','date')}${field('Last promotion date','last_promo',member.last_promo||'','date')}${field('LOA until (optional)','loa_until',member.loa_until||'','date')}<div class="unit-field wide"><span>Positions (optional)</span>${checks('positions',catalog.positions||[],(member.position||'').split(';'))}</div><div class="unit-field wide"><span>Qualifications / certifications</span>${checks('certificates',catalog.certificates||[],(member.certificates||'').split(';'))}</div><label class="unit-field wide">Notes<textarea name="notes" maxlength="2000">${esc(member.notes||'')}</textarea></label></div>${member.id?`<label><input type="checkbox" name="archived" ${member.archived?'checked':''}> Former member — retain records and exclude from current roster</label>`:''}`,async()=>{
      const data=values();await write(`/api/units/${unitId}/roster`,{...Object.fromEntries(['game_name','discord','identity','status','rank','section','joined_on','last_promo','loa_until','notes'].map(k=>[k,data[k]])),position:checked('positions').join(';'),certificates:checked('certificates').join(';'),archived:!!data.archived,panel_user_id:detail.can_staff?(data.panel_user_id?Number(data.panel_user_id):null):(member.panel_user_id??null),revision:detail.unit.revision,...(member.id?{id:member.id}:{})});
    });
    const accountSelect=el('member-panel-account');
    accountSelect.disabled=!detail.can_staff;
    accountSelect.append(new Option('Not linked',''));
    const accounts=[...(detail.accounts||[])];
    if(member.panel_user_id&&!accounts.some(a=>a.id===member.panel_user_id))accounts.push({id:member.panel_user_id,username:member.panel_username||'Previously linked account',enabled:member.panel_user_enabled});
    for(const account of accounts){const option=new Option(account.username+(account.enabled?'':' · Disabled'),account.id);option.selected=account.id===member.panel_user_id;accountSelect.append(option);}
    if(member.id&&detail.can_delete){
      const remove=document.createElement('button');remove.type='button';remove.className='member-delete-button';remove.textContent='Delete member…';remove.onclick=()=>deleteMember(member);el('unit-dialog-body').append(remove);
    }
    baseline=signature();
    let timer,requestNumber=0;
    async function identities(){
      const number=++requestNumber;
      try{
        const data=await read(`/api/units/${unitId}/identities?q=`+encodeURIComponent(el('identity-search').value));
        if(!dialog.open||number!==requestNumber||!el('member-identity'))return;
        const select=el('member-identity'),selected=select.value;
        select.innerHTML=options(selected?[selected]:[],selected,'Not linked yet');
        for(const player of data.players){if(player.identity===selected)continue;const option=document.createElement('option');option.value=player.identity;option.textContent=`${player.name} · ${player.identity}`;select.append(option);}
        el('identity-note').textContent=data.more?'Showing 100 matches; narrow your search.':`${data.players.length} recorded players. Selection links identity; it does not replace the game name.`;
      }catch(error){if(el('identity-note'))el('identity-note').textContent=error.message;}
    }
    el('identity-search').oninput=()=>{clearTimeout(timer);timer=setTimeout(identities,250);};identities();
    el('member-identity').onchange=()=>{if(!form.elements.game_name.value){const option=el('member-identity').selectedOptions[0];form.elements.game_name.value=option.textContent.split(' · ')[0];}};
  }
  async function deleteMember(member){
    if(dialogSaving)return;
    const name=prompt(`Permanently delete ${member.game_name} from this unit, including their saved staff notes? Their panel account and permissions will remain. To keep their record, use Former member instead. Type their game name exactly to delete:`);
    if(name===null)return;
    dialogSaving=true;
    try{
      await write(`/api/units/${unitId}/roster/${member.id}/delete`,{confirm_name:name,revision:detail.unit.revision});
      dialog.close();await loadListing(unitId);feedback('Member deleted from this unit.');
    }catch(error){el('unit-dialog-error').textContent=error.message;}
    finally{dialogSaving=false;}
  }
  function renderCatalog(){
    const c=detail.unit.catalog;
    el('catalog-summary').innerHTML=`<div class="unit-block"><h3>Qualifications / certifications</h3>${esc((c.certificates||[]).join(', ')||'None defined')}</div><div class="unit-block"><h3>Positions</h3>${esc((c.positions||[]).join(', ')||'None defined')}</div><div class="unit-block"><h3>Paygrades</h3>${(c.paygrades||[]).map(g=>`<p><strong>${esc(g.name)}</strong> · ${g.days} days since last promotion to enter this grade${g.certificates.length?' · Requires '+esc(g.certificates.join(', ')):''}</p>`).join('')||'None defined'}</div><div class="unit-block"><h3>Ranks</h3>${(c.ranks||[]).map(r=>`<p><strong>${esc(r.name)}</strong> · ${esc(r.paygrade)} → ${esc(r.next_rank||'No next rank')}${r.certificates.length?' · Requires '+esc(r.certificates.join(', ')):''}</p>`).join('')||'None defined'}</div>`;
  }
  function catalogEditor(){
    const c=detail.unit.catalog;
    openDialog('Ranks, qualifications & positions',`<p class="feature-note">One qualification or position per line. Requirements use semicolon-separated qualification names. Days means time since the member’s last promotion required to enter the target paygrade.</p><div class="unit-form-grid"><label class="unit-field">Qualification names<textarea name="qualification_names">${esc((c.certificates||[]).join('\n'))}</textarea></label><label class="unit-field">Position names<textarea name="position_names">${esc((c.positions||[]).join('\n'))}</textarea></label></div><h3>Paygrades</h3><div id="grade-rows"></div><button type="button" id="grade-add">Add paygrade</button><h3>Ranks</h3><p class="feature-note">Next rank uses the exact rank name. Leave blank at the end of a career path. For example, HM2 and Sgt can both use E-5 while having different next ranks.</p><div id="rank-rows"></div><button type="button" id="rank-add">Add rank</button>`,async()=>{
      const split=value=>value.split(/[;\n]/).map(s=>s.trim()).filter(Boolean);
      const catalog={certificates:split(form.elements.qualification_names.value),positions:split(form.elements.position_names.value),paygrades:[...form.querySelectorAll('[data-grade]')].map(row=>({name:row.querySelector('[name="grade_name"]').value.trim(),days:Number(row.querySelector('[name="grade_days"]').value),certificates:split(row.querySelector('[name="grade_certs"]').value)})),ranks:[...form.querySelectorAll('[data-rank]')].map(row=>Object.fromEntries(['name','paygrade','next_rank','certificates'].map(k=>[k,k==='certificates'?split(row.querySelector('[name="rank_'+k+'"]').value):row.querySelector('[name="rank_'+k+'"]').value.trim()]))) };
      await write(`/api/units/${unitId}/catalog`,{catalog,revision:detail.unit.revision});
    });
    function addGrade(g={}){const row=document.createElement('div');row.className='catalog-row';row.dataset.grade='';row.innerHTML=field('Paygrade','grade_name',g.name||'')+field('Days to enter','grade_days',g.days??0,'number')+field('Required qualifications','grade_certs',(g.certificates||[]).join(';'))+'<button type="button">Remove</button>';row.querySelector('button').onclick=()=>row.remove();el('grade-rows').append(row);}
    function addRank(r={}){const row=document.createElement('div');row.className='catalog-row';row.dataset.rank='';row.innerHTML=field('Rank','rank_name',r.name||'')+field('Paygrade','rank_paygrade',r.paygrade||'')+field('Next rank','rank_next_rank',r.next_rank||'')+field('Required qualifications','rank_certificates',(r.certificates||[]).join(';'))+'<button type="button">Remove</button>';row.querySelector('button').onclick=()=>row.remove();el('rank-rows').append(row);}
    (c.paygrades||[]).forEach(addGrade);(c.ranks||[]).forEach(addRank);el('grade-add').onclick=()=>addGrade();el('rank-add').onclick=()=>addRank();baseline=signature();
  }
  function renderStaff(){
    el('staff-list').innerHTML=detail.staff.map(s=>`<div class="unit-block"><strong>${esc(s.username)}</strong> · ${s.role==='admin'?'Unit administrator':'Staff'}${!s.enabled?' · Account disabled':''}<p class="feature-note">${s.role==='admin'?'Full unit administration':s.capabilities.includes('roster')?'Can edit roster':'View unit records'}</p><button data-staff="${s.user_id}">Edit membership</button></div>`).join('');
    el('staff-list').querySelectorAll('[data-staff]').forEach(b=>b.onclick=()=>staffEditor(detail.staff.find(s=>s.user_id===Number(b.dataset.staff))));
  }
  function staffEditor(staff={}){
    openDialog('Unit staff access',`${field('Existing panel username','username',staff.username||'')}<label class="unit-field">Unit role<select name="role"><option value="staff">Staff</option><option value="admin" ${staff.role==='admin'?'selected':''}>Unit administrator</option>${staff.user_id?'<option value="remove">Remove from this unit</option>':''}</select></label><label><input type="checkbox" name="roster_permission" ${staff.capabilities?.includes('roster')?'checked':''}> Staff may edit roster</label><p class="feature-note">Unit administrators can manage members, ranks, qualifications and staff access. This does not grant server controls or panel administration.</p>`,async()=>{const data=values();await write(`/api/units/${unitId}/staff`,{username:data.username,role:data.role,capabilities:data.role==='staff'&&data.roster_permission?['roster']:[],revision:detail.unit.revision});});
    if(staff.username)form.elements.username.readOnly=true;
  }
  async function renderServers(unit){
    el('unit-server-list').textContent='Loading health…';
    try{const data=await read(`/api/units/${unitId}/health`);if(unit.id!==unitId)return;
      el('unit-server-list').innerHTML=data.servers.map(s=>`<div class="unit-block"><strong>${esc(listing.servers.find(item=>item.id===s.id)?.name||'Unavailable server')}</strong><p>${s.unavailable?'Unavailable':s.running?'Online':'Offline'}${!s.unavailable?' · CPU '+Number(s.cpu).toFixed(1)+'% · '+(s.ram_process/1024).toFixed(2)+' GiB':''}</p>${s.can_open?`<a class="manager-link" href="${s.id?'/?server='+encodeURIComponent(s.id):'/?legacy=1'}">Open server</a>`:''}</div>`).join('')||'<p>No servers linked. A panel administrator can assign them in Unit settings.</p>';
    }catch(error){el('unit-server-list').textContent=error.message;}
  }
  function selectTab(key){document.querySelectorAll('[data-unit-tab]').forEach(b=>{const active=b.dataset.unitTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;el('unit-'+b.dataset.unitTab).hidden=!active;});}
  document.querySelectorAll('[data-unit-tab]').forEach(b=>{
    b.onclick=()=>selectTab(b.dataset.unitTab);
    b.onkeydown=e=>{const tabs=[...document.querySelectorAll('[data-unit-tab]')].filter(t=>!t.hidden);let i=tabs.indexOf(b);if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();i=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[i].click();tabs[i].focus();};
  });
  document.addEventListener('unit-access-changed',()=>loadListing());
  el('position-rename').onclick=()=>openDialog('Rename position',`<label class="unit-field">Existing position<select name="old">${options(detail.unit.catalog.positions||[],'','Choose position')}</select></label>${field('New name','name')}<p class="feature-note">Updates this unit’s current and former roster assignments together.</p>`,async()=>{const data=values();await write(`/api/units/${unitId}/positions/rename`,{...data,revision:detail.unit.revision});});
  el('unit-new').onclick=()=>unitSettings(true);el('unit-settings').onclick=()=>unitSettings();el('roster-add').onclick=()=>memberEditor();el('catalog-edit').onclick=catalogEditor;el('staff-add').onclick=()=>staffEditor();
  for(const id of ['roster-search','roster-status','roster-section','roster-sort'])el(id).addEventListener(id==='roster-search'?'input':'change',renderRoster);
  el('unit-select').onchange=()=>{unitId=Number(el('unit-select').value);loadUnit();};el('unit-refresh').onclick=()=>loadListing();
  el('unit-users').onclick=async()=>{el('panel-users').hidden=!el('panel-users').hidden;if(!el('panel-users').hidden){await loadUsers();el('panel-users').scrollIntoView();}};
  el('users-new').onclick=()=>openUserEditor();
  read('/api/me').then(account=>{window.unitAccount=account;return loadListing(Number(new URLSearchParams(location.search).get('unit')));}).then(async()=>{if(listing?.panel_admin&&new URLSearchParams(location.search).has('users')){el('panel-users').hidden=false;await loadUsers();}}).catch(error=>feedback(error.message));
})();
