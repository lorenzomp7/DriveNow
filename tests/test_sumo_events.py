"""Road events in SUMO: in force only between their real start and end, closed lanes,
closed edges with the cars sent another way, and advice that does not know them.
Skipped when SUMO is not installed."""

import os

import pytest

pytest.importorskip("traci")

from drivenow.road_events import RoadEvent  # noqa: E402

NET = os.path.join(os.path.dirname(__file__), "..", "data", "sumo", "2_2_intersections.net.xml")
INNER = "intersectionNW___intersectionNE"
T0 = 1_800_000_000.0   # the events' clock at simulation time 0


def world(label, **kw):
    try:
        from drivenow.sumo_world import SumoWorld
        return SumoWorld(NET, demand=400, penetration=0.5, seed=5, label=label, **kw)
    except RuntimeError as exc:
        pytest.skip(str(exc))


def run_to(w, t):
    while w.t < t:
        w.step()


def test_a_dated_limit_applies_only_while_in_force_in_sumo_and_in_the_advice():
    w = world("ev_clock")
    try:
        w.clock0 = T0
        w.load_road_events([RoadEvent("wz", "roadworks", "test", [], start=T0 + 30, end=T0 + 90,
                                      speed_limit=5.0, edges=[INNER])])
        lane = INNER + "_0"
        before = w.conn.lane.getMaxSpeed(lane)
        assert before > 5.0
        run_to(w, 20)
        assert w.conn.lane.getMaxSpeed(lane) == pytest.approx(before)
        assert w.advisor.limit_fn(INNER, 20) is None
        run_to(w, 40)
        assert w.conn.lane.getMaxSpeed(lane) == pytest.approx(5.0)
        assert w.advisor.limit_fn(INNER, 40) == pytest.approx(5.0)
        run_to(w, 100)
        assert w.conn.lane.getMaxSpeed(lane) == pytest.approx(before)     # put back after the end
    finally:
        w.close()


def test_advice_that_does_not_know_the_roadworks_while_sumo_has_them():
    w = world("ev_unaware")
    try:
        w.road_events_advice = False
        w.load_road_events([RoadEvent("wz", "roadworks", "test", [], speed_limit=5.0, edges=[INNER])])
        assert w.advisor.limit_fn is None
        assert w.conn.lane.getMaxSpeed(INNER + "_0") == pytest.approx(5.0)
    finally:
        w.close()


def test_a_closed_edge_sends_the_cars_another_way():
    w = world("ev_closed")
    try:
        run_to(w, 60)
        w.load_road_events([RoadEvent("cl", "closure", "test", [], blocked=True, edges=[INNER])])
        run_to(w, 400)
        assert w.rerouted > 0
        for vid, veh in w.vehicles.items():
            assert INNER not in veh.route[veh.idx + 1:], vid
            assert veh.route == list(w.conn.vehicle.getRoute(vid))
        assert w.conn.lane.getDisallowed(INNER + "_0")
    finally:
        w.close()


def test_which_sumo_lanes_an_event_closes():
    from drivenow.sumo_world import SumoWorld
    idx = SumoWorld._closed_lane_indices
    assert idx(None, RoadEvent("a", "roadworks", "t", [], closed_lanes=[1], lane_count=2, lanes_closed=1), 2) == [1]
    assert idx(None, RoadEvent("b", "roadworks", "t", [], closed_lanes=[1], lane_count=3, lanes_closed=1), 2) == [0]
    assert idx(None, RoadEvent("c", "roadworks", "t", [], lanes_closed=3), 2) == [0]          # one stays open
    # "linker Fahrstreifen": the leftmost lane, whatever the number of lanes
    assert idx(None, RoadEvent("e", "restriction", "t", [], closed_lanes=[1], lanes_closed=1), 3) == [2]
    assert idx(None, RoadEvent("d", "closure", "t", [], blocked=True), 2) == [0, 1]
