"""A car that drives itself along its lane, from what its own sensors see.

Only the pedals: the simulated roads have one lane and no width, so there is
no steering to do. Each step the autopilot takes the lowest of these
accelerations:

* **the car in front**, as the sensors see it (``perception.Seen``), with the
  Intelligent Driver Model and a time gap of 1.5 s, a little more than a
  human's 1.2 s. The gap it uses is the measured one minus twice its
  uncertainty, so a car seen badly is kept further away;
* **the stop line**, when it must stop there (a red light, a yellow it can
  still stop for, a give-way line that is not clear);
* **DriveNow's advice**: towards the advised speed, slowing only by lifting
  off, exactly as a DriveNow driver does;
* **what it cannot see yet**: no faster than it can stop, comfortably,
  within the distance where it would see a car standing still, and the
  same for a light it cannot read yet when the light's timing is not known;
* **emergency braking** (6 m/s²) when the object ahead would be hit within
  1.5 s, counting the slowest closing speed the measurement allows (a noisy
  estimate must not slam the brakes).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .perception import Seen


@dataclass
class AutopilotConfig:
    accel: float = 1.4         # m/s^2, IDM
    comfort_decel: float = 2.0  # m/s^2, IDM and the speed it can stop from in its sight
    time_gap: float = 1.5      # s
    min_gap: float = 2.5       # m standing still
    k_sigma: float = 2.0       # the gap used is the measured one minus this many sigmas
    aeb_ttc: float = 1.5       # s
    aeb_decel: float = 6.0     # m/s^2


def idm(v: float, v0: float, gap: float, dv: float, cfg: AutopilotConfig) -> float:
    v0 = max(v0, 0.1)
    free = 1 - (v / v0) ** 4
    if gap == math.inf:
        return cfg.accel * free
    s_star = cfg.min_gap + max(0.0, v * cfg.time_gap + v * dv / (2 * math.sqrt(cfg.accel * cfg.comfort_decel)))
    return cfg.accel * (free - (s_star / max(gap, 0.1)) ** 2)


def control(v: float, limit: float, seen: Optional[Seen], stop_at: Optional[float],
            target: Optional[float], coast_decel: float, accel: float, sight: float,
            cfg: AutopilotConfig = AutopilotConfig()) -> Tuple[float, str]:
    """Acceleration and what set it: 'free', 'leader', 'line', 'advice', 'sight' or 'aeb'.

    ``stop_at``: distance to where the car must stop, or None; ``target``: the advised
    speed, or None; ``sight``: how far ahead it can see an obstacle (m).
    """
    # Never faster than it can stop within what it can see.
    if sight < math.inf:
        limit = min(limit, math.sqrt(2 * cfg.comfort_decel * max(sight - cfg.min_gap, 0.0)))
    best, why = idm(v, limit, math.inf, 0.0, cfg), "free"
    if limit < v - 0.5 and best < 0:
        why = "sight"
    if seen is not None:
        gap = seen.gap - cfg.k_sigma * seen.sigma
        a = idm(v, limit, gap, -seen.rate, cfg)
        if a < best:
            best, why = a, "leader"
        # Emergency braking only when the closing is certain: the slowest closing speed the
        # measurement allows, on the measured gap.
        closing = -seen.rate - 2 * seen.sigma_rate
        if closing > 0.5 and max(seen.gap - seen.sigma, 0.0) / closing < cfg.aeb_ttc:
            return -cfg.aeb_decel, "aeb"
    if stop_at is not None:
        a = idm(v, limit, stop_at, v, cfg)
        if a < best:
            best, why = a, "line"
    if target is not None:
        a = min(max((target - v) / 1.0, -coast_decel), accel)
        if a < best:
            best, why = a, "advice"
    return max(best, -9.0), why
