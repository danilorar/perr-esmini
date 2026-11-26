# K-Radar: measured errors instead of assumed ones

Until now our error values were assumed (for example a random distance error of 5–20% of the distance). The teacher's
K-Radar tables let us measure them: they hold where each car really was and where real detectors put it. This page
says what the data is, how `fit-kradar` turns it into error values, what came out, and how to use it.

## Words used here

- **Reference box:** where an object really was, labelled by people on lidar points, then refined. We take it as the
  truth, and check it where we can (see "Checks on the data").
- **Detector:** a program that finds cars in sensor data and gives one box per car per frame. Its boxes are what an
  AEB would get.
- **Frame:** one time step of the data, 0.1 s.
- **Miss:** a frame in which the detector gives no box for a car that is there.

## The data

K-Radar is a public dataset from KAIST: 58 drives of one research car in Korea, in normal weather, rain, fog and snow.
The teacher made four tables from it:

| Table | One row is | Detector reads |
|---|---|---|
| `reference/kradar_P3.parquet` | a reference box; `track_id` follows one object through a drive | (labelled by people) |
| `candidates/kradar_asf.parquet` | a box from the detector ASF | camera, 4D radar, lidar |
| `candidates/kradar_pvrcnn.parquet` | a box from the detector PV-RCNN++ | lidar |
| `candidates/kradar_l4dr.parquet` | a box from the detector L4DR | 4D radar, lidar |

- Join the tables on `recording_id` and `frame_idx`. Detector boxes are not matched to reference boxes; that is our job.
- Detectors cover only the area ahead (about 76 m forward, 16 m to each side) and only two classes, Sedan and
  BusOrTruck.
- The teacher's README next to the tables describes every column. The detector tables also carry ids from three
  trackers; the fit does not use them.

**Use the corrected detector tables of 2026-11-25.** They replace the first set (2026-11-17); do not mix the two.
In the first set, PV-RCNN++ boxes sat 2.54 m behind and 0.30 m left of the reference (`fit-kradar` used to shift them
back), 17% of ASF's boxes and about half of L4DR's sat in the wrong frames, and ASF lacked 707 boxes. The corrected
set has the same boxes in the right place. The wrong frames had made ASF look twice as noisy as it is (spread 0.58 m,
now 0.27 m), with a car read 2.26 m too far and losses of up to 14.9 s; none of that is in the corrected data.

What we found in the data:

- About half of the frames were used to train the detectors, and there they look better (ASF finds 90% of the cars
  there, 78% elsewhere). We use only the other half, K-Radar's test frames.
- L4DR often gives two boxes for one car: in the test frames, 6,677 boxes have a more confident box of the same class
  less than 1 m away. `fit-kradar` keeps only the most confident one.

## Why the tables are not in Git

This repository is public. K-Radar's licence (CC BY-NC-ND) does not allow sharing changed versions of the data, and the
teacher's tables are such a version. So they stay outside Git. What is in Git, in `pipeline/kradar/`:

| File | What it is |
|---|---|
| `parameters.json` | the fitted values; numbers only, no boxes. The `fitted` plugin reads it |
| `tables.sha256` | the sha256 fingerprint of each of the teacher's tables (corrected detector set) |
| `meta/` | K-Radar's train/test split (github.com/kaist-avelab/K-Radar) and the weather of each drive (K-Radar paper, Table 5) |

Without the tables you can still run the `fitted` plugin. With them you can redo the fit and check it.

## Redo the fit

1. Get the four tables from the teacher: the reference table and the corrected detector tables of 2026-11-25. Keep
   `reference/` and `candidates/` as they are, in a folder outside the repo.
2. Run:

```bash
pip install pandas pyarrow
python -m pipeline fit-kradar <data folder>
```

It takes about half a minute. It stops if a table is not the teacher's version, and it ends with:

```
asf: same as pipeline/kradar/parameters.json (largest difference 0)
pvrcnn: same as pipeline/kradar/parameters.json (largest difference 0)
l4dr: same as pipeline/kradar/parameters.json (largest difference 0)
```

All tables and checks are in `output/kradar/fit/summary.md`.

## How the fit works

1. Take K-Radar's test frames only. Drop L4DR's double boxes.
2. Match each detector box to the nearest reference box in the same frame, if the centres are less than 3 m apart.
3. Follow the **lead**: the nearest reference vehicle ahead whose centre is less than 2 m to the side, when it is a Sedan.
4. Distance error in a frame = distance to the detector box minus distance to the reference box. A frame with no
   matched box is a miss.
5. Check the data (next section) and leave out what is a fault of the reference. This leaves 5,603 frames of 106 cars
   in 45 drives, the same rows for every detector.
6. Fit the model `error = b + OU + white noise`:
   - **b**, the mean error, and **sigma**, the spread, per distance band: 0–25, 25–45 and 45–72 m.
   - **tau**, how long an error lasts, from how similar the error of the same car is 0.1 to 3 s later, over all
     distances.
7. Misses: the share of missed frames, and the length of every run of missed frames.
8. Check: fit on half of the drives and test on the other half. 94% (ASF), 91% (PV-RCNN++) and 94% (L4DR) of the other
   half's errors fall inside the first half's 90% range.

