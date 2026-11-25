# BLOCKS

Reference: `docs/SUMMARY.md` (NCAP + controller analysis), `docs/EXPERIMENTS.md` (existing grids).

---

## Block 0 — Repo cleanup
_Do this first, before any other block. No code changes — moves and one delete only._

**Create `archive/` at the repo root** with three subfolders, then move:

| Source | Destination |
|---|---|
| `docs/radar_plugin_design.md` | `archive/docs/radar_plugin_design.md` |
| `configs/example_controller.json` | `archive/configs/example_controller.json` |
| `pipeline/controllers/example_aeb/` (whole folder) | `archive/controllers/example_aeb/` |

**Delete** the empty directory `esmini/` at the repo root.

**Do not touch** anything else — `pipeline/scenarios/imported/import_report.csv`, `OSC-NCAP-scenarios/`, `experiments/`, `data/`, or `runtime/` are all left exactly as they are.

**Done when**: `python -m unittest discover tests` still passes after the moves, and `git status` shows the renames (not deletions of tracked files).

---

## Block 0b — Folder reorganisation
_No code changes. Moves and new index files only._

### 1. Move NCAP source into `data/`
```
mkdir -p data/ncap
git mv OSC-NCAP-scenarios/OpenSCENARIO data/ncap/OpenSCENARIO
git mv OSC-NCAP-scenarios/OpenDRIVE    data/ncap/OpenDRIVE
git mv OSC-NCAP-scenarios/CONTRIBUTING.md data/ncap/CONTRIBUTING.md
git mv OSC-NCAP-scenarios/LICENSE      data/ncap/LICENSE
git mv OSC-NCAP-scenarios/README.md    data/ncap/README.md
rmdir OSC-NCAP-scenarios
```

### 2. Archive the 11 completed experiment grids
```
mkdir -p experiments/archive
git mv experiments/detection_seeds_50_99.json experiments/archive/
git mv experiments/fitted_profiles.json       experiments/archive/
git mv experiments/fitted_target_offsets.json experiments/archive/
git mv experiments/lost_target.json           experiments/archive/
git mv experiments/ou_bias.json               experiments/archive/
git mv experiments/ou_size.json               experiments/archive/
git mv experiments/ou_tau.json                experiments/archive/
git mv experiments/range_factors.json         experiments/archive/
git mv experiments/size_geometry.json         experiments/archive/
git mv experiments/tasc_baseline.json         experiments/archive/
git mv experiments/tasc_bicycle.json          experiments/archive/
git mv experiments/tasc_tolerance.json        experiments/archive/
```
Leave `smoke.json` at the root of `experiments/` — it is the standard sanity check.

### 3. Create cluster index files
Create `data/ccr/index.md` listing the TASC car-car scenario names (from `pipeline/scenarios/imported/scenarios.json`, group `car`).  
Create `data/vru_cb/index.md` listing the TASC cyclist scenario names (group `cyclist` and `bicycle`).  
Each file is a simple markdown table: scenario name | source file | notes. No pipeline files are moved.

### Done when
- `python -m unittest discover tests` passes.
- `git status` shows all moves as renames (R).
- `OSC-NCAP-scenarios/` no longer exists at the repo root.
- `experiments/` root contains only `smoke.json` and the `archive/` subfolder.

---

## Frozen decisions

| Decision | Choice |
|---|---|
| esmini version | Stay on **3.8.1** — OSC 1.3 fully supported |
| radar.py | **Archived** — future work, not in this paper |
| Controllers | **HiDrive** + **ALKS_R157SM** (ReferenceDriver) + **ACCController** |
| Scenario clusters | CCR (rear-end car-car) · VRU-CB (car-to-bicyclist) |
| VRU-CP (pedestrian) | Deferred — pending ClothoidSpline verification |
| TASC data | **Re-run** inside the clusters alongside NCAP cases |

---

## Block 1 — Bridge verification
_Prerequisite for all controller grids. One person, one run._

**Goal**: confirm the PerceptionBridge corrupts what native esmini controllers see.

**What to do**
- Run one CCRs scenario with `ALKS_R157SM_Controller` (ReferenceDriver) and no errors → record brake trigger time / minimum gap.
- Re-run the same scenario with a large bias (`+30 %` OU or fixed offset) → check if the controller brakes later or not at all.
- Repeat for `ACCController`.

**Done when**: both controllers show a measurable change in brake trigger time under the large bias. If not, flag immediately — a wrapper approach is needed before any grid.

