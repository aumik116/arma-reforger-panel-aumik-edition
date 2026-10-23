"""Seed missing Workshop downloads before launch, using independent local copies."""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time

from mod_inventory import scan_downloads, mod_id, read_metadata
from server_software import write_state

REPORT = '.mod-reuse.json'
ACTOR = '.mod-reuse-actor.json'


def report(directory):
    try:
        path=Path(directory)/REPORT
        if path.is_symlink():return {}
        return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def remember_actor(directory, user_id):
    if type(user_id) is int:
        path=Path(directory)/ACTOR
        if path.is_symlink():raise ValueError('Mod reuse settings must not be a link')
        write_state(path,dict(user_id=user_id))
        path.chmod(0o600)


def source_ids(registry, directory):
    """Recheck the initiating account's current server visibility at every launch."""
    try:
        policy=Path(directory)/ACTOR
        if policy.is_symlink():return set()
        actor=json.loads(policy.read_text())['user_id']
        with registry.connect() as conn:
            user=conn.execute('SELECT * FROM users WHERE id=?',(actor,)).fetchone()
            owner=conn.execute('SELECT user_id FROM panel_owner WHERE singleton=1').fetchone()
            if not user or not user['enabled']:return set()
            if (owner and actor==owner[0]) or user['access_all']:
                return {server.id for server in registry.list()}|{'__existing__'}
            return {row[0] for row in conn.execute('SELECT server_id FROM user_server_roles WHERE user_id=?',(actor,))}
    except (OSError,ValueError,KeyError,TypeError):return set()


def invalidate_index(registry, identity):
    with registry.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS mod_download_index (server_id TEXT PRIMARY KEY,root TEXT NOT NULL,checked REAL NOT NULL,inventory TEXT NOT NULL)')
        conn.execute('DELETE FROM mod_download_index WHERE server_id=?',(identity,))


def indexed_inventory(registry, identity, root, refresh=False):
    root=str(Path(root).absolute())
    with registry.connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS mod_download_index (server_id TEXT PRIMARY KEY,root TEXT NOT NULL,checked REAL NOT NULL,inventory TEXT NOT NULL)')
        saved=conn.execute('SELECT root,checked,inventory FROM mod_download_index WHERE server_id=?',(identity,)).fetchone()
    if saved and not refresh and saved[0]==root and time.time()-saved[1]<120:
        try:return json.loads(saved[2])
        except ValueError:pass
    inventory=scan_downloads(root,measure_sizes=False)
    with registry.connect() as conn:
        conn.execute('INSERT OR REPLACE INTO mod_download_index VALUES(?,?,?,?)',(identity,root,time.time(),json.dumps(inventory)))
    return inventory


def fingerprint(folder):
    """Reject links, partial downloads and file changes, including added/deleted files."""
    result={}
    for root,dirs,files in os.walk(folder,followlinks=False):
        for name in dirs+files:
            path=Path(root)/name
            info=path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError('Source contains a linked or special file')
            relative=path.relative_to(folder).as_posix()
            if name.lower() in ('temp','tmp') and path.is_dir():
                if any(path.iterdir()):raise ValueError('Source has a download in progress')
            if name.lower().endswith(('.part','.download','.tmp')):
                raise ValueError('Source has an incomplete download')
            result[relative]=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,stat.S_IFMT(info.st_mode))
            if len(result)>100000:raise ValueError('Source contains too many files to verify')
    return result


