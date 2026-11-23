"""Adapters for public traffic data, on real answers recorded on 23 November 2026
(Autobahn, NDW, Belgium, Hamburg, Turin, Finland, USDOT registry) or, where the
host could not be reached, on answers written to the published format
(files named *_written.json)."""
import json
import os

import pytest

from drivenow.fleet import FleetDB
from drivenow.road_events import RoadEvent, epoch, match
from drivenow.sources import autobahn, datex2, digitraffic, hamburg_traffic, here, osm, torino, wzdx

DATA = os.path.join(os.path.dirname(__file__), "data")
KMH = 1 / 3.6
POINTS = {   # a road east along 53.55 N, its other direction, and one elsewhere
    "e1": [9.9900, 53.55, 90.0, 60.0],
    "e2": [9.9915, 53.55, 90.0, 60.0],
    "w1": [9.9905, 53.55, 270.0, 60.0],
    "far": [10.0100, 53.56, 90.0, 60.0],
}


def raw(name):
    return open(os.path.join(DATA, name), "rb").read()


def js(name):
    return json.loads(raw(name))


def test_epoch_reads_the_time_formats_of_the_sources():
    assert epoch("2026-11-23T10:00:00Z") == epoch("2026-11-23T11:00:00+01:00")
    assert epoch("2026-11-23T10:52:31.558144593Z") == pytest.approx(epoch("2026-11-23T10:52:31Z") + 0.558144)
    assert epoch("2026-11-23T10:00:00") == epoch("2026-11-23T10:00:00Z")      # no zone: UTC
    assert epoch(None) is None and epoch("yesterday") is None


def test_match_a_line_and_a_point():
    assert sorted(match(RoadEvent("a", "other", "t", [(9.9890, 53.55), (9.9930, 53.55)]), POINTS)) == ["e1", "e2"]
    assert match(RoadEvent("b", "other", "t", [(9.9915, 53.5501)]), POINTS)[:1] in (["e2"], ["e1"], ["w1"])
    assert match(RoadEvent("c", "other", "t", [(9.0, 50.0)]), POINTS) == []


# -- DATEX II (NDW Netherlands, Verkeerscentrum Belgium) ---------------------------------

def test_datex2_situations_from_the_netherlands():
    ev, st = datex2.parse_situations(raw("ndw_speed_limits_v3.xml"))
    assert st == {"records": 2, "with_coordinates": 2, "alert_c_only": 0, "no_location": 0}
    assert all(e.kind == "speed_limit" and e.speed_limit == pytest.approx(50 * KMH) for e in ev)
    assert all(len(e.line) > 1 for e in ev)
    ev, _ = datex2.parse_situations(raw("ndw_bridges_v3.xml"))
    assert ev and all(e.kind == "bridge" and e.blocked and e.end > e.start for e in ev)
    ev, st = datex2.parse_situations(raw("ndw_closures_v3.xml"))
    kinds = {e.kind for e in ev}
    assert "closure" in kinds and any(e.lanes_closed == 1 for e in ev)
    assert st["alert_c_only"] == 1                     # one record has no coordinates: left out


def test_datex2_alert_c_only_feeds_are_counted_not_guessed():
    ev, st = datex2.parse_situations(raw("be_situations_v2.xml"))
    assert ev == [] and st["records"] == st["alert_c_only"] == 3


def test_datex2_measured_speeds_and_travel_times():
    sites = datex2.parse_sites(raw("ndw_sites_v2.xml"))
    rows = datex2.parse_measured(raw("ndw_trafficspeed_v2.xml"))
    assert {r["site"] for r in rows} <= set(sites)
    assert all(0 < r["speed"] < 200 and r["flow"] > 0 for r in rows)
    tt = datex2.parse_measured(raw("ndw_traveltime_v2.xml"))
    assert [round(r["travel_time"], 1) for r in tt] == [23.2, 110.3]
    # On a network of our own around the first site: speed and travel time in the database.
    site, line = next(iter(sites.items()))
    lon, lat = line[0]
    pts = {"x": [lon, lat, 0.0, 200.0]}
    db = FleetDB({"x": 200.0})
    n = datex2.apply_measured([r for r in rows if r["site"] == site], sites, pts, db, {"x": 100 * KMH})
    assert n == 1 and db.segments["x"].source == "datex2"