---

## Block 2 — Scenario import
_Can run in parallel with Block 1._

**Goal**: both NCAP clusters registered in the pipeline and smoke-tested.

### 2a — CCR cluster
- Import `OSC-NCAP-scenarios/OpenSCENARIO/NCAP/CA-FC_2026/CCRs.xosc` as the base scenario.
- Expose the speed parameters so the grid can sweep CCRs / CCRb / CCRm variants.
- Add the 2023 version (`AEB_C2C_2023/NCAP_AEB_C2C_CCR_2023.xosc`) as a cross-check entry.
- Smoke-run each imported case with no errors and confirm it completes.
- TASC car-car cases are already in the registry — verify they still run cleanly after any import changes.

**Done when**: `python -m pipeline run configs/<ccr_smoke>.json` finishes without error for at least one NCAP CCR case and two TASC car-car cases.

### 2b — VRU-CB cluster
- Import the four CA-FC 2026 cyclist files: `CBNA`, `CBNAO`, `CBFA`, `CBLA`.
- Adapt if needed (note: no ClothoidSpline in these files — adaptation should be minimal or none).
- Smoke-run each with no errors.
- TASC cyclist cases: verify they run cleanly under the same controller(s) used for NCAP VRU-CB.

**Done when**: all four NCAP CB cases + existing TASC cyclist cases complete a no-error smoke run.

---

## Block 3 — Controller integration
_Depends on Block 1 passing._

**Goal**: HiDrive, ALKS_R157SM, and ACCController all working through the PerceptionBridge on CCR scenarios.

**What to do**
- For ALKS_R157SM and ACCController: wire them into the pipeline's controller registry (like HiDrive is wired).
- Write a minimal `controller.json` / config entry for each specifying the esmini property name.
- Confirm `python -m unittest discover tests` passes.
- Run a no-error baseline on CCRs for each controller; record crash / no-crash and minimum gap — this becomes the reference row in every future comparison table.

**Done when**: three controllers each produce a reproducible no-error baseline on CCRs. Numbers documented in `docs/EXPERIMENTS.md`.

---

## Block 4 — Experiment grids
_Depends on Blocks 2 + 3._

### 4a — CCR grid

**Question**: do the error sensitivity levels from the TASC-based grids hold across NCAP CCR cases and across all three controllers?

**Error levels** (same as `tasc_tolerance` for comparability):
- OU random: 5 %, 10 %, 20 %
- Too-far bias: +5, +10, +15, +20 %
- Miss rate: 10 % (vanish)
- Fitted profile: ASF (distance error + misses)

**Scenario set**: NCAP CCR (CCRs / CCRb / CCRm variants) + TASC car-car cases  
**Controllers**: HiDrive · ALKS_R157SM · ACCController  
**Seeds**: 10 per case (consistent with `tasc_tolerance`)

**Done when**: grid completes, `summary.json` for each run, results in `output/grids/ncap_ccr/`. Key table: crash rate × error level × controller.

### 4b — VRU-CB grid

**Question**: how do the same error types affect a crossing/cyclist scenario? Does identification (wrong class → different size assumption) matter more here than in CCR?

**Error levels**: same set as 4a  
**Scenario set**: NCAP CBNA · CBNAO · CBFA · CBLA + TASC cyclist cases  
**Controllers**: ALKS_R157SM + whichever of HiDrive/ACC handles VRU scenarios (confirm at Block 3)  
**Seeds**: 10 per case

**Done when**: grid completes in `output/grids/ncap_vru_cb/`. Key table: crash rate × error level × scenario type.

---

## Block 5 — Paper structure
_Can start in parallel with Block 4._

**6-page IEEE paper — SENSI project contribution.**  
Existing results from `docs/EXPERIMENTS.md` feed directly into Sections 3–4.

| Section | Content | Key figure / table |
|---|---|---|
| 1. Introduction | AEB + perception gap + SENSI placement (this paper closes the loop) | — |
| 2. Framework | Error chain · PerceptionBridge · scenario clusters · controllers | Pipeline diagram |
| 3. Sensitivity results (CCR) | Which error types crash, at what levels, across controllers | Crash rate × error level table |
| 4. Fitted K-Radar + VRU | Real detector profiles · cyclist cluster results | Miss-length vs crash plot |
| 5. Conclusion | Dominant risk = sustained miss; margin predicts vulnerability; future: radar.py | — |

**Done when**: one-sentence claim per section written down and agreed before any prose is drafted.
