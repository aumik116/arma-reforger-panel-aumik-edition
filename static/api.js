// Shared authenticated request helpers.
let CSRF = '';

// Selection is explicit per page. Reloading on switch clears all drafts/cursors.
const selectedServerId = new URLSearchParams(location.search).get('server') || '';
const originalFetch = window.fetch.bind(window);
window.fetch = (input, options = {}) => {
  const url = new URL(input instanceof Request ? input.url : input, location.href);
  if (selectedServerId && url.origin === location.origin && url.pathname.startsWith('/api/')) {
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    if (!headers.has('X-Server-ID')) headers.set('X-Server-ID', selectedServerId);
    options = {...options, headers};
  }
  return originalFetch(input, options);
};

async function readJson(response) {
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Please sign in');
  }
  let data;
  try { data = await response.json(); }
  catch (_) { throw new Error(`Unreadable server response (HTTP ${response.status}).`); }
  if (!response.ok || data?.ok === false) {
    throw new Error(data?.error || `Request failed (HTTP ${response.status}).`);
  }
  return data;
}

async function postJson(url, body, options = {}) {
  if (!CSRF) {
    try { const r = await fetch('/api/csrf'); if (r.ok) CSRF = (await r.json()).csrf || ''; }
    catch(e) {}
  }
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  headers.set('X-CSRF-Token', CSRF);
  const r = await fetch(url, {
    ...options,
    method: 'POST',
    headers,
    body: JSON.stringify({ ...(body || {}), _csrf: CSRF }),
  });
  if (r.status === 401) { window.location.href = '/login'; throw new Error('Please sign in'); }
  if (r.status === 403) {
    // CSRF expired — refresh token and surface error
    try { const cr = await fetch('/api/csrf'); if (cr.ok) CSRF = (await cr.json()).csrf || ''; } catch(e) {}
  }
  document.dispatchEvent(new CustomEvent('panel-change', {detail: url}));
  return r;
}

async function controlServer(action, serverId = selectedServerId) {
  if (!['start', 'stop', 'restart'].includes(action)) throw new Error('Unsupported server action');
  return readJson(await postJson('/api/' + action, {}, {headers: {'X-Server-ID': serverId}}));
}

async function postForm(url, formData, options = {}) {
  if (!CSRF) {
    try { const r = await fetch('/api/csrf'); if (r.ok) CSRF = (await r.json()).csrf || ''; }
    catch(e) {}
  }
  formData.append('_csrf', CSRF);
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'X-CSRF-Token': CSRF },
    body: formData,
    signal: options.signal,
  });
  if (r.status === 401) { window.location.href = '/login'; throw new Error('Please sign in'); }
  document.dispatchEvent(new CustomEvent('panel-change', {detail: url}));
  return r;
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
