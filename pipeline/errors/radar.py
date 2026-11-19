"""Radar: SNR-based range noise and missed detections.

Replaces ou + detection with a physically coupled model. Both noise magnitude and
miss probability are derived from the same SNR each step:

    SNR = K * RCS * env_factor / R^4

RCS is estimated from the target's bounding-box length. env_factor is set by the
environment setting. Range noise follows an OU process with sigma = C1/sqrt(SNR).
Miss probability follows a sigmoid in SNR_dB; on a miss the lost-target behaviour
matches detection.py (vanish or predict).

Put this plugin after fov in the chain. Do not stack with ou or detection.
"""
import math
import random

from .ou import CorrelatedRangeNoise, SIGMA_PER_MAE

SETTINGS = {
    'environment':          'clear',
    'snr_threshold_db':     13.0,
    'tau_s':                0.5,
    'lost_target':          'vanish',
    'lost_target_motion':   'live',
    'lost_target_distance': 'frozen_difference',
}
RANGES = {
    'snr_threshold_db': (-10.0, 40.0),
    'tau_s':            (0.01, 20.0),
}
CHOICES = {
    'environment':          ('clear', 'rain', 'fog'),
    'lost_target':          ('vanish', 'predict'),
    'lost_target_motion':   ('live', 'frozen'),
    'lost_target_distance': ('frozen_difference', 'frozen_object'),
}
LOG = ('snr_db', 'sigma_m', 'noise_m', 'missed')

_ENV = {'clear': 1.0, 'rain': 0.5, 'fog': 0.2}

# Radar constant K: calibrated so a car (RCS=10 m²) at 150 m in clear conditions
# sits at the default detection threshold (SNR_threshold=13 dB ≈ 20 linear).
# K * 10 / 150^4 = 20  →  K ≈ 1.0e9
_K = 1.0e9

# Noise scale: sigma = C1 / sqrt(SNR).
# At the threshold (SNR≈20, car at ~150 m): sigma ≈ C1/4.5 ≈ 3 m.
_C1 = 14.0

# Sigmoid sharpness: Pd transitions from ~0.95 to ~0.05 over ±5 dB around the threshold.
_SHARPNESS = 3.0

# Kinematics held in predict+frozen mode (matches detection.py)
_HELD = ('speed', 'vx', 'vy', 'vz', 'ax', 'ay', 'az')


def _rcs(length):
    """Estimate RCS (m²) from target bounding-box length."""
    if length >= 6.0: return 20.0   # truck / bus
    if length >= 3.5: return 10.0   # car
    if length >= 2.0: return  2.0   # motorbike
    return 1.0                       # cyclist / bicycle / pedestrian


def check(settings, run):
    if settings['lost_target_motion'] == 'frozen' and settings['lost_target'] != 'predict':
        raise ValueError('lost_target_motion "frozen" needs lost_target "predict"')
    if settings['lost_target_distance'] == 'frozen_object' and settings['lost_target_motion'] != 'frozen':
        raise ValueError('lost_target_distance "frozen_object" needs lost_target_motion "frozen"')


class Error:
    def __init__(self, settings, run):
        self.settings  = settings
        self.env       = _ENV[settings['environment']]
        self.thr       = settings['snr_threshold_db']
        self.predict   = settings['lost_target'] == 'predict'
        self.freeze    = settings['lost_target_motion'] == 'frozen'
        self.live_ego  = settings['lost_target_distance'] == 'frozen_object'
        self.dt        = run.dt_s

        # OU noise: one pre-computed z sequence per target.
        # Seed prefix differs from ou.py ('range-ou') so streams are independent.
        ou = CorrelatedRangeNoise(f'{run.seed}:radar-ou', settings['tau_s'])
        self.z = {
            target['name']: [ou.sample(target['id'], round(k * run.dt_s, 8))
                             for k in range(run.steps)]
            for target in run.targets
        }

        # Miss draws: one uniform per step per target.
        self.u = {}
        for target in run.targets:
            stream = random.Random(f'{run.seed}:radar-miss:{target["id"]}')
            self.u[target['name']] = [stream.random() for _ in range(run.steps)]

        # Lost-target state (same structure as detection.py)
        self.last = {}

    def perceive(self, step, t, ego, targets):
        for target in targets:
            if not target['seen']:
                continue  # fov or a prior plugin already hid this target

            name, true = target['name'], target['true']
            R   = max(target['true_range'], 0.1)
            rcs = _rcs(true['length'])
            snr = _K * rcs * self.env / R ** 4

            target['snr'] = snr  # downstream plugins (identification, box) can read this

            # range noise: OU with SNR-derived sigma
            sigma = _C1 / math.sqrt(max(snr, 1e-12))
            noise = sigma * SIGMA_PER_MAE * self.z[name][step]
            target['range'] = target['range'] + noise

            # miss decision: sigmoid in SNR_dB
            snr_db = 10.0 * math.log10(max(snr, 1e-30))
            pd     = 1.0 / (1.0 + math.exp(-( snr_db - self.thr) / _SHARPNESS))
            missed = self.u[name][step] > pd

            target['log'].update(snr_db=round(snr_db, 2), sigma_m=round(sigma, 4),
                                 noise_m=round(noise, 4), missed=int(missed))

            if not missed:
                if target['range'] >= 0.0:
                    self.last[name] = {'range': target['range'],
                                       'closing': ego['speed'] - true['speed'], 'time': t,
                                       **{key: true[key] for key in _HELD}}
                continue

            # missed — vanish or predict
            if not self.predict:
                target['seen'] = False
                continue

            last = self.last.get(name)
            if last is None:
                target['seen'] = False  # never seen yet: nothing to predict from
                continue

            contact = (ego['length'] + true['length']) / 2.0
            if self.live_ego:
                last['range'] = last['range'] - (ego['speed'] - last['speed']) * (t - last['time'])
                last['time']  = t
                distance      = last['range']
            else:
                distance = last['range'] - last['closing'] * (t - last['time'])
            target['range']     = max(contact, distance)
            target['seen']      = True
            target['predicted'] = True
            if self.freeze:
                target.update({key: last[key] for key in _HELD})

    def describe(self):
        return {'calibration': 'Physics-based SNR model: K*RCS/R^4; sigma=C1/sqrt(SNR); Pd sigmoid in SNR_dB.',
                'K': _K, 'C1': _C1, 'sharpness_db': _SHARPNESS, **self.settings}
