# Experiments

Every grid in `experiments/` gets a row here. Results live in `output/grids/<name>/` (not in Git),
so this file is the shared record of what was run and what it showed.

## Protocol
1. **One question per grid.** Write the question and the decision rule here *before* running it.
2. **Error values are assumed.** Report results as sensitivity ("collisions start above X % range
   error"), never as measured sensor risk.
3. **Always include a reference:** a `no_error` group on the same scenarios, so every change is
   compared with the error-free controller.
4. **Paired comparisons.** Two variants run on the same scenarios and seeds are compared seed by seed
   (difference per seed, then mean and a bootstrap 95% CI), not as two separate averages.
5. **Report the seed count.** Rates from few seeds (e.g. 2 collisions in 50) are uncertain: give the
   count and a confidence interval, not only the percentage.
6. **Reproducibility check:** the same config and seed must give the same `summary.json` on the same
   machine. Windows and macOS may differ slightly; say which machine produced a number.
7. **Negative results are results.** "No effect up to X" goes in the table with one line of reason.

## Grid log

| Grid | Question | Runs | Date run | Machine | Main result | Verdict |
|---|---|---|---|---|---|---|
| `smoke` | Does the pipeline work end to end? | 6 | 2026-11-08 | Windows 11, `247f6cc` | 6/6 finish; only `gidas_1554431` without error crashes | Works; same numbers before and after a fresh setup from `main` |
| `range_factors` | Size, identification, detection and OU errors, each alone: which matter? | 1899 | 2026-11-08 | Windows 11, `247f6cc` | Safe scenarios: target vanishing while missed 30/400 crash (95% CI 5.3–10.5%); wrong class ×1.77 at 20% 9/60 (8.1–26.1%), at 5% 1/60; size scale 1.1 1/2, 1.2 2/2; OU 0.8% and 1.4% 0/60; all other cells 0 | At these assumed values detection, identification (×1.77) and size (from +10%) can cause crashes, OU at 0.8–1.4% does not. Same as the 2026-11-01 studio sweep, run by run |
| `detection_seeds_50_99` | Extra seeds 50–99 for the detection groups of `range_factors` | 600 | | | | |
| `ou_size` | How large must the OU error be before safety changes? | 282 | 2026-11-08 | Windows 11, `247f6cc` | Safe scenarios: 0/60 at 5%, 5/60 at 10% (3.6–18.1%), 8/60 at 20% (6.9–24.2%). `gidas_1554431`: 17, 14, 12 of 30 crash, median impact 17.5, 19.6, 24.7 km/h (no error 10.5) | Safe scenarios start crashing between 5% and 10%; on `gidas_1554431` fewer but harder crashes as the error grows. Sizes are sensitivity levels, not sensor values. Same as the 2026-11-03 studio sweep, run by run |
| `ou_tau` | OU error: mean error at 100 m x correlation time | 1803 | 2026-11-08 | Windows 11, `8954bdf` | Safe scenarios, crashes of 60 at tau 0.05 / 0.2 / 0.5 / 1 / 2 s: 5% 0/0/0/0/0; 10% 0/4/5/4/5; 20% 0/1/8/8/9; 50% 0/0/1/3/9 (4/60: 2.6–15.9%, 9/60: 8.1–26.1%). At tau 0.05 s no crash up to 50%, but the brake triggers more than 0.1 s early in 47–60 of 60 runs from 10% | Up to 5% no crash at any correlation time. From 10% crashes need an error that lasts (none at 0.05 s, 4–5/60 from 0.2 s); larger errors that change fast trigger early braking instead of crashes. Sensitivity levels, not sensor values |
| `ou_bias` | Same mean error size: does a constant too-far reading hurt more than random error, and where does bias plus random error start to crash? | 579 | 2026-11-08 | Windows 11, `685e3a0` | Constant bias, one run per level: reading too near (−5, −10%) never crashes and also avoids the no-error crash on `gidas_1554431`; reading too far first crashes at +15% on `gidas_1554254` and +20% on `gidas_1549178` (about 2.4 m at braking start), while the gap shrinks from +5% (`gidas_1554254` 1.90 → 0.56 m at +10%). Random error alone (`ou_tau`, tau 0.5 s) already crashes 5/60 at 10%. Bias + random, safe scenarios: random 2.5% with bias up to +5% 0/60; random 5% 0/60, with +2.5% bias 2/60, with +5% bias 4/60 (2.6–15.9%). `gidas_1554431`: random 2.5% 20/30 crash, with +5% bias 30/30, median impact 13.2 → 22.1 km/h | Direction matters: too near is safe here, too far eats the margin in every run and crashes for sure from about 15–20%. A random error of the same mean size crashes earlier (10%) but only in some runs, as it is sometimes two to three times its mean. A +5% bias and 5% random error, harmless alone, crash together about as often as 10% random alone. Sensitivity levels, not sensor values |
| `size_geometry` | A wrong reported length of the target box (`box` plugin): does braking follow the box length, and how much does safety change when the centre or the near end stays right? | 27 | 2026-11-10 | Windows 11, `711fd6a` | Target is 5.0 m long, so ±10% and ±20% move each end by 0.25 and 0.5 m. Near end right: all 12 runs equal the no-error run (differences below 1e-5). Centre right, safe scenarios: no crash; shorter box (near end read too far) lowers the minimum gap, `gidas_1549178` 3.20 → 3.17 → 3.13 m and `gidas_1554254` 1.90 → 1.84 → 1.74 m at −10 and −20%; longer box raises it on `gidas_1554254` (2.11, 2.60 m) and changes nothing on `gidas_1549178`. `gidas_1554431` (crashes without error at 10.5 km/h relative): 12.6 and 17.5 km/h at −10 and −20%, 3.1 km/h at +10%, no crash at +20% (gap 0.18 m) | The controller reacts to the gap to the near end of the box. A length error changes safety only if the centre, not the near end, is what is measured right, and then by half the length error: same direction as a range bias (too far is worse), no new crash up to ±20% on the safe scenarios. One run per level, no randomness. Sensitivity levels, not sensor values |
| `lost_target` | What the vehicle gets while the target is lost (vanish / predict / frozen) | 3000 | 2026-11-08 | Windows 11, `247f6cc` | Safe scenarios, against 30/400 when the target vanishes: object speed held (`ou_speed`) 17/400 (2.7–6.7%); speed difference held (`frozen`, `ou_frozen`) 14/400; true speed kept (`predict`, `ou_predict`) 4/400. `gidas_1554431`: 162/200 with OU, 198–200/200 without | Holding the object speed avoids 13 of the 30 vanish crashes and adds none. The 4/400 groups still get the true target speed, so they flatter the prediction. Same as the 2026-11-02/03 studio sweeps, run by run |
| `tasc_baseline` | No error on every imported TASC case: which ones does HiDrive avoid, and do converted copies match the shared files? | 133 | 2026-11-11 | Windows 11, `e6f1024` | Car-car 81 of 101 safe; the 20 crashes are 17 cases in lane at ego 95–110 km/h and 3 side contacts where HiDrive never triggers. Cyclist 20 of 24 safe; the 4 crashes enter the ego path late or touch at the side. Cut-in 5 of 5 crash and HiDrive never triggers. `tasc_car_1554254` and `1554431` equal the shared runs exactly; `tasc_car_1549178` (real road instead of the straight one) differs by under 0.01 m | Every car-car case up to ego 75 km/h is safe without error; the cut-in cases cannot show a range-error effect with this controller |
| `tasc_tolerance` | Do the limits found on the three shared scenarios hold across the TASC car-car and cyclist cases? | 5355 | 2026-11-17 | Windows 11, `03043b2` | Each case draws its own errors. Car-car, 81 cases safe without error, 10 seeds each: OU 5/10/20% crash in 16/810 = 2.0% (0.0–5.1%, bootstrap over cases), 41/810 = 5.1% (2.8–7.5%) and 64/810 = 7.9% (5.8–10.4%) of runs, in 3, 24 and 41 cases; at 5% 15 of the 16 are the two cases with 0.20 and 0.32 m left without error (`1571693`, `1620061`). 10% miss rate (target vanishes): 76/810 = 9.4% (7.4–11.5%) in 52 cases. Too-far bias (no randomness, unchanged) crashes 2, 3, 14, 23 of 81 cases at +5, +10, +15, +20%; 58 do not crash up to +20%. Cluster ego/target 65/55 km/h (17 cases): 11 and 16 crash at +15 and +20%; cluster 45/35 (44 cases): 0 and 1 (`1549178`). Cyclist (a car-sized box), 20 safe cases: no crash from OU or bias up to 20%, miss rate 4/200. Car-car cases that crash without error (17): median relative impact +3.1, +8.5, +12.6 km/h at OU 5/10/20% (29%, 39% and 60% of those runs avoid the crash), +10 to +22 km/h with bias and never avoided; misses never avoid one | Random error starts to crash between 5% and 10% (at 5% almost only where the margin is a few decimetres) and grows slowly: 20% crashes 8% of runs. A 10% miss rate with the target vanishing crashes more often than 20% random error. "Too far crashes for sure from 15–20%" holds only where the margin is small: the minimum gap without error, divided by the range at braking start, ranks the cases (Spearman −0.50 with the random-error and miss crashes per case), and cases under 15% hold 20 of the 23 crashes at +20%. Sensitivity levels, not sensor values. The first run (2026-11-11, `e6f1024`, 5625 runs, one error pattern per seed shared by all cases) gave OU 1.2/6.8/16.8% and misses 5.2%, mostly from seeds 2 and 4 (OU) and 10 (misses); it is kept in `output/grids/tasc_tolerance_shared_seeds/` |
| `fitted_profiles` | With the distance error and misses of two real detectors (fitted from K-Radar, `fitted` plugin), does HiDrive still avoid the TASC car-car crashes it avoids without error, and is it the distance error or the misses? | 5978 | 2026-11-17 | Windows 11, `407795b` | 81 of 98 cases safe without error; each case draws its own errors. Distance error alone: only the two cases with 0.20 and 0.32 m left without error (`1571693`, `1620061`) crash, in 11/20 (ASF) and 10/20 (PV-RCNN) runs; 0/1580 in the other 79. Misses alone: 36/810 = 4.4% (3.0–6.0%, bootstrap over cases) ASF and 32/810 = 4.0% (2.6–5.4%) PV-RCNN, in 29 and 25 cases, spread over all seeds. By the longest miss while the ego moves, both detectors together: under 0.5 s 5/709 crash, 0.5–1 s 9/152, 1–2 s 19/74, 2–3 s 14/33, 3 s or more 21/28. Both errors: 43/810 = 5.3% (3.1–8.1%) and 37/810 = 4.6% (2.7–7.2%), relative impact median 24 km/h, max 58. Cases that crash without error (17): misses avoid 0/170 and 1/170 of the crashes, the distance error 27/170 and 13/170 | The fitted distance error (0.24–0.71 m spread) matters only where the margin is a few decimetres. Misses decide: about 4% of runs crash, 54 of the 68 after a loss of 1 s or more while closing in. ASF and PV-RCNN do not differ beyond the noise. Error values fitted from one research car's log, not assumed. The first run, at `ab2d102` with one pattern per seed shared by all cases, gave 50/810 and 76/810 misses-only crashes, mostly from seed 9 (`output/grids/fitted_profiles_shared_seeds/`) |
| `fitted_target_offsets` | Does the fitted distance error still crash only the two cases with a few decimetres of margin when each car keeps one whole-run offset drawn from the K-Radar log (`offset` `target`)? The log has a few cars read 1–2.3 m too far for their whole track, which one Gaussian almost never gives under 25 m (`output/kradar/tail_check/`) | 2058 | 2026-11-23 | Windows 11, `86756ab` | 81 safe cases, 810 runs per detector, misses off. ASF 15/810 = 1.9% in 4 cases (was 11/810 in 2): the two low-margin cases as before, plus `1595368` and `1553490` (2.50 and 2.80 m left without error), both after drawing ASF's +2.26 m car. That car was drawn in 15 runs: 2 crashes, 2 more ended within 0.6 m, the gap shrank by about 2–3 m in most. PV-RCNN 12/810 = 1.5% in 3 cases (was 10/810 in 2): its largest offset (+1.08 m) was drawn in 15 runs, all in cases with 1.8 m or more, no crash; the third case (`1605269`, 4.83 m) crashed with a +0.09 m offset because HiDrive never braked harder than 3.5 m/s² (31 runs in each grid stay below 4 m/s², this is the only crash among them) | A car misread by about 2 m for its whole track turns cases with 2–3 m margin into crashes; the pooled share moves little (1.4 to 1.9% for ASF) because such a car is 1 of 46 in the log. Whether it is 1 in 46 is uncertain: in a half split the extreme cars fall in one half, so fitting on the other half does not reproduce them |
| `fitted_offset_tolerance` | How large may a whole-run too-far offset be before the 81 safe TASC car-car cases start to crash, and where do the K-Radar cars fall? Offset 0–4 m in 0.5 m steps, the same for every car (`fitted`, `offset` `fixed`); without a random part, and with PV-RCNN++'s or ASF's spread around each car's mean. Written before running: if a case crashes once the offset exceeds its margin without error, the no-spread line follows the margins (2 cases up to 1.5 m, 6 at 2 m, 13 at 2.5 m, 23 at 3 m, 58 at 4 m); a large gap means something else counts too (one case with 1.82 m did not crash at +2.26 m in `fitted_target_offsets`). Read off the offset at which 5% of cases (4) crash, expected between 1.5 and 2 m, and count the log's cars above it | 9800 | 2026-11-23 | Windows 11 | pending | pending |

## Notes per grid

### Scenarios and the 2026-11-08 check
- `gidas_1549178` and `gidas_1554254` do not crash without error ("safe scenarios" above);
  `gidas_1554431` crashes without error at 10.5 km/h. The data are TASC, although the names say GIDAS.
- `smoke`, `range_factors`, `ou_size` and `lost_target` ran on `main` at `247f6cc` with no local changes
  and 0 failed runs. Each run was compared with the simulation-studio sweeps of 2026-11-01 to 11-03
  (collision, impact speed, trigger time, minimum gap and TTC): `range_factors` 1899/1899 and
  `lost_target` 3000/3000 identical; `ou_size` 279/279 identical (its 3 `no_error` runs had no
  counterpart there and match `range_factors`).
- CIs are Wilson 95% intervals on the crash count.

### `range_factors`
- Detection seeds 0–49 miss 11.9% of frames on average (IID 10.3%, T = 0.2 s 11.2%, 0.5 s 12.7%,
  1 s 13.4%) against the set 10%, so 30/400 may be high; `detection_seeds_50_99` is the check.
- Size runs once per level and scenario (no randomness), so where crashes start is a coarse boundary.
- Identification at 1% gives a wrong class in only 3 of 30 seeds, so 0/60 there proves little.

### `ou_tau`
- Seeds 1–30 (`ou_size` used 0–29). The tau 0.5 s runs on the 29 shared seeds equal `ou_size` run by run
  (261/261), and 0 of 1803 failed.
- OU changes every 0.01 s step, faster than the 0.05 s sensor frame of `detection`, so tau 0.05 s is
  close to independent noise per frame.
- "Early" means the first trigger is more than 0.1 s before the no-error run on the same scenario.
- `gidas_1554431` (crashes without error at 10.5 km/h): at tau 0.5 s 18, 15, 12, 3 of 30 crash at 5, 10,
  20, 50%, median impact 18.7, 20.5, 24.7, 18.6 km/h; at tau 0.05 s 16, 7, 0, 0 of 30.

### `ou_bias`
- `bias_pct` uses the same distance law as `mae_pct`, so the same percentage gives the same mean error size. At
  braking start (no-error run) 1% is about 0.12 m on `gidas_1549178`, 0.16 m on `gidas_1554254` and 0.23 m on
  `gidas_1554431`.
- Bias-only runs have no randomness: one run per level and scenario, so where crashes start is a coarse boundary.
- Random 5% with bias 0 equals `ou_tau` 5% at tau 0.5 s run by run (90/90). With `bias_pct` 0 the plugin skips
  the bias, and 120 `ou_tau` runs repeated exactly before the grid ran.
- `size` scale 1.1 crashed `gidas_1554254` in `range_factors`, while bias +10% here does not: the size law
  (scale − 1) × r gives a larger offset at that range (1.89 against 1.64 m when braking starts).

### `size_geometry`
- `box` changes only the reported length; `keep: near_end` also moves the centre by half the length error along
  the line of sight, so the end facing the ego stays where it is. `size` (range scaled by an assumed size) is
  the camera-type link and gives much larger errors: scale 1.1 is 1.89 m at braking start on `gidas_1554254`, against 0.25 m here.
- The first trigger moves only on `gidas_1554254` at +20% (3.20 → 3.16 s) and on `gidas_1554431` (3.23 s without
  error; 3.28, 3.24, 3.21, 3.19 s at −20, −10, +10, +20%). Why a longer box changes nothing on `gidas_1549178`
  is not known; the controller is a black box here.
- Which point a real perception system measures right is an assumption, not a result of this grid.

### `lost_target`
- The vanish reference is the detection groups of `range_factors`: same seeds, same misses.
- `frozen` holds the speed difference of the last seen step, so its distance does not follow the ego's
  braking; `ou_speed` holds the object speed and uses the ego's live speed. No `ou_speed` run without OU
  exists, so 17/400 is with OU only.
- OU enters only as the error of the last seen reading and stays constant through a miss.

### TASC cases (`tasc_baseline`, `tasc_tolerance`, `tasc_bicycle`)
- Source: the teacher's upload of 2026-11-11 (Cut-in 7, Rear-end car-car 110, Rear-end car-cyclist 32 files), imported
  with `python -m pipeline import-tasc`. The files stay out of Git (teacher data, public repository); each registry
  entry in `pipeline/scenarios/local/scenarios.json` keeps the SHA-1 of its source file.
- Scope changed on 2026-11-15: `import-tasc` now keeps only cases where the ego's front runs into the other road user,
  119 of 149 (car-car 98, cyclist 21); see `docs/TASC_SCENARIOS.md`. The runs recorded here used the import of
  2026-11-11 below, which also held 5 cut-in, 3 car-car and 3 cyclist cases that are now skipped. All 11 crashed without
  error; the results on cases that are safe without error are unchanged.
- 130 of 149 imported on 2026-11-11. Skipped: 7 whose boxes overlap from the start (car-car 1553190, 1556158, 1571692; cut-in 1539179,
  1567320; cyclist 1587666, 1614846), 6 car-car copies of cut-in cases (the teacher's cut-in `_s` files swap the roles
  and have their own road), and 6 cyclist cases where object_2, the car, strikes the cyclist object_1 from behind.
- Those 6 were first run with the trajectories swapped: in 5 the ego jumped about 10 m along the road at brake onset.
  The road follows object_1's path, so a swap needs a road along the new ego's path; they are skipped until one exists.
- Cyclists are a 5.0 x 1.8 m car box in the files (category `car`, model `car_white.osgb`, the same as the ego), so
  the `tasc_cyclist_*` results are about a slow car-sized target.
- `tasc_bicycle` (2026-11-13, 1080 runs, none failed): `import-tasc --bicycle` writes the same 24 cases a second time
  as `tasc_bicycle_*`, with object_2 as category `bicycle`, a 1.8 x 0.6 x 1.7 m box and `cyclist.osgb`. The size is
  assumed; the files hold none. The box stays centred on the trajectory point. Groups and levels are those of
  `tasc_tolerance`, so each case compares with its car-box run.
  - HiDrive brakes for the bicycle as for the car. Without error 4 of 24 crash with either box, the same 4 cases
    (`1554559`, `1555622`, `1588450`, `1598752`), 3–4 km/h slower with the bicycle box.
  - Crashes, car box against bicycle box: OU 5% 40/240 and 40/240, OU 10% 35/240 and 37/240, OU 20% 27/240 and
    28/240, bias +5 to +20% 4/24 at every level with both, 10% misses 44/240 and 45/240.
  - In the 20 cases that are safe without error, the minimum gap changes by −0.18 to +0.23 m: HiDrive brakes on the
    distance to the box, so a shorter box moves the stopping point, not the gap.
  - These runs were made before the importer change was committed (the grid notes "files differ from commit c9ecdde").
- Cut-in: contact is at the side, with the cutting car faster than the ego, and HiDrive never triggers in any of the 5
  cases. A range error cannot change them; a lateral or lane-assignment error with a controller that reacts to cut-ins
  could.
- Polyline roads make esmini report "Last geometry of road 0 does not end at road end", so those runs are
  `completed_with_warnings`. The shared `gidas_1554254` and `gidas_1554431` give the same line; results are unaffected.
- Check (first run, shared seeds): the 68 OU and bias runs of `tasc_car_1554254` and `tasc_car_1554431` equal the
  `ou_tau` (tau 0.5 s) and `ou_bias` runs with the same seed. Since `407795b` the TASC copies draw other samples than
  the `gidas_*` scenarios, so only the bias runs still match.
- Car-car safe cases by margin without error (minimum gap / range at braking start), crashes at +20% bias, OU 10% and
  10% misses: under 10%, 3 cases, 3, 10/30 and 7/30; 10–15%, 18 cases, 17, 20/180 and 20/180; 15–20%, 5 cases, 2, 1/50
  and 4/50; 20–30%, 47 cases, 1, 10/470 and 43/470; over 30%, 8 cases, 0, 0/80 and 2/80. Random error follows the margin,
  misses much less. The two cases that crash already at OU 5% and bias +5% (`1571693`, `1620061`, ego 95–100 km/h) keep
  0.2–0.3 m without error; the third case at OU 5% (`1611189`, 1/10) keeps 2.0 m.
- Per-case table: `output/grids/tasc_tolerance/per_case.csv`, with `analyse_tolerance.py` and `tolerance_rates.py`
  (bootstrap over cases, crashes per seed, crashes by margin) next to it. The same files for the first run are in
  `output/grids/tasc_tolerance_shared_seeds/`.

### `fitted_profiles`
- Error model and parameters: `pipeline/errors/fitted.py` with the parameter file from `python -m pipeline fit-kradar`
  at `9ecc56b` (sha256 starting `549dba29f9a7`), then in `output/kradar/fit/`; the same file is in Git as
  `pipeline/kradar/parameters.json` since `82c4eb0`. The K-Radar tables are not in Git.
  Rows per range band (`condition` `range`), lead predicted with the object speed held while missed, as in `lost_target`.
  Values are fitted from a paired log of one research car, not assumed; ASF and PV-RCNN are the two detectors fitted.
- Generator check: the plugin alone, 3000 seeds of 10 s per band with no esmini (`gen_check.py`), gives the fitted
  miss share in every band (for example PV-RCNN 5.72% against 5.71% at 0–25 m), the same share in the first frame, and
  the fitted spread (0.242 against 0.241 m). In the grid the outer bands read a little higher (ASF 25–45 m 14.2%
  against 12.0%): the miss runs are pooled over bands, so a miss that starts farther out carries on into the next band.
  Complete miss runs are shorter than in the log (ASF mean 3.7 against 5.0 frames) because a 10 s run cannot hold a
  whole long one; the offline check shows the same.
- Shared seeds: until `407795b` every plugin drew its random numbers from the seed and the target id only, so a seed
  gave the same miss pattern (and the same OU draws) in every case. The first run of this grid (`ab2d102`, kept in
  `output/grids/fitted_profiles_shared_seeds/`) got 44 of 81 (ASF) and 74 of 81 (PV-RCNN) misses-only crashes from
  seed 9 alone, a loss of about 3–5 s early in the approach that every case shared. Earlier TASC grids ran that way:
  in `tasc_tolerance`, seeds 2 and 4 give 47 of the 55 OU 10% crashes on safe car-car cases and seed 10 gives 22 of the
  42 miss crashes, so their confidence intervals, which treat runs as independent, are too narrow.
- Since `407795b` each scenario draws its own samples (`seed_scope` `scenario`, the default). `"seed_scope": "shared"`
  repeats the old runs: 17 runs from the first `fitted_profiles` run and `tasc_tolerance` repeated exactly with it.
- ASF's log has one loss of 149 frames (14.9 s); started already missed, a run draws its remaining length in
  proportion to the run lengths, so this one loss gives 16% of such starts a remaining miss over 4 s.
- Scripts and full output: `rates.py` (crash shares, bootstrap over cases, crashes by miss length), `analyse_fitted.py`,
  `gen_check.py` and `analysis.txt` in `output/grids/fitted_profiles/`; `per_seed.py` with the first run.

### `fitted_target_offsets`
- Model: `fitted` with `offset` `target`. Each target draws one of the 46 per-track mean errors of the log (tracks with
  20+ paired frames) for the whole run, in place of b; the rest is OU + white noise with the spread around each track's
  mean (ASF 0.32 m at 0–25 m, PV-RCNN 0.12 m) and its tau (2.0 and 1.4 s). Written by `fit-kradar` since `86756ab`
  (`target_offset` in `pipeline/kradar/parameters.json`; every older value unchanged). `offset` `none`, the default,
  repeats the old model.
- Tail check before the run (`output/kradar/tail_check/`, no esmini): the old model has the right spread (ASF 0.58 m,
  PV-RCNN 0.27 m) but the wrong shape. Under 25 m it gives > 1 m too far in 0.08% (ASF) and 0% (PV-RCNN) of frames,
  the log 1.4% for both, each from one car: ASF `kradar_008:R:T0004` +2.26 m down to 11 m (PV-RCNN reads it right),
  PV-RCNN `kradar_055:R:T0003` +1.08 m in snow. The near-end (rear) error is the same, so not a length error.
  The new model gives these cars (in-sample), but its middle is still wider than the log (ASF robust spread 0.46
  against 0.25 m). Fitted on half of the recordings it does not reproduce the other half's extreme cars, because
  they fall in one half: the share of such cars rests on 1–3 cars per detector.
- Scripts and output: `analysis.py` and `analysis.txt` in `output/grids/fitted_target_offsets/`.
