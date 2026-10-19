// Server-administrator file management with isolated profile writes.
let filesRoot = 'profile';
let filesPath = '';
let filesEntries = [];
let filesSelected = null;
let filesOriginal = '';
let filesRevision = '';
let filesReviewedText = null;
let filesLoaded = false;
let filesBusy = false;
let filesReadSerial = 0;

const filesEditor = byId('files-content');
const fileUrl = (endpoint, root, path) => `${endpoint}?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}${selectedServerId ? '&_server=' + encodeURIComponent(selectedServerId) : ''}`;
const fileSize = bytes => bytes == null ? '' : bytes < 1000 ? `${bytes} B` : bytes < 1000000 ? `${(bytes / 1000).toFixed(1)} KB` : bytes < 1000000000 ? `${(bytes / 1000000).toFixed(1)} MB` : `${(bytes / 1000000000).toFixed(2)} GB`;
const filesDirty = () => filesSelected?.editable && filesEditor.value !== filesOriginal;

function filesFeedback(message, error = false) {
  byId('files-feedback').textContent = message;
  byId('files-feedback').classList.toggle('error', error);
}

function resetFileEditor() {
  filesReadSerial++;
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
  document.querySelectorAll('[data-files-root], #files-management button, .files-row-action').forEach(button=>button.disabled=filesBusy);
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
  const labels = {profile:'Game profile', logs:'Server logs', 'server-config':'Server config',workshop:'Workshop',server:'Game files',backups:'Backups'};
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
    button.type = 'button'; button.className = 'files-entry'; button.title=entry.name;
    button.setAttribute('aria-current', String(filesSelected?.root === filesRoot && filesSelected?.path === entry.path));
    const icon = document.createElement('span'); icon.className = 'files-entry-icon'; icon.textContent = entry.directory ? '▣' : '▤';
    const name = document.createElement('span'); name.textContent = entry.name;
    const size = document.createElement('small'); size.textContent = entry.directory ? '' : fileSize(entry.size);
    button.append(icon, name, size);
    button.addEventListener('click', () => entry.directory ? openFilesFolder(entry.path) : openFilesFile(entry));
    const row=document.createElement('div');row.className='files-entry-row';row.append(button);
    if(filesRoot==='profile'){
      for(const [label,action] of [['Rename',()=>renameFilesEntry(entry)],['Trash',()=>trashFilesEntry(entry)]]){
        const control=document.createElement('button');control.type='button';control.className='files-row-action';control.textContent=label;control.setAttribute('aria-label',label+' '+entry.name);control.onclick=action;row.append(control);
      }
    }
    return row;
  });
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.textContent = filter ? 'No matches in this folder.' : 'This folder is empty.';
    rows.push(empty);
  }
  byId('files-list').replaceChildren(...rows);
}

