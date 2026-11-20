import pytest
from drivenow.hamburg.signals import SignalHistory
from drivenow.darts_benchmark import forecast_at, score_pairs


def periodic_history(end=1800):
    return SignalHistory([(t, 3 if t % 60 < 25 else 1, 10) for t in range(end)])


def test_future_mutation_cannot_change_fit_or_prediction():
    h = periodic_history()
    changed = SignalHistory([(t, c if t <= 1200 else 9, 10)
                             for t, c in zip(h.times[10], h.codes[10])])
    seen = []
    def predict(values, period, horizon):
        seen.append((values, period, horizon))
        return [values[-period + (k % period)] for k in range(horizon)]
    before = forecast_at(h, 10, 1200, {}, 90, 900, predict)
    after = forecast_at(changed, 10, 1200, {}, 90, 900, predict)
    assert before == after and seen[0] == seen[1]
    assert len(seen[0][0]) == 900


def test_unknown_training_is_not_filled_with_red_or_future():
    h = SignalHistory([(0, 9, 10), (1199, 3, 10)])
    def forbidden(*a): raise AssertionError('model must abstain')
    assert forecast_at(h, 10, 1200, {}, 60, 900, forbidden) is None


def test_forecast_alignment_starts_at_origin_plus_one():
    h = periodic_history()
    def predict(values, period, horizon):
        assert values[-1] == 0  # t=1199 is red, encoded as zero
        return [1, 0, 1]
    got = forecast_at(h, 10, 1199, {}, 3, 900, predict)
    assert got['darts'] == [True, False, True]


def test_metrics_use_same_samples_and_reject_empty_report():
    report = score_pairs([(True, False, True), (False, True, False)])
    assert report['samples'] == 2
    assert report['darts']['accuracy'] == 1
    assert report['drivenow']['false_green_fraction'] == 0.5
    assert report['drivenow']['missed_green_fraction'] == 0.5
    with pytest.raises(ValueError, match='No paired'):
        score_pairs([])
