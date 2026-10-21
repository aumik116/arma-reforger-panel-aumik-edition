const loginForm = document.getElementById('login-form');
const loginButton = loginForm.querySelector('button');
const loginError = document.getElementById('login-error');
const loginUsername = document.getElementById('username');
const loginPassword = document.getElementById('pwd');
let loginPending = false;

function clearLoginError() {
  loginError.hidden = true;
  loginError.textContent = '';
  for (const input of [loginUsername, loginPassword]) input.removeAttribute('aria-invalid');
}

loginForm.addEventListener('input', clearLoginError);
loginForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (loginPending || !loginForm.reportValidity()) return;
  loginPending = true;
  loginButton.disabled = true;
  loginButton.textContent = 'Signing in…';
  loginForm.setAttribute('aria-busy', 'true');
  clearLoginError();
  try {
    const response = await fetch('/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: loginUsername.value.trim(), password: loginPassword.value}),
      signal: AbortSignal.timeout(15000),
    });
    let data;
    try { data = await response.json(); } catch (_) {}
    if (response.ok && data?.ok === true) { window.location.href = '/'; return; }
    if (response.status === 401) {
      for (const input of [loginUsername, loginPassword]) input.setAttribute('aria-invalid', 'true');
      loginPassword.focus();
    }
    loginError.textContent = data?.error || (response.status === 429
      ? 'Too many attempts. Wait a minute before trying again.'
      : 'Sign-in service is unavailable. Please try again.');
    loginError.hidden = false;
  } catch (error) {
    loginError.textContent = ['TimeoutError', 'AbortError'].includes(error.name)
      ? 'Sign-in timed out. Please try again.' : 'Could not connect. Please try again.';
    loginError.hidden = false;
  } finally {
    loginPending = false;
    loginButton.disabled = false;
    loginButton.textContent = 'Sign in';
    loginForm.removeAttribute('aria-busy');
  }
});
