"""Germany's motorways: the Autobahn GmbH's public API (verkehr.autobahn.de), no key.

    https://verkehr.autobahn.de/o/autobahn/                    the motorways
    https://verkehr.autobahn.de/o/autobahn/A7/services/roadworks
    .../services/warning   (jams, accidents, hazards)
    .../services/closure

Each item has a LineString (lon, lat), a display type, a blocked flag and a
German description that holds the speed limit ("Max. 80 km/h") and, for
warnings, the length of a jam ("Länge: 4 km").
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from ..road_events import RoadEvent, epoch

BASE = "https://verkehr.autobahn.de/o/autobahn"
SERVICES = ("roadworks", "warning", "closure")

_LIMIT = re.compile(r"Max\.\s*(\d+)\s*km/h")
_LENGTH = re.compile(r"Länge:\s*([\d.,]+)\s*km")


def _kind(service: str, item: dict, text: str) -> str:
    display = item.get("display_type", "")
    if service == "closure" or display == "CLOSURE" or display == "CLOSURE_ENTRY_EXIT":
        return "closure"
    if service == "roadworks":
        return "roadworks"
    low = text.lower()
    if "stau" in low or "stockender verkehr" in low:
        return "queue"
    if "unfall" in low:
        return "accident"
    return "hazard"


def parse(answer: dict, service: str, source: str = "autobahn") -> List[RoadEvent]:
    out = []
    for item in answer.get(service, []):
        text = " ".join(item.get("description") or [])
        geom = item.get("geometry") or {}
        line = [tuple(c[:2]) for c in geom.get("coordinates", [])] if geom.get("type") == "LineString" else []
        if not line and item.get("coordinate"):
            c = item["coordinate"]
            line = [(float(c["long"]), float(c["lat"]))]
        if not line:
            continue
        limit = _LIMIT.search(text)
        length = _LENGTH.search(text)
        kind = _kind(service, item, text)
        out.append(RoadEvent(
            id=f"{source}:{item.get('identifier')}", kind=kind, source=source, line=line,
            start=epoch(item.get("startTimestamp")), end=None,
            speed_limit=int(limit.group(1)) / 3.6 if limit else None,
            blocked=str(item.get("isBlocked", "false")).lower() == "true" or kind == "closure",
            queue_length=float(length.group(1).replace(",", ".")) * 1000 if length and kind == "queue" else None,
            text=(item.get("title", "") + " " + item.get("subtitle", "")).strip()))
    return out


def fetch_road(road: str, fetch: Callable[[str], dict], services=SERVICES) -> List[RoadEvent]:
    events: List[RoadEvent] = []
    for s in services:
        events += parse(fetch(f"{BASE}/{road}/services/{s}"), s)
    return events


def roads(fetch: Callable[[str], dict]) -> List[str]:
    return list(fetch(f"{BASE}/").get("roads", []))
