# Branch `Aron-dev`

This is Aron's own working branch. It replaces `Aron` for Aron's work from 2026-11-26.

## Why a new branch

Between 2026-11-24 and 2026-11-26, 24 commits were pushed to `Aron` that change files this work depends on:

- `pipeline/scenarios/local/` was renamed to `imported/`, so locally imported TASC scenarios are no longer found.
- The experiment grids were moved to `experiments/archive/`.
- The defaults of the shared `detection` plugin changed (range-dependent miss rate, new random stream), so earlier
  detection and lost-target results no longer reproduce with the same configs; `ou` now also clamps the range at 0.1 m.

At the same time, 6 local commits on `Aron` (the corrected K-Radar fit and the fitted offset tolerance grid) had
not been pushed yet, so the two lines had diverged. To keep these results reproducible and to avoid mixing the
two lines, this work is pushed here instead of being merged with the new `Aron`.

## What is in it

- `Aron` as of `b7ecfec` (2026-11-23), plus the 6 commits after it (`26cca32` to `30f5458`) and this note.
- None of the 24 commits pushed to `Aron` after `b7ecfec`.

`Aron` is left as it is for that work; Aron no longer pushes there.
Please do not push to `Aron-dev`. If you need something from it, open a pull request or ask Aron.
