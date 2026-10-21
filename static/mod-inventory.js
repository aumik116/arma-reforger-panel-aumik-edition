// Inventory is read-only; absence from config does not prove a download is unused.
let downloadedInventory = null, downloadedLoading = false, downloadedTimer;
const downloadedEl = id => document.getElementById(id);
function renderDownloadedMods() {
  if (!downloadedInventory) return;
  const query = downloadedEl('downloaded-search').value.trim().toLowerCase();
  const filter = downloadedEl('downloaded-filter').value;
  const sort = downloadedEl('downloaded-sort').value;
  const all = downloadedInventory.mods;
  const rows = all.filter(row => `${row.name} ${row.modId || ''} ${row.path}`.toLowerCase().includes(query) &&
    (filter === 'all' || filter === 'not-configured' && !row.configured || filter === row.usage));
  const name = (a,b) => a.name.localeCompare(b.name, undefined, {numeric:true,sensitivity:'base'});
  rows.sort((a,b) => sort === 'largest' ? b.bytes-a.bytes || name(a,b) : sort === 'smallest' ? a.bytes-b.bytes || name(a,b) : (sort === 'name-desc' ? -1 : 1) * name(a,b));
  const container = downloadedEl('downloaded-rows'); container.replaceChildren();
  const labels = {configured:'Configured',dependency:'Known dependency',not_required:'Not required by known configuration',unverified:'Not configured · usage unverified'};
  for (const mod of rows) {
    const row = document.createElement('tr');
    const title = document.createElement('td');
    const strong = document.createElement('strong'); strong.textContent = mod.name;
    const id = document.createElement('small'); id.textContent = mod.modId || 'Mod ID unavailable';
    const folder = document.createElement('small'); folder.textContent = mod.path;
    title.append(strong, id, folder); row.append(title);
    for (const value of [mod.version || 'Unknown', (mod.size_partial ? 'At least ' : '') + formatModSize(mod.bytes), labels[mod.usage]]) {
      const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
    }
    container.append(row);
  }
  if (!rows.length) {
    const row = document.createElement('tr'), cell = document.createElement('td');
    cell.colSpan=4;cell.textContent=all.length ? 'No downloads match these filters.' : 'No downloaded mod folders found in the configured Workshop directory.';row.append(cell);container.append(row);
  }
  const configured = all.filter(row=>row.configured).length;
  const bytes = all.reduce((sum,row)=>sum+row.bytes,0);
  downloadedEl('downloaded-summary').textContent = `${rows.length} shown / ${all.length} folders · ${configured} configured · ${all.length-configured} not directly configured · ${downloadedInventory.partial ? 'at least ' : ''}${formatModSize(bytes)} on disk`;
}
async function loadDownloadedMods(refresh=false) {
  if (downloadedLoading) return;
  clearTimeout(downloadedTimer);
  downloadedLoading = true; downloadedEl('downloaded-refresh').disabled = true;
  const status = downloadedEl('downloaded-status');
  status.textContent = 'Scanning downloaded files…';
  try {
    const data = await readJson(await fetch('/api/mods/downloaded' + (refresh ? '?refresh=1' : ''), {signal:AbortSignal.timeout(15000)}));
    if (data.status === 'pending') {
      status.textContent = 'Scanning downloaded files in the background…';
      downloadedTimer = setTimeout(()=>{if (!downloadedEl('section-mods-downloaded').hidden) loadDownloadedMods();},1500);
      return;
    }
    downloadedInventory = data;
    status.textContent = data.message || `${data.partial ? 'Partial scan — some files could not be inspected. ' : ''}Scanned ${new Date(data.checked*1000).toLocaleString()}.${data.dependencies_complete ? '' : ' Dependency metadata is incomplete; unlisted downloads may still be required.'}`;
    renderDownloadedMods();
  } catch (error) {
    status.textContent = 'Inventory unavailable: ' + error.message + (downloadedInventory ? ' Displayed results are from the previous scan.' : '');
  } finally {
    downloadedLoading = false; downloadedEl('downloaded-refresh').disabled = false;
  }
}
downloadedEl('downloaded-refresh').onclick = () => loadDownloadedMods(true);
downloadedEl('downloaded-search').oninput = renderDownloadedMods;
downloadedEl('downloaded-filter').onchange = renderDownloadedMods;
downloadedEl('downloaded-sort').onchange = renderDownloadedMods;
window.addEventListener('pagehide',()=>clearTimeout(downloadedTimer));
