// Server selection only; fleet management lives at /servers.
document.addEventListener('DOMContentLoaded',async()=>{
  const select=document.getElementById('instance-switcher');
  try{
    const response=await fetch('/api/servers');if(!response.ok)throw new Error('Could not load servers');
    const data=await response.json();select.replaceChildren();
    const option=(id,name)=>{const item=document.createElement('option');item.value=id;item.textContent=name;select.append(item);};
    if(data.legacy_server)option('',data.legacy_server.name);
    for(const server of data.servers)if(server.state==='ready')option(server.id,server.name);
    select.value=selectedServerId;
    if(select.selectedIndex<0)option(selectedServerId,'Selected server unavailable');
    select.value=selectedServerId;
    select.onchange=()=>{location.href=select.value?'/?server='+encodeURIComponent(select.value):'/?legacy=1';};
  }catch(error){select.disabled=true;select.title=error.message;}
});
