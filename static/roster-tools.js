// Qualifications, promotion review and previewed bulk edits share the roster revision.
(() => {
  const el = id => document.getElementById(id), esc = escHtml;
  const dialog = el('roster-tools-dialog'), form = el('roster-tools-form');
  let context, metadata, save, baseline = '', saving = false, generation = 0;
  const read = async url => readJson(await fetch(url));
  const write = async (url, data) => readJson(await postJson(url, data));
  const base = () => `/api/units/${context.unitId}`;
  const feedback = message => { el('units-feedback').textContent = message; };
  const current = () => context.detail.roster.filter(m => !m.archived);
  const awards = member => (metadata?.awards || []).filter(a => a.member_id === member.id);
  const held = member => member.certificates.split(';').filter(Boolean);
  const sign = () => JSON.stringify([...new FormData(form)]);
  UnitUX.registerDraft({dirty:()=>dialog.open&&sign()!==baseline,busy:()=>dialog.open&&saving,discard:()=>dialog.close()});
  function close() {
    if (!UnitUX.canLeave()) return;
    dialog.close();
  }
  el('roster-tools-close').onclick = close;
  dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
  function open(title, html, handler, button = 'Save changes') {
    if (dialog.open) dialog.close();
    el('roster-tools-title').textContent = title;
    el('roster-tools-body').innerHTML = html;
    el('roster-tools-error').textContent = '';
    el('roster-tools-save').textContent = button;
    el('roster-tools-save').hidden = !handler;
    save = handler; dialog.showModal(); baseline = sign();
    UnitUX.open(dialog);
  }
  form.onsubmit = async e => {
    e.preventDefault(); if (saving || !save) return;
    saving = true; el('roster-tools-save').disabled = true;
    try {
      const result = await save();
      if (result !== false) {
        dialog.close(); document.dispatchEvent(new Event('unit-access-changed'));
      } else baseline = sign();
    } catch (error) { el('roster-tools-error').textContent = error.message; }
    finally { saving = false; el('roster-tools-save').disabled = false; }
  };
  function path(id) {
    const nodes = new Map(context.detail.structure.map(n => [n.id, n]));
    const result = []; let node = nodes.get(id);
    while (node) { result.push(node.name); node = nodes.get(node.parent_id); }
    return result.reverse().join(' / ');
  }
  function sectionMembers(id, members) {
    if (id === 'all') return members;
    if (id === 'unassigned') return members.filter(m => !m.billet_id);
    const descendants = new Set([Number(id)]);
    for (let i = 0; i < 7; i++) context.detail.structure.forEach(n => { if (descendants.has(n.parent_id)) descendants.add(n.id); });
    return members.filter(m => descendants.has(m.billet_id));
  }
  function memberButton(member) {
    return `<button type="button" class="member-record-link" data-tool-record="${member.id}">${esc(member.game_name)}</button><small>${esc([member.rank_track, member.rank].filter(Boolean).join(' · '))}</small>`;
  }
  function bindMembers(root) {
    root.querySelectorAll('[data-tool-record]').forEach(b => b.onclick = () => {
      document.dispatchEvent(new CustomEvent('unit-open-member', { detail: Number(b.dataset.toolRecord) }));
    });
  }
  function renderMatrix() {
    if (!context || !metadata) return;
    const certificates = context.detail.unit.catalog.certificates || [];
    const status = el('matrix-status').value, search = el('matrix-search').value.trim().toLowerCase();
    let members = context.detail.roster.filter(m => (status === 'archived' ? m.archived : !m.archived && (!status || m.status === status)) &&
      [m.game_name, m.rank, m.rank_track, m.discord, m.billet_path].join(' ').toLowerCase().includes(search));
    members = sectionMembers(el('matrix-section').value, members);
    const scope = members;
    const selected = el('matrix-certificate').value, mode = el('matrix-held').value;
    if (mode !== 'all' && !selected) {
      el('qualification-matrix').innerHTML = '<p class="unit-empty">Choose a qualification to filter who holds or is missing it.</p>';
      el('matrix-coverage').replaceChildren(); return;
    }
    if (mode !== 'all') members = members.filter(m => held(m).includes(selected) === (mode === 'held'));
    const rankOrder = new Map(); let index = 0;
    (context.detail.unit.catalog.rank_structures || []).forEach(s => s.ranks.forEach(r => rankOrder.set(JSON.stringify([s.name, r.name]), index++)));
    const key = el('matrix-sort').value;
    members = [...members].sort((a, b) => (key === 'rank' ? (rankOrder.get(JSON.stringify([a.rank_track, a.rank])) ?? 9999) - (rankOrder.get(JSON.stringify([b.rank_track, b.rank])) ?? 9999) :
      key === 'section' ? (a.billet_path || 'ZZZ').localeCompare(b.billet_path || 'ZZZ') : 0) || a.game_name.localeCompare(b.game_name));
    const columns = selected ? [selected] : certificates;
    const unitMembers = current();
    el('matrix-coverage').innerHTML = columns.map(c => {
      const count = scope.filter(m => held(m).includes(c)).length;
      return `<div class="unit-block"><strong>${esc(c)}</strong><span>Filtered coverage: ${count}/${scope.length}${scope.length ? ` · ${Math.round(count / scope.length * 100)}%` : ''}</span><small>Whole current unit: ${unitMembers.filter(m => held(m).includes(c)).length}/${unitMembers.length}</small></div>`;
    }).join('');
    el('qualification-matrix').innerHTML = certificates.length ? `<table><thead><tr><th>Member</th><th>Primary billet</th>${columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${members.map(m => `<tr><td>${memberButton(m)}<small>${m.archived ? 'Former' : esc(m.status)}</small></td><td>${esc(m.billet_path || 'Unassigned')}</td>${columns.map(c => {
      const has = held(m).includes(c), award = awards(m).find(a => a.certificate === c);
      const title = has ? `Awarded: ${award?.awarded_on || 'Unknown'} · Issuer: ${award?.issuer || 'Unknown'}${award?.notes ? ' · ' + award.notes : ''}` : 'Not held';
      return `<td><button type="button" class="qualification-cell ${has ? 'qualification-held' : 'qualification-missing'}" data-qual-member="${m.id}" data-qual-name="${esc(c)}" title="${esc(title)}" aria-label="${esc(m.game_name + ' · ' + c + ' · ' + (has ? 'Held' : 'Missing'))}">${has ? '✓' : '—'}</button>${has && !el('matrix-checks').checked ? `<small>${esc(award?.awarded_on || 'Date unknown')}</small>` : ''}</td>`;
    }).join('')}</tr>`).join('') || `<tr><td colspan="${columns.length + 2}" class="unit-empty">No members match these filters.</td></tr>`}</tbody></table>` : '<p class="unit-empty">Create qualifications in Ranks & qualifications to build the matrix.</p>';
    bindMembers(el('qualification-matrix'));
    el('qualification-matrix').querySelectorAll('[data-qual-member]').forEach(b => b.onclick = () => qualificationEditor(Number(b.dataset.qualMember), b.dataset.qualName));
  }
  function qualificationEditor(memberId, certificate = '') {
    if (saving) return;
    if (!metadata) { feedback('Award records are not loaded yet. Refresh the unit and try again.'); return; }
    const member = context.detail.roster.find(m => m.id === memberId);
    if (!member) return;
    const catalog = context.detail.unit.catalog.certificates || [];
    certificate ||= catalog[0];
    if (!certificate) { feedback('Create qualifications in Ranks & qualifications first.'); return; }
    const canEdit = context.detail.can_edit, revision = context.detail.unit.revision;
    open(`${member.game_name} — qualification`, `<label class="unit-field">Qualification<select name="certificate">${catalog.map(c => `<option ${c === certificate ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label><div id="qualification-award-fields"></div>`, canEdit ? async () => {
      const values = Object.fromEntries(new FormData(form));
      await write(`${base()}/roster/${member.id}/qualifications`, { ...values, revision });
    } : null);
    function fields() {
      const chosen = form.elements.certificate.value, has = held(member).includes(chosen), award = awards(member).find(a => a.certificate === chosen);
      el('qualification-award-fields').innerHTML = `<p>${has ? 'Currently held' : 'Not held'} · Issuer: ${esc(award?.issuer || (has ? 'Unknown — existing record' : 'Defaults to your name in this unit; enter the original instructor if needed'))}</p>${canEdit ? `<label class="unit-field">Action<select name="action">${has ? '<option value="update">Update award details</option><option value="revoke">Revoke qualification</option>' : '<option value="grant">Grant qualification</option>'}</select></label>` : ''}<label class="unit-field">Award date<input type="date" name="awarded_on" value="${esc(has ? award?.awarded_on || '' : metadata.today)}" max="${metadata.today}" ${canEdit ? '' : 'disabled'}></label><label class="unit-field">Issuing staff / instructor<input name="issuer" maxlength="120" value="${esc(has ? award?.issuer || '' : metadata.actor)}" ${canEdit ? '' : 'disabled'} placeholder="Unknown if left blank"></label><label class="unit-field">Award notes<textarea name="notes" maxlength="1000" ${canEdit ? '' : 'disabled'}>${esc(award?.notes || '')}</textarea></label>${canEdit ? '<label class="unit-field">Change / revocation reason<textarea name="reason" maxlength="1000"></textarea></label>' : ''}<p class="feature-note">Grant/revoke changes affect promotion readiness. Earlier grant and revocation entries remain in the member timeline. The issuing name changes only when you edit it; the timeline separately records who saved the change.</p>`;
      if (canEdit) {
        const setRequired = () => { form.elements.awarded_on.required = form.elements.action.value === 'grant'; form.elements.reason.required = form.elements.action.value === 'revoke'; };
        form.elements.action.onchange = setRequired; setRequired();
      }
      baseline = sign();
    }
    fields();
    form.elements.certificate.onchange = () => {
      const selected = form.elements.certificate.value;
      form.elements.certificate.value = certificate;
      if (sign() !== baseline && !confirm('Discard unsaved award details?')) { form.elements.certificate.value = certificate; return; }
      certificate = selected; form.elements.certificate.value = selected; fields();
    };
    baseline = sign();
  }
  function renderPromotions() {
    if (!context) return;
    const filter = el('promotion-filter').value, query = el('promotion-search').value.trim().toLowerCase();
    const members = current().filter(m => [m.game_name, m.rank_track, m.rank, m.promotion.next_rank].join(' ').toLowerCase().includes(query) &&
      (filter === 'all' || (filter === 'eligible' ? m.promotion.eligible : !m.promotion.eligible))).sort((a, b) => Number(b.promotion.eligible) - Number(a.promotion.eligible) || (a.promotion.next_date || '9999').localeCompare(b.promotion.next_date || '9999') || a.game_name.localeCompare(b.game_name));
    el('promotion-queue').innerHTML = `<table><thead><tr><th>Member</th><th>Current rank</th><th>Next rank</th><th>Eligibility</th><th>Unmet requirements</th><th>Review</th></tr></thead><tbody>${members.map(m => {
      const p = m.promotion;
      return `<tr><td>${memberButton(m)}</td><td>${esc(m.rank || 'Not assigned')}</td><td>${esc(p.next_rank || 'No next rank')}</td><td>${p.eligible ? '<strong class="unit-good">Eligible for review</strong>' : 'Not eligible'}<small>${esc(p.next_date || (p.next_rank ? 'Set last promotion date' : 'Configure a rank path'))}</small></td><td>${esc(p.missing.join(', ') || (p.next_rank ? 'Qualifications met' : 'No advancement path'))}${p.next_date && p.next_date > metadata?.today ? '<small>Time requirement not met</small>' : ''}</td><td>${context.detail.can_edit ? `<button type="button" data-promote="${m.id}" ${p.eligible && metadata ? '' : 'disabled'}>Review promotion</button>` : 'View only'}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="unit-empty">No members match this review queue.</td></tr>'}</tbody></table>`;
    bindMembers(el('promotion-queue'));
    el('promotion-queue').querySelectorAll('[data-promote]').forEach(b => b.onclick = () => promotionEditor(Number(b.dataset.promote)));
  }
  function promotionEditor(memberId) {
    if (saving || !metadata) return;
    const member = context.detail.roster.find(m => m.id === memberId), revision = context.detail.unit.revision;
    if (!member?.promotion.eligible || !context.detail.can_edit) return;
    const target = member.promotion.next_rank;
    open(`Review promotion — ${member.game_name}`, `<div class="unit-block"><p><strong>${esc(member.rank_track)}</strong></p><p>${esc(member.rank)} → <strong>${esc(target)}</strong></p><p>Last promotion date will become <strong>${metadata.today}</strong> (panel date).</p><p>Time and qualification requirements are met. The server rechecks eligibility when you confirm.</p></div><label class="unit-field">Staff review note<textarea name="reason" required maxlength="1000"></textarea></label><label><input type="checkbox" name="confirmed" required> I approve this promotion and the new promotion date.</label>`, async () => {
      await write(`${base()}/roster/${member.id}/promote`, { revision, confirm_rank: target, confirm_date: metadata.today, reason: new FormData(form).get('reason') });
    }, 'Confirm promotion');
  }
  function bulkEditor(initial = {}) {
    if (saving && !initial.fromPreview) return;
    if (!context?.detail.can_edit || !metadata) return;
    const members = current(), chosen = new Set(initial.members || []), catalog = context.detail.unit.catalog.certificates || [];
    const sections = context.detail.structure.filter(n => n.kind === 'section');
    open('Bulk roster edit', `<p class="feature-note">Select up to 500 current members. Review every proposed change before applying. Section moves fill open primary billets; ranks and qualifications do not restrict placement.</p><div class="bulk-layout"><section><div class="unit-toolbar"><input type="search" id="bulk-search" aria-label="Find members for bulk editing" placeholder="Search members"><button type="button" id="bulk-select-visible">Select shown</button><button type="button" id="bulk-clear">Clear selection</button></div><p id="bulk-count" role="status"></p><div class="bulk-member-list">${members.map(m => `<label data-bulk-row="${m.id}"><input type="checkbox" name="bulk_members" value="${m.id}" ${chosen.has(m.id) ? 'checked' : ''}><span>${esc(m.game_name)}<small>${esc([m.rank, m.status, m.billet_path || 'Unassigned'].join(' · '))}</small></span></label>`).join('') || '<p>No current members.</p>'}</div></section><section><label class="unit-field">Change<select name="action"><option value="grant">Grant qualification</option><option value="revoke">Revoke qualification</option><option value="status">Change status</option><option value="section">Move to section’s open billets</option><option value="unassign">Remove primary billet</option></select></label><div id="bulk-fields"></div><label class="unit-field">Reason / award note<textarea name="reason" required maxlength="1000">${esc(initial.reason || '')}</textarea></label></section></div>`, async () => {
      const data = Object.fromEntries(new FormData(form)); delete data.bulk_members;
      const payload = { ...data, members: [...form.querySelectorAll('[name="bulk_members"]:checked')].map(c => Number(c.value)), revision: context.detail.unit.revision };
      if (data.section_id !== undefined) payload.section_id = Number(data.section_id);
      const preview = await write(`${base()}/roster/bulk/preview`, payload);
      showBulkPreview(payload, preview); return false;
    }, 'Preview changes');
    form.elements.action.value = initial.action || 'grant';
    function fields() {
      const action = form.elements.action.value;
      el('bulk-fields').innerHTML = action === 'grant' || action === 'revoke' ? `<label class="unit-field">Qualification<select name="certificate" required>${catalog.map(c => `<option ${c === initial.certificate ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>${!catalog.length?'<p class="unit-warn">Create qualifications in Ranks & qualifications first.</p>':''}${action === 'grant' ? `<label class="unit-field">Award date<input type="date" name="awarded_on" required value="${esc(initial.awarded_on || metadata.today)}" max="${metadata.today}"></label><p class="feature-note">Members who already hold it keep their current award date and issuer.</p>` : ''}` : action === 'status' ? `<label class="unit-field">New status<select name="status">${['active', 'reserve', 'loa'].map(s => `<option value="${s}" ${s === initial.status ? 'selected' : ''}>${s === 'loa' ? 'LOA' : s[0].toUpperCase() + s.slice(1)}</option>`).join('')}</select></label><p class="feature-note">Future event rosters update. Past and active event expectations stay unchanged.</p>` : action === 'section' ? `<label class="unit-field">Target section<select name="section_id" required>${sections.map(s => `<option value="${s.id}" ${s.id === initial.section_id ? 'selected' : ''}>${esc(path(s.id))}</option>`).join('')}</select></label><p class="feature-note">Members already in this section stay in their billets. Others receive vacant billets in structure order. The preview lists each assignment. No change is applied if there are too few vacancies.</p>${!sections.length?'<p class="unit-warn">Create sections and billets in Structure first.</p>':''}` : '<p>Selected members will become unassigned. Their roster records remain.</p>';
    }
    fields(); form.elements.action.onchange = fields;
    const updateCount = () => { el('bulk-count').textContent = `${form.querySelectorAll('[name="bulk_members"]:checked').length} selected`; };
    form.querySelectorAll('[name="bulk_members"]').forEach(c => c.onchange = updateCount);
    el('bulk-search').oninput = () => {
      const query = el('bulk-search').value.trim().toLowerCase();
      form.querySelectorAll('[data-bulk-row]').forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
    };
    el('bulk-select-visible').onclick = () => { form.querySelectorAll('[data-bulk-row]:not([hidden]) input').forEach(c => { c.checked = true; }); updateCount(); };
    el('bulk-clear').onclick = () => { form.querySelectorAll('[name="bulk_members"]').forEach(c => { c.checked = false; }); updateCount(); };
    updateCount(); baseline = sign();
  }
  function showBulkPreview(payload, preview) {
    const changed = preview.changes.filter(c => JSON.stringify(c.before) !== JSON.stringify(c.after)).length;
    const describe = s => payload.action === 'status' ? s.status : payload.action === 'section' || payload.action === 'unassign' ? s.billet_path || 'Unassigned' : s.certificates.split(';').filter(Boolean).join(', ') || 'None';
    open('Review bulk changes', `<p><strong>${changed}</strong> of ${preview.changes.length} selected members will change.</p><p class="member-record-note">Reason: ${esc(payload.reason)}</p>${payload.action === 'grant' ? `<p>Award date: ${esc(payload.awarded_on)}</p>` : ''}<div class="unit-table bulk-preview-table"><table><thead><tr><th>Member</th><th>Before</th><th>After</th></tr></thead><tbody>${preview.changes.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(describe(c.before))}</td><td>${esc(describe(c.after))}${JSON.stringify(c.before) === JSON.stringify(c.after) ? '<small>No change</small>' : ''}</td></tr>`).join('')}</tbody></table></div><button type="button" id="bulk-back">Back to selection</button><label class="bulk-confirm"><input type="checkbox" name="confirm" required> Apply exactly these changes to the listed members.</label>`, async () => {
      if(!changed)throw new Error('No changes to apply. Go back and choose a different change.');
      await write(`${base()}/roster/bulk/apply`, { ...payload, preview_token: preview.preview_token });
    }, 'Apply reviewed changes');
    el('bulk-back').onclick = () => bulkEditor({ ...payload, fromPreview: true });
    baseline = sign();
  }
  async function loaded(event) {
    const token = ++generation;
    if (dialog.open && !saving) dialog.close();
    context = event.detail; metadata = null;
    el('roster-bulk').hidden = !context.detail.can_edit; el('roster-bulk').disabled = true;
    for (const [id, options] of [['matrix-section', ['all', 'All groups / sections']], ['matrix-certificate', ['', 'All qualifications']]]) {
      const previous = el(id).value;
      el(id).replaceChildren(new Option(options[1], options[0]));
      if (id === 'matrix-section') {
        el(id).add(new Option('Unassigned', 'unassigned'));
        context.detail.structure.filter(n => n.kind !== 'billet').forEach(n => el(id).add(new Option(path(n.id), n.id)));
      } else (context.detail.unit.catalog.certificates || []).forEach(c => el(id).add(new Option(c, c)));
      if ([...el(id).options].some(o => o.value === previous)) el(id).value = previous;
    }
    el('qualification-matrix').textContent = 'Loading award records…';
    if(!el('unit-promotions').hidden)renderPromotions();
    try {
      const result = await read(`${base()}/roster-tools`);
      if (token !== generation) return;
      if (result.revision !== context.detail.unit.revision) { feedback('This unit changed while loading. Refresh to see the current roster.'); return; }
      metadata = result; el('roster-bulk').disabled = false; if(!el('unit-qualifications').hidden)renderMatrix(); if(!el('unit-promotions').hidden)renderPromotions();
    } catch (error) { if (token === generation) {feedback(error.message);const retry=()=>document.dispatchEvent(new Event('unit-access-changed'));UnitUX.error(el('qualification-matrix'),error,retry);UnitUX.error(el('promotion-queue'),error,retry);} }
  }
  document.addEventListener('unit-loaded', loaded);
  document.addEventListener('unit-section-changed',event=>{if(event.detail.tab==='qualifications')renderMatrix();if(event.detail.tab==='promotions')renderPromotions();});
  document.addEventListener('unit-manage-qualification', e => qualificationEditor(e.detail));
  el('roster-bulk').onclick = () => bulkEditor();
  for (const id of ['matrix-search', 'matrix-status', 'matrix-section', 'matrix-certificate', 'matrix-held', 'matrix-sort', 'matrix-checks']) el(id).addEventListener(id === 'matrix-search' ? 'input' : 'change', renderMatrix);
  el('promotion-search').oninput = renderPromotions; el('promotion-filter').onchange = renderPromotions;
})();
