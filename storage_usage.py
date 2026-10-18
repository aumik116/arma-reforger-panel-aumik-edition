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
