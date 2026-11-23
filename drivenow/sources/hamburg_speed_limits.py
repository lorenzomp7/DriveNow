"""Hamburg's official speed limits (geodienste.hamburg.de/HH_WFS_Zulaessige_Hoechstgeschwindigkeiten).

Feature type ``de.hh.up:zulaessige_hoechstgeschwindigkeiten``: every section of Hamburg's
street network with its limit in the section's direction (``geschwindigkeit_in``) and
against it (``geschwindigkeit_gegen``), its street name, the Tempo 30/20 zone it lies in,
and a rule by hours where there is one (``sonderregelung_in``/``_gegen``, e.g. "Mo-Fr 6-19
h, sonst 50km/h": the limit holds Monday to Friday 6 to 19 h, else 50). "5-7 km/h" is a
traffic-calmed area (walking pace): read as 7. Licence: Datenlizenz Deutschland
Namensnennung 2.0, "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende".
The same data is published in DATEX II 3.7 on daten-hamburg.de.

``limit_at`` applies a rule at a time. A rule it does not know leaves the limit given and
is kept in ``unknown_rules``, so it can be reported.
"""

from __future__ import annotations

import datetime as _dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

URL = "https://geodienste.hamburg.de/HH_WFS_Zulaessige_Hoechstgeschwindigkeiten"
TYPE = "de.hh.up:zulaessige_hoechstgeschwindigkeiten"

_RULE = re.compile(r"^(?:(werktags|mo\s*-\s*fr|mo\s*-\s*sa)\s+)?(\d{1,2})\s*-\s*(\d{1,2})\s*h\s*,\s*sonst\s*(\d{2,3})\s*km/?h",
                   re.I)
unknown_rules: set = set()


def url(bbox=None) -> str:
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": TYPE,
         "SRSNAME": "urn:ogc:def:crs:EPSG::4326"}
    if bbox:
        lo1, la1, lo2, la2 = bbox
        q["BBOX"] = f"{la1},{lo1},{la2},{lo2},urn:ogc:def:crs:EPSG::4326"
    return URL + "?" + urllib.parse.urlencode(q)


def _kmh(s: str) -> Optional[int]:
    nums = [int(x) for x in re.findall(r"\d+", s or "")]
    return max(nums) if nums else None          # "5-7 km/h" -> 7


def parse(data) -> List[Dict]:
    out = []
    for f in ET.fromstring(data).iter():
        if not f.tag.endswith("}zulaessige_hoechstgeschwindigkeiten"):
            continue
        v = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in f}
        pos = next((x.text for x in f.iter() if x.tag.endswith("}posList") and x.text), None)
        if not pos:
            continue
        n = [float(x) for x in pos.split()]
        out.append({"street": v.get("strassenname", ""), "line": [(n[i + 1], n[i]) for i in range(0, len(n) - 1, 2)],
                    "kmh_in": _kmh(v.get("geschwindigkeit_in", "")), "kmh_gegen": _kmh(v.get("geschwindigkeit_gegen", "")),
                    "rule_in": v.get("sonderregelung_in", ""), "rule_gegen": v.get("sonderregelung_gegen", ""),
                    "zone": v.get("zone_bereich", "")})
    return out


def _local(t: float) -> _dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.fromtimestamp(t, ZoneInfo("Europe/Berlin"))
    except Exception:  # no time zone data: CET
        return _dt.datetime.fromtimestamp(t, _dt.timezone(_dt.timedelta(hours=1)))


def limit_at(rule: str, kmh: Optional[int], t: float) -> Optional[int]:
    """The limit (km/h) a section has at Unix time ``t`` under its rule by hours."""
    rule = (rule or "").strip()
    if not rule or rule.lower() == "keine sonderregelung":
        return kmh
    m = _RULE.match(rule)
    if not m:
        unknown_rules.add(rule)
        return kmh
    local = _local(t)
    days, start, end, other = (m.group(1) or "").lower().replace(" ", ""), int(m.group(2)), int(m.group(3)), int(m.group(4))
    last = {"": 6, "werktags": 5, "mo-sa": 5, "mo-fr": 4}[days]        # Werktage: Monday to Saturday
    on = local.weekday() <= last and start <= local.hour < end
    return kmh if on else other
