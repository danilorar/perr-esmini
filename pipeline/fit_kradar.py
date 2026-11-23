"""Fit error-model parameters from K-Radar: reference boxes against detector boxes, on test frames only.

    python -m pipeline fit-kradar <data folder> [--meta <folder>] [--detectors asf pvrcnn] [--output <folder>]
                                  [--other-data]

<data folder>: reference/kradar_P3.parquet and candidates/kradar_<detector>.parquet (the teacher's tables, not in Git:
K-Radar licence). Each table must match its sha256 in pipeline/kradar/tables.sha256, so everyone fits the same data;
--other-data skips that check.
<meta folder>: default pipeline/kradar/meta. K-Radar's split lists train.txt and test.txt (github.com/kaist-avelab/K-Radar,
resources/split) and sequences.csv (sequence, road_type, time, weather, frames), Table 5 of the K-Radar paper
(arXiv 2206.08171).
Needs pandas and pyarrow on top of pipeline/requirements.txt. At the end the new parameters.json is compared with
pipeline/kradar/parameters.json, the shared fit that the fitted plugin reads by default.

Every detector box is paired with at most one reference box of the same frame: nearest centres first, at most GATE_M
apart. The lead is the nearest reference vehicle ahead in the ego lane (|y| < LANE_M); its rows count when it is a
Sedan. The model for the lead, in metres:

    range error e(t) = b + sigma_ou * z(t) + sigma_white * w(t)
        b        mean error
        z        unit OU process with correlation time tau
        w        independent from frame to frame (0.1 s)
    misses: share of lead frames with no paired box (p_miss) and mean length of a run of missed frames (t_miss_s),
        the two settings of the detection plugin's Markov chain; the table also gives how many runs last 0.5, 1
        and 2 s or more, because the data has more one-frame misses and more long losses than that chain

b, the spread and the misses are fitted per cell: range band (all weather) and weather group (all ranges). tau and the
white share come from the autocovariance of e along each lead's track (lags up to MAX_LAG frames). A constant offset
per target and an OU with a tau of several seconds look the same over these lags, so the OU part holds both.
Sizes: detector length and width over the reference's, per class, for every reference vehicle in the detector area.

parameters.json also lists the lengths of the lead's miss runs, which the fitted error plugin draws from. A run cut off
by the end of a track or of a block of test frames counts with the length seen, so long losses are if anything short.
It also lists each lead track's mean error and the spread around it (target_offset), for the plugin's offset "target":
the log is a narrow spread plus a few targets read too far for their whole track, which one Gaussian does not give.

Check: fit on half of the recordings of each weather group (A) and compare with the other half (B).
"""
from pathlib import Path
import hashlib
import json
import math
import subprocess

import numpy as np

KRADAR = Path(__file__).resolve().parent / 'kradar'
DT_S = 0.1
AREA_X_M = (0.0, 72.0)
AREA_Y_M = 16.0
LANE_M = 2.0
GATE_M = 3.0
GHOST_CLEAR_M = 5.0
BANDS_M = (0.0, 25.0, 45.0, 72.0)
MAX_LAG = 30
LONG_TRACK = 20
CLASSES = ('Sedan', 'BusOrTruck')
WEATHER_GROUP = {'normal': 'normal', 'overcast': 'normal', 'rain': 'rain', 'sleet': 'rain', 'fog': 'fog',
                 'light snow': 'snow', 'heavy snow': 'snow'}
# Added to a detector's x and y. PV-RCNN++ boxes sit 2.55 m behind and 0.31 m left of the reference: median over
# pairs beyond 20 m, the same in every range band and with no rotation, so a shift between two sensor frames (the
# data's README names only the 0.7 m in z, which this fit does not use).
FRAME_SHIFT_M = {'pvrcnn': (2.55, -0.31)}


