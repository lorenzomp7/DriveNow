"""Road events saved for a Hamburg scenario (``tools/hamburg_road_events.py``), read back.

data/hamburg/<scenario>/road_events.json holds each source's raw answer as it was read.
``read`` parses them again with the source's own parser, so a change to a parser shows in
the simulations without reading the sources again.

The police messages and the city's roadworks are points without a direction, and a
point near a junction is near several streets. ``on_network`` therefore keeps, of the
edges a point matches, only those of the street the message names ("Hamburg,
Repsoldstraße zwischen ...", "Steinstraße, Speersort / ..."); a message whose street
is not in the network is left out. ``in_force`` drops a message given only at some
hours ("Mo - Fr zwischen 10:00 Uhr und 16:00 Uhr") outside them.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, List, Optional

from ..road_events import RoadEvent, match_all
from ..sources import datex2, hamburg_police, hamburg_roadworks

PARSERS = {
    "hamburg-police": lambda data: hamburg_police.parse(data.encode("utf-8")),
    "hamburg-roadworks": lambda data: hamburg_roadworks.parse(data.encode("utf-8")),
    "lsbg-datex2": lambda data: datex2.parse_situations(data.encode("utf-8"), "lsbg")[0],
}

_STREET = re.compile(r"^(?:[AB]\d+\s+)?Hamburg,?\s+(.+?)(?:\s+zwischen\b|\s+in Höhe\b|\s+bis\b|\s+gesperrt\b|,|$)")
_HOURS = re.compile(r"(?:(mo|di|mi|do|fr|sa|so)\s*-\s*(mo|di|mi|do|fr|sa|so)\s+)?zwischen\s+(\d{1,2})[:.](\d{2})\s*uhr"
                    r"\s+und\s+(\d{1,2})[:.](\d{2})\s*uhr", re.I)
_DAYS = ["mo", "di", "mi", "do", "fr", "sa", "so"]


def street(text: str) -> Optional[str]:
    """The street a message is about: after "Hamburg," (police), or the title's first name."""
    m = _STREET.search(text)
    if m:
        return m.group(1).strip()
    head = re.split(r"[,/|]", text, maxsplit=1)[0].strip()
    return head or None


def in_force(text: str, t: float) -> bool:
    """False when the text gives hours ("Mo - Fr zwischen 10:00 Uhr und 16:00 Uhr") and Hamburg's
    local time ``t`` is outside them."""
    m = _HOURS.search(text)
    if not m:
        return True
    try:
        from zoneinfo import ZoneInfo
        local = _dt.datetime.fromtimestamp(t, ZoneInfo("Europe/Berlin"))
    except Exception:  # no time zone data: CET
        local = _dt.datetime.fromtimestamp(t, _dt.timezone(_dt.timedelta(hours=1)))
    if m.group(1):
        a, b = _DAYS.index(m.group(1).lower()), _DAYS.index(m.group(2).lower())
        if not a <= local.weekday() <= b:
            return False
    now = local.hour * 60 + local.minute
    start, end = int(m.group(3)) * 60 + int(m.group(4)), int(m.group(5)) * 60 + int(m.group(6))
    return start <= now < end if start <= end else (now >= start or now < end)


def read(snapshot: Dict, only: Optional[str] = None) -> List[RoadEvent]:
    out: List[RoadEvent] = []
    for name, src in snapshot.get("sources", {}).items():
        if only is not None and name != only:
            continue
        out += PARSERS[name](src["data"])
    return out


def on_network(events: List[RoadEvent], points, names: Dict[str, str], t: float) -> List[RoadEvent]:
    """The events on the network at Hamburg time ``t``: points kept to the named street's edges."""
    out = []
    for ev in match_all([e for e in events if in_force(e.text, t)], points):
        if len(ev.line) == 1:
            s = street(ev.text)
            ev.edges = [e for e in ev.edges if s and names.get(e) == s]
        if ev.edges:
            out.append(ev)
    return out
