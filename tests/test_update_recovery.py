from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from update_recovery import backup, restore


class RecoveryTests(unittest.TestCase):
    def test_restore_all_pages_and_remove_new_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel, source = root / 'panel', root / 'source'
            panel.mkdir()
            source.mkdir()
            (panel / 'config.env').write_text('PANEL_PORT=8888')
            pages = [path.name for path in Path(__file__).resolve().parents[1].glob('*.html')]
            for name in pages:
                (panel / name).write_text('old ' + name)
                (source / name).write_text('new ' + name)
            (panel / 'retired.html').write_text('old page')
            (source / 'new-page.html').write_text('new page')
            saved = backup(panel, source, root / 'etc', root / 'backups')
            for page in source.glob('*.html'):
                (panel / page.name).write_text(page.read_text())
            (panel / 'retired.html').unlink()
            restore(saved)
            for name in pages:
                self.assertEqual((panel / name).read_text(), 'old ' + name)
            self.assertEqual((panel / 'retired.html').read_text(), 'old page')
            self.assertFalse((panel / 'new-page.html').exists())

    def test_restore_files_services_and_keep_live_database_and_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel, source, etc = [root / name for name in ('panel','source','etc')]
            for path in (panel / 'static', source / 'static', etc / 'sudoers.d'):
                path.mkdir(parents=True)
            (panel / 'app.py').write_text('old code')
            (panel / 'config.env').write_text('PANEL_PORT=8888')
            (panel / 'static' / 'old.js').write_text('old asset')
            (source / 'new.py').write_text('new code')
            (etc / 'sudoers.d' / 'arma-panel-control').write_text('old permission')
            (panel / 'instances').mkdir()
            (panel / 'instances' / 'save').write_text('world')
            database = panel / '.panel-data.sqlite3'
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute('CREATE TABLE sample(value)')
                conn.execute("INSERT INTO sample VALUES ('before')")
            saved = backup(panel, source, etc, root / 'backups')
            (panel / 'app.py').write_text('broken code')
            (panel / 'new.py').write_text('new code')
            (panel / 'static' / 'old.js').unlink()
            (etc / 'sudoers.d' / 'arma-panel-control').write_text('new permission')
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("INSERT INTO sample VALUES ('after')")
            restore(saved)
            self.assertEqual((panel / 'app.py').read_text(), 'old code')
            self.assertFalse((panel / 'new.py').exists())
            self.assertEqual((panel / 'static' / 'old.js').read_text(), 'old asset')
            self.assertEqual((etc / 'sudoers.d' / 'arma-panel-control').read_text(), 'old permission')
            self.assertEqual((panel / 'instances' / 'save').read_text(), 'world')
            with closing(sqlite3.connect(database)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM sample').fetchone()[0], 2)
            with closing(sqlite3.connect(Path(saved) / 'panel-data.sqlite3')) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM sample').fetchone()[0], 1)
