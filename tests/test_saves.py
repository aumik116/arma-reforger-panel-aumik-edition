import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from save_library import SaveLibrary

class SaveLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.profile = self.base / 'profile'
        self.root = self.profile / '.save'
        self.save = self.root / 'sessions' / 'point'
        self.save.mkdir(parents=True)
        (self.save / 'meta-info.json').write_text('{"example": "test fixture"}')
        (self.save / 'data.bin').write_bytes(b'original scene\x00\xff')
        self.config = {'game': {'scenarioId':'camp-neptune', 'mods':[{'modId':'ABC', 'version':'1'}]}}
        self.api = SimpleNamespace(_BASE_DIR=str(self.base), PROFILE_DIR=str(self.profile), SERVER_DIR=str(self.base / 'server'),
            _SAVE_SUBDIRS=('.save', 'save', 'saves'), _save_root=lambda: str(self.root), read_config=lambda:self.config,
            get_server_pid=Mock(return_value=None), service_command=Mock(), software_manager=SimpleNamespace(busy=lambda:False))
        self.library = SaveLibrary(self.api)

    def test_capture_restore_binary_data_and_rollback(self):
        self.library.stopped()
        saved = self.library.capture('Training', 'admin')
        (self.save / 'data.bin').write_bytes(b'changed scene')
        rollback = self.library.restore(saved['snapshot'], 'admin')
        self.assertEqual((self.save / 'data.bin').read_bytes(), b'original scene\x00\xff')
        self.assertEqual((self.library.base / rollback / 'files/sessions/point/data.bin').read_bytes(), b'changed scene')
        self.assertEqual(len(self.library.listing()), 2)

    def test_invalid_paths_and_mismatched_context_do_not_replace_saves(self):
        saved = self.library.capture('Training', 'admin')
        for key in ['../escape', '', None]:
            with self.assertRaises(ValueError): self.library.restore(key, 'admin')
        self.config['game']['scenarioId'] = 'other'
        with self.assertRaisesRegex(ValueError, 'differs'): self.library.restore(saved['snapshot'], 'admin')
        self.assertEqual((self.save / 'data.bin').read_bytes(), b'original scene\x00\xff')

    def test_corrupt_snapshot_and_settings_only_directory_rejected(self):
        saved = self.library.capture('Training', 'admin')
        (self.library.base / saved['snapshot'] / 'files/sessions/point/data.bin').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'integrity'): self.library.restore(saved['snapshot'], 'admin')
        (self.save / 'meta-info.json').unlink()
        with self.assertRaisesRegex(ValueError, 'metadata'): self.library.capture('Missing metadata', 'admin')

    def test_running_server_and_custom_storage_rejected(self):
        self.api.get_server_pid.return_value = 42
        with self.assertRaisesRegex(ValueError, 'stop'): self.library.stopped()
        self.api.service_command.assert_not_called()
        self.config['game']['gameProperties'] = {'persistence': {'databases': {'custom': {}}}}
        with self.assertRaisesRegex(ValueError, 'Custom'): self.library.root()

    def test_failed_swap_rolls_back_existing_directory(self):
        saved = self.library.capture('Training', 'admin')
        (self.save / 'data.bin').write_bytes(b'current scene')
        original = Path.rename
        def fail_new(source, destination):
            if source.name == 'files' and source.parent.name.startswith('.restore-'):
                raise OSError('simulated rename failure')
            return original(source, destination)
        with patch.object(Path, 'rename', fail_new):
            with self.assertRaises(OSError): self.library.restore(saved['snapshot'], 'admin')
        self.assertEqual((self.save / 'data.bin').read_bytes(), b'current scene')
