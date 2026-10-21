// Login failures, remembered themes and worker upgrades without browser packages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = name => fs.readFileSync(path.join(__dirname, '..', 'static', name), 'utf8');

(async () => {
  const handlers = {}, calls = [], attributes = new Map();
  const input = () => ({value:'test', setAttribute(key,value) { this[key]=value; }, removeAttribute(key) { delete this[key]; }, focus() { this.focused=true; }});
  const username = input(), password = input(), error = {hidden:true, textContent:''}, button = {};
  const form = {querySelector:() => button, reportValidity:() => Boolean(username.value && password.value),
    addEventListener:(name,callback) => handlers[name]=callback,
    setAttribute:(key,value) => attributes.set(key,value), removeAttribute:key => attributes.delete(key)};
  const elements = {'login-form':form, username, pwd:password, 'login-error':error};
  const reply = (status,data) => ({status, ok:status < 400, json:async () => data});
  let respond = async () => reply(401,{error:'Invalid username or password'});
  const context = vm.createContext({AbortSignal, Event,
    document:{getElementById:id => elements[id], body:{hasAttribute:name => name==='data-login-page'},
      documentElement:{dataset:{}}, addEventListener:(name,callback) => handlers[name]=callback, dispatchEvent() {}},
    localStorage:{getItem:() => 'forest', setItem() {}}, location:{href:'/login'},
    fetch:async (url,options) => {calls.push({url,options});return respond();},
  });
  context.window=context;
  vm.runInContext(source('theme.js'),context);
  await handlers.DOMContentLoaded();
  assert.equal(context.document.documentElement.dataset.theme,'forest');
  assert.equal(calls.length,0,'The login page must not request private account preferences');
  vm.runInContext(source('login.js'),context);
  const submit = () => handlers.submit({preventDefault() {}});

  password.value=''; await submit(); assert.equal(calls.length,0);
  password.value='test-password'; username.value='  admin  ';
  let finish;
  respond = () => new Promise(resolve => {finish=resolve;});
  const pending = submit(); await submit();
  assert.equal(calls.length,1,'Repeated Enter presses must submit once');
  assert.equal(button.disabled,true); assert.equal(attributes.get('aria-busy'),'true');
  assert.deepEqual(JSON.parse(calls[0].options.body),{username:'admin',password:'test-password'});
  finish(reply(401,{error:'Invalid username or password'})); await pending;
  assert.equal(error.hidden,false); assert.match(error.textContent,/Invalid username/);
  assert.equal(password['aria-invalid'],'true'); assert.equal(password.focused,true);
  assert.equal(button.disabled,false); assert.equal(attributes.has('aria-busy'),false);
  handlers.input(); assert.equal(error.hidden,true); assert.equal(password['aria-invalid'],undefined);

  respond=async () => reply(429,null); await submit(); assert.match(error.textContent,/Too many attempts/);
  respond=async () => ({status:502,ok:false,json:async () => {throw new Error('HTML');}});
  await submit(); assert.match(error.textContent,/service is unavailable/);
  respond=async () => {throw new Error('Network failed');};
  await submit(); assert.match(error.textContent,/Could not connect/); assert.equal(button.disabled,false);
  respond=async () => {const e=new Error();e.name='TimeoutError';throw e;};
  await submit(); assert.match(error.textContent,/timed out/);
  respond=async () => reply(200,{ok:false}); await submit(); assert.equal(context.location.href,'/login');
  respond=async () => reply(200,{ok:true}); await submit(); assert.equal(context.location.href,'/');

  const events={}, removed=[], waits=[]; let claimed=false, skipped=false;
  vm.runInNewContext(source('service-worker.js'),{
    self:{addEventListener:(name,callback) => events[name]=callback,
      skipWaiting:async () => {skipped=true;}, clients:{claim:async () => {claimed=true;}}},
    caches:{keys:async () => ['arma-panel-v1','unrelated-app','arma-panel-v2'], delete:async key => {removed.push(key);}},
  });
  events.install({waitUntil:promise => waits.push(promise)});
  events.activate({waitUntil:promise => waits.push(promise)});
  await Promise.all(waits);
  assert.equal(skipped,true); assert.equal(claimed,true);
  assert.deepEqual(removed,['arma-panel-v1','arma-panel-v2']);
  assert.equal(events.fetch,undefined,'Worker upgrades must leave network requests uncached');
  vm.runInNewContext(source('pwa.js'),{navigator:{}});
  const registrations=[];
  vm.runInNewContext(source('pwa.js'),{navigator:{serviceWorker:{register:(url,options) => {
    registrations.push({url,options});return Promise.reject(new Error('Unsupported context'));
  }}}});
  await Promise.resolve();
  assert.equal(registrations[0].url,'/service-worker.js');
  assert.equal(registrations[0].options.updateViaCache,'none');
  console.log('Login validation, failure recovery, themes and safe worker upgrade checks passed');
})().catch(error => {console.error(error);process.exitCode=1;});
