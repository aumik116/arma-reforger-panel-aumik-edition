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
        for page in ('index.html', 'login.html', 'setup.html', 'servers.html'):
            html = (ROOT / page).read_text(encoding='utf-8')
            for asset in re.findall(r'/static/([\w.-]+)', html):
                self.assertTrue((ROOT / 'static' / asset).is_file(), f'{page} references missing {asset}')

    def test_original_navigation_and_accessible_targets_remain_available(self):
        html = (ROOT / 'index.html').read_text(encoding='utf-8')
        sidebar = html.split('<aside', 1)[1].split('</aside>', 1)[0]
        self.assertEqual(set(re.findall(r'id="tab-([^"]+)"', sidebar)), {
            'dashboard', 'console', 'persistence', 'configuration',
            'mods', 'files', 'network', 'administration','startup','players','scheduler'})
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)), 'Duplicate HTML IDs break shared controls')
        for target in re.findall(r'aria-controls="([^"]+)"', html):
            self.assertIn(target, ids, f'Missing accessible tab target: {target}')


if __name__ == '__main__':
    unittest.main()
