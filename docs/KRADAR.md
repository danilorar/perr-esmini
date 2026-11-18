# K-Radar: measured errors instead of assumed ones

Until now our error values were assumed (for example a random distance error of 5–20% of the distance). The teacher's
K-Radar tables let us measure them: they hold where each car really was and where real detectors put it. This page
says what the data is, how `fit-kradar` turns it into error values, what came out, and how to use it.

## Words used here

- **Reference box:** where an object really was, labelled by people on lidar points, then refined. This is the truth.
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
- The teacher's README next to the tables describes every column.

What we found in the data:

- About half of the frames were used to train the detectors, and there they look better (ASF finds 83% of the cars
  there, 71% elsewhere). We use only the other half, K-Radar's test frames.
- PV-RCNN++ boxes sit 2.55 m behind and 0.31 m left of the reference, the same everywhere. `fit-kradar` shifts them
  back.
- L4DR has no box near any reference object in 41% of its frames, in stretches. We do not use it.

## Why the tables are not in Git

This repository is public. K-Radar's licence (CC BY-NC-ND) does not allow sharing changed versions of the data, and the
teacher's tables are such a version. So they stay outside Git. What is in Git, in `pipeline/kradar/`:

| File | What it is |
|---|---|
| `parameters.json` | the fitted values; numbers only, no boxes. The `fitted` plugin reads it |
| `tables.sha256` | the sha256 fingerprint of each of the teacher's tables |
| `meta/` | K-Radar's train/test split (github.com/kaist-avelab/K-Radar) and the weather of each drive (K-Radar paper, Table 5) |

Without the tables you can still run the `fitted` plugin. With them you can redo the fit and check it.

## Redo the fit

1. Get the four tables from the teacher. Keep `reference/` and `candidates/` as they are, in a folder outside the repo.
2. Run:

```bash
pip install pandas pyarrow
python -m pipeline fit-kradar <data folder>
```

It takes a few seconds. It stops if a table is not the teacher's version, and it ends with:

```
asf: same as pipeline/kradar/parameters.json (largest difference 0)
pvrcnn: same as pipeline/kradar/parameters.json (largest difference 0)
```

All tables and checks are in `output/kradar/fit/summary.md`.

## How the fit works

1. Take K-Radar's test frames only.
2. Match each detector box to the nearest reference box in the same frame, if the centres are less than 3 m apart.
3. Follow the **lead**: the nearest reference vehicle ahead whose centre is less than 2 m to the side, when it is a Sedan.
   This gives 5,824 frames of 111 cars in 48 drives.
4. Distance error in a frame = distance to the detector box minus distance to the reference box. A frame with no
   matched box is a miss.
5. Fit the model `error = b + OU + white noise`:
   - **b**, the mean error, and **sigma**, the spread, per distance band: 0–25, 25–45 and 45–72 m.
   - **tau**, how long an error lasts, from how similar the error of the same car is 0.1 to 3 s later, over all
     distances.
6. Misses: the share of missed frames, and the length of every run of missed frames.
7. Check: fit on half of the drives and test on the other half. 88% (ASF) and 87% (PV-RCNN++) of the other half's
   errors fall inside the first half's 90% range.

## Results

Lead car, test frames, all distances:

| | ASF | PV-RCNN++ | Assumed before |
|---|---|---|---|
| Bias b | +0.09 m | −0.01 m | 0 |
| Spread sigma | 0.58 m | 0.27 m | |
| Spread / distance, per band | 1.0–2.0% | 0.5–1.4% | 5–20% (mean error) |
| tau | 7.1 s | 4.9 s | 0.5 s |
| Frames missed | 11% | 9% | set by hand |
| Mean miss length | 0.50 s | 0.36 s | 0.5 s |

- The real distance error is small and slow: almost no bias, a spread of at most 2% of the distance, and an error that
  lasts several seconds.
- Most of ASF's larger spread comes from a few cars it reads about 2 m too far for many seconds.
- Misses come in more one-frame flickers and more long losses than a simple on/off model gives, so the plugin draws
  miss lengths from the data.

In the simulation (grid `fitted_profiles`: the 81 TASC car-car cases that HiDrive handles without error, 10 seeds,
810 runs per detector):

| Error | ASF | PV-RCNN++ |
|---|---|---|
| Distance error only | 11 crashes (1.4%) | 10 crashes (1.2%) |
| Misses only | 36 (4.4%) | 32 (4.0%) |
| Both | 43 (5.3%) | 37 (4.6%) |

- Distance error alone crashes only the two cases that keep 0.20 and 0.32 m without error. The assumed 5/10/20% error
  crashed 2.0/5.1/7.9% of runs in the same cases (grid `tasc_tolerance`).
- Misses decide: 54 of the 68 miss crashes follow a loss of 1 s or more while closing in.

Details of both grids: [EXPERIMENTS.md](EXPERIMENTS.md).

## Use it in a simulation

```json
{"errors": [{"type": "fitted", "profile": "pvrcnn", "condition": "range", "misses": false}]}
```

- `profile`: `asf` or `pvrcnn`.
- `condition`: `range` uses the band of the current distance; `all` uses one value for all distances.
- `misses: false` gives the distance error only; `range_error: false` gives the misses only.
- The other settings are in the README's error plugin table. Ready-made grid: `experiments/fitted_profiles.json`.

## Limits

- One research car and one dataset; ASF and PV-RCNN++ are research detectors, not a production sensor.
- Lead car only, Sedan only, up to 72 m.
- The values per weather and the per-band tau change between the two halves of the drives, so we do not use them.
  Only PV-RCNN++ clearly misses more in snow (18% of frames against 5% in normal weather).
