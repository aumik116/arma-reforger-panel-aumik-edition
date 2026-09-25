import json
import tempfile
import unittest
from pathlib import Path

from config_backups import backup_current, list_backups, load_backup, preview


class ConfigBackupTests(unittest.TestCase):
    def test_snapshot_review_and_path_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'server.json'
            original = {'game': {'scenarioId': 'first', 'mods': []}}
            path.write_text(json.dumps(original))
            name = backup_current(path)
            self.assertEqual(load_backup(path, name), original)
            self.assertEqual(len(list_backups(path)), 1)
            changed = {'game': {'scenarioId': 'second', 'mods': []}}
            diff, truncated = preview(changed, original)
            self.assertIn('first', diff)
            self.assertFalse(truncated)
            with self.assertRaises(ValueError):
                load_backup(path, '../server.json')


if __name__ == '__main__':
    unittest.main()
