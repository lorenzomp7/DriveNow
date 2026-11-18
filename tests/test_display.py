import pytest

from drivenow.display import AdviceDisplay
from drivenow.glosa import Advice

KMH = 1 / 3.6


def slow(target, low=20, high=40):
    return Advice("slow", low * KMH, high * KMH, target * KMH)


def test_small_wobbles_are_not_shown():
    d = AdviceDisplay()
    assert d.update(0.0, slow(31), "L").target == pytest.approx(31 * KMH)
    for i, v in enumerate((32, 30, 32.5, 29.5)):
        assert d.update(0.6 * (i + 1), slow(v), "L").target == pytest.approx(31 * KMH)
    assert d.update(4.0, slow(35), "L").target == pytest.approx(35 * KMH)
    assert d.changes == 2 and d.announcements == 1


def test_a_shown_speed_out_of_the_new_band_changes_at_once():
    d = AdviceDisplay()
    d.update(0.0, slow(31, 20, 40), "L")
    # The band shrinks: 31 km/h would now arrive on red.
    shown = d.update(0.6, slow(29, 20, 28), "L")
    assert shown.target == pytest.approx(29 * KMH)


def test_a_new_kind_must_last_before_it_is_shown():
    d = AdviceDisplay()
    d.update(0.0, Advice("go", None, 50 * KMH, 50 * KMH), "L")
    flicker = Advice("slow", 30 * KMH, 49 * KMH, 49 * KMH)
    assert d.update(0.6, flicker, "L").kind == "go"
    assert d.update(1.2, Advice("go", None, 50 * KMH, 50 * KMH), "L").kind == "go"
    assert d.update(1.8, flicker, "L").kind == "go"       # the 2 s start again
    assert d.update(3.0, flicker, "L").kind == "go"
    assert d.update(4.0, flicker, "L").kind == "slow"


def test_stop_and_a_new_control_are_shown_at_once():
    d = AdviceDisplay()
    d.update(0.0, slow(31), "L")
    assert d.update(0.6, Advice("stop", None, None, 20 * KMH), "L").kind == "stop"
    assert d.announce
    assert d.update(1.2, Advice("cap", None, 25 * KMH, 25 * KMH), "R").kind == "cap"


def test_announcements_keep_a_minimum_gap_unless_urgent():
    d = AdviceDisplay()
    d.update(0.0, slow(31), "L1")
    d.update(1.0, slow(31), "L2")                         # new control, but just announced
    assert not d.announce
    d.update(2.0, Advice("stop", None, None, 20 * KMH), "L2")
    assert d.announce                                      # urgent: announced anyway
    d.update(12.0, slow(25), "L3")
    assert d.announce
    assert d.announcements == 3
