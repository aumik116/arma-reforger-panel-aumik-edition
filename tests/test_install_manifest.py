import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerManifestTests(unittest.TestCase):
    def test_both_install_modes_copy_every_panel_module(self):
        installer = (ROOT / 'install.sh').read_text(encoding='utf-8')
        manifest = re.search(r'^PANEL_PY_FILES=\(([^)]*)\)', installer, re.MULTILINE)
        self.assertIsNotNone(manifest)
        listed = set(manifest.group(1).split())
        self.assertEqual(listed, {path.name for path in ROOT.glob('*.py')})
        self.assertIn('update_panel_with_recovery "$PANEL_DIR_EXISTING" "$EXISTING_USER"', installer)
        self.assertIn('copy_panel_files "$panel_dir"', installer)
        self.assertIn('copy_panel_files "$PANEL_DIR"', installer)

    def test_referenced_static_assets_exist_and_are_copied(self):
        installer = (ROOT / 'install.sh').read_text(encoding='utf-8')
        self.assertIn('cp "$SCRIPT_DIR/static/"* "$destination/static/"', installer)
        for page in ('index.html', 'login.html'):
            html = (ROOT / page).read_text(encoding='utf-8')
            for asset in re.findall(r'/static/([\w.-]+)', html):
                self.assertTrue((ROOT / 'static' / asset).is_file(), f'{page} references missing {asset}')


if __name__ == '__main__':
    unittest.main()
