import random

import pytest

from drivenow.glosa import DriverProfile
from drivenow.profile_learner import ProfileLearner


def coast_down(p, rng, t, v, decel, seconds, noise=0.2):
    for _ in range(seconds):
        p.observe(t, v + rng.gauss(0, noise), "coast")
        t += 1.0
        v -= decel
    p.observe(t, v, None)  # the driver stops lifting off
    return t + 1.0


def test_learns_a_strong_regeneration_through_noisy_speeds():
    rng = random.Random(1)
    p = ProfileLearner()
    default = DriverProfile()
    assert p.profile(default) == default            # nothing learnt yet: the default
    t = 0.0
    for _ in range(6):
        t = coast_down(p, rng, t, 14.0, 1.3, 7)
    assert p.profile(default).coast_decel == pytest.approx(1.3, abs=0.15)
    assert p.profile(default).accel == default.accel  # never seen accelerating


def test_braking_and_slow_speeds_are_ignored():
    p = ProfileLearner()
    t = 0.0
    for _ in range(20):
        p.observe(t, 12.0, "coast")
        p.observe(t + 1, 8.0, "coast")    # 4 m/s^2: the brakes, not lifting off
        p.observe(t + 2, 2.5, "coast")    # below 3 m/s
        p.observe(t + 3, 2.0, "coast")
        t += 10
    assert p.coast == []


def test_accelerating_is_learnt_separately_when_asked():
    p = ProfileLearner(learn_accel=True)
    t, v = 0.0, 5.0
    for _ in range(12):
        p.observe(t, v, "accel")
        t, v = t + 1, v + 2.0
        if v > 13:
            p.observe(t, v, None)
            v, t = 5.0, t + 1
    assert p.profile(DriverProfile()).accel == pytest.approx(2.0)


def test_acceleration_is_not_used_by_default():
    p = ProfileLearner()
    for k in range(20):
        p.observe(k, 5.0 + 2.0 * k, "accel")
    assert len(p.accel) >= p.min_samples
    assert p.profile(DriverProfile()).accel == DriverProfile().accel


def test_lifting_off_is_not_braking_for_any_car():
    from drivenow.simulation import Vehicle, record_motion

    ev = Vehicle("ev", ["e"], True, 0.0, coast_true=1.3)
    usual = Vehicle("car", ["e"], True, 0.0)
    for _ in range(10):
        record_motion(ev, 10.0, 10.0 - 1.3 * 0.2, 0.2)       # regeneration: free
        record_motion(usual, 10.0, 10.0 - 1.3 * 0.2, 0.2)    # 1.3 m/s^2 in a usual car: the brakes
    assert ev.brake_events == 0 and ev.brake_energy == 0
    assert usual.brake_events == 1 and usual.brake_energy > 0
    sailing = Vehicle("sail", ["e"], True, 0.0, coast_true=0.35)
    record_motion(sailing, 10.0, 10.0 - 0.6 * 0.2, 0.2)      # more than it loses by itself: brakes
    assert sailing.brake_energy > 0
