# data/ — source files only, the pipeline runs from pipeline/scenarios/local/

This folder holds **original, unmodified** scenario sources. The pipeline never reads from here directly.

## What lives here

| Folder | Contents | In Git? |
|---|---|---|
| `ncap/` | Euro NCAP OpenSCENARIO + OpenDRIVE files, as downloaded from the public NCAP repo | Yes |
| `ccr/index.md` | Names and IDs of registered CCR (car-car rear-end) scenarios | Yes |
| `vru_cb/index.md` | Names and IDs of registered VRU-CB (car-to-bicyclist) scenarios | Yes |
| `Rear-end car-car/` | Raw TASC car-car cases (teacher data, source of truth) | **No** — gitignored |
| `Rear-end car-cyclist/` | Raw TASC cyclist/bicycle cases (teacher data) | **No** — gitignored |

## Why data/ and pipeline/scenarios/local/ are separate

`pipeline/scenarios/local/` holds **pipeline-ready copies** of the scenarios. They differ from the originals in a few ways:

- Paths are adjusted so esmini can find road and catalog files from wherever the pipeline runs
- A speed parameter (`Ego_speed_kph`) is added so the pipeline can sweep speeds without editing the file
- The controller slot is left neutral so `write_scene()` can inject whichever controller a run config requests

The source in `data/` is kept intact so re-importing is always possible without losing the original.

## Workflow

```
data/ncap/           →  (import step)  →  pipeline/scenarios/local/ncap_*.xosc
data/Rear-end car-car/  →  python -m pipeline tasc  →  pipeline/scenarios/local/tasc_car_*.xosc
```

Once a scenario is in `pipeline/scenarios/local/` and listed in `pipeline/scenarios/local/scenarios.json`, the pipeline can run it. The files in `data/` are not needed again after import.
