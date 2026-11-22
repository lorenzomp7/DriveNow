"""Aggregated traffic from data providers, into the fleet database (fleet.py).

Neither provider gives single cars: both describe stretches of road. These
adapters turn their answers into ``FleetDB.segment`` entries for the edges of
the network, using each edge's midpoint and heading (``tools/edge_points.py``).

``TomTomFlow``  TomTom Traffic Flow, "Flow Segment Data": for a point, the road
                segment there with its current and free-flow speed. One request
                per point, so polling is paced by a request budget (the free
                quota). Needs the user's API key; nothing is fetched without one.
``WazeJams``    the jams of a Waze for Cities partner feed (open to public bodies
                only): each with its line, speed and length. Parser only, written
                to the published field names; to be checked against a real feed.

Standard library only. The HTTP call is injectable (``fetch``) so the adapters
are tested offline on recorded or written answers.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

Points = Dict[str, Sequence[float]]   # edge -> [lon, lat, heading in degrees, length in m]
KMH = 1 / 3.6


def _xy(lon: float, lat: float, lat0: float) -> Tuple[float, float]:
    """Metres east/north of (0, lat0): accurate enough over a few hundred metres."""
    return math.radians(lon) * 6371000.0 * math.cos(math.radians(lat0)), math.radians(lat) * 6371000.0


def _heading(a, b) -> float:
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def _angle(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _dist_to_segment(p, a, b) -> float:
    ax, ay = b[0] - a[0], b[1] - a[1]
    n = ax * ax + ay * ay
    f = 0.0 if n == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / n))
    return math.dist(p, (a[0] + f * ax, a[1] + f * ay))


def edges_along(line: Sequence[Tuple[float, float]], points: Points, within: float = 20.0,
                max_turn: float = 45.0) -> List[str]:
    """Edges whose midpoint lies within ``within`` m of the (lon, lat) polyline, heading its way."""
    if len(line) < 2:
        return []
    lat0 = line[0][1]
    xy = [_xy(lon, lat, lat0) for lon, lat in line]
    out = []
    for edge, (lon, lat, heading, _) in points.items():
        p = _xy(lon, lat, lat0)
        best = min(((_dist_to_segment(p, a, b), _heading(a, b)) for a, b in zip(xy, xy[1:]) if a != b),
                   default=None)
        if best is not None and best[0] <= within and _angle(best[1], heading) <= max_turn:
            out.append(edge)
    return out


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


class TomTomFlow:
    URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

    def __init__(self, key: str, points: Points, edges: Iterable[str], budget: int, period: float = 86400.0,
                 fetch: Optional[Callable[[str], dict]] = None, min_confidence: float = 0.5) -> None:
        if not key:
            raise ValueError("TomTom needs an API key")
        self.key = key
        self.points = points
        self.edges = [e for e in edges if e in points]
        self.budget = budget            # requests allowed per ``period`` seconds (the quota)
        self.period = period
        self.fetch = fetch or _http_json
        self.min_confidence = min_confidence
        self.requests = 0
        self._fresh: Dict[str, float] = {}  # edge -> when it was last covered by an answer

    @property
    def refresh(self) -> float:
        """Seconds between two updates of the same edge that keep within the budget."""
        return self.period * max(len(self.edges), 1) / max(self.budget, 1)

    def url(self, edge: str) -> str:
        lon, lat = self.points[edge][:2]
        q = urllib.parse.urlencode({"key": self.key, "point": f"{lat:.6f},{lon:.6f}", "unit": "KMPH"})
        return f"{self.URL}?{q}"

    @staticmethod
    def parse(answer: dict) -> Optional[Tuple[float, float, float, bool, List[Tuple[float, float]]]]:
        """(speed m/s, free-flow speed m/s, confidence, road closed, line as (lon, lat)) or None."""
        f = answer.get("flowSegmentData")
        if not f or "currentSpeed" not in f or "freeFlowSpeed" not in f:
            return None
        line = [(c["longitude"], c["latitude"]) for c in (f.get("coordinates") or {}).get("coordinate", [])]
        return (f["currentSpeed"] * KMH, f["freeFlowSpeed"] * KMH, float(f.get("confidence", 1.0)),
                bool(f.get("roadClosure", False)), line)

    def poll(self, t: float, db, max_requests: int = 1) -> int:
        """Ask about the stalest edges that are due, at most ``max_requests``; returns how many were asked.

        One answer describes a whole road segment, so every polled edge along it is updated
        and does not need its own request.
        """
        due = sorted((self._fresh.get(e, -1e18), e) for e in self.edges
                     if t - self._fresh.get(e, -1e18) >= self.refresh)
        asked = 0
        for _, edge in due:
            if asked >= max_requests:
                break
            if t - self._fresh.get(edge, -1e18) < self.refresh:
                continue  # covered by an answer about a neighbouring edge
            asked += 1
            self.requests += 1
            got = self.parse(self.fetch(self.url(edge)))
            self._fresh[edge] = t
            if got is None:
                continue
            speed, free, conf, closed, line = got
            if conf < self.min_confidence:
                continue
            covered = set(edges_along(line, {e: self.points[e] for e in self.edges})) | {edge}
            for e in covered:
                db.segment(e, 0.0 if closed else speed, free, t, "tomtom")
                self._fresh[e] = t
        return asked


class WazeJams:
    def __init__(self, points: Points, free_speed: Dict[str, float]) -> None:
        self.points = points
        self.free_speed = free_speed    # edge -> m/s with no traffic (the speed limit)

    def parse(self, feed: dict) -> List[Tuple[str, float, float, int]]:
        """(edge, speed m/s, jam length m, level 0-5) for every edge a jam lies on."""
        out = []
        for jam in feed.get("jams", []):
            line = [(p["x"], p["y"]) for p in jam.get("line", [])]
            if "speed" in jam:
                speed = float(jam["speed"])           # m/s
            elif "speedKMH" in jam:
                speed = float(jam["speedKMH"]) * KMH
            else:
                continue
            for edge in edges_along(line, self.points):
                out.append((edge, speed, float(jam.get("length", 0.0)), int(jam.get("level", 0))))
        return out

    def apply(self, feed: dict, t: float, db) -> int:
        n = 0
        for edge, speed, _, _ in self.parse(feed):
            if edge in self.free_speed:
                db.segment(edge, speed, self.free_speed[edge], t, "waze")
                n += 1
        return n
