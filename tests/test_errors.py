"""Error plugins: the registry, settings, the plugin chain and the frame sequences."""
import csv
import json
import math
from pathlib import Path
import statistics
import tempfile
from types import SimpleNamespace
import unittest

from pipeline import errors, scenarios
from pipeline.config import validate
from pipeline.errors.frames import hold_per_step, iid_frames, markov_frames, markov_parameters, missed_steps, wrong_class_steps
from pipeline.errors import fitted, lateral, velocity
from pipeline.errors.ou import SIGMA_PER_MAE, CorrelatedRangeNoise, unit_samples
from pipeline.errors.outliers import TargetOutliers

TARGET = {'id': 1, 'name': 'object_2'}
DT = 0.01
# ego at the origin at 20 m/s; both boxes 4 m x 2 m
EGO = [0.0, 0.0, 0.0, 0.0, 20.0, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0, 2.0, 1.5, 0.0]
REPLY = ('range', 'x', 'y', 'heading', 'speed', 'vx', 'vy', 'vz', 'ax', 'ay', 'az', 'length', 'width')


def longest_run(states):
    best = current = 0
    for state in states:
        current = current + 1 if state else 0
        best = max(best, current)
    return best


def config(entries, seed=0):
    return validate({'scenario': 'gidas_1549178', 'errors': entries, 'seed': seed})


def message(step, gap=30.0, speed=5.0):
    """A bridge request as esmini writes it: time, object count, the observer, then every target."""
    target = [gap, 0.0, 0.0, 0.0, speed, speed, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0, 2.0, 1.5, gap]
    cells = [b'@@PB', b'S', (step * DT).hex().encode(), b'2', b'object_1', *(v.hex().encode() for v in EGO),
             b'object_2', *(v.hex().encode() for v in target)]
    return b'\t'.join(cells) + b'\n'


def reply(line):
    cells = line.rstrip(b'\n').split(b'\t')
    assert cells[:2] == [b'@@PB', b'R'] and len(cells) == 3 + len(REPLY), cells
    return int(cells[2]), dict(zip(REPLY, (float.fromhex(cell.decode()) for cell in cells[3:])))


