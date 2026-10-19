let moderationAction='ban', moderationBusy=false, banRows=[], banPage=1;
function openModeration(player,action){
  if(!can('admin_config')||moderationBusy)return;
  moderationAction=action;
  byId('moderation-form').reset();
  byId('moderation-heading').textContent=action==='kick'?'Kick player':action==='unban'?'Remove ban':'Ban player';
  byId('moderation-target').textContent=(player?.name||'Selected server')+(action==='kick'?' · Disconnects this player. They can rejoin. The reason is recorded in Activity.':action==='ban'?' · Prevents joining for the chosen duration. Permanent bans require manual removal.':' · Allows this identity to join again.');
  byId('moderation-identity').value=player?.identity||'';
  byId('moderation-identity').readOnly=!!player;
  byId('moderation-duration').closest('.field').hidden=action!=='ban';
  byId('moderation-feedback').textContent='';byId('moderation-submit').disabled=false;
  byId('moderation-dialog').showModal();
}
byId('moderation-cancel').onclick=()=>{if(!moderationBusy)byId('moderation-dialog').close();};
byId('moderation-dialog').addEventListener('cancel',event=>{if(moderationBusy)event.preventDefault();});
byId('moderation-form').onsubmit=async event=>{
  event.preventDefault();if(moderationBusy)return;
  moderationBusy=true;byId('moderation-submit').disabled=true;byId('moderation-cancel').disabled=true;
  try{
    const result=await changeFeature('/api/players/moderate',{action:moderationAction,identity:byId('moderation-identity').value.trim(),duration:Number(byId('moderation-duration').value),reason:byId('moderation-reason').value.trim()});
    byId('operator-player-feedback').textContent=result.message;
    byId('moderation-dialog').close();
    if(!byId('moderation-bans').hidden&&byId('moderation-bans').open)await loadBans(banPage);
    await loadOperatorPlayers(true);
  }catch(error){byId('moderation-feedback').textContent=error.message;}
  finally{moderationBusy=false;byId('moderation-submit').disabled=false;byId('moderation-cancel').disabled=false;}
};
function drawBans(){
  const list=byId('ban-list');list.replaceChildren();const search=byId('ban-search').value.toLowerCase();
  for(const ban of banRows.filter(b=>b.identity.toLowerCase().includes(search))){
    const row=operationElement('div','','operator-row'),info=document.createElement('div');
    info.append(operationElement('strong',ban.identity),operationElement('small','Game duration: '+ban.duration));row.append(info);
    const remove=operationElement('button','Unban','config-button');remove.onclick=()=>openModeration(ban,'unban');row.append(remove);list.append(row);
  }
  if(!list.children.length)list.append(operationElement('p','No parsed bans match this page. Check the game response below for status or unsupported reply formats.','feature-note'));
}
let bansLoading=false;
async function loadBans(page=1){
  if(bansLoading||!can('admin_config'))return;bansLoading=true;
  byId('ban-feedback').textContent='Reading game ban list…';
  try{
    const result=await getFeature('/api/players/bans?page='+page);banRows=result.bans;banPage=result.page;drawBans();
    byId('ban-output').textContent=result.output;byId('ban-feedback').textContent=result.note;
    byId('bans-page').textContent='Page '+banPage;byId('bans-previous').disabled=banPage===1;byId('bans-next').disabled=!result.next_page;
  }catch(error){banRows=[];drawBans();byId('ban-output').textContent='';byId('ban-feedback').textContent=error.message;byId('bans-next').disabled=true;}
  finally{bansLoading=false;}
}
byId('ban-search').oninput=drawBans;
byId('bans-previous').onclick=()=>loadBans(banPage-1);
byId('bans-next').onclick=()=>loadBans(banPage+1);
byId('moderation-bans').ontoggle=()=>{if(byId('moderation-bans').open)loadBans();};
