"""Velocity: radar velocity errors — correlated OU noise on radial (Doppler) and
tangential (poorly observed) speed components, with optional per-target outlier biases.

Radial speed (along the line of sight, good Doppler coverage) gets OU noise plus a
configurable bias.  Tangential speed (perpendicular, estimated from successive
detections or ignored) gets OU noise with no bias — a persistent tangential bias would
look like steady lateral drift, which is unrealistic.

Sign convention: positive bias_radial_mps makes the target appear to close slower
(vr_obs > vr_true for an approaching target) → controller brakes later.
Positive = less threatening, consistent with ou.py's bias_pct and lateral.py's bias_theta_deg.

noise='gaussian'  : OU noise only
noise='mixture'   : OU noise + per-target persistent outlier bias (whole track)
"""
import math
import random

from pipeline.errors.outliers import TargetOutliers

SETTINGS = {
    'sigma_radial_mps': 0.5,
    'sigma_tangential_mps': 2.0,
    'bias_radial_mps': 0.0,
    'correlation_time_s': 0.5,
    'p_outlier': 0.02,
    'noise': 'gaussian',
}
RANGES = {
    'sigma_radial_mps': (0.0, 50.0),
    'sigma_tangential_mps': (0.0, 50.0),
    'bias_radial_mps': (-20.0, 20.0),
    'correlation_time_s': (0.01, 20.0),
    'p_outlier': (0.0, 1.0),
}
CHOICES = {'noise': ('gaussian', 'mixture')}
LOG = ('vr_error_mps', 'vt_error_mps', 'outlier_r_mps', 'outlier_t_mps')


def _ou_samples(seed_string, tau_s, dt_s, steps):
    """Pre-compute `steps` unit-variance OU samples for one stream.

    Transition: z_next = exp(-dt/tau)*z + sqrt(1-exp(-2*dt/tau))*N(0,1)
    The process starts at a draw from N(0,1) so it is stationary from step 0.
    """
    rng = random.Random(seed_string)
    z = rng.gauss(0.0, 1.0)
    rho = math.exp(-dt_s / tau_s)
    spread = math.sqrt(1.0 - rho * rho)   # = sqrt(1 - exp(-2*dt/tau))
    samples = [z]
    for _ in range(steps - 1):
        z = rho * z + spread * rng.gauss(0.0, 1.0)
        samples.append(z)
    return samples


class Error:
    def __init__(self, settings, run):
        self.settings = settings
        self.sigma_r = settings['sigma_radial_mps']
        self.sigma_t = settings['sigma_tangential_mps']
        self.bias_r = settings['bias_radial_mps']
        self.noise = settings['noise']
        tau = settings['correlation_time_s']

        # Pre-compute unit-variance OU samples for every target on both axes.
        self.ou_r = {}
        self.ou_t = {}
        for target in run.targets:
            tid = target['id']
            seed_r = f'{run.seed}:{run.label}:{tid}:vel_radial'
            seed_t = f'{run.seed}:{run.label}:{tid}:vel_tangential'
            self.ou_r[target['name']] = _ou_samples(seed_r, tau, run.dt_s, run.steps)
            self.ou_t[target['name']] = _ou_samples(seed_t, tau, run.dt_s, run.steps)

        # Mixture: pre-draw per-target persistent outlier biases (whole track).
        if self.noise == 'mixture':
            seed_string = f'{run.seed}:{run.label}'
            self._ol_r = TargetOutliers(seed_string + ':radial', settings['p_outlier'],
                                        5.0 * self.sigma_r)
            self._ol_t = TargetOutliers(seed_string + ':tangential', settings['p_outlier'],
                                        5.0 * self.sigma_t)

    def perceive(self, step, t, ego, targets):
        for target in targets:
            true = target['true']

            # Radial / tangential unit vectors pointing from ego to target.
            dx = true['x'] - ego['x']
            dy = true['y'] - ego['y']
            r = max(target['true_range'], 1e-6)
            ur_x, ur_y = dx / r, dy / r    # radial: ego → target
            ut_x, ut_y = -ur_y, ur_x       # tangential: 90° left of radial

            # True velocity projected onto each axis.
            vr_true = true['vx'] * ur_x + true['vy'] * ur_y
            vt_true = true['vx'] * ut_x + true['vy'] * ut_y

            # OU noise (unit samples scaled by sigma).
            vr_noise = self.sigma_r * self.ou_r[target['name']][step]
            vt_noise = self.sigma_t * self.ou_t[target['name']][step]

            # Outlier bias (zero unless noise='mixture').
            if self.noise == 'mixture':
                outlier_r = self._ol_r.draw(target['id'])
                outlier_t = self._ol_t.draw(target['id'])
            else:
                outlier_r = 0.0
                outlier_t = 0.0

            # Observed radial and tangential components.
            # bias_r is added: positive bias makes target appear to close slower
            # (vr_obs > vr_true for an approaching target → less threatening).
            vr_obs = vr_true + self.bias_r + outlier_r + vr_noise
            vt_obs = vt_true + outlier_t + vt_noise

            # Reconstruct Cartesian velocity and scalar speed; leave vz, ax, ay, az unchanged.
            target['vx'] = vr_obs * ur_x + vt_obs * ut_x
            target['vy'] = vr_obs * ur_y + vt_obs * ut_y
            target['speed'] = math.hypot(target['vx'], target['vy'])

            target['log'].update(
                vr_error_mps=vr_obs - vr_true,
                vt_error_mps=vt_obs - vt_true,
                outlier_r_mps=outlier_r,
                outlier_t_mps=outlier_t,
            )

    def describe(self):
        return {
            **self.settings,
            'calibration': 'Assumed values; a sensitivity model, not measured sensor risk.',
            'transition': 'z_next = exp(-dt/tau)*z + sqrt(1-exp(-2*dt/tau))*N(0,1), one stream per target per axis',
        }
