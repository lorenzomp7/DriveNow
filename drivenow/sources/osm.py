"""OpenStreetMap through the Overpass API: where the lights are, speed limits, roadworks.

Worldwide, open (ODbL). For a box (south, west, north, east) one query asks for:

- nodes ``highway=traffic_signals`` (and ``crossing=traffic_signals``): where
  there are lights, also where a network has none or no timing for them;
- ways ``highway=construction`` or with ``construction=*``: roads under works;
- ways with ``maxspeed``: the signed limits.

Timings of the lights are not in OpenStreetMap; they come from the city
(Hamburg), from the DriveNow cars (probe.py), or stay unknown, and an unknown
light is never taken as green.
"""

from __future__ import annotations

import urllib.parse
from typing import Dict, List, Tuple

from ..road_events import RoadEvent

URL = "https://overpass-api.de/api/interpreter"


def query(bbox: Tuple[float, float, float, float]) -> str:
    """Overpass QL for (min lon, min lat, max lon, max lat)."""
    lo1, la1, lo2, la2 = bbox
    b = f"{la1},{lo1},{la2},{lo2}"
    return (f"[out:json][timeout:60];("
            f'node["highway"="traffic_signals"]({b});node["crossing"="traffic_signals"]({b});'
            f'way["highway"="construction"]({b});way["construction"]({b});'
            f'way["highway"]["maxspeed"]({b}););out geom;')


def url(bbox) -> str:
    return URL + "?data=" + urllib.parse.quote(query(bbox))


def _maxspeed(s: str):
    s = (s or "").strip().lower()
    try:
        if s.endswith("mph"):
            return float(s[:-3]) * 0.44704
        return float(s) / 3.6
    except ValueError:
        return None   # "none", "walk", "DE:urban"...: not a number


def parse(answer: dict) -> Dict[str, list]:
    """{"signals": [(lon, lat, id)], "roadworks": [RoadEvent], "maxspeed": [(line, m/s, id)]}."""
    signals, works, limits = [], [], []
    for el in answer.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "node":
            if tags.get("highway") == "traffic_signals" or tags.get("crossing") == "traffic_signals":
                signals.append((el["lon"], el["lat"], el["id"]))
            continue
        line = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if not line:
            continue
        if tags.get("highway") == "construction" or "construction" in tags:
            works.append(RoadEvent(id=f"osm:way/{el['id']}", kind="roadworks", source="osm", line=line,
                                   text=tags.get("name", "")))
        elif "maxspeed" in tags:
            v = _maxspeed(tags["maxspeed"])
            if v:
                limits.append((line, v, el["id"]))
    return {"signals": signals, "roadworks": works, "maxspeed": limits}


def nearest_nodes(signals: List[tuple], nodes: Dict[str, Tuple[float, float]], within: float = 30.0) -> Dict[str, int]:
    """For each network node (id -> lon, lat) the OSM light within ``within`` m, if any."""
    import math
    out = {}
    for nid, (lon, lat) in nodes.items():
        best = None
        for slon, slat, sid in signals:
            dx = math.radians(slon - lon) * 6371000.0 * math.cos(math.radians(lat))
            dy = math.radians(slat - lat) * 6371000.0
            d = math.hypot(dx, dy)
            if d <= within and (best is None or d < best[0]):
                best = (d, sid)
        if best:
            out[nid] = best[1]
    return out
