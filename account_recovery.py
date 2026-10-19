"""Local terminal recovery for the existing panel Owner; never imports the app."""
import argparse
from contextlib import closing
import getpass
import json
from pathlib import Path
import sqlite3
import sys
import time

import bcrypt


def database_path(panel):
    panel = Path(panel).resolve()
    settings = {}
    for line in (panel / 'config.env').read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            settings[key.strip()] = value.strip().strip('"').strip("'")
    path = Path(settings.get('PANEL_DATA_FILE', '.panel-data.sqlite3'))
    return path if path.is_absolute() else panel / path


def reset_owner(path, password):
    if not isinstance(password, str) or len(password) < 10 or len(password.encode('utf-8')) > 72:
        raise ValueError('Use at least 10 characters and at most 72 UTF-8 bytes.')
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode()
    # mode=rw refuses to create a database at an incorrect installation path.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True, timeout=15)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        owner = conn.execute('SELECT users.id,users.username FROM panel_owner JOIN users ON users.id=panel_owner.user_id WHERE panel_owner.singleton=1').fetchone()
        if not owner:
            raise ValueError('No existing Owner account found. No changes made.')
        conn.execute('UPDATE users SET password=?,version=version+1 WHERE id=?', (hashed, owner[0]))
        conn.execute('INSERT INTO activity(ts,actor,action,outcome,details) VALUES(?,?,?,?,?)',
                     (time.time(), owner[1], 'owner_password_reset', 'success', json.dumps({'source':'local_terminal'})))
    return owner[1]


def main():
    parser = argparse.ArgumentParser(description='Reset the existing Owner password using local VM access. No game servers are restarted.')
    parser.add_argument('--panel-dir', required=True, type=Path, help='Installed panel directory containing config.env')
    args = parser.parse_args()
    try:
        if not sys.stdin.isatty():
            raise ValueError('Run from an interactive terminal. Passwords cannot be supplied through arguments or pipes.')
        path = database_path(args.panel_dir)
        if not path.is_file():
            raise ValueError('Panel account database not found. Check the installed panel directory.')
        password = getpass.getpass('New Owner password: ')
        if password != getpass.getpass('Confirm new Owner password: '):
            raise ValueError('Passwords do not match. No changes made.')
        username = reset_owner(path, password)
        print(f'Owner password reset for {username}. Sign in with the new password. Existing sessions are signed out.')
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'Recovery failed: {exc}', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nRecovery cancelled. No changes made.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
