"""Fixed-time traffic light plans and their green windows.

A plan is a cycle of phases. Each phase lasts some seconds and gives every
signal group a colour: ``G`` green, ``y`` yellow, ``r`` red. A signal group
is a set of approaches that always share the same colour; in the grid
networks of the base repository these are ``NS`` and ``EW``, like the
CycleRuleSet there.

Because the plan is fixed, the future is known exactly, and that is what
GLOSA needs: the next green windows for the approach the car is on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

Window = Tuple[float, float]


@dataclass
class Phase:
    duration: float
    states: Dict[str, str]  # group -> 'G' | 'y' | 'r'


@dataclass
class SignalPlan:
    phases: List[Phase]
    offset: float = 0.0
    groups: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.phases:
            raise ValueError("a plan needs at least one phase")
        if any(p.duration <= 0 for p in self.phases):
            raise ValueError("phase durations must be positive")
        if not self.groups:
            seen: List[str] = []
            for p in self.phases:
                for g in p.states:
                    if g not in seen:
                        seen.append(g)
            self.groups = seen

    @property
    def cycle(self) -> float:
        return sum(p.duration for p in self.phases)

    def _locate(self, t: float) -> Tuple[int, float]:
        """Phase index at absolute time ``t`` and seconds left in that phase."""
        tc = (t - self.offset) % self.cycle
        acc = 0.0
        for i, p in enumerate(self.phases):
            if tc < acc + p.duration - 1e-9:
                return i, acc + p.duration - tc
            acc += p.duration
        return len(self.phases) - 1, 0.0

    def locate(self, t: float) -> Tuple[int, float]:
        """Phase index at time ``t`` and the seconds left in it."""
        return self._locate(t)

    def state(self, t: float, group: str) -> str:
        i, _ = self._locate(t)
        return self.phases[i].states.get(group, "r")

    def phase_index(self, t: float) -> int:
        return self._locate(t)[0]

    def time_to_change(self, t: float, group: str) -> Tuple[float, str]:
        """Seconds until ``group`` changes colour, and the colour it changes to."""
        i, left = self._locate(t)
        current = self.phases[i].states.get(group, "r")
        elapsed = left
        n = len(self.phases)
        for k in range(1, n + 1):
            p = self.phases[(i + k) % n]
            s = p.states.get(group, "r")
            if s != current:
                return elapsed, s
            elapsed += p.duration
        return math.inf, current

    def green_windows(self, t: float, group: str, horizon: float = 240.0) -> List[Window]:
        """Green intervals for ``group`` from now (``t``) up to ``horizon`` seconds.

        Times in the result are relative to ``t``. A window already in
        progress starts at 0 or earlier (its true start), so callers can tell
        that the light is green right now.
        """
        i, left = self._locate(t)
        n = len(self.phases)
        cur_start = left - self.phases[i].duration  # <= 0
        segments: List[Tuple[float, float, str]] = []
        start = cur_start
        k = 0
        while start < horizon:
            p = self.phases[(i + k) % n]
            segments.append((start, start + p.duration, p.states.get(group, "r")))
            start += p.duration
            k += 1
            if k > 10_000:
                break
        windows: List[Window] = []
        for s, e, st in segments:
            if st != "G":
                continue
            if windows and abs(windows[-1][1] - s) < 1e-9:
                windows[-1] = (windows[-1][0], e)
            else:
                windows.append((s, e))
        return [(s, e) for s, e in windows if e > 0]


def two_group_plan(
    green_a: float,
    green_b: float,
    yellow: float = 3.0,
    all_red: float = 2.0,
    offset: float = 0.0,
    groups: Sequence[str] = ("NS", "EW"),
) -> SignalPlan:
    """The classic two-phase cycle: A green, A yellow, all red, B green, B yellow, all red."""
    a, b = groups
    phases = [
        Phase(green_a, {a: "G", b: "r"}),
        Phase(yellow, {a: "y", b: "r"}),
    ]
    if all_red > 0:
        phases.append(Phase(all_red, {a: "r", b: "r"}))
    phases += [
        Phase(green_b, {a: "r", b: "G"}),
        Phase(yellow, {a: "r", b: "y"}),
    ]
    if all_red > 0:
        phases.append(Phase(all_red, {a: "r", b: "r"}))
    return SignalPlan(phases=phases, offset=offset, groups=list(groups))
