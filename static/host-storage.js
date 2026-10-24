// One storage entry point: host breakdown for admins, accessible servers for staff.
(() => {
  const button=document.getElementById('overview-storage'),dialog=document.createElement('dialog');dialog.className='fleet-update-dialog';dialog.setAttribute('aria-labelledby','storage-overview-title');
  dialog.innerHTML='<div class="fleet-dialog-heading"><h2 id="storage-overview-title">Storage</h2><button class="btn-logout" type="button" data-close>Close</button></div><div class="panel-dialog-toolbar"><button class="btn-logout" type="button" data-refresh>Refresh measurement</button><span data-cleanup></span></div><p data-status role="status"></p><div data-disks class="storage-disk-counters"></div><div class="fleet-table-wrap"><table><thead><tr><th>Server / category</th><th>Logical size</th><th>Files</th></tr></thead><tbody></tbody></table></div><details class="storage-reading-note"><summary>About storage measurements</summary><p>Logical sizes can differ from physical usage because of copy-on-write. Filesystem totals include other host files. Scans are bounded; partial results are labeled. Measurements are cached for ten minutes.</p></details>';
  document.body.append(dialog);dialog.querySelector('[data-cleanup]').append(document.getElementById('server-cleanup-open'));
  const el=selector=>dialog.querySelector(selector),bytes=value=>(value/1073741824).toFixed(2)+' GiB';let timer,admin=false,serial=0;
  async function load(refresh=false){
    const request=++serial;clearTimeout(timer);el('[data-status]').textContent='Measuring storage…';el('[data-refresh]').disabled=true;
    try{
      let data;
      if(admin)data=await readJson(await fetch('/api/host/storage'+(refresh?'?refresh=1':'')));
      else{
        const visible=await readJson(await fetch('/api/servers')),servers=visible.servers.filter(row=>row.state==='ready');if(visible.legacy_server)servers.push({id:'',name:visible.legacy_server.name});
        const results=await Promise.allSettled(servers.map(async server=>({server,data:await readJson(await fetch('/api/storage'+(refresh?'?refresh=1':''),{headers:{'X-Server-ID':server.id}}))})));
        data={status:'ready',categories:[],filesystems:[],checked:Date.now()/1000,total_bytes:0};
        for(let index=0;index<results.length;index++){
          const result=results[index];if(result.status==='rejected'){data.status='partial';data.categories.push({label:servers[index].name+' · Unavailable',bytes:null,files:null});continue;}
          const {server,data:usage}=result.value;if(usage.status==='pending'){data.status='pending';continue;}
          if(usage.status==='partial')data.partial=true;for(const row of usage.categories)data.categories.push({...row,label:server.name+' · '+row.label});data.total_bytes+=usage.total_bytes;
        }
      }
      if(request!==serial||!dialog.open)return;
      if(data.status==='pending'){timer=setTimeout(()=>load(),2000);return;}
      el('[data-disks]').replaceChildren();
      for(const disk of data.filesystems){const card=document.createElement('div');card.className='card';const value=document.createElement('strong');value.className='chart-value';value.textContent=bytes(disk.free)+' free';const label=document.createElement('p');label.textContent=bytes(disk.used)+' used / '+bytes(disk.total)+' total';const path=document.createElement('small');path.textContent=disk.path;card.append(value,label,path);el('[data-disks]').append(card);}
      el('tbody').replaceChildren();
      for(const category of data.categories){const row=document.createElement('tr');for(const value of [category.label,category.bytes===null?'Unavailable':bytes(category.bytes)+(category.partial||category.errors?' (partial)':''),category.files===null?'—':category.files.toLocaleString()]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}el('tbody').append(row);}
      el('[data-status]').textContent=`${bytes(data.total_bytes)} accounted for · ${new Date(data.checked*1000).toLocaleString()}${data.status==='partial'||data.partial?' · Some readings are incomplete.':''}`;
    }catch(error){if(request===serial)el('[data-status]').textContent=error.message;}finally{if(request===serial)el('[data-refresh]').disabled=false;}
  }
  button.onclick=async()=>{PanelUI.open(dialog);try{const account=await readJson(await fetch('/api/me'));admin=(account.panel_permissions||[]).includes('users');await load();}catch(error){el('[data-status]').textContent=error.message;}};
  el('[data-refresh]').onclick=()=>load(true);el('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{serial++;clearTimeout(timer);});
})();
