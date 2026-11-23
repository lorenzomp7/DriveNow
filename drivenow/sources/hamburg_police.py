"""Hamburg police traffic messages, open (geodienste.hamburg.de/wfs_verkehrsinformation).

Feature type ``de.hh.up:hauptmeldungen_aktuell``: the messages in force now, about
240 on a weekday, each a point (EPSG:4326 asked for, so lat lon) with a status
(BAUSTELLE, SPERRUNG, WARTUNG, STAU, UNFALL...), a DATEX II-style type (``art``),
a German description, and start and end in local time (Europe/Berlin, no zone
given). Licence: Datenlizenz Deutschland Namensnennung 2.0, "Freie und
Hansestadt Hamburg, Polizei Hamburg".

From the description: "gesperrt" closes the road unless only a lane or half of
it is ("halbseitig", "Fahrstreifen"); "rechter/linker Fahrstreifen gesperrt" closes
that lane; "Ampelanlage außer Betrieb" or "Ampel
ausgefallen" is a light out of order, which the advice must not use.
"""

from __future__ import annotations

import datetime as _dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..road_events import RoadEvent

URL = "https://geodienste.hamburg.de/wfs_verkehrsinformation"
TYPE = "de.hh.up:hauptmeldungen_aktuell"

_KIND = {"ConstructionWorks": "roadworks", "MaintenanceWorks": "roadworks", "AbnormalTraffic": "queue",
         "Accident": "accident", "RoadOrCarriagewayOrLaneManagement": "restriction",
         "GeneralNetworkManagement": "restriction", "Conditions": "weather", "VehicleObstruction": "obstruction",
         "GeneralObstruction": "obstruction", "EquipmentOrSystemFault": "hazard"}
_FAULT = re.compile(r"ampel\w*\s+(außer betrieb|ausgefallen|gestört)|ampelausfall", re.I)
_PARTIAL = re.compile(r"halbseitig|fahrstreifen|spur|einengung|verengt", re.I)
_LANE = re.compile(r"\b(rechter|linker)\s+fahrstreifen\s+gesperrt", re.I)


def _lanes(text: str):
    """(lanes closed, which: 1 = the leftmost) from "rechter/linker Fahrstreifen gesperrt"."""
    m = _LANE.search(text)
    if not m:
        return None, []
    return 1, ([1] if m.group(1).lower() == "linker" else [])


def url(bbox=None) -> str:
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": TYPE,
         "SRSNAME": "urn:ogc:def:crs:EPSG::4326"}
    if bbox:
        lo1, la1, lo2, la2 = bbox
        q["BBOX"] = f"{la1},{lo1},{la2},{lo2},urn:ogc:def:crs:EPSG::4326"
    return URL + "?" + urllib.parse.urlencode(q)


def _local(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(s[:19])
    except ValueError:
        return None
    try:
        from zoneinfo import ZoneInfo
        return d.replace(tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
    except Exception:          # no time zone data: assume CET
        return d.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=1))).timestamp()


def parse(data, source: str = "hamburg-police") -> List[RoadEvent]:
    root = ET.fromstring(data)
    out = []
    for feat in root.iter():
        if not feat.tag.endswith(("hauptmeldungen_aktuell", "hauptmeldungen", "meldungen_punkte", "meldungen_linien")):
            continue
        v = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in feat}
        pos = next((x.text for x in feat.iter() if x.tag.endswith(("pos", "posList")) and x.text), None)
        if not pos:
            continue
        nums = [float(s) for s in pos.split()]
        line = [(nums[i + 1], nums[i]) for i in range(0, len(nums) - 1, 2)]
        text = " ".join(v.get("description", "").split())
        art = v.get("art", "")
        if art == "Conditions" and v.get("art_detail") == "normal":
            continue                               # "traffic back to normal"
        kind = _KIND.get(art, "other")
        blocked = "gesperrt" in text.lower() and not _PARTIAL.search(text)
        if _FAULT.search(text):
            kind = "signal_fault"
        elif blocked:
            kind = "closure"
        lanes, which = _lanes(text) if not blocked else (None, [])
        out.append(RoadEvent(id=f"{source}:{v.get('id')}", kind=kind, source=source, line=line,
                             start=_local(v.get("start")), end=_local(v.get("end")), blocked=blocked,
                             lanes_closed=lanes, closed_lanes=which, text=text[:240]))
    return out