## Checks on the data

The three detectors read different sensors, so an error that all three show alike is most likely in the reference.

- **Timing.** For each drive, the frame lag at which detector and reference fit best. Over all drives it is 0 for every
  detector. In three drives every detector is 2 or more frames off the same way (kradar_003: 2–3 frames,
  kradar_041: 5, kradar_052: 5–10): there the reference runs late. These drives are left out.
- **Single cars.** For each car, its mean error per detector. One car is read alike by every detector that sees it
  and far from all others (kradar_055 T0003, snow: +1.07 m by PV-RCNN++ and L4DR; modified z-score 3.6, limit 3.5).
  It is left out.
- **Shared part.** Even after this, most of the error is common to the three detectors: on frames where all three see
  the lead, their errors correlate about 0.7, and the per-car mean errors about 0.9. Split into a part they share and
  a part of their own:

| | ASF | PV-RCNN++ | L4DR |
|---|---|---|---|
| Spread of the error, all distances | 0.24 m | 0.24 m | 0.22 m |
| ... shared by all three | 0.20 m | 0.20 m | 0.20 m |
| ... the detector's own | 0.13 m | 0.12 m | 0.09 m |
| Own part under 25 m | 0.11 m | 0.10 m | 0.07 m |

  The shared part is either an error of the reference or an error all three detectors make; the data cannot tell
  which. The fitted values below contain both, so they are an upper bound for the detector's own error.

## Results

Lead car, test frames, all distances:

| | ASF | PV-RCNN++ | L4DR | Assumed before |
|---|---|---|---|---|
| Bias b | −0.03 m | −0.02 m | +0.01 m | 0 |
| Spread sigma | 0.27 m | 0.25 m | 0.24 m | |
| Spread / distance, per band | 0.5–1.2% | 0.4–1.1% | 0.4–1.2% | 5–20% (mean error) |
| tau | 4.2 s | 5.5 s | 4.1 s | 0.5 s |
| Frames missed | 5.7% | 8.2% | 4.9% | set by hand |
| Mean miss length | 0.26 s | 0.35 s | 0.25 s | 0.5 s |
| Longest miss | 1.8 s | 3.4 s | 1.6 s | |

- The real distance error is small and slow: almost no bias, a spread of at most about 1% of the distance, and an
  error that lasts several seconds. The three detectors are alike.
- No car is read more than 1 m off on average by any detector.
- Misses are short. PV-RCNN++ misses most, and all three miss two to four times as often in snow (10–19% of frames,
  about 5% in normal weather).

### Which model: one spread for all cars, or one offset per car

The fitted plugin can give every car the same bias and spread (`offset` `none`) or let each car keep the whole-run
offset of one real car (`offset` `target`). The second was added for the first tables, where ASF read one car 2.26 m
too far; that car came from the wrong frames. Run on the same cars and frames (500 replicas each,
`output/kradar/tail_check_20261126/`):

- PV-RCNN++ and L4DR: `none` gives the spread between cars of the log (0.15 m real, 0.15 m model for PV-RCNN++;
  0.17 against 0.14 m for L4DR) and the same 5–95% range of errors; the log's 1% tails are a little wider.
  `target` adds nothing.
- ASF: `none` gives a little less spread between cars (0.23 m real, 0.17 m model), because of one car ASF reads
  0.93 m too near (kradar_057 T0003, seen long enough by ASF only). `target` gives it; the half split does not
  reproduce it, since it rests on that one car.
- Both models leave out the rare frames more than 1 m off (0.1–0.3% of frames in the log), and both are a little wider
  in the middle than the log.

So `none` is the model to use; `target` stays as an option.

## Simulation results

The grids `fitted_profiles`, `fitted_target_offsets` and `fitted_offset_tolerance` in [EXPERIMENTS.md](EXPERIMENTS.md)
were run with the fit of the first tables (ASF spread 0.58 m, losses up to 14.9 s). Their ASF results no longer hold,
and the PV-RCNN++ values have changed a little (spread 0.27 to 0.25 m). They need a rerun with this fit. The
offset-only curve of `fitted_offset_tolerance` (same offset for every car, no spread) does not depend on the fit.

## Use it in a simulation

```json
{"errors": [{"type": "fitted", "profile": "pvrcnn", "condition": "range", "misses": false}]}
```

- `profile`: `asf`, `pvrcnn` or `l4dr`.
- `condition`: `range` uses the band of the current distance; `all` uses one value for all distances.
- `misses: false` gives the distance error only; `range_error: false` gives the misses only.
- `offset`: keep the default `none` (see above). `target` gives each car one offset for the whole run, drawn from the
  per-car mean errors of the log, plus the spread around them.
- The other settings are in the README's error plugin table. Ready-made grid: `experiments/fitted_profiles.json`.

## Limits

- One research car and one dataset; ASF, PV-RCNN++ and L4DR are research detectors, not a production sensor.
- Lead car only, Sedan only, up to 72 m.
- The errors are measured against the reference, which has its own error; 70–85% of the variance is shared by all
  three detectors (see "Checks on the data").
- The values per weather and the per-band tau change between the two halves of the drives, so we do not use them.
