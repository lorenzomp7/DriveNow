"""Hamburg's roadworks, open (geodienste.hamburg.de/hh_wfs_baustellen, "Bauweiser").

Feature type ``de.hh.up:baustelle``: about 135 sites, each a point with a title, the
works' start and end day (``baubeginn``/``bauende``, dd.mm.yyyy, Hamburg time) and a
free text on what they do to traffic (``umfang``). Licence: Datenlizenz Deutschland
Namensnennung 2.0, "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende".

The text often describes several phases. A site is read as closing the road only when
it says "Vollsperrung" (or "voll gesperrt") and nothing in the whole text limits that to
a section, a time of day, a later phase, kept access or a footpath; a limit only from an
explicit speed sentence ("Reduzierung der Geschwindigkeit auf 30 km/h"). Lanes are not given. In doubt a site
is roadworks with nothing changed on the road: nothing is made up.

The same authority's roadworks in DATEX II are on Mobilithek, by subscription only
(see ``mobilithek.py``).
"""

from __future__ import annotations

import datetime as _dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..road_events import RoadEvent

URL = "https://geodienste.hamburg.de/hh_wfs_baustellen"
TYPE = "de.hh.up:baustelle"

_FULL = re.compile(r"voll\s*(?:-\s*)?sperr|voll\s+gesperrt|vollgesperrt", re.I)
_LIMITED = re.compile(r"abschnitt|bis auf|zeitweise|nachts|wochenende|halbseitig|fahrstreifen|fahrspur|"
                      r"nebenfahrbahn|gehweg|radweg|voraussichtlich|kurzzeitig|bauphase|phase|woche|"
                      r"tage|einm(ü|u)ndung|zufahrt|rampe|unterf(ü|u)hrung|teilweise", re.I)
_SPEED = re.compile(r"(?:geschwindigkeit|tempo)[^.]{0,40}?(\d{2,3})\s*km\s*/?\s*h", re.I)


def url(bbox=None) -> str:
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": TYPE,
         "SRSNAME": "urn:ogc:def:crs:EPSG::4326"}
    if bbox:
        lo1, la1, lo2, la2 = bbox
        q["BBOX"] = f"{la1},{lo1},{la2},{lo2},urn:ogc:def:crs:EPSG::4326"
    return URL + "?" + urllib.parse.urlencode(q)


def _day(s: Optional[str]) -> Optional[float]:
    """Midnight starting a day dd.mm.yyyy in Hamburg, as Unix time."""
    if not s:
        return None
    try:
        d = _dt.datetime.strptime(s.strip(), "%d.%m.%Y")
    except ValueError:
        return None
    try:
        from zoneinfo import ZoneInfo
        return d.replace(tzinfo=ZoneInfo("Europe/Berlin")).timestamp()
    except Exception:          # no time zone data: assume CET
        return d.replace(tzinfo=_dt.timezone(_dt.timedelta(hours=1))).timestamp()


def parse(data, source: str = "hamburg-roadworks") -> List[RoadEvent]:
    root = ET.fromstring(data)
    out = []
    for feat in root.iter():
        if not feat.tag.endswith("}baustelle"):
            continue
        v = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in feat}
        pos = next((x.text for x in feat.iter() if x.tag.endswith("}pos") and x.text), None)
        if not pos:
            continue
        lat, lon = (float(s) for s in pos.split()[:2])
        text = " ".join(v.get("umfang", "").split())
        # The texts mix phases across sentences: anything in the whole text that limits the
        # closure (a section, a time, a later phase, access kept) leaves it as roadworks.
        blocked = bool(_FULL.search(text)) and not _LIMITED.search(text)
        m = _SPEED.search(text)
        end = _day(v.get("bauende"))
        out.append(RoadEvent(
            id=f"{source}:{feat.get('{http://www.opengis.net/gml/3.2}id') or len(out)}",
            kind="closure" if blocked else "roadworks", source=source, line=[(lon, lat)],
            start=_day(v.get("baubeginn")), end=end + 86400 if end is not None else None,
            speed_limit=int(m.group(1)) / 3.6 if m else None, blocked=blocked,
            text=f"{v.get('titel', '')} | {text}"[:300]))
    return out