# -- Germany, Hamburg, Finland, Turin ---------------------------------------------------------

def test_autobahn_roadworks_with_their_limit_and_closures():
    ev = autobahn.parse(js("autobahn_A7_roadworks.json"), "roadworks")
    assert ev and all(e.kind == "roadworks" and e.speed_limit == pytest.approx(80 * KMH) for e in ev)
    cl = autobahn.parse(js("autobahn_A7_closure.json"), "closure")
    assert cl and all(e.kind == "closure" and e.blocked and len(e.line) > 1 for e in cl)


def test_hamburg_traffic_state_as_speeds():
    rows = hamburg_traffic.parse(raw("hh_verkehrslage.xml"))
    assert len(rows) == 6 and {r["state"] for r in rows} <= set(hamburg_traffic.SPEED_SHARE)
    r = next(x for x in rows if x["state"] == "dicht")
    lon0, lat0 = r["line"][0]
    lon1, lat1 = r["line"][-1]
    import math
    heading = math.degrees(math.atan2((lon1 - lon0) * math.cos(math.radians(lat0)), lat1 - lat0)) % 360
    pts = {"x": [(lon0 + lon1) / 2, (lat0 + lat1) / 2, heading, 100.0]}
    db = FleetDB({"x": 100.0})
    assert hamburg_traffic.apply([r], pts, db, {"x": 50 * KMH}) == 1
    assert db.segments["x"].speed == pytest.approx(0.7 * 50 * KMH)
    assert "BBOX=53.5" in hamburg_traffic.url((9.98, 53.54, 10.02, 53.56))


def test_finland_road_works_with_speed_limits_and_dates():
    ev = digitraffic.parse(js("fi_digitraffic_roadworks.json"))
    assert ev and all(e.kind == "roadworks" and e.speed_limit == pytest.approx(50 * KMH) for e in ev)
    assert all(e.start < e.end for e in ev)


def test_turin_flows_and_speeds():
    rows = torino.parse(raw("torino_5t.xml"))
    assert len(rows) == 4 and all(r["speed"] > 0 and 7 < r["lon"] < 8 and 44 < r["lat"] < 46 for r in rows)


# -- USA, HERE, OpenStreetMap (written answers) --------------------------------------------

def test_wzdx_v4_work_zones_and_the_feed_registry():
    ev = wzdx.parse(js("wzdx_v4_written.json"))
    assert [e.kind for e in ev] == ["roadworks", "closure"]
    assert ev[0].speed_limit == pytest.approx(72.4 * KMH) and ev[0].lanes_closed == 1 and ev[1].blocked
    v3 = {"features": [{"id": "a", "properties": {"road_name": "I-15", "reduced_speed_limit": 45,
                                                    "vehicle_impact": "some-lanes-closed"},
                        "geometry": {"type": "LineString", "coordinates": [[-111.9, 40.7], [-111.9, 40.8]]}}]}
    assert wzdx.parse(v3)[0].speed_limit == pytest.approx(45 * 0.44704)
    reg = wzdx.parse_registry(json.load(open(os.path.join(os.path.dirname(DATA), "..", "data", "wzdx_registry.json"))))
    assert len(reg) >= 40 and sum(1 for r in reg if r["url"]) >= 35


def test_wzdx_detour_is_the_open_diversion_route_not_a_closure():
    # Real Florida DOT answer (23 Nov 2026): a detour road event is the road traffic is
    # sent onto. Closing it would close the way round the works.
    detour, closed = wzdx.parse(js("wzdx_fldot_detour.json"), "fldot")
    assert detour.kind == "other" and not detour.blocked and detour.text.startswith("Detour")
    assert closed.kind == "closure" and closed.blocked


