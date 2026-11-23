"""Adapters for public and commercial traffic data, one per format.

Each turns a source's answer into what the fleet database (fleet.py) keeps:
speeds per edge, travel times, and road events (road_events.py). The catalogue
of the sources found, and which adapter reads each, is data/traffic_sources.json.

    datex2.py           DATEX II v2/v3: most European road authorities
    autobahn.py         Germany's motorways (Autobahn GmbH API)
    hamburg_traffic.py  Hamburg's traffic state on every road (WFS)
    digitraffic.py      Finland (Fintraffic Digitraffic)
    torino.py           Turin, Italy (5T)
    wzdx.py             US work zones (WZDx) and USDOT's feed registry
    here.py             HERE Traffic API v7 (key)
    osm.py              OpenStreetMap via Overpass: lights, limits, roadworks
    ../traffic_sources  TomTom Traffic Flow (key) and Waze for Cities jams (partners)
    ../hamburg/live.py  Hamburg's traffic lights and loop detectors, live (MQTT)
"""

from ..traffic_sources import TomTomFlow, WazeJams, edges_along  # noqa: F401
