(() => {
  const manual=document.getElementById('manual-content');
  if(manual){
    const input=document.getElementById('manual-search'),status=document.getElementById('manual-find-status');let term='',matches=[],index=-1;
    function find(){
      const query=input.value.trim();
      if(query!==term){
        for(const mark of matches)mark.replaceWith(document.createTextNode(mark.textContent));manual.normalize();matches=[];index=-1;term=query;
        if(term){const walker=document.createTreeWalker(manual,NodeFilter.SHOW_TEXT),nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
          for(const text of nodes){if(matches.length>=500)break;const value=text.nodeValue,lower=value.toLowerCase(),needle=term.toLowerCase();let start=0,at=lower.indexOf(needle),fragment=document.createDocumentFragment();if(at<0)continue;
            while(at>=0&&matches.length<500){fragment.append(document.createTextNode(value.slice(start,at)));const mark=document.createElement('mark');mark.textContent=value.slice(at,at+term.length);fragment.append(mark);matches.push(mark);start=at+term.length;at=lower.indexOf(needle,start);}fragment.append(document.createTextNode(value.slice(start)));text.replaceWith(fragment);
          }
        }
      }
      if(!matches.length){status.textContent=term?'No matches.':'';return;}index=(index+1)%matches.length;matches[index].scrollIntoView({block:'center'});status.textContent=`Match ${index+1} of ${matches.length}${matches.length===500?' (first 500)':''}`;
    }
    document.getElementById('manual-find-next').onclick=find;input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();find();}});input.addEventListener('search',find);return;
  }
  const header=document.querySelector('header');if(!header)return;
  const button=document.createElement('button');button.type='button';button.id='panel-help-open';button.className='btn-logout';button.textContent='Help';button.setAttribute('aria-haspopup','dialog');
  const actions=header.querySelector('.fieldhq-account');if(actions)actions.prepend(button);else header.append(button);
  const dialog=document.createElement('dialog');dialog.className='help-dialog';dialog.setAttribute('aria-labelledby','panel-help-title');
  dialog.innerHTML='<div class="mods-dialog-heading"><h2 id="panel-help-title">Help for this page</h2><button type="button" class="btn-logout" data-close>Close</button></div><p role="status" data-status></p><article class="manual-content" data-content></article><div class="help-dialog-footer"><a data-section href="/help">Read this section in the manual</a><a href="/help/manual/full">Full user manual</a><a href="/help/manual/staff">Unit staff manual</a></div>';
  document.body.append(dialog);const el=selector=>dialog.querySelector(selector);el('[data-close]').onclick=()=>dialog.close();let serial=0;
  function topic(){
    if(location.pathname==='/servers')return 'servers';if(location.pathname==='/account')return 'account';if(location.pathname==='/setup')return 'setup';
    if(location.pathname==='/units'){const tab=document.querySelector('[data-unit-tab][aria-selected="true"]');return document.getElementById('unit-workspace')?.hidden?'units':tab?'unit-'+tab.dataset.unitTab:'units';}
    const tab=document.querySelector('.panel-tab[aria-selected="true"]');const name=tab?.id.replace(/^tab-/,'')||'dashboard';
    if(name==='mods'){const section=document.querySelector('[data-section-group="mods"][aria-selected="true"]');return section?'mods-'+section.dataset.sectionKey:'mods';}
    if(name==='administration'){const section=document.querySelector('[data-section-group="admin"][aria-selected="true"]');return section?'admin-'+section.dataset.sectionKey:name;}
    return name;
  }
  button.onclick=async()=>{
    const request=++serial;PanelUI.open(dialog);el('[data-content]').replaceChildren();el('[data-status]').textContent='Loading help for this page…';
    try{const data=await readJson(await fetch('/help/topic/'+encodeURIComponent(topic())));if(request!==serial||!dialog.open)return;el('[data-content]').innerHTML=data.html;el('[data-section]').href=data.manual_url;el('[data-status]').textContent='';dialog.scrollTop=0;}
    catch(error){if(request===serial)el('[data-status]').textContent='Help could not load. Open one of the manuals below or try again.';}
  };
  dialog.addEventListener('close',()=>serial++);
})();