def read_split(meta):
    """recording_id, frame_idx and part (train or test) for every labelled frame."""
    import pandas as pd
    sequences = pd.read_csv(Path(meta) / 'sequences.csv').set_index('sequence')
    rows = []
    for part in ('train', 'test'):
        for line in (Path(meta) / f'{part}.txt').read_text().split():
            sequence, name = line.split(',')
            rows.append((int(sequence), name, int(name.split('.')[0].split('_')[1]), part))
    table = pd.DataFrame(rows, columns=['sequence', 'name', 'lidar', 'part']).sort_values(['sequence', 'name'])
    out = []
    for sequence, group in table.groupby('sequence'):
        frames = int(sequences.loc[sequence, 'frames'])
        if group.lidar.max() - group.lidar.min() + 1 == frames:
            index = group.lidar - group.lidar.min()       # one frame may be in neither list
        elif len(group) == frames:
            index = np.arange(len(group))                  # label numbers with gaps
        else:
            raise ValueError(f'sequence {sequence}: cannot match {len(group)} split entries to {frames} frames')
        out.append(pd.DataFrame({'recording_id': f'kradar_{sequence:03d}', 'frame_idx': np.asarray(index),
                                 'part': group.part.values}))
    return pd.concat(out, ignore_index=True)


def read_weather(meta):
    import pandas as pd
    sequences = pd.read_csv(Path(meta) / 'sequences.csv')
    return {f'kradar_{s:03d}': WEATHER_GROUP[w] for s, w in zip(sequences.sequence, sequences.weather)}


def assign(ax, ay, bx, by, gate):
    """Nearest pairs first, each box used once, pairs closer than gate. Returns index arrays into a and b."""
    distance = np.hypot(ax[:, None] - bx[None, :], ay[:, None] - by[None, :])
    used_a, used_b, pairs = set(), set(), []
    for flat in np.argsort(distance, axis=None, kind='stable'):
        i, j = divmod(int(flat), distance.shape[1])
        if distance[i, j] >= gate:
            break
        if i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            pairs.append((i, j))
    return np.array([p[0] for p in pairs], dtype=int), np.array([p[1] for p in pairs], dtype=int)


def pair(ref, det, gate=GATE_M):
    """Reference rows with the paired detector box (columns det_*; hit False when none) and the unpaired boxes."""
    ref = ref.reset_index(drop=True)
    det = det.reset_index(drop=True)
    columns = {name: np.full(len(ref), np.nan) for name in ('det_x', 'det_y', 'det_length', 'det_width')}
    det_used = np.zeros(len(det), dtype=bool)
    det_frames = det.groupby(['recording_id', 'frame_idx']).indices
    for key, rows in ref.groupby(['recording_id', 'frame_idx']).indices.items():
        boxes = det_frames.get(key)
        if boxes is None:
            continue
        i, j = assign(ref.x_est.values[rows], ref.y_est.values[rows], det.x.values[boxes], det.y.values[boxes], gate)
        for name, source in (('det_x', 'x'), ('det_y', 'y'), ('det_length', 'length'), ('det_width', 'width')):
            columns[name][rows[i]] = det[source].values[boxes[j]]
        det_used[boxes[j]] = True
    out = ref.assign(**columns)
    out['hit'] = out.det_x.notna()
    out['error_m'] = np.hypot(out.det_x, out.det_y) - np.hypot(out.x_est, out.y_est)
    return out, det[~det_used]


def mark_lead(ref):
    """The nearest reference vehicle ahead in the ego lane of each frame."""
    lane = ref[(ref.x_est > 0) & (ref.y_est.abs() < LANE_M)]
    lead = lane.loc[lane.groupby(['recording_id', 'frame_idx']).x_est.idxmin()]
    return ref.index.isin(lead.index)


def band_of(range_m):
    import pandas as pd
    labels = [f'{a:g}-{b:g}' for a, b in zip(BANDS_M[:-1], BANDS_M[1:])]
    return pd.cut(range_m, BANDS_M, labels=labels).astype(str)


