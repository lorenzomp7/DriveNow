"""Compare Darts NaiveSeasonal with DriveNow on recorded Hamburg signals."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drivenow.darts_benchmark import KNOWN, forecast_at, score_pairs
from drivenow.hamburg.signals import GREEN, SignalHistory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['willy-brandt', 'gaertnerstrasse'], default='willy-brandt')
    parser.add_argument('--signals', type=int, default=5)
    parser.add_argument('--minutes', type=int, default=20)
    parser.add_argument('--stride', type=int, default=17)
    parser.add_argument('--lookback', type=int, default=1800)
    parser.add_argument('--output', type=Path, default=ROOT / 'test-results/darts.json')
    args = parser.parse_args()
    if not 1 <= args.minutes <= 60 or args.signals < 1 or args.stride < 1 or args.lookback < 300:
        parser.error('Use minutes 1..60, signals/stride >= 1 and lookback >= 300')
    folder = ROOT / 'data/hamburg' / args.scenario
    paths = [folder / file for file in ['scenario.json', 'links.json', 'lanes.json', 'signals.csv.gz']]
    scenario, links, lanes = [json.loads(path.read_text()) for path in paths[:3]]
    history = SignalHistory.load(str(paths[3]))
    cycle_ds = {lane['datastreams']['primary_signal']: lane['datastreams']['cycle_second']
                for lane in lanes if {'primary_signal', 'cycle_second'} <= lane['datastreams'].keys()}
    selected = sorted({link['ds'] for link in links.values() if link.get('ds') in history.times})[:args.signals]
    start = scenario['start']
    horizons = [5, 15, 30, 60, 90]
    paired = {h: [] for h in horizons}
    attempted = {h: 0 for h in horizons}
    diagnostics = {ds: {'origins': 0, 'paired_origins': 0, 'periods_seconds': set()} for ds in selected}
    # Targets must remain inside the hour; the final origin leaves 90s holdout.
    end = min(start + args.minutes * 60, start + 3600 - max(horizons) + 1)
    for ds in selected:
        for origin in range(start, end, args.stride):
            predictions = forecast_at(history, ds, origin, cycle_ds, max(horizons), args.lookback)
            diagnostics[ds]['origins'] += 1
            if predictions is not None:
                diagnostics[ds]['paired_origins'] += 1
                diagnostics[ds]['periods_seconds'].add(predictions['period_seconds'])
            for horizon in horizons:
                target = origin + horizon
                # Never extrapolate truth beyond that stream's recording.
                if target > history.times[ds][-1]:
                    continue
                code = history.code_at(ds, target)
                if code not in KNOWN:
                    continue
                attempted[horizon] += 1
                if predictions is not None:
                    paired[horizon].append((code in GREEN, predictions['drivenow'][horizon-1],
                                            predictions['darts'][horizon-1]))
    metrics = {}
    for h in horizons:
        metrics[str(h)] = {**(score_pairs(paired[h]) if paired[h] else {'samples': 0}),
                           'eligible_targets': attempted[h],
                           'paired_coverage': len(paired[h]) / attempted[h] if attempted[h] else 0}
    report = {'scenario': args.scenario, 'signals': selected, 'origin_start': start,
              'origin_end_exclusive': end, 'stride_seconds': args.stride,
              'training_lookback_seconds': args.lookback, 'horizons_seconds': horizons,
              'model': 'Darts NaiveSeasonal; period inferred from past only',
              'threshold': 0.8, 'darts_version': version('u8darts'),
              'dataset_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              'metrics': metrics, 'signal_diagnostics': {ds: {**diag, 'periods_seconds': sorted(diag['periods_seconds'])} for ds, diag in diagnostics.items()},
              'live_model_changed': False, 'traffic_benefit_measured': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'metrics': metrics}, indent=2))
    return 0 if any(rows for rows in paired.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