async function refreshFiles() {
  if (filesBusy) return;
  byId('files-list-note').textContent = 'Loading folder…';
  const root=filesRoot,path=filesPath;
  try {
    const data = await getFeature(fileUrl('/api/files', root, path));
    if(root!==filesRoot||path!==filesPath)return;
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
  if(filesBusy)return;
  if (root === filesRoot && filesLoaded) return;
  if (!confirmLeaveFile()) return;
  filesRoot = root;
  byId('files-management').hidden=root!=='profile';
  filesPath = '';
  filesLoaded = true;
  byId('files-search').value = '';
  document.querySelectorAll('[data-files-root]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filesRoot === root)));
  resetFileEditor();
  refreshFiles();
}

function openFilesFolder(path) {
  if(filesBusy)return;
  if (path === filesPath) return;
  if (!confirmLeaveFile()) return;
  filesPath = path;
  byId('files-search').value = '';
  resetFileEditor();
  refreshFiles();
}

async function openFilesFile(entry, bypassDirty = false) {
  if(filesBusy)return;
  const serial=++filesReadSerial;
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
  if(entry.text===false){filesFeedback('Binary file. Use Download to save a copy.');return;}
  try {
    const data = await getFeature(fileUrl('/api/files/content', filesRoot, entry.path));
    if (serial!==filesReadSerial||filesSelected?.root !== filesRoot || filesSelected?.path !== entry.path) return;
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
    if(serial!==filesReadSerial)return;
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


async function filesMutation(url,body){
  const response=await postJson(url,body);const data=await response.json();
  if(!response.ok||!data.ok)throw new Error(data.error||'File operation failed');
  return data;
}
function filesChildPath(name){return filesPath?filesPath+'/'+name:name;}
async function createFilesEntry(kind){
  if(filesBusy||filesRoot!=='profile'||!confirmLeaveFile())return;
  const name=prompt(kind==='folder'?'New folder name':'New text file name (for example settings.json)');if(!name)return;
  if(name.includes('/')||name.includes('\\')){filesFeedback('Enter a name, without folder separators.',true);return;}
  filesBusy=true;updateFileActions();
  try{await filesMutation('/api/files/create',{root:filesRoot,path:filesChildPath(name),kind});resetFileEditor();filesFeedback('Created '+name+'.');}
  catch(error){filesFeedback(error.message,true);}finally{filesBusy=false;updateFileActions();await refreshFiles();}
}
async function renameFilesEntry(entry){
  if(filesBusy||!confirmLeaveFile())return;
  const name=prompt('New name for '+entry.name,entry.name);if(!name||name===entry.name)return;
  if(name.includes('/')||name.includes('\\')){filesFeedback('Enter a name, without folder separators.',true);return;}
  filesBusy=true;updateFileActions();
  try{await filesMutation('/api/files/rename',{root:filesRoot,path:entry.path,destination:filesChildPath(name),revision:entry.revision});resetFileEditor();filesFeedback('Renamed to '+name+'.');}
  catch(error){filesFeedback(error.message,true);}finally{filesBusy=false;updateFileActions();await refreshFiles();}
}
async function trashFilesEntry(entry){
  if(filesBusy||!confirmLeaveFile()||!confirm('Move '+entry.name+(entry.directory?' and everything inside it':'')+' to Trash? You can restore it later.'))return;
  filesBusy=true;updateFileActions();
  try{await filesMutation('/api/files/delete',{root:filesRoot,path:entry.path,revision:entry.revision});resetFileEditor();filesFeedback('Moved to Trash. Use Trash / restore deleted files to undo.');}
  catch(error){filesFeedback(error.message,true);}finally{filesBusy=false;updateFileActions();await refreshFiles();}
}
let filesUploadController=null;
byId('files-upload-cancel').onclick=()=>filesUploadController?.abort();
async function uploadFiles(files, folder=false){
  if(filesBusy||filesRoot!=='profile'||!files.length||!confirmLeaveFile())return;
  filesBusy=true;updateFileActions();filesUploadController=new AbortController();
  const signal=filesUploadController.signal,results=byId('files-upload-results');results.replaceChildren();
  byId('files-upload-progress').hidden=false;byId('files-upload-cancel').disabled=false;
  let uploaded=0,failed=0,processed=0;
  const report=()=>{byId('files-upload-summary').textContent=processed+' / '+files.length+' processed · '+uploaded+' uploaded · '+failed+' skipped or failed';byId('files-upload-meter').max=files.length;byId('files-upload-meter').value=processed;};report();
  try{
    for(const file of files){
      if(signal.aborted)break;
      const name=folder?file.webkitRelativePath:file.name;
      let message='';
      try{
        if(!name)throw new Error('Folder path unavailable');
        if(file.size>50*1024*1024)throw new Error('Exceeds 50 MiB');
        filesFeedback('Uploading '+name+'…');
        const form=new FormData();form.append('root',filesRoot);form.append('path',filesChildPath(name));form.append('file',file);if(folder)form.append('create_parents','true');
        const response=await postForm('/api/files/upload',form,{signal});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'Upload failed');
        uploaded++;message=name+': uploaded';
      }catch(error){
        if(signal.aborted)break;
        failed++;message=name+': '+error.message;
      }
      processed++;report();
      if(results.children.length<500){const row=document.createElement('li');row.textContent=message;results.append(row);}
    }
    resetFileEditor();filesFeedback(signal.aborted?'Upload cancelled. Completed files are kept. The active file may have reached the server; refresh before retrying.':uploaded+' uploaded · '+failed+' skipped or failed.',failed>0);
    report();
    if(signal.aborted)byId('files-upload-summary').textContent+=' · Cancelled';
    if(processed>500){const row=document.createElement('li');row.textContent='First 500 file results shown.';results.append(row);}
  }finally{filesUploadController=null;filesBusy=false;byId('files-upload-cancel').disabled=true;byId('files-upload-input').value='';byId('files-folder-input').value='';updateFileActions();await refreshFiles();}
}
byId('files-upload-input').onchange=event=>uploadFiles([...event.target.files]);
byId('files-folder-input').onchange=event=>uploadFiles([...event.target.files],true);
if(!('webkitdirectory' in byId('files-folder-input'))){byId('files-upload-folder').hidden=true;}
async function openFilesTrash(){
  const dialog=byId('files-trash-dialog');if(!dialog.open)dialog.showModal();
  const status=byId('files-trash-status'),holder=byId('files-trash-items');status.textContent='Loading Trash…';holder.replaceChildren();
  try{
    const data=await getFeature('/api/files/trash');status.textContent=data.entries.length?'':'Trash is empty.';
    for(const item of data.entries){
      const row=document.createElement('div');row.className='files-trash-row';const label=document.createElement('span');label.textContent=item.path+' · '+new Date(item.deleted).toLocaleString();
      const restore=document.createElement('button');restore.type='button';restore.textContent='Restore';restore.onclick=async()=>{restore.disabled=true;try{await filesMutation('/api/files/restore',{token:item.token});await openFilesTrash();await refreshFiles();}catch(error){status.textContent=error.message;restore.disabled=false;}};
      row.append(label,restore);holder.append(row);
    }
  }catch(error){status.textContent=error.message;}
}
