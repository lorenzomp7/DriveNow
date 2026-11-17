"""Learning a traffic light's timing from the cars that drive through it.

Many lights publish nothing. But the cars using DriveNow see them every
day: a car waiting at the stop line that drives off means the light has
just turned green; a car crossing the line means it is green; a car
standing at the line means it is red. From a few of these reports the
learner finds the cycle length, when in the cycle the green starts, and
how long it lasts, and from that forecasts the next greens.

It only works for lights with a fixed cycle (most urban lights at peak
hours). When the reports do not fit a fixed cycle, it gives no forecast.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

Window = Tuple[float, float]

WAIT_DIST = 8.0      # m: a car this close to the line and standing is waiting at the light
WAIT_SPEED = 0.5     # m/s
GO_SPEED = 2.0       # m/s: a waiting car faster than this has driven off
REACTION = 1.0       # s: the first car drives off about this long after the green starts


@dataclass
class Timing:
    cycle: float     # s
    anchor: float    # absolute time of one green start
    green: float     # s of green per cycle
    fit: float       # share of reports the model explains


class ProbeLearner:
    def __init__(self, window: float = 1800.0, min_onsets: int = 5, min_fit: float = 0.85) -> None:
        self.window = window            # s of reports kept
        self.min_onsets = min_onsets
        self.min_fit = min_fit
        self.onsets: Dict[str, List[float]] = defaultdict(list)  # approach -> green starts seen
        self.green: Dict[str, List[float]] = defaultdict(list)   # approach -> times a car crossed
        self.red: Dict[str, List[float]] = defaultdict(list)     # approach -> times a car stood at the line
        self._waiting: Dict[object, str] = {}
        self._fits: Dict[str, Tuple[float, Optional[Timing]]] = {}

    # -- reports ------------------------------------------------------------------

    def report(self, t: float, vid: object, edge: str, to_line: float, v: float, crossed: bool) -> None:
        """One car's state on the approach ``edge`` to a light.

        ``crossed`` is true at the step the car passes the stop line.
        """
        waiting_on = self._waiting.get(vid)
        if waiting_on is not None and (crossed or v > GO_SPEED or waiting_on != edge):
            self._add(self.onsets[waiting_on], t - REACTION, 10.0)
            del self._waiting[vid]
        if crossed:
            self._add(self.green[edge], t, 1.0)
        elif to_line < WAIT_DIST and v < WAIT_SPEED:
            self._waiting[vid] = edge
            self._add(self.red[edge], t, 1.0)

    def forget(self, vid: object) -> None:
        self._waiting.pop(vid, None)

    def _add(self, series: List[float], t: float, min_gap: float) -> None:
        if series and t - series[-1] < min_gap:
            return  # one report per light and second (or per green, for green starts)
        series.append(t)
        while series and series[0] < t - self.window:
            series.pop(0)

    # -- model --------------------------------------------------------------------

    def timing(self, edge: str, t: float) -> Optional[Timing]:
        cached = self._fits.get(edge)
        if cached is not None and t - cached[0] < 10.0:
            return cached[1]
        fit = self._fit(edge, t)
        self._fits[edge] = (t, fit)
        return fit

    def _fit(self, edge: str, t: float) -> Optional[Timing]:
        onsets = [o for o in self.onsets.get(edge, []) if o > t - self.window]
        if len(onsets) < self.min_onsets:
            return None
        # Cycle: the onsets line up at the true cycle and at its divisors; take the longest
        # cycle that lines them up nearly as well as the best one.
        scores = {}
        for c in range(30, 151):
            sx = sum(math.cos(2 * math.pi * o / c) for o in onsets)
            sy = sum(math.sin(2 * math.pi * o / c) for o in onsets)
            scores[c] = (math.hypot(sx, sy) / len(onsets), math.atan2(sy, sx))
        best = max(r for r, _ in scores.values())
        if best < 0.7:
            return None
        longest = max(c for c, (r, _) in scores.items() if r >= 0.9 * best)
        # The tolerance also lets neighbours of the true cycle through, which would drift
        # by a second per cycle: take the exact peak around it.
        cycle = max(range(max(30, longest - 3), longest + 1), key=lambda c: scores[c][0])
        anchor = (scores[cycle][1] / (2 * math.pi) * cycle) % cycle

        def phase(x: float) -> float:
            return (x - anchor) % cycle

        greens = sorted(phase(x) for x in self.green.get(edge, []) if x > t - self.window)
        reds = [phase(x) for x in self.red.get(edge, []) if x > t - self.window]
        if len(greens) < 5:
            return None
        # Green ends between the last crossings and the first cars that stop at red: few cars
        # reach the end of a green, so the crossings alone make it look too short.
        last_cross = greens[int(0.9 * (len(greens) - 1))] + 1.0
        later_reds = sorted(p for p in reds if p > greens[len(greens) // 2])
        green = last_cross
        if later_reds:
            first_stop = later_reds[int(0.05 * (len(later_reds) - 1))]
            if first_stop > last_cross:
                green = (last_cross + first_stop) / 2
        if not 5.0 <= green <= cycle - 5.0:
            return None
        ok = sum(1 for p in greens if p < green) + sum(1 for p in reds if p >= green)
        fit = ok / (len(greens) + len(reds))
        if fit < self.min_fit:
            return None
        return Timing(cycle=float(cycle), anchor=anchor, green=green, fit=fit)

    def green_windows(self, edge: str, t: float, horizon: float) -> Optional[List[Window]]:
        """Forecast green intervals (relative to ``t``), or ``None`` if the light is not learnt."""
        tm = self.timing(edge, t)
        if tm is None:
            return None
        start = -((t - tm.anchor) % tm.cycle)
        out: List[Window] = []
        while start < horizon:
            end = start + tm.green
            if end > 0:
                out.append((start, end))
            start += tm.cycle
        return out
