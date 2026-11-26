# Perception errors on esmini

This pipeline runs a rear-end scenario in [esmini](https://github.com/esmini/esmini) with an AEB controller,
adds a range error to what the controller sees, and saves what the car did. The controller reacts to the error, so
the loop is closed.

Most error values are assumed, so those results show sensitivity, not measured sensor risk. The `fitted` plugin uses
values fitted from real detectors on the K-Radar dataset instead (see [K-Radar data](#k-radar-data)).

Works on Windows and macOS. The default controller is HiDrive.

## Setup

You need Python 3.11 or newer, about 3 GB of disk, and a C++ compiler:

- **Windows:** Visual Studio with "Desktop development with C++" (it includes CMake).
- **macOS:** run `xcode-select --install` and `brew install cmake`.

```bash
git clone https://github.com/danilorar/perr-esmini.git
cd perr-esmini
```

Create and activate a Python environment.

Windows:

```bat
py -m venv .venv
.venv\Scripts\activate
```

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Then, on both:

```bash
pip install -r pipeline/requirements.txt
python -m pipeline setup
python -m unittest discover tests
```

`setup` downloads esmini 3.8.1 and about 1 GB of dependencies, then compiles it with the controllers. The first time takes a
few minutes. Run it again whenever a controller or `pipeline/engine/PerceptionBridge.hpp` changes; a run refuses to start on a
stale build. Error plugins are Python and need no compile. If a download fails, `setup` says which one; run it again
later and it downloads only what is missing.

## Run one simulation

```bash
python -m pipeline run configs/lost_target.json --output output/my_run
python -m pipeline replay output/my_run
python -m pipeline list
```

Without `--output`, results go to a new folder in `output/runs/`. `replay` opens the run in the esmini viewer. `list` shows
the available controllers, error plugins and scenarios.

A configuration lists only what differs from the defaults in `pipeline/config.py`:

```json
{"scenario": "gidas_1549178", "errors": [{"type": "ou", "mae_pct": 5.0}], "seed": 0}
```

| Result file | Content |
|---|---|
| `summary.json` | Collision, impact speed, trigger and brake times, smallest gap and TTC, status |
| `ego.csv` | Ego speed, position and controller acceleration per step |
| `observations.csv` | True and observed range per step and target |
| `truth.csv` | True state of every vehicle per step |
| `metrics.csv` | Distance, gap and TTC per step. These use the truth; the controller never sees them |
| `speed.png`, `range.png` | Plots of this run |
| `config.json`, `versions.json` | Full settings and versions; `config.json` can be run again. `versions.json` also has the Git commit and any files that differ from it |
| `perception_applied.tsv` | Per step: true range, range given to the controller, and the values each error plugin logs |
| `esmini.log`, `esmini.csv`, `replay.dat`, `scene.xosc` | Raw esmini input and output |

## Run a grid

```bash
python -m pipeline grid experiments/smoke.json
python -m pipeline grid experiments/range_factors.json --list
python -m pipeline grid experiments/range_factors.json --workers 16
```

Results go to `output/grids/<name>/`: `results.csv` has one row per run, `summary.csv` one row per scenario and level,
`failed.txt` lists failed runs. A stopped grid continues where it stopped. A grid keeps compressed tables only; it does not
keep plots or replay files.

To compare results with someone else, run the same commit with no local changes. The last columns of `results.csv`
give each run's commit and how many files differed from it, and the grid warns at the end when that is not one clean
commit.

```json
{
  "name": "my_grid",
  "scenarios": ["gidas_1549178"],
  "base": {"errors": [{"type": "detection", "miss_rate": 0.1}]},
  "groups": [
    {"name": "markov", "vary": {"errors.detection.miss_mean_s": [0.2, 0.5, 1.0]}, "seeds": 50},
    {"name": "iid", "set": {"errors.detection.miss_model": "iid"}, "seeds": {"first": 50, "count": 50}}
  ]
}
```

Every combination of the `vary` values runs on every scenario with every seed. Without `scenarios`, the three shared
scenarios run. `scenarios` also takes patterns such as `"tasc_car_*"` for imported TASC cases (see below).
A key like `errors.detection.miss_rate` changes one setting of the entry with that `name` or `type`; the entry must
already be in the list, from `base` or `set`. A `set` of `"errors"` replaces the whole list.
`seeds` is a count (from 0), a range, or a list like `[1, 2]`; without it, seed 0 runs.

Ready-made grids are in `experiments/`. Start with `smoke`, which checks that the pipeline works.

## Error plugins

Errors are set with `"errors"`, a list of plugins that run in that order on every controller step:

```json
"errors": [{"type": "size", "scale": 1.1}, {"type": "ou", "mae_pct": 1.4}, {"type": "detection", "miss_rate": 0.1}]
```

`type` is the file name in `pipeline/errors/`. The other keys are settings; a setting left out keeps its default. Each
plugin gets the result of the one before it, so the order matters. To use one type twice, give each entry a `name`.

| Type | What the controller gets | Settings (default) |
|---|---|---|
| `size` | range + (scale - 1) * true range + bias | `scale` (1.0), `bias_m` (0.0) |
| `box` | a box with length_scale * true length and width_scale * true width; `keep` says which point stays right: the centre (the gap is wrong by half the length error) or the end facing the ego (the gap is unchanged) | `length_scale` (1.0), `width_scale` (1.0), `keep` (`centre` or `near_end`) |
| `identification` | in wrong-class frames: range + (wrong_scale - 1) * true range + wrong_bias; `size` skips those frames | `wrong_rate` (0), `wrong_mean_s` (0.5), `wrong_scale` (1.0), `wrong_bias_m` (0), `sensor_period_s` (0.05) |
| `ou` | range + a correlated error that grows with distance, plus an optional constant bias with the same distance law | `mae_pct` (5.0, mean error at `reference_range_m`), `bias_pct` (0.0, > 0 reads too far), `correlation_time_s` (0.5), `zero_range_m` (3), `reference_range_m` (100) |
| `detection` | in lost frames: no target, or a predicted range | `miss_rate` (0), `miss_model` (`markov` or `iid`), `miss_mean_s` (0.5), `sensor_period_s` (0.05), `lost_target` (`vanish` or `predict`), `lost_target_motion` (`live` or `frozen`), `lost_target_distance` (`frozen_difference` or `frozen_object`) |
| `fitted` | range + a bias, an OU error and white noise per 0.1 s frame, and missed frames whose lengths are drawn from the log, all with the values `fit-kradar` fitted (see below); a missed frame is handled as in `detection` | `parameters` (`pipeline/kradar/parameters.json`), `profile` (a detector in that file, such as `asf`), `condition` (`all`, `range`, `normal`, `rain`, `fog` or `snow`), `offset` (`none`; `target`: each target keeps one offset for the whole run, drawn from the log's per-car mean errors, plus the spread around them; `fixed`: every target keeps `offset_m`, for sensitivity studies), `offset_m` (0, metres, > 0 too far), `spread_scale` (1; multiplies the random part, 0 turns it off), `range_error` (true), `misses` (true), `lost_target`, `lost_target_motion`, `lost_target_distance` (as in `detection`) |
| `template` | range + white noise; a starting point for new plugins | `sigma_m` (0.0) |

Put `identification` before `size`, and `detection` or `fitted` last, so the prediction starts from the range with all
other errors. `fitted` replaces `ou` and `detection`; do not stack them. The docstring at the top of each file gives
the details.

How it works: before each controller step, esmini sends the true state of every object to Python. The plugins change
what the controller should see, and esmini moves the targets there for that one step and puts them back right after.
Collisions, logs and replays therefore stay true, and any controller that reads targets from esmini gets the error with
no extra code. `perception_applied.tsv` records, per step, the true and given range and every value the plugins log.

## K-Radar data

The `fitted` plugin uses distance errors and misses measured on the K-Radar dataset: the teacher's tables of where each
car really was and where three detectors put it. What the data is, how it was fitted and what came out:
[docs/KRADAR.md](docs/KRADAR.md).

**The tables are not in this repository, on purpose.** The repository is public, and K-Radar's licence (CC BY-NC-ND)
does not allow sharing changed versions of the data; the teacher's tables are one. `pipeline/kradar/` holds what you
need instead: the fitted values (`parameters.json`, numbers only), K-Radar's train/test split and the sha256 of each
table. So the `fitted` plugin works without the tables.

To redo the fit, get the four tables from the teacher (detector tables: the corrected set of 2026-11-25) and
run:

```bash
pip install pandas pyarrow
python -m pipeline fit-kradar <data folder>
```

It stops if a table is not the teacher's version, and ends by saying whether your fit matches
`pipeline/kradar/parameters.json`. Never add the tables to Git.

## Extend the pipeline

To add an error plugin, a controller or a scenario, see [docs/EXTENDING.md](docs/EXTENDING.md).

## Files

```
pipeline/
  __main__.py       command line
  config.py         settings and checks
  run.py            one simulation
  grid.py           many simulations
  results.py        result tables and metrics
  plots.py          plots of one run
  fit_kradar.py     error parameters fitted from K-Radar boxes (fit-kradar)
  kradar/           the shared K-Radar fit, split lists and table checksums (no K-Radar data)
  controllers/      one folder per controller
  errors/           error plugins
  scenarios/        scenario files
  engine/           esmini build and the perception bridge
configs/            example configurations
experiments/        grids
tests/              python -m unittest discover tests
docs/               EXTENDING.md (add plugins, controllers, scenarios), EXPERIMENTS.md (grid log),
                    TASC_SCENARIOS.md (which TASC cases are used), KRADAR.md (K-Radar data, fit and results)
AGENTS.md           rules for AI agents (CLAUDE.md loads it for Claude Code)
```

Not used by the pipeline, and left as they are on `main`: `OSC-NCAP-scenarios/`, `PerceptionModels.pdf`, `esmini`,
`requirements.txt`. Created locally and not in Git: `runtime/` (compiled esmini), `output/` (results),
`pipeline/scenarios/local/` (imported TASC cases).

## Good to know

- `gidas_*` are the three scenario IDs. The data are TASC data, even where a file says GIDAS.
- The teacher's TASC case folders (`Cut-in`, `Rear-end car-car`, `Rear-end car-cyclist`, each with `Xosc/` and `Xodr/`)
  are imported with `python -m pipeline import-tasc <folder>`. HiDrive is a forward AEB, so only cases where the ego's
  front hits the other road user are kept: 119 of 149, as `tasc_car_*` (98) and `tasc_cyclist_*` (21) in
  `pipeline/scenarios/local/`, outside Git. Cases hit from behind, cut-ins, crossings and boxes that overlap from the
  start are skipped; see `docs/TASC_SCENARIOS.md`, and `import_report.csv` next to the cases for each file's reason.
  The cyclist files define the cyclist as a car; add `--bicycle` to also get `tasc_bicycle_*`, the same cases with a
  bicycle-sized box.
- The course does not allow a Kalman filter, so controllers get the observations directly.
- The same seed gives the same result on the same machine. Windows and macOS may differ slightly.
- Each scenario draws its own error samples from the seed (`"seed_scope": "scenario"`, the default), so seed 1
  is a different miss pattern in every TASC case. Runs before 2026-11-17 drew the same samples in every scenario;
  add `"seed_scope": "shared"` to a configuration or a grid's `base` to repeat them.
- macOS was tested on a cloud Mac with no display, so `replay` has not been tried there yet.
- If a Windows build fails on long paths, set `TME180_RUNTIME` to a short folder, such as `C:\t`, and run `setup` again.
- AI agents must not read the HiDrive sources: see `pipeline/controllers/hidrive/AGENTS.md`.
