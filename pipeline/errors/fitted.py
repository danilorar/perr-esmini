"""Fitted: range error and missed frames with parameters fitted from a paired log, not assumed.

Reads a file as `python -m pipeline fit-kradar` writes it (parameters; default pipeline/kradar/parameters.json, the
shared fit of ASF and PV-RCNN++, in Git) and uses one profile in it (profile: a detector of that file, such as "asf" or "pvrcnn"). Per sensor frame of
the log (frame_period_s there, 0.1 s) and per target:

    range += b + sigma_ou * z + sigma_white * w
        z   unit OU process with the fitted correlation time tau, one step per frame
        w   independent N(0, 1) per frame
    missed frames: from a seen frame a miss starts with probability enter; its length in frames is drawn from the
        miss runs of the log; enter = p_miss / ((1 - p_miss) * mean run), so the long-run share is p_miss and the mean
        run is t_miss_s, as in the detection plugin's Markov chain; only the spread of run lengths comes from the log.
        The first frame is missed with probability p_miss, for a remaining length drawn as in a running miss.

condition picks the row of the file: "all" (every lead row), "range" (the row of the range band holding the true range,
looked up every frame; below or above the bands, the nearest band) or a weather group (normal, rain, fog, snow).
tau and how the spread splits into OU and white always come from the "all" row; the chosen row gives b, the spread and
p_miss. The miss runs are pooled over all rows.

A missed frame is handled by the detection plugin's code with lost_target, lost_target_motion and
lost_target_distance, after the range error, so the remembered range includes it. Put this plugin last, as detection,
and do not stack it with ou or detection. range_error and misses switch the two parts on and off; each has its own
random stream, so switching one off leaves the other unchanged.
"""
import hashlib
import json
import math
from pathlib import Path
import random

from . import detection

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = {'parameters': 'pipeline/kradar/parameters.json', 'profile': '', 'condition': 'all',
            'range_error': True, 'misses': True, 'lost_target': 'vanish', 'lost_target_motion': 'live',
            'lost_target_distance': 'frozen_difference'}
LOST = ('lost_target', 'lost_target_motion', 'lost_target_distance')
CHOICES = {'condition': ('all', 'range', 'normal', 'rain', 'fog', 'snow'), **{key: detection.CHOICES[key] for key in LOST}}
LOG = ('bias_m', 'sigma_ou_m', 'sigma_white_m', 'z', 'w', 'error_m', 'missed')


def parameter_path(settings):
    path = Path(settings['parameters'])
    return path if path.is_absolute() else ROOT / path


def load(settings):
    """The chosen profile as plain numbers: rows [(low_m, high_m, row)], shape, miss runs, frame period."""
    path = parameter_path(settings)
    if not path.is_file():
        raise ValueError(f'{path} not found; run "python -m pipeline fit-kradar" first')
    profiles = json.loads(path.read_text(encoding='utf-8'))
    if settings['profile'] not in profiles:
        raise ValueError(f'profile must be one of {", ".join(profiles)}')
    profile = profiles[settings['profile']]
    cells = {cell['cell']: cell for cell in profile['cells']}
    shape = cells['all']
    share_ou = (shape['sigma_ou_m'] / shape['sd_m']) ** 2
    runs = profile['miss_runs_frames']
    if not runs or min(runs) < 1:
        raise ValueError(f'{path}: profile {settings["profile"]} has no miss runs')
    mean_run = sum(runs) / len(runs)
    condition = settings['condition']
    if condition == 'all':
        chosen = [(-math.inf, math.inf, shape)]
    elif condition == 'range':
        chosen = []
        for key, cell in cells.items():
            if key.startswith('range '):
                low, high = (float(value) for value in key.split()[1].split('-'))
                chosen.append((low, high, cell))
        chosen.sort(key=lambda item: item[0])
    else:
        chosen = [(-math.inf, math.inf, cells.get(f'weather {condition}'))]
    rows = []
    for low, high, cell in chosen:
        if cell is None or any(not math.isfinite(cell[key]) for key in ('b_m', 'sd_m', 'p_miss')):
            raise ValueError(f'{path}: profile {settings["profile"]} has no complete row for condition {condition}')
        p = cell['p_miss']
        enter = p / ((1.0 - p) * mean_run) if p < 1 else 1.0
        if enter > 1:
            raise ValueError(f'{path}: p_miss {p} with a mean miss run of {mean_run} frames needs enter > 1')
        rows.append((low, high, {'cell': cell['cell'], 'b_m': cell['b_m'], 'p_miss': p, 'enter': enter,
                                 'sigma_ou_m': cell['sd_m'] * math.sqrt(share_ou),
                                 'sigma_white_m': cell['sd_m'] * math.sqrt(1.0 - share_ou)}))
    return {'path': path, 'rows': rows, 'tau_s': shape['tau_s'], 'share_ou': share_ou, 'runs': runs,
            'mean_run': mean_run, 'period_s': profile['frame_period_s']}


