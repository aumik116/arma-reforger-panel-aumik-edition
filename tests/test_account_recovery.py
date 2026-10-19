import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import bcrypt
from account_recovery import database_path, reset_owner


class AccountRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'accounts.sqlite3'
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript('''
                CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,password TEXT,version INTEGER);
                CREATE TABLE panel_owner(singleton INTEGER,user_id INTEGER);
                CREATE TABLE activity(ts REAL,actor TEXT,action TEXT,outcome TEXT,details TEXT);
                INSERT INTO users VALUES(1,'staff','unchanged',3);
                INSERT INTO users VALUES(7,'renamed-owner','old-hash',8);
                INSERT INTO panel_owner VALUES(1,7);
            ''')

    def test_reset_targets_recorded_owner_and_revokes_sessions(self):
        self.assertEqual(reset_owner(self.path, 'replacement-password'), 'renamed-owner')
        with closing(sqlite3.connect(self.path)) as conn:
            owner = conn.execute('SELECT password,version FROM users WHERE id=7').fetchone()
            self.assertTrue(bcrypt.checkpw(b'replacement-password', owner[0].encode()))
            self.assertEqual(owner[1], 9)
            self.assertEqual(conn.execute('SELECT password,version FROM users WHERE id=1').fetchone(), ('unchanged', 3))
            record = conn.execute('SELECT action,details FROM activity').fetchone()
            self.assertEqual(record[0], 'owner_password_reset')
            self.assertNotIn('replacement-password', record[1])

    def test_invalid_password_or_missing_owner_does_not_change_database(self):
        for password in ('short', 'x' * 73, 'é' * 37):
            with self.assertRaises(ValueError):
                reset_owner(self.path, password)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('SELECT password FROM users WHERE id=7').fetchone()[0], 'old-hash')
            conn.execute('DELETE FROM panel_owner')
        with self.assertRaises(ValueError):
            reset_owner(self.path, 'replacement-password')
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT password FROM users WHERE id=7').fetchone()[0], 'old-hash')

    def test_wrong_path_never_creates_database(self):
        path = self.root / 'wrong.sqlite3'
        with self.assertRaises(sqlite3.Error):
            reset_owner(path, 'replacement-password')
        self.assertFalse(path.exists())

    def test_resolves_default_and_custom_database_paths(self):
        config = self.root / 'config.env'
        config.write_text('# Default\nPANEL_PASSWORD_HASH=unused\n', encoding='utf-8')
        self.assertEqual(database_path(self.root), self.root / '.panel-data.sqlite3')
        config.write_text('PANEL_DATA_FILE="accounts.sqlite3"\n', encoding='utf-8')
        self.assertEqual(database_path(self.root), self.path)
        config.write_text('PANEL_DATA_FILE=' + str(self.path) + '\n', encoding='utf-8')
        self.assertEqual(database_path(self.root), self.path)
