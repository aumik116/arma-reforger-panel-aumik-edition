// The account is authoritative; this cache avoids a flash during page reloads.
(() => {
  const themes = ['original', 'ocean', 'forest', 'light'];
  let current = 'original';
  function apply(theme) {
    current = themes.includes(theme) ? theme : 'original';
    document.documentElement.dataset.theme = current;
    try { localStorage.setItem('panel-theme', current); } catch (_) {}
    document.dispatchEvent(new Event('panel-theme-change'));
  }
  try { apply(localStorage.getItem('panel-theme')); } catch (_) { apply('original'); }
  document.addEventListener('DOMContentLoaded', async () => {
    if (document.body.hasAttribute('data-login-page')) return;
    const picker = document.getElementById('theme-choice');
    const feedback = document.getElementById('theme-feedback');
    if (!picker) {
      try { const response = await fetch('/api/preferences'); if (response.ok) apply((await response.json()).theme); } catch (_) {}
      return;
    }
    picker.value = current;
    try {
      const response = await fetch('/api/preferences');
      if (!response.ok) throw new Error('Could not load your saved appearance.');
      apply((await response.json()).theme); picker.value = current;
    } catch (error) { feedback.textContent = error.message; }
    picker.onchange = async () => {
      const previous = current;
      apply(picker.value); picker.disabled = true;
      try {
        const response = await postJson('/api/preferences', {theme:current});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Could not save appearance.');
        feedback.textContent = 'Theme saved to your account.';
      } catch (error) {
        apply(previous); picker.value = current; feedback.textContent = error.message;
      } finally { picker.disabled = false; }
    };
  });
})();
