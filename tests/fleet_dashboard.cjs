// Bounded live history must keep missing readings and hidden-tab gaps honest.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'servers.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('  function sample('), source.indexOf('  function renderEvents(')), context);
const chart = {data:{datasets:[{data:[]},{data:[]}]}, options:{scales:{x:{}}}, update(){}};
context.sample(chart,[12,40],100000);
context.sample(chart,[null,undefined],110000);
assert.equal(chart.data.datasets[0].data.at(-1).y,null);
assert.equal(chart.data.datasets[1].data.at(-1).y,null);
context.sample(chart,[0,50],160000);
assert.equal(chart.data.datasets[0].data.at(-2).y,null);
assert.equal(chart.data.datasets[0].data.at(-1).y,0);
for(let i=0;i<400;i++)context.sample(chart,[10,20],170000+i*10000);
assert.equal(chart.data.datasets[0].data.length,181);
assert.equal(chart.options.scales.x.max-chart.options.scales.x.min,1800000);
context.sample(null,[1],1); // Missing chart assets do not break current readings.
console.log('Fleet charts preserve gaps, zero readings and a bounded 30-minute window');

// Overview links always follow the selected server and its current permissions.
const links = ['view','admin_config','mods'].map(permission => ({
  dataset:{fleetPermission:permission,fleetPanel:permission==='view'?'dashboard':permission==='mods'?'mods':'startup'},
  removeAttribute(name){delete this[name];}
}));
const navigation = vm.createContext({
  navigationServers:[{id:'alpha',permissions:['view','mods']},{id:'beta',permissions:['view','admin_config']}],
  switcher:{value:'alpha'}, document:{querySelectorAll:()=>links},
  workspace:server=>'/?server='+encodeURIComponent(server.id)
});
vm.runInContext(source.slice(source.indexOf('  function updateNavigation()'), source.indexOf('  switcher.onchange')),navigation);
navigation.updateNavigation();
assert.equal(links[2].href,'/?server=alpha#mods');assert.equal(links[1].hidden,true);
navigation.switcher.value='beta';navigation.updateNavigation();
assert.equal(links[1].href,'/?server=beta#startup');assert.equal(links[2].hidden,true);assert.equal(links[2].href,undefined);
navigation.switcher.value='removed';navigation.updateNavigation();
assert.equal(links.every(link=>link.hidden&&link.href===undefined),true);
console.log('Overview navigation follows server selection and revokes unavailable links');
