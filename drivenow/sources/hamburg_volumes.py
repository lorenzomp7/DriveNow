"""Hamburg's traffic volumes on main roads, 2019 (geodienste.hamburg.de/HH_WFS_Verkehrsmengen).

Feature type ``de.hh.up:verkehrsmengen_dtv_hvs_2019``: for each section of a main road
(Hauptverkehrsstraße) the average daily traffic over the week (DTV, Monday to Sunday,
both directions together) and the share of heavy vehicles (``sv``, %). Licence:
Datenlizenz Deutschland Namensnennung 2.0, "Freie und Hansestadt Hamburg, Behörde für
Verkehr und Mobilitätswende". The sections carry no street name: they are matched to the
network by their line.
"""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List

URL = "https://geodienste.hamburg.de/HH_WFS_Verkehrsmengen"
TYPE = "de.hh.up:verkehrsmengen_dtv_hvs_2019"


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
        if not f.tag.endswith("}verkehrsmengen_dtv_hvs_2019"):
            continue
        v = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in f}
        pos = next((x.text for x in f.iter() if x.tag.endswith("}posList") and x.text), None)
        if not pos or not v.get("dtv", "").isdigit():
            continue
        n = [float(x) for x in pos.split()]
        out.append({"line": [(n[i + 1], n[i]) for i in range(0, len(n) - 1, 2)], "dtv": int(v["dtv"]),
                    "sv_pct": float(v["sv"]) if v.get("sv", "").replace(".", "", 1).isdigit() else None})
    return out
