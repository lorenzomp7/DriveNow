import json
import os

import pytest

from drivenow.hamburg.signals import GREEN, CyclePredictor, SignalHistory

DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "hamburg")
SCENARIOS = [s for s in ("willy-brandt", "gaertnerstrasse") if os.path.exists(os.path.join(DATA_ROOT, s, "routes.rou.xml"))]


def synthetic(cycles=30, C=60, green=(10, 35), jitter=None):
    """Signal 1 green from second 10 to 35 of every 60 s cycle; stream 2 marks cycle starts."""
    rows = []
    for k in range(cycles):
        t0 = 1000 + k * C
        g0, g1 = green
        if jitter and k % 2:
            g1 += jitter
        rows += [(t0, 0, 2), (t0 + g0, 3, 1), (t0 + g1, 2, 1), (t0 + g1 + 3, 1, 1)]
    return SignalHistory(rows)


def test_history_state_and_oracle_windows():
    h = synthetic()
    assert h.code_at(1, 1000 + 20) == 3
    assert h.code_at(1, 1000 + 40) == 1
    w = h.green_windows(1, 1000 + 5, 120)
    assert w[0] == (5, 30)
    assert w[1] == (65, 90)


def test_predictor_learns_fixed_cycle():
    h = synthetic()
    p = CyclePredictor(h, {1: 2}, lookback_cycles=10, threshold=0.8)
    t = 1000 + 25 * 60 + 5  # 5 s into a cycle, using only the past
    w = p.green_windows(1, t, 120)
    assert w[0] == pytest.approx((5, 30))
    assert w[1] == pytest.approx((65, 90))


def test_predictor_is_cautious_when_green_varies():
    # Every other cycle the green lasts 15 s longer: the extra part is only 50% likely.
    h = synthetic(jitter=15)
    p = CyclePredictor(h, {1: 2}, lookback_cycles=10, threshold=0.8)
    t = 1000 + 26 * 60 + 5
    w = p.green_windows(1, t, 60)
    assert w[0][1] == pytest.approx(30)  # the certain part only


def test_predictor_without_history_gives_no_forecast():
    h = SignalHistory([(1000, 3, 1)])
    assert CyclePredictor(h, {1: 2}).green_windows(1, 1010, 60) is None


def test_predictor_infers_cycle_when_feed_is_missing():
    # Same fixed cycle, but the cycle-second stream (2) stops after cycle 5.
    h = synthetic()
    rows = [(t, c, ds) for ds in h.times for t, c in zip(h.times[ds], h.codes[ds]) if ds == 1 or t < 1000 + 5 * 60]
    h = SignalHistory(rows)
    p = CyclePredictor(h, {1: 2}, lookback_cycles=10)
    t = 1000 + 25 * 60 + 5
    w = p.green_windows(1, t, 120)
    assert w[0] == pytest.approx((5, 30), abs=1)
    assert w[1] == pytest.approx((65, 90), abs=1)


