"""HERE Traffic API v7: real-time flow and incidents, worldwide. Needs the user's API key.

    GET https://data.traffic.hereapi.com/v7/flow?in=circle:<lat>,<lng>;r=<m>&locationReferencing=shape&apiKey=...
    GET https://data.traffic.hereapi.com/v7/incidents?in=circle:...&locationReferencing=shape&apiKey=...

Flow: for each stretch of road its shape (``location.shape.links[].points``,
lat/lng) and ``currentFlow``: speed and free-flow speed in m/s, jam factor (0
free, 10 standing), confidence, traversability (closed roads). Incidents: the
same shape and ``incidentDetails``: type (construction, accident, roadClosure,
congestion, ...), whether the road is closed, start and end time.

HERE's pricing page lists 5,000 free traffic transactions a month; ``refresh``
paces the requests within a budget, as ``TomTomFlow`` does. The tests use
answers written to the published format; no live answer has been seen (no key).
"""

from __future__ import annotations

import urllib.parse
from typing import Callable, List, Optional, Tuple

from ..road_events import RoadEvent, epoch
from ..traffic_sources import _http_json, edges_along

BASE = "https://data.traffic.hereapi.com/v7"
_KIND = {"construction": "roadworks", "plannedEvent": "restriction", "accident": "accident",
         "congestion": "queue", "roadClosure": "closure", "laneRestriction": "restriction",
         "disabledVehicle": "obstruction", "roadHazard": "hazard", "weather": "weather", "massTransit": "other"}


def _shape(location: dict) -> List[Tuple[float, float]]:
    pts = []
    for link in (location.get("shape") or {}).get("links", []):
        for p in link.get("points", []):
            q = (float(p["lng"]), float(p["lat"]))
            if not pts or pts[-1] != q:
                pts.append(q)
    return pts


def parse_flow(answer: dict) -> List[dict]:
    """[{"line", "speed", "free_speed" (m/s), "jam", "confidence", "closed"}]."""
    out = []
    for r in answer.get("results", []):
        cf = r.get("currentFlow") or {}
        if "speed" not in cf and cf.get("traversability") != "closed":
            continue
        out.append({"line": _shape(r.get("location", {})), "speed": float(cf.get("speed", 0.0)),
                    "free_speed": float(cf.get("freeFlow", 0.0)), "jam": float(cf.get("jamFactor", 0.0)),
                    "confidence": float(cf.get("confidence", 1.0)), "closed": cf.get("traversability") == "closed"})
    return out


def parse_incidents(answer: dict, source: str = "here") -> List[RoadEvent]:
    out = []
    for r in answer.get("results", []):
        d = r.get("incidentDetails") or {}
        line = _shape(r.get("location", {}))
        if not line:
            continue
        closed = bool(d.get("roadClosed"))
        kind = "closure" if closed else _KIND.get(d.get("type"), "other")
        desc = (d.get("description") or {}).get("value", "")
        out.append(RoadEvent(id=f"{source}:{d.get('id', len(out))}", kind=kind, source=source, line=line,
                             start=epoch(d.get("startTime")), end=epoch(d.get("endTime")), blocked=closed,
                             text=desc[:200]))
    return out


class HereTraffic:
    def __init__(self, key: str, center: Tuple[float, float], radius: float = 1500.0, budget: int = 5000,
                 period: float = 30 * 86400.0, fetch: Optional[Callable[[str], dict]] = None,
                 min_confidence: float = 0.5) -> None:
        if not key:
            raise ValueError("HERE needs an API key")
        self.key, self.center, self.radius = key, center, radius
        self.budget, self.period = budget, period
        self.fetch = fetch or _http_json
        self.min_confidence = min_confidence
        self.requests = 0
        self._last = {"flow": -1e18, "incidents": -1e18}

    @property
    def refresh(self) -> float:
        """Seconds between two readings of each kind that keep within the budget."""
        return self.period * 2 / max(self.budget, 1)

    def url(self, kind: str) -> str:
        lon, lat = self.center
        q = {"in": f"circle:{lat:.6f},{lon:.6f};r={int(self.radius)}", "locationReferencing": "shape",
             "apiKey": self.key}
        return f"{BASE}/{kind}?" + urllib.parse.urlencode(q, safe=":;,=")

    def poll(self, t: float, db, points) -> Tuple[int, int]:
        """Flow and incidents when due; returns (edges with a speed, events on the network)."""
        from ..road_events import match_all
        speeds = events = 0
        if t - self._last["flow"] >= self.refresh:
            self._last["flow"] = t
            self.requests += 1
            for row in parse_flow(self.fetch(self.url("flow"))):
                if row["confidence"] < self.min_confidence or len(row["line"]) < 2:
                    continue
                for e in edges_along(row["line"], points):
                    db.segment(e, 0.0 if row["closed"] else row["speed"], row["free_speed"], t, "here")
                    speeds += 1
        if t - self._last["incidents"] >= self.refresh:
            self._last["incidents"] = t
            self.requests += 1
            evs = match_all(parse_incidents(self.fetch(self.url("incidents"))), points)
            db.replace_events("here", evs)
            events = len(evs)
        return speeds, events
