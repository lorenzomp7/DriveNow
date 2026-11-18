import random

import pytest

from drivenow.probe import ProbeLearner


def drive(learner, cycle=90, green=40, anchor=1000.0, minutes=30, gap=6.0, seed=1, start=None, ask=False):
    """Cars arriving at a fixed-time light, as DriveNow cars would report them.

    With ``ask`` the timing is asked for every 10 s, as the advisor does while cars approach.
    """
    rng = random.Random(seed)
    t = anchor if start is None else start
    n = int(t)
    end = t + minutes * 60
    asked = t
    while t < end:
        n += 1
        vid = f"car{n}"
        if ask and t - asked >= 10:
            learner.timing("A", t)
            asked = t
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
    assert tm is not None and tm.level == "confirmed"
    assert tm.cycle == pytest.approx(90)
    assert tm.green == pytest.approx(40, abs=4)
    w = p.green_windows("A", end, 200)
    starts = [s for s, _ in w if s > 0]
    # The next green starts at the cycle boundary (within a couple of seconds).
    true_next = 90 - ((end - 1000.0) % 90)
    assert starts[0] == pytest.approx(true_next, abs=2.5)


def test_no_forecast_without_enough_reports():
    p = ProbeLearner()
    end = drive(p, minutes=2)
    assert p.green_windows("A", end, 120) is None
    assert p.green_windows("unknown", end, 120) is None


def test_a_few_cycles_give_a_suspected_timing():
    p = ProbeLearner()
    end = drive(p, minutes=6)
    tm = p.timing("A", end)
    assert tm is not None and tm.level == "suspected"
    assert p.green_windows("A", end, 120) is not None
    # Without levels only confirmed timings are given.
    q = ProbeLearner(levels=False)
    end = drive(q, minutes=6)
    assert q.timing("A", end) is None
    # Many cycles later the timing is confirmed.
    end = drive(p, minutes=20, start=end, seed=2)
    assert p.timing("A", end).level == "confirmed"


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


def test_steady_light_is_never_dropped():
    p = ProbeLearner()
    end = drive(p, minutes=60, ask=True)
    assert p.drops == []
    assert p.timing("A", end).cycle == pytest.approx(90)


def test_change_of_plan_is_noticed_and_learnt_again():
    p = ProbeLearner()
    change = drive(p, minutes=30, ask=True)
    assert p.timing("A", change).cycle == pytest.approx(90)
    # The city switches to a shorter cycle that starts elsewhere.
    end = drive(p, cycle=70, green=30, anchor=change + 25.0, start=change, minutes=20, seed=2, ask=True)
    assert len(p.drops) == 1
    assert change < p.drops[0][0] < change + 8 * 60   # noticed within a few minutes
    tm = p.timing("A", end)
    assert tm is not None and tm.cycle == pytest.approx(70)
    assert tm.green == pytest.approx(30, abs=4)


def _stand_in_green(p, tm, t, count):
    """``count`` seconds of a car standing at the line while ``tm`` says green, just before ``t``."""
    added, x = 0, t - 1
    while added < count:
        ph = (x - tm.anchor) % tm.cycle
        if 5 <= ph < tm.green - 3 and x not in p.red["A"]:
            p.red["A"].append(x)
            added += 1
        x -= 1
    p.red["A"].sort()
    p._fits.clear()


def test_some_cars_standing_in_the_forecast_green_make_it_suspected():
    p = ProbeLearner()
    end = drive(p, minutes=30)
    tm = p.timing("A", end)
    assert tm.level == "confirmed"
    reds = sum(1 for x in p.red["A"] if x >= end - p.recent)
    _stand_in_green(p, tm, end, int(0.25 * reds) + 1)   # about a fifth of the recent stops
    tm = p.timing("A", end)
    assert tm is not None and tm.level == "suspected" and p.drops == []


def test_many_cars_standing_in_the_forecast_green_drop_it():
    p = ProbeLearner()
    end = drive(p, minutes=30)
    tm = p.timing("A", end)
    reds = sum(1 for x in p.red["A"] if x >= end - p.recent)
    _stand_in_green(p, tm, end, reds)   # half of the recent stops
    p.timing("A", end)
    assert len(p.drops) == 1
