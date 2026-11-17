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


class CyclePredictor:
    """Green probability per second of the cycle, learned from recent cycles."""

    def __init__(self, history: SignalHistory, cycle_ds: Dict[int, int], lookback_cycles: int = 20,
                 threshold: float = 0.8) -> None:
        self.h = history
        self.cycle_ds = cycle_ds          # signal datastream -> its cycle-second datastream
        self.lookback = lookback_cycles
        self.threshold = threshold
        self._cache: Dict[Tuple[int, int], Tuple[CycleInfo, List[float]]] = {}

    def cycle(self, ds: int, t: float) -> Optional[CycleInfo]:
        cds = self.cycle_ds.get(ds)
        if cds is None or cds not in self.h:
            return None
        resets = self.h.changes(cds, t - 6 * 90, t)
        resets = [tc for tc, _ in resets]
        if len(resets) < 2:
            return None
        lengths = [b - a for a, b in zip(resets, resets[1:])]
        lengths.sort()
        return CycleInfo(start=resets[-1], length=float(lengths[len(lengths) // 2]))

    def profile(self, ds: int, t: float) -> Optional[Tuple[CycleInfo, List[float]]]:
        info = self.cycle(ds, t)
        if info is None:
            return None
        key = (ds, int(info.start))
        if key in self._cache:
            return self._cache[key]
        C = int(round(info.length))
        hits = [0] * C
        n = 0
        cds = self.cycle_ds[ds]
        resets = [tc for tc, _ in self.h.changes(cds, info.start - (self.lookback + 2) * C, info.start)]
        for a, b in zip(resets, resets[1:]):
            if round(b - a) != C:
                continue  # a different programme was running
            n += 1
            for s in range(C):
                if self.h.code_at(ds, a + s + 0.5) in GREEN:
                    hits[s] += 1
        if n == 0:
            return None
        prof = [x / n for x in hits]
        self._cache[key] = (info, prof)
        if len(self._cache) > 5000:
            self._cache.clear()
        return info, prof

    def green_windows(self, ds: int, t: float, horizon: float) -> List[Window]:
        """Forecast green intervals (relative to ``t``), using only data up to ``t``."""
        got = self.profile(ds, t)
        if got is None:
            return []
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
