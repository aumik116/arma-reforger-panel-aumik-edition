import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_ops import ServerFPS


class NativeStatsTests(unittest.TestCase):
    def test_counts_frame_times_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'console.log'
            path.write_text('old log\n')
            reader = ServerFPS()
            with patch('runtime_ops.time.monotonic', return_value=10):
                reader.read(str(path), 12)
                with path.open('a') as stream:
                    stream.write('FPS: 60.0, frame time (avg: 16.7 ms, min: 9.3 ms, max: 23.7 ms), Mem: 3291106 kB, Player: 2, AI: 104, Veh: 0 (17), Proj (S: 12)\n')
                sample = reader.read(str(path), 12)
                self.assertEqual([sample[key] for key in reader.empty_sample], [60, 2, 104, 17, 16.7, 23.7])
                with path.open('a') as stream:
                    stream.write('FPS: 30, frame time (avg: 33.3 ms), AI: 0, Veh: 9 (0)\n')
                sample = reader.read(str(path), 12)
                self.assertEqual(sample['ai_count'], 0)
                self.assertEqual(sample['vehicle_count'], 0)
                self.assertIsNone(sample['frame_time_max'])
                with path.open('a') as stream:
                    stream.write('FPS: 30, frame time (avg: invalid ms), AI: -1, Veh: invalid\n')
                sample = reader.read(str(path), 12)
                for key in ('player_count', 'ai_count', 'vehicle_count', 'frame_time_avg', 'frame_time_max'):
                    self.assertIsNone(sample[key])
            with patch('runtime_ops.time.monotonic', return_value=26):
                sample = reader.read(str(path), 12)
                self.assertTrue(all(sample[key] is None for key in reader.empty_sample))
                sample = reader.read(str(path), None)
                self.assertTrue(all(sample[key] is None for key in reader.empty_sample))


if __name__ == '__main__':
    unittest.main()
