const workshopState={page:1,category:'',request:0,detailRequest:0,previewRequest:0};
function workshopNode(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function workshopButton(text,action,write=false){const button=workshopNode('button',text);button.type='button';button.onclick=action;if(write)button.disabled=!can('mods');return button;}
function workshopSize(value){return Number.isFinite(value)?(value>=1e9?`${(value/1e9).toFixed(2)} GB`:`${(value/1000000).toFixed(1)} MB`):'Size unavailable';}
async function workshopGet(url){const response=await fetch(url);const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'Workshop request failed');return data;}
function workshopImage(asset){if(!asset.thumbnail)return workshopNode('div','No preview','workshop-image');const img=workshopNode('img');img.src=asset.thumbnail;img.alt='';img.loading='lazy';img.className='workshop-image';img.referrerPolicy='no-referrer';return img;}
async function loadWorkshop(reset=false){
  if(reset)workshopState.page=1;
  const serial=++workshopState.request;
  const status=modEl('workshop-status');status.textContent='Loading Workshop…';
  modEl('workshop-previous').disabled=true;modEl('workshop-next').disabled=true;
  try{
    const query=new URLSearchParams({search:modEl('workshop-search').value,sort:modEl('workshop-sort').value,category:workshopState.category,page:workshopState.page});
    const data=await workshopGet('/api/mods/workshop?'+query);if(serial!==workshopState.request)return;
    const grid=modEl('workshop-grid');grid.replaceChildren();
    for(const asset of data.items){
      const card=workshopNode('article',undefined,'workshop-card');const detail=workshopButton('',()=>openWorkshopDetails(asset.modId));detail.className='workshop-card-open';detail.append(workshopImage(asset),workshopNode('h3',asset.name),workshopNode('p','by '+asset.author));
      const installed=modLibrary.mods.find(m=>m.modId.toUpperCase()===asset.modId);
      detail.append(workshopNode('p',`${installed?'On server · ':''}${workshopSize(asset.size)} · v${asset.version}`),workshopNode('p',`${(asset.subscribers??0).toLocaleString()} subscribers · ${typeof asset.rating==='number'?Math.round(asset.rating*100)+'% rating':'Unrated'}`));card.append(detail);const actions=workshopNode('div',undefined,'workshop-toolbar');actions.append(workshopButton(installed?'Set to latest':'Add now',async()=>{await openWorkshopDetails(asset.modId);await previewWorkshop(asset,'add','',true);},true),workshopButton('Add to queue',()=>queueWorkshopMod(asset.modId),true));card.append(actions);grid.append(card);
    }
    status.textContent=`${data.count.toLocaleString()} mods${data.items.length?'':' · No matches'}`;
    modEl('workshop-page').textContent=`Page ${data.page}`;
    modEl('workshop-previous').disabled=data.page<=1;modEl('workshop-next').disabled=data.page*16>=data.count;
  }catch(error){if(serial===workshopState.request){status.textContent=error.message;modEl('workshop-grid').replaceChildren(workshopButton('Retry',()=>loadWorkshop()));}}
}
async function openWorkshopDetails(id){
  const serial=++workshopState.detailRequest;const dialog=modEl('workshop-detail');const body=modEl('workshop-detail-content');body.replaceChildren(workshopNode('h2','Loading mod…'));modEl('workshop-preview').replaceChildren();modEl('workshop-detail-status').textContent='';if(!dialog.open)dialog.showModal();
  try{
    const {asset}=await workshopGet('/api/mods/workshop/'+encodeURIComponent(id));if(serial!==workshopState.detailRequest)return;
    body.replaceChildren(workshopImage(asset),workshopNode('h2',asset.name));body.querySelector('h2').id='workshop-title';
    body.append(workshopNode('p',`by ${asset.author} · ${workshopSize(asset.size)}`),workshopNode('p',`${(asset.subscribers??0).toLocaleString()} subscribers · ${typeof asset.rating==='number'?Math.round(asset.rating*100)+'% positive':'Unrated'} (${asset.ratings??0} ratings)`));
    const tags=workshopNode('div',undefined,'workshop-toolbar');for(const tag of asset.tags)tags.append(workshopNode('span',tag,'workshop-tag'));body.append(tags);
    const configured=modLibrary.mods.find(m=>m.modId.toUpperCase()===id.toUpperCase());body.append(workshopNode('p',configured?`On server · ${configured.version?'Pinned v'+configured.version:'Tracks latest'}`:'Not on this server'));
    const actions=workshopNode('div',undefined,'workshop-toolbar');
    actions.append(workshopButton(configured?'Set to latest':'Add now',()=>previewWorkshop(asset,'add','',false),true));
    actions.append(workshopButton('Add to queue',()=>queueWorkshopMod(asset.modId),true));
    if(asset.dependencies.length)actions.append(workshopButton('Add with dependencies',()=>previewWorkshop(asset,'add','',true),true));
    if(configured){actions.append(workshopButton('Remove from server',()=>previewWorkshop(asset,'remove'),true));actions.append(workshopButton('Edit fields',()=>{dialog.close();openModDetails(configured);},true));}
    const link=workshopNode('a','View on Workshop');link.href='https://reforger.armaplatform.com/workshop/'+asset.modId;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);body.append(actions);
    body.append(workshopNode('h3',`Dependencies (${asset.dependencies.length})`));
    for(const dep of asset.dependencies){const row=workshopNode('div',undefined,'workshop-row');row.append(workshopNode('span',`${dep.asset.name} · v${dep.version} · ${workshopSize(dep.totalFileSize)}`),workshopButton('View',()=>openWorkshopDetails(dep.asset.id)));body.append(row);}
    if(asset.tags.some(tag=>tag.toUpperCase()==='TERRAINS')){
      body.append(workshopNode('h3','Scenarios in this mod'));
      for(const scenario of asset.scenarios||[]){
        const card=workshopNode('div',undefined,'workshop-scenario');
        card.append(workshopNode('h4',scenario.name),workshopNode('p',scenario.description),
          workshopNode('p',`${scenario.mode.replace('#AR-Scenario_GameMode_','')}${scenario.players?' · '+scenario.players+' players':''}`),workshopNode('code',scenario.id));
        const use=workshopButton('Use scenario',()=>previewWorkshop(asset,'add','',true,scenario.id),true);use.disabled=!can('mods')||!can('configure');card.append(use);body.append(card);
      }
      if(!asset.scenarios?.length)body.append(workshopNode('p','The Workshop does not list scenarios for this terrain’s current release.','feature-note'));
    }
    body.append(workshopNode('h3','Version history'));
    const versionRow=workshopNode('div',undefined,'workshop-toolbar');
    const versionSelect=workshopNode('select');versionSelect.id='workshop-version';
    const versionLabel=workshopNode('label','Release');versionLabel.htmlFor=versionSelect.id;
    const latest=workshopNode('option','Track latest');latest.value='';versionSelect.append(latest);
    for(const version of asset.versions){const option=workshopNode('option',`v${version.version} · game ${version.game||'unknown'} · ${workshopSize(version.size)} · ${(version.date||'').slice(0,10)}`);option.value=version.version;versionSelect.append(option);}
    versionSelect.value=configured?.version||'';
    versionRow.append(versionLabel,versionSelect,workshopButton('Preview version change',()=>previewWorkshop(asset,'add',versionSelect.value,false),true));body.append(versionRow);
    body.append(workshopNode('p','Latest follows updates. Choosing a release pins that version. Historical dependency versions must be managed separately.','feature-note'));
    body.append(workshopNode('h3','Description'),workshopNode('p',asset.description,'workshop-description'));
  }catch(error){if(serial===workshopState.detailRequest)body.replaceChildren(workshopNode('h2','Workshop unavailable'),workshopNode('p',error.message),workshopButton('Retry',()=>openWorkshopDetails(id)));}
}
async function previewWorkshop(asset,action,version='',dependencies=false,scenario=''){
  const serial=workshopState.detailRequest;const previewSerial=++workshopState.previewRequest;const status=modEl('workshop-detail-status');const panel=modEl('workshop-preview');status.textContent='Preparing change preview…';panel.replaceChildren();
  try{
    const query=new URLSearchParams({action,version,dependencies:dependencies?'1':'0',scenario});const data=await workshopGet(`/api/mods/workshop/${asset.modId}/preview?${query}`);if(serial!==workshopState.detailRequest||previewSerial!==workshopState.previewRequest)return;
    status.textContent='Review changes before saving. Restart the server after saving to apply them.';
    const before=new Map(modLibrary.mods.map(m=>[m.modId.toUpperCase(),m]));const after=new Map(data.mods.map(m=>[m.modId.toUpperCase(),m]));
    for(const [id,mod] of after)if(JSON.stringify(before.get(id))!==JSON.stringify(mod))panel.append(workshopNode('p',`${before.has(id)?'Change':'Add'}: ${mod.name||id} · ${mod.version?'pin v'+mod.version:'latest'}`));
    for(const [id,mod] of before)if(!after.has(id))panel.append(workshopNode('p','Remove: '+(mod.name||id)));
    if(data.scenario)panel.append(workshopNode('p','Use scenario: '+data.scenario));
    for(const note of data.notes)panel.append(workshopNode('p',note,'feature-note'));
    panel.append(workshopButton('Save changes',async function(){this.disabled=true;try{await changeFeature('/api/mods/workshop/apply',{token:data.token});await fetchStatus();await openWorkshopDetails(asset.modId);}catch(error){status.textContent=error.message;this.disabled=false;}},true));panel.scrollIntoView({block:'nearest'});
  }catch(error){if(serial===workshopState.detailRequest)status.textContent=error.message;}
}
modEl('workshop-search-form').onsubmit=event=>{event.preventDefault();loadWorkshop(true);};
modEl('workshop-sort').onchange=()=>loadWorkshop(true);
modEl('workshop-previous').onclick=()=>{workshopState.page--;loadWorkshop();};modEl('workshop-next').onclick=()=>{workshopState.page++;loadWorkshop();};
for(const category of ['',...'TERRAINS WEAPONS VEHICLES STRUCTURES CHARACTERS ANIMALS VEGETATION PROPS COMPOSITIONS SCENARIOS_SP SCENARIOS_MP SYSTEMS EFFECTS MISC'.split(' ')]){const button=workshopButton(category||'All',()=>{workshopState.category=category;for(const sibling of button.parentElement.children)sibling.setAttribute('aria-pressed',String(sibling===button));loadWorkshop(true);});button.setAttribute('aria-pressed',String(!category));modEl('workshop-categories').append(button);}

async function queueWorkshopMod(modId){
  const status=modEl('workshop-detail').open?modEl('workshop-detail-status'):modEl('workshop-status');
  status.textContent='Adding mod and dependencies to queue…';
  try{await readJson(await postJson('/api/mods/draft/queue',{modId}));status.textContent='Added to queue with known dependencies. Open Review queue to review changes and size estimates.';}
  catch(error){status.textContent=error.message;}
}
