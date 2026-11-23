"""How many cars stand at each light, from the light's colour, loop detectors and phones.

The colour of the light comes first: on red every car that arrives joins the
queue, on green the queue drives off. A loop at the stop line says when a car
passes it ("free" -> "occupied"), which gives the two numbers the colour leaves
open:

- the arrival rate on the lane: the passages of the last ``window`` seconds
  (over whole cycles every car that arrives also leaves), taken when the light
  turns red, since on red nobody passes;
- the cars leaving on green: every passage is one car out of the queue;
- whether a queue has begun on red: its first car stands on the loop.

So, for each lane: on red, while a car is on the loop, the queue left over from
the last green plus rate x (time since the light turned red, or since the loop
was last free); on green, the queue at the start of
green plus the cars arriving behind it minus the passages, until it has gone
(no car on the loop for ``hold`` seconds, or the count reaches zero). Yellow
counts as red, as in the advice. A car standing on the loop for more than
``hold`` seconds is at least one car standing.

Where the colour is not known, the loop alone gives a rougher estimate: a car
standing on it for more than ``hold`` seconds is the head of a queue that grows
at the arrival rate, and drives off one passage at a time once the loop frees.

On the road the colours and the loop states come live from the city's feed
(see ``hamburg/live.py``); in the Hamburg simulation from the recording that
drives SUMO's lights.

Fused with the phones (``FleetDB.occupancy``): the standing cars the phones show
or reveal stay; the estimate adds the standing cars it implies and the phones do
not show, from the line backwards (over the edges before it, when the queue is
longer than the edge). A DriveNow car driving through close to the line without
stopping means no queue is left there unless the loop says otherwise.
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
        self._rate = 0.0                 # arrival rate taken when the loop/light last changed
        # Loop only (colour unknown)
        self._q0 = 0.0                   # cars standing when the loop freed after a standing period
        self._left = 0                   # passages since then
        self._discharging = False
        # With the colour of the light
        self.green: Optional[bool] = None
        self._changed = 0.0              # when the light last changed colour
        self._base = 0.0                 # cars standing then
        self._out = 0                    # passages since then
        self._gone = False               # on green: the queue has gone
        self._anchor = 0.0               # on red: since when the queue grows from _base

    def rate(self, t: float) -> float:
        while self.passages and self.passages[0] < t - self.window:
            self.passages.popleft()
        span = min(self.window, max(t - (self.start if self.start is not None else t), 60.0))
        return len(self.passages) / span

    # -- inputs ----------------------------------------------------------------

    def signal(self, t: float, green: bool) -> None:
        """The light of this lane shows green (True) or not (False) from ``t``."""
        if self.start is None:
            self.start = t
        if green == self.green:
            return
        base = self._estimate(t) if self.green is not None else (self._loop_cars(t) if not green else 0.0)
        if not green:
            self._rate = self.rate(t)     # nobody passes on red: keep the rate from before
        self.green = green
        self._changed = t
        self._anchor = t
        if not green and not self.occupied:
            base = 0.0                    # nobody at the line: the queue starts with the first car
        self._base = base
        self._out = 0
        self._gone = False

    def event(self, t: float, occupied: bool) -> None:
        if self.start is None:
            self.start = t
        if occupied == self.occupied:
            return
        if occupied:
            self.passages.append(t)
            if self.green is None:
                self._rate = self.rate(t)
            if self._discharging:
                self._left += 1
            if self.green:
                self._out += 1
            elif self.green is False:
                # On red the first car reaches the line: the queue starts with it.
                self._base, self._anchor = 1.0, t
        else:
            if self.green and self.since < self._changed:
                self._out += 1            # the car that stood on the loop through red has left
        if not occupied and t - self.since > self.hold:
            # A car stood on the loop: the queue behind it starts to drive off.
            self._q0 = self._standing(self.since, t)
            self._left = 0
            self._discharging = True
        self.occupied = occupied
        self.since = t

    def drove_through(self) -> None:
        """A car crossed the line without stopping: no queue is left (the loop is not standing)."""
        self._discharging = False
        if self.green:
            self._gone = True

    # -- estimate ----------------------------------------------------------------

    def _standing(self, since: float, t: float) -> float:
        return min(1.0 + self._rate * (t - since), float(self.max_cars))

    def _loop_cars(self, t: float) -> float:
        """From the loop alone."""
        if self.occupied and t - self.since > self.hold:
            return self._standing(self.since, t)
        if self._discharging:
            if not self.occupied and t - self.since > self.hold:
                self._discharging = False   # no car for a while: the queue has gone
                return 0.0
            return max(self._q0 - self._left, 0.0)
        return 0.0

    def _estimate(self, t: float) -> float:
        standing_on_loop = self.occupied and t - self.since > self.hold
        if self.green is False:
            # On red a queue starts at the line: while nobody stands on the loop there is none
            # (the cars arriving are still on their way to it).
            if not self.occupied:
                return 0.0
            q = self._base + self._rate * (t - self._anchor)
            if standing_on_loop:
                q = max(q, 1.0)
            return min(q, float(self.max_cars))
        # Green: the queue drives off, the cars arriving behind it join it until it has gone.
        if self._gone:
            return 1.0 if standing_on_loop else 0.0
        q = self._base + self.rate(t) * (t - self._changed) - self._out
        quiet = not self.occupied and t - max(self.since, self._changed) > self.hold
        if q <= 0.0 or (quiet and t - self._changed > self.hold + 2.0):
            self._gone = True
            return 0.0
        return min(q, float(self.max_cars))

    def cars(self, t: float) -> int:
        """Cars estimated to stand on the lane at ``t``."""
        if self.green is None:
            return int(round(self._loop_cars(t)))
        return int(round(self._estimate(t)))


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

    def signal(self, edge: str, lane: int, t: float, green: bool) -> None:
        q = self.lanes.get((edge, lane))
        if q is not None:
            q.signal(t, green)

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
