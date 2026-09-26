// Shared authenticated request helpers.
let CSRF = '';

async function postJson(url, body) {
  if (!CSRF) {
    try { const r = await fetch('/api/csrf'); if (r.ok) CSRF = (await r.json()).csrf || ''; }
    catch(e) {}
  }
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
    body: JSON.stringify({ ...(body || {}), _csrf: CSRF }),
  });
  if (r.status === 401) { window.location.href = '/login'; throw new Error('unauthorized'); }
  if (r.status === 403) {
    // CSRF expired — refresh token and surface error
    try { const cr = await fetch('/api/csrf'); if (cr.ok) CSRF = (await cr.json()).csrf || ''; } catch(e) {}
  }
  document.dispatchEvent(new CustomEvent('panel-change', {detail: url}));
  return r;
}

async function postForm(url, formData) {
  if (!CSRF) {
    try { const r = await fetch('/api/csrf'); if (r.ok) CSRF = (await r.json()).csrf || ''; }
    catch(e) {}
  }
  formData.append('_csrf', CSRF);
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'X-CSRF-Token': CSRF },
    body: formData,
  });
  if (r.status === 401) { window.location.href = '/login'; throw new Error('unauthorized'); }
  document.dispatchEvent(new CustomEvent('panel-change', {detail: url}));
  return r;
}

// ─── Charts setup ────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
