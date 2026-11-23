"""What is in the way on the road: roadworks, closures, accidents, queues, weather.

Every public source describes these differently (DATEX II situations, WZDx work
zones, the Autobahn API, HERE incidents, Waze alerts...). The adapters in
``drivenow/sources`` turn them into ``RoadEvent``: one kind from a short list,
where (a lon/lat line or point), when, and what it does to driving (a temporary
speed limit, lanes or the whole road closed, the length of a queue).

``match`` finds the edges of a network the event lies on, from the edges' lon/lat
midpoints and headings (``tools/edge_points.py``).
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# The kinds of event, whatever the source calls them.
KINDS = ("roadworks", "closure", "restriction", "speed_limit", "accident", "obstruction",
         "queue", "weather", "bridge", "hazard", "signal_fault", "other")

Points = Dict[str, Sequence[float]]   # edge -> [lon, lat, heading in degrees, length in m]


@dataclass
class RoadEvent:
    id: str
    kind: str                                   # one of KINDS
    source: str
    line: List[Tuple[float, float]]             # (lon, lat), in the direction of travel when known
    start: Optional[float] = None               # Unix time; None: already going on
    end: Optional[float] = None                 # Unix time; None: until further notice
    speed_limit: Optional[float] = None         # m/s, temporary
    blocked: bool = False                       # the road (this way) is closed
    lanes_closed: Optional[int] = None
    closed_lanes: List[int] = field(default_factory=list)   # which: 1 = leftmost car lane, when known
    lane_count: Optional[int] = None            # car lanes the source counts there
    queue_length: Optional[float] = None        # m
    text: str = ""
    edges: List[str] = field(default_factory=list)

    def active(self, t: float) -> bool:
        return (self.start is None or self.start <= t) and (self.end is None or t < self.end)


def epoch(s: Optional[str]) -> Optional[float]:
    """ISO 8601 time (with or without zone; no zone means UTC) to Unix time, or None."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    if "." in s:                                  # fractions longer than Python accepts
        head, rest = s.split(".", 1)
        digits = "".join(c for c in rest if c.isdigit())
        zone = rest[len(digits):]
        s = head + "." + digits[:6] + zone
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def _xy(lon: float, lat: float, lat0: float) -> Tuple[float, float]:
    return math.radians(lon) * 6371000.0 * math.cos(math.radians(lat0)), math.radians(lat) * 6371000.0


def match(event: RoadEvent, points: Points, within: float = 25.0, max_turn: float = 45.0) -> List[str]:
    """Edges the event lies on: along its line (heading its way), or at its point."""
    from .traffic_sources import edges_along  # same matching as the traffic sources
    if len(event.line) >= 2:
        return edges_along(event.line, points, within=within, max_turn=max_turn)
    if not event.line:
        return []
    lon, lat = event.line[0]
    p = _xy(lon, lat, lat)
    out = []
    for edge, (elon, elat, _, length) in points.items():
        if math.dist(p, _xy(elon, elat, lat)) <= max(within, length / 2):
            out.append(edge)
    return out


def match_all(events: Iterable[RoadEvent], points: Points, **kw) -> List[RoadEvent]:
    """The events that lie on the network, with their edges filled in."""
    out = []
    for ev in events:
        ev.edges = match(ev, points, **kw)
        if ev.edges:
            out.append(ev)
    return out


def bbox_of(points: Points, margin: float = 0.002) -> Tuple[float, float, float, float]:
    """(min lon, min lat, max lon, max lat) around the network's edge midpoints."""
    lons = [p[0] for p in points.values()]
    lats = [p[1] for p in points.values()]
    return min(lons) - margin, min(lats) - margin, max(lons) + margin, max(lats) + margin


def kmh(v: Optional[float]) -> Optional[float]:
    return None if v is None else v / 3.6
