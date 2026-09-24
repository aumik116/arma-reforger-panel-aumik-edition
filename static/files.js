// Admin-only, scoped browser for profile text configs and read-only logs.
let filesRoot = 'profile';
let filesPath = '';
let filesEntries = [];
let filesSelected = null;
let filesOriginal = '';
let filesRevision = '';
let filesReviewedText = null;
let filesLoaded = false;
let filesBusy = false;

const filesEditor = byId('files-content');
const fileUrl = (endpoint, root, path) => `${endpoint}?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`;
const fileSize = bytes => bytes == null ? '' : bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1048576).toFixed(1)} MiB`;
const filesDirty = () => filesSelected?.editable && filesEditor.value !== filesOriginal;

function filesFeedback(message, error = false) {
  byId('files-feedback').textContent = message;
  byId('files-feedback').classList.toggle('error', error);
}

function resetFileEditor() {
  filesSelected = null;
  filesOriginal = '';
  filesRevision = '';
  filesReviewedText = null;
  filesEditor.value = '';
  filesEditor.readOnly = true;
  byId('files-current-name').textContent = 'Select a file';
  byId('files-current-meta').textContent = 'Choose a text file to inspect it.';
  byId('files-diff-panel').hidden = true;
  filesFeedback('');
  updateFileActions();
}

function updateFileActions() {
  const editable = filesSelected?.editable && !filesBusy;
  const dirty = filesDirty();
  byId('files-download').disabled = !filesSelected;
  byId('files-reload').disabled = !filesSelected || filesBusy;
  byId('files-review').disabled = !editable || !dirty;
  byId('files-save').disabled = !editable || !dirty || filesReviewedText !== filesEditor.value;
  byId('files-edit-state').textContent = !filesSelected ? 'No file selected'
    : !filesSelected.editable ? 'Read-only file' : dirty ? 'Unsaved edits' : 'No unsaved changes';
}

function confirmLeaveFile() {
  return !filesDirty() || confirm('Discard your unsaved file edits?');
}

function renderFileBreadcrumbs() {
  const holder = byId('files-breadcrumbs');
  const labels = {profile:'Game profile', logs:'Server logs', 'server-config':'Server config'};
  const segments = filesPath ? filesPath.split('/') : [];
  const buttons = [];
  for (let depth = 0; depth <= segments.length; depth++) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = depth ? segments[depth - 1] : labels[filesRoot];
    const destination = segments.slice(0, depth).join('/');
    button.addEventListener('click', () => openFilesFolder(destination));
    buttons.push(button);
  }
  holder.replaceChildren(...buttons);
}

function renderFilesEntries() {
  const filter = byId('files-search').value.trim().toLowerCase();
  const visible = filesEntries.filter(entry => entry.name.toLowerCase().includes(filter));
  const rows = visible.map(entry => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'files-entry';
    button.setAttribute('aria-current', String(filesSelected?.root === filesRoot && filesSelected?.path === entry.path));
    const icon = document.createElement('span'); icon.className = 'files-entry-icon'; icon.textContent = entry.directory ? '▣' : '▤';
    const name = document.createElement('span'); name.textContent = entry.name;
    const size = document.createElement('small'); size.textContent = entry.directory ? '' : fileSize(entry.size);
    button.append(icon, name, size);
    button.addEventListener('click', () => entry.directory ? openFilesFolder(entry.path) : openFilesFile(entry));
    return button;
  });
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.textContent = filter ? 'No matches in this folder.' : 'No supported text files in this folder.';
    rows.push(empty);
  }
  byId('files-list').replaceChildren(...rows);
}

async function refreshFiles() {
  if (filesBusy) return;
  byId('files-list-note').textContent = 'Loading folder…';
  try {
    const data = await getFeature(fileUrl('/api/files', filesRoot, filesPath));
    filesEntries = data.entries;
    renderFileBreadcrumbs();
    renderFilesEntries();
    byId('files-list-note').textContent = `${filesEntries.length} item${filesEntries.length === 1 ? '' : 's'}${data.truncated ? ' · first 500 shown' : ''}`;
  } catch (error) {
    filesEntries = [];
    renderFilesEntries();
    byId('files-list-note').textContent = error.message;
  }
}

function selectFilesRoot(root) {
  if (root === filesRoot && filesLoaded) return;
  if (!confirmLeaveFile()) return;
  filesRoot = root;
  filesPath = '';
  filesLoaded = true;
  byId('files-search').value = '';
  document.querySelectorAll('[data-files-root]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filesRoot === root)));
  resetFileEditor();
  refreshFiles();
}

function openFilesFolder(path) {
  if (path === filesPath) return;
  if (!confirmLeaveFile()) return;
  filesPath = path;
  byId('files-search').value = '';
  resetFileEditor();
  refreshFiles();
}

async function openFilesFile(entry, bypassDirty = false) {
  if (!bypassDirty && !confirmLeaveFile()) return;
  filesSelected = {...entry, root:filesRoot};
  filesOriginal = '';
  filesRevision = '';
  filesReviewedText = null;
  filesEditor.value = '';
  filesEditor.readOnly = true;
  byId('files-current-name').textContent = entry.name;
  byId('files-current-meta').textContent = `${fileSize(entry.size)} · ${entry.editable ? 'Editable game profile file' : 'Read-only'}`;
  byId('files-diff-panel').hidden = true;
  filesFeedback('Loading file…');
  renderFilesEntries();
  updateFileActions();
  try {
    const data = await getFeature(fileUrl('/api/files/content', filesRoot, entry.path));
    if (filesSelected?.root !== filesRoot || filesSelected?.path !== entry.path) return;
    filesSelected.editable = data.editable;
    filesEditor.value = data.content;
    filesOriginal = filesEditor.value;
    filesRevision = data.revision;
    filesEditor.readOnly = !data.editable;
    const modified = new Date(data.modified * 1000).toLocaleString();
    byId('files-current-meta').textContent = `${fileSize(data.size)} · Modified ${modified} · ${data.editable ? 'Editable' : 'Read-only'}`;
    filesFeedback(data.editable ? 'Review changes before saving. A backup is created automatically.' : 'This file is read-only here.');
    updateFileActions();
  } catch (error) {
    filesFeedback(error.message, true);
    updateFileActions();
  }
}

function reloadSelectedFile() {
  if (!filesSelected || !confirmLeaveFile()) return;
  openFilesFile(filesSelected, true);
}

function downloadSelectedFile() {
  if (!filesSelected) return;
  const link = document.createElement('a');
  link.href = fileUrl('/api/files/download', filesSelected.root, filesSelected.path);
  link.download = filesSelected.name;
  document.body.append(link);
  link.click();
  link.remove();
}

async function reviewSelectedFile() {
  if (!filesSelected?.editable || !filesDirty() || filesBusy) return;
  filesBusy = true; updateFileActions();
  try {
    const response = await postJson('/api/files/preview', {
      root:filesSelected.root, path:filesSelected.path, content:filesEditor.value, revision:filesRevision
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not review changes');
    filesReviewedText = data.changed ? filesEditor.value : null;
    byId('files-diff').textContent = data.diff || 'No content changes.';
    byId('files-diff-panel').hidden = false;
    filesFeedback(data.truncated ? 'Diff is truncated. Only the first part is shown; download the file if you need a complete comparison.' :
      data.changed ? 'Review the diff, then select Save file.' : 'No content changes to save.');
  } catch (error) {
    filesReviewedText = null;
    byId('files-diff-panel').hidden = true;
    filesFeedback(error.message, true);
  } finally { filesBusy = false; updateFileActions(); }
}

async function saveSelectedFile() {
  if (!filesSelected?.editable || !filesDirty() || filesReviewedText !== filesEditor.value || filesBusy) return;
  filesBusy = true; updateFileActions();
  let saved = false;
  try {
    const response = await postJson('/api/files/save', {
      root:filesSelected.root, path:filesSelected.path, content:filesEditor.value, revision:filesRevision
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not save file');
    filesRevision = data.revision;
    filesOriginal = filesEditor.value;
    filesReviewedText = null;
    byId('files-diff-panel').hidden = true;
    filesFeedback(`Saved. Backup: ${data.backup}`);
    saved = true;
  } catch (error) {
    filesReviewedText = null;
    filesFeedback(error.message, true);
  } finally { filesBusy = false; updateFileActions(); if (saved) refreshFiles(); }
}

function openFilesPanel() {
  if (!filesLoaded) selectFilesRoot('profile');
}

document.querySelectorAll('[data-files-root]').forEach(button => button.addEventListener('click', () => selectFilesRoot(button.dataset.filesRoot)));
byId('files-search').addEventListener('input', renderFilesEntries);
filesEditor.addEventListener('input', () => {
  filesReviewedText = null;
  byId('files-diff-panel').hidden = true;
  updateFileActions();
});
window.addEventListener('beforeunload', event => {
  if (filesDirty()) { event.preventDefault(); event.returnValue = ''; }
});
