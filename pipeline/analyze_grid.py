"""Summarise a finished grid: per-scenario × group mean min_gap, brake_delay, ΔTTC, crash rate.

Usage:
    python -m pipeline analyze-grid output/grids/step6_ccr [--csv results.csv]

Reads every summary.json under <grid>/runs/, recomputes TTC metrics from the compressed
per-step files (corrected formula), computes delays relative to the baseline group for each
scenario, and prints the table.  For velocity_on groups, appends +/− based on outlier sign.

ΔTTC sign: positive = perceived TTC > true TTC = controller thinks it has more time = brakes
later = dangerous.  Positive vr_error (target appears to move away) gives positive ΔTTC.
For stationary targets BOTH outlier signs give the same positive ΔTTC (sign does not matter;
see docs for derivation).  For moving targets the sign matters.
"""
import csv
import gzip
import json
import math
import sys
from pathlib import Path


def _float(value, default=None):
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _load_step_at(run_dir, target_t, tol=0.006):
    """Return (perc_row, ego_row, metrics_row) closest to target_t, or None each."""
    run_dir = Path(run_dir)
    t0 = float(target_t)

    def _closest(path, delimiter=','):
        best, best_dt = None, tol
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt') as f:
            for row in csv.DictReader(f, delimiter=delimiter):
                try:
                    dt = abs(float(row['time_s']) - t0)
                except (ValueError, KeyError):
                    continue
                if dt < best_dt:
                    best, best_dt = row, dt
        return best

    perc = _closest(run_dir / 'perception_applied.tsv.gz', delimiter='\t') \
        if (run_dir / 'perception_applied.tsv.gz').exists() else None
    ego = _closest(run_dir / 'ego.csv.gz') if (run_dir / 'ego.csv.gz').exists() else None
    met = _closest(run_dir / 'metrics.csv.gz') if (run_dir / 'metrics.csv.gz').exists() else None
    return perc, ego, met


def _ttc_from_steps(run_dir, t):
    """Recompute (ttc_true, ttc_perceived, delta_ttc, outlier_r_mps) at time t.

    Uses the corrected closing-speed formula:
        closing_perceived = ego_speed − |vr_true + vr_error|
    where vr_true ≈ ego_speed − closing_true (collinear approximation).
    Returns (None, None, None, 0.0) if data are missing.
    """
    if t is None:
        return None, None, None, 0.0
    perc, ego_r, met = _load_step_at(run_dir, t)

    ego_speed = _float(ego_r.get('speed_mps')) if ego_r else None
    gap = _float(met.get('minimum_gap_m')) if met else None
    ttc_true = _float(met.get('ttc_s')) if met else None

    if ego_speed is None or gap is None:
        return ttc_true, None, None, 0.0

    outlier_r = _float(perc.get('velocity.outlier_r_mps'), 0.0) if perc else 0.0

    if perc is None or ego_speed < 1e-3:
        return ttc_true, ttc_true, 0.0, outlier_r

    raw_range = _float(perc.get('raw_range_m'))
    true_range = _float(perc.get('true_range_m'))
    vr_error = _float(perc.get('velocity.vr_error_mps'), 0.0)

    if raw_range is None or true_range is None:
        return ttc_true, None, None, outlier_r

    # Perceived gap: adjust for range error.
    perceived_gap = max(raw_range - (true_range - gap), 0.0)

    # True closing speed from metrics TTC and gap; fall back to ego_speed (stationary target).
    if ttc_true and ttc_true > 1e-6 and gap > 0:
        true_closing = gap / ttc_true
    else:
        true_closing = ego_speed  # stationary target approximation

    # After velocity.py heading-flip fix: closing_perceived = closing_true − vr_error.
    # Positive vr_error → target appears slower → later braking.
    # Negative vr_error → heading flipped → target appears to approach → earlier braking.
    p_close = true_closing - (vr_error or 0.0)
    # If ≤ 0 the error makes the target appear to recede: TTC undefined.
    if p_close <= 0:
        return ttc_true, None, None, outlier_r
    perceived_closing = max(p_close, 1e-6)

    ttc_perceived = perceived_gap / perceived_closing
    delta_ttc = ttc_perceived - ttc_true if ttc_true is not None else None
    return ttc_true, ttc_perceived, delta_ttc, outlier_r