class ChainRun:
    """A plugin chain fed with made-up esmini requests."""

    def __init__(self, entries, seed=0):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'applied.tsv'
        self.chain = errors.Chain(config(entries, seed), scenarios.get('gidas_1549178'), self.path)

    def step(self, step, **target):
        return reply(self.chain.answer(message(step, **target)))

    def log(self):
        self.chain.close()
        with self.path.open(encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        self.folder.cleanup()
        return rows


class SeedScopeTests(unittest.TestCase):
    def test_each_scenario_gets_its_own_seed_unless_shared(self):
        def seeds(**extra):
            return [errors.plugin_seed(validate({'scenario': name, 'seed': 3, **extra}))
                    for name in ('gidas_1549178', 'gidas_1554254', 'gidas_1549178')]
        first, second, again = seeds()
        self.assertNotEqual(first, second)
        self.assertEqual(first, again)
        self.assertTrue(0 <= first <= 2147483647)
        self.assertEqual(seeds(seed_scope='shared'), [3, 3, 3])
        with self.assertRaises(ValueError):
            validate({'seed_scope': 'case'})

    def test_the_chain_draws_from_the_plugin_seed(self):
        # Verify reproducibility: same config and seed → identical output across two runs.
        entry = {'type': 'detection', 'miss_rate': 0.3, 'miss_mean_s': 0.2}
        for scope in ('scenario', 'shared'):
            c = validate({'scenario': 'gidas_1549178', 'errors': [entry], 'seed': 1, 'seed_scope': scope})
            def _run():
                chain = errors.Chain(c, scenarios.get('gidas_1549178'), Path(tempfile.gettempdir()) / f'seed_scope_{scope}.tsv')
                flags = [reply(chain.answer(message(s)))[0] for s in range(100)]
                chain.close()
                return flags
            self.assertEqual(_run(), _run())


class ZhuoMaPortTests(unittest.TestCase):
    """Counts from sensitivity_runs.csv of reports/aeb_markov_20261006 (commit 484675b): 200 frames, p=0.1."""

    def test_iid_matches_recorded_frames(self):
        for seed, dropped, longest in ((0, 25, 3), (1, 21, 2)):
            states = iid_frames(0.1, seed, TARGET['id'], 200)
            self.assertEqual((sum(states), longest_run(states)), (dropped, longest))

    def test_markov_matches_recorded_frames(self):
        cases = ((0.2, 0, 33, 11), (0.2, 1, 24, 13), (0.5, 0, 62, 53), (0.5, 1, 6, 6), (1.0, 0, 9, 9), (1.0, 1, 29, 29))
        for mean_s, seed, dropped, longest in cases:
            states = markov_frames(0.1, mean_s, 0.05, seed, TARGET['id'], 200)
            self.assertEqual((sum(states), longest_run(states)), (dropped, longest))

    def test_chain_parameters(self):
        enter, recover = markov_parameters(0.1, 0.5, 0.05)
        self.assertAlmostEqual(recover, 0.1)
        self.assertAlmostEqual(enter, 0.1 * 0.1 / 0.9)
        self.assertEqual(markov_parameters(0, 0.5, 0.05), (0.0, 1.0))
        with self.assertRaises(ValueError):
            markov_parameters(0.1, 0.01, 0.05)

    def test_realized_rate_and_duration_follow_settings(self):
        states = markov_frames(0.1, 0.5, 0.05, 3, TARGET['id'], 400000)
        runs = sum(1 for before, now in zip(states, states[1:]) if now and not before)
        self.assertAlmostEqual(sum(states) / len(states), 0.1, delta=0.01)
        self.assertAlmostEqual(sum(states) * 0.05 / runs, 0.5, delta=0.03)

    def test_frame_state_holds_between_frames(self):
        self.assertEqual(hold_per_step([True, False], 0.05, 0.01, 7), [True] * 5 + [False] * 2)

    def test_identification_stream_is_independent_of_detection(self):
        settings = {'miss_rate': 0.2, 'miss_model': 'markov', 'miss_mean_s': 0.5, 'sensor_period_s': 0.05,
                    'wrong_rate': 0.2, 'wrong_mean_s': 0.5}
        self.assertNotEqual(missed_steps(settings, 0, 1, DT, 1000), wrong_class_steps(settings, 0, 1, DT, 1000))


class OuTests(unittest.TestCase):
    def test_stationary_distribution_and_correlation(self):
        for interval in (0.1, 1.0):
            first, second = [], []
            for seed in range(6000):
                process = CorrelatedRangeNoise(seed, 0.5)
                first.append(process.sample(1, 0))
                second.append(process.sample(1, interval))
            self.assertAlmostEqual(statistics.mean(second), 0, delta=0.04)
            self.assertAlmostEqual(statistics.pvariance(second), 1, delta=0.06)
            self.assertAlmostEqual(statistics.correlation(first, second), math.exp(-interval / 0.5), delta=0.03)

    def test_a_second_object_does_not_change_the_first(self):
        alone, together = CorrelatedRangeNoise(42, 0.5), CorrelatedRangeNoise(42, 0.5)
        for step in range(30):
            time = step * DT
            if step >= 10:
                together.sample(2, time)
            self.assertEqual(alone.sample(1, time), together.sample(1, time))


class SettingsTests(unittest.TestCase):
    def test_registry_finds_every_plugin_and_no_helper(self):
        self.assertEqual(set(errors.all_plugins()), {'box', 'detection', 'fitted', 'identification', 'lateral', 'ou',
                                                         'size', 'template', 'velocity'})

    def test_defaults_are_filled_in(self):
        entries = config([{'type': 'detection'}, {'type': 'size', 'name': 'big', 'scale': 2}])['errors']
        self.assertEqual(entries[0], {'type': 'detection', **errors.all_plugins()['detection'].SETTINGS})
        self.assertEqual(entries[1], {'type': 'size', 'name': 'big', 'scale': 2.0, 'bias_m': 0.0})
        self.assertIsInstance(entries[1]['scale'], float)

    def test_defaults_are_neutral(self):
        detection, identification = config([{'type': 'detection'}, {'type': 'identification'}])['errors']
        self.assertFalse(any(missed_steps(detection, 0, 1, DT, 1000)))
        self.assertFalse(any(wrong_class_steps(identification, 0, 1, DT, 1000)))

    def test_rejects_bad_entries(self):
        for bad in (None, {}, [{}], [{'type': 'gauss'}], [{'type': 'size', 'nope': 1}], [{'type': 'size', 'scale': 0}],
                    [{'type': 'size', 'scale': True}], [{'type': 'size', 'scale': float('nan')}],
                    [{'type': 'detection', 'miss_model': 'gauss'}], [{'type': 'detection', 'miss_mean_s': 0.01}],
                    [{'type': 'detection', 'sensor_period_s': 0.015}], [{'type': 'detection', 'lost_target': 'hold'}],
                    [{'type': 'detection', 'lost_target_motion': 'frozen'}],
                    [{'type': 'detection', 'lost_target': 'predict', 'lost_target_distance': 'frozen_object'}],
                    [{'type': 'ou', 'zero_range_m': 100}], [{'type': 'ou', 'correlation_time_s': 0}],
                    [{'type': 'size'}, {'type': 'size'}], [{'type': 'size', 'name': 'a.b'}]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config(bad)

    def test_the_same_type_twice_with_names(self):
        entries = config([{'type': 'template', 'name': 'a', 'sigma_m': 1}, {'type': 'template', 'name': 'b'}])['errors']
        self.assertEqual([entry['name'] for entry in entries], ['a', 'b'])

    def test_old_settings_point_to_errors(self):
        for raw in ({'uncertainty': 'distance_ou_range'}, {'range_factors': {}}, {'noise_reference_mae_pct': 5.0}):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, '"errors"'):
                validate(raw)


class ChainTests(unittest.TestCase):
    def test_neutral_plugin_changes_nothing(self):
        run = ChainRun([{'type': 'size'}])
        flags, seen = run.step(0)
        run.log()
        self.assertEqual(flags, errors.SEEN)
        self.assertEqual((seen['range'], seen['x'], seen['speed'], seen['length']), (30.0, 30.0, 5.0, 4.0))

    def test_ou_adds_the_scaled_sample(self):
        run = ChainRun([{'type': 'ou', 'mae_pct': 5.0}], seed=4)
        z = unit_samples(errors.plugin_seed(config([], 4)), 0.5, TARGET['id'], DT, 20)
        sigma = 100.0 * 5.0 / 100.0 * (30.0 - 3.0) / (100.0 - 3.0) * SIGMA_PER_MAE
        for step in (0, 7, 19):
            self.assertEqual(run.step(step)[1]['range'], 30.0 + sigma * z[step])
        rows = run.log()
        self.assertEqual(float(rows[1]['ou.z']), z[7])
        self.assertEqual(float(rows[1]['raw_range_m']), 30.0 + sigma * z[7])

    def test_ou_bias_follows_the_same_distance_law(self):
        z = unit_samples(errors.plugin_seed(config([], 4)), 0.5, TARGET['id'], DT, 20)
        share = (30.0 - 3.0) / (100.0 - 3.0)
        bias_only = ChainRun([{'type': 'ou', 'mae_pct': 0.0, 'bias_pct': 5.0}], seed=4)
        both = ChainRun([{'type': 'ou', 'mae_pct': 5.0, 'bias_pct': -2.0}], seed=4)
        for step in (0, 7, 19):
            self.assertAlmostEqual(bias_only.step(step)[1]['range'], 30.0 + 5.0 * share, places=12)
            self.assertAlmostEqual(both.step(step)[1]['range'], 30.0 - 2.0 * share + 5.0 * share * SIGMA_PER_MAE * z[step],
                                   places=12)

    def test_box_length_moves_the_ends_or_the_centre(self):
        neutral = ChainRun([{'type': 'box'}])
        centre = ChainRun([{'type': 'box', 'length_scale': 1.1, 'width_scale': 0.5}])
        near_end = ChainRun([{'type': 'box', 'length_scale': 1.1, 'keep': 'near_end'}])
        shorter = ChainRun([{'type': 'box', 'length_scale': 0.8, 'keep': 'near_end'}, {'type': 'size', 'bias_m': 1.0}])
        flags, seen = neutral.step(0)
        self.assertEqual((flags, seen['range'], seen['length'], seen['width']), (errors.SEEN, 30.0, 4.0, 2.0))
        flags, seen = centre.step(0)
        self.assertEqual(flags, errors.SEEN | errors.SIZE)
        self.assertEqual((seen['range'], seen['length'], seen['width']), (30.0, 4.0 * 1.1, 1.0))
        # The end facing the ego stays at 30 - 2 m: the centre is half the new length behind it.
        flags, seen = near_end.step(0)
        self.assertEqual(flags, errors.SEEN | errors.SIZE)
        self.assertAlmostEqual(seen['range'] - seen['length'] / 2.0, 28.0, places=12)
        self.assertAlmostEqual(shorter.step(0)[1]['range'], 30.0 - 0.4 + 1.0, places=12)
        self.assertAlmostEqual(float(near_end.log()[0]['box.range_shift_m']), 0.2, places=12)
        for run in (neutral, centre, shorter):
            run.log()

    def test_identification_replaces_size_on_wrong_frames(self):
        entries = [{'type': 'identification', 'wrong_rate': 0.5, 'wrong_scale': 2.0, 'wrong_mean_s': 0.2},
                   {'type': 'size', 'bias_m': 1.0}]
        run, wrong = ChainRun(entries, seed=2), wrong_class_steps(config(entries, 2)['errors'][0], errors.plugin_seed(config(entries, 2)), 1, DT, 300)
        for step in range(300):
            self.assertEqual(run.step(step)[1]['range'], 60.0 if wrong[step] else 31.0)
        rows = run.log()
        self.assertEqual([row['class_correct'] == '0' for row in rows], wrong)
        self.assertTrue(any(wrong) and not all(wrong))

    def test_detection_hides_the_target_on_missed_steps(self):
        # reference_range_m=30 makes miss_rate(30 m) == miss_rate; easier to reason about.
        entry = {'type': 'detection', 'miss_rate': 0.3, 'miss_mean_s': 0.2, 'reference_range_m': 30.0}
        run = ChainRun([entry], seed=1)
        flags = [run.step(step)[0] for step in range(300)]
        missed = [not flag & errors.SEEN for flag in flags]
        rows = run.log()
        # Behavioral invariants: flag and log agree; some misses occur over 300 steps.
        self.assertEqual([row['valid'] == '0' for row in rows], missed)
        self.assertTrue(any(missed))

    def test_prediction_moves_the_last_range_on(self):
        # reference_range_m=30 gives miss_rate(30 m)=0.3; fixed gap keeps rate constant.
        base = {'type': 'detection', 'miss_rate': 0.3, 'miss_mean_s': 0.2, 'reference_range_m': 30.0}
        predict_entry = {**base, 'lost_target': 'predict', 'lost_target_motion': 'frozen'}
        # With lost_target='predict', missed frames still set SEEN; scan with vanish mode instead
        # to find `first` (same chain evolution since seed and label are identical).
        vanish_entry = dict(base)
        scan = ChainRun([vanish_entry], seed=0)
        had_hit, first = False, None
        for step in range(300):
            f, _ = scan.step(step, gap=30.0, speed=5.0)
            if f & errors.SEEN:
                had_hit = True
            elif had_hit:
                first = step
                break
        scan.log()
        self.assertIsNotNone(first, 'No miss found after a hit in 300 steps')
        self.assertLess(first, 150)

        # Verify prediction: same seed → same chain states; at step `first` the target is missed and
        # the plugin should return the frozen last-seen state.
        run = ChainRun([predict_entry], seed=0)
        for step in range(first):
            run.step(step, gap=30.0, speed=5.0)
        # While lost, the true target stops; the controller still gets its old speed and closing.
        flags, seen = run.step(first, gap=30.0, speed=0.0)
        self.assertEqual(flags & (errors.SEEN | errors.MOVING), errors.SEEN | errors.MOVING)
        self.assertEqual(seen['speed'], 5.0)
        # Last seen range was 30.0; ego_speed=20 target_speed=5 → closing=15 m/s; predict one dt.
        self.assertAlmostEqual(seen['range'], 30.0 - 15.0 * DT, places=9)
        self.assertEqual(run.log()[-1]['predicted'], '1')

    def test_plugins_stack_in_order_with_their_own_streams(self):
        both = ChainRun([{'type': 'template', 'name': 'a', 'sigma_m': 0.5}, {'type': 'template', 'name': 'b', 'sigma_m': 0.5}])
        only = ChainRun([{'type': 'template', 'name': 'a', 'sigma_m': 0.5}])
        for step in range(5):
            both.step(step)
            only.step(step)
        both_rows, only_rows = both.log(), only.log()
        self.assertEqual([row['a.error_m'] for row in both_rows], [row['a.error_m'] for row in only_rows])
        self.assertNotEqual(both_rows[0]['a.error_m'], both_rows[0]['b.error_m'])
        total = 30.0 + float(both_rows[0]['a.error_m']) + float(both_rows[0]['b.error_m'])
        self.assertAlmostEqual(float(both_rows[0]['raw_range_m']), total, places=12)

    def test_a_moved_position_wins_over_range(self):
        class Shift:
            def perceive(self, step, t, ego, targets):
                targets[0]['y'] = 1.0
        run = ChainRun([])
        run.chain.plugins = [('shift', Shift())]
        flags, seen = run.step(0)
        run.log()
        self.assertEqual(flags, errors.SEEN | errors.POSITION)
        self.assertEqual((seen['x'], seen['y']), (30.0, 1.0))


def fitted_file(folder, rows=(), runs=(1, 1, 1, 2, 10), p_miss=0.1, target=None):
    """A parameter file as fit-kradar writes it, with one profile "test": b 0.2 m, spread 0.5 m, 80% of it OU.
    target: the target_offset block, left out when None."""
    shape = {'cell': 'all', 'b_m': 0.2, 'sd_m': 0.5, 'sigma_ou_m': 0.5 * math.sqrt(0.8), 'tau_s': 1.0, 'p_miss': p_miss}
    profile = {'frame_period_s': 0.1, 'cells': [shape, *rows], 'miss_runs_frames': list(runs)}
    if target is not None:
        profile['target_offset'] = target
    path = Path(folder) / 'parameters.json'
    path.write_text(json.dumps({'test': profile}), encoding='utf-8')
    return str(path)


def target_at(gap):
    """A target as the chain hands it to a plugin."""
    true = dict(zip(errors.STATE, [gap, 0.0, 0.0, 0.0, 5.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0, 2.0, 1.5]))
    return {'id': 1, 'name': 'object_2', 'true': true, 'true_range': gap, 'range': gap, **true, 'seen': True,
            'class_correct': True, 'predicted': False, 'log': {}, 'last_noisy_range': gap}


class FittedTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def entry(self, **settings):
        return {'type': 'fitted', 'parameters': fitted_file(self.folder.name, **settings.pop('file', {})),
                'profile': 'test', **settings}

    def test_error_holds_for_a_frame_and_adds_up(self):
        run = ChainRun([self.entry(misses=False)], seed=3)
        ranges = [run.step(step)[1]['range'] for step in range(25)]
        rows = run.log()
        self.assertEqual(len(set(ranges[:10])), 1)
        self.assertEqual(len(set(ranges[10:20])), 1)
        self.assertNotEqual(ranges[9], ranges[10])
        row = rows[12]
        error = 0.2 + 0.5 * math.sqrt(0.8) * float(row['fitted.z']) + 0.5 * math.sqrt(0.2) * float(row['fitted.w'])
        self.assertAlmostEqual(float(row['fitted.error_m']), error, places=12)
        self.assertAlmostEqual(float(row['raw_range_m']), 30.0 + error, places=12)
        self.assertEqual(row['fitted.missed'], '')

    def test_error_and_misses_follow_the_fitted_values(self):
        settings = config([self.entry()], 1)['errors'][0]
        settings = {key: value for key, value in settings.items() if key != 'type'}
        run = SimpleNamespace(seed=1, dt_s=0.05, steps=40002, duration_s=2000.0, scenario='test', ego='object_1',
                              targets=[{'id': 1, 'name': 'object_2'}], label='fitted')
        plugin = fitted.Error(settings, run)
        error, missed = [], []
        for frame in range(20000):
            target = target_at(30.0)
            plugin.perceive(2 * frame, 0.1 * frame, {'speed': 10.0, 'length': 4.0}, [target])
            error.append(target['log']['error_m'])
            missed.append(not target['seen'])
        self.assertAlmostEqual(statistics.mean(error), 0.2, delta=0.06)
        self.assertAlmostEqual(statistics.stdev(error), 0.5, delta=0.04)
        self.assertAlmostEqual(statistics.correlation(error[:-1], error[1:]), 0.8 * math.exp(-0.1), delta=0.05)
        self.assertAlmostEqual(sum(missed) / len(missed), 0.1, delta=0.02)
        runs, length = [], 0
        for state in missed:
            if state:
                length += 1
            elif length:
                runs.append(length)
                length = 0
        self.assertEqual(set(runs[1:]), {1, 2, 10})

    def test_misses_use_the_detection_code_and_their_own_stream(self):
        file = {'p_miss': 0.4, 'runs': (3,)}
        vanish = ChainRun([self.entry(file=file)], seed=2)
        predict = ChainRun([self.entry(file=file, lost_target='predict')], seed=2)
        no_misses = ChainRun([self.entry(file=file, misses=False)], seed=2)
        flags = [(vanish.step(step)[0], predict.step(step)[0]) for step in range(400)]
        for step in range(400):
            no_misses.step(step)
        rows_vanish, rows_predict, rows_none = vanish.log(), predict.log(), no_misses.log()
        missed = [row['fitted.missed'] == '1' for row in rows_vanish]
        self.assertTrue(any(missed) and not all(missed))
        self.assertEqual([not seen & errors.SEEN for seen, _ in flags], missed)
        first_seen = missed.index(False)
        later = [step for step in range(first_seen, 400) if missed[step]]
        self.assertTrue(later)
        self.assertTrue(all(flags[step][1] & errors.SEEN and rows_predict[step]['predicted'] == '1' for step in later))
        self.assertEqual([row['fitted.error_m'] for row in rows_vanish], [row['fitted.error_m'] for row in rows_none])

    def test_range_condition_uses_the_band_of_the_true_range(self):
        bands = ({'cell': 'range 0-25 m', 'b_m': -1.0, 'sd_m': 0.0, 'p_miss': 0.0},
                 {'cell': 'range 25-45 m', 'b_m': 1.0, 'sd_m': 0.0, 'p_miss': 0.0})
        run = ChainRun([self.entry(file={'rows': bands}, condition='range')])
        for step, gap, seen in ((0, 30.0, 31.0), (1, 10.0, 9.0), (2, 100.0, 101.0)):
            self.assertAlmostEqual(run.step(step, gap=gap)[1]['range'], seen, places=12)
        run.log()

    def test_target_offset_holds_for_the_whole_run_and_replaces_b(self):
        target = {'min_frames': 20, 'offsets_m': [-1.0, 2.0], 'tau_s': 0.5, 'share_ou': 0.5,
                  'residual': {'all': {'rows': 10, 'sd_m': 0.0}}}
        seen = set()
        for seed in range(1, 30):
            run = ChainRun([self.entry(file={'target': target}, offset='target', misses=False)], seed=seed)
            ranges = {run.step(step)[1]['range'] for step in range(30)}
            rows = run.log()
            self.assertEqual(len(ranges), 1)                       # no spread left: the offset alone, all run
            offset = ranges.pop() - 30.0
            self.assertIn(round(offset, 9), (-1.0, 2.0))          # b 0.2 is not added
            self.assertAlmostEqual(float(rows[0]['fitted.offset_m']), offset, places=12)
            seen.add(round(offset, 9))
        self.assertEqual(seen, {-1.0, 2.0})

    def test_target_offset_uses_the_spread_around_the_track_means(self):
        target = {'min_frames': 20, 'offsets_m': [0.0], 'tau_s': 0.5, 'share_ou': 0.5,
                  'residual': {'all': {'rows': 10, 'sd_m': 0.3}}}
        run = ChainRun([self.entry(file={'target': target}, offset='target', misses=False)], seed=4)
        for step in range(25):
            run.step(step)
        row = run.log()[12]
        self.assertAlmostEqual(float(row['fitted.sigma_ou_m']), 0.3 * math.sqrt(0.5), places=12)
        self.assertAlmostEqual(float(row['fitted.sigma_white_m']), 0.3 * math.sqrt(0.5), places=12)
        self.assertEqual(float(row['fitted.bias_m']), 0.0)

    def test_offset_none_leaves_the_old_model(self):
        target = {'min_frames': 20, 'offsets_m': [5.0], 'tau_s': 0.5, 'share_ou': 0.5,
                  'residual': {'all': {'rows': 10, 'sd_m': 0.0}}}
        plain = ChainRun([self.entry(misses=False)], seed=3)
        with_block = ChainRun([self.entry(file={'target': target}, misses=False)], seed=3)
        self.assertEqual([plain.step(s)[1]['range'] for s in range(25)],
                         [with_block.step(s)[1]['range'] for s in range(25)])
        plain.log()
        with_block.log()

    def test_rejects_missing_file_profile_or_row(self):
        for bad in ({'parameters': str(Path(self.folder.name) / 'none.json')}, {'profile': 'other'},
                    {'condition': 'fog'}, {'condition': 'dry'}, {'lost_target_motion': 'frozen'},
                    {'offset': 'target'}, {'offset': 'per_frame'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config([{**self.entry(), **bad}])


# ---------------------------------------------------------------------------
# Helpers shared by LateralErrorTests, VelocityErrorTests, OutlierTests
# ---------------------------------------------------------------------------

def _run(steps=20, seed=0, label='test', dt_s=0.1):
    """Minimal run namespace for plugin construction (fixed seed → deterministic)."""
    return SimpleNamespace(
        seed=seed, label=label, dt_s=dt_s, steps=steps,
        targets=[{'id': 1, 'name': 'obj1'}],
    )


def _tgt(x, y, vx=0.0, vy=0.0, heading=0.0):
    """Minimal target dict for perceive() calls; ego is assumed at (0, 0)."""
    r = math.hypot(x, y)
    return {
        'id': 1, 'name': 'obj1',
        'true': {'x': x, 'y': y, 'vx': vx, 'vy': vy, 'heading': heading},
        'true_range': r,
        'x': x, 'y': y, 'vx': vx, 'vy': vy,
        'heading': heading,
        'speed': math.hypot(vx, vy),
        'log': {},
    }


_EGO = {'x': 0.0, 'y': 0.0}


# ---------------------------------------------------------------------------
# Lateral plugin tests
# ---------------------------------------------------------------------------

class LateralErrorTests(unittest.TestCase):
    def _plugin(self, steps=20, **kw):
        cfg = {'sigma_theta_deg': 0.0, 'bias_theta_deg': 0.0,
               'p_outlier': 0.0, 'noise': 'gaussian'}
        cfg.update(kw)
        return lateral.Error(cfg, _run(steps=steps))

    def test_L1_zero_sigma_no_bias_unchanged(self):
        """L1: zero sigma and bias leaves x, y unchanged within 1e-9 m."""
        plugin = self._plugin()
        tgt = _tgt(20.0, 1.5)
        plugin.perceive(0, 0.0, _EGO, [tgt])
        self.assertAlmostEqual(tgt['x'], 20.0, delta=1e-9)
        self.assertAlmostEqual(tgt['y'], 1.5, delta=1e-9)

    def test_L2_nonzero_sigma_range_unchanged(self):
        """L2: nonzero sigma changes position; range preserved to 1e-6 m (exact rotation).

        The plugin rotates the ego→target bearing by theta_total; the new position
        lies exactly on the circle of radius r centred at ego, so range is preserved
        to floating-point precision.
        """
        true_range = math.hypot(20.0, 1.5)
        plugin = self._plugin(sigma_theta_deg=2.0)
        tgt = _tgt(20.0, 1.5)
        plugin.perceive(0, 0.0, _EGO, [tgt])
        self.assertTrue(abs(tgt['x'] - 20.0) > 1e-9 or abs(tgt['y'] - 1.5) > 1e-9,
                        'sigma=2 deg should shift position')
        perceived_range = math.hypot(tgt['x'] - _EGO['x'], tgt['y'] - _EGO['y'])
        self.assertAlmostEqual(perceived_range, true_range, delta=1e-6)

    def test_L3_bias_shifts_consistently(self):
        """L3: bias_theta=1 deg produces the exact-rotation position on every step.

        Target along x-axis (phi=0).  After rotation by 1°:
            x' = r*cos(1°),  y' = r*sin(1°).
        """
        plugin = self._plugin(bias_theta_deg=1.0, sigma_theta_deg=0.0)
        r = 20.0
        x0, y0 = r, 0.0        # target along x-axis from ego at origin
        bias_rad = math.radians(1.0)
        expected_x = r * math.cos(bias_rad)
        expected_y = r * math.sin(bias_rad)
        for step in range(5):
            tgt = _tgt(x0, y0)
            plugin.perceive(step, step * 0.1, _EGO, [tgt])
            self.assertAlmostEqual(tgt['x'], expected_x, delta=1e-9,
                                   msg=f'x must equal r*cos(1°) (step {step})')
            self.assertAlmostEqual(tgt['y'], expected_y, delta=1e-9,
                                   msg=f'y must equal r*sin(1°) (step {step})')


# ---------------------------------------------------------------------------
# Velocity plugin tests
# ---------------------------------------------------------------------------

class VelocityErrorTests(unittest.TestCase):
    def _plugin(self, steps=20, dt_s=0.1, **kw):
        cfg = {
            'sigma_radial_mps': 0.0, 'sigma_tangential_mps': 0.0,
            'bias_radial_mps': 0.0, 'correlation_time_s': 1.0,
            'p_outlier': 0.0, 'noise': 'gaussian',
        }
        cfg.update(kw)
        return velocity.Error(cfg, _run(steps=steps, dt_s=dt_s))

    def test_V1_zero_sigma_zero_bias_unchanged(self):
        """V1: zero sigma and bias leaves vx, vy, speed unchanged."""
        plugin = self._plugin()
        tgt = _tgt(20.0, 1.0, vx=5.0, vy=2.0)
        plugin.perceive(0, 0.0, _EGO, [tgt])
        self.assertAlmostEqual(tgt['vx'], 5.0, delta=1e-9)
        self.assertAlmostEqual(tgt['vy'], 2.0, delta=1e-9)
        self.assertAlmostEqual(tgt['speed'], math.hypot(5.0, 2.0), delta=1e-9)

    def test_V2_ou_lag1_autocorrelation(self):
        """V2: radial OU lag-1 acf ≈ exp(-0.1/1.0) ≈ 0.905; must lie in [0.80, 0.98].

        The sample ACF of an AR(1) process has SD ≈ sqrt((1+ρ²)/n).  With ρ≈0.905
        and n=100, SD ≈ 0.14 — too noisy for the [0.80, 0.98] window.  Using
        n=500 brings SD ≈ 0.06, so the window is about ±1.7 SD: reliable.
        """
        steps = 500
        plugin = self._plugin(steps=steps, dt_s=0.1,
                              sigma_radial_mps=1.0, correlation_time_s=1.0)
        vr_errors = []
        for step in range(steps):
            tgt = _tgt(20.0, 0.0, vx=0.0, vy=0.0)
            plugin.perceive(step, step * 0.1, _EGO, [tgt])
            # target along x-axis → ur=(1,0) → perceived vx = vr_obs; true vr = 0
            vr_errors.append(tgt['vx'])

        mean_e = sum(vr_errors) / len(vr_errors)
        num = sum((vr_errors[i] - mean_e) * (vr_errors[i + 1] - mean_e)
                  for i in range(steps - 1))
        den = sum((e - mean_e) ** 2 for e in vr_errors)
        acf1 = num / den
        self.assertGreater(acf1, 0.80, msg=f'lag-1 acf = {acf1:.3f}; expected ≈ 0.905')
        self.assertLess(acf1, 0.98, msg=f'lag-1 acf = {acf1:.3f}; expected ≈ 0.905')

    def test_V3_bias_decreases_closing_speed(self):
        """V3: bias_radial=2 lowers perceived closing speed by 2 m/s (positive = less threatening).

        Sign convention: positive bias_radial_mps → vr_obs = vr_true + bias
        → target appears to close slower → controller brakes later.
        """
        plugin = self._plugin(bias_radial_mps=2.0)
        # Target approaching head-on; ur=(1,0) → vr = tgt['vx']
        tgt = _tgt(20.0, 0.0, vx=-15.0, vy=0.0)
        plugin.perceive(0, 0.0, _EGO, [tgt])
        true_closing_speed = 15.0            # = -vr_true = -(-15)
        perceived_closing_speed = -tgt['vx']  # = -vr_obs = -(vr_true + 2) = 15 - 2
        self.assertAlmostEqual(perceived_closing_speed, true_closing_speed - 2.0,
                               delta=1e-6)

    def test_V4_stationary_target_negative_bias_heading_from_velocity_vector(self):
        """V4: stationary target, bias_radial = −2 m/s → v_obs = (−2, 0) → heading = π, speed = 2.

        vr_true = 0, vr_obs = −2.  v_obs = vr_obs·u_r = (−2, 0).
        heading = atan2(0, −2) = π.  HiDrive: closing = ego_speed − 2×cos(π) = ego_speed + 2.
        """
        plugin = self._plugin(bias_radial_mps=-2.0)
        tgt = _tgt(20.0, 0.0, vx=0.0, vy=0.0, heading=0.0)
        plugin.perceive(0, 0.0, _EGO, [tgt])
        self.assertAlmostEqual(tgt['heading'], math.pi, delta=1e-9,
                               msg='heading = atan2(0, -2) = π')
        self.assertAlmostEqual(tgt['vx'], -2.0, delta=1e-9,
                               msg='vx = vr_obs × ur_x = -2')
        self.assertAlmostEqual(tgt['speed'], 2.0, delta=1e-9,
                               msg='speed = |v_obs| = 2')

    def test_V5_crossing_target_tiny_radial_error_heading_stable(self):
        """V5: cyclist at (20, 0) moving +4 m/s in y, e_r = −0.1.

        v_obs = (−0.1, 4.0) → heading = atan2(4.0, −0.1) ≈ +91.4°, speed ≈ 4.001.
        Old heading-flip code would have set heading to −90° (crossing direction reversed).
        Vector approach keeps heading near +90°.
        """
        plugin = self._plugin(bias_radial_mps=-0.1)
        tgt = _tgt(20.0, 0.0, vx=0.0, vy=4.0, heading=math.pi / 2)
        plugin.perceive(0, 0.0, _EGO, [tgt])
        expected_vx = -0.1  # vr_obs × ur_x = -0.1 × 1
        expected_vy = 4.0   # vt_obs × ut_y = 4 × 1
        self.assertAlmostEqual(tgt['vx'], expected_vx, delta=1e-9)
        self.assertAlmostEqual(tgt['vy'], expected_vy, delta=1e-9)
        self.assertAlmostEqual(tgt['speed'], math.hypot(-0.1, 4.0), delta=1e-9)
        # heading ≈ 91.4°, well within 10° of +90°; definitely not -90° (old flip behaviour)
        self.assertAlmostEqual(tgt['heading'], math.atan2(4.0, -0.1), delta=1e-9,
                               msg='heading must come from atan2(vy_obs, vx_obs)')


# ---------------------------------------------------------------------------
# Outlier / mixture tests
# ---------------------------------------------------------------------------

class OutlierTests(unittest.TestCase):
    def test_O1_p_outlier_1_all_nonzero_constant(self):
        """O1: p_outlier=1 gives nonzero, constant outlier_m across 10 steps."""
        cfg = {'sigma_theta_deg': 1.0, 'bias_theta_deg': 0.0,
               'p_outlier': 1.0, 'noise': 'mixture'}
        plugin = lateral.Error(cfg, _run(steps=10))
        outlier_ms = []
        for step in range(10):
            tgt = _tgt(20.0, 0.0)
            plugin.perceive(step, step * 0.1, _EGO, [tgt])
            outlier_ms.append(tgt['log']['outlier_m'])
        self.assertNotAlmostEqual(outlier_ms[0], 0.0, places=9,
                                  msg='p_outlier=1 should give non-zero bias')
        for i in range(1, 10):
            self.assertAlmostEqual(outlier_ms[i], outlier_ms[0], delta=1e-12,
                                   msg=f'outlier_m must be constant (step {i})')

    def test_O2_p_outlier_0_always_zero(self):
        """O2: p_outlier=0 gives outlier_m == 0.0 on every step."""
        cfg = {'sigma_theta_deg': 1.0, 'bias_theta_deg': 0.0,
               'p_outlier': 0.0, 'noise': 'mixture'}
        plugin = lateral.Error(cfg, _run(steps=10))
        for step in range(10):
            tgt = _tgt(20.0, 0.0)
            plugin.perceive(step, step * 0.1, _EGO, [tgt])
            self.assertEqual(tgt['log']['outlier_m'], 0.0,
                             msg=f'step {step}')

    def test_O3_p_outlier_002_fraction(self):
        """O3: p_outlier=0.02 across 10,000 targets gives outlier count in [100, 300]."""
        ol = TargetOutliers('o3_seed', p_outlier=0.02)
        count = sum(1 for tid in range(10_000) if ol.draw(tid) != 0.0)
        self.assertGreaterEqual(count, 100,
                                msg=f'too few outliers: {count} (expected ≈ 200)')
        self.assertLessEqual(count, 300,
                             msg=f'too many outliers: {count} (expected ≈ 200)')


if __name__ == '__main__':
    unittest.main()
