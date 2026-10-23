(() => {
  const button=document.getElementById('host-storage-open');
  const dialog=document.createElement('dialog');dialog.className='fleet-update-dialog';
  dialog.innerHTML='<div class="fleet-dialog-heading"><h2>Host storage</h2><button class="btn-logout" type="button" data-close>Close</button></div><p>Logical file sizes by server and category. Reflink copies can share physical blocks, so category totals may exceed physical usage. Shared roots are counted once. Other host files contribute to filesystem usage.</p><button class="btn-logout" type="button" data-refresh>Refresh measurement</button><p data-status role="status"></p><div data-disks></div><div class="fleet-table-wrap"><table><thead><tr><th>Server / category</th><th>Logical size</th><th>Files</th></tr></thead><tbody></tbody></table></div>';
  document.body.append(dialog);let timer;
  const el=selector=>dialog.querySelector(selector),bytes=value=>(value/1073741824).toFixed(2)+' GiB';
  async function load(refresh=false){
    clearTimeout(timer);el('[data-status]').textContent='Measuring host storage…';
    try{
      const data=await readJson(await fetch('/api/host/storage'+(refresh?'?refresh=1':'')));
      if(!dialog.open)return;
      if(data.status==='pending'){timer=setTimeout(()=>load(),2000);return;}
      el('[data-disks]').replaceChildren();
      for(const disk of data.filesystems){const p=document.createElement('p');p.textContent=`${disk.path}: ${bytes(disk.used)} used / ${bytes(disk.total)} total · ${bytes(disk.free)} free`;el('[data-disks]').append(p);}
      el('tbody').replaceChildren();
      for(const category of data.categories){const row=document.createElement('tr');for(const value of [category.label,bytes(category.bytes)+(category.partial||category.errors?' (partial)':''),category.files.toLocaleString()]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}el('tbody').append(row);}
      el('[data-status]').textContent=`${bytes(data.total_bytes)} accounted for · ${new Date(data.checked*1000).toLocaleString()}${data.status==='partial'?' · Partial scan: time/file limit or unreadable files.':''}`;
    }catch(error){el('[data-status]').textContent=error.message;}
  }
  button.onclick=()=>{dialog.showModal();load();};el('[data-refresh]').onclick=()=>load(true);
  el('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>clearTimeout(timer));
  fetch('/api/me').then(readJson).then(account=>{button.hidden=!(account.panel_permissions||[]).includes('users');}).catch(()=>{});
})();
