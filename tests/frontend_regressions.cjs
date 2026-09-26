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
console.log('Frontend background-refresh regressions passed');