def test_predictor_without_cycle_uses_green_share():
    # A main road that turns red only twice in 40 minutes: no cycle, mostly green.
    rows = [(0, 3, 1), (900, 1, 1), (915, 3, 1), (1800, 1, 1), (1812, 3, 1)]
    p = CyclePredictor(SignalHistory(rows), {}, threshold=0.8)
    w = p.green_windows(1, 2400, 60)
    assert w == [(0.0, 61.0)]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_built_files_are_consistent(scenario):
    data = os.path.join(DATA_ROOT, scenario)
    links = json.load(open(os.path.join(data, "links.json")))
    lanes = json.load(open(os.path.join(data, "lanes.json")))
    known = {t["datastreams"].get("primary_signal") for t in lanes}
    assert links and all(v["ds"] in known for v in links.values() if v["ds"])
    h = SignalHistory.load(os.path.join(data, "signals.csv.gz"))
    scen = json.load(open(os.path.join(data, "scenario.json")))
    used = {v["ds"] for v in links.values() if v["ds"]}
    with_data = [ds for ds in used if ds in h]
    assert len(with_data) >= 0.8 * len(used)
    # Most signals change during the first minutes of the test hour (some only on demand).
    changing = [ds for ds in with_data if h.changes(ds, scen["start"], scen["start"] + 600)]
    assert len(changing) >= 0.5 * len(with_data)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_sumo_runs_the_recorded_lights(scenario):
    pytest.importorskip("traci")
    from drivenow.hamburg.world import SUMO_CHAR, HamburgWorld

    try:
        w = HamburgWorld(scenario=scenario, penetration=1.0, label="hh_test_" + scenario)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    try:
        for _ in range(int(90 / w.dt)):
            w.step()
        checked = 0
        for key, rec in w.links.items():
            if rec["how"] != "direct" or rec["ds"] not in w.history:
                continue  # links without recorded data follow SUMO's own programme
            tls, idx = key.split("|")
            state = w.conn.trafficlight.getRedYellowGreenState(tls)[int(idx)]
            expected = SUMO_CHAR.get(w.history.code_at(rec["ds"], w.T0 + w.t), "O")
            assert state == expected, (key, state, expected)
            checked += 1
        assert checked >= 10
        snap = w.snapshot()
        assert snap["vehicles"] and snap["signals"]
        assert any(row[11] == "signal" for row in snap["vehicles"])
    finally:
        w.close()


def test_road_events_read_for_willy_brandt_in_the_simulation():
    # The police messages and city roadworks read on 23 Nov 2026 (road_events.json), applied
    # as they were then: lanes and streets closed in SUMO; known to the advice or not.
    pytest.importorskip("traci")
    from drivenow.hamburg.world import HamburgWorld
    w = HamburgWorld(scenario="willy-brandt", penetration=0.5, label="hh_events_aware", road_events="aware")
    try:
        names = {w.net.edges[e].name for ev in w.road_events for e in ev.edges}
        assert "Willy-Brandt-Straße" in names and "Repsoldstraße" in names
        assert "Spaldingstraße" not in names                 # only Mo-Fr 10-16: not in force when read
        assert w.clock0 and w.advisor.blocked_fn is not None
        closed = [e for ev in w.road_events if ev.blocked for e in ev.edges]
        assert closed and all(e in w._closed_edges for e in closed)
        lane = next(ev for ev in w.road_events if ev.lanes_closed and "Willy-Brandt" in ev.text)
        e = lane.edges[0]
        assert "passenger" in w.conn.lane.getDisallowed(e + "_0")      # the right lane is shut
        assert "passenger" not in w.conn.lane.getDisallowed(e + "_1")  # the others stay open
        for _ in range(100):
            w.step()
    finally:
        w.close()
    u = HamburgWorld(scenario="willy-brandt", penetration=0.5, label="hh_events_unaware", road_events="unaware")
    try:
        assert u.road_events and u.advisor.blocked_fn is None and u._closed_edges
    finally:
        u.close()


def test_open_street_data_in_the_hamburg_simulation():
    # public_data.json (read 23 Nov 2026): official limits at the recorded hour, zebra crossings,
    # and the traffic file built from the 2019 volumes.
    pytest.importorskip("traci")
    from drivenow.hamburg.world import HamburgWorld
    w = HamburgWorld(scenario="gaertnerstrasse", penetration=0.5, label="hh_public", official_limits=True,
                     crossings=True, demand="dtv")
    try:
        assert w.official_limits and w.crossings and w.advisor.crossings_fn is not None
        e, kmh = next((e, k) for e, k in w.official_limits.items() if k == 30)
        assert w.net.edges[e].speed == pytest.approx(30 / 3.6)
        assert w.conn.lane.getMaxSpeed(e + "_0") == pytest.approx(30 / 3.6)
        assert w._route_file.endswith("routes_dtv.rou.xml")
        for _ in range(50):
            w.step()
    finally:
        w.close()
    plain = HamburgWorld(scenario="gaertnerstrasse", penetration=0.5, label="hh_plain")
    try:
        assert not plain.official_limits and plain.advisor.crossings_fn is None
        assert plain._route_file.endswith("routes.rou.xml")
    finally:
        plain.close()
