"""Detection: in some sensor frames the target is lost.

The miss probability grows with range:

    miss_rate(r) = miss_rate_ref * (r / reference_range_m) ^ range_exponent

At the reference range the rate equals miss_rate_ref; it is clamped to [0, 0.5].
range_exponent=2 follows radar SNR ∝ r^-4 → detection probability drops, miss rate rises.

Temporal structure (burst dropouts) is preserved via a two-state Markov chain
(miss_model "markov") or independent frames ("iid"). The chain's recovery probability
(how long a dropout lasts) stays fixed; only the entry probability scales with range.
A frame's state holds for every integration step inside it.

What the controller gets on a lost step (lost_target):
    vanish    nothing: the target is hidden
    predict   the last measured range, moved on by
                  lost_target_distance "frozen_difference": (ego speed - target speed), both of the last seen step
                  lost_target_distance "frozen_object": (live ego speed - target speed of the last seen step)
              times the elapsed time, no lower than the two boxes touching. With lost_target_motion "frozen" the
              target's speed, velocity and acceleration of the last seen step are reported as well.
Put detection last, so the range it remembers includes the other errors.
"""
import random

from .frames import check_period, markov_parameters

SETTINGS = {'miss_rate': 0.0, 'miss_model': 'markov', 'miss_mean_s': 0.5, 'sensor_period_s': 0.05,
            'reference_range_m': 100.0, 'range_exponent': 2.0,
            'lost_target': 'vanish', 'lost_target_motion': 'live', 'lost_target_distance': 'frozen_difference'}
RANGES = {'miss_rate': (0, 0.5), 'miss_mean_s': (0.01, 20), 'sensor_period_s': (0.01, 1),
          'reference_range_m': (1.0, 500.0), 'range_exponent': (0.0, 6.0)}
CHOICES = {'miss_model': ('markov', 'iid'), 'lost_target': ('vanish', 'predict'), 'lost_target_motion': ('live', 'frozen'),
           'lost_target_distance': ('frozen_difference', 'frozen_object')}
LOG = ('missed',)
HELD = ('speed', 'vx', 'vy', 'vz', 'ax', 'ay', 'az')


def check(settings, run):
    if settings['lost_target_motion'] == 'frozen' and settings['lost_target'] != 'predict':
        raise ValueError('lost_target_motion "frozen" needs lost_target "predict"')
    if settings['lost_target_distance'] == 'frozen_object' and settings['lost_target_motion'] != 'frozen':
        raise ValueError('lost_target_distance "frozen_object" needs lost_target_motion "frozen"')
    check_period(settings['sensor_period_s'], settings['miss_mean_s'], run.dt_s)


class Error:
    def __init__(self, settings, run):
        self.settings = settings
        self.predict = settings['lost_target'] == 'predict'
        self.freeze = settings['lost_target_motion'] == 'frozen'
        self.live_ego = settings['lost_target_distance'] == 'frozen_object'
        self.miss_rate_ref = settings['miss_rate']
        self.ref_range_m = settings['reference_range_m']
        self.range_exp = settings['range_exponent']
        self._per_frame = round(settings['sensor_period_s'] / run.dt_s)

        # Per-target RNG and chain state; state steps dynamically in perceive().
        seed_base = f'{run.seed}:{run.label}'
        self._rng = {}
        self._chain = {}  # target name → current missed state (bool)
        for target in run.targets:
            name = target['name']
            rng = random.Random(f'{seed_base}:{target["id"]}:detection_range')
            self._rng[name] = rng
            self._chain[name] = rng.random() < self.miss_rate_ref  # stationary init at ref range

        # Optional override: fitted plugin pre-populates this per-step list to drive
        # the miss sequence externally while reusing the predict/vanish logic here.
        # Pre-allocate to run.steps with None; None means "use the dynamic chain".
        self.missed = {target['name']: [None] * run.steps for target in run.targets}

        self.last = {}

    def _miss_rate_at(self, r):
        return min(0.5, self.miss_rate_ref * (max(r, 1e-6) / self.ref_range_m) ** self.range_exp)

    def perceive(self, step, t, ego, targets):
        for target in targets:
            name, true = target['name'], target['true']
            # Use override (set by fitted plugin) if present; otherwise step the dynamic chain.
            override = self.missed[name][step] if step < len(self.missed.get(name, [])) else None
            if override is not None:
                missed = override
                self._chain[name] = missed  # keep chain state consistent
            elif step % self._per_frame == 0:
                r = target['true_range']
                p = self._miss_rate_at(r)
                rng = self._rng[name]
                if self.settings['miss_model'] == 'iid':
                    self._chain[name] = rng.random() < p
                else:
                    if p == 0.0:
                        self._chain[name] = False
                    else:
                        enter, recover = markov_parameters(p, self.settings['miss_mean_s'],
                                                           self.settings['sensor_period_s'])
                        if self._chain[name]:
                            self._chain[name] = rng.random() >= recover  # stay missed unless recovering
                        else:
                            self._chain[name] = rng.random() < enter     # enter missed state
            missed = self._chain[name]
            target['log']['missed'] = int(missed)
            if not self.predict:
                if missed:
                    target['seen'] = False
                continue
            if not missed:
                if target['seen'] and target['range'] >= 0.0:
                    self.last[name] = {'range': target['range'], 'closing': ego['speed'] - true['speed'], 'time': t,
                                       **{key: true[key] for key in HELD}}
                continue
            last = self.last.get(name)
            if last is None:
                target['seen'] = False  # never seen yet: nothing to predict from
                continue
            contact = (ego['length'] + true['length']) / 2.0
            if self.live_ego:
                # The held range stays unclamped: only the reported distance stops at contact.
                last['range'] = last['range'] - (ego['speed'] - last['speed']) * (t - last['time'])
                last['time'] = t
                distance = last['range']
            else:
                distance = last['range'] - last['closing'] * (t - last['time'])
            target['range'] = max(contact, distance)
            target['seen'] = target['predicted'] = True
            if self.freeze:
                target.update({key: last[key] for key in HELD})

    def describe(self):
        return {'frames': 'Range-dependent Markov or IID loss: miss_rate(r) = miss_rate_ref * (r/reference_range_m)^range_exponent; '
                          'entry probability scales with range, recovery probability (burst duration) stays fixed.',
                **self.settings}
