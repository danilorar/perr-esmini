"""fit-kradar: pairing, split mapping and whether the fit finds known parameters in made-up data."""
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

try:
    import pandas as pd
except ImportError:          # fit-kradar needs pandas; the rest of the pipeline does not
    pd = None

from pipeline import fit_kradar


@unittest.skipIf(pd is None, 'pandas is not installed')
class FitKradarTest(unittest.TestCase):
    def test_assign_takes_nearest_pairs_first_and_respects_the_gate(self):
        i, j = fit_kradar.assign(np.array([0.0, 10.0]), np.zeros(2), np.array([9.0, 0.5, 30.0]), np.zeros(3), 3.0)
        self.assertEqual(sorted(zip(i.tolist(), j.tolist())), [(0, 1), (1, 0)])

    def test_split_rows_map_to_frame_index(self):
        with tempfile.TemporaryDirectory() as folder:
            meta = Path(folder)
            # sequence 1: 4 frames, label 00003 in neither list; sequence 2: 2 frames with gaps in the label numbers
            (meta / 'train.txt').write_text('1,00010_00001.txt\n1,00011_00002.txt\n2,00050_00005.txt\n')
            (meta / 'test.txt').write_text('1,00013_00004.txt\n2,00060_00009.txt\n')
            (meta / 'sequences.csv').write_text('sequence,road_type,time,weather,frames\n1,urban,day,normal,4\n'
                                                '2,urban,day,fog,2\n')
            split = fit_kradar.read_split(meta).set_index(['recording_id', 'frame_idx']).part
        self.assertEqual(split.to_dict(), {('kradar_001', 0): 'train', ('kradar_001', 1): 'train',
                                           ('kradar_001', 3): 'test', ('kradar_002', 0): 'train',
                                           ('kradar_002', 1): 'test'})

    def test_fit_finds_bias_spread_correlation_time_and_misses(self):
        rng = np.random.default_rng(1)
        b, sigma_ou, sigma_white, tau, p_miss, t_miss = 0.2, 0.3, 0.1, 1.0, 0.1, 0.3
        leave = fit_kradar.DT_S / t_miss                     # miss -> seen
        enter = leave * p_miss / (1 - p_miss)                 # seen -> miss
        rho = math.exp(-fit_kradar.DT_S / tau)
        rows = []
        for track in range(400):
            z, missed = rng.normal(), rng.random() < p_miss
            for frame in range(150):
                if frame:
                    z = rho * z + math.sqrt(1 - rho * rho) * rng.normal()
                    missed = rng.random() >= leave if missed else rng.random() < enter
                error = b + sigma_ou * z + sigma_white * rng.normal()
                rows.append((f'T{track}', f'R{track % 20}', frame, not missed, error, 30.0))
        lead = pd.DataFrame(rows, columns=['track_id', 'recording_id', 'frame_idx', 'hit', 'error_m', 'range_m'])
        lead.loc[~lead.hit, 'error_m'] = np.nan
        fit = fit_kradar.cell(lead)
        self.assertAlmostEqual(fit['b_m'], b, delta=0.03)
        self.assertAlmostEqual(fit['sd_m'], math.hypot(sigma_ou, sigma_white), delta=0.03)
        self.assertAlmostEqual(fit['sigma_white_m'], sigma_white, delta=0.04)
        self.assertGreater(fit['tau_s'], 0.7)
        self.assertLess(fit['tau_s'], 1.4)
        self.assertAlmostEqual(fit['p_miss'], p_miss, delta=0.015)
        self.assertAlmostEqual(fit['t_miss_s'], t_miss, delta=0.04)


if __name__ == '__main__':
    unittest.main()