def clone_folder(source, destination, snapshot):
    import fcntl
    cloned=ordinary=0
    for relative,expected in snapshot.items():
        origin=source/relative;target=destination/relative
        if expected[-1]==stat.S_IFDIR:
            target.mkdir(parents=True,exist_ok=True);continue
        target.parent.mkdir(parents=True,exist_ok=True)
        descriptor=os.open(origin,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(descriptor,'rb') as incoming, target.open('xb') as outgoing:
            info=os.fstat(incoming.fileno())
            actual=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,stat.S_IFMT(info.st_mode))
            if actual!=expected:raise ValueError('Source changed during copying')
            try:
                fcntl.ioctl(outgoing.fileno(),0x40049409,incoming.fileno())  # Linux FICLONE, independent inodes.
                cloned+=1
            except OSError as exc:
                if exc.errno not in (errno.EXDEV,errno.EOPNOTSUPP,errno.ENOTTY,errno.EINVAL,errno.ENOSYS):raise
                shutil.copyfileobj(incoming,outgoing,1024*1024);ordinary+=1
        os.chmod(target,0o600)
    if fingerprint(source)!=snapshot:raise ValueError('Source changed during copying')
    return dict(reflink_files=cloned,copied_files=ordinary)


def seed_mods(registry, target_id, target_root, directory, config, legacy_root=None):
    """Best-effort only: leave unavailable/changed mods for Reforger's downloader."""
    directory=Path(directory);target_root=Path(target_root).absolute()
    state=dict(state='running',started=time.time(),copied=0,reflink_files=0,copied_files=0,skipped=0,messages=[])
    def save():
        state['updated']=time.time();write_state(directory/REPORT,state)
    def note(message):
        state['skipped']+=1
        if len(state['messages'])<30:state['messages'].append(message)
        save()
    if target_root.resolve()!=target_root:raise ValueError('Destination Workshop directory redirects through a link')
    target_root.mkdir(parents=True,exist_ok=True)
    from server_provisioning import lock_job
    import fcntl
    with (directory/'.mod-reuse.lock').open('a+') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        staging_prefix='.mod-reuse-'+hashlib.sha256(str(target_root).encode()).hexdigest()[:12]+'-'
        for abandoned in target_root.parent.glob(staging_prefix+'*'):
            if abandoned.is_dir() and not abandoned.is_symlink():shutil.rmtree(abandoned,ignore_errors=True)
        save()
        try:
            allowed=source_ids(registry,directory)
            sources=[(server.id,server.paths['workshop'],server.directory) for server in registry.list() if server.id!=target_id and server.id in allowed and server.state=='ready']
            if legacy_root and target_id!='__existing__' and '__existing__' in allowed:
                sources.append(('__existing__',Path(legacy_root),Path(legacy_root).parent))
            wanted={mod_id(item.get('modId')):item.get('version') or '' for item in config.get('game',{}).get('mods',[]) if mod_id(item.get('modId'))}
            installed=indexed_inventory(registry,target_id,target_root,refresh=True)
            if not wanted or not sources:
                state['state']='complete';save();return state
            if installed['partial']:
                note('Destination inventory is incomplete; local reuse skipped.');state['state']='complete';save();return state
            existing={item['modId'] for item in installed['mods']}
            candidates={}
            for identity,root,source_directory in sources:
                try:
                    inventory=indexed_inventory(registry,identity,root)
                    for item in inventory['mods']:
                        if item['modId'] and item['version']:
                            candidates.setdefault(item['modId'],[]).append((item,Path(root).absolute(),source_directory))
                except (OSError,ValueError):continue
            pending=list(wanted.items());seen=set()
            while pending:
                identity,version=pending.pop(0)
                if identity in seen:continue
                seen.add(identity)
                matches=[item for item in candidates.get(identity,[]) if not version or item[0]['version']==version]
                matches.sort(key=lambda item:(tuple(int(n) for n in re.findall(r'\d+',item[0]['version'])),item[0]['version']),reverse=True)
                if not matches:
                    if identity not in existing:note(identity+': no matching local download; Reforger will download it.')
                    continue
                if identity in existing:
                    # Existing downloads stay untouched, but their known dependencies can still be seeded.
                    installed_match=next((item for item in installed['mods'] if item['modId']==identity),None)
                    for dependency in (installed_match or {}).get('dependencies') or []:
                        pending.append((dependency,wanted.get(dependency,'')))
                    continue
                copied=False
                for item,root,source_directory in matches:
                    temporary=None
                    try:
                        with lock_job(source_directory,'.software-job.lock'),lock_job(source_directory,'.provision.lock'),lock_job(source_directory,'.mod-reuse.lock'):
                            source=root/item['path'];target=target_root/item['path']
                            if source.resolve()!=source or root not in source.parents or source==target or source in target.parents or target in source.parents:raise ValueError('Source path redirects or overlaps the destination')
                            if target.resolve()!=target or target_root not in target.parents:raise ValueError('Destination path redirects outside Workshop storage')
                            if target.exists():continue
                            metadata=read_metadata(source)
                            actual_id=mod_id(metadata.get('id') or metadata.get('modId'))
                            if actual_id and actual_id!=identity:raise ValueError('Indexed source mod changed')
                            versions=metadata.get('versions')
                            latest=versions[0] if isinstance(versions,list) and versions and isinstance(versions[0],dict) else {}
                            actual_version=str(latest.get('version') or metadata.get('version') or '')
                            if actual_version!=item['version']:raise ValueError('Indexed source version changed')
                            snapshot=fingerprint(source)
                            if not any(name in snapshot and snapshot[name][2]>0 for name in ('data.pak','addon.gproj','resourceDatabase.rdb')):
                                raise ValueError('Downloaded asset files could not be verified')
                            temporary=Path(tempfile.mkdtemp(prefix=staging_prefix,dir=target_root.parent))
                            result=clone_folder(source,temporary,snapshot)
                            target.parent.mkdir(parents=True,exist_ok=True)
                            if target.exists() or target.resolve()!=target:raise ValueError('Destination changed during copying')
                            temporary.rename(target);temporary=None
                            state['copied']+=1
                            state['reflink_files']+=result['reflink_files'];state['copied_files']+=result['copied_files']
                            existing.add(identity);save();copied=True
                            for dependency in item['dependencies'] or []:pending.append((dependency,wanted.get(dependency,'')))
                            break
                    except (OSError,ValueError):continue
                    finally:
                        if temporary:shutil.rmtree(temporary,ignore_errors=True)
                if not copied:note(identity+': no stable copy available; Reforger will download it.')
            if state['copied']:indexed_inventory(registry,target_id,target_root,refresh=True)
            state['state']='complete';save();return state
        except Exception:
            state['state']='unavailable';note('Local reuse could not finish. Reforger will handle remaining downloads normally.');save();raise


