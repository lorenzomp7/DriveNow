import math

import pytest

from drivenow.glosa import (
    Control,
    DriverProfile,
    Margins,
    advise,
    arrival_time,
    band_for_window,
    coast_cap,
    constant_speed_band,
    effective_windows,
)

P = DriverProfile()
KMH = 1 / 3.6


def test_constant_speed_arrival():
    assert arrival_time(100, 10, 10, P) == pytest.approx(10)


def test_arrival_time_never_increases_with_speed():
    for d in (20, 80, 250, 600):
        for v0 in (0, 5, 10, 14):
            last = math.inf
            for i in range(1, 200):
                v = i * 0.1
                t = arrival_time(d, v0, v, P)
                assert t <= last + 1e-9, (d, v0, v)
                last = t


def test_coasting_transition_is_counted():
    # 14 -> 8 m/s at 0.7 m/s^2 takes 8.57 s over 94.3 m, then 105.7 m at 8 m/s.
    t = arrival_time(200, 14, 8, P)
    t1 = 6 / 0.7
    d1 = 11 * t1
    assert t == pytest.approx(t1 + (200 - d1) / 8)


def test_band_edges_hit_window_edges():
    d, v0, window = 300.0, 13.9, (25.0, 45.0)
    band = band_for_window(lambda v: arrival_time(d, v0, v, P), window, 2.0, 13.9)
    assert band is not None
    assert arrival_time(d, v0, band.low, P) == pytest.approx(window[1], abs=0.05)
    assert arrival_time(d, v0, band.high, P) == pytest.approx(window[0], abs=0.05)
    # Just outside the band lands outside the window.
    assert arrival_time(d, v0, band.high + 0.3, P) < window[0]
    assert arrival_time(d, v0, band.low - 0.3, P) > window[1]


def test_band_none_when_window_unreachable():
    # 100 m in less than 3 s would need more than 33 m/s.
    assert band_for_window(lambda v: arrival_time(100, 13.9, v, P), (0, 3), 2, 13.9) is None


def test_constant_speed_band_closed_form():
    b = constant_speed_band(300, (20, 30), 1, 20)
    assert b.low == pytest.approx(10)
    assert b.high == pytest.approx(15)


def test_queue_delays_green():
    m = Margins()
    raw = [(10.0, 40.0)]
    assert effective_windows(raw, m)[0][0] == pytest.approx(10 + m.after_green_start)
    queued = effective_windows(raw, m, queue_len=4)
    assert queued[0][0] == pytest.approx(10 + m.startup_lost_time + 4 * m.queue_headway)
    assert queued[0][1] == pytest.approx(40 - m.before_green_end)


def test_advise_green_reachable_at_limit():
    limit = 50 * KMH
    adv = advise([Control("signal", 200, "J", windows=[(-5, 40)])], limit, limit)
    assert adv.kind == "go"
    assert adv.high == pytest.approx(limit)
    assert adv.target == pytest.approx(limit)


def test_advise_slow_down_for_next_green():
    limit = 50 * KMH
    adv = advise([Control("signal", 300, "J", windows=[(30, 60)])], limit, limit)
    assert adv.kind == "slow"
    assert adv.low < adv.target < adv.high < limit
    eta = arrival_time(300, limit, adv.target, P)
    assert 30 + Margins().after_green_start <= eta <= 60 - Margins().before_green_end


def test_advise_red_unavoidable():
    limit = 50 * KMH
    # Green ends in 5 s, next green in 3 minutes: neither is reachable from 150 m.
    adv = advise([Control("signal", 150, "J", windows=[(-20, 5), (180, 210)])], limit, limit)
    assert adv.kind == "stop"
    assert adv.low is None and adv.high is None


def test_roundabout_caps_speed_by_coasting():
    limit = 50 * KMH
    entry = 25 * KMH
    adv = advise([Control("yield", 100, "R", entry_speed=entry)], limit, limit)
    assert adv.kind == "cap"
    assert adv.high == pytest.approx(min(limit, coast_cap(100, entry, P)))
    near = advise([Control("yield", 30, "R", entry_speed=entry)], limit, limit)
    assert near.high == pytest.approx(math.sqrt(entry ** 2 + 2 * P.coast_decel * 30))


