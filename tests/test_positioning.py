import random

from drivenow.positioning import Phone


def _drive(phone, v=12.0, seconds=120, dt=0.2, start=0.0):
    """A car at constant speed; returns the errors of the estimate (estimated minus true) once per step."""
    errors = []
    t = start
    for _ in range(int(seconds / dt)):
        t += dt
        s = v * t
        phone.tick(t, s, v)
        est = phone.estimate(t)
        if est is not None and t > 10:
            errors.append(est[0] - s)
    return errors


def _no_dropouts(mode, seed=1):
    return Phone(random.Random(seed), mode=mode, dropout_rate=0.0)


def test_filter_carries_the_estimate_across_the_delay():
    raw = _drive(_no_dropouts("raw"))
    filt = _drive(_no_dropouts("filtered"))
    mean = lambda xs: sum(xs) / len(xs)
    # The last fix describes the car 1-2 s ago: at 12 m/s the raw position lags by 12-24 m.
    assert mean(raw) < -10
    # The filter moves it forward to "now".
    assert abs(mean(filt)) < 2
    assert mean([abs(e) for e in filt]) < mean([abs(e) for e in raw]) / 3


def test_filter_averages_the_noise():
    filt = _drive(_no_dropouts("filtered"), v=0.0)
    raw = _drive(_no_dropouts("raw"), v=0.0)
    rms = lambda xs: (sum(x * x for x in xs) / len(xs)) ** 0.5
    assert rms(filt) < 0.7 * rms(raw)


def test_uncertainty_grows_during_a_dropout():
    phone = _no_dropouts("filtered")
    _drive(phone, seconds=60)
    t = 60.0
    sigma_before = phone.estimate(t)[2]
    phone._silent_until = t + 20          # the signal goes away for 20 s
    for _ in range(50):                   # 10 s without a fix
        t += 0.2
        phone.tick(t, 12.0 * t, 12.0)
    sigma_during = phone.estimate(t)[2]
    assert sigma_during > 3 * sigma_before
    assert sigma_during > 15              # enough to suspend the advice with the default threshold
    for _ in range(100):                  # the signal is back
        t += 0.2
        phone.tick(t, 12.0 * t, 12.0)
    assert phone.estimate(t)[2] < 6


def test_no_estimate_before_the_first_fix():
    phone = _no_dropouts("filtered")
    assert phone.estimate(0.0) is None
    phone.tick(0.0, 0.0, 10.0)
    assert phone.estimate(0.0) is not None