def autocovariance(rows):
    """Mean of u(t) * u(t + k) over pairs inside one track, lags 0..MAX_LAG. Rows: hits only, with column u."""
    base = rows[['track_id', 'frame_idx', 'u']]
    c, n = [], []
    for lag in range(MAX_LAG + 1):
        both = base.merge(base.assign(frame_idx=base.frame_idx - lag), on=['track_id', 'frame_idx'])
        c.append(float((both.u_x * both.u_y).mean()))
        n.append(len(both))
    return np.arange(MAX_LAG + 1), np.array(c), np.array(n, dtype=float)


def fit_time_structure(lags, c, n):
    """c(0) = ou + white, c(k >= 1) = ou * exp(-k dt / tau), weighted by the pair counts. Returns tau and shares."""
    best = None
    for tau in np.geomspace(0.05, 30.0, 281):
        x = np.exp(-lags[1:] * DT_S / tau)
        ou = max(0.0, float(np.sum(n[1:] * x * c[1:]) / np.sum(n[1:] * x * x)))
        cost = float(np.sum(n[1:] * (ou * x - c[1:]) ** 2))
        if best is None or cost < best[0]:
            best = (cost, tau, ou)
    _, tau, ou = best
    ou = min(ou, c[0])
    return {'tau_s': tau, 'share_ou': ou / c[0], 'share_white': 1 - ou / c[0]}


def miss_stretches(rows):
    """Lengths in frames of the runs of consecutive misses along each track."""
    lengths = []
    for _, g in rows.sort_values(['track_id', 'frame_idx']).groupby('track_id'):
        run, last = 0, None
        for frame, hit in zip(g.frame_idx.values, g.hit.values):
            if run and (hit or frame != last + 1):
                lengths.append(run)
                run = 0
            if not hit:
                run += 1
            last = frame
        if run:
            lengths.append(run)
    return np.array(lengths)


def cell(rows):
    """Parameters of one cell of lead rows."""
    hits = rows[rows.hit]
    e = hits.error_m
    hits = hits.assign(u=e - e.mean())
    shape = fit_time_structure(*autocovariance(hits))
    sd = float(e.std())
    stretches = miss_stretches(rows) * DT_S
    per_track = hits.groupby('track_id').error_m.agg(['mean', 'size'])
    long = per_track[per_track['size'] >= LONG_TRACK]['mean']
    return {'rows': len(rows), 'tracks': rows.track_id.nunique(), 'recordings': rows.recording_id.nunique(),
            'b_m': float(e.mean()), 'sd_m': sd, 'robust_sd_m': float(1.4826 * (e - e.median()).abs().median()),
            'q05_m': float(e.quantile(0.05)), 'q95_m': float(e.quantile(0.95)),
            'sd_pct_of_range': 100 * sd / float(rows.range_m.median()),
            'sigma_ou_m': sd * math.sqrt(shape['share_ou']), 'sigma_white_m': sd * math.sqrt(shape['share_white']),
            'tau_s': shape['tau_s'], 'p_miss': float((~rows.hit).mean()),
            't_miss_s': float(stretches.mean()) if len(stretches) else math.nan,
            'misses_0.5s_up': float(np.mean(stretches >= 0.5 - 1e-9)) if len(stretches) else math.nan,
            'misses_1s_up': float(np.mean(stretches >= 1 - 1e-9)) if len(stretches) else math.nan,
            'misses_2s_up': float(np.mean(stretches >= 2 - 1e-9)) if len(stretches) else math.nan,
            'targets_over_1m_far': float((long > 1).mean()), 'targets_over_1m_near': float((long < -1).mean())}


