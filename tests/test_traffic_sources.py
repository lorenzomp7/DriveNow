import json
import os

import pytest

from drivenow.fleet import FleetDB
from drivenow.traffic_sources import TomTomFlow, WazeJams, edges_along

DATA = os.path.join(os.path.dirname(__file__), "data")
# A road heading east along 53.55 N, the opposite carriageway, and a road elsewhere.
POINTS = {
    "e1": [9.9900, 53.55, 90.0, 60.0],
    "e2": [9.9915, 53.55, 90.0, 60.0],
    "w1": [9.9905, 53.55, 270.0, 60.0],
    "far": [10.0100, 53.56, 90.0, 60.0],
}


def load(name):
    return json.load(open(os.path.join(DATA, name)))


def test_edges_along_a_line_follow_its_direction():
    line = [(9.9890, 53.55), (9.9930, 53.55)]
    assert sorted(edges_along(line, POINTS)) == ["e1", "e2"]
    assert edges_along(list(reversed(line)), POINTS) == ["w1"]


def test_tomtom_answer_fills_every_edge_of_the_segment():
    asked = []

    def fetch(url):
        asked.append(url)
        return load("tomtom_flow_segment.json")

    db = FleetDB({})
    tt = TomTomFlow("demo-key", POINTS, ["e1", "e2", "w1"], budget=3000, fetch=fetch)
    assert tt.poll(0.0, db, max_requests=5) == 2      # e1 answers for e2 too; w1 asks on its own
    assert "point=53.550000%2C9.990000" in asked[0] or "point=53.550000%2C9.991500" in asked[0]
    assert db.segments["e1"].speed == pytest.approx(5.0) and db.segments["e2"].free_speed == pytest.approx(50 / 3.6)
    assert db.segment_speed("e2", 10.0) == pytest.approx(5.0)   # 18 of 50 km/h: slow
    assert tt.poll(1.0, db, max_requests=5) == 0      # nothing due yet


def test_tomtom_paces_requests_to_the_budget():
    tt = TomTomFlow("k", POINTS, ["e1", "e2", "w1", "far"], budget=2400, period=86400.0, fetch=lambda u: {})
    assert tt.refresh == pytest.approx(144.0)         # 4 edges, 2400 a day: each every 144 s
    with pytest.raises(ValueError):
        TomTomFlow("", POINTS, ["e1"], budget=10)


def test_tomtom_low_confidence_or_bad_answer_is_skipped():
    weak = load("tomtom_flow_segment.json")
    weak["flowSegmentData"]["confidence"] = 0.2
    db = FleetDB({})
    TomTomFlow("k", POINTS, ["e1"], budget=100, fetch=lambda u: weak).poll(0.0, db)
    TomTomFlow("k", POINTS, ["e2"], budget=100, fetch=lambda u: {"error": "x"}).poll(0.0, db)
    assert db.segments == {}


def test_waze_jams_on_the_network():
    wz = WazeJams(POINTS, {e: 50 / 3.6 for e in POINTS})
    rows = wz.parse(load("waze_jams.json"))
    assert sorted(r[0] for r in rows) == ["e1", "e2"]           # the jam without a speed is skipped
    assert all(r[1] == pytest.approx(2.5) and r[3] == 3 for r in rows)
    db = FleetDB({})
    assert wz.apply(load("waze_jams.json"), 5.0, db) == 2
    assert db.segment_speed("e1", 10.0) == pytest.approx(2.5)


def test_hamburg_edge_points_cover_the_network():
    from drivenow.network import load_sumo_net
    for sc in ("willy-brandt", "gaertnerstrasse"):
        base = os.path.join(os.path.dirname(DATA), "..", "data", "hamburg", sc)
        pts = json.load(open(os.path.join(base, "edge_points.json")))
        net = load_sumo_net(os.path.join(base, "corridor.net.xml"))
        assert set(net.edges) <= set(pts)
        # Every point falls in the lon/lat box the network was cut from.
        import xml.etree.ElementTree as ET
        loc = ET.parse(os.path.join(base, "corridor.net.xml")).getroot().find("location")
        b = [float(v) for v in loc.attrib["origBoundary"].split(",")]
        assert all(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for lon, lat, _, _ in pts.values())
