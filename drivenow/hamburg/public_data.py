"""Hamburg's open street data saved for a scenario (``tools/hamburg_public_data.py``), on its edges.

data/hamburg/<scenario>/public_data.json holds the raw answers (gzip, base64) of three
datasets of the Behörde für Verkehr und Mobilitätswende, read for the network's box:
the official speed limits, the 2019 traffic volumes on main roads and the zebra crossings.
They are parsed again here and matched to the network's edges:

- limits: a section's line, in its direction ("in") and against it ("gegen"), along the
  edges heading the same way (``traffic_sources.edges_along``), kept to edges of the same
  street; the limit at a given time follows the section's rule by hours;
- volumes: both directions of a section, kept to the edges of the named main roads;
- crossings: every edge of the crossing's street within 20 m of it, with the crossing's
  position along the edge.
"""

from __future__ import annotations

import base64
import gzip
import math
from typing import Dict, Iterable, List

from ..sources import hamburg_crossings, hamburg_speed_limits, hamburg_volumes
from ..traffic_sources import edges_along

SOURCES = {"speed-limits": hamburg_speed_limits, "volumes": hamburg_volumes, "crossings": hamburg_crossings}


def pack(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode("ascii")


def unpack(text: str) -> bytes:
    return gzip.decompress(base64.b64decode(text))


def rows(snapshot: Dict, name: str) -> List[Dict]:
    src = snapshot.get("sources", {}).get(name)
    return SOURCES[name].parse(unpack(src["data"])) if src else []


def limits(snapshot: Dict, points, names: Dict[str, str], t: float) -> Dict[str, int]:
    """edge -> official limit (km/h) at Unix time ``t``."""
    out: Dict[str, int] = {}
    for r in rows(snapshot, "speed-limits"):
        for line, kmh, rule in ((r["line"], r["kmh_in"], r["rule_in"]), (r["line"][::-1], r["kmh_gegen"], r["rule_gegen"])):
            k = hamburg_speed_limits.limit_at(rule, kmh, t)
            if not k or len(line) < 2:
                continue
            for e in edges_along(line, points):
                if names.get(e) == r["street"]:
                    out[e] = k
    return out


def volumes(snapshot: Dict, points, names: Dict[str, str], roads: Iterable[str]) -> Dict[str, int]:
    """edge of a named main road (``roads``; None: any street) -> the daily volume (DTV, both
    directions) of its section; the edge must carry a street name."""
    roads = set(roads) if roads is not None else None
    out: Dict[str, int] = {}
    for r in rows(snapshot, "volumes"):
        for line in (r["line"], r["line"][::-1]):
            for e in edges_along(line, points):
                if names.get(e) and (roads is None or names.get(e) in roads):
                    out[e] = max(out.get(e, 0), r["dtv"])
    return out


def _metres(lon, lat, lon0, lat0):
    return ((lon - lon0) * 111320.0 * math.cos(math.radians(lat0)), (lat - lat0) * 110540.0)


def crossings(snapshot: Dict, net, points, within: float = 20.0) -> Dict[str, List[float]]:
    """edge -> positions (m from its start) of the zebra crossings on it."""
    out: Dict[str, List[float]] = {}
    for c in rows(snapshot, "crossings"):
        cands = [e for e, p in points.items() if e in net.edges and net.edges[e].name == c["street"]
                 and math.dist(_metres(c["lon"], c["lat"], p[0], p[1]), (0, 0)) < 150]
        for e in cands:
            edge, (lon0, lat0) = net.edges[e], points[e][:2]
            # The crossing in the net's metres, from the edge's own midpoint (accurate to about a
            # metre over these distances).
            shape = edge.shape
            segs = [(a, b, math.dist(a, b)) for a, b in zip(shape, shape[1:])]
            half, mid = sum(d for *_, d in segs) / 2, shape[0]
            for a, b, d in segs:
                if half <= d:
                    f = half / d if d else 0.0
                    mid = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
                    break
                half -= d
            dx, dy = _metres(c["lon"], c["lat"], lon0, lat0)
            p = (mid[0] + dx, mid[1] + dy)
            best, along, run = None, 0.0, 0.0
            for a, b, d in segs:
                u = 0.0 if not d else max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / d / d))
                q = (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))
                dist = math.dist(p, q)
                if best is None or dist < best:
                    best, along = dist, run + u * d
                run += d
            if best is not None and best <= within:
                out.setdefault(e, []).append(round(min(along, edge.length), 1))
    return {e: sorted(v) for e, v in out.items()}
