import os

import pytest

from drivenow.network import BORDER, PRIORITY, ROUNDABOUT, SIGNAL, demo_city, load_sumo_net
from drivenow.signals import two_group_plan

HERE = os.path.dirname(__file__)
NET_2X2 = os.path.join(HERE, "..", "data", "sumo", "2_2_intersections.net.xml")


def test_two_group_plan_cycle_and_states():
    plan = two_group_plan(20, 30, yellow=3, all_red=2)
    assert plan.cycle == 60
    assert plan.state(0, "NS") == "G"
    assert plan.state(21, "NS") == "y"
    assert plan.state(24, "NS") == "r"
    assert plan.state(26, "EW") == "G"
    assert plan.state(60, "NS") == "G"  # wraps


def test_offset_shifts_the_cycle():
    plan = two_group_plan(20, 30, offset=10)
    assert plan.state(5, "NS") != "G"
    assert plan.state(10, "NS") == "G"


def test_green_windows_relative_to_now():
    plan = two_group_plan(20, 30, yellow=3, all_red=2)
    wins = plan.green_windows(t=5, group="NS", horizon=130)
    assert wins[0] == pytest.approx((-5, 15))
    assert wins[1] == pytest.approx((55, 75))
    ew = plan.green_windows(t=5, group="EW", horizon=100)
    assert ew[0] == pytest.approx((20, 50))


def test_time_to_change():
    plan = two_group_plan(20, 30, yellow=3, all_red=2)
    assert plan.time_to_change(5, "NS") == (pytest.approx(15), "y")
    assert plan.time_to_change(5, "EW") == (pytest.approx(20), "G")


def test_demo_city_has_every_kind_of_control():
    net = demo_city()
    kinds = {n.kind for n in net.nodes.values()}
    assert {SIGNAL, ROUNDABOUT, PRIORITY, BORDER} <= kinds
    for node in net.nodes.values():
        if node.kind == SIGNAL:
            assert set(node.group_of) == set(net.in_edges[node.id])


def test_demo_city_green_wave_on_viale_roma():
    net = demo_city()
    v = 45 / 3.6
    for name in ("J00", "J10", "J20"):
        node = net.nodes[name]
        if node.kind != SIGNAL:
            continue
        t_arrive = node.x / v + 1.0
        assert node.plan.state(t_arrive, "EW") == "G", name


def test_routes_end_at_a_border():
    import random
    net = demo_city()
    rng = random.Random(0)
    for e in net.entry_edges():
        for _ in range(20):
            r = net.random_route(e, rng)
            assert net.nodes[net.edges[r[-1]].to_node].kind == BORDER
            for a, b in zip(r, r[1:]):
                assert b in net.edges[a].next_edges


def test_load_base_repo_net():
    net = load_sumo_net(NET_2X2)
    signals = [n for n in net.nodes.values() if n.kind == SIGNAL]
    assert len(signals) == 4
    # The base repo uses 100000 s phases (its agent switches the lights), so
    # DriveNow falls back to the rule-based cycle: 20 s green + 3 s yellow per direction.
    assert all(n.plan.cycle == pytest.approx(46) for n in signals)
    assert all(e.length == pytest.approx(292) for e in net.edges.values())
    assert net.entry_edges()