def detection_settings(settings):
    """Settings for the detection plugin's code: no misses of its own, the lost-target handling of this entry."""
    return {**detection.SETTINGS, **{key: settings[key] for key in LOST}}


def check(settings, run):
    fit = load(settings)
    ratio = fit['period_s'] / run.dt_s
    if abs(ratio - round(ratio)) > 1e-9:
        raise ValueError(f'the frame period {fit["period_s"]} s must be a whole number of time steps')
    detection.check(detection_settings(settings), run)


class Error:
    def __init__(self, settings, run):
        self.settings = settings
        self.fit = load(settings)
        self.per_frame = round(self.fit['period_s'] / run.dt_s)
        frames = run.steps // self.per_frame + 1
        rho = math.exp(-self.fit['period_s'] / self.fit['tau_s'])
        self.z, self.w, self.miss = {}, {}, {}
        for target in run.targets:
            stream = random.Random(f'{run.seed}:{run.label}:{target["id"]}:range')
            z = [stream.gauss(0.0, 1.0)]
            for _ in range(1, frames):
                z.append(rho * z[-1] + math.sqrt(1.0 - rho * rho) * stream.gauss(0.0, 1.0))
            self.z[target['name']] = z
            self.w[target['name']] = [stream.gauss(0.0, 1.0) for _ in range(frames)]
            self.miss[target['name']] = {'random': random.Random(f'{run.seed}:{run.label}:{target["id"]}:miss'),
                                         'frame': -1, 'left': 0}
        # Remaining length of a miss already running at the start: P(k) proportional to the runs of k frames or more.
        longest = max(self.fit['runs'])
        self.residual = [sum(1 for n in self.fit['runs'] if n >= k) for k in range(1, longest + 1)]
        self.detection = detection.Error(detection_settings(settings), run) if settings['misses'] else None

    def row(self, true_range):
        rows = self.fit['rows']
        for low, high, row in rows:
            if true_range < high:
                return row
        return rows[-1][2]

    def advance(self, state, frame, row):
        """Move a target's miss state on to `frame`; left = missed frames still to come, this one included."""
        while state['frame'] < frame:
            draw = state['random']
            if state['frame'] < 0:
                if draw.random() < row['p_miss']:
                    state['left'] = draw.choices(range(1, len(self.residual) + 1), weights=self.residual)[0]
            elif state['left'] > 0:
                state['left'] -= 1
            elif draw.random() < row['enter']:
                state['left'] = draw.choice(self.fit['runs'])
            state['frame'] += 1

    def perceive(self, step, t, ego, targets):
        frame = step // self.per_frame
        for target in targets:
            name = target['name']
            row = self.row(target['true_range'])
            if self.settings['range_error']:
                z, w = self.z[name][frame], self.w[name][frame]
                error = row['b_m'] + row['sigma_ou_m'] * z + row['sigma_white_m'] * w
                target['range'] += error
                target['log'].update(bias_m=row['b_m'], sigma_ou_m=row['sigma_ou_m'],
                                     sigma_white_m=row['sigma_white_m'], z=z, w=w, error_m=error)
            if self.detection is not None:
                state = self.miss[name]
                self.advance(state, frame, row)
                # The detection code reads its missed flag per step from this list.
                self.detection.missed[name][step] = state['left'] > 0
        if self.detection is not None:
            self.detection.perceive(step, t, ego, targets)

    def describe(self):
        digest = hashlib.sha256(self.fit['path'].read_bytes()).hexdigest()[:12]
        return {'calibration': 'Fitted from a paired log (python -m pipeline fit-kradar), not assumed values.',
                'parameters_sha256': digest, 'tau_s': self.fit['tau_s'], 'share_ou': self.fit['share_ou'],
                'mean_miss_run_frames': self.fit['mean_run'], 'frame_period_s': self.fit['period_s'],
                'rows': [{'low_m': low if math.isfinite(low) else None, 'high_m': high if math.isfinite(high) else None,
                          **row} for low, high, row in self.fit['rows']],
                **self.settings}
