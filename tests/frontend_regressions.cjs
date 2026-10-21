// Focused regression tests for background refreshes; no browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
require('./server_controls.cjs');
require('./login_and_pwa.cjs');
require('./fleet_dashboard.cjs');
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
  const context = vm.createContext({busy:new Set(), feedback, Headers, Request, URL, URLSearchParams,
    location:{href:'https://panel.test/servers?server=unrelated',origin:'https://panel.test',search:'?server=unrelated'},
    document:{dispatchEvent(){}}, CustomEvent:class {},
    confirm:()=>true, refresh:async()=>{},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({ok:true})};}});
  context.window = context;
  vm.runInContext(source('api.js'),context);
  vm.runInContext('CSRF="token";',context);
  vm.runInContext(between(source('servers.js'),'  async function action(', '  function render('),context);
  for (const id of ['training','everon','']) await context.action({id,name:id || 'Existing'},'restart',{disabled:false});
  assert.equal(calls[0].options.headers.get('X-Server-ID'),'training');
  assert.equal(calls[1].options.headers.get('X-Server-ID'),'everon');
  assert.equal(calls[2].options.headers.get('X-Server-ID'),'');
  assert.equal(calls[0].options.headers.get('X-CSRF-Token'),'token');
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

// PlayStation warning uses the unrounded decimal total across all configured mods.
{
  const nodes = new Map();
  const library = {mods:[],metadata:new Map()};
  const context = vm.createContext({modLibrary:library,modEl:id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id);}});
  vm.runInContext(between(source('mods.js'),'function modSize(', 'function applyModMetadata('),context);
  vm.runInContext(between(source('mods.js'),'function formatModSize(', 'let modMetadataLoading='),context);
  function size(bytes) {
    library.mods=[{modId:'A'},{modId:'B',version:'pinned'},{modId:'a'}];
    library.metadata.set('A',{current_version:'latest',sizes:{latest:bytes}});
    library.metadata.set('B',{current_version:'latest',sizes:{pinned:1,latest:100000000000}});
    context.drawModTotal();
    return nodes.get('mods-psn-warning').hidden;
  }
  assert.equal(size(24999999998),true);
  assert.equal(size(24999999999),true); // Exactly 25 GB, including pinned mod.
  assert.equal(size(25000000000),false); // One byte above, even when display rounds to 25 GB.
  library.mods.push({modId:'unknown'});context.drawModTotal();
  assert.equal(nodes.get('mods-psn-warning').hidden,false);
  library.mods=[];context.drawModTotal();
  assert.equal(nodes.get('mods-psn-warning').hidden,true);
}
console.log('PSN warning respects 25 GB boundary, pinned versions, deduplication and removal');

// CPU ranges and presets use the existing startup draft without changing FPS/options.
{
  const nodes=new Map();
  const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false});return nodes.get(id);};
  const context=vm.createContext({byId:node,document:{},startupDirty:false,Array,Set,Number,String});
  vm.runInContext(between(source('operator-tools.js'),'let startupCpuCount=', 'async function loadStartup('),context);
  vm.runInContext('startupCpuCount=6; renderStartupCpus=()=>{};',context);
  assert.equal(JSON.stringify(context.selectedStartupCpus('0-2,2,5',6)),'[0,1,2,5]');
  assert.equal(JSON.stringify(context.selectedStartupCpus('',2)),'[0,1]');
  for(const invalid of ['6','2-1','0,,1','-1','0-9999','0;1'])assert.equal(context.selectedStartupCpus(invalid,6),null);
  assert.equal(context.startupCpuRanges([0,1,2,4,6,7]),'0-2,4,6-7');
  assert.equal(context.startupCpuRanges(Array.from({length:4096},(_,i)=>i)),'0-4095');
  node('operator-startup-fps').value=60;
  for(const [preset,cpus,high] of [['small','0-1',4000],['standard','0-3',8000],['large','',16000],['unrestricted','',0]]){
    node('operator-startup-memory-max').value=32000;
    node('startup-resource-preset').value=preset;
    node('startup-resource-preset').onchange({target:node('startup-resource-preset')});
    assert.equal(node('operator-startup-cpus').value,cpus);
    assert.equal(node('operator-startup-memory-high').value,high);
    assert.equal(node('operator-startup-memory-max').value,0);
    assert.equal(node('operator-startup-fps').value,60);
    assert.equal(node('operator-startup-save').disabled,false);
  }
  vm.runInContext('startupCpuCount=1;',context);
  node('startup-resource-preset').value='standard';
  node('startup-resource-preset').onchange({target:node('startup-resource-preset')});
  assert.equal(node('operator-startup-cpus').value,'');
  context.startupChanged();assert.equal(node('startup-resource-preset').value,'');
}
console.log('CPU range selection and editable presets preserve other launch settings');

