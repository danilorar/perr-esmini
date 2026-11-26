# imported/ — pipeline-ready scenarios (the working set)

This is what the pipeline actually runs. All 153 scenarios are registered in `scenarios.json`:

| Group | Count | Source |
|---|---|---|
| `car` | 98 | TASC car-car (imported from `data/Rear-end car-car/`) |
| `cyclist` | 21 | TASC cyclist (imported from `data/Rear-end car-cyclist/`) |
| `bicycle` | 21 | Same as cyclist but with bicycle-sized bounding box |
| `ncap_ccr` | 3 | NCAP CCRs/CCRb/CCRm at 50 kph (adapted from `data/ncap/`) |
| `ncap_vru_cb` | 10 | NCAP CB cyclist scenarios at 50/60/70 kph (adapted from `data/ncap/`) |

## What "pipeline-ready" means

Files here differ from the originals in `data/` in three ways:
1. Paths to road/catalog files are made absolute so esmini can find them from any working directory.
2. An `Ego_speed_kph` parameter is added so the pipeline can sweep speeds without editing the file.
3. The controller slot is left neutral — `write_scene()` injects the chosen controller at runtime.

## Gitignore

`scenarios.json` and `tasc_*/gidas_*/import_report.csv` are gitignored (teacher data, never commit).
Only the NCAP files (`ncap_*.xosc`, `ncap_*.xodr`) and their registry entries are tracked in Git.
To regenerate all files, run `python -m pipeline tasc <folder>` and `python -m pipeline import-ncap`.
