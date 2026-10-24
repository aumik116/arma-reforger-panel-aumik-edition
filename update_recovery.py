"""Private, bounded installer snapshots; game files and saves are never touched."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing


SERVICE_FILES = (
    'systemd/system/arma-server.service',
    'systemd/system/arma-server.service.d/panel-control.conf',
    'systemd/system/arma-panel.service.d/legacy-game.conf',
    'systemd/system/arma-server@.service',
    'sudoers.d/arma-panel-control', 'sudoers.d/arma-panel-instances',
    'arma-panel/instance-control.py',
)


def backup(panel, source, config_root='/etc', backup_root='/var/backups/arma-panel'):
    panel, source, config_root = Path(panel).resolve(), Path(source).resolve(), Path(config_root).resolve()
    root = Path(backup_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    snapshot = Path(tempfile.mkdtemp(prefix='update-', dir=root))
    # Include files that the new installer may create, so rollback removes them.
    names = {p.name for folder in (panel, source) for p in folder.glob('*.py')}
    names.update(p.name for folder in (panel, source) for p in folder.glob('*.html'))
    names.update(('config.env', '.panel-secret'))
    for folder in (panel, source):
        for name in ('static','docs'):
            assets=folder/name
            if assets.is_symlink():
                raise ValueError(f'Update recovery requires a regular directory: {assets}')
            for asset in assets.rglob('*'):
                if asset.is_symlink():
                    raise ValueError(f'Update recovery requires regular assets: {asset}')
                if asset.is_file():
                    names.add(asset.relative_to(folder).as_posix())
    targets = [panel / name for name in sorted(names)] + [config_root / name for name in SERVICE_FILES]
    records = []
    for index, target in enumerate(targets):
        if target.is_symlink():
            raise ValueError(f'Update recovery requires regular files: {target}')
        record = {'path': str(target), 'saved': None}
        if target.exists():
            record['saved'] = str(index)
            shutil.copy2(target, snapshot / str(index))
            stat = target.stat()
            record.update(uid=stat.st_uid, gid=stat.st_gid)
        records.append(record)
    (snapshot / 'manifest.json').write_text(json.dumps(records))
    # Keep an independent consistent database backup for manual disaster recovery.
    # Do not rewind accounts/audit records automatically during code rollback.
    settings = {}
    for line in (panel / 'config.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            settings[key.strip()] = value.strip().strip('"').strip("'")
    database = Path(settings.get('PANEL_DATA_FILE', str(panel / '.panel-data.sqlite3')))
    if not database.is_absolute():
        database = panel / database
    if database.exists():
        with closing(sqlite3.connect(str(database))) as original, closing(sqlite3.connect(str(snapshot / 'panel-data.sqlite3'))) as saved:
            original.backup(saved)
    return str(snapshot)


def restore(snapshot):
    snapshot = Path(snapshot)
    for record in json.loads((snapshot / 'manifest.json').read_text()):
        target = Path(record['path'])
        if record['saved'] is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot / record['saved'], target)
            if hasattr(os, 'chown'):
                os.chown(target, record['uid'], record['gid'])


if __name__ == '__main__':
    if sys.argv[1] == 'backup':
        print(backup(*sys.argv[2:]))
    elif sys.argv[1] == 'restore':
        restore(sys.argv[2])
    else:
        sys.exit('Expected backup or restore')
