# TODOs — waiting before Block 4 can run

Block 4 (the full error-sweep grid) is on hold until both items below are done.
Do not start Block 4 without checking this file first.

## Pending

### April — K-Radar fitting / detection
- Finish fitting the detection (and possibly identification) parameters from K-Radar data.
- Result should land in `pipeline/kradar/parameters.json` and be usable via `{"type": "fitted", "profile": "..."}`.
- Block 4 needs the `fitted` group to be complete before the grid runs, so all error levels
  (assumed + fitted) are in one clean run.

### Aron
- TBD — confirm with Aron what their contribution is and update this file.

## Ready to run once both are done

- Block 4a: CCR grid (OU bias/noise sweep + miss rate + fitted, all controllers, 10 seeds)
- Block 4b: VRU-CB grid (same error levels, HiDrive only, 10 seeds)

See `BLOCKS.md` for the full spec.
