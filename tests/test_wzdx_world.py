"""SUMO around a real US work zone (data/wzdx). Skipped when SUMO is not installed."""

import pytest

pytest.importorskip("traci")

from drivenow.network import SIGNAL  # noqa: E402
from drivenow.wzdx_world import WzdxWorld, scenarios  # noqa: E402

LIMIT = "modot-44-66-7th-st-lp-44-mo-66"   # a 56 km/h work zone on East 7th Street, Joplin
CLOSED = "idot-ia-12"                       # Gordon Drive, Sioux City, closed with a detour


def test_the_scenarios_are_there():
    assert {LIMIT, CLOSED} <= set(scenarios())


def test_work_zones_in_force_from_the_feed_and_known_to_the_advice():
    w = WzdxWorld(LIMIT, label="wz_aware")
    try:
        assert w.road_events and all(w._applied[ev.id] for ev in w.road_events)   # read while in force
        edge = next(e for ev in w.road_events if ev.speed_limit for e in ev.edges)
        assert w.advisor.limit_fn(edge, 0.0) == pytest.approx(56 / 3.6, abs=0.1)
        assert w.conn.lane.getMaxSpeed(edge + "_0") <= 56 / 3.6 + 0.01
        # Every light of the network has SUMO's programme, whatever SUMO calls it.
        signals = [n for n in w.net.nodes.values() if n.kind == SIGNAL]
        assert signals and all(n.plan is not None and n.plan_source == "sumo" for n in signals)
        for _ in range(50):
            w.step()
    finally:
        w.close()


def test_unaware_advice_and_learned_lights():
    w = WzdxWorld(LIMIT, lights="learned", events="unaware", label="wz_unaware")
    try:
        edge = next(e for ev in w.road_events if ev.speed_limit for e in ev.edges)
        assert w.advisor.limit_fn is None                                # the advice does not know
        assert w.conn.lane.getMaxSpeed(edge + "_0") <= 56 / 3.6 + 0.01   # the road has it
        assert w.advisor.windows_fn is not None
        approach = next(iter(w._probe_edges))
        assert w.advisor.windows_fn(approach, None, 0.0) is None         # nothing learned yet: no green
    finally:
        w.close()


def test_a_closed_road_sends_the_cars_round_it():
    w = WzdxWorld(CLOSED, label="wz_closed", warmup=0)
    try:
        assert w._closed_edges
        for _ in range(int(300 / w.dt)):
            w.step()
        assert w.rerouted > 0
        for veh in w.vehicles.values():
            assert not w._closed_edges.intersection(veh.route[veh.idx + 1:])
    finally:
        w.close()