// Folder uploads retain relative paths and continue after conflicts.
(async()=>{
  const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'selected',webkitdirectory:true,children:[],replaceChildren(){this.children=[];},append(item){this.children.push(item);}});return nodes.get(id);};
  const sent=[],messages=[];
  class Form {constructor(){this.values={};}append(key,value){this.values[key]=value;}}
  const context=vm.createContext({byId:node,AbortController,document:{createElement:()=>({})},filesUploadController:null,filesBusy:false,filesRoot:'profile',filesPath:'destination',
    confirmLeaveFile:()=>true,confirm:()=>true,updateFileActions:()=>{},filesFeedback:message=>messages.push(message),
    filesChildPath:name=>'destination/'+name,resetFileEditor:()=>{},refreshFiles:async()=>{},FormData:Form,
    postForm:async(url,form)=>{sent.push({url,...form.values});const ok=sent.length!==1;return {ok,json:async()=>({ok,error:'Already exists'})};}});
  vm.runInContext(between(source('files.js'),'async function uploadFiles(', 'async function openFilesTrash('),context);
  await context.uploadFiles([{name:'a.txt',webkitRelativePath:'Folder/sub/a.txt',size:1},{name:'a.txt',webkitRelativePath:'Folder/other/a.txt',size:1}],true);
  assert.deepEqual(sent.map(row=>row.path),['destination/Folder/sub/a.txt','destination/Folder/other/a.txt']);
  assert.ok(sent.every(row=>row.url==='/api/files/upload'&&row.create_parents==='true'&&row.root==='profile'));
  assert.match(nodes.get('files-upload-results').children[0].textContent,/Already exists/);
  assert.match(nodes.get('files-upload-results').children[1].textContent,/uploaded/);
  assert.match(nodes.get('files-upload-summary').textContent,/2 \/ 2 processed/);
  assert.equal(node('files-folder-input').value,'');
  assert.equal(context.filesBusy,false);
  console.log('Folder uploads preserve nested names and report partial failures');
})().catch(error=>{console.error(error);process.exitCode=1;});

// Checkbox selection, manual ranges and Use all stay synchronized without losing focus.
{
  class CpuNode {
    constructor(){this.children=[];this.value='';}
    append(...children){this.children.push(...children);}
    replaceChildren(){this.children=[];}
    querySelectorAll(selector){return this.children.flatMap(label=>label.children).filter(box=>box.type==='checkbox'&&(selector!=='input:checked'||box.checked));}
  }
  const nodes=new Map(),node=id=>{if(!nodes.has(id))nodes.set(id,new CpuNode());return nodes.get(id);};
  const context=vm.createContext({byId:node,operationElement:()=>new CpuNode(),document:{createElement:()=>new CpuNode(),createTextNode:text=>({text})},startupDirty:false});
  vm.runInContext(between(source('operator-tools.js'),'let startupCpuCount=', 'async function loadStartup('),context);
  vm.runInContext('startupCpuCount=4;renderStartupCpus();',context);
  const holder=node('startup-cpu-options'),boxes=holder.querySelectorAll('input');
  assert.equal(boxes.length,4);assert.ok(boxes.every(box=>box.checked));
  boxes[1].checked=false;boxes[1].onchange();
  assert.equal(node('operator-startup-cpus').value,'0,2-3');
  assert.equal(node('startup-cpu-all').checked,false);
  assert.equal(holder.querySelectorAll('input')[1],boxes[1]);
  node('operator-startup-cpus').value='3';context.renderStartupCpus();
  assert.deepEqual(holder.querySelectorAll('input:checked').map(box=>box.value),[3]);
  boxes[3].checked=false;boxes[3].onchange();assert.equal(boxes[3].checked,true);
  node('startup-cpu-all').checked=true;node('startup-cpu-all').onchange();
  assert.equal(node('operator-startup-cpus').value,'');assert.ok(boxes.every(box=>box.checked));
}
console.log('Visual CPU controls preserve selection, manual ranges and focused elements');

// A missing chart asset leaves a usable numeric dashboard.
{
  const warning={hidden:true},canvas={hidden:false};
  const context=vm.createContext({document:{getElementById:()=>warning}});
  vm.runInContext(between(source('dashboard.js'),'function createPanelChart(', 'function makeChartData('),context);
  const data={datasets:[{data:[1,2,3]}]};
  const fallback=context.createPanelChart(canvas,{data,options:{}});
  assert.equal(fallback.data,data);fallback.update();fallback.resize();
  assert.equal(warning.hidden,false);assert.equal(canvas.hidden,true);
}
console.log('Missing charts preserve numeric telemetry with visible feedback');
