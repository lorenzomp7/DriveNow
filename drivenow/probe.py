"""Learning a traffic light's timing from the cars that drive through it.

Many lights publish nothing. But the cars using DriveNow see them every
day: a car waiting at the stop line that drives off means the light has
just turned green; a car crossing the line means it is green; a car
standing at the line means it is red. From a few of these reports the
learner finds the cycle length, when in the cycle the green starts, and
how long it lasts, and from that forecasts the next greens.

It only works for lights with a fixed cycle (most urban lights at peak
hours). When the reports do not fit a fixed cycle, it gives no forecast.

A learnt timing is checked against what the cars keep reporting. Over half an
hour a change of plan (cities switch plans at set times of day) or a broken
light barely moves the overall fit, so every refit also looks at the last few
minutes alone: cars standing at the line while the timing says green, and
cars driving off where it puts no green start. If there are too many, the
light loses its forecast and the reports from before are dropped, so that it
is learnt again from the new behaviour only.

A timing comes at one of two levels. ``confirmed``: plenty of reports over
many cycles, and nothing doubtful in the last minutes. ``suspected``: a few
cycles only, a looser fit, or some doubt in the last minutes; the advice uses
it only for small speed changes. Below that there is no forecast at all.
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
    level: str = "confirmed"   # or "suspected"
    onsets: int = 0            # green starts it rests on...
    span: float = 0.0          # ...and the time between the first and the last of them
    crossings: int = 0         # cars seen crossing the line


class ProbeLearner:
    def __init__(self, window: float = 1800.0, min_onsets: int = 5, min_fit: float = 0.85,
                 recent: float = 300.0, recent_reports: int = 10, check: bool = True,
                 wrong_share: float = 0.3, doubt_share: float = 0.15, onset_tolerance: float = 5.0,
                 levels: bool = True, suspect_onsets: int = 3, suspect_fit: float = 0.75,
                 confirm_cycles: float = 8.0, confirm_clean: bool = True) -> None:
        self.window = window            # s of reports kept
        self.min_onsets = min_onsets    # a confirmed timing needs this many green starts,
        self.min_fit = min_fit          # this overall fit,
        self.confirm_cycles = confirm_cycles  # its green starts spread over this many cycles,
        self.confirm_clean = confirm_clean    # and nothing doubtful in the last minutes
        self.levels = levels            # give suspected timings too (else only confirmed ones)
        self.suspect_onsets = suspect_onsets  # a suspected one needs only this many green starts
        self.suspect_fit = suspect_fit  # and this overall fit
        self.check = check              # drop a timing the last minutes contradict (see _recent_check)
        self.recent = recent            # s: the stretch a timing is checked against
        self.recent_reports = recent_reports  # cars standing at the line needed to judge from them
        self.wrong_share = wrong_share  # this share of them standing in the forecast green: wrong
        self.doubt_share = doubt_share  # this share: doubtful (suspected, not confirmed)
        self.onset_tolerance = onset_tolerance  # s: a green start this far off the forecast is off
        self.drops: List[Tuple[float, str]] = []  # (time, approach) of every timing dropped
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
        recent = "ok" if fit is None else self._recent_check(edge, fit, t)
        if recent == "wrong" and self.check:
            # The light no longer behaves as learnt: forget what came before and start again.
            cut = t - self.recent
            for series in (self.onsets, self.green, self.red):
                series[edge] = [x for x in series.get(edge, []) if x >= cut]
            self.drops.append((t, edge))
            fit = self._fit(edge, t)
            recent = "ok" if fit is None else self._recent_check(edge, fit, t)
        if fit is not None:
            confirmed = (fit.onsets >= self.min_onsets and fit.crossings >= 5 and fit.fit >= self.min_fit
                         and fit.span >= self.confirm_cycles * fit.cycle
                         and (recent == "ok" or not self.confirm_clean))
            fit.level = "confirmed" if confirmed else "suspected"
            if not confirmed and not self.levels:
                fit = None
        self._fits[edge] = (t, fit)
        return fit

    def _recent_check(self, edge: str, tm: Timing, t: float) -> str:
        """Does ``tm`` still match the last ``recent`` seconds: "ok", "doubtful" or "wrong".

        It looks at the two reports a wrong timing cannot explain away. Cars standing at
        the line when the timing says green (the error that matters: a promised green
        that is not there). And cars driving off, which mark green starts: they must
        fall where the timing puts them. The share of all reports explained, as in the
        overall fit, is no good here: where the green takes most of the cycle, a timing
        that says "green" most of the time is right most of the time by chance.
        """
        cut = t - self.recent
        reds = [x for x in self.red.get(edge, []) if x >= cut]
        onsets = [x for x in self.onsets.get(edge, []) if x >= cut]

        def phase(x: float) -> float:
            return (x - tm.anchor) % tm.cycle

        # Not the first seconds of the green: the first car is still pulling away.
        stood = sum(1 for x in reds if REACTION + 2.0 <= phase(x) < tm.green - 1.0)
        red_share = stood / len(reds) if len(reds) >= self.recent_reports else 0.0
        off = sum(1 for x in onsets if min(phase(x), tm.cycle - phase(x)) > self.onset_tolerance)
        if red_share >= self.wrong_share or (len(onsets) >= 3 and off > 2 * len(onsets) / 3):
            return "wrong"
        if red_share >= self.doubt_share or (len(onsets) >= 2 and off >= len(onsets) / 2):
            return "doubtful"
        return "ok"

    def _fit(self, edge: str, t: float) -> Optional[Timing]:
        onsets = [o for o in self.onsets.get(edge, []) if o > t - self.window]
        if len(onsets) < min(self.suspect_onsets, self.min_onsets):
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
        if len(greens) < 3:
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
        if fit < min(self.suspect_fit, self.min_fit):
            return None
        return Timing(cycle=float(cycle), anchor=anchor, green=green, fit=fit,
                      onsets=len(onsets), span=max(onsets) - min(onsets), crossings=len(greens))

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
