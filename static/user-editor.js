// One account editor shared by the server administration and unit workspace.
let userEditorData, userEditorDialog, userEditorBaseline='';
const userEditorEl=id=>document.getElementById(id);
const userEditorRead=async url=>readJson(await fetch(url));
const userEditorWrite=async(url,data)=>readJson(await postJson(url,data));
function userEditorSignature(){return JSON.stringify([...new FormData(userEditorEl('user-editor-form'))]);}
async function loadUsers(){
  userEditorData=await userEditorRead('/api/users');
  const list=userEditorEl('users-list');
  list.innerHTML='<div class="unit-toolbar"><input type="search" id="users-search" aria-label="Search accounts" placeholder="Search username"><select id="users-unit-filter" aria-label="Filter accounts by unit"><option value="">All units</option>'+userEditorData.units.map(u=>`<option value="${u.id}">${escHtml(u.name)}</option>`).join('')+'</select><select id="users-server-filter" aria-label="Filter accounts by server"><option value="">All servers</option>'+userEditorData.servers.map(s=>`<option value="${escHtml(s.id)}">${escHtml(s.name)}</option>`).join('')+'</select><select id="users-role-filter" aria-label="Filter accounts by panel role"><option value="">All panel roles</option><option value="admin">Panel administrators</option><option value="staff">Staff</option></select><select id="users-enabled-filter" aria-label="Filter accounts by enabled state"><option value="">All accounts</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></div><div id="users-results"></div>';
  const render=()=>{
    const query=userEditorEl('users-search').value.trim().toLowerCase(),unit=userEditorEl('users-unit-filter').value,server=userEditorEl('users-server-filter').value,role=userEditorEl('users-role-filter').value,enabled=userEditorEl('users-enabled-filter').value;
    const rows=userEditorData.users.filter(u=>u.username.toLowerCase().includes(query)&&(!unit||u.units.some(m=>String(m.unit_id)===unit))&&(!server||u.access_all||u.server_roles[server])&&(!role||(role==='admin')===!!u.panel_admin)&&(!enabled||(enabled==='enabled')===!!u.enabled));
    userEditorEl('users-results').innerHTML=rows.map(u=>`<div class="unit-block feature-row"><span><strong>${escHtml(u.username)}</strong> · ${u.is_owner?'Owner':u.panel_admin?'Panel administrator':'Staff'}${u.enabled?'':' · Disabled'}<small class="unit-meta">${u.units.length} unit memberships</small></span><button data-edit-user="${u.id}">Edit</button></div>`).join('')||'<p>No matching accounts.</p>';
    userEditorEl('users-results').querySelectorAll('[data-edit-user]').forEach(b=>b.onclick=()=>openUserEditor(Number(b.dataset.editUser)));
  };
  for(const id of ['users-search','users-unit-filter','users-server-filter','users-role-filter','users-enabled-filter'])userEditorEl(id).addEventListener(id==='users-search'?'input':'change',render);
  render();
}
async function openUserEditor(userId){
  try{
    await loadUsers();
    const user=userEditorData.users.find(u=>u.id===userId),esc=escHtml;
    const me=window.unitAccount||(typeof currentAccount!=='undefined'?currentAccount:{});
    if(user?.is_owner&&me.id!==user.id)throw new Error('Only the Owner can edit the Owner account');
    if(!userEditorDialog){
      userEditorDialog=document.createElement('dialog');userEditorDialog.className='user-editor';userEditorDialog.setAttribute('aria-labelledby','user-editor-title');document.body.append(userEditorDialog);
      userEditorDialog.addEventListener('cancel',e=>{e.preventDefault();closeUserEditor();});
    }
    const roleOptions=selected=>[['','No access'],['viewer','Viewer'],['operator','Operator'],['manager','Manager'],['admin','Server administrator']].map(([value,label])=>`<option value="${value}" ${value===selected?'selected':''}>${label}</option>`).join('');
    userEditorDialog.innerHTML=`<form id="user-editor-form" novalidate><div class="user-editor-heading"><h2 id="user-editor-title">${user?'Edit '+esc(user.username):'Create account'}</h2><button type="button" id="user-editor-close">Close</button></div><div class="section-tabs" role="tablist" aria-label="Account sections">${['Account','Servers','Units'].map((name,i)=>`<button type="button" role="tab" id="user-tab-${name}" aria-controls="user-pane-${name}" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-user-tab="${name}">${name}</button>`).join('')}</div>
      <section id="user-pane-Account" role="tabpanel" aria-labelledby="user-tab-Account"><label class="unit-field">Username<input name="username" value="${esc(user?.username||'')}" maxlength="32" required autocomplete="off"></label><label class="unit-field">Panel role<select name="panel_admin" ${user?.is_owner?'disabled':''}><option value="staff">Staff</option><option value="admin" ${user?.panel_admin?'selected':''}>Panel administrator</option></select></label><label><input type="checkbox" name="enabled" ${!user||user.enabled?'checked':''} ${user?.is_owner?'disabled':''}> Account enabled</label>${user?'<button type="button" id="user-password-toggle">Reset password…</button>':''}<label class="unit-field" id="user-password-field" ${user?'hidden':''}>${user?'New password':'Initial password'}<input name="password" type="password" autocomplete="new-password" minlength="10" ${user?'':'required'}></label>${user&&!user.is_owner&&user.id!==me.id?'<button type="button" id="user-delete-account">Delete account…</button>':''}<p class="feature-note">Only panel administrators create accounts and grant server or panel roles. Unit administrators manage unit membership through Staff access.</p></section>
      <section id="user-pane-Servers" role="tabpanel" aria-labelledby="user-tab-Servers" hidden><p class="feature-note">Server access is separate from unit membership.</p>${userEditorData.servers.map(s=>`<label class="unit-field">${esc(s.name)}<select name="server:${esc(s.id)}" ${user?.is_owner?'disabled':''}>${roleOptions(user?.server_roles[s.id]||'')}</select></label>`).join('')}<details><summary>Access to all current and future servers</summary><label><input type="checkbox" name="access_all" ${user?.access_all?'checked':''} ${user?.is_owner?'disabled':''}> Enable all-server access</label><label class="unit-field">Default server role<select name="role" ${user?.is_owner?'disabled':''}>${roleOptions(user?.role||'viewer').replace('<option value="" >No access</option>','')}</select></label><p class="feature-note">Explicit server roles override the default. All-server access does not reveal other units.</p></details></section>
      <section id="user-pane-Units" role="tabpanel" aria-labelledby="user-tab-Units" hidden>${userEditorData.units.map(u=>{const m=user?.units.find(m=>m.unit_id===u.id);return `<div class="unit-block"><label class="unit-field">${esc(u.name)}<select name="unit:${u.id}"><option value="">Not assigned</option><option value="staff" ${m?.role==='staff'?'selected':''}>Staff</option><option value="admin" ${m?.role==='admin'?'selected':''}>Unit administrator</option></select></label><label><input type="checkbox" name="roster:${u.id}" ${m?.capabilities.includes('roster')?'checked':''}> Staff may edit roster</label>${['events','attendance'].map(cap=>`<label><input type="checkbox" name="${cap}:${u.id}" ${m?.capabilities.includes(cap)?'checked':''}> Staff may ${cap==='events'?'manage events':'review attendance'}</label>`).join('')}</div>`;}).join('')||'<p>Create a unit first.</p>'}<p class="feature-note">Removing unit membership preserves roster records. Separately assigned server access stays in effect.</p></section><p id="user-editor-error" role="alert"></p><div class="user-editor-footer"><span id="user-editor-summary" class="feature-note"></span><button type="submit" class="btn-save">Save changes</button></div></form>`;
    const form=userEditorEl('user-editor-form');
    function selectTab(key){userEditorDialog.querySelectorAll('[data-user-tab]').forEach(b=>{const active=b.dataset.userTab===key;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;userEditorEl('user-pane-'+b.dataset.userTab).hidden=!active;});}
    userEditorDialog.querySelectorAll('[data-user-tab]').forEach(b=>{b.onclick=()=>selectTab(b.dataset.userTab);b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...userEditorDialog.querySelectorAll('[data-user-tab]')];const i=e.key==='Home'?0:e.key==='End'?2:(tabs.indexOf(b)+(e.key==='ArrowRight'?1:-1)+3)%3;tabs[i].click();tabs[i].focus();};});
    userEditorEl('user-editor-close').onclick=closeUserEditor;
    userEditorEl('user-password-toggle')?.addEventListener('click',()=>{userEditorEl('user-password-field').hidden=false;form.elements.password.focus();});
    userEditorEl('user-delete-account')?.addEventListener('click',async()=>{
      if(!confirm(`Delete account "${user.username}"? Remove its unit memberships first. Its activity history will remain.`))return;
      try{await userEditorWrite('/api/users/delete',{id:user.id});userEditorDialog.close();await loadUsers();}
      catch(error){userEditorEl('user-editor-error').textContent=error.message;}
    });
    form.oninput=()=>{const values=new FormData(form);const units=userEditorData.units.filter(u=>values.get('unit:'+u.id));const servers=userEditorData.servers.filter(s=>values.get('server:'+s.id));userEditorEl('user-editor-summary').textContent=`${values.get('panel_admin')==='admin'||user?.is_owner?'Panel administrator':'Staff'} · ${units.length} units · ${values.has('access_all')||user?.is_owner?'all servers':servers.length+' server assignments'}`;};
    form.onsubmit=async e=>{
      e.preventDefault();if(!form.checkValidity()){selectTab('Account');form.reportValidity();return;}const button=form.querySelector('[type="submit"]');button.disabled=true;userEditorEl('user-editor-error').textContent='';
      try{
        const values=new FormData(form);
        const body={username:values.get('username').trim(),role:user?.is_owner?'admin':values.get('role')||'viewer',panel_admin:user?.is_owner||values.get('panel_admin')==='admin',enabled:user?.is_owner||values.has('enabled'),access_all:user?.is_owner||values.has('access_all'),server_roles:user?.is_owner?{}:Object.fromEntries(userEditorData.servers.filter(s=>values.get('server:'+s.id)).map(s=>[s.id,values.get('server:'+s.id)])),units:userEditorData.units.filter(u=>values.get('unit:'+u.id)).map(u=>({unit_id:u.id,role:values.get('unit:'+u.id),capabilities:values.get('unit:'+u.id)==='staff'?['roster','events','attendance'].filter(cap=>values.has(cap+':'+u.id)):[]})),unit_revisions:Object.fromEntries(userEditorData.units.map(u=>[u.id,u.revision])),...(user?{id:user.id,version:user.version}:{})};
        if(values.get('password'))body.password=values.get('password');
        await userEditorWrite('/api/users',body);userEditorDialog.close();await loadUsers();document.dispatchEvent(new Event('unit-access-changed'));
      }catch(error){userEditorEl('user-editor-error').textContent=error.message;}
      finally{button.disabled=false;}
    };
    userEditorDialog.showModal();form.oninput();userEditorBaseline=userEditorSignature();form.elements.username.focus();
  }catch(error){const target=userEditorEl('units-feedback')||userEditorEl('users-restricted');if(target){target.hidden=false;target.textContent=error.message;}}
}
function closeUserEditor(){if(userEditorSignature()!==userEditorBaseline&&!confirm('Discard unsaved account changes?'))return;userEditorDialog.close();}
