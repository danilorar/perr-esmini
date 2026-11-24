"""Summarise a finished grid: per-scenario × group mean min_gap, brake_delay, ΔTTC, crash rate.

Usage:
    python -m pipeline analyze-grid output/grids/step6_ccr [--csv results.csv]

Reads every summary.json under <grid>/runs/, computes brake_delay relative to the baseline
group for each scenario, splits velocity_on groups by outlier sign, and prints the table.
"""
import csv
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


def load_runs(grid_dir):
    runs_dir = Path(grid_dir) / 'runs'
    if not runs_dir.is_dir():
        sys.exit(f'No runs/ folder in {grid_dir}')
    rows = []
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
        rows.append(dict(
            run_id=d.name,
            scenario=config.get('scenario', ''),
            group=s.get('group', _group_from_name(d.name, config)),
            seed=config.get('seed', 0),
            collision=bool(s.get('collision')),
            impact_speed_kph=_float(s.get('impact_speed_kph')),
            minimum_gap_m=_float(s.get('minimum_gap_m')),
            first_brake_time_s=_float(s.get('first_brake_time_s')),
            first_emergency_brake_time_s=_float(s.get('first_emergency_brake_time_s')),
            brake_ttc_true_s=_float(s.get('brake_ttc_true_s')),
            brake_ttc_perceived_s=_float(s.get('brake_ttc_perceived_s')),
            brake_delta_ttc_s=_float(s.get('brake_delta_ttc_s')),
            brake_outlier_r_mps=_float(s.get('brake_outlier_r_mps')),
        ))
    return rows


def _group_from_name(run_id, config):
    """Infer group from run folder name (scenario__group[__key=val...]__seed<n>)."""
    parts = run_id.split('__')
    if len(parts) < 2:
        return 'unknown'
    group = parts[1]
    # Include any level values (parts containing '=', before the seed part).
    levels = [p for p in parts[2:] if '=' in p]
    return (group + '__' + '__'.join(levels)) if levels else group


def _mean(values):
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return sum(finite) / len(finite) if finite else None


def _fmt(v, decimals=2):
    if v is None:
        return '—'
    return f'{v:.{decimals}f}'


def analyze(grid_dir, csv_out=None):
    rows = load_runs(grid_dir)
    if not rows:
        sys.exit('No completed runs found.')

    # Baseline first_brake per scenario (for delay computation).
    baseline_brake = {}
    for r in rows:
        if r['group'] == 'baseline':
            baseline_brake[r['scenario']] = r['first_brake_time_s']

    # Augment with brake_delay.
    for r in rows:
        base = baseline_brake.get(r['scenario'])
        fb = r['first_brake_time_s']
        r['brake_delay_s'] = (fb - base) if (fb is not None and base is not None) else None

    # Build groups, splitting velocity_on by outlier sign.
    def effective_group(r):
        g = r['group']
        if 'velocity_on' in g:
            outlier = r['brake_outlier_r_mps']
            if outlier is None:
                return g
            return g + ('+' if outlier > 0 else '-')
        return g

    for r in rows:
        r['eff_group'] = effective_group(r)

    # Collect unique (scenario, group) keys in encounter order.
    seen = {}
    for r in rows:
        key = (r['scenario'], r['eff_group'])
        seen[key] = seen.get(key, [])
        seen[key].append(r)

    # Print header.
    col_w = [30, 22, 5, 7, 8, 8, 8]
    header = ['Scenario', 'Group', 'N', 'Crash%', 'MinGap', 'Delay', 'ΔTTC']
    sep = '  '.join(f'{h:{w}}' for h, w in zip(header, col_w))
    print()
    print(sep)
    print('-' * len(sep))

    table_rows = []
    last_scenario = None
    for (scenario, group), group_rows in seen.items():
        if scenario != last_scenario:
            if last_scenario is not None:
                print()
            last_scenario = scenario
        n = len(group_rows)
        crash_pct = 100.0 * sum(r['collision'] for r in group_rows) / n
        min_gap = _mean([r['minimum_gap_m'] for r in group_rows])
        brake_delay = _mean([r['brake_delay_s'] for r in group_rows])
        delta_ttc = _mean([r['brake_delta_ttc_s'] for r in group_rows])
        cells = [scenario, group, str(n), f'{crash_pct:.0f}%', _fmt(min_gap), _fmt(brake_delay), _fmt(delta_ttc)]
        line = '  '.join(f'{c:{w}}' for c, w in zip(cells, col_w))
        print(line)
        table_rows.append(dict(scenario=scenario, group=group, n=n, crash_pct=crash_pct,
                               mean_minimum_gap_m=min_gap, mean_brake_delay_s=brake_delay,
                               mean_delta_ttc_s=delta_ttc))

    print()

    if csv_out:
        with open(csv_out, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['scenario', 'group', 'n', 'crash_pct',
                                                    'mean_minimum_gap_m', 'mean_brake_delay_s', 'mean_delta_ttc_s'])
            writer.writeheader()
            writer.writerows(table_rows)
        print(f'Table written to {csv_out}')

    return table_rows
