"""Agent-switched SUMO lights and committed windows. Skipped when SUMO is not installed."""

import os

import pytest

pytest.importorskip("traci")
pytest.importorskip("sumolib")

from drivenow.committed import AgentTiming, CommittedSignalSource  # noqa: E402
from tools import ppo_bench  # noqa: E402

NET = os.path.join(os.path.dirname(__file__), "..", "data", "sumo", "2_2_intersections.net.xml")


def _world(advice, label, seed=4, **kw):
    try:
        return ppo_bench.AgentWorld(NET, ppo_bench.random_policy(seed), ppo_bench.TIMINGS["rules"],
                                    advice=advice, demand=216, penetration=1.0, seed=seed, label=label, **kw)
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _run(w, until):
    while w.t < until:
        w.step()


def test_certain_windows_are_always_green_and_the_agent_keeps_its_rules():
    w = _world("certain", "bench_test_a")
    try:
        greens = {}
        tl = w.conn.trafficlight
        for _ in range(int(300 / w.dt)):
            w.step()
            for a in w.agents:
                phase = tl.getPhase(a)
                elapsed = tl.getPhaseDuration(a) - (tl.getNextSwitch(a) - w.t)
                if phase % 2 == 0:
                    greens[a] = max(greens.get(a, 0.0), elapsed)
                    assert elapsed <= 60 + 1.01   # the maximum green, up to the decision that ends it
        assert w.switches > 10
        assert w.source.certain_given > 100
        assert w.false_green == 0.0
        assert w.stats[True].red_runs == 0
    finally:
        w.close()


def test_the_check_sees_a_false_promise():
    # Windows computed for a 20 s minimum green while the agent may switch after 5 s.
    w = _world("certain", "bench_test_b")
    try:
        w.source = CommittedSignalSource(w.conn, w.net_path, AgentTiming(min_green=20, max_green=60),
                                         mode="certain", record=True)
        w.advisor.windows_fn = w.source
        _run(w, 300)
        assert w.false_green > 0
    finally:
        w.close()


def test_committed_mode_flags_the_likely_windows_as_not_certain():
    w = _world("committed", "bench_test_c")
    try:
        _run(w, 60)
        edge, nxt = next(k for k in w.source.movements if k[1] is not None)
        got = w.source(edge, nxt, w.t)
        assert got is not None
        windows, group, certain = got
        assert windows and group.startswith(w.source.movements[(edge, nxt)].tl)
        assert certain is False or windows == w.source.windows(edge, nxt, w.t).likely
    finally:
        w.close()


def test_every_case_gets_the_same_cars(tmp_path):
    a = ppo_bench.write_routes(NET, 216, 300, 7, str(tmp_path / "a"))
    b = ppo_bench.write_routes(NET, 216, 300, 7, str(tmp_path / "b"))
    assert ppo_bench.sha256(a) == ppo_bench.sha256(b)
    rows = [ppo_bench.run_case(NET, c, t, adv, 7, a, until=200, warmup=50, policy_factory=ppo_bench.random_policy)
            for c, t, adv in (("fixed", "", "none"), ("ppo", "rules", "committed"))]
    assert all(r["false_green_s"] == 0 for r in rows)
    assert all(r["trips"] > 20 for r in rows)


def test_agent_state_has_the_repository_layout():
    w = _world("none", "bench_test_d")
    try:
        _run(w, 5)
        state = w.agent_state()
        assert list(state) == ppo_bench.intersections(NET)
        # 2x2: four approaches per intersection, then phase and seconds in it (+ time: 7 inputs).
        assert all(len(s) == 6 for s in state.values())
        assert all(s[4] in (0.0, 1.0, 2.0, 3.0) for s in state.values())
    finally:
        w.close()
