import pytest

from drivenow.committed import AgentTiming, committed_windows

T = AgentTiming(min_green=5, max_green=60, yellow=3, decision_interval=1)


def test_green_just_started_is_certain_for_the_minimum_green():
    w = committed_windows("green", since=100.0, now=100.0, timing=T)
    assert w.certain == [(0.0, 5.0)]
    assert w.likely == [(0.0, 60.0)]


def test_green_past_its_minimum_is_certain_only_to_the_next_decision():
    w = committed_windows("green", since=80.2, now=100.2, timing=T)
    assert w.certain == [(0.0, 0.8)]        # the agent may switch at t = 101
    assert w.likely == [(0.0, 40.8)]        # first decision once 60 s are reached: t = 141


def test_green_close_to_its_maximum_has_nothing_uncertain_left():
    w = committed_windows("green", since=41.0, now=100.5, timing=T)
    assert w.certain == w.likely == [(0.0, 0.5)]


def test_a_decision_due_now_is_still_to_come():
    # Advice at t = 101 comes before the decision taken at t = 101: the green may end right now.
    w = committed_windows("green", since=80.0, now=101.0, timing=T)
    assert w.certain == []


def test_conflicting_green_gives_a_certain_window_only_when_the_maximum_is_short():
    w = committed_windows("conflict_green", since=0.0, now=0.0, timing=T)
    assert w.certain == []                  # our green starts between t = 8 and t = 63
    assert w.likely == [(63.0, 68.0)]       # green by 63 at the latest, for at least 5 s
    short = AgentTiming(min_green=5, max_green=8, yellow=3)
    w = committed_windows("conflict_green", since=0.0, now=0.0, timing=short)
    assert w.certain == [(11.0, 13.0)]      # starts in [8, 11], lasts at least to 8 + 5
    assert w.likely == [(11.0, 16.0)]


def test_conflicting_yellow_means_our_green_comes_next():
    w = committed_windows("conflict_yellow", since=9.0, now=10.0, timing=T)
    assert w.certain == [(2.0, 7.0)]        # green at 12, at least to 17
    assert w.likely == [(2.0, 62.0)]


def test_our_yellow_waits_for_the_other_green():
    a = committed_windows("yellow", since=10.0, now=11.0, timing=T)
    b = committed_windows("conflict_green", since=13.0, now=11.0, timing=T)
    assert a == b


def test_an_agent_without_rules_commits_to_almost_nothing():
    raw = AgentTiming(min_green=0, max_green=None, yellow=3, decision_interval=1)
    w = committed_windows("green", since=50.0, now=60.2, timing=raw)
    assert w.certain == [(0.0, 0.8)]        # only until the next decision
    assert w.likely == [(0.0, 180.0)]       # it may hold it for ever: open-ended, never certain
    assert committed_windows("conflict_green", since=50.0, now=60.2, timing=raw).certain == []


def test_windows_stay_within_the_horizon():
    w = committed_windows("green", since=0.0, now=0.0, timing=T, horizon=30)
    assert w.likely == [(0.0, 30.0)]


def test_inconsistent_rules_are_refused():
    with pytest.raises(ValueError):
        AgentTiming(min_green=10, max_green=5)
    with pytest.raises(ValueError):
        AgentTiming(decision_interval=0)
    with pytest.raises(ValueError):
        committed_windows("purple", 0.0, 0.0, T)
