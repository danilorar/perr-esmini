"""FOV: targets outside the sensor cone or beyond max range are not seen.

Bearing is the angle from the ego's heading to the target. A target outside
[-fov_deg/2, +fov_deg/2] or beyond max_range_m is marked seen=False for this
step. All downstream plugins leave unseen targets unchanged.
"""

import math 

SETTINGS = {'fov_deg': 60.0, 'max_range_m': 150.0}
RANGES   = {'fov_deg': (1.0, 180.0), 'max_range_m': (1.0, 500.0)}
LOG      = ('in_fov', 'bearing_deg')

class Error:
    def __init__(self, settings, run):
        self.half      = math.radians(settings['fov_deg'] / 2.0)
        self.max_range = settings['max_range_m']

    def perceive(self, step, t, ego, targets):
        for target in targets:
            dx = target['true']['x'] - ego['x']
            dy = target['true']['y'] - ego['y']
            bearing = math.remainder(math.atan2(dy, dx) - ego['heading'], 2 * math.pi)
            in_fov  = abs(bearing) <= self.half and target['true_range'] <= self.max_range
            if not in_fov:
                target['seen'] = False
            target['log'].update(in_fov=int(in_fov), bearing_deg=round(math.degrees(bearing), 2))