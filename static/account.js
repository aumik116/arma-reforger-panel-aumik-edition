document.addEventListener('DOMContentLoaded', async () => {
  const field = id => document.getElementById(id);
  field('account-logout').onclick = async () => {
    try { const response = await postJson('/logout', {}); if (!response.ok) throw new Error('Could not sign out.'); location.href = '/login'; }
    catch (error) { field('account-feedback').textContent = error.message; }
  };
  try {
    const response = await fetch('/api/me');
    if (response.status === 401) { location.href = '/login'; return; }
    if (!response.ok) throw new Error('Could not load your account.');
    const account = await response.json();
    field('account-name').textContent = account.username;
    field('account-avatar').textContent = account.username.slice(0, 1).toUpperCase();
    field('account-access').textContent = account.is_owner ? 'Owner · Full panel and server access' : (account.panel_permissions || []).includes('users') ? 'Panel administrator · Manages users and server access' : 'Staff · Server access and actions depend on your assigned server roles';
    field('account-password-save').disabled = false;
  } catch (error) { field('account-feedback').textContent = error.message; }
  field('account-password-form').onsubmit = async event => {
    event.preventDefault();
    const feedback = field('account-password-feedback'), button = field('account-password-save');
    if (field('new-password').value !== field('confirm-password').value) { feedback.textContent = 'New passwords do not match.'; return; }
    button.disabled = true; feedback.textContent = 'Saving…';
    try {
      const response = await postJson('/api/account/password', {current_password:field('current-password').value, password:field('new-password').value});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Could not change your password.');
      field('account-password-form').reset(); feedback.textContent = 'Password changed. Other sessions have been signed out.';
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  };
});
