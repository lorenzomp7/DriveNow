"""Finland: Fintraffic's Digitraffic traffic messages (tie.digitraffic.fi), open, no key.

    https://tie.digitraffic.fi/api/traffic-message/v1/messages?situationType=ROAD_WORK
    situationType: TRAFFIC_ANNOUNCEMENT, ROAD_WORK, WEIGHT_RESTRICTION, EXEMPTED_TRANSPORT

GeoJSON features with the geometry in lon/lat, and announcements that list
restrictions (a speed limit in km/h, lanes closed, the road closed) and the times
of each road work phase. The service asks for gzip and a ``Digitraffic-User``
header.
"""

from __future__ import annotations

from typing import List

from ..road_events import RoadEvent, epoch

URL = "https://tie.digitraffic.fi/api/traffic-message/v1/messages"
HEADERS = {"Accept-Encoding": "gzip", "Digitraffic-User": "DriveNow"}
_KIND = {"ROAD_WORK": "roadworks", "WEIGHT_RESTRICTION": "restriction", "EXEMPTED_TRANSPORT": "hazard",
         "TRAFFIC_ANNOUNCEMENT": "hazard"}


def _lines(geom) -> List[List[tuple]]:
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point":
        return [[tuple(c[:2])]]
    if t == "LineString":
        return [[tuple(p[:2]) for p in c]]
    if t == "MultiLineString":
        return [[tuple(p[:2]) for p in line] for line in c]
    return []


def parse(answer: dict, source: str = "digitraffic") -> List[RoadEvent]:
    out = []
    for f in answer.get("features", []):
        p = f.get("properties", {})
        kind = _KIND.get(p.get("situationType"), "other")
        for a_i, a in enumerate(p.get("announcements", [])):
            limit, blocked, start, end = None, False, None, None
            texts = [r.get("restriction", {}) for ph in a.get("roadWorkPhases", []) for r in ph.get("restrictions", [])]
            texts += a.get("features", [])
            for r in texts:
                if r.get("unit") == "km/h" and r.get("quantity"):
                    limit = min(limit or 1e9, float(r["quantity"]) / 3.6)
            types = {r.get("type") for ph in a.get("roadWorkPhases", []) for r in ph.get("restrictions", [])}
            if types & {"ROAD_CLOSED", "TRAFFIC_STOPPED"}:
                blocked = True
            tad = a.get("timeAndDuration") or {}
            phases = [ph.get("timeAndDuration", {}) for ph in a.get("roadWorkPhases", [])]
            starts = [epoch(x.get("startTime")) for x in [tad] + phases if x.get("startTime")]
            ends = [epoch(x.get("endTime")) for x in [tad] + phases if x.get("endTime")]
            start = min(starts) if starts else None
            end = max(ends) if ends else None
            if kind == "hazard" and "onnettomuus" in (a.get("title") or "").lower():
                kind = "accident"
            for i, line in enumerate(_lines(f.get("geometry"))):
                out.append(RoadEvent(id=f"{source}:{p.get('situationId')}:{a_i}:{i}", kind="closure" if blocked else kind,
                                     source=source, line=line, start=start, end=end, speed_limit=limit,
                                     blocked=blocked, text=(a.get("title") or "")[:200]))
    return out