def test_here_flow_and_incidents_into_the_database():
    db = FleetDB({e: 60.0 for e in POINTS})
    answers = {"flow": js("here_flow_written.json"), "incidents": js("here_incidents_written.json")}
    asked = []

    def fetch(u):
        asked.append(u)
        return answers["flow" if "/flow?" in u else "incidents"]

    h = here.HereTraffic("demo", center=(9.991, 53.55), radius=500, fetch=fetch)
    speeds, events = h.poll(0.0, db, POINTS)
    assert "in=circle:53.550000,9.991000;r=500" in asked[0] and "apiKey=demo" in asked[0]
    assert speeds == 2 and db.segments["e1"].speed == pytest.approx(4.2)    # low-confidence row skipped
    assert "w1" not in db.segments
    assert events == 2 and db.blocked("w1", epoch("2026-11-23T11:00:00Z")).kind == "closure"
    assert db.events["here:1001"].kind == "roadworks"
    assert h.poll(1.0, db, POINTS) == (0, 0)                                 # not due yet
    with pytest.raises(ValueError):
        here.HereTraffic("", center=(0, 0))


def test_osm_lights_roadworks_and_limits():
    got = osm.parse(js("overpass_written.json"))
    assert [s[2] for s in got["signals"]] == [11, 12]
    assert [e.id for e in got["roadworks"]] == ["osm:way/21"]
    assert [(round(v * 3.6), i) for _, v, i in got["maxspeed"]] == [(50, 22)]   # "DE:zone30" is no number
    near = osm.nearest_nodes(got["signals"], {"J1": (9.9901, 53.5500), "J2": (9.98, 53.54)})
    assert near == {"J1": 11}
    assert "traffic_signals" in osm.query((9.98, 53.54, 10.02, 53.56))


def test_hamburg_police_messages_closures_works_queues_and_lights_out_of_order():
    from drivenow.sources import hamburg_police
    ev = hamburg_police.parse(raw("hh_police_current.xml"))
    assert [e.kind for e in ev] == ["closure", "roadworks", "queue", "roadworks"]
    assert ev[0].blocked and not ev[1].blocked                      # "halbseitig gesperrt": half the road
    assert all(e.start and len(e.line) == 1 for e in ev)
    fault, = hamburg_police.parse(raw("hh_police_signal_fault.xml"))
    assert fault.kind == "signal_fault" and "Ampelanlage" in fault.text
    # Local time without a zone: 06:00 in Hamburg in May is 04:00 UTC.
    assert hamburg_police._local("2023-05-30T06:00:00") == epoch("2023-05-30T04:00:00Z")


def test_a_light_out_of_order_is_not_used_by_the_advice():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city
    net = demo_city()
    edge = next(e for e in net.edges.values() if net.nodes[e.to_node].kind == "signal")
    adv = Advisor(net)
    assert adv._signal(edge.id, None, 0.0) is not None
    db = FleetDB({e: net.edges[e].length for e in net.edges})
    db.event(RoadEvent("f", "signal_fault", "hamburg-police", [], edges=[edge.id]))
    adv.signal_fault_fn = db.signal_fault
    assert adv._signal(edge.id, None, 0.0) is None


def test_the_catalogue_names_only_adapters_that_exist():
    import importlib
    cat = json.load(open(os.path.join(os.path.dirname(DATA), "..", "data", "traffic_sources.json"), encoding="utf-8"))
    assert len(cat["sources"]) > 100
    for s in cat["sources"]:
        assert s["url"] and s["kinds"] and s["access"] and s["region"]
        if s.get("adapter"):
            mod, _, attr = s["adapter"].partition(".")
            if mod in ("traffic_sources", "hamburg"):
                m = importlib.import_module(f"drivenow.{mod}" + (".live" if mod == "hamburg" else ""))
                assert attr in ("", "live") or hasattr(m, attr)
            else:
                importlib.import_module(f"drivenow.sources.{mod}")
