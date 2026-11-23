"""Two pictures for one run: speed.png and range.png.
Grid summary: grid_plots(output_dir) writes collision_rate.png, rmse.png, gap_cdf.png."""
import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from .common import read_json

SPEED, BRAKE = '#197f7a', '#bc632d'

_GROUP_COLORS = {'no_error': '#6b7280', 'radar_clear': '#2563eb', 'radar_fog': '#d97706'}
_GROUP_LABELS = {'no_error': 'No error', 'radar_clear': 'Radar — clear', 'radar_fog': 'Radar — fog'}
_TYPE_ORDER = ['car', 'cyclist', 'bicycle']
_GROUP_ORDER = ['no_error', 'radar_clear', 'radar_fog']


def read_table(path):
    with Path(path).open(encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def values(rows, key):
    return [float(row[key]) if row[key] else float('nan') for row in rows]


def speed_plot(out, ego, summary):
    figure, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    t = values(ego, 'time_s')
    axes[0].plot(t, values(ego, 'speed_kph'), color=SPEED, lw=2)
    axes[0].set(ylabel='Ego speed (km/h)', title='Ego response')
    axes[1].step(t, values(ego, 'command_accel_mps2'), where='post', color=BRAKE)
    axes[1].set(xlabel='Simulation time (s)', ylabel='Controller acceleration (m/s²)')
    for axis in axes:
        if summary.get('first_brake_time_s') is not None:
            axis.axvline(summary['first_brake_time_s'], color=BRAKE, ls=':', lw=1)
        axis.grid(alpha=0.2)
    figure.savefig(out / 'speed.png', dpi=150, bbox_inches='tight')
    plt.close(figure)


def range_plot(out, observations):
    figure, (axis, error_axis) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for name in dict.fromkeys(row['object_name'] for row in observations):
        rows = [row for row in observations if row['object_name'] == name]
        t = values(rows, 'time_s')
        truth = values(rows, 'true_range_m')
        observed = values(rows, 'observed_range_m')
        line, = axis.plot(t, truth, lw=1.8, label=f'{name}: truth')
        axis.plot(t, observed, ls='--', alpha=0.65, color=line.get_color(), label=f'{name}: observed')
        error_axis.plot(t, [o - r for o, r in zip(observed, truth)], color=line.get_color(), alpha=0.6, label=name)
    axis.set(ylabel='Centre-to-centre range (m)', title='Truth and observed range')
    axis.legend(fontsize=8)
    error_axis.axhline(0, color='#7b8793', lw=0.7)
    error_axis.set(xlabel='Simulation time (s)', ylabel='Range error (m)')
    for item in (axis, error_axis):
        item.grid(alpha=0.2)
    figure.savefig(out / 'range.png', dpi=150, bbox_inches='tight')
    plt.close(figure)


def make_plots(out):
    out = Path(out)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    speed_plot(out, read_table(out / 'ego.csv'), read_json(out / 'summary.json'))
    range_plot(out, read_table(out / 'observations.csv'))


# ---------------------------------------------------------------------------
# Grid summary plots
# ---------------------------------------------------------------------------

def _target_type(scenario_name):
    if 'bicycle' in scenario_name:
        return 'bicycle'
    if 'cyclist' in scenario_name:
        return 'cyclist'
    return 'car'


def _load_grid_rows(output_dir):
    path = Path(output_dir) / 'results.csv'
    if not path.is_file():
        raise FileNotFoundError(f'{path} not found — run the grid first.')
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    for r in rows:
        r['_type'] = _target_type(r['scenario'])
        r['_collision'] = r['collision'] == 'True'
    return rows


def _collision_rate_plot(out, rows):
    groups = [g for g in _GROUP_ORDER if any(r['group'] == g for r in rows)]
    types = [t for t in _TYPE_ORDER if any(r['_type'] == t for r in rows)]

    n_groups = len(groups)
    n_types = len(types)
    bar_w = 0.7 / n_groups
    x = list(range(n_types))

    fig, ax = plt.subplots(figsize=(max(6, n_types * 2.2), 4.5))
    for i, grp in enumerate(groups):
        rates, counts, totals = [], [], []
        for t in types:
            bucket = [r for r in rows if r['group'] == grp and r['_type'] == t]
            n = len(bucket)
            c = sum(1 for r in bucket if r['_collision'])
            rates.append(100 * c / n if n else 0)
            counts.append(c)
            totals.append(n)
        offset = (i - (n_groups - 1) / 2) * bar_w
        bars = ax.bar([xi + offset for xi in x], rates, width=bar_w * 0.9,
                      color=_GROUP_COLORS[grp], label=_GROUP_LABELS[grp])
        for bar, c, n in zip(bars, counts, totals):
            if n:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.4,
                        f'{c}/{n}', ha='center', va='bottom', fontsize=7.5, color='#374151')

    ax.set_xticks(x)
    ax.set_xticklabels([t.capitalize() for t in types])
    ax.set_ylabel('Collision rate (%)')
    ax.set_ylim(0, min(100, max(r for grp_rates in
                                [[100 * sum(1 for r in rows if r['group'] == g and r['_type'] == t and r['_collision'])
                                  / max(1, sum(1 for r in rows if r['group'] == g and r['_type'] == t))
                                  for t in types] for g in groups] for r in grp_rates) + 8))
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.25)
    ax.set_title('Collision rate by error group and target type')
    fig.tight_layout()
    fig.savefig(out / 'collision_rate.png', dpi=150, bbox_inches='tight')
    plt.close(fig)


