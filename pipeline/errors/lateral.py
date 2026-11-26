"""Lateral (azimuth) position error: the sensor measures the bearing to the target with
Gaussian noise. The perceived bearing is rotated by theta_total; the perceived range is
left unchanged, so the new position lies exactly on the circle of radius r centred at ego.

    x' = ego_x + r * cos(phi + theta_total)
    y' = ego_y + r * sin(phi + theta_total)

Angular noise scales with range (beam-width-limited radar + SNR degradation at distance):

    sigma_theta(r) = sigma_theta_deg * max(0, r - zero_range_m) / (reference_range_m - zero_range_m)

At r = reference_range_m the noise equals sigma_theta_deg; below zero_range_m (blind zone)
it is zero; between the two it grows linearly. Position uncertainty therefore scales as
r * sigma_theta(r), which grows roughly as r² at typical operational ranges.

Sign convention: positive bias_theta_deg increases the absolute azimuth of the target
from the ego's heading (pushes the target further off the ego's path, regardless of
which side it is on) → less threatening → controller brakes later.
For a target on the centreline the bias goes left (anti-clockwise) by default.

Two noise modes:
  gaussian  — i.i.d. N(0, sigma_theta(r)²) per frame, one random stream per target
  mixture   — same per-frame noise, plus a persistent outlier bias drawn once per
              target (probability p_outlier, amplitude 5 * sigma_theta(r) at current range)
"""
import math
import random

from pipeline.errors.outliers import TargetOutliers

SETTINGS = {
    'sigma_theta_deg': 1.0,
    'reference_range_m': 100.0,
    'zero_range_m': 0.0,
    'bias_theta_deg': 0.0,
    'bias_m': 0.0,
    'p_outlier': 0.02,
    'noise': 'gaussian',
}
RANGES = {
    'sigma_theta_deg': (0.0, 45.0),
    'reference_range_m': (1.0, 500.0),
    'zero_range_m': (0.0, 499.0),
    'bias_theta_deg': (-45.0, 45.0),
    'bias_m': (-20.0, 20.0),
    'p_outlier': (0.0, 1.0),
}
CHOICES = {'noise': ('gaussian', 'mixture')}
LOG = ('theta_deg', 'delta_x_m', 'delta_y_m', 'outlier_m')


def check(settings, run):
    if settings['reference_range_m'] <= settings['zero_range_m']:
        raise ValueError('reference_range_m must be greater than zero_range_m')


class Error:
    def __init__(self, settings, run):
        self.settings = settings
        self.sigma_rad_ref = math.radians(settings['sigma_theta_deg'])  # at reference_range_m
        self.ref_range_m = settings.get('reference_range_m', SETTINGS['reference_range_m'])
        self.zero_range_m = settings.get('zero_range_m', SETTINGS['zero_range_m'])
        self.bias_rad = math.radians(settings['bias_theta_deg'])
        self.bias_m = settings.get('bias_m', 0.0)
        self.noise_mode = settings['noise']

        # Pre-draw unit-normal samples per target; scaled by sigma_theta(r) in perceive().
        seed_base = f'{run.seed}:{run.label}'
        self._samples = {}
        for target in run.targets:
            tid = target['id']
            rng = random.Random(f'{seed_base}:{tid}:lateral')
            self._samples[tid] = [rng.gauss(0.0, 1.0) for _ in range(run.steps)]

        # Mixture mode: persistent outlier per target stored as a z-score.
        # Actual offset = z * 5 * sigma_theta(r_current) — scales with range like the OU noise.
        if self.noise_mode == 'mixture':
            ol = TargetOutliers(seed_base, settings['p_outlier'])
            self._outlier_z = {target['id']: ol.draw(target['id']) * 5.0
                               for target in run.targets}
        else:
            self._outlier_z = {}

    def _sigma_at(self, r):
        """Angular noise sigma at range r (radians)."""
        span = self.ref_range_m - self.zero_range_m
        return self.sigma_rad_ref * max(0.0, r - self.zero_range_m) / span

    def perceive(self, step, t, ego, targets):
        for target in targets:
            r = target['true_range']
            if r < 1e-6:
                target['log'].update(theta_deg=0.0, delta_x_m=0.0, delta_y_m=0.0, outlier_m=0.0)
                continue

            tid = target['id']
            true_x, true_y = target['true']['x'], target['true']['y']
            ego_x, ego_y = ego['x'], ego['y']

            sigma_r = self._sigma_at(r)
            per_frame = self._samples[tid][step] * sigma_r
            outlier_rad = self._outlier_z.get(tid, 0.0) * sigma_r  # z * 5 * sigma(r)

            # Total angular error (radians).
            # Bias is applied in the direction that increases |azimuth from ego heading|,
            # so positive bias always pushes the target further off the ego's path.
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

            # Fixed-metre lateral offset (bias_m): shifts target by a constant distance
            # perpendicular to the line of sight, in the "away from path" direction.
            # Equivalent angle grows at close range, so it is a pessimistic test near impact.
            if self.bias_m:
                perp_x = -math.sin(phi_new) * away_sign
                perp_y = math.cos(phi_new) * away_sign
                target['x'] += self.bias_m * perp_x
                target['y'] += self.bias_m * perp_y
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
            'reference_range_m': self.settings['reference_range_m'],
            'zero_range_m': self.settings['zero_range_m'],
            'bias_theta_deg': self.settings['bias_theta_deg'],
            'bias_m': self.settings.get('bias_m', 0.0),
            'p_outlier': self.settings['p_outlier'],
            'noise': self.settings['noise'],
            'calibration': 'Assumed values; a sensitivity model, not measured sensor risk.',
            'distance_law': 'sigma_theta(r) = sigma_theta_deg * max(0, r - zero_range_m) / (reference_range_m - zero_range_m)',
        }
