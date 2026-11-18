"""Learning how each car slows down and speeds up, from its own driving.

The advice assumes the car loses about 0.7 m/s^2 when the driver lifts off,
and gains about 1.3 m/s^2 when they accelerate gently. Real cars differ: an
electric car with strong regeneration slows down twice as fast, a car that
"sails" in neutral half as fast. With the wrong figure the advice brings the
car to the line too early (and it brakes) or too late (and it wastes green).

Each car measures itself. Once a second it compares its speed now with its
speed a second ago, but only over seconds in which the driver was doing one
thing: lifting off to slow down to the advice, or accelerating towards it.
Phone speed is noisy, so it keeps the median of many such seconds, and gives
its own figure only after ``min_samples`` of them.

Only the lifting-off figure is used by default. Acceleration measured this way
comes out far too low: in town a car rarely has room to accelerate as hard as
it would like (a car ahead, the limit reached within the second). In the
Hamburg simulation electric cars that accelerate at 2.0 m/s^2 were measured at
0.3 (median) to 0.9 (80th percentile). ``learn_accel`` turns it on anyway.
"""

from __future__ import annotations

from dataclasses import replace
from statistics import median
from typing import List, Optional, Tuple

from .glosa import DriverProfile


class ProfileLearner:
    def __init__(self, min_samples: int = 8, keep: int = 60, min_speed: float = 3.0,
                 learn_accel: bool = False) -> None:
        self.learn_accel = learn_accel
        self.min_samples = min_samples   # seconds of evidence before trusting the car's own figure
        self.keep = keep                 # most recent seconds kept for each figure
        self.min_speed = min_speed       # m/s: slower than this, rolling friction and stops dominate
        self.coast: List[float] = []     # m/s^2 measured while lifting off
        self.accel: List[float] = []     # m/s^2 measured while speeding up
        self._last: Optional[Tuple[float, float, Optional[str]]] = None

    def observe(self, t: float, v: float, doing: Optional[str]) -> None:
        """A speed reading at time ``t``; ``doing`` is "coast", "accel" or None (anything else)."""
        last = self._last
        self._last = (t, v, doing)
        if last is None or doing is None or doing != last[2]:
            return
        dt = t - last[0]
        if not 0.5 <= dt <= 2.0 or min(v, last[1]) < self.min_speed:
            return
        rate = (last[1] - v) / dt
        if doing == "coast" and 0.05 <= rate <= 2.5:      # more than that is braking (a leader, a light)
            _push(self.coast, rate, self.keep)
        elif doing == "accel" and 0.05 <= -rate <= 4.0:
            _push(self.accel, -rate, self.keep)

    def profile(self, default: DriverProfile) -> DriverProfile:
        """``default`` with the figures this car has measured well enough."""
        p = default
        if len(self.coast) >= self.min_samples:
            p = replace(p, coast_decel=median(self.coast))
        if self.learn_accel and len(self.accel) >= self.min_samples:
            p = replace(p, accel=median(self.accel))
        return p


def _push(series: List[float], x: float, keep: int) -> None:
    series.append(x)
    if len(series) > keep:
        del series[0]
