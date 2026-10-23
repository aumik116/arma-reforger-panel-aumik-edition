// Server removal and explicit cleanup of files retained by earlier removals.
let serverRemoval=null,serverRemovalBusy=false;
const cleanupEl=id=>document.getElementById(id);
function closeServerRemoval(){if(!serverRemovalBusy)cleanupEl('server-remove-dialog').close();}
function removalWarning(){
 const deleting=serverRemoval?.orphan||new FormData(cleanupEl('server-remove-form')).get('mode')==='delete';
 cleanupEl('server-remove-warning').textContent=deleting?'Permanent deletion includes saves, mods, logs and backups. Files cannot be restored through the panel.':'The server will be stopped and removed from the panel. Files are archived on the VM for later cleanup.';
 cleanupEl('server-remove-confirm').textContent=deleting?'Permanently delete files':'Remove from panel';
}
async function openServerRemoval(server,refresh){
 try{
  const info=await readJson(await fetch('/api/servers/'+encodeURIComponent(server.id)+'/removal'));
  showServerRemoval({...info,orphan:false,refresh});
 }catch(error){document.getElementById('overview-feedback').textContent=error.message;}
}
function showServerRemoval(target){
 serverRemoval=target;const form=cleanupEl('server-remove-form');form.reset();cleanupEl('server-remove-error').textContent='';
 cleanupEl('server-remove-title').textContent=target.orphan?'Delete retained server files':'Remove '+target.name;
 cleanupEl('server-remove-description').textContent=target.orphan?'This server was previously removed from the panel. Review the folder before deleting it.':'The server will be stopped before removal.';
 cleanupEl('server-remove-path').textContent=target.path;cleanupEl('server-remove-id').textContent=target.id||target.server_id;cleanupEl('server-remove-options').hidden=!!target.orphan;
 removalWarning();cleanupEl('server-remove-dialog').showModal();form.elements.confirm_id.focus();
}
cleanupEl('server-remove-form').onchange=removalWarning;
cleanupEl('server-remove-close').onclick=closeServerRemoval;cleanupEl('server-remove-cancel').onclick=closeServerRemoval;
cleanupEl('server-remove-dialog').addEventListener('cancel',event=>{event.preventDefault();closeServerRemoval();});
cleanupEl('server-remove-form').onsubmit=async event=>{
 event.preventDefault();if(serverRemovalBusy||!serverRemoval)return;
 const values=new FormData(event.target),target=serverRemoval,id=target.id||target.server_id;
 if(values.get('confirm_id')!==id){cleanupEl('server-remove-error').textContent='Type the exact server ID shown above.';return;}
 serverRemovalBusy=true;cleanupEl('server-remove-confirm').disabled=true;cleanupEl('server-remove-error').textContent='';
 try{
  const result=await readJson(await postJson(target.orphan?'/api/server-cleanup/delete':'/api/servers/'+encodeURIComponent(id)+'/delete',target.orphan?{folder:target.folder,revision:target.revision,confirm_id:id}:{confirm_id:id,delete_files:values.get('mode')==='delete'}));
  cleanupEl('server-remove-dialog').close();
  document.getElementById('overview-feedback').textContent=result.warning||(target.orphan?'Retained server files deleted.':result.files_deleted?'Server and files deleted.':result.archived?'Server removed. Files retained at '+result.archived+'.':'Server removed. No server folder was found.');
  if(target.refresh)await target.refresh();
  if(cleanupEl('server-cleanup-dialog').open)await loadServerCleanup();
 }catch(error){cleanupEl('server-remove-error').textContent=error.message;}
 finally{serverRemovalBusy=false;cleanupEl('server-remove-confirm').disabled=false;}
};
let cleanupLoading=false;
async function loadServerCleanup(){
 if(cleanupLoading)return;cleanupLoading=true;cleanupEl('server-cleanup-refresh').disabled=true;cleanupEl('server-cleanup-status').textContent='Finding retained server folders…';
 try{
  const result=await readJson(await fetch('/api/server-cleanup'));const list=cleanupEl('server-cleanup-list');list.replaceChildren();
  cleanupEl('server-cleanup-status').textContent=result.folders.length+' retained folder(s) under '+result.root+'. Registered and unrecognized folders are excluded.';
  for(const folder of result.folders){
   const row=document.createElement('article');row.className='server-cleanup-folder';
   const name=document.createElement('strong');name.textContent=folder.server_id;
   const path=document.createElement('code');path.textContent=folder.path;
   const contents=document.createElement('p');contents.className='feature-note';contents.textContent='Contains: '+folder.contents.join(', ');
   const remove=document.createElement('button');remove.type='button';remove.className='btn-logout btn-danger';remove.textContent='Delete retained files';remove.onclick=()=>showServerRemoval({...folder,orphan:true});
   row.append(name,path,contents,remove);list.append(row);
  }
 }catch(error){cleanupEl('server-cleanup-status').textContent=error.message;}
 finally{cleanupLoading=false;cleanupEl('server-cleanup-refresh').disabled=false;}
}
cleanupEl('server-cleanup-open').onclick=()=>{cleanupEl('server-cleanup-dialog').showModal();loadServerCleanup();};
cleanupEl('server-cleanup-close').onclick=()=>cleanupEl('server-cleanup-dialog').close();cleanupEl('server-cleanup-refresh').onclick=loadServerCleanup;