def target_offsets(lead):
    """Each lead track's mean error (tracks with LONG_TRACK+ paired frames) and the error left around it.

    The log's errors are a narrow spread plus a few targets read too far for their whole track; one Gaussian with the
    pooled spread is wider in the middle and gives almost none of those targets. The fitted plugin with offset
    "target" draws one of these means per target for the whole run and adds the rest as OU + white noise, with the
    spread per cell (the error around each track's mean) and tau from all rows."""
    hits = lead[lead.hit]
    hits = hits[hits.groupby('track_id').error_m.transform('size') >= LONG_TRACK]
    hits = hits.assign(u=hits.error_m - hits.groupby('track_id').error_m.transform('mean'))
    shape = fit_time_structure(*autocovariance(hits))

    def residual(rows):
        return {'rows': len(rows), 'sd_m': float(np.sqrt((rows.u ** 2).mean()))}

    cells = {'all': residual(hits)}
    cells.update({f'range {band} m': residual(g) for band, g in hits.groupby('band') if '-' in band})
    cells.update({f'weather {w}': residual(g) for w, g in hits.groupby('group')})
    return {'min_frames': LONG_TRACK, 'offsets_m': sorted(float(v) for v in hits.groupby('track_id').error_m.mean()),
            'tau_s': shape['tau_s'], 'share_ou': shape['share_ou'], 'residual': cells}


def tables(lead):
    import pandas as pd
    rows = [{'cell': 'all', **cell(lead)}]
    rows += [{'cell': f'range {band} m', **cell(g)} for band, g in sorted(lead.groupby('band'), key=lambda kv: float(kv[0].split('-')[0]))]
    rows += [{'cell': f'weather {w}', **cell(g)} for w, g in lead.groupby('group')]
    return pd.DataFrame(rows)


def check(lead):
    """Fit on half of the recordings of each weather group (A), compare with the other half (B)."""
    import pandas as pd
    recordings = lead[['recording_id', 'group']].drop_duplicates().sort_values('recording_id')
    half = {rec: i % 2 for _, g in recordings.groupby('group') for i, rec in enumerate(g.recording_id)}
    lead = lead.assign(half=lead.recording_id.map(half))
    a, b = lead[lead.half == 0], lead[lead.half == 1]
    table_a, table_b = tables(a), tables(b)
    both = table_a.merge(table_b, on='cell', suffixes=('_A', '_B'))
    inside = []
    for _, row in both.iterrows():
        rows = b[b.hit]
        if row.cell.startswith('range'):
            rows = rows[rows.band == row.cell.split()[1]]
        elif row.cell.startswith('weather'):
            rows = rows[rows.group == row.cell.split()[1]]
        low, high = row.b_m_A - 1.645 * row.sd_m_A, row.b_m_A + 1.645 * row.sd_m_A
        inside.append(float(rows.error_m.between(low, high).mean()))
    both['B_inside_A_90pct'] = inside
    # correlation over time of B against A's model, all rows
    hits_b = b[b.hit].assign(u=lambda d: d.error_m - d.error_m.mean())
    lags, c, _ = autocovariance(hits_b)
    shape = table_a.set_index('cell').loc['all']
    share_ou = shape.sigma_ou_m ** 2 / shape.sd_m ** 2
    model = np.where(lags == 0, 1.0, share_ou * np.exp(-lags * DT_S / shape.tau_s))
    correlation = pd.DataFrame({'lag_s': lags * DT_S, 'B_data': c / c[0], 'A_model': model})
    # miss runs of B against the geometric law of a Markov chain with A's mean run length
    stretches = miss_stretches(b)
    leave = DT_S / shape.t_miss_s
    stretch = pd.DataFrame({'at_least_s': [0.2, 0.5, 1.0, 2.0],
                            'B_data': [float(np.mean(stretches >= m)) for m in (2, 5, 10, 20)],
                            'A_model': [(1 - leave) ** (m - 1) for m in (2, 5, 10, 20)]})
    return both, correlation, stretch


