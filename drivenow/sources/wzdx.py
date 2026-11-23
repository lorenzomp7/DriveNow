"""US work zones: the Work Zone Data Exchange (WZDx) feeds, GeoJSON.

About 40 public feeds, listed in USDOT's registry (data.transportation.gov,
dataset 69qe-yiui; ``parse_registry``). Versions 3.x keep the fields on the
feature's properties; 4.x put them under ``core_details``. Speeds are in mph
(v3 ``reduced_speed_limit``) or km/h (v4 ``reduced_speed_limit_kph``).
``vehicle_impact`` "all-lanes-closed", or two or more car lanes listed and all closed,
means the road is closed. ``lanes`` tells
which car lanes are closed (``order`` counts from the left; shoulders, sidewalks
and the like are not car lanes). A limit that is not a positive number is no limit. A "detour" road
event is the diversion route: the open road traffic is sent onto, kept as "other".
"""

from __future__ import annotations

import math
from typing import List, Optional

from ..road_events import RoadEvent, epoch

CAR_LANES = {"general", "exit-lane", "entrance-lane", "two-way-center-turn-lane", "hov-lane", "hov"}


def _limit(value, scale: float) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v * scale if math.isfinite(v) and v > 0 else None


REGISTRY = "https://data.transportation.gov/api/views/69qe-yiui/rows.json?accessType=DOWNLOAD"
MPH = 0.44704


def _line(geom) -> List[tuple]:
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "LineString":
        return [tuple(p[:2]) for p in c]
    if t == "MultiPoint":
        return [tuple(p[:2]) for p in c]
    if t == "Point":
        return [tuple(c[:2])]
    if t == "MultiLineString":
        return [tuple(p[:2]) for line in c for p in line]
    return []


def parse(feed: dict, source: str = "wzdx") -> List[RoadEvent]:
    out = []
    for f in feed.get("features", []):
        p = f.get("properties", {})
        core = p.get("core_details", p)
        etype = core.get("event_type", "work-zone")
        if p.get("reduced_speed_limit_kph") is not None:
            limit = _limit(p["reduced_speed_limit_kph"], 1 / 3.6)
        else:
            limit = _limit(p.get("reduced_speed_limit"), MPH)
        line = _line(f.get("geometry"))
        if not line:
            continue
        lanes = sorted((ln for ln in p.get("lanes") or [] if ln.get("type", "general") in CAR_LANES),
                       key=lambda ln: ln.get("order", 0))
        at = [i + 1 for i, ln in enumerate(lanes) if ln.get("status") == "closed"]
        closed = len(at) if lanes else None
        # Two or more car lanes listed and all closed close the road, even when a shoulder stays
        # open and the feed says "some-lanes-closed". One lane listed is not enough: some feeds
        # list only the lane the works take.
        impact = p.get("vehicle_impact", "")
        blocked = etype != "detour" and (impact == "all-lanes-closed" or (len(lanes) >= 2 and closed == len(lanes)))
        kind = ("other" if etype == "detour" else "closure" if blocked
                else "restriction" if etype == "restriction" else "roadworks")
        out.append(RoadEvent(
            id=f"{source}:{f.get('id') or core.get('road_event_id') or len(out)}", kind=kind, source=source, line=line,
            start=epoch(p.get("start_date")), end=epoch(p.get("end_date")), speed_limit=limit, blocked=blocked,
            lanes_closed=closed, closed_lanes=at, lane_count=len(lanes) or None, text=("Detour: " if etype == "detour" else "")
            + ", ".join(core.get("road_names") or [core.get("road_name", "")])[:200]))
    return out


def parse_registry(rows_json: dict) -> List[dict]:
    """The registry's feeds: [{"state", "organization", "name", "url", "format", "version", "active", "needs_key"}]."""
    cols = [c["name"] for c in rows_json["meta"]["view"]["columns"]]
    out = []
    for row in rows_json["data"]:
        r = dict(zip(cols, row))
        url = r.get("url")
        if isinstance(url, list):
            url = url[0]
        out.append({"state": r.get("state"), "organization": r.get("issuingOrganization"), "name": r.get("feedName"),
                    "url": url, "format": r.get("format"), "version": r.get("version"),
                    "active": bool(r.get("active")), "needs_key": bool(r.get("needAPIKey"))})
    return out
