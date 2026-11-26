"""fit-kradar: pairing, split mapping, the data check and whether the fit finds known parameters in made-up data."""
import hashlib
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
from pipeline.errors import fitted


class SharedKradarFilesTest(unittest.TestCase):
    """The files in pipeline/kradar that let everyone fit the same data and use the same fit without it."""

    def test_table_sums_accept_the_listed_version_only(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'reference').mkdir()
            (data / 'reference' / 'a.parquet').write_bytes(b'table')
            right = data / 'right.sha256'
            right.write_text(f'{hashlib.sha256(b"table").hexdigest()}  reference/a.parquet\n')
            wrong = data / 'wrong.sha256'
            wrong.write_text(f'{"0" * 64}  reference/a.parquet\n')
            names = ['reference/a.parquet']
            self.assertEqual(fit_kradar.table_sums(data, names, right), fit_kradar.table_sums(data, names))
            with self.assertRaises(ValueError):
                fit_kradar.table_sums(data, names, wrong)
            with self.assertRaises(ValueError):
                fit_kradar.table_sums(data, ['reference/none.parquet'])

    def test_largest_difference_compares_numbers_and_layout(self):
        a = {'cells': [{'b_m': 0.1, 't': math.nan, 'name': 'all'}], 'runs': [1, 2]}
        self.assertEqual(fit_kradar.largest_difference(a, a), 0.0)
        self.assertAlmostEqual(fit_kradar.largest_difference(a, {**a, 'runs': [1, 2.5]}), 0.5)
        self.assertIsNone(fit_kradar.largest_difference(a, {**a, 'runs': [1]}))
        self.assertIsNone(fit_kradar.largest_difference(a, {'cells': a['cells']}))

    def test_shared_fit_and_meta_are_complete(self):
        self.assertEqual(sorted(fit_kradar.read_sums(fit_kradar.KRADAR / 'tables.sha256')),
                         ['candidates/kradar_asf.parquet', 'candidates/kradar_l4dr.parquet',
                          'candidates/kradar_pvrcnn.parquet', 'reference/kradar_P3.parquet'])
        for name in ('train.txt', 'test.txt', 'sequences.csv'):
            self.assertTrue((fit_kradar.KRADAR / 'meta' / name).is_file(), name)
        for profile in ('asf', 'pvrcnn', 'l4dr'):
            fit = fitted.load({**fitted.SETTINGS, 'profile': profile, 'condition': 'range'})
            self.assertEqual(len(fit['rows']), 3)


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

    def test_duplicates_keep_the_most_confident_box(self):
        det = pd.DataFrame({'recording_id': 'R', 'frame_idx': [0, 0, 0, 0, 1],
                            'class_name': ['Sedan', 'Sedan', 'BusOrTruck', 'Sedan', 'Sedan'],
                            'x': [10.0, 10.5, 10.2, 20.0, 10.0], 'y': 0.0, 'confidence': [0.5, 0.9, 0.4, 0.3, 0.6]})
        kept, dropped = fit_kradar.drop_duplicates(det)
        self.assertEqual(dropped, 1)                              # the 0.5 Sedan, 0.5 m from the 0.9 one
        self.assertEqual(sorted(kept.confidence.tolist()), [0.3, 0.4, 0.6, 0.9])

    def test_reference_suspects_are_what_every_detector_shows(self):
        rng = np.random.default_rng(3)
        offsets = {f'T{k}': 0.1 * rng.normal() for k in range(30)}
        offsets['T0'] = 1.5                                       # every detector reads it 1.5 m too far
        leads = {}
        for detector, own in (('a', 0.0), ('b', 0.05)):
            rows = [(f'R{k % 5}', track, frame, True, offset + own + 0.05 * rng.normal())
                    for k, (track, offset) in enumerate(offsets.items()) for frame in range(30)]
            leads[detector] = pd.DataFrame(rows, columns=['recording_id', 'track_id', 'frame_idx', 'hit', 'error_m'])
        lags = pd.DataFrame({'a': [-3.0, 2.0, 0.0, 0.0], 'b': [-2.0, -2.0, 0.0, 0.0]},
                            index=['R1', 'R2', 'R3', 'all'])
        suspects = fit_kradar.reference_suspects(leads, lags)
        self.assertEqual(suspects['recordings'], ['R1'])          # R2: off both ways
        self.assertEqual(suspects['tracks'], ['T0'])
        kept = fit_kradar.drop_suspects(leads['a'], suspects)
        self.assertFalse(kept.recording_id.eq('R1').any() or kept.track_id.eq('T0').any())

    def test_error_split_separates_the_shared_part(self):
        rng = np.random.default_rng(4)
        n = 20000
        shared = 0.2 * rng.normal(size=n)
        leads = {}
        for detector, own in (('a', 0.1), ('b', 0.15), ('c', 0.05)):
            leads[detector] = pd.DataFrame({'track_id': [f'T{k // 100}' for k in range(n)], 'frame_idx': np.arange(n),
                                            'hit': True, 'error_m': shared + own * rng.normal(size=n),
                                            'range_m': 30.0})
        split = fit_kradar.error_split(leads)
        for detector, own in (('a', 0.1), ('b', 0.15), ('c', 0.05)):
            self.assertAlmostEqual(split[detector]['all']['shared_sd_m'], 0.2, delta=0.01)
            self.assertAlmostEqual(split[detector]['all']['own_sd_m'], own, delta=0.015)

    def test_target_offsets_are_track_means_and_the_rest_is_the_spread_around_them(self):
        rng = np.random.default_rng(2)
        offsets = {'T0': -1.0, 'T1': 0.0, 'T2': 2.5}
        rows = []
        for track, offset in offsets.items():
            for frame in range(400):
                band = '0-25' if frame < 200 else '25-45'
                rows.append((track, 'R0', frame, True, offset + 0.2 * rng.normal(), band, 'normal'))
        rows.append(('T3', 'R0', 0, True, 9.0, '0-25', 'normal'))          # too short: left out
        lead = pd.DataFrame(rows, columns=['track_id', 'recording_id', 'frame_idx', 'hit', 'error_m', 'band', 'group'])
        fit = fit_kradar.target_offsets(lead)
        self.assertEqual(len(fit['offsets_m']), 3)
        for found, true in zip(fit['offsets_m'], sorted(offsets.values())):
            self.assertAlmostEqual(found, true, delta=0.05)
        self.assertEqual(set(fit['residual']), {'all', 'range 0-25 m', 'range 25-45 m', 'weather normal'})
        self.assertAlmostEqual(fit['residual']['all']['sd_m'], 0.2, delta=0.02)
        self.assertLess(fit['tau_s'], 0.3)                                  # white noise: no correlation over time


if __name__ == '__main__':
    unittest.main()
