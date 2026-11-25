# TASC scenarios: which cases the pipeline uses

HiDrive is a forward AEB. It picks a lead vehicle only in its own lane and ahead of it, and brakes for that vehicle.
It cannot act when the ego is hit from behind, when another vehicle cuts in and touches its side, or when a road
user crosses its path, and a range error cannot change those cases either. Since 2026-11-15 `import-tasc` therefore
keeps only the cases where the front of the ego (`object_1`) runs into the other road user (`object_2`).

The case files are teacher data and stay out of Git. Import them with
`python -m pipeline import-tasc <folder> [--bicycle]`; running it again removes cases that are now skipped from
`pipeline/scenarios/imported/`. `import_report.csv` there gives the reason for every skipped file.

## The upload of 2026-11-11

149 files in three folders, 143 accidents: 6 cut-in accidents also appear in the car-car folder.

| Folder | Files | Used | Overlap at start | Hit from behind | Side (cut-in) | Crossing | Copy of a cut-in case |
|---|---|---|---|---|---|---|---|
| Rear-end car-car | 110 | **98** | 3 | 0 | 2 | 1 | 6 |
| Rear-end car-cyclist | 32 | **21** | 2 | 5 | 2 | 2 | 0 |
| Cut-in | 7 | **0** | 2 | 1 | 4 | 0 | 0 |
| Total | 149 | **119** | 7 | 6 | 8 | 3 | 6 |

The used cases are `tasc_car_*` (98) and `tasc_cyclist_*` (21). With `--bicycle` the 21 cyclist cases are also
written as `tasc_bicycle_*`, with a bicycle-sized box.

## Skipped cases

| Reason | Car-car | Cyclist | Cut-in |
|---|---|---|---|
| Boxes overlap from the start | 1553190, 1556158, 1571692 | 1587666, 1614846 | 1539179, 1567320 |
| `object_2` hits the ego from behind | | 1553065, 1554327, 1580185, 1591276, 1602944 | 1604659 |
| Side contact (cut-in) | 1574615, 1613458 | 1555622, 1588450 | 1556273, 1576377, 1602918, 1635137 |
| Crossing, headings differ by more than 30° | 1621004 (46°) | 1547607 (100°), 1554559 (58°) | |
| Copy of a cut-in case | 1556273, 1567320, 1576377, 1602918, 1604659, 1635137 | | |

## How the importer decides

It looks at the first time step where the two boxes touch in the recorded trajectories, seen from the ego. It does not
run the controller.

1. The boxes already overlap at the first step: skipped.
2. The headings differ by more than 30°: crossing. Front contacts in this upload stay under 12°.
3. The centre of `object_2` is behind the centre of the ego: hit from behind.
4. The boxes overlap less across the ego's side than across its front, so `object_2` came in sideways: side contact.
5. Otherwise the ego's front runs into `object_2`: imported.

A car-car file whose case also exists in the cut-in folder is skipped as a copy; the cut-in file sets its roles.

Check against the no-error run of 2026-11-11 (`tasc_baseline`): all 11 cases that were imported then and are skipped
now crashed. HiDrive never braked in 9 of them (cut-in 5, car-car 3, cyclist 1555622). In cyclist 1554559 and 1588450
it braked 0.2 s before contact, when the cyclist entered the lane.

## Effect on recorded results

No grid was run again; these numbers come from the existing results restricted to the used cases.

- Without error, car-car is 81 of 98 safe (was 81 of 101). The 17 crashes are all front contacts, and HiDrive brakes
  in each of them.
- Without error, cyclist is 20 of 21 safe (was 20 of 24). In the remaining crash, 1598752, the cyclist rides about
  2 m to the side and swerves in front of the ego in the last second; HiDrive brakes at 7.9 m centre distance.
- The `tasc_tolerance` and `tasc_bicycle` conclusions use the cases that are safe without error (81 car-car, 20
  cyclist). All of them are still used, so those conclusions do not change.
- Of the 4 cyclist cases that crash without error in `tasc_bicycle`, only 1598752 is still used.