def _group_from_name(run_id):
    """Infer group from run folder name (scenario__group[__key=val...]__seed<n>)."""
    parts = run_id.split('__')
    if len(parts) < 2:
        return 'unknown'
    group = parts[1]
    levels = [p for p in parts[2:] if '=' in p]
    return (group + '__' + '__'.join(levels)) if levels else group


def load_runs(grid_dir, recompute_ttc=True):
    """Load all completed runs; recompute TTC metrics from step files when requested."""
    runs_dir = Path(grid_dir) / 'runs'
    if not runs_dir.is_dir():
        sys.exit(f'No runs/ folder in {grid_dir}')
    rows = []
    total = sum(1 for d in runs_dir.iterdir() if (d / 'summary.json').is_file())
    done = 0
    for d in sorted(runs_dir.iterdir()):
        summary_path = d / 'summary.json'
        config_path = d / 'config.json'
        if not summary_path.is_file():
            continue
        with summary_path.open(encoding='utf-8') as f:
            s = json.load(f)
        if s.get('status') not in ('completed', 'completed_with_warnings'):
            continue
        config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else s.get('config', {})
        done += 1
        if done % 100 == 0:
            print(f'  loading {done}/{total}...', flush=True)

        fb_t = _float(s.get('first_brake_time_s'))
        emgcy_t = _float(s.get('first_emergency_brake_time_s'))

        if recompute_ttc:
            fb_ttc_true, fb_ttc_perc, fb_delta, fb_outlier = _ttc_from_steps(d, fb_t)
            em_ttc_true, em_ttc_perc, em_delta, _ = _ttc_from_steps(d, emgcy_t)
        else:
            fb_ttc_true = _float(s.get('brake_ttc_true_s'))
            fb_ttc_perc = _float(s.get('brake_ttc_perceived_s'))
            fb_delta = _float(s.get('brake_delta_ttc_s'))
            fb_outlier = _float(s.get('brake_outlier_r_mps'), 0.0)
            em_ttc_true = _float(s.get('emgcy_ttc_true_s'))
            em_ttc_perc = _float(s.get('emgcy_ttc_perceived_s'))
            em_delta = _float(s.get('emgcy_delta_ttc_s'))

        rows.append(dict(
            run_id=d.name,
            run_dir=str(d),
            scenario=config.get('scenario', ''),
            group=_group_from_name(d.name),
            seed=config.get('seed', 0),
            collision=bool(s.get('collision')),
            impact_speed_kph=_float(s.get('impact_speed_kph')),
            minimum_gap_m=_float(s.get('minimum_gap_m')),
            first_brake_time_s=fb_t,
            first_emergency_brake_time_s=emgcy_t,
            brake_ttc_true_s=fb_ttc_true,
            brake_ttc_perceived_s=fb_ttc_perc,
            brake_delta_ttc_s=fb_delta,
            brake_outlier_r_mps=fb_outlier,
            emgcy_ttc_true_s=em_ttc_true,
            emgcy_ttc_perceived_s=em_ttc_perc,
            emgcy_delta_ttc_s=em_delta,
        ))
    return rows


def _mean(values):
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return sum(finite) / len(finite) if finite else None


def _fmt(v, decimals=2):
    return '—' if v is None else f'{v:.{decimals}f}'


