# aep — perception errors on esmini

Hard rules for every AI agent (HiDrive files, no Kalman filter, wording of results):
@AGENTS.md

## New agent? Read these first
Before writing a single line of code, read in this order:
1. `AGENTS.md` — hard rules you must not break.
2. `docs/SUMMARY.md` — what the project is, what scenarios and controllers we use, frozen decisions.
3. `docs/EXPERIMENTS.md` — every grid that has been run; check before designing a new one.
4. `BLOCKS.md` — block-by-block plan; find which block is next and start there.
5. `README.md` — setup and commands if you need to run anything.

If in doubt about the architecture of the error generator, read `docs/figures/architecture.png`
(the pipeline diagram) and `pipeline/errors/__init__.py` (Chain class).

## Data layout — read this before touching `data/` or `pipeline/scenarios/`

| Folder | What it contains | In Git? |
|---|---|---|
| `data/Rear-end car-car/` | Raw TASC car-car scenarios (teacher data, source of truth) | **No** — gitignored, never commit |
| `data/Rear-end car-cyclist/` | Raw TASC cyclist/bicycle scenarios (teacher data) | **No** — gitignored, never commit |
| `data/ncap/` | NCAP OpenSCENARIO + OpenDRIVE files (public, Euro NCAP repo) | Yes |
| `data/ccr/index.md` | List of registered CCR scenario names and IDs | Yes |
| `data/vru_cb/index.md` | List of registered VRU-CB scenario names and IDs | Yes |
| `pipeline/scenarios/imported/` | Imported, pipeline-ready versions of all scenarios | Yes |
| `pipeline/scenarios/imported/scenarios.json` | Registry — the single source of truth for what the pipeline can run | Yes |

**The pipeline never reads `data/` directly.** See `data/README.md` for a full explanation and `pipeline/scenarios/imported/README.md` for what the working set contains. It reads `pipeline/scenarios/imported/` and the registry.
Raw TASC files in `data/Rear-end*/` are only used by `python -m pipeline tasc` to (re-)import scenarios;
once imported they are not needed again. If those folders are missing on a fresh clone, that is expected.

## Project
Closed-loop sensitivity study: Python plugins add assumed or K-Radar-fitted range errors to what an AEB controller sees
in esmini rear-end scenarios; we measure how collisions, impact speed and TTC change.
Shared branch: `main`. Each person works on their own branch and merges into `main` through a pull request.
Teammates use Windows and macOS; this machine is Linux.

## Where to read
- `README.md`: setup, running one simulation or a grid, error plugin settings, file map.
- `docs/EXTENDING.md`: adding an error plugin, a controller or a scenario.
- `docs/EXPERIMENTS.md`: protocol and log of every grid. Add a row for every grid you run.
- `docs/SUMMARY.md`: scenario clusters, controller candidates, frozen decisions, open questions.
- `docs/figures/architecture.png` / `architecture.dot`: pipeline architecture diagram (Graphviz source + rendered PNG).

## Commands
- `source .venv/bin/activate`
- `python -m unittest discover tests`   (must pass before any commit)
- `python -m pipeline setup`            (after controller or PerceptionBridge.hpp changes)
- `python -m pipeline run configs/<subfolder>/<cfg>.json --output output/<subfolder>/<name>`
- `python -m pipeline grid experiments/<grid>.json --workers N`   (start with smoke.json)

## configs/ layout — one subfolder per purpose
| Subfolder | What goes there |
|---|---|
| `configs/smoke/` | Block 2 end-to-end smoke runs (no errors) |
| `configs/sanity/` | Quick error-generator sanity checks (one plugin or full chain) |
| `configs/baselines/` | Block 3 no-error baselines for all controller-scenario combinations |
| `configs/grids/` | Block 4 single-run configs used by grid experiments |
| `configs/archive/` | Old one-off configs — do not use for new runs |

## output/ layout — mirrors configs/
| Subfolder | What goes there |
|---|---|
| `output/smoke/` | Block 2 smoke results |
| `output/baselines/` | Block 3 baseline results — named `{controller}_{scenario}` |
| `output/grids/` | Block 4 grid results — named `{grid_name}` |
| `output/_archive/` | Old results — kept for reference, do not overwrite |

## Structure rules — keep the repo easy to follow
- Docs: only `README.md`, `CLAUDE.md` and `AGENTS.md` at the root; every other .md goes in `docs/`.
  Exception: `pipeline/controllers/hidrive/AGENTS.md` stays next to the files it protects.
- Prefer extending an existing file over adding a new script. A new error type is one file in
  `pipeline/errors/`; a new single run is one JSON in the right `configs/` subfolder; a new grid is one JSON in `experiments/`.
- No new top-level folders without asking. Results stay in `output/` (not in Git).
- Never search `runtime/`; for esmini source, read the zip in `runtime/downloads/`.

## Known pitfalls
- A run refuses to start on a stale build: run `setup` again.
- Windows long-path build failure: set `TME180_RUNTIME` to a short folder (e.g. `C:\t`).
