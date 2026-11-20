"""Where the car is, as a phone knows it.

The simulation knows every car's position exactly. A phone does not: its
satellite fix is a few metres off, comes once a second and about a second
late, and now and then drops out for a while (an underpass, tall buildings).
``Phone`` turns the true position into what such a phone reports, and
estimates from it the car's position along its route and its speed, in one
of two ways:

``raw``       the last fix as it is, however old;
``filtered``  a Kalman filter along the road (position and speed): it
              averages the noise, carries the estimate forward to "now"
              across the delay, and keeps estimating through a dropout,
              with an uncertainty that grows while no fix arrives.

Positions are distances along the car's route (map matching is assumed:
the car is on its route, only how far along is uncertain).
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Deque, Optional, Tuple


class Phone:
    def __init__(self, rng: random.Random, mode: str = "filtered", sigma_pos: float = 5.0,
                 sigma_speed: float = 0.5, period: float = 1.0, delay: float = 1.0,
                 dropout_rate: float = 1 / 300, dropout: Tuple[float, float] = (5.0, 20.0),
                 accel_noise: float = 1.5) -> None:
        self.rng = rng
        self.mode = mode
        self.sigma_pos = sigma_pos        # m: error of a fix along the road
        self.sigma_speed = sigma_speed    # m/s: error of the speed it reports
        self.period = period              # s between fixes
        self.delay = delay                # s a fix arrives late
        self.dropout_rate = dropout_rate  # per second: chance that the signal goes away...
        self.dropout = dropout            # ...for this long (s, uniform)
        self.accel_noise = accel_noise    # m/s^2: how much the speed may change unseen (filter)
        self._truth: Deque[Tuple[float, float, float]] = deque()  # (t, s, v)
        self._next_fix = 0.0
        self._silent_until = -1.0
        # Last fix (raw) or filter state at time _t (filtered)
        self._t: Optional[float] = None
        self._s = 0.0
        self._v = 0.0
        self._P = [[0.0, 0.0], [0.0, 0.0]]

    # -- the phone ---------------------------------------------------------------

    def tick(self, t: float, s: float, v: float) -> None:
        """The car is truly at ``s`` with speed ``v`` at time ``t``; a fix may come out."""
        self._truth.append((t, s, v))
        while len(self._truth) > 2 and self._truth[1][0] <= t - self.delay - 1.0:
            self._truth.popleft()
        if t < self._next_fix:
            return
        self._next_fix = t + self.period
        if t < self._silent_until:
            return
        if self.rng.random() < self.dropout_rate * self.period:
            self._silent_until = t + self.rng.uniform(*self.dropout)
            return
        # The fix describes where the car was ``delay`` seconds ago.
        tm = t - self.delay
        past = min(self._truth, key=lambda x: abs(x[0] - tm))
        z_s = past[1] + self.rng.gauss(0.0, self.sigma_pos)
        z_v = max(0.0, past[2] + self.rng.gauss(0.0, self.sigma_speed))
        self._fix(past[0], z_s, z_v)

    # -- the estimate ------------------------------------------------------------

    def _fix(self, tm: float, z_s: float, z_v: float) -> None:
        if self.mode == "raw" or self._t is None:
            self._t, self._s, self._v = tm, z_s, z_v
            self._P = [[self.sigma_pos ** 2, 0.0], [0.0, self.sigma_speed ** 2]]
            return
        s, v, P = self._predict(tm)
        # Measurement of both position and speed: H = I, R = diag(sp^2, sv^2).
        r_s, r_v = self.sigma_pos ** 2, self.sigma_speed ** 2
        a, b, d = P[0][0] + r_s, P[0][1], P[1][1] + r_v
        det = a * d - b * b
        inv = [[d / det, -b / det], [-b / det, a / det]]
        K = [[P[0][0] * inv[0][0] + P[0][1] * inv[1][0], P[0][0] * inv[0][1] + P[0][1] * inv[1][1]],
             [P[1][0] * inv[0][0] + P[1][1] * inv[1][0], P[1][0] * inv[0][1] + P[1][1] * inv[1][1]]]
        ys, yv = z_s - s, z_v - v
        self._s = s + K[0][0] * ys + K[0][1] * yv
        self._v = max(0.0, v + K[1][0] * ys + K[1][1] * yv)
        # P = (I - K) P
        self._P = [[(1 - K[0][0]) * P[0][0] - K[0][1] * P[1][0], (1 - K[0][0]) * P[0][1] - K[0][1] * P[1][1]],
                   [-K[1][0] * P[0][0] + (1 - K[1][1]) * P[1][0], -K[1][0] * P[0][1] + (1 - K[1][1]) * P[1][1]]]
        self._t = tm

    def _predict(self, t: float):
        dt = max(0.0, t - self._t)
        s = self._s + self._v * dt
        v = self._v
        P = self._P
        q = self.accel_noise ** 2
        p00 = P[0][0] + 2 * dt * P[0][1] + dt * dt * P[1][1] + q * dt ** 4 / 4
        p01 = P[0][1] + dt * P[1][1] + q * dt ** 3 / 2
        p11 = P[1][1] + q * dt * dt
        return s, v, [[p00, p01], [p01, p11]]

    def estimate(self, t: float) -> Optional[Tuple[float, float, float]]:
        """(position along the route, speed, uncertainty of the position in m) now, or None."""
        if self._t is None:
            return None
        if self.mode == "raw":
            # The last fix as it is; its uncertainty is the fix's own plus how far the car
            # may have gone since (the phone knows the fix is old).
            age = t - self._t
            return self._s, self._v, math.hypot(self.sigma_pos, self._v * age)
        s, v, P = self._predict(t)
        return s, v, math.sqrt(max(P[0][0], 0.0))
