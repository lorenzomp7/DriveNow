"""US work zones: the Work Zone Data Exchange (WZDx) feeds, GeoJSON.

About 40 public feeds, listed in USDOT's registry (data.transportation.gov,
dataset 69qe-yiui; ``parse_registry``). Versions 3.x keep the fields on the
feature's properties; 4.x put them under ``core_details``. Speeds are in mph
(v3 ``reduced_speed_limit``) or km/h (v4 ``reduced_speed_limit_kph``).
``vehicle_impact`` "all-lanes-closed" means the road is closed. A "detour" road
event is the diversion route: the open road traffic is sent onto, kept as "other".
"""

from __future__ import annotations

from typing import List

from ..road_events import RoadEvent, epoch

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
            limit = float(p["reduced_speed_limit_kph"]) / 3.6
        elif p.get("reduced_speed_limit") is not None:
            limit = float(p["reduced_speed_limit"]) * MPH
        else:
            limit = None
        impact = p.get("vehicle_impact", "")
        blocked = impact == "all-lanes-closed" and etype != "detour"
        kind = ("other" if etype == "detour" else "closure" if blocked
                else "restriction" if etype == "restriction" else "roadworks")
        line = _line(f.get("geometry"))
        if not line:
            continue
        lanes = p.get("lanes") or []
        closed = sum(1 for ln in lanes if ln.get("status") == "closed") if lanes else None
        out.append(RoadEvent(
            id=f"{source}:{f.get('id') or core.get('road_event_id') or len(out)}", kind=kind, source=source, line=line,
            start=epoch(p.get("start_date")), end=epoch(p.get("end_date")), speed_limit=limit, blocked=blocked,
            lanes_closed=closed, text=("Detour: " if etype == "detour" else "")
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