def test_chained_signals_narrow_the_band():
    limit = 50 * KMH
    one = advise([Control("signal", 250, "A", windows=[(0, 60)])], limit, limit)
    two = advise(
        [Control("signal", 250, "A", windows=[(0, 60)]), Control("signal", 510, "B", windows=[(50, 70)])],
        limit, limit, max_signals=2,
    )
    assert one.kind == "go"
    assert two.controls_used == 2
    assert two.high < one.high


def test_gap_clear_keeps_the_usual_cap():
    # Main road empty: same advice as a plain give-way line.
    c = Control("gap", 80.0, "J", windows=[(0.0, 1e9)], entry_speed=20 * KMH)
    a = advise([c], 50 * KMH, 50 * KMH, P)
    assert a.kind == "cap"
    assert a.high == pytest.approx(coast_cap(80.0, 20 * KMH, P))


def test_gap_slows_to_arrive_after_the_main_road_car():
    # A main-road car blocks the junction for the next 12 s: arrive just after it.
    c = Control("gap", 120.0, "J", windows=[(12.0, 1e9)], entry_speed=20 * KMH)
    a = advise([c], 50 * KMH, 50 * KMH, P)
    assert a.kind == "slow"
    assert 12.0 <= a.eta <= 12.0 + Margins().target_buffer + 0.5
    assert a.target < 50 * KMH


def test_gap_unreachable_rolls_to_the_line():
    c = Control("gap", 40.0, "J", windows=[(60.0, 1e9)], entry_speed=20 * KMH)
    a = advise([c], 30 * KMH, 50 * KMH, P)
    assert a.kind == "stop"


def test_main_road_gaps_from_traffic():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    node = net.nodes["J02"]
    major = sorted(node.major)[0]
    length = net.edges[major].length
    # One car 50 m away at 10 m/s: arrives in 5 s, so the junction is busy from 1.5 s to 6.5 s.
    occ = {major: [(length - 50.0, 10.0)]}
    gaps = adv.main_road_gaps("J02", occ)
    assert gaps[0] == pytest.approx((0.0, 5.0 - adv.gap_before))
    assert gaps[1][0] == pytest.approx(5.0 + adv.gap_after)
    assert adv.main_road_gaps("J02", {}) == [(0.0, 1e9)]


def test_advisor_waits_for_the_gap_at_a_give_way_line():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    route = ["W2>J02", "J02>J12"]  # minor road, straight across the main road
    pos = net.edges["W2>J02"].length - 120.0
    # A queue-free main road: the usual cap.
    a, nc = adv.advise(route, 0, pos, 50 * KMH, 0.0, {})
    assert nc.kind == "yield" and a.kind in ("cap", "free")
    # A main-road car 80 m away at 10 m/s reaches the junction in 8 s, just when we would:
    # slow down and arrive after it.
    occ = {"N0>J02": [(net.edges["N0>J02"].length - 80.0, 10.0)]}
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, occ)
    assert a.kind == "slow"
    assert a.eta >= 8.0 + adv.gap_after
    # The old behaviour is still available.
    adv.gap_aware = False
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, occ)
    assert a.kind in ("cap", "free")


def test_right_turn_only_yields_to_traffic_heading_the_same_way():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    route = ["W2>J02", "J02>J01"]  # minor road, turning right
    pos = net.edges["W2>J02"].length - 120.0
    # Traffic from J01 drives away from J01: it does not feed the lane we turn into.
    far_side = {"J01>J02": [(net.edges["J01>J02"].length - 80.0, 10.0)]}
    assert "J02>J01" not in net.edges["J01>J02"].next_edges
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, far_side)
    assert a.kind in ("cap", "free")
    same_way = {"N0>J02": [(net.edges["N0>J02"].length - 80.0, 10.0)]}
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, same_way)
    assert a.kind == "slow"


def test_no_early_slowing_with_a_car_close_behind():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    route = ["W2>J02", "J02>J12"]
    pos = net.edges["W2>J02"].length - 120.0
    occ = {"N0>J02": [(net.edges["N0>J02"].length - 80.0, 10.0)],
           "W2>J02": [(pos - 15.0, 13.0), (pos, 13.9)]}  # a follower 15 m behind
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, occ)
    assert a.kind in ("cap", "free")  # just the usual cap: do not hold the follower up
    adv.considerate = False
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, occ)
    assert a.kind == "slow"
