import random

import pytest

from drivenow.probe import ProbeLearner


def drive(learner, cycle=90, green=40, anchor=1000.0, minutes=30, gap=6.0, seed=1):
    """Cars arriving at a fixed-time light, as DriveNow cars would report them."""
    rng = random.Random(seed)
    t, n = anchor, 0
    end = anchor + minutes * 60
    while t < end:
        n += 1
        vid = f"car{n}"
        phase = (t - anchor) % cycle
        if phase < green - 2:
            learner.report(t, vid, "A", 0.0, 12.0, crossed=True)
        else:
            go = t + (cycle - phase)  # waits for the next green
            s = t
            while s < go:
                learner.report(s, vid, "A", 2.0, 0.0, crossed=False)
                s += 1.0
            learner.report(go + 1.0, vid, "A", 1.0, 3.0, crossed=False)  # drives off
            learner.report(go + 2.0, vid, "A", 0.0, 4.0, crossed=True)
        t += rng.expovariate(1 / gap)
    return end


def test_learns_a_fixed_cycle():
    p = ProbeLearner()
    end = drive(p)
    tm = p.timing("A", end)
    assert tm is not None
    assert tm.cycle == pytest.approx(90)
    assert tm.green == pytest.approx(40, abs=4)
    w = p.green_windows("A", end, 200)
    starts = [s for s, _ in w if s > 0]
    # The next green starts at the cycle boundary (within a couple of seconds).
    true_next = 90 - ((end - 1000.0) % 90)
    assert starts[0] == pytest.approx(true_next, abs=2.5)


def test_no_forecast_without_enough_reports():
    p = ProbeLearner()
    end = drive(p, minutes=3)
    assert p.green_windows("A", end, 120) is None
    assert p.green_windows("unknown", end, 120) is None


def test_no_forecast_for_an_irregular_light():
    p = ProbeLearner()
    rng = random.Random(3)
    t = 1000.0
    for i in range(400):
        # Green starts at random times: no fixed cycle to find.
        p.report(t, f"w{i}", "A", 2.0, 0.0, crossed=False)
        p.report(t + 1, f"w{i}", "A", 1.0, 3.0, crossed=False)
        p.report(t + 2, f"w{i}", "A", 0.0, 4.0, crossed=True)
        t += rng.uniform(15, 140)
    assert p.timing("A", t) is None
