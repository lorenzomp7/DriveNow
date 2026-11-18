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


def test_coast_up_to_a_standing_queue():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    route = ["N0>J02"]  # main road towards a give-way junction, no light ahead
    pos = 0.0
    tail = 90.0
    occ = {"N0>J02": [(tail, 0.0)]}  # a car standing 90 m ahead
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, occ)
    assert a.kind == "cap"
    assert a.high == pytest.approx(coast_cap(tail - 2.0, 0.0, P))
    adv.queue_aware = False
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, occ)
    assert a.kind == "free"


def test_right_before_left_gives_way_to_the_right():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    node = net.nodes["J02"]
    node.right_before_left, node.major = True, set()
    adv = Advisor(net)
    route = ["W2>J02", "J02>J12"]  # heading east
    pos = net.edges["W2>J02"].length - 120.0
    from_right = [f for f in net.in_edges["J02"] if f != "W2>J02" and net.turn(f, "W2>J02") == "r"]
    from_left = [f for f in net.in_edges["J02"] if f != "W2>J02" and net.turn(f, "W2>J02") == "l"]
    assert from_right and from_left
    near = lambda e: {e: [(net.edges[e].length - 80.0, 10.0)]}
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, near(from_right[0]))
    assert a.kind == "slow"
    a, _ = adv.advise(route, 0, pos, 50 * KMH, 0.0, near(from_left[0]))
    assert a.kind in ("cap", "free")


def test_queue_behind_a_light_counts_over_several_edges():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    route = ["N0>J02", "J02>J12"]  # through the give-way junction, then a light
    occ = {"J02>J12": [(net.edges["J02>J12"].length - 5.0 * k, 0.0) for k in range(1, 4)],
           "N0>J02": [(net.edges["N0>J02"].length - 3.0, 0.0)]}  # the queue spills back over J02
    controls, _ = adv.controls_ahead(route, 0, 0.0, 0.0, occ)
    sig = [c for c in controls if c.kind == "signal"][0]
    assert sig.queue_len == 4


def _light(windows, certain):
    return [Control("signal", 300.0, "L", windows=windows, certain=certain)]


def test_suspected_light_still_gives_a_small_slowdown():
    sure = advise(_light([(23, 60)], True), 50 * KMH, 50 * KMH)
    unsure = advise(_light([(23, 60)], False), 50 * KMH, 50 * KMH)
    assert sure.kind == "slow" and sure.target > 40 * KMH
    assert unsure.kind == "slow" and unsure.target == pytest.approx(sure.target)
    assert "uncertain:L" in unsure.notes


def test_suspected_light_never_asks_for_a_big_slowdown():
    sure = advise(_light([(40, 80)], True), 50 * KMH, 50 * KMH)
    unsure = advise(_light([(40, 80)], False), 50 * KMH, 50 * KMH)
    assert sure.kind == "slow" and sure.target < 30 * KMH
    assert unsure.kind == "free" and unsure.target == pytest.approx(50 * KMH)
    assert "uncertain-skipped:L" in unsure.notes


def test_suspected_light_never_makes_a_car_coast_to_its_line():
    assert advise(_light([(100, 120)], True), 50 * KMH, 50 * KMH).kind == "stop"
    assert advise(_light([(100, 120)], False), 50 * KMH, 50 * KMH).kind == "free"


def test_suspected_light_keeps_a_cap_from_a_roundabout_beyond():
    controls = _light([(100, 120)], False) + [Control("yield", 320.0, "R", entry_speed=25 * KMH)]
    a = advise(controls, 50 * KMH, 50 * KMH)
    assert a.kind == "free"  # the roundabout is 320 m away: nothing to cap yet
    near = _light([(100, 120)], False) + [Control("yield", 330.0, "R", entry_speed=25 * KMH)]
    near[0].distance, near[1].distance = 60.0, 90.0
    a = advise(near, 50 * KMH, 50 * KMH)
    assert a.kind == "cap" and a.target == pytest.approx(coast_cap(90.0, 25 * KMH, P))


def test_lift_off_early_for_slow_traffic_ahead():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    adv.slow_traffic = True
    route = ["N0>J02"]  # main road, no light ahead
    occ = {"N0>J02": [(60.0, 4.0)]}  # a car 60 m ahead at 14 km/h
    a, nc = adv.advise(route, 0, 0.0, 50 * KMH, 0.0, occ)
    gap = 60.0 - 2.0
    # Coasting from 50 to 14 km/h behind a moving car: v <= v_slow + sqrt(2 b gap).
    assert a.kind == "cap" and a.high == pytest.approx(4.0 + math.sqrt(2 * P.coast_decel * gap))
    assert nc.kind == "queue" and nc.distance == pytest.approx(gap) and nc.group == "14"
    # By default only a standing queue counts.
    adv.slow_traffic = False
    a, nc = adv.advise(route, 0, 0.0, 50 * KMH, 0.0, occ)
    assert a.kind == "free" and nc is None  # the main road has nothing else ahead


def test_traffic_only_a_little_slower_is_not_slow_traffic():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    adv = Advisor(demo_city())
    adv.slow_traffic = True
    a, _ = adv.advise(["N0>J02"], 0, 0.0, 50 * KMH, 0.0, {"N0>J02": [(60.0, 10.0)]})
    assert a.kind == "free"


def test_cars_before_the_slow_ones_count_too():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    adv = Advisor(demo_city())
    adv.slow_traffic = True
    occ = {"N0>J02": [(40.0, 12.0), (100.0, 0.0)]}  # a moving car, then a standing one
    a, nc = adv.advise(["N0>J02"], 0, 0.0, 50 * KMH, 0.0, occ)
    assert nc.kind == "queue" and nc.distance == pytest.approx(100.0 - adv.car_space - 2.0)