def size_table(pairs):
    import pandas as pd
    rows = []
    for name, g in pairs[pairs.hit].groupby('class_name'):
        length = g.det_length / g.length_est
        width = g.det_width / g.width_est
        per_track = g.assign(lr=length).groupby('track_id').lr.agg(['mean', 'size'])
        # targets roughly ahead and aligned: how far the centre moves per metre of length error
        ahead = g[(g.x_est > 0) & (np.cos(g.yaw_est).abs() > 0.9)]
        dl = ahead.det_length - ahead.length_est
        dx = ahead.det_x - ahead.x_est
        rows.append({'class': name, 'boxes': len(g), 'tracks': g.track_id.nunique(),
                     'length_scale_mean': length.mean(), 'length_scale_sd': length.std(),
                     'length_scale_sd_between_targets': per_track[per_track['size'] >= LONG_TRACK]['mean'].std(),
                     'width_scale_mean': width.mean(), 'width_scale_sd': width.std(),
                     'length_error_sd_m': (g.det_length - g.length_est).std(),
                     'centre_shift_per_length_error': float(np.cov(dx, dl)[0, 1] / np.var(dl, ddof=1))})
    return pd.DataFrame(rows)


def ghosts(unpaired, reference, test_frames):
    """Unpaired detector boxes in the ego lane with no reference object of any class within GHOST_CLEAR_M."""
    lane = unpaired[unpaired.x.between(*AREA_X_M) & (unpaired.y.abs() < LANE_M)].reset_index(drop=True)
    near = np.zeros(len(lane), dtype=bool)
    ref_frames = reference.groupby(['recording_id', 'frame_idx']).indices
    for key, rows in lane.groupby(['recording_id', 'frame_idx']).indices.items():
        objects = ref_frames.get(key)
        if objects is None:
            continue
        d = np.hypot(lane.x.values[rows][:, None] - reference.x_est.values[objects][None, :],
                     lane.y.values[rows][:, None] - reference.y_est.values[objects][None, :])
        near[rows] = d.min(axis=1) < GHOST_CLEAR_M
    clear = lane[~near]
    seconds = test_frames * DT_S
    return {'unpaired_in_lane_per_s': len(lane) / seconds, 'nothing_within_5m_per_s': len(clear) / seconds,
            'nothing_within_5m_conf_0.5_per_s': int((clear.confidence >= 0.5).sum()) / seconds}


def load(data, meta, detector):
    import pandas as pd
    reference = pd.read_parquet(Path(data) / 'reference' / 'kradar_P3.parquet')
    det = pd.read_parquet(Path(data) / 'candidates' / f'kradar_{detector}.parquet')
    split = read_split(meta)
    test = split[split.part == 'test'][['recording_id', 'frame_idx']]
    reference = reference.merge(test, on=['recording_id', 'frame_idx']).reset_index(drop=True)
    det = det.merge(test, on=['recording_id', 'frame_idx'])
    shift = FRAME_SHIFT_M.get(detector, (0.0, 0.0))
    det = det.assign(x=det.x + shift[0], y=det.y + shift[1])
    vehicles = reference[reference.class_name.isin(CLASSES) & reference.x_est.between(*AREA_X_M)
                         & (reference.y_est.abs() < AREA_Y_M)]
    pairs, unpaired = pair(vehicles, det)
    pairs['group'] = pairs.recording_id.map(read_weather(meta))
    pairs['range_m'] = np.hypot(pairs.x_est, pairs.y_est)
    pairs['band'] = band_of(pairs.range_m)
    pairs['lead'] = mark_lead(pairs)
    return pairs, unpaired, reference, len(test), shift


def fit_detector(data, meta, detector):
    pairs, unpaired, reference, test_frames, shift = load(data, meta, detector)
    lead = pairs[pairs.lead & (pairs.class_name == 'Sedan')]
    both, correlation, stretch = check(lead)
    return {'table': tables(lead), 'sizes': size_table(pairs), 'ghosts': ghosts(unpaired, reference, test_frames),
            'check': both, 'correlation': correlation, 'stretch': stretch, 'shift': shift, 'lead_rows': len(lead),
            'vehicle_rows': len(pairs), 'vehicle_hit': float(pairs.hit.mean()),
            'miss_runs_frames': sorted(int(n) for n in miss_stretches(lead)), 'target_offset': target_offsets(lead)}


