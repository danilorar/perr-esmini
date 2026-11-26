# Analysis summary — NCAP scenarios, esmini controllers, next steps

_Date: 2026-11-24_

---

## 1. esmini version — stay on 3.8.1

3.8.1 fully supports OpenSCENARIO 1.3: `VariableDeclarations`, `VariableCondition`, absent `StartTrigger`, and `ClothoidSpline`. Confirmed by `osc_coverage.txt` in the source archive and by the NCAP smoke test suite that ships with esmini. **No upgrade needed.**

---

## 2. NCAP scenario clusters

### Cluster 1 — CCR (Car-to-Car Rear-end)

| Recommended file | Covers |
|---|---|
| `CA-FC_2026/CCRs.xosc` | Stationary, braking, moving variants via parameters |
| `AEB_C2C_2023/NCAP_AEB_C2C_CCR_2023.xosc` | 2023 protocol reference / cross-check |

Ego is on a constant-speed approach; needs an active braking controller. No ClothoidSpline. Ready to import as-is.

### Cluster 2 — VRU-CB (Car-to-Bicyclist)

| File | Scenario |
|---|---|
| `CA-FC_2026/CBNA.xosc` | Cyclist crossing nearside |
| `CA-FC_2026/CBNAO.xosc` | Cyclist crossing nearside, obstructed |
| `CA-FC_2026/CBFA.xosc` | Cyclist crossing farside, obstructed |
| `CA-FC_2026/CBLA.xosc` | Cyclist longitudinal (ahead of ego) |

No TrajectoryCatalog / ClothoidSpline dependency. Ego is the AEB subject in all four. Ready to import.

### Deferred — VRU-CP (Car-to-Pedestrian)

Pedestrian scenarios (`CPNA`, `CPNCO`) reference `TrajectoryCatalog`, which uses `ClothoidSpline` even for straight-walk paths. Feasible once the catalog is verified in esmini 3.8.1. Recommend deferring until CCR and VRU-CB clusters are running.

### Not in scope

CCF (front head-on, turn-across-path), CCCscp (crossing), CPRA (reverse), CPTA (ego turns): ego is on a fixed trajectory or the scenario geometry makes it unsuitable for AEB testing.

---

## 3. Controller candidates

Both are native esmini controllers — no extra build required.

| Controller | What it does | Fit for this project |
|---|---|---|
| **ALKS_R157SM_Controller** (use model `ReferenceDriver`) | TTC-based emergency brake trigger (default TTC 1.4 s, decel 8.34 m/s²). Designed for UN R157 / NCAP rear-end evaluation. Runs against NCAP scenarios in esmini's own CI. | **Primary candidate** — purpose-built for this use case |
| **ACCController** | Maintains a time-gap headway (default 1.5 s) to the nearest lead vehicle; brakes to 3 m minimum free space. Simpler — no explicit emergency-brake trigger. | **Secondary / baseline** — good for comparing a comfort-only controller against ALKS |

Referenced in xosc as:
```xml
<Property name="esminiController" value="ALKS_R157SM_Controller" />
<!-- or -->
<Property name="esminiController" value="ACCController" />
```

---

## 4. Open engineering question — PerceptionBridge compatibility

The bridge moves objects in esmini's global scene graph to corrupted positions before the ego controller's step, then restores them. HiDrive (custom plugin) already works. Native controllers (ALKS, ACC) also read the global scene graph, so in principle the bridge should corrupt what they see too.

**But this needs a one-run verification before any grid is designed around these controllers.** The check: run a CCRs scenario with ALKS_R157SM, inject a large bias (+30%), and confirm the controller brakes later than the no-error run. If it does, the bridge works for native controllers. If not, a wrapper approach is needed.

---

## 5. Scenario/data organisation

The existing TASC car-car cases (teacher-provided, not public) fall naturally into the CCR cluster. The existing TASC cyclist cases map to VRU-CB. No re-running needed just for organisation — when new NCAP grids are run, results from both sources sit in the same cluster table.

---

## 6. What comes next (TODOS outline)

1. **Verify bridge + native controller** (one test run, CCRs + ALKS_R157SM + large bias)
2. **Import NCAP CCR scenarios** into the pipeline scenario registry
3. **Import NCAP VRU-CB scenarios** (CBNA, CBNAO, CBFA, CBLA)
4. **CCR grid**: run main error levels (OU 10 %, miss 10 %, bias +15 %, fitted-ASF) × ALKS_R157SM + HiDrive × NCAP CCR cases
5. **VRU-CB grid**: same error levels × whichever controller passes the bridge check × NCAP CB cases
6. **Paper structure**: freeze section outline and figure list (see `docs/EXPERIMENTS.md` for existing results that feed directly into sections 3–4)
