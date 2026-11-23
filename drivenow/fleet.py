"""Where the other cars are, as DriveNow can know it on the road.

The advice looks at the cars around: the queue ahead, who follows close behind,
the main-road cars at a give-way line. A simulation knows every car. On the road
DriveNow knows only two things:

- its own cars, one by one: each phone reports where it is (``report``). These
  are personal data, so a car is known by a pseudonym and is forgotten ``ttl``
  seconds after its last report;
- aggregated traffic per stretch of road from a traffic data provider (TomTom
  Traffic Flow, Waze for Cities jams, a city's detectors): how fast traffic
  moves there, a few minutes late, never single cars (``segment``).

``FleetDB.occupancy`` turns the cars it knows into the advisor's ``Occupancy``
(edge -> [(position, speed)]). One thing it can add about the cars it does not
see: a DriveNow car standing in a queue at ``p`` means the road between ``p``
and the stop line is standing too, so that stretch is filled with standing cars
every ``car_space`` metres (up to the first seen car that moves, if any: there the
queue is already driving off).

With ``path`` every report is also written to an SQLite file (history for
analysis and replays); the live view stays in memory.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from .road_events import RoadEvent

STOPPED = 2.0  # m/s, as in advisor.py


@dataclass
class Segment:
    speed: float       # m/s now (as reported)
    free_speed: float  # m/s with no traffic
    t: float           # when it was measured
    source: str


class FleetDB:
    def __init__(self, lengths: Dict[str, float], ttl: float = 3.0, car_space: float = 7.5,
                 fill_queues: bool = True, path: Optional[str] = None, share: float = 1.0) -> None:
        self.lengths = lengths            # edge -> m, to fill queues up to the stop line
        self.ttl = ttl
        self.car_space = car_space
        self.fill_queues = fill_queues
        # Share of the cars on the road that are DriveNow cars (an estimate). Aiming for a gap
        # in the main-road traffic needs to see nearly all of it: see gap_trust.
        self.share = share
        self.gap_min_share = 0.9
        self.cars: Dict[str, Tuple[float, str, float, float]] = {}   # car -> (t, edge, pos, v)
        self.segments: Dict[str, Segment] = {}
        # What is in the way (roadworks, closures, queues...: road_events.py), by id, and the
        # travel times measured per edge by a source: edge -> (seconds, time, source).
        self.events: Dict[str, RoadEvent] = {}
        self.travel: Dict[str, Tuple[float, float, str]] = {}
        # Travel times of the DriveNow cars themselves: when each car first reported each edge.
        self._entered: Dict[str, Tuple[str, float]] = {}
        self.crossings: Dict[str, Deque[Tuple[float, float]]] = {}   # edge -> (time, seconds)
        self._db: Optional[sqlite3.Connection] = None
        if path:
            self._db = sqlite3.connect(path)
            self._db.execute("CREATE TABLE IF NOT EXISTS reports (t REAL, car TEXT, edge TEXT, pos REAL, v REAL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS segments (t REAL, edge TEXT, speed REAL, free_speed REAL, source TEXT)")

    # -- writing -------------------------------------------------------------

    def report(self, car: str, t: float, edge: str, pos: float, v: float) -> None:
        """A DriveNow car is at ``pos`` on ``edge`` with speed ``v`` at time ``t``."""
        self.cars[car] = (t, edge, pos, v)
        prev = self._entered.get(car)
        if prev is None or prev[0] != edge:
            if prev is not None and 0.0 < t - prev[1] < 900.0:
                q = self.crossings.setdefault(prev[0], deque(maxlen=20))
                q.append((t, t - prev[1]))
            self._entered[car] = (edge, t)
        if self._db is not None:
            self._db.execute("INSERT INTO reports VALUES (?, ?, ?, ?, ?)", (t, car, edge, pos, v))

    def leave(self, car: str) -> None:
        self.cars.pop(car, None)
        self._entered.pop(car, None)

    def event(self, ev: RoadEvent) -> None:
        """Something in the way, already matched to edges (``road_events.match``)."""
        self.events[ev.id] = ev

    def replace_events(self, source: str, events: Iterable[RoadEvent]) -> None:
        """A new reading of a source replaces everything it said before."""
        self.events = {k: v for k, v in self.events.items() if v.source != source}
        for ev in events:
            self.events[ev.id] = ev

    def measured_travel_time(self, edge: str, seconds: float, t: float, source: str = "") -> None:
        self.travel[edge] = (seconds, t, source)

    def segment(self, edge: str, speed: float, free_speed: float, t: float, source: str = "") -> None:
        """Aggregated traffic on ``edge``: it moves at ``speed`` (``free_speed`` when empty)."""
        self.segments[edge] = Segment(speed, free_speed, t, source)
        if self._db is not None:
            self._db.execute("INSERT INTO segments VALUES (?, ?, ?, ?, ?)", (t, edge, speed, free_speed, source))

    def commit(self) -> None:
        if self._db is not None:
            self._db.commit()

    def close(self) -> None:
        if self._db is not None:
            self._db.commit()
            self._db.close()
            self._db = None

    # -- reading -------------------------------------------------------------

    def expire(self, t: float) -> None:
        for car in [c for c, r in self.cars.items() if t - r[0] > self.ttl]:
            del self.cars[car]

    def occupancy(self, t: float) -> Dict[str, List[Tuple[float, float]]]:
        """The cars known at ``t`` per edge, ascending position, with the queues they reveal."""
        self.expire(t)
        occ: Dict[str, List[Tuple[float, float]]] = {}
        for _, edge, pos, v in self.cars.values():
            occ.setdefault(edge, []).append((pos, v))
        for edge, lst in occ.items():
            lst.sort()
            if self.fill_queues and edge in self.lengths:
                lst[:] = self._fill(lst, self.lengths[edge])
        self._event_queues(occ, t)
        return occ

    def _event_queues(self, occ: Dict[str, List[Tuple[float, float]]], t: float) -> None:
        """A queue reported by a source (Waze, DATEX II, HERE...) with its length: standing cars
        from the end of each of its edges backwards, where none are shown standing already."""
        for ev in self.events.values():
            if ev.kind != "queue" or not ev.queue_length or not ev.active(t):
                continue
            left = ev.queue_length
            for edge in ev.edges:
                length = self.lengths.get(edge)
                if not length or left <= 0:
                    continue
                lst = occ.setdefault(edge, [])
                if any(v < STOPPED for _, v in lst):
                    left -= length
                    continue
                n = int(min(left, length) // self.car_space)
                lst.extend((max(length - 1.0 - i * self.car_space, 0.0), 0.0) for i in range(n))
                lst.sort()
                left -= length

    def _fill(self, cars: List[Tuple[float, float]], length: float) -> List[Tuple[float, float]]:
        """Standing cars that are not seen, between the last seen standing car and the line."""
        standing = [p for p, v in cars if v < STOPPED]
        if not standing:
            return cars
        tail = min(standing)
        # Up to the line, or to a seen car that moves: there the queue is already driving off.
        end = min([p for p, v in cars if v >= STOPPED and p > tail] + [length])
        out = list(cars)
        known = sorted(p for p, _ in cars)
        p = tail + self.car_space
        while p <= end - self.car_space / 2:
            if all(abs(p - q) >= self.car_space / 2 for q in known):
                out.append((p, 0.0))
            p += self.car_space
        out.sort()
        return out

    # -- what is in the way ----------------------------------------------------------

    def events_on(self, edge: str, t: float) -> List[RoadEvent]:
        return [ev for ev in self.events.values() if edge in ev.edges and ev.active(t)]

    def speed_limit(self, edge: str, t: float) -> Optional[float]:
        """The lowest temporary speed limit on ``edge`` now (m/s), or None."""
        limits = [ev.speed_limit for ev in self.events_on(edge, t) if ev.speed_limit]
        return min(limits) if limits else None

    def blocked(self, edge: str, t: float) -> Optional[RoadEvent]:
        """An event closing ``edge`` now, or None."""
        return next((ev for ev in self.events_on(edge, t) if ev.blocked), None)

    def signal_fault(self, edge: str, t: float) -> bool:
        """The light at the end of ``edge`` is reported out of order."""
        return any(ev.kind == "signal_fault" for ev in self.events_on(edge, t))

    def travel_time(self, edge: str, t: float, limit: Optional[float] = None,
                    max_age: float = 600.0) -> Optional[Tuple[float, str, float]]:
        """(seconds, source, age in s) to drive ``edge``, from the most direct estimate there is:
        a travel time measured by a source, the DriveNow cars that crossed it, the aggregated
        speed on it, or else its speed limit (``limit``, m/s)."""
        length = self.lengths.get(edge)
        m = self.travel.get(edge)
        if m is not None and t - m[1] <= max_age:
            return m[0], m[2] or "measured", t - m[1]
        cr = [(tc, s) for tc, s in self.crossings.get(edge, ()) if t - tc <= max_age]
        if cr:
            times = sorted(s for _, s in cr)
            return times[len(times) // 2], "drivenow", t - max(tc for tc, _ in cr)
        seg = self.segments.get(edge)
        if length and seg is not None and t - seg.t <= max_age and seg.speed > 0.5:
            return length / seg.speed, seg.source or "segment", t - seg.t
        if length and limit:
            lim = self.speed_limit(edge, t)
            return length / min(limit, lim or limit), "limit", 0.0
        return None

    def segment_speed(self, edge: str, t: float, max_age: float = 300.0, slow: float = 0.5) -> Optional[float]:
        """Speed of slow aggregated traffic on ``edge`` (m/s), or None: no data, too old, or not slow."""
        s = self.segments.get(edge)
        if s is None or t - s.t > max_age or s.free_speed <= 0 or s.speed >= slow * s.free_speed:
            return None
        return max(s.speed, 0.5)

    def gap_trust(self, node: str, t: float) -> bool:
        """Can the cars seen be trusted to show every gap in the main-road traffic?

        A gap DriveNow does not see a car in may not be a gap at all (a car without
        DriveNow drives there), just as an unknown light is no green. Without a sensor
        at the junction, only when nearly every car is a DriveNow car.
        """
        return self.share >= self.gap_min_share
