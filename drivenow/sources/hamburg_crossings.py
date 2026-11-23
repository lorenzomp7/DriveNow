"""Hamburg's zebra crossings (geodienste.hamburg.de/wfs_fussgaengerueberwege).

Feature type ``de.hh.up:fussgaengerueberwege``: every Fußgängerüberweg (sign 293 of the
StVO) the city is responsible for, a point with its street name. Licence: Datenlizenz
Deutschland Namensnennung 2.0, "Freie und Hansestadt Hamburg, Behörde für Verkehr und
Mobilitätswende". Also published in DATEX II 3.7 on daten-hamburg.de.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List

URL = "https://geodienste.hamburg.de/wfs_fussgaengerueberwege"
TYPE = "de.hh.up:fussgaengerueberwege"


def url(bbox=None) -> str:
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": TYPE,
         "SRSNAME": "urn:ogc:def:crs:EPSG::4326"}
    if bbox:
        lo1, la1, lo2, la2 = bbox
        q["BBOX"] = f"{la1},{lo1},{la2},{lo2},urn:ogc:def:crs:EPSG::4326"
    return URL + "?" + urllib.parse.urlencode(q)


def parse(data) -> List[Dict]:
    out = []
    for f in ET.fromstring(data).iter():
        if not f.tag.endswith("}fussgaengerueberwege"):
            continue
        v = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in f}
        pos = next((x.text for x in f.iter() if x.tag.endswith("}pos") and x.text), None)
        if not pos:
            continue
        lat, lon = (float(s) for s in pos.split()[:2])
        out.append({"street": v.get("strassenname", ""), "lon": lon, "lat": lat})
    return out
