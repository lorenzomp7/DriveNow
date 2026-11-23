"""Listen to Hamburg's live feed and estimate the queues at a scenario's lights.

    python tools/hamburg_live.py --scenario willy-brandt --minutes 10 [--out live.json]

Subscribes to the car loop detectors and signal colours of the scenario's lights
(lanes.json), passes every colour and loop state to the queue estimator (estimator.py) on
the scenario's SUMO lanes, and reports what came: messages per kind, which
detectors spoke, how late they arrived (time received minus the observation's
time) and the standing cars estimated at each approach with a loop. Needs network
access to tld.iot.hamburg.de (port 443).
"""
import argparse, json, os, sys, time
from collections import Counter, defaultdict
from statistics import median
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drivenow.estimator import QueueEstimator
from drivenow.hamburg.detectors import place_loops
from drivenow.hamburg.live import LiveFeed, parse_observation
from drivenow.hamburg.world import scenario_dir
from drivenow.network import load_sumo_net

ap = argparse.ArgumentParser()
ap.add_argument("--scenario", default="willy-brandt")
ap.add_argument("--minutes", type=float, default=10)
ap.add_argument("--out", default=None)
a = ap.parse_args()

d = scenario_dir(a.scenario)
lanes = json.load(open(os.path.join(d, "lanes.json")))
kind_of = {}
for t in lanes:
    for k in ("detector_car", "primary_signal"):
        if k in t["datastreams"]:
            kind_of[t["datastreams"][k]] = (k, t["name"])
net = load_sumo_net(os.path.join(d, "corridor.net.xml"))
lengths = {e.id: e.length for e in net.edges.values()}
loops = place_loops(d, lengths)
by_ds, by_sig = {}, {}
for lp in loops:
    by_ds.setdefault(lp.ds, []).append(lp)
    for s in lp.signal_ds:
        by_sig.setdefault(s, []).append(lp)
colour = {}   # last known colour code of each light
GREEN, KNOWN = {3, 6}, {1, 2, 3, 4, 6}   # Hamburg's colour codes (hamburg/signals.py); yellow counts as red
est = QueueEstimator([(lp.edge, lp.lane) for lp in loops], lengths, upstream=lambda e: None)

topics = [f"v1.1/Datastreams({ds})/Observations" for ds in kind_of]
feed = LiveFeed(topics)
feed.connect()
print(f"{a.scenario}: {sum(1 for k, _ in kind_of.values() if k == 'detector_car')} detectors "
      f"({len(loops)} on the SUMO lanes), {sum(1 for k, _ in kind_of.values() if k == 'primary_signal')} signals; "
      f"listening {a.minutes} min", flush=True)
count, heard, delay = Counter(), defaultdict(int), defaultdict(list)
t0 = time.time()
next_report = t0 + 60
try:
    for topic, payload, received in feed.observations(a.minutes * 60):
        obs = parse_observation(topic, payload)
        if obs is None:
            continue
        ds, t, result, _ = obs
        kind, name = kind_of.get(ds, ("other", "?"))
        count[kind] += 1
        delay[kind].append(received - t)
        if kind == "detector_car":
            heard[name] += 1
            for lp in by_ds.get(ds, []):
                est.event(lp.edge, lp.lane, t, result > 0)
        if int(result) in KNOWN and ds in by_sig:
            colour[ds] = int(result)
            for lp in by_sig[ds]:
                # The lane can drive off when any of its movements has green.
                est.signal(lp.edge, lp.lane, t, any(colour.get(s) in GREEN for s in lp.signal_ds))
        if received >= next_report:
            next_report += 60
            print(f"{round((received - t0) / 60)} min: {dict(count)}", flush=True)
finally:
    feed.close()

now = time.time()
res = {
    "scenario": a.scenario, "minutes": a.minutes, "started_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t0)),
    "messages": dict(count),
    "detectors_heard": len(heard), "detectors_total": sum(1 for k, _ in kind_of.values() if k == "detector_car"),
    "detector_messages": dict(heard),
    "median_delay_s": {k: round(median(v), 2) for k, v in delay.items() if v},
    "standing_now": {e: n for e, n in est.standing(now).items() if n},
}
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"), indent=1)
