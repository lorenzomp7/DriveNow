"""Turin, Italy: 5T's open real-time traffic flows (opendata.5t.torino.it/get_fdt).

Every 5 minutes, for each measurement point (``FDT_data``: lat, lng, road name,
direction), the flow (vehicles/h) and the mean speed (km/h).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from ..road_events import epoch

URL = "https://opendata.5t.torino.it/get_fdt"


def parse(data) -> List[dict]:
    root = ET.fromstring(data)
    t = epoch(root.get("end_time"))
    out = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "FDT_data":
            continue
        sf = next((x for x in el if x.tag.endswith("speedflow")), None)
        if sf is None:
            continue
        out.append({"lon": float(el.get("lng")), "lat": float(el.get("lat")), "road": el.get("Road_name", ""),
                    "direction": el.get("direction", ""), "flow": float(sf.get("flow", 0)),
                    "speed": float(sf.get("speed", 0)), "time": t})
    return out
