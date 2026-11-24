"""Per-target outlier draw: once per track, with probability p_outlier, a target
gets a persistent bias drawn from N(0, sigma_outlier²) for its whole run. Normal
per-frame noise is added on top. p_outlier and sigma_outlier are caller-supplied.

Usage:
    ol = TargetOutliers(seed_string, p_outlier, sigma_outlier)
    bias = ol.draw(target_id)   # same value every call for the same target_id
"""
import random


class TargetOutliers:
    def __init__(self, seed_string, p_outlier, sigma_outlier):
        self._p = p_outlier
        self._sigma = sigma_outlier
        self._seed = seed_string
        self._cache = {}

    def draw(self, target_id):
        if target_id not in self._cache:
            rng = random.Random(f'{self._seed}:outlier:{target_id}')
            self._cache[target_id] = rng.gauss(0.0, self._sigma) if rng.random() < self._p else 0.0
        return self._cache[target_id]
