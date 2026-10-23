"""Bounded background file-size accounting for selected server locations."""
import os
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import jsonify, request


def scan_storage(paths,seconds=15,max_entries=250000):
    deadline=time.monotonic()+seconds
    rows=[];visited=0;partial=False
    paths=[(key,label,Path(os.path.abspath(path))) for key,label,path in paths]
    for key,label,path in paths:
        excluded={other for other_key,_,other in paths if other_key!=key and path in other.parents}
        total=count=errors=0
        pending=[Path(path)];seen=set()
        while pending:
            if time.monotonic()>deadline or visited>=max_entries:
                partial=True;break
            current=pending.pop();visited+=1
            if current in excluded or current.is_symlink():continue
            try:
                info=current.stat()
                if current.is_dir():
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if entry.is_symlink() or key=='profile' and entry.name=='.panel-trash':continue
                            pending.append(Path(entry.path))
                            if len(pending)+visited>=max_entries:
                                partial=True;break
                elif current.is_file():
                    identity=(info.st_dev,info.st_ino)
                    if identity not in seen:
                        total+=info.st_size;count+=1;seen.add(identity)
            except FileNotFoundError:
                continue
            except OSError:
                errors+=1
        rows.append(dict(key=key,label=label,bytes=total,files=count,errors=errors,partial=partial))
    return dict(status='partial' if partial or any(row['errors'] for row in rows) else 'ready',
                checked=time.time(),categories=rows,total_bytes=sum(row['bytes'] for row in rows))


def install(api):
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='storage-scan')
    cache={};lock=threading.Lock()
    @api.app.get('/api/storage')
    def storage_usage():
        instance=api.selected_instance()
        key=instance.id if instance else ''
        paths=[('game','Game files',str(api.SERVER_DIR)),('mods','Workshop mods',str(api.WORKSHOP_DIR)),
               ('logs','Server logs',str(api.LOG_DIR)),('profile','Profile and saves',str(api.PROFILE_DIR)),('trash','Trash',str(Path(api.PROFILE_DIR)/'.panel-trash')),
               ('backups','Backups',str(api._cfg.get('FILE_BACKUP_DIR') or Path(api._STATE_DIR)/'.file-backups')),
               ('config','Server configuration',str(api.SERVER_CONFIG))]
        with lock:
            previous=cache.get(key)
            if previous and not previous[1].done():
                return jsonify(ok=True,status='pending')
            if previous and request.args.get('refresh')!='1' and time.monotonic()-previous[0]<600:
                try:return jsonify(ok=True,**previous[1].result())
                except Exception:return jsonify(ok=False,error='Storage scan failed. Try refreshing.'),503
            if sum(not value[1].done() for value in cache.values())>=8:
                return jsonify(ok=False,error='Storage scanner is busy. Try again shortly.'),503
            cache[key]=(time.monotonic(),pool.submit(scan_storage,paths))
            for old in list(cache):
                if len(cache)>128 and cache[old][1].done():cache.pop(old)
        return jsonify(ok=True,status='pending')


def install_host(api):
    import shutil
    from flask import g
    api.PANEL_WIDE_ENDPOINTS.add('host_storage')
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='host-storage')
    job=None;started=0;lock=threading.Lock()
    legacy=None if api.manager_mode else [('legacy-game','Existing server · game',str(api.SERVER_DIR)),('legacy-mods','Existing server · mods',str(api.WORKSHOP_DIR)),('legacy-profile','Existing server · profile',str(api.PROFILE_DIR)),('legacy-logs','Existing server · logs',str(api.LOG_DIR))]

    def measure():
        paths=list(legacy or [])
        for server in api.server_registry.list():
            paths.extend((server.id+'-'+key,server.name+' · '+key,str(path)) for key,path in server.paths.items())
        from server_provisioning import retained_server_folder
        root=api.server_registry.root
        candidates=list(root.iterdir()) if root.exists() else []
        archive=root/'.removed'
        if archive.is_dir() and not archive.is_symlink():candidates+=list(archive.iterdir())
        for folder in candidates:
            try:
                retained,identity=retained_server_folder(api.server_registry,folder.relative_to(root).as_posix())
                paths.append(('retained-'+folder.name,'Retained · '+identity,str(retained)))
            except (ValueError,OSError):continue
        unique={}
        for key,label,path in paths:
            absolute=os.path.abspath(path)
            if absolute in unique:
                previous=unique[absolute]
                unique[absolute]=(previous[0],previous[1]+' / '+label,absolute)
            else:unique[absolute]=(key,label,absolute)
        paths=list(unique.values())
        result=scan_storage(paths,seconds=30,max_entries=500000)
        disks={}
        for _,_,path in paths+ [('panel','Panel data',str(Path(api.server_registry.database).parent))]:
            location=Path(path)
            while not location.exists() and location!=location.parent:location=location.parent
            if location.is_symlink():continue
            info=location.stat();usage=shutil.disk_usage(location)
            disks.setdefault(info.st_dev,dict(path=str(location),total=usage.total,used=usage.used,free=usage.free))
        result['filesystems']=list(disks.values())
        return result

    @api.app.get('/api/host/storage')
    def host_storage():
        nonlocal job,started
        if 'users' not in g.panel_permissions:return jsonify(ok=False,error='Panel administrator access required'),403
        with lock:
            if job and not job.done():return jsonify(ok=True,status='pending')
            if job and request.args.get('refresh')!='1' and time.monotonic()-started<600:
                try:return jsonify(ok=True,**job.result())
                except Exception:return jsonify(ok=False,error='Host storage scan failed. Refresh to try again.'),503
            started=time.monotonic();job=pool.submit(measure)
        return jsonify(ok=True,status='pending')
