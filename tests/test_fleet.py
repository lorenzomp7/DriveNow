import sqlite3

from drivenow.fleet import FleetDB


def test_reports_become_occupancy_and_expire():
    db = FleetDB({"a": 200.0}, ttl=3.0, fill_queues=False)
    db.report("x", 10.0, "a", 50.0, 12.0)
    db.report("y", 11.0, "a", 20.0, 10.0)
    assert db.occupancy(11.0) == {"a": [(20.0, 10.0), (50.0, 12.0)]}
    assert db.occupancy(13.5) == {"a": [(20.0, 10.0)]}   # x last reported 3.5 s ago
    assert db.occupancy(20.0) == {}


def test_a_standing_car_reveals_the_queue_in_front_of_it():
    db = FleetDB({"a": 100.0}, car_space=7.5)
    db.report("x", 0.0, "a", 70.0, 0.0)                  # standing 30 m before the line
    occ = db.occupancy(0.0)["a"]
    assert occ[0] == (70.0, 0.0)
    filled = [p for p, v in occ[1:]]
    assert len(filled) == 3 and all(v == 0.0 for _, v in occ)  # 77.5, 85, 92.5
    assert max(filled) < 100.0


def test_no_queue_is_invented_in_front_of_a_moving_car():
    db = FleetDB({"a": 100.0})
    db.report("x", 0.0, "a", 40.0, 0.0)
    db.report("y", 0.0, "a", 60.0, 8.0)                  # the queue drives off from here
    occ = db.occupancy(0.0)["a"]
    assert all(p < 60.0 for p, v in occ if v == 0.0)
    assert (60.0, 8.0) in occ
    db = FleetDB({"a": 100.0})
    db.report("z", 0.0, "a", 30.0, 9.0)                  # nobody standing: nothing added
    assert db.occupancy(0.0) == {"a": [(30.0, 9.0)]}


def test_segment_speed_only_when_slow_and_fresh():
    db = FleetDB({})
    db.segment("a", 3.0, 13.9, t=0.0, source="test")
    db.segment("b", 12.0, 13.9, t=0.0)
    assert db.segment_speed("a", 60.0) == 3.0
    assert db.segment_speed("b", 60.0) is None           # not slow
    assert db.segment_speed("a", 400.0) is None          # too old
    assert db.segment_speed("c", 0.0) is None            # no data


def test_gaps_trusted_only_when_nearly_every_car_is_seen():
    assert FleetDB({}, share=1.0).gap_trust("n", 0.0)
    assert not FleetDB({}, share=0.5).gap_trust("n", 0.0)


def test_history_in_sqlite(tmp_path):
    path = str(tmp_path / "fleet.sqlite")
    db = FleetDB({"a": 100.0}, path=path)
    db.report("x", 1.0, "a", 10.0, 5.0)
    db.segment("a", 4.0, 13.9, 1.0, "test")
    db.close()
    con = sqlite3.connect(path)
    assert con.execute("SELECT car, edge, pos, v FROM reports").fetchall() == [("x", "a", 10.0, 5.0)]
    assert con.execute("SELECT edge, speed FROM segments").fetchall() == [("a", 4.0)]


def test_events_give_speed_limits_and_closures_while_active():
    from drivenow.road_events import RoadEvent
    db = FleetDB({"a": 100.0, "b": 100.0})
    db.event(RoadEvent("w1", "roadworks", "test", [], start=10.0, end=100.0, speed_limit=60 / 3.6, edges=["a"]))
    db.event(RoadEvent("c1", "closure", "test", [], blocked=True, edges=["b"]))
    assert db.speed_limit("a", 5.0) is None                  # not yet
    assert abs(db.speed_limit("a", 50.0) - 60 / 3.6) < 1e-9
    assert db.speed_limit("a", 100.0) is None                # over
    assert db.blocked("b", 0.0).id == "c1" and db.blocked("a", 0.0) is None
    db.replace_events("test", [])                            # the next reading of the source
    assert db.events == {}


def test_travel_time_from_the_most_direct_estimate():
    db = FleetDB({"a": 200.0})
    assert db.travel_time("a", 0.0) is None
    assert db.travel_time("a", 0.0, limit=20.0)[:2] == (10.0, "limit")
    db.segment("a", 5.0, 13.9, 0.0, "tomtom")
    assert db.travel_time("a", 10.0, limit=20.0)[:2] == (40.0, "tomtom")
    db.report("x", 0.0, "a", 1.0, 8.0)                       # a DriveNow car crosses "a" in 25 s
    db.report("x", 25.0, "b", 1.0, 8.0)
    assert db.travel_time("a", 30.0)[:2] == (25.0, "drivenow")
    db.measured_travel_time("a", 31.0, 30.0, "ndw")
    assert db.travel_time("a", 31.0)[:2] == (31.0, "ndw")


def test_a_reported_queue_becomes_standing_cars_at_the_end_of_its_edge():
    from drivenow.road_events import RoadEvent
    db = FleetDB({"a": 100.0}, car_space=7.5)
    db.event(RoadEvent("q", "queue", "waze", [], queue_length=30.0, edges=["a"]))
    occ = db.occupancy(0.0)["a"]
    assert len(occ) == 4 and all(v == 0.0 for _, v in occ) and min(p for p, _ in occ) > 70.0
