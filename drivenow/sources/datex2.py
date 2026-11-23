"""DATEX II, the European standard for traffic data (versions 2 and 3).

Most European road authorities publish in DATEX II through their national access
points: the Netherlands (NDW), Germany (Mobilithek, Bavaria), France, Belgium,
Luxembourg, Finland, Latvia, Norway, Sweden, the UK, Austria, Porto, and more.
Three kinds of publication matter here:

- situations: roadworks, closures, temporary speed limits, accidents,
  obstructions, queues (with their length), weather, bridge openings ->
  ``parse_situations`` -> ``RoadEvent``;
- measured data per measurement site: speed and flow, or travel time ->
  ``parse_measured``;
- the measurement site table: where each site is -> ``parse_sites``.

Only locations given in coordinates (points, GML lines, ``locationForDisplay``)
are read. Many feeds give locations only as Alert-C codes, which need each
country's location table to decode: those records are counted
(``stats["alert_c_only"]``) and left out, not guessed.

The parser looks at local element names only, so the same code reads
namespaced DATEX II v3 and the unprefixed v2, also inside a SOAP envelope.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from ..road_events import RoadEvent, epoch

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _root(data) -> ET.Element:
    if isinstance(data, ET.Element):
        return data
    if isinstance(data, str):
        data = data.encode()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return ET.fromstring(data)


def _children(el: ET.Element, name: str) -> Iterator[ET.Element]:
    return (x for x in el.iter() if _local(x.tag) == name)


def _first(el: ET.Element, name: str) -> Optional[str]:
    x = next(_children(el, name), None)
    return None if x is None or x.text is None else x.text.strip()


def _type(el: ET.Element) -> str:
    return _local(el.get(XSI_TYPE, "")).split(":")[-1]


def coordinates(el: ET.Element) -> List[Tuple[float, float]]:
    """(lon, lat) in document order: GML posList (lat lon pairs) or latitude/longitude elements."""
    out: List[Tuple[float, float]] = []
    lat = None
    for x in el.iter():
        name = _local(x.tag)
        if name == "posList" and x.text:
            v = [float(s) for s in x.text.split()]
            out += [(v[i + 1], v[i]) for i in range(0, len(v) - 1, 2)]
        elif name == "latitude" and x.text:
            lat = float(x.text)
        elif name == "longitude" and x.text and lat is not None:
            out.append((float(x.text), lat))
            lat = None
    # Consecutive duplicates (a point given twice: for display and as the location)
    dedup = []
    for p in out:
        if not dedup or dedup[-1] != p:
            dedup.append(p)
    return dedup


# DATEX II record type -> event kind
_KIND = {
    "MaintenanceWorks": "roadworks", "ConstructionWorks": "roadworks", "Roadworks": "roadworks",
    "SpeedManagement": "speed_limit", "Accident": "accident", "VehicleObstruction": "obstruction",
    "GeneralObstruction": "obstruction", "AnimalPresenceObstruction": "obstruction",
    "EnvironmentalObstruction": "obstruction", "InfrastructureDamageObstruction": "obstruction",
    "AbnormalTraffic": "queue", "PoorEnvironmentConditions": "weather",
    "WeatherRelatedRoadConditions": "weather", "NonWeatherRelatedRoadConditions": "hazard",
    "RoadOrCarriagewayOrLaneManagement": "restriction", "GeneralNetworkManagement": "restriction",
    "NetworkManagement": "restriction", "ReroutingManagement": "restriction",
}
_CLOSED = {"roadClosed", "carriagewayClosures", "closedPermanentlyForTheWinter", "roadBlocked"}


def parse_situations(data, source: str = "datex2") -> Tuple[List[RoadEvent], Dict[str, int]]:
    """Every situation record with a location in coordinates, and counts of what was read."""
    root = _root(data)
    events: List[RoadEvent] = []
    stats = {"records": 0, "with_coordinates": 0, "alert_c_only": 0, "no_location": 0}
    for rec in _children(root, "situationRecord"):
        stats["records"] += 1
        rtype = _type(rec)
        line = coordinates(rec)
        if not line:
            if any(_local(x.tag).startswith("alertC") for x in rec.iter()):
                stats["alert_c_only"] += 1
            else:
                stats["no_location"] += 1
            continue
        stats["with_coordinates"] += 1
        kind = _KIND.get(rtype, "other")
        manage = {x.text.strip() for x in _children(rec, "roadOrCarriagewayOrLaneManagementType") if x.text}
        manage |= {x.text.strip() for x in _children(rec, "generalNetworkManagementType") if x.text}
        blocked = bool(manage & _CLOSED)
        if blocked:
            kind = "closure"
        if "bridgeSwingInOperation" in manage or "bridgeOpen" in manage:
            kind, blocked = "bridge", True
        if kind == "restriction" and manage & {"laneClosures", "narrowLanes", "newRoadworksLayout"} \
                and _first(rec, "causeType") in ("roadMaintenance", "roadworks"):
            kind = "roadworks"
        limit = _first(rec, "temporarySpeedLimit") or _first(rec, "speedLimit")
        queue = _first(rec, "queueLength")
        lanes = _first(rec, "numberOfLanesRestricted")
        comment = _first(rec, "value") or ""
        events.append(RoadEvent(
            id=f"{source}:{rec.get('id')}", kind=kind, source=source, line=line,
            start=epoch(_first(rec, "overallStartTime")), end=epoch(_first(rec, "overallEndTime")),
            speed_limit=float(limit) / 3.6 if limit else None, blocked=blocked,
            lanes_closed=int(float(lanes)) if lanes else None,
            queue_length=float(queue) if queue else None, text=f"{rtype}: {comment}"[:200]))
    return events, stats


def parse_sites(data) -> Dict[str, List[Tuple[float, float]]]:
    """Measurement site id -> its location as (lon, lat) points, from a site table."""
    out = {}
    for rec in _children(_root(data), "measurementSiteRecord"):
        loc = next(_children(rec, "measurementSiteLocation"), rec)
        pts = coordinates(loc)
        if pts:
            out[rec.get("id")] = pts
    return out


def parse_measured(data) -> List[dict]:
    """Per measurement site: {"site", "time", "speed" (km/h), "flow" (veh/h), "travel_time" (s)},
    averaged over its lanes and vehicle classes; values a site marks as missing (-1) are left out."""
    rows = []
    for sm in _children(_root(data), "siteMeasurements"):
        ref = next((x for x in sm if _local(x.tag) == "measurementSiteReference"), None)
        if ref is None:
            continue
        speeds, flows, times = [], [], []
        for bd in _children(sm, "basicData"):
            t = _type(bd)
            if t == "TrafficSpeed":
                v = _first(bd, "speed")
                if v is not None and float(v) >= 0:
                    speeds.append(float(v))
            elif t == "TrafficFlow":
                v = _first(bd, "vehicleFlowRate")
                if v is not None and float(v) >= 0:
                    flows.append(float(v))
            elif t == "TravelTimeData":
                err = _first(bd, "dataError")
                v = _first(bd, "duration")
                if v is not None and float(v) > 0 and err != "true":
                    times.append(float(v))
        rows.append({
            "site": ref.get("id"), "time": epoch(_first(sm, "measurementTimeDefault")),
            "speed": sum(speeds) / len(speeds) if speeds else None,
            "flow": sum(flows) if flows else None,
            "travel_time": times[0] if times else None,
        })
    return rows


def apply_measured(rows: Iterable[dict], sites: Dict[str, List[Tuple[float, float]]], points, db,
                   free_speed: Dict[str, float], source: str = "datex2") -> int:
    """Speeds and travel times of the sites that lie on the network, into the fleet database."""
    from ..road_events import RoadEvent as _E, match
    n = 0
    for r in rows:
        line = sites.get(r["site"])
        if not line:
            continue
        # A site is a point (its first coordinate, the one for display): the lane it measures
        # may run either way along the coordinates that follow.
        edges = match(_E("", "other", source, line[:1]), points)
        for e in edges:
            if r["speed"] and e in free_speed:
                db.segment(e, r["speed"] / 3.6, free_speed[e], r["time"] or 0.0, source)
                n += 1
            if r["travel_time"] and len(edges) == 1:
                db.measured_travel_time(e, r["travel_time"], r["time"] or 0.0, source)
    return n
