// Exercise real shared requests and controls without browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

(async () => {
  const nodes = new Map(), calls = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent:'Training', className:'', disabled:false, classList:{toggle() {}}});
    return nodes.get(id);
  };
  const reply = (status, data) => ({status, ok:status < 400, json:async () => data});
  let respond = async () => reply(200, {ok:true});
  const context = vm.createContext({Headers, Request, URL, URLSearchParams,
    location:{href:'https://panel.test/?server=training', origin:'https://panel.test', search:'?server=training'},
    document:{getElementById:node, querySelector:() => null, dispatchEvent() {}},
    CustomEvent:class {}, confirm:() => true, updateModLibrary() {},
    fetch:async (input, options = {}) => { calls.push({input, options}); return respond(input, options); },
  });
  context.window = context;
  for (const name of ['api.js', 'status.js', 'server_controls.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', name), 'utf8'), context);
  }
  const consoleSource = fs.readFileSync(path.join(__dirname, '..', 'static', 'console.js'), 'utf8');
  vm.runInContext(consoleSource.slice(consoleSource.indexOf('function syncConsoleControls('),
    consoleSource.indexOf('function insertConsoleCommand(')), context);
  vm.runInContext('CSRF="token";', context);

  await context.fetch(new URL('https://panel.test/api/status'));
  assert.equal(calls.at(-1).options.headers.get('X-Server-ID'), 'training');
  await context.fetch(new Request('https://panel.test/api/status', {headers:{'X-Server-ID':'second'}}));
  assert.equal(calls.at(-1).options.headers.get('X-Server-ID'), 'second');
  await context.fetch('/api/status', {headers:{'X-Server-ID':''}});
  assert.equal(calls.at(-1).options.headers.get('X-Server-ID'), '');
  for (const url of ['/account', 'https://other.test/api/status']) {
    await context.fetch(url);
    assert.equal(calls.at(-1).options.headers, undefined);
  }

  respond = async (url, options) => options.method === 'POST'
    ? reply(403, {ok:false, error:'Your server access was revoked'})
    : reply(200, {csrf:'refreshed'});
  calls.length = 0;
  await assert.rejects(context.controlServer('stop', 'second'), /access was revoked/);
  const mutations = calls.filter(call => call.options.method === 'POST');
  assert.equal(mutations.length, 1, 'A failed mutation must not be retried automatically');
  assert.equal(mutations[0].options.headers.get('X-Server-ID'), 'second');
  assert.equal(mutations[0].options.headers.get('X-CSRF-Token'), 'token');
  assert.equal(JSON.parse(mutations[0].options.body)._csrf, 'token');
  await assert.rejects(context.controlServer('delete'), /Unsupported/);

  context.consoleServerRunning = false;
  let finish;
  respond = () => new Promise(resolve => { finish = resolve; });
  calls.length = 0;
  const pending = context.serverAction('start');
  await context.serverAction('start');
  assert.equal(calls.length, 1, 'Repeated clicks must not start concurrent actions');
  finish(reply(503, {ok:false, error:'Steam update is running'}));
  await pending;
  assert.match(node('log-msg').textContent, /Steam update is running/);
  assert.equal(node('btn-start').disabled, false);
  assert.equal(node('btn-stop').disabled, true);

  respond = async () => reply(200, {ok:true, running:true});
  await context.serverAction('start');
  assert.equal(node('btn-start').disabled, true);
  assert.equal(node('btn-stop').disabled, false);
  context.confirm = () => false;
  calls.length = 0;
  await context.serverAction('restart');
  assert.equal(calls.length, 0);

  respond = async () => reply(403, {error:'No access to this server'});
  await context.fetchStatus();
  assert.equal(node('status-text').textContent, 'UNAVAILABLE');
  assert.equal(node('console-live-label').textContent, 'STATUS UNAVAILABLE');
  for (const id of ['btn-start', 'btn-stop', 'btn-reset']) assert.equal(node(id).disabled, true);
  assert.match(node('log-msg').textContent, /No access to this server/);

  await assert.rejects(context.readJson({status:502, ok:false, json:async () => { throw new Error('HTML'); }}), /HTTP 502/);
  await assert.rejects(context.readJson(reply(200, {ok:false, error:'Operation failed'})), /Operation failed/);
  respond = async () => reply(401, {error:'Please sign in'});
  await assert.rejects(context.controlServer('start'), /Please sign in/);
  assert.equal(context.location.href, '/login');
  console.log('Server targets, CSRF, operation recovery and unavailable status checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