def test_the_queue_of_a_known_light_is_left_to_the_green_advice():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    adv = Advisor(net)
    adv.slow_traffic = True
    route = ["N0>J02", "J02>J12"]  # then a light with a known plan
    L = net.edges["J02>J12"].length
    at_light = {"J02>J12": [(L - 5.0 - 7.5 * k, 0.0) for k in range(3)]}
    controls, _ = adv.controls_ahead(route, 0, 0.0, 0.0, at_light, 50 * KMH)
    assert not any(c.node == "queue" for c in controls)
    # A car standing far before the light is not its queue: coast up to it.
    far = {"J02>J12": [(50.0, 0.0)]}
    controls, _ = adv.controls_ahead(route, 0, 0.0, 0.0, far, 50 * KMH)
    q = [c for c in controls if c.node == "queue"]
    assert q and q[0].shown_distance == pytest.approx(net.edges["N0>J02"].length + 50.0 - 2.0)
    # The default rule: any known light ahead switches the queue rule off.
    adv.slow_traffic = False
    controls, _ = adv.controls_ahead(route, 0, 0.0, 0.0, far, 50 * KMH)
    assert not any(c.node == "queue" for c in controls)


def test_the_panel_hears_about_a_standing_queue_with_the_default_rule():
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    adv = Advisor(demo_city())
    a, nc = adv.advise(["N0>J02"], 0, 0.0, 50 * KMH, 0.0, {"N0>J02": [(90.0, 0.0)]})
    assert a.kind == "cap" and nc.kind == "queue" and nc.distance == pytest.approx(88.0) and nc.group == "0"


def test_intersect_windows():
    from drivenow.glosa import intersect_windows

    assert intersect_windows([(0, 10), (30, 40)], [(5, 35)]) == [(5, 10), (30, 35)]
    assert intersect_windows([(0, 10)], [(20, 30)]) == []


def _turn_advisor():
    """Demo city, with a light at J00 that is green at different times for each way out."""
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    ways = [n for n in net.edges["W0>J00"].next_edges if net.turn("W0>J00", n) != "t"]
    straight = next(n for n in ways if net.turn("W0>J00", n) == "s")
    turn = next(n for n in ways if n != straight)
    greens = {straight: [(0.0, 30.0)], turn: [(40.0, 70.0)]}

    def windows(edge, nxt, t):
        if edge != "W0>J00":
            return None
        return greens.get(nxt, [(0.0, 100.0)]), "g"

    return net, Advisor(net, windows_fn=windows), straight, turn


def test_without_a_route_the_car_is_assumed_to_go_straight_until_its_lane_tells():
    net, adv, straight, turn = _turn_advisor()
    route = ["W0>J00", turn]
    L = net.edges["W0>J00"].length
    adv.turns = "straight"
    guess, known = adv.guessed_route(route, 0, 0.0)
    assert guess[1] == straight and known == 1
    guess, known = adv.guessed_route(route, 0, L - 30.0)   # in the turning lane now
    assert guess[1] == turn and known == 2
    # Far from the line the advice follows the straight-on green, close to it the real one.
    c, _ = adv.controls_ahead(*_args(adv, route, 0.0))
    assert c[0].windows == [(0.0, 30.0)]


def _args(adv, route, pos):
    guess, _ = adv.guessed_route(route, 0, pos)
    return guess, 0, pos, 0.0, {}, 50 / 3.6


def test_common_green_is_the_green_every_way_out_shares():
    net, adv, straight, turn = _turn_advisor()
    adv.turns = "common"
    ways = [n for n in net.edges["W0>J00"].next_edges if net.turn("W0>J00", n) != "t"]
    c, _ = adv.controls_ahead(["W0>J00", straight], 0, 0.0, 0.0, {}, 0.0, ways)
    assert c[0].windows == []          # straight and turn are never green together here
    a, _ = adv.advise(["W0>J00", turn], 0, 0.0, 50 / 3.6, 0.0, {})
    assert a.kind == "stop"            # so far away, no speed is sure to get a green
    # In its lane the turn is known: only its own green counts, and no other way out.
    L = net.edges["W0>J00"].length
    guess, known = adv.guessed_route(["W0>J00", turn], 0, L - 30.0)
    assert known == 2
    c, _ = adv.controls_ahead(guess, 0, L - 30.0, 0.0, {}, 0.0, None)
    assert c[0].windows == [(40.0, 70.0)]


def test_common_green_reaches_a_light_beyond_the_current_edge():
    """The lanes split before the light: the light is one edge further on."""
    from drivenow.advisor import Advisor
    from drivenow.network import demo_city

    net = demo_city()
    before, first = "W2>J02", "J02>J12"   # a give-way junction, straight on, then the light J12 ...
    assert net.nodes[net.edges[before].to_node].kind != "signal" and net.turn(before, first) == "s"
    ways = [n for n in net.edges[first].next_edges if net.turn(first, n) != "t"]
    greens = {ways[0]: [(0.0, 30.0)], ways[1]: [(40.0, 70.0)]}

    def windows(edge, nxt, t):
        return (greens.get(nxt, [(0.0, 100.0)]), "g") if edge == first else None

    adv = Advisor(net, windows_fn=windows)
    adv.turns = "common"
    seen = {}
    orig = adv.controls_ahead

    def spy(*a, **k):
        seen["options"] = a[6] if len(a) > 6 else k.get("turn_options")
        return orig(*a, **k)

    adv.controls_ahead = spy
    adv.advise([before, first, ways[1]], 0, 0.0, 50 / 3.6, 0.0, {})
    assert sorted(seen["options"]) == sorted(ways)   # ... still two edges away
