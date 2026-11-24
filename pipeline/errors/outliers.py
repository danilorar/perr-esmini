"""Per-target outlier draw: once per track, with probability p_outlier, a target
gets a persistent z-score drawn from N(0, 1). The caller multiplies by the
appropriate sigma to get the actual bias.

Using z-scores (not pre-scaled biases) lets each caller apply sigma at the
current observed range/speed, so the outlier magnitude scales naturally with
the per-frame noise level (e.g. larger range → larger range outlier).

Usage:
    ol = TargetOutliers(seed_string, p_outlier)
    z  = ol.draw(target_id)   # N(0,1) or 0.0; same value every call per target_id
    bias = z * sigma           # caller supplies sigma for the current state
"""
import random


class TargetOutliers:
    def __init__(self, seed_string, p_outlier):
        self._p = p_outlier
        self._seed = seed_string
        self._cache = {}

    def draw(self, target_id):
        """z ~ N(0,1) or 0.0 (with probability 1-p_outlier). Same value every call."""
        if target_id not in self._cache:
            rng = random.Random(f'{self._seed}:outlier:{target_id}')
            self._cache[target_id] = rng.gauss(0.0, 1.0) if rng.random() < self._p else 0.0
        return self._cache[target_id]
