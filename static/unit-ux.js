// Shared behavior for the unit workspace's native dialogs and async panels.
const unitDrafts = [];
window.UnitUX = {
  registerDraft(draft) { unitDrafts.push(draft); },
  hasDraft() { return unitDrafts.some(draft => draft.dirty()); },
  canLeave() {
    if (unitDrafts.some(draft => draft.busy?.())) return false;
    const drafts = unitDrafts.filter(draft => draft.dirty());
    if (!drafts.length) return true;
    if (!confirm('Discard unsaved changes?')) return false;
    drafts.forEach(draft => draft.discard());
    return true;
  },
  open(dialog) {
    dialog.scrollTop = 0;
    const heading = dialog.querySelector('h2');
    if (heading) heading.tabIndex = -1;
    const input = [...dialog.querySelectorAll('input:not([disabled]):not([type="checkbox"]), select:not([disabled]), textarea:not([disabled])')].find(field=>field.getClientRects().length&&!field.closest('details:not([open])'));
    const nearTop = input && input.getBoundingClientRect().top - dialog.getBoundingClientRect().top < Math.min(260, dialog.clientHeight / 2);
    (nearTop ? input : heading)?.focus({preventScroll:true});
    dialog.scrollTop = 0;
  },
  error(region, error, retry) {
    region.querySelector('.unit-inline-error')?.remove();
    if (region.textContent.trim() === 'Loading…' || region.textContent.trim().startsWith('Loading award')) region.replaceChildren();
    const box = document.createElement('div'); box.className = 'unit-inline-error'; box.setAttribute('role','alert');
    const text = document.createElement('p'); text.textContent = error.message || String(error); box.append(text);
    if (retry) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Try again';
      button.onclick = async () => {button.disabled=true;try {await retry();box.remove();} catch(e) {text.textContent=e.message;} finally {button.disabled=false;}};
      box.append(button);
    }
    region.prepend(box);
  }
};
// Keep validation visible in long dialogs; moving focus also announces it to keyboards/readers.
for (const dialog of document.querySelectorAll('.unit-dialog')) {
  const error = dialog.querySelector('[role="alert"]');
  if (!error) continue;
  error.tabIndex = -1;
  new MutationObserver(() => {
    if (dialog.open && error.textContent.trim()) {error.focus({preventScroll:true});error.scrollIntoView({block:'nearest'});}
  }).observe(error,{childList:true,subtree:true,characterData:true});
}
let scrollHintFrame;
function updateUnitScrollHints() {
  cancelAnimationFrame(scrollHintFrame);
  scrollHintFrame = requestAnimationFrame(() => {
    for (const region of document.querySelectorAll('.unit-table,.billet-table,.rank-policy-table')) {
      const overflow = region.getClientRects().length > 0 && region.scrollWidth > region.clientWidth + 2;
      let hint = region.previousElementSibling?.classList.contains('unit-scroll-hint') ? region.previousElementSibling : null;
      if (overflow && !hint) {
        hint = document.createElement('p'); hint.className = 'unit-scroll-hint';
        hint.textContent = 'More columns → scroll sideways'; region.before(hint);
      }
      if (hint) hint.hidden = !overflow;
      if (overflow) {
        region.tabIndex = 0;
        if (!region.hasAttribute('aria-label')) region.setAttribute('aria-label','Scrollable table. Use left and right arrow keys for more columns.');
      }
    }
  });
}
new MutationObserver(updateUnitScrollHints).observe(document.body,{childList:true,subtree:true});
window.addEventListener('resize',updateUnitScrollHints);
document.addEventListener('toggle',updateUnitScrollHints,true);

window.addEventListener('beforeunload',event=>{if(UnitUX.hasDraft()){event.preventDefault();event.returnValue='';}});