def markdown(frame, digits=3):
    frame = frame.copy()
    for column in frame.columns:
        if frame[column].dtype.kind == 'f':
            frame[column] = frame[column].map(lambda v: '' if v != v else f'{v:.{digits}g}')
    head = '| ' + ' | '.join(map(str, frame.columns)) + ' |'
    rule = '|' + '---|' * len(frame.columns)
    body = ['| ' + ' | '.join(map(str, row)) + ' |' for row in frame.itertuples(index=False)]
    return '\n'.join([head, rule, *body])


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def read_sums(path):
    """{relative path: sha256} from a file in sha256sum format."""
    sums = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.strip().lstrip('*')] = digest
    return sums


def table_sums(data, names, sums_file=None):
    """sha256 of each table (paths relative to data). With sums_file, every table must match the sum listed there."""
    expected = read_sums(sums_file) if sums_file else {}
    sums, differ = {}, []
    for name in names:
        path = Path(data) / name
        if not path.is_file():
            raise ValueError(f'{path} not found')
        sums[name] = sha256(path)
        if sums_file and sums[name] != expected.get(name):
            differ.append(name)
    if differ:
        raise ValueError(f'{", ".join(differ)} differ from {Path(sums_file).name}, so the fit would not match the shared '
                         'parameters; add --other-data to fit them anyway')
    return sums


def largest_difference(a, b):
    """Largest absolute difference between the numbers of two parameter files; None when anything else differs."""
    if isinstance(a, dict) and isinstance(b, dict):
        parts = [largest_difference(a[key], b[key]) for key in a] if a.keys() == b.keys() else [None]
    elif isinstance(a, list) and isinstance(b, list):
        parts = [largest_difference(x, y) for x, y in zip(a, b)] if len(a) == len(b) else [None]
    elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (a, b)):
        if a != a or b != b:                      # NaN
            return 0.0 if a != a and b != b else math.inf
        return abs(a - b)
    else:
        return 0.0 if a == b else None
    return None if None in parts else max(parts, default=0.0)


def compare_with_shared(path, shared=KRADAR / 'parameters.json'):
    """One line per detector: is the new fit the same as the shared file?"""
    name = f'pipeline/kradar/{Path(shared).name}'
    new = json.loads(Path(path).read_text(encoding='utf-8'))
    old = json.loads(Path(shared).read_text(encoding='utf-8')) if Path(shared).is_file() else {}
    lines = []
    for detector, profile in new.items():
        if detector not in old:
            lines.append(f'{detector}: not in {name}')
            continue
        difference = largest_difference(profile, old[detector])
        if difference is not None and difference < 1e-9:
            lines.append(f'{detector}: same as {name} (largest difference {difference:.1g})')
        else:
            size = 'layout' if difference is None else f'largest difference {difference:.3g}'
            lines.append(f'{detector}: differs from {name} ({size})')
    return '\n'.join(lines)


def git_state():
    root = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.run(['git', 'rev-parse', '--short=10', 'HEAD'], cwd=root, capture_output=True,
                                text=True).stdout.strip()
        status = subprocess.run(['git', 'status', '--porcelain', '--', 'pipeline'], cwd=root, capture_output=True,
                                text=True).stdout.splitlines()
        return commit, [line[3:] for line in status if line.strip()]
    except OSError:
        return 'unknown', []


