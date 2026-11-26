"""OU: a temporally correlated range error (Ornstein-Uhlenbeck) that grows with distance.

    mean absolute error = reference_range_m * mae_pct / 100 * max(0, r - zero_range_m) / (reference_range_m - zero_range_m)
    bias                = reference_range_m * bias_pct / 100 * max(0, r - zero_range_m) / (reference_range_m - zero_range_m)
    range += bias + mean absolute error * sqrt(pi / 2) * z,   z: unit OU process with correlation time correlation_time_s

r is the true range. bias_pct > 0 reads the target too far, < 0 too near; it follows the same distance law, so
mae_pct = bias_pct gives a random and a constant error of the same mean size. With a bias, mae_pct is the size of the
random part only. The distance law and correlation time are assumptions for sensitivity studies, not
calibrated sensor values.

noise='mixture': in addition to the per-frame OU noise, each target draws a persistent whole-track z-score once,
then each step the outlier offset is z * 5 * sigma(r_current). Using the current range means the outlier scales
with the same distance law as the OU noise (not fixed at reference_range_m). With p_outlier=1 and 10% MAE at
30 m the typical |outlier| is a few metres; at the reference range it matches the K-Radar fitted offset.
"""
import math
import random

from pipeline.errors.outliers import TargetOutliers

SETTINGS = {'mae_pct': 5.0, 'bias_pct': 0.0, 'correlation_time_s': 0.5, 'zero_range_m': 3.0,
            'reference_range_m': 100.0, 'p_outlier': 0.02, 'noise': 'gaussian'}
RANGES = {'mae_pct': (0, 100), 'bias_pct': (-100, 100), 'correlation_time_s': (0.01, 20), 'zero_range_m': (0, 499),
          'reference_range_m': (1, 500), 'p_outlier': (0.0, 1.0)}
CHOICES = {'noise': ('gaussian', 'mixture')}
LOG = ('z', 'sigma_m', 'error_m', 'outlier_m')
SIGMA_PER_MAE = math.sqrt(math.pi / 2.0)


class CorrelatedRangeNoise:
    """Unit-variance OU process per object, sampled at observation times.

    Turlej (Electronics 2023, 12, 71), p. 6: temporally correlated perception.
    Yang et al. (JAIF 2020, 15(2)), p. 93, eqs. (3), (4), (7): exact discrete Gauss-Markov
    transition and stationary variance normalization.
    """

    def __init__(self, seed, tau_s):
        self.seed, self.tau_s = seed, tau_s
        self.states = {}
        self.streams = {}

    def sample(self, object_id, time_s):
        previous = self.states.get(object_id)
        if previous is None:
            # One independent stream per object: unrelated objects cannot change this object's errors.
            rng = random.Random(f'{self.seed}:range-ou:{object_id}')
            self.streams[object_id] = rng
            z = rng.gauss(0, 1)
        else:
            last_time, z = previous
            elapsed = max(0.0, time_s - last_time)
            if elapsed > 0:
                rho = math.exp(-elapsed / self.tau_s)
                z = rho * z + math.sqrt(-math.expm1(-2 * elapsed / self.tau_s)) * self.streams[object_id].gauss(0, 1)
        self.states[object_id] = (time_s, z)
        return z


def unit_samples(seed, tau_s, object_id, dt_s, steps):
    noise = CorrelatedRangeNoise(seed, tau_s)
    return [noise.sample(object_id, round(k * dt_s, 8)) for k in range(steps)]


def check(settings, run):
    if settings['reference_range_m'] <= settings['zero_range_m']:
        raise ValueError('reference_range_m must be greater than zero_range_m')


class Error:
    def __init__(self, settings, run):
        self.settings = settings
        self.pct, self.zero, self.reference = settings['mae_pct'], settings['zero_range_m'], settings['reference_range_m']
        self.bias = settings['bias_pct']
        self.z = {target['name']: unit_samples(run.seed, settings['correlation_time_s'], target['id'], run.dt_s, run.steps)
                  for target in run.targets}

        # Mixture: per-target z-score drawn once; outlier_m = z * 5 * sigma(r_current) in perceive().
        # Using current range (not reference) so outlier scales with the distance law.
        if settings.get('noise', 'gaussian') == 'mixture':
            ol = TargetOutliers(f'{run.seed}:{run.label}:range', settings.get('p_outlier', 0.02))
            self._outlier_z = {target['id']: ol.draw(target['id']) for target in run.targets}
        else:
            self._outlier_z = {}

    def perceive(self, step, t, ego, targets):
        for target in targets:
            r = target['true_range']
            mae = self.reference * self.pct / 100.0 * max(0.0, r - self.zero) / (self.reference - self.zero)
            sigma = mae * SIGMA_PER_MAE
            z = self.z[target['name']][step]
            error = sigma * z
            if self.bias:  # skipped at 0, so runs without a bias stay identical to the ones before bias_pct existed
                error = self.reference * self.bias / 100.0 * max(0.0, r - self.zero) / (self.reference - self.zero) + error
            outlier_m = self._outlier_z.get(target['id'], 0.0) * 5.0 * sigma
            # Clamp to 0.1 m: a large negative outlier must not make the target disappear
            # (negative range hides it in Chain.flags); instead the target appears very close
            # and the controller emergency-brakes. Without the clamp, 5×sigma outliers at
            # large initial ranges (sigma≈8m at 10% MAE, 70m) produced range < 0 → valid=0.
            target['range'] = max(0.1, target['range'] + error + outlier_m)
            target['log'].update(z=z, sigma_m=sigma, error_m=error, outlier_m=outlier_m)

    def describe(self):
        return {'transition': 'z_next = exp(-dt/tau) * z + sqrt(1 - exp(-2*dt/tau)) * N(0,1), from N(0,1), one stream per object',
                'calibration': 'Assumed values; a sensitivity model, not measured sensor risk.', **self.settings}
