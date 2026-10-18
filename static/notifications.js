async function loadNotifications(){
  const holder=byId('notification-events');
  try{
    const data=await getFeature('/api/notifications');const rows=[];
    const delivery={local:'Panel only',pending:'Discord queued',sent:'Discord delivered',failed:'Discord delivery failed',cancelled:'Discord cancelled'};
    for(const event of data.events){const row=document.createElement('p');row.textContent=`${new Date(event.created*1000).toLocaleString()} · ${event.message} · ${delivery[event.delivery]||event.delivery}`;rows.push(row);}
    if(!rows.length){const row=document.createElement('p');row.className='feature-note';row.textContent='No notifications yet. Monitoring runs with the Linux panel service.';rows.push(row);}
    holder.replaceChildren(...rows);
  }catch(error){holder.textContent=error.message;}
}
async function loadNotificationSettings(){
  try{
    const data=await getFeature('/api/notifications/settings');byId('notifications-test').disabled=!data.supported||!data.configured;if(!data.supported)byId('notifications-status').textContent='Local preview: automatic monitoring and Discord delivery run on the Linux panel service.';byId('notifications-webhook').value='';byId('notifications-routine').checked=data.routine;byId('notifications-role').value=data.role;byId('notifications-clear').checked=false;byId('notifications-configured').textContent=data.configured?'A webhook is saved. Its secret URL is hidden.':'No webhook saved. Notifications appear only in the panel.';
  }catch(error){byId('notifications-status').textContent=error.message;}
}
byId('notifications-form').onsubmit=async event=>{
  event.preventDefault();const button=byId('notifications-save');button.disabled=true;
  try{
    await changeFeature('/api/notifications/settings',{webhook:byId('notifications-webhook').value.trim(),routine:byId('notifications-routine').checked,role:byId('notifications-role').value.trim(),clear_webhook:byId('notifications-clear').checked});await loadNotificationSettings();byId('notifications-status').textContent='Saved for this server. New events use these settings.';
  }catch(error){byId('notifications-status').textContent=error.message;}finally{button.disabled=false;}
};
byId('notifications-test').onclick=async()=>{
  const button=byId('notifications-test');button.disabled=true;
  try{await changeFeature('/api/notifications/test',{});byId('notifications-status').textContent='Test queued using saved settings. Check Dashboard → Server notifications for delivery status. Delivery requires the Linux panel service.';await loadNotifications();}
  catch(error){byId('notifications-status').textContent=error.message;}finally{button.disabled=false;}
};
