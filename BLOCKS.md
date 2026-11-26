# BLOCKS

Reference: `docs/SUMMARY.md` (NCAP + controller analysis), `docs/EXPERIMENTS.md` (existing grids).

---

## Frozen decisions

| Decision | Choice |
|---|---|
| esmini version | Stay on **3.8.1** — OSC 1.3 fully supported |
| radar.py | **Archived** — future work, not in this paper |
| Controllers | **HiDrive** + **ALKS_R157SM** + **ACCController** |
| Scenario clusters | CCR (rear-end car-car) · VRU-CB (car-to-bicyclist) |
| VRU-CP (pedestrian) | Deferred — pending ClothoidSpline verification |
| TASC data | **Re-run** inside the clusters alongside NCAP cases |
| PerceptionBridge | Already wraps all controller steps — no C++ changes needed |

---

## Controller–scenario assignment

| Controller | CCR (CCRs) | CCR (CCRb/CCRm) | VRU-CB | Why |
|---|---|---|---|---|
| **HiDrive** | ✓ | ✓ | ✓ | Forward AEB — brakes for any obstacle ahead |
| **ACC** | ✗ | ✓ | ✗ | Follows a moving lead vehicle; can't emergency-brake a stationary target or a crossing cyclist |
| **ALKS R157** | ✓ | ✓ | ✗ | R157 regulation defines CCRs/CCRb/CCRm as its test cases; not designed for VRU |

---

## Block 2 — Scenario smoke-run ← **next**
_Registration and files are already in place. This block is just end-to-end verification._

Run these configs with no errors and confirm each completes without crash:

| Scenario | Controller | Config to create |
|---|---|---|
| `ncap_ccrs_50` | hidrive | `configs/smoke_ccrs.json` |
| `ncap_ccrb_50` | hidrive | `configs/smoke_ccrb.json` |
| `ncap_ccrm_50` | hidrive | `configs/smoke_ccrm.json` |
| `ncap_cbna_50` | hidrive | `configs/smoke_cbna.json` |
| `tasc_car_1549178` | hidrive | `configs/smoke_tasc_car.json` |
| `tasc_cyclist_1543798` | hidrive | `configs/smoke_tasc_cyclist.json` |

**Done when**: all six complete, `end_reason` is `scenario_stop` or `collision` (not an error/crash), numbers logged in `docs/EXPERIMENTS.md`.

---

## Block 3 — No-error baselines

_All three controllers are already registered. This block records the reference numbers._

For each valid controller–scenario combination in the assignment table above, run with no errors and record crash / no-crash and minimum gap. These become the reference row in every comparison table.

**Done when**: baseline numbers in `docs/EXPERIMENTS.md` for all combinations.

---

## Block 4 — Experiment grids
_Depends on Blocks 2 + 3. **On hold** — do not start until both items below are resolved._

### Waiting on
- **April** — K-Radar fitting for detection (and possibly identification). Result goes into
  `pipeline/kradar/parameters.json` and must be usable via `{"type": "fitted", "profile": "..."}`.
  Block 4 runs the full grid in one shot (assumed + fitted together), so this must be ready first.
- **Aron** — TBD. Update this line once confirmed.

### 4a — CCR grid

**Question**: at what error level does each controller fail to avoid a rear-end collision?

**Error levels**:
- OU random: 5 %, 10 %, 20 %
- Too-far bias: +5, +10, +15, +20 %
- Miss rate: 10 % (vanish)
- Fitted profile: ASF (distance error + misses)

**Scenario set**: NCAP CCRs + CCRb + CCRm (50 kph) + TASC car-car cases  
**Controllers**: HiDrive (all) · ACC (CCRb + CCRm only) · ALKS (all)  
**Seeds**: 10 per case

**Done when**: grid completes in `output/grids/ncap_ccr/`. Key table: crash rate × error level × controller.

### 4b — VRU-CB grid

**Question**: how do the same error types affect a crossing-cyclist scenario?

**Error levels**: same set as 4a  
**Scenario set**: NCAP CBNA · CBNAO · CBFA · CBLA + TASC cyclist cases  
**Controllers**: HiDrive only  
**Seeds**: 10 per case

**Done when**: grid completes in `output/grids/ncap_vru_cb/`. Key table: crash rate × error level × scenario type.

---

## Block 5 — Paper structure
_Can start in parallel with Block 4._

**6-page IEEE paper — SENSI project contribution.**

| Section | Content | Key figure / table |
|---|---|---|
| 1. Introduction | AEB + perception gap + SENSI placement | — |
| 2. Framework | Error chain · PerceptionBridge · scenario clusters · controllers | Pipeline diagram |
| 3. Sensitivity results (CCR) | Which error types crash, at what levels, across controllers | Crash rate × error level table |
| 4. Fitted K-Radar + VRU | Real detector profiles · cyclist cluster results | Miss-length vs crash plot |
| 5. Conclusion | Dominant risk = sustained miss; margin predicts vulnerability; future: radar.py | — |

**Done when**: one-sentence claim per section written down and agreed before any prose is drafted.
