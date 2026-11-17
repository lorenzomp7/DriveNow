"""Recorded signal states, and a forecast that only looks at the past.

Codes in the Hamburg feed: 0 dark, 1 red, 2 amber, 3 green, 4 red-amber,
5 amber flashing, 6 green flashing, 9 unknown.

The lights on the corridor run a fixed cycle (45-90 s depending on the time
of day), but each green inside the cycle stretches or shrinks with demand.
So the forecast is a probability, built the way the TU Dresden study of
these lights does: for every second of the cycle, how often was this signal
green in the last cycles. A future second counts as green when that share
reaches ``threshold``.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

GREEN = {3, 6}
Window = Tuple[float, float]


class SignalHistory:
    """State changes per datastream, as recorded."""

    def __init__(self, rows: Sequence[Tuple[int, int, int]]) -> None:
        series: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for t, code, ds in rows:
            series[ds].append((t, code))
        self.times: Dict[int, List[int]] = {}
        self.codes: Dict[int, List[int]] = {}
        for ds, s in series.items():
            s.sort()
            self.times[ds] = [t for t, _ in s]
            self.codes[ds] = [c for _, c in s]

    @classmethod
    def load(cls, path: str) -> "SignalHistory":
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt") as f:
            r = csv.reader(f)
            next(r)
            return cls([(int(a), int(b), int(c)) for a, b, c in r])

    def __contains__(self, ds: int) -> bool:
        return ds in self.times

    def code_at(self, ds: int, t: float) -> int:
        ts = self.times.get(ds)
        if not ts:
            return 9
        i = bisect.bisect_right(ts, t) - 1
        return self.codes[ds][i] if i >= 0 else 9

    def changes(self, ds: int, t0: float, t1: float) -> List[Tuple[int, int]]:
        ts = self.times.get(ds)
        if not ts:
            return []
        i, j = bisect.bisect_left(ts, t0), bisect.bisect_right(ts, t1)
        return list(zip(ts[i:j], self.codes[ds][i:j]))

    def green_windows(self, ds: int, t: float, horizon: float) -> List[Window]:
        """True green intervals from the recording (relative to ``t``): the oracle."""
        out: List[Window] = []
        if ds not in self.times:
            return []
        cur = self.code_at(ds, t)
        start: Optional[float] = 0.0 if cur in GREEN else None
        if start == 0.0:
            # find when the current green started
            ts = self.times[ds]
            i = bisect.bisect_right(ts, t) - 1
            start = ts[i] - t if i >= 0 else 0.0
        for tc, code in self.changes(ds, t + 1e-6, t + horizon):
            if code in GREEN and start is None:
                start = tc - t
            elif code not in GREEN and start is not None:
                out.append((start, tc - t))
                start = None
        if start is not None:
            out.append((start, horizon + 60))
        return out


@dataclass
class CycleInfo:
    start: float    # absolute time the current cycle started
    length: float   # seconds
    source: str = "feed"   # "feed": the controller's cycle-second stream; "onsets": inferred; "flat": no cycle


class CyclePredictor:
    """Green probability per second of the cycle, learned from recent cycles.

    The cycle comes from the controller's cycle-second stream when it is
    live. That stream has long gaps in the recording (hours at some
    junctions), so otherwise the cycle is inferred from the signal's own
    green starts; and when there is no regular cycle at all (a main road
    that only turns red on demand), the forecast is the plain share of time
    the signal was green recently, the same for every future second.
    """

    def __init__(self, history: SignalHistory, cycle_ds: Dict[int, int], lookback_cycles: int = 20,
                 threshold: float = 0.8, window: float = 1800.0) -> None:
        self.h = history
        self.cycle_ds = cycle_ds          # signal datastream -> its cycle-second datastream
        self.lookback = lookback_cycles
        self.threshold = threshold
        self.window = window              # seconds of the past used when inferring
        self._cache: Dict[Tuple[int, int, str], List[float]] = {}

    # -- where are we in the cycle ------------------------------------------------

    def cycle(self, ds: int, t: float) -> Optional[CycleInfo]:
        return self._from_feed(ds, t) or self._from_onsets(ds, t)

    def _from_feed(self, ds: int, t: float) -> Optional[CycleInfo]:
        cds = self.cycle_ds.get(ds)
        if cds is None or cds not in self.h:
            return None
        resets = [tc for tc, _ in self.h.changes(cds, t - 6 * 90, t)]
        if len(resets) < 2:
            return None
        lengths = sorted(b - a for a, b in zip(resets, resets[1:]))
        length = float(lengths[len(lengths) // 2])
        if t - resets[-1] > 2 * length:
            return None  # the stream went quiet: stale
        return CycleInfo(start=resets[-1], length=length, source="feed")

    def _onsets(self, ds: int, t0: float, t1: float) -> List[float]:
        prev = self.h.code_at(ds, t0) in GREEN
        out = []
        for tc, code in self.h.changes(ds, t0 + 1e-6, t1):
            g = code in GREEN
            if g and not prev:
                out.append(float(tc))
            prev = g
        return out

    def _from_onsets(self, ds: int, t: float) -> Optional[CycleInfo]:
        onsets = self._onsets(ds, t - self.window, t)
        if len(onsets) < 6:
            return None
        diffs = sorted(b - a for a, b in zip(onsets, onsets[1:]))
        C = round(diffs[len(diffs) // 2])
        if not 30 <= C <= 150:
            return None
        regular = sum(1 for d in diffs if min(abs(d - k * C) for k in (1, 2, 3)) <= 3)
        if regular < 0.7 * len(diffs):
            return None
        # Anchor the cycle at the usual green start (circular mean of the phases).
        ang = [2 * math.pi * (o % C) / C for o in onsets]
        phase = (math.atan2(sum(map(math.sin, ang)), sum(map(math.cos, ang))) / (2 * math.pi) * C) % C
        start = t - ((t - phase) % C)
        return CycleInfo(start=start, length=float(C), source="onsets")

    # -- how likely is green ------------------------------------------------------

    def profile(self, ds: int, t: float) -> Optional[Tuple[CycleInfo, List[float]]]:
        if ds not in self.h:
            return None
        info = self.cycle(ds, t)
        if info is None:
            return self._flat(ds, t)
        key = (ds, int(info.start), info.source)
        if key in self._cache:
            return info, self._cache[key]
        C = int(round(info.length))
        if info.source == "feed":
            cds = self.cycle_ds[ds]
            resets = [tc for tc, _ in self.h.changes(cds, info.start - (self.lookback + 2) * C, info.start)]
            # Only cycles of the current length: a different programme was running otherwise.
            starts = [a for a, b in zip(resets, resets[1:]) if round(b - a) == C]
        else:
            first = self.h.times[ds][0]
            starts = [info.start - k * C for k in range(1, self.lookback + 1) if info.start - k * C >= first]
        if not starts:
            return self._flat(ds, t)
        hits = [0] * C
        for a in starts:
            for s in range(C):
                if self.h.code_at(ds, a + s + 0.5) in GREEN:
                    hits[s] += 1
        prof = [x / len(starts) for x in hits]
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[key] = prof
        return info, prof

    def _flat(self, ds: int, t: float) -> Optional[Tuple[CycleInfo, List[float]]]:
        """No cycle: the share of the recent past the signal was green."""
        ts, codes = self.h.times[ds], self.h.codes[ds]
        t0 = max(t - self.window, ts[0])
        if t - t0 < 600:
            return None  # too little history to say anything
        i = max(bisect.bisect_right(ts, t0) - 1, 0)
        green, cur = 0.0, t0
        while i < len(ts) and ts[i] < t:
            nxt = ts[i + 1] if i + 1 < len(ts) else t
            a, b = max(ts[i], t0), min(nxt, t)
            if b > a and codes[i] in GREEN:
                green += b - a
            i += 1
        return CycleInfo(start=t, length=1.0, source="flat"), [green / (t - t0)]

    def green_windows(self, ds: int, t: float, horizon: float) -> Optional[List[Window]]:
        """Forecast green intervals (relative to ``t``), using only data up to ``t``.

        ``None`` means no forecast at all (unknown signal, or too little history):
        not the same as "no green coming".
        """
        got = self.profile(ds, t)
        if got is None:
            return None
        info, prof = got
        C = len(prof)
        out: List[Window] = []
        start: Optional[float] = None
        now_green = self.h.code_at(ds, t) in GREEN
        for k in range(int(horizon) + 1):
            s = int((t + k - info.start) % C)
            g = prof[s] >= self.threshold
            if k == 0:
                g = now_green  # the present is observed, not predicted
            if k > 0 and now_green and start == 0.0 and not out and prof[s] >= 0.5:
                g = True       # a running green lasts at least as long as it usually does
            if g and start is None:
                start = float(k)
            elif not g and start is not None:
                out.append((start, float(k)))
                start = None
        if start is not None:
            out.append((start, horizon + 1.0))
        return out