def run(data, meta, detectors, output, check=True):
    meta = Path(meta) if meta else KRADAR / 'meta'
    names = ['reference/kradar_P3.parquet', *(f'candidates/kradar_{d}.parquet' for d in detectors)]
    sums = table_sums(data, names, KRADAR / 'tables.sha256' if check else None)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    commit, changed = git_state()
    lines = ['# K-Radar fit', '',
             f'Code: commit {commit}' + (f', changed: {", ".join(changed)}' if changed else ', no local changes'),
             'Data (sha256): ' + ', '.join(f'{Path(n).name} {s[:12]}' for n, s in sums.items())
             + ('' if check else ' (not checked against pipeline/kradar/tables.sha256)'),
             'Test frames only. Lead = nearest reference vehicle ahead with |y| < 2 m; rows kept when it is a Sedan.',
             'targets_over_1m_far: share of lead tracks with 20+ paired frames whose mean error is above +1 m.', '']
    parameters = {}
    columns = ['cell', 'rows', 'tracks', 'recordings', 'b_m', 'sd_m', 'robust_sd_m', 'q05_m', 'q95_m', 'sd_pct_of_range',
               'sigma_ou_m', 'sigma_white_m', 'tau_s', 'p_miss', 't_miss_s', 'misses_0.5s_up', 'misses_1s_up',
               'misses_2s_up', 'targets_over_1m_far', 'targets_over_1m_near']
    for detector in detectors:
        result = fit_detector(data, meta, detector)
        folder = output / detector
        folder.mkdir(exist_ok=True)
        result['table'].to_csv(folder / 'parameters.csv', index=False)
        result['sizes'].to_csv(folder / 'sizes.csv', index=False)
        result['check'].to_csv(folder / 'check_halves.csv', index=False)
        result['correlation'].to_csv(folder / 'check_correlation.csv', index=False)
        result['stretch'].to_csv(folder / 'check_miss_stretches.csv', index=False)
        parameters[detector] = {'frame_period_s': DT_S, 'frame_shift_m': result['shift'],
                                'cells': result['table'].to_dict('records'),
                                'miss_runs_frames': result['miss_runs_frames'],
                                'sizes': result['sizes'].to_dict('records'), 'ghosts': result['ghosts'],
                                'target_offset': result['target_offset']}
        offset = result['target_offset']
        spread = ', '.join(f'{name} {cell["sd_m"]:.3f}' for name, cell in offset['residual'].items())
        halves = result['check'][['cell', 'rows_A', 'rows_B', 'b_m_A', 'b_m_B', 'sd_m_A', 'sd_m_B', 'tau_s_A', 'tau_s_B',
                                  'p_miss_A', 'p_miss_B', 't_miss_s_A', 't_miss_s_B', 'B_inside_A_90pct']]
        g = result['ghosts']
        lines += [f'## {detector}', '',
                  f'Frame shift added to x, y: {result["shift"]} m. Reference vehicles in the area (test frames): '
                  f'{result["vehicle_rows"]}, paired {result["vehicle_hit"]:.3f}. Lead rows: {result["lead_rows"]}.', '',
                  '### Lead: distance error and misses', '', markdown(result['table'][columns]), '',
                  '### Lead: whole-track offsets (fitted plugin, offset "target")', '',
                  f'Mean error of each of the {len(offset["offsets_m"])} lead tracks with {offset["min_frames"]}+ '
                  f'paired frames, m: ' + ', '.join(f'{v:.2f}' for v in offset['offsets_m']) + '.', '',
                  f'Error around each track\'s mean: sd {spread} m; tau {offset["tau_s"]:.2f} s, '
                  f'OU share of the variance {offset["share_ou"]:.2f}.', '',
                  '### Sizes per class', '', markdown(result['sizes']), '',
                  f'Unpaired boxes in the ego lane: {g["unpaired_in_lane_per_s"]:.3f} per second; with no reference '
                  f'object within 5 m: {g["nothing_within_5m_per_s"]:.3f} per second '
                  f'({g["nothing_within_5m_conf_0.5_per_s"]:.3f} with confidence >= 0.5).', '',
                  '### Check: half A against half B of the recordings', '', markdown(halves), '',
                  markdown(result['correlation'].iloc[[1, 2, 5, 10, 20, 30]]), '', markdown(result['stretch']), '']
    (output / 'parameters.json').write_text(json.dumps(parameters, indent=1, default=float), encoding='utf-8')
    (output / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    return output / 'summary.md'
