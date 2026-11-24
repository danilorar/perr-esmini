"""Lateral (azimuth) position error: the sensor measures the bearing to the target with
Gaussian noise. The perceived bearing is rotated by theta_total; the perceived range is
left unchanged, so the new position lies exactly on the circle of radius r centred at ego.

    x' = ego_x + r * cos(phi + theta_total)
    y' = ego_y + r * sin(phi + theta_total)

Sign convention: positive bias_theta_deg increases the absolute azimuth of the target
from the ego's heading (pushes the target further off the ego's path, regardless of
which side it is on) → less threatening → controller brakes later.
For a target on the centreline the bias goes left (anti-clockwise) by default.

Two noise modes:
  gaussian  — i.i.d. N(0, sigma_theta_rad²) per frame, one random stream per target
  mixture   — same per-frame noise, plus a persistent outlier bias drawn once per
              target (probability p_outlier, N(0, (5*sigma_theta_deg)²) in degrees)
"""
import math
import random

from pipeline.errors.outliers import TargetOutliers

SETTINGS = {
    'sigma_theta_deg': 1.0,
    'bias_theta_deg': 0.0,
    'p_outlier': 0.02,
    'noise': 'gaussian',
}
RANGES = {
    'sigma_theta_deg': (0.0, 45.0),
    'bias_theta_deg': (-45.0, 45.0),
    'p_outlier': (0.0, 1.0),
}
CHOICES = {'noise': ('gaussian', 'mixture')}
LOG = ('theta_deg', 'delta_x_m', 'delta_y_m', 'outlier_m')


class Error:
    def __init__(self, settings, run):
        self.settings = settings
        self.sigma_rad = math.radians(settings['sigma_theta_deg'])
        self.bias_rad = math.radians(settings['bias_theta_deg'])
        self.noise_mode = settings['noise']

        # Pre-draw per-frame Gaussian samples for each target.
        # One independent stream per target, seeded to be reproducible.
        seed_base = f'{run.seed}:{run.label}'
        self._samples = {}
        for target in run.targets:
            tid = target['id']
            rng = random.Random(f'{seed_base}:{tid}:lateral')
            self._samples[tid] = [rng.gauss(0.0, self.sigma_rad) for _ in range(run.steps)]

        # Mixture mode: persistent outlier bias per target (in radians).
        # sigma = 5 * sigma_theta_deg in angle space — range-independent, as Danilo confirmed.
        if self.noise_mode == 'mixture':
            sigma_outlier_deg = 5.0 * settings['sigma_theta_deg']
            ol = TargetOutliers(seed_base, settings['p_outlier'])
            self._outlier_rad = {target['id']: math.radians(ol.draw(target['id']) * sigma_outlier_deg)
                                 for target in run.targets}
        else:
            self._outlier_rad = {}

    def perceive(self, step, t, ego, targets):
        for target in targets:
            r = target['true_range']
            if r < 1e-6:
                target['log'].update(theta_deg=0.0, delta_x_m=0.0, delta_y_m=0.0, outlier_m=0.0)
                continue

            tid = target['id']
            true_x, true_y = target['true']['x'], target['true']['y']
            ego_x, ego_y = ego['x'], ego['y']

            # Total angular error (radians).
            # Bias is applied in the direction that increases |azimuth from ego heading|,
            # so positive bias always pushes the target further off the ego's path.
            per_frame = self._samples[tid][step]
            outlier_rad = self._outlier_rad.get(tid, 0.0)
            phi = math.atan2(true_y - ego_y, true_x - ego_x)
            h_ego = ego.get('heading', 0.0)
            azimuth = (phi - h_ego + math.pi) % (2 * math.pi) - math.pi
            away_sign = math.copysign(1.0, azimuth) if abs(azimuth) > 1e-9 else 1.0
            theta_total = away_sign * self.bias_rad + outlier_rad + per_frame

            # Exact rotation: rotate the ego→target bearing by theta_total.
            # The new position lies on the circle of radius r centred at ego,
            # so range is preserved to floating-point precision.
            phi_new = phi + theta_total
            target['x'] = ego_x + r * math.cos(phi_new)
            target['y'] = ego_y + r * math.sin(phi_new)
            delta_x = target['x'] - true_x
            delta_y = target['y'] - true_y

            outlier_m = r * outlier_rad

            target['log'].update(
                theta_deg=math.degrees(theta_total),
                delta_x_m=delta_x,
                delta_y_m=delta_y,
                outlier_m=outlier_m,
            )

    def describe(self):
        return {
            'sigma_theta_deg': self.settings['sigma_theta_deg'],
            'bias_theta_deg': self.settings['bias_theta_deg'],
            'p_outlier': self.settings['p_outlier'],
            'noise': self.settings['noise'],
            'calibration': 'Assumed values; a sensitivity model, not measured sensor risk.',
        }
