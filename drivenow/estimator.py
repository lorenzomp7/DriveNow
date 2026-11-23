"""How many cars stand at each light, from loop detectors and the DriveNow phones.

A loop at the stop line only says "occupied" or "free". That is enough for a queue:

- every change from free to occupied is a car: the passages of the last
  ``window`` seconds give the arrival rate on the lane;
- a loop occupied for longer than ``hold`` seconds has a car standing on it, the
  head of a queue. Behind it the cars that keep arriving join the queue:
  1 + rate x (time since the loop has been occupied);
- when it frees again the queue drives off: each passage takes one car away,
  and after ``hold`` seconds without one the queue has gone.

No signal timing is needed. On the road the same loop states come live from the
city's feed (see ``hamburg/live.py``).

Fused with the phones (``FleetDB.occupancy``): the standing cars the phones show
or reveal stay; the loops add the standing cars they imply and the phones do not
show, from the line backwards (over the edges before it, when the queue is longer
than the edge). A DriveNow car driving through close to the line without stopping
means no queue is left on a loop that is not occupied.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

STOPPED = 2.0  # m/s, as in advisor.py

Occupancy = Dict[str, List[Tuple[float, float]]]


class LaneQueue:
    def __init__(self, max_cars: int, hold: float = 3.0, window: float = 300.0) -> None:
        self.max_cars = max_cars
        self.hold = hold
        self.window = window
        self.occupied = False
        self.since = 0.0                 # when the loop changed to its current state
        self.passages: Deque[float] = deque()
        self.start: Optional[float] = None
        self._q0 = 0.0                   # cars standing when the loop freed after a standing period
        self._left = 0                   # passages since then
        self._discharging = False
        self._rate = 0.0                 # arrival rate when the loop was last occupied

    def rate(self, t: float) -> float:
        while self.passages and self.passages[0] < t - self.window:
            self.passages.popleft()
        span = min(self.window, max(t - (self.start if self.start is not None else t), 60.0))
        return len(self.passages) / span

    def event(self, t: float, occupied: bool) -> None:
        if self.start is None:
            self.start = t
        if occupied == self.occupied:
            return
        if occupied:
            self.passages.append(t)
            # While a car stands on the loop no one passes it: keep the rate from before.
            self._rate = self.rate(t)
            if self._discharging:
                self._left += 1
        else:
            if t - self.since > self.hold:
                # A car stood on the loop: the queue behind it starts to drive off.
                self._q0 = self._standing(self.since, t)
                self._left = 0
                self._discharging = True
        self.occupied = occupied
        self.since = t

    def _standing(self, since: float, t: float) -> float:
        return min(1.0 + self._rate * (t - since), float(self.max_cars))

    def cars(self, t: float) -> int:
        """Cars estimated to stand on the lane at ``t``."""
        if self.occupied and t - self.since > self.hold:
            return int(round(self._standing(self.since, t)))
        if self._discharging:
            if not self.occupied and t - self.since > self.hold:
                self._discharging = False   # no car for a while: the queue has gone
                return 0
            return max(int(round(self._q0 - self._left)), 0)
        return 0

    def drove_through(self) -> None:
        """A car crossed the line without stopping: no queue is left (the loop is not standing)."""
        self._discharging = False


class QueueEstimator:
    def __init__(self, lanes: Sequence[Tuple[str, int]], lengths: Dict[str, float],
                 upstream: Callable[[str], Optional[str]], car_space: float = 7.5, hold: float = 3.0) -> None:
        """``lanes``: (edge, lane index) with a loop at the line; ``upstream(edge)``: the edge
        before it that its queue reaches back over, or None."""
        self.lengths = lengths
        self.upstream = upstream
        self.car_space = car_space
        self.lanes: Dict[Tuple[str, int], LaneQueue] = {}
        for edge, lane in lanes:
            reach, e, n = 0.0, edge, 0
            while e is not None and n < 6:
                reach += lengths.get(e, 0.0)
                e, n = upstream(e), n + 1
            self.lanes[(edge, lane)] = LaneQueue(max(int(reach / car_space), 1), hold=hold)
        self.edges = {e for e, _ in self.lanes}

    def event(self, edge: str, lane: int, t: float, occupied: bool) -> None:
        q = self.lanes.get((edge, lane))
        if q is not None:
            q.event(t, occupied)

    def drove_through(self, edge: str) -> None:
        for (e, _), q in self.lanes.items():
            if e == edge and not q.occupied:
                q.drove_through()

    def standing(self, t: float) -> Dict[str, int]:
        """Cars standing per edge with a loop (all its lanes together)."""
        out: Dict[str, int] = {}
        for (edge, _), q in self.lanes.items():
            out[edge] = out.get(edge, 0) + q.cars(t)
        return out

    def merge(self, occ: Occupancy, t: float) -> Occupancy:
        """``occ`` with the standing cars the loops imply and it does not show.

        An edge's queue (all its lanes with a loop) fills it from the line backwards, one row
        of cars every ``car_space`` metres, then the edges before it; the cars already shown
        standing there count towards it.
        """
        out = {e: list(v) for e, v in occ.items()}
        per_edge: Dict[str, Tuple[int, int]] = {}
        for (edge, _), q in self.lanes.items():
            n, k = per_edge.get(edge, (0, 0))
            per_edge[edge] = (n + q.cars(t), k + 1)
        for edge, (left, k) in per_edge.items():
            e, hops = edge, 0
            while left > 0 and e is not None and hops < 6:
                length = self.lengths.get(e, 0.0)
                rows = max(int(length // self.car_space), 1)
                want = min(left, k * rows)
                lst = out.setdefault(e, [])
                seen = sum(1 for _, v in lst if v < STOPPED)
                for i in range(seen, want):
                    lst.append((max(length - 1.0 - (i // k) * self.car_space, 0.0), 0.0))
                left -= want
                e, hops = self.upstream(e), hops + 1
        for lst in out.values():
            lst.sort()
        return {e: v for e, v in out.items() if v}