def analyze(grid_dir, csv_out=None, no_split=False):
    print('Loading runs (recomputing ΔTTC from step files)...')
    rows = load_runs(grid_dir, recompute_ttc=True)
    if not rows:
        sys.exit('No completed runs found.')

    # Baseline metrics per scenario.
    baseline_brake, baseline_emgcy, baseline_gap = {}, {}, {}
    for r in rows:
        if r['group'] == 'baseline':
            baseline_brake[r['scenario']] = r['first_brake_time_s']
            baseline_emgcy[r['scenario']] = r['first_emergency_brake_time_s']
            baseline_gap[r['scenario']] = r['minimum_gap_m']

    for r in rows:
        base_b = baseline_brake.get(r['scenario'])
        base_e = baseline_emgcy.get(r['scenario'])
        fb = r['first_brake_time_s']
        fe = r['first_emergency_brake_time_s']
        r['brake_delay_s'] = (fb - base_b) if (fb is not None and base_b is not None) else None
        r['emgcy_delay_s'] = (fe - base_e) if (fe is not None and base_e is not None) else None
        r['baseline_gap_m'] = baseline_gap.get(r['scenario'])

    # For velocity_on groups: append + or − based on outlier sign (unless suppressed).
    for r in rows:
        g = r['group']
        if not no_split and 'velocity_on' in g:
            outlier = r['brake_outlier_r_mps']
            if outlier is not None:
                g = g + ('+' if outlier >= 0 else '-')
        r['eff_group'] = g

    # Collect (scenario, eff_group) in encounter order.
    seen = {}
    for r in rows:
        key = (r['scenario'], r['eff_group'])
        seen.setdefault(key, []).append(r)

    # Print first brake table.
    col_w = [28, 30, 5, 7, 7, 7, 7, 7]
    hdr = ['Scenario', 'Group', 'N', 'Crash%', 'BasGap', 'MinGap', 'Delay', 'ΔTTC@1st']
    _print_table(seen, hdr, col_w,
                 lambda rs: (rs[0]['baseline_gap_m'],
                             _mean([r['minimum_gap_m'] for r in rs]),
                             _mean([r['brake_delay_s'] for r in rs]),
                             _mean([r['brake_delta_ttc_s'] for r in rs])))

    # Print emergency brake table (only rows where ≥1 run fired emergency brake).
    seen_emgcy = {k: v for k, v in seen.items() if any(r['emgcy_delay_s'] is not None for r in v)}
    if seen_emgcy:
        print('\n--- Emergency brake (< −4 m/s²) ---')
        hdr2 = ['Scenario', 'Group', 'N_emgcy', 'Crash%', 'BasGap', 'MinGap', 'EmgcyDelay', 'ΔTTC@emgcy']
        col_w2 = [28, 30, 8, 7, 7, 7, 10, 10]
        _print_table(seen_emgcy, hdr2, col_w2,
                     lambda rs: (rs[0]['baseline_gap_m'],
                                 _mean([r['minimum_gap_m'] for r in rs]),
                                 _mean([r['emgcy_delay_s'] for r in rs if r['emgcy_delay_s'] is not None]),
                                 _mean([r['emgcy_delta_ttc_s'] for r in rs])))

    if csv_out:
        table_rows = []
        for (scenario, group), group_rows in seen.items():
            n = len(group_rows)
            table_rows.append(dict(
                scenario=scenario, group=group, n=n,
                crash_pct=100.0 * sum(r['collision'] for r in group_rows) / n,
                mean_minimum_gap_m=_mean([r['minimum_gap_m'] for r in group_rows]),
                mean_brake_delay_s=_mean([r['brake_delay_s'] for r in group_rows]),
                mean_brake_delta_ttc_s=_mean([r['brake_delta_ttc_s'] for r in group_rows]),
                mean_emgcy_delay_s=_mean([r['emgcy_delay_s'] for r in group_rows]),
                mean_emgcy_delta_ttc_s=_mean([r['emgcy_delta_ttc_s'] for r in group_rows]),
            ))
        with open(csv_out, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(table_rows[0].keys()))
            writer.writeheader()
            writer.writerows(table_rows)
        print(f'\nTable written to {csv_out}')

    return seen


def _print_table(seen, header, col_w, row_fn):
    sep = '  '.join(f'{h:{w}}' for h, w in zip(header, col_w))
    print()
    print(sep)
    print('-' * len(sep))
    last_scenario = None
    for (scenario, group), group_rows in seen.items():
        if scenario != last_scenario:
            if last_scenario is not None:
                print()
            last_scenario = scenario
        n = len(group_rows)
        crash_pct = 100.0 * sum(r['collision'] for r in group_rows) / n
        values = row_fn(group_rows)
        cells = [scenario, group, str(n), f'{crash_pct:.0f}%'] + [_fmt(v) for v in values]
        print('  '.join(f'{c:{w}}' for c, w in zip(cells, col_w)))
    print()
