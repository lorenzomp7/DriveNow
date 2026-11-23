"""Hamburg's traffic state on every road, every 5 minutes: "Verkehrslage Hamburg".

An open WFS of the city (geodienste.hamburg.de/wfs_hh_verkehrslage, feature type
``de.hh.up:verkehrslage``). Each feature is a stretch of road (a GML line, asked
for in EPSG:4326, so lat lon) with a state class and a timestamp:

    fliessend  flowing        dicht   dense
    zäh        slow           stockend stop-and-go

There is no speed, only the class. ``SPEED_SHARE`` turns a class into a share of
the free speed; these shares are assumptions, not the city's figures.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from ..road_events import epoch
from ..traffic_sources import edges_along

URL = "https://geodienste.hamburg.de/wfs_hh_verkehrslage"
SPEED_SHARE = {"fliessend": 1.0, "dicht": 0.7, "zäh": 0.4, "zaeh": 0.4, "stockend": 0.15}


def url(bbox: Tuple[float, float, float, float]) -> str:
    """GetFeature for (min lon, min lat, max lon, max lat)."""
    lo1, la1, lo2, la2 = bbox
    crs = "urn:ogc:def:crs:EPSG::4326"
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": "de.hh.up:verkehrslage",
         "SRSNAME": crs, "BBOX": f"{la1},{lo1},{la2},{lo2},{crs}"}
    return URL + "?" + urllib.parse.urlencode(q)


def parse(data) -> List[dict]:
    """[{"state", "time", "road_class", "line" [(lon, lat)]}] for every stretch."""
    root = ET.fromstring(data if isinstance(data, (bytes, str)) else bytes(data))
    out = []
    for feat in root.iter():
        if feat.tag.rsplit("}", 1)[-1] != "verkehrslage":
            continue
        vals = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in feat}
        pos = next((x.text for x in feat.iter() if x.tag.endswith("posList")), None)
        if not pos:
            continue
        v = [float(s) for s in pos.split()]
        out.append({"state": vals.get("zustandsklasse", ""), "time": epoch(vals.get("zeitstempel_utc")),
                    "road_class": vals.get("strassenklasse", ""),
                    "line": [(v[i + 1], v[i]) for i in range(0, len(v) - 1, 2)]})
    return out


def apply(rows: List[dict], points, db, free_speed: Dict[str, float], source: str = "hamburg-verkehrslage") -> int:
    """Each stretch's state as a speed on the edges along it."""
    n = 0
    for r in rows:
        share = SPEED_SHARE.get(r["state"])
        if share is None or len(r["line"]) < 2:
            continue
        for e in edges_along(r["line"], points):
            if e in free_speed:
                db.segment(e, share * free_speed[e], free_speed[e], r["time"] or 0.0, source)
                n += 1
    return n
