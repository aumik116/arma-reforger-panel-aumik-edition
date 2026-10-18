// Focused regression tests for background refreshes; no browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname, '..', 'static', name), 'utf8');
const between = (text, first, next) => text.slice(text.indexOf(first), text.indexOf(next));

// A ten-second config poll must preserve a number currently being typed.
{
  const fields = new Map();
  const get = id => {
    if (!fields.has(id)) fields.set(id, {value:'', textContent:'', classList:{remove(){}}, checkValidity:()=>true});
    return fields.get(id);
  };
  const paths = {'network-view-distance':'game.distance', 'network-max-players':'game.players'};
  const context = vm.createContext({
    networkLeverPaths:paths, configSnapshot:{game:{distance:1000, players:64}},
    networkInfo:null, configPending:false, configChanges:{}, document:{activeElement:null},
    can:()=>true, byId:get, renderConfigFields(){}, configMissions:[],
    configGet:(object,key)=>key.split('.').reduce((value,part)=>value[part],object),
    configDraft:()=>({game:{distance:1000,players:64}}), updateConfigDraft(){}
  });
  vm.runInContext(between(source('network.js'), 'function syncNetworkForm()', 'Object.keys(networkLeverPaths).forEach'), context);
  context.syncNetworkForm();
  const input = get('network-view-distance'); input.id='network-view-distance';
  context.document.activeElement=input; input.value='1250';
  context.syncNetworkForm(); assert.equal(input.value,'1250');
  context.updateNetworkLever({target:input}); assert.equal(context.configChanges['game.distance'],1250);
  input.value=''; context.syncNetworkForm(); assert.equal(input.value,'');
  assert.match(source('network.js'), /addEventListener\('input', updateNetworkLever\)/);
}

class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.dataset={}; this.parent=null; }
  append(...children) { for (const child of children) { child.remove(); child.parent=this; this.children.push(child); } }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this),1); this.parent=null; } }
  insertBefore(child,before) { child.remove(); child.parent=this; const i=before?this.children.indexOf(before):this.children.length; this.children.splice(i,0,child); }
  querySelectorAll(selector) { return this.children.filter(child=>selector==='[data-update-id]' && child.dataset.updateId); }
  querySelector(selector) { return this.children.find(child=>child.tag===selector); }
  setAttribute() {}
}

// Metadata arriving for another mod must not replace a focused update checkbox.
{
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id,new Element('div')); return elements.get(id); };
  const mods=[{modId:'AAAA', name:'First', version:'1'}];
  const context = vm.createContext({
    modLibrary:{mods, metadata:new Map([['AAAA',{status:'available'}]])},
    modUpdates:{selected:new Set()}, modEl:get, can:()=>true,
    modUpdateCandidate:mod=>({mod,from:'1',to:'2'}),
    document:{activeElement:null, createElement:tag=>new Element(tag)}
  });
  vm.runInContext(between(source('mods.js'),'function renderModUpdates()','function reviewModUpdates()'),context);
  context.renderModUpdates();
  const list=get('mods-update-list'), checkbox=list.children[0].querySelector('input');
  context.document.activeElement=checkbox;
  mods.push({modId:'BBBB',name:'Second',version:'1'});
  context.modLibrary.metadata.set('BBBB',{status:'available'});
  context.renderModUpdates();
  assert.equal(list.children[0].querySelector('input'),checkbox);
  assert.equal(context.document.activeElement,checkbox);
  assert.equal(checkbox.parent.parent,list);
  assert.equal(list.children.length,2);
}
// Moving administrators into their own card must retain every schema field.
{
  const groups = [
    {title:'Access',fields:[{path:'game.password',kind:'password'},{path:'game.admins',kind:'admins'}]},
    {title:'Operating',fields:[{path:'operating.playerSaveTime',kind:'int'}]},
    {title:'Persistence',fields:[{path:'game.gameProperties.persistence.autoSaveInterval',kind:'int'}]}
  ];
  const before = JSON.stringify(groups);
  const context = vm.createContext({configGroups:groups});
  const arrange = between(source('configuration.js'),'  const playerSave =','  displayGroups.map(');
  vm.runInContext(arrange + '\nglobalThis.arranged = displayGroups;',context);
  assert.deepEqual(context.arranged.flatMap(group=>group.fields.map(field=>field.path)).sort(),
    groups.flatMap(group=>group.fields.map(field=>field.path)).sort());
  assert.equal(context.arranged.find(group=>group.title==='In-game administrators').fields[0].path,'game.admins');
  assert.equal(JSON.stringify(groups),before);
}
console.log('Frontend refresh and configuration-layout regressions passed');

// An overview control must target its row, including after another row is used.
(async () => {
  const calls = [], feedback = {textContent:''};
  const context = vm.createContext({CSRF:'token', busy:new Set(), feedback,
    confirm:()=>true, refresh:async()=>{},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({ok:true})};}});
  vm.runInContext(between(source('servers.js'),'  async function action(', '  function render('),context);
  for (const id of ['training','everon','']) await context.action({id,name:id || 'Existing'},'restart',{disabled:false});
  assert.equal(calls[0].options.headers['X-Server-ID'],'training');
  assert.equal(calls[1].options.headers['X-Server-ID'],'everon');
  assert.equal(calls[2].options.headers['X-Server-ID'],undefined);
  assert.equal(calls[0].options.headers['X-CSRF-Token'],'token');
  assert.equal(context.busy.size,0);
  console.log('Overview controls preserve per-server targets and CSRF');
})().catch(error=>{console.error(error);process.exitCode=1;});

// The access summary must distinguish server control from panel administration.
{
  const choice = {dataset:{server:'training'},value:'operator',selectedOptions:[{textContent:'Start, stop and read logs'}]};
  const fields = {
    'user-all-servers':{checked:false},
    'user-server-access':{querySelectorAll:()=>[choice]},
    'user-role':{selectedOptions:[{textContent:'Full server administration'}]},
    'user-panel-admin':{value:'staff'},'user-enabled':{checked:true},
    'user-access-summary':{textContent:''}
  };
  const context=vm.createContext({byId:id=>fields[id],accountServers:[{id:'training',name:'Training'}]});
  vm.runInContext(between(source('features.js'),'function updateUserAccessSummary()', 'function resetUserForm()'),context);
  context.updateUserAccessSummary();
  assert.equal(fields['user-access-summary'].textContent,'Training: Start, stop and read logs. Cannot manage panel users.');
  fields['user-all-servers'].checked=true; context.updateUserAccessSummary();
  assert.match(fields['user-access-summary'].textContent,/Every current and future server: Full server administration/);
  assert.match(fields['user-access-summary'].textContent,/Cannot manage panel users/);
  fields['user-panel-admin'].value='admin'; context.updateUserAccessSummary();
  assert.match(fields['user-access-summary'].textContent,/Can manage panel users and grant access to any server/);
  fields['user-enabled'].checked=false; context.updateUserAccessSummary();
  assert.match(fields['user-access-summary'].textContent,/Account disabled: cannot sign in/);
  console.log('Permission summaries explain server scope, panel privileges and disabled accounts');
}

// Storage uses decimal units rather than relabeling binary GiB values.
{
  const nodes=new Map();
  const context=vm.createContext({byId:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}});
  vm.runInContext(source('storage.js'),context);
  assert.equal(vm.runInContext('storageBytes(1000000000)',context),'1.00 GB');
  assert.equal(vm.runInContext('storageBytes(1500000)',context),'1.50 MB');
  assert.equal(vm.runInContext('storageBytes(2500)',context),'2.5 KB');
}
console.log('Storage displays decimal GB and MB');
