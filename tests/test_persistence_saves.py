import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import persistence_saves
import runtime_ops


UUID = '07e8fa26-d5b6-47f6-a19b-641c72ab05bc'


class PersistenceSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = self.root / 'panel'
        self.panel.mkdir()
        self.profile = self.root / 'profile'
        self.point = self.profile / '.save' / 'sessions' / 'session-1' / 'point-1'
        self.point.mkdir(parents=True)
        (self.point / 'meta-info.json').write_text(json.dumps({'uuid': UUID}), encoding='utf-8')
        (self.point / 'world.bin').write_bytes(b'FOB')
        self.scenario = '{394A32B84B229832}Missions/GM_CampNeptune_Persistence.conf'

    def test_named_backup_and_pin_survive_game_retention_and_relaunch(self):
        points = persistence_saves.list_save_points(self.profile)
        self.assertEqual([point['uuid'] for point in points], [UUID])
        persistence_saves.save_named_point(self.panel, self.profile, self.scenario, UUID, 'Everon FOB')
        self.assertEqual(persistence_saves.named_saves_for(self.panel, self.scenario)[0]['name'], 'Everon FOB')
        persistence_saves.set_startup_save(self.panel, self.profile, self.scenario, UUID)

        shutil.rmtree(self.point)
        self.assertEqual(persistence_saves.prepare_startup_save(self.panel, self.profile, self.scenario), UUID)
        self.assertEqual((self.point / 'world.bin').read_bytes(), b'FOB')

        config = self.root / 'server.json'
        config.write_text(json.dumps({'game': {'scenarioId': self.scenario,
            'gameProperties': {'persistence': {'loadSessionSave': True}}}}), encoding='utf-8')
        env = self.panel / 'config.env'
        env.write_text(f'SERVER_DIR={self.root}\nSERVER_CONFIG={config}\nPROFILE_DIR={self.profile}\n', encoding='utf-8')
        with patch.object(runtime_ops.os, 'chdir'), patch.object(runtime_ops.os, 'execv') as execute:
            runtime_ops.launch_server(str(env))
        args = execute.call_args.args[1]
        self.assertEqual(args[args.index('-loadSessionSave') + 1], UUID)

        persistence_saves.set_startup_save(self.panel, self.profile, self.scenario, '')
        self.assertIsNone(persistence_saves.prepare_startup_save(self.panel, self.profile, self.scenario))
        self.assertEqual(persistence_saves.named_saves_for(self.panel, self.scenario)[0]['name'], 'Everon FOB')
        shutil.rmtree(self.point)
        persistence_saves.set_startup_save(self.panel, self.profile, self.scenario, UUID)
        self.assertEqual(persistence_saves.prepare_startup_save(self.panel, self.profile, self.scenario), UUID)
        self.assertIsNone(persistence_saves.selection_for(self.panel, 'another-scenario'))

    def test_missing_archive_blocks_pinned_launch_instead_of_loading_latest(self):
        persistence_saves.set_startup_save(self.panel, self.profile, self.scenario, UUID)
        shutil.rmtree(persistence_saves._archive_path(self.panel, self.scenario, UUID))
        with self.assertRaisesRegex(RuntimeError, 'archive is missing'):
            persistence_saves.prepare_startup_save(self.panel, self.profile, self.scenario)

    def test_unrecognized_metadata_cannot_be_selected(self):
        (self.point / 'meta-info.json').write_text('{"id":"not-a-uuid"}', encoding='utf-8')
        self.assertEqual(persistence_saves.list_save_points(self.profile), [])
        with self.assertRaisesRegex(ValueError, 'not found'):
            persistence_saves.save_named_point(self.panel, self.profile, self.scenario, UUID, 'FOB')


if __name__ == '__main__':
    unittest.main()