def _rmse_plot(out, rows):
    rmse_groups = [g for g in _GROUP_ORDER if g != 'no_error'
                   and any(r['group'] == g and r['observed_range_rmse_m'] for r in rows)]
    if not rmse_groups:
        return
    types = [t for t in _TYPE_ORDER if any(r['_type'] == t for r in rows)]

    n_groups = len(rmse_groups)
    bar_w = 0.7 / n_groups
    x = list(range(len(types)))

    fig, ax = plt.subplots(figsize=(max(6, len(types) * 2.2), 4.5))
    for i, grp in enumerate(rmse_groups):
        means, stds = [], []
        for t in types:
            vals = [float(r['observed_range_rmse_m']) for r in rows
                    if r['group'] == grp and r['_type'] == t and r['observed_range_rmse_m']]
            means.append(sum(vals) / len(vals) if vals else 0)
            if len(vals) > 1:
                mu = means[-1]
                stds.append(math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)))
            else:
                stds.append(0)
        offset = (i - (n_groups - 1) / 2) * bar_w
        ax.bar([xi + offset for xi in x], means, width=bar_w * 0.9,
               yerr=stds, capsize=3, error_kw={'linewidth': 1},
               color=_GROUP_COLORS[grp], label=_GROUP_LABELS[grp])

    ax.set_xticks(x)
    ax.set_xticklabels([t.capitalize() for t in types])
    ax.set_ylabel('Mean range RMSE (m)')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.25)
    ax.set_title('Range RMSE introduced by error groups (mean ± 1 SD)')
    fig.tight_layout()
    fig.savefig(out / 'rmse.png', dpi=150, bbox_inches='tight')
    plt.close(fig)


def _gap_cdf_plot(out, rows):
    groups = [g for g in _GROUP_ORDER if any(r['group'] == g for r in rows)]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for grp in groups:
        gaps = sorted(float(r['minimum_gap_m']) for r in rows
                      if r['group'] == grp and r['minimum_gap_m'])
        if not gaps:
            continue
        n = len(gaps)
        ax.step([gaps[0]] + gaps, [0] + [(i + 1) / n for i in range(n)],
                where='post', color=_GROUP_COLORS[grp], lw=1.8, label=_GROUP_LABELS[grp])
    ax.axvline(0, color='#9ca3af', lw=0.8, ls='--', label='Collision threshold')
    ax.set_xlabel('Minimum gap (m)')
    ax.set_ylabel('Cumulative fraction of runs')
    ax.set_xlim(left=min(-1, ax.get_xlim()[0]))
    ax.legend(fontsize=9)
    ax.grid(alpha=0.2)
    ax.set_title('Distribution of closest approach across all scenarios')
    fig.tight_layout()
    fig.savefig(out / 'gap_cdf.png', dpi=150, bbox_inches='tight')
    plt.close(fig)


def grid_plots(output_dir):
    """Generate collision_rate.png, rmse.png and gap_cdf.png from a grid's results.csv."""
    out = Path(output_dir)
    rows = _load_grid_rows(out)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    _collision_rate_plot(out, rows)
    _rmse_plot(out, rows)
    _gap_cdf_plot(out, rows)
    return out
