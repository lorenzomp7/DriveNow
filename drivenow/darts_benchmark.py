"""Offline, past-only Darts seasonal baseline; never used by live GLOSA."""
from .hamburg.signals import CyclePredictor, GREEN, SignalHistory

KNOWN = {1, 2, 3, 4, 6}


def seasonal_predict(values, period, horizon):
    # Optional dependency imported only by the experiment, not by the server.
    from darts import TimeSeries
    from darts.models import NaiveSeasonal
    series = TimeSeries.from_values(values)
    model = NaiveSeasonal(K=period)
    model.fit(series)
    return model.predict(horizon).univariate_values().tolist()


def forecast_at(history, ds, origin, cycle_ds, horizon, lookback=1800, predict=None):
    if horizon < 1 or lookback < 2:
        raise ValueError('horizon must be positive and lookback >= 2')
    # Hard truncation protects both the period estimator and the existing
    # baseline, even if a future refactor accidentally asks beyond origin.
    past = SignalHistory([(t, c, stream) for stream in {ds, cycle_ds.get(ds)}
                          if stream is not None
                          for t, c in zip(history.times.get(stream, []), history.codes.get(stream, []))
                          if t <= origin])
    predictor = CyclePredictor(past, cycle_ds)
    cycle = predictor.cycle(ds, origin)
    if cycle is None:
        return None
    period = round(cycle.length)
    codes = [past.code_at(ds, t) for t in range(origin - lookback + 1, origin + 1)]
    # Keep only the trailing contiguous known segment. Do not turn missing
    # observations into red or interpolate through the held-out future.
    last_unknown = max((i for i, code in enumerate(codes) if code not in KNOWN), default=-1)
    values = [float(code in GREEN) for code in codes[last_unknown + 1:]]
    if period < 2 or len(values) < 2 * period:
        return None
    windows = predictor.green_windows(ds, origin, horizon + 1)
    if windows is None:
        return None
    prediction = (predict or seasonal_predict)(values, period, horizon)
    if len(prediction) != horizon:
        raise ValueError('Prediction length does not match horizon')
    return {'darts': [value >= 0.8 for value in prediction],
            'drivenow': [any(a <= k < b for a, b in windows) for k in range(1, horizon + 1)],
            'period_seconds': period, 'training_samples': len(values)}


def score_pairs(rows):
    """Rows: (truth, DriveNow prediction, Darts prediction), same samples."""
    if not rows:
        raise ValueError('No paired predictions; inspect coverage and training data')
    result = {'samples': len(rows)}
    for index, name in ((1, 'drivenow'), (2, 'darts')):
        result[name] = {
            'accuracy': sum(row[0] == row[index] for row in rows) / len(rows),
            'false_green_fraction': sum(not row[0] and row[index] for row in rows) / len(rows),
            'missed_green_fraction': sum(row[0] and not row[index] for row in rows) / len(rows),
        }
    return result