def install(api):
    """Mod-list writes on stopped servers opportunistically seed in the background."""
    from concurrent.futures import ThreadPoolExecutor
    from flask import g
    executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mod-reuse')
    original=api.write_config
    legacy_root=None if api.manager_mode else str(api.WORKSHOP_DIR)

    def copy_after_save(identity, operation_lock):
        try:
            with api.operator_tools.selected(identity):
                with operation_lock:
                    if api.get_server_pid():return
                    from server_provisioning import lock_job
                    with lock_job(Path(api._STATE_DIR),'.software-job.lock'):
                        result=seed_mods(api.server_registry,identity or '__existing__',str(api.WORKSHOP_DIR),str(api._STATE_DIR),api.read_config(),legacy_root)
                    api.app.logger.info('Local mod reuse: %s copied for %s',result['copied'],identity or 'existing server')
        except Exception:
            api.app.logger.info('Local mod reuse deferred to startup for %s',identity or 'existing server',exc_info=True)

    def write_config(config):
        before=api.read_config().get('game',{}).get('mods',[])
        original(config)
        after=config.get('game',{}).get('mods',[])
        if before==after:return
        previous={mod.get('modId'):mod.get('version') for mod in before}
        added=any(mod.get('modId') not in previous or previous[mod.get('modId')]!=mod.get('version') for mod in after)
        try:
            instance=api.selected_instance()
            identity=instance.id if instance else ''
            actor=(getattr(g,'user',None) or {}).get('id')
            remember_actor(str(api._STATE_DIR),actor)
            if added and not api.get_server_pid():
                operation_lock=api.operation_lock._get_current_object()
                executor.submit(copy_after_save,identity,operation_lock)
        except Exception:
            api.app.logger.info('Local mod reuse will be attempted at startup',exc_info=True)
    api.write_config=write_config
