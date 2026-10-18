const storageBytes=bytes=>bytes>=1e9?(bytes/1e9).toFixed(2)+' GB':bytes>=1e6?(bytes/1e6).toFixed(2)+' MB':bytes>=1000?(bytes/1000).toFixed(1)+' KB':bytes+' B';
let storageTimer;
async function loadStorageBreakdown(refresh=false){
  clearTimeout(storageTimer);const status=byId('storage-status');status.textContent='Scanning server storage…';
  try{
    const data=await getFeature('/api/storage'+(refresh?'?refresh=1':''));
    if(data.status==='pending'){if(byId('storage-details').open)storageTimer=setTimeout(()=>loadStorageBreakdown(),2000);return;}
    const holder=byId('storage-breakdown');holder.replaceChildren();
    for(const row of data.categories){const line=document.createElement('p');line.textContent=`${row.label}: ${storageBytes(row.bytes)} · ${row.files.toLocaleString()} ${row.files===1?'file':'files'}${row.partial?' · partial':''}${row.errors?' · some files could not be read':''}`;holder.append(line);}
    status.textContent=`${storageBytes(data.total_bytes)} accounted for · ${new Date(data.checked*1000).toLocaleString()}${data.status==='partial'?' · Partial scan: time/file limit or unreadable files. Refresh to try again.':''}`;
  }catch(error){status.textContent=error.message;}
}
byId('storage-details').ontoggle=()=>{if(byId('storage-details').open)loadStorageBreakdown();else clearTimeout(storageTimer);};
byId('storage-refresh').onclick=()=>loadStorageBreakdown(true);
