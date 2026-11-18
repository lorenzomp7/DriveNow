"""How well the timings learnt from the cars forecast the lights without data.

    python tools/probe_accuracy.py --scenario willy-brandt --minutes 60 [--replan 30]

Runs Hamburg with 100% DriveNow cars. Every 5 s, for each car on the approach to a
light without Hamburg data, it notes what the learnt timing forecasts for the
movement that car will take, 5 to 60 s ahead, and later compares it with what
SUMO actually showed. Yellow counts as not green, as in the advice.

With ``--replan M`` the lights without data switch to another plan after M
minutes (see ``HamburgWorld.replan``), and the report also shows the first 15
minutes after the switch on their own.
"""
import argparse, json, os, sys, time
import xml.etree.ElementTree as ET
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drivenow.hamburg.world import HamburgWorld, scenario_dir

HORIZONS = (5, 15, 30, 60)

ap = argparse.ArgumentParser()
ap.add_argument("--scenario", default="willy-brandt")
ap.add_argument("--minutes", type=float, default=60)
ap.add_argument("--replan", type=float, default=None, help="minute at which the lights without data change plan")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--learner", choices=["old", "check", "levels"], default="levels",
                help="lights learnt from the cars: as before, + check of recent reports, + suspected level")
ap.add_argument("--out", default=None)
a = ap.parse_args()

w = HamburgWorld(scenario=a.scenario, penetration=1.0, seed=a.seed, scale=a.scale,
                 label=f"acc_{a.scenario}_{a.seed}_{a.replan}_{a.learner}")
conn = w.conn
if a.learner != "levels":   # only confirmed timings, as before the suspected level
    w.probe.levels, w.probe.confirm_cycles, w.probe.confirm_clean = False, 0.0, False
if a.learner == "old":      # and never dropped
    w.probe.check = False

# (from edge, to edge) -> (light id, link index), from the network's connections
link_of = {}
for c in ET.parse(os.path.join(scenario_dir(a.scenario), "corridor.net.xml")).getroot().iter("connection"):
    if "tl" in c.attrib and c.attrib["from"] in w._probe_edges:
        link_of.setdefault((c.attrib["from"], c.attrib["to"]), (c.attrib["tl"], int(c.attrib["linkIndex"])))
probe_tls = {tls for tls, _ in link_of.values()}

states = {}          # (tls, second) -> state string
preds = []           # (t, tls, idx, horizon, predicted_green, level)
asked = []          # (t, level): every evaluation, level "none" when there is no forecast
steps_per_s = round(1 / w.dt)
t0 = time.time()
for i in range(int(a.minutes * 60 / w.dt)):
    if a.replan is not None and i == int(a.replan * 60 / w.dt):
        w.replan(seed=a.seed)
    w.step()
    if i % steps_per_s:
        continue
    sec = round(w.t)
    for tls in probe_tls:
        states[(tls, sec)] = conn.trafficlight.getRedYellowGreenState(tls)
    if sec % 5:
        continue
    for vid, veh in w.vehicles.items():
        if not veh.route or vid in w._internal or veh.edge not in w._probe_edges:
            continue
        k = veh.route.index(veh.edge) if veh.edge in veh.route else -1
        if k < 0 or k + 1 >= len(veh.route):
            continue
        link = link_of.get((veh.edge, veh.route[k + 1]))
        if link is None:
            continue
        tls, idx = link
        tm = w.probe.timing(veh.edge, w.t)
        win = w.probe.green_windows(veh.edge, w.t, 120)
        level = "none" if tm is None or win is None else getattr(tm, "level", "confirmed")
        asked.append((sec, level))
        if level == "none":
            continue
        for h in HORIZONS:
            green = any(s <= h < e for s, e in win)
            preds.append((sec, tls, idx, h, green, level))
    if i % 3000 == 0:
        print(round(w.t), "s, vehicles", len(w.vehicles), "wall", round(time.time() - t0), flush=True)
w.close()


def score(rows):
    out = {}
    for h in HORIZONS:
        n = ok = false_green = missed_green = 0
        for sec, tls, idx, hh, green, _ in rows:
            if hh != h:
                continue
            st = states.get((tls, sec + h))
            if st is None:
                continue
            real = st[idx] in "Gg"
            n += 1
            ok += green == real
            false_green += green and not real
            missed_green += real and not green
        if n:
            out[h] = {"n": n, "correct": round(100 * ok / n, 1), "promised_green_was_red": round(100 * false_green / n, 1),
                      "green_not_forecast": round(100 * missed_green / n, 1)}
    return out


def counts(rows):
    c = defaultdict(int)
    for _, level in rows:
        c[level] += 1
    return dict(c)


res = {"scenario": a.scenario, "minutes": a.minutes, "replan": a.replan, "seed": a.seed,
       "evaluations": counts(asked),
       "approaches_with_forecast": len({(r[1], r[2]) for r in preds}),
       "timings_dropped": [round(t) for t, _ in getattr(w.probe, "drops", [])],
       "all": score(preds)}
for level in sorted({r[5] for r in preds}):
    res[level] = score([r for r in preds if r[5] == level])
if a.replan is not None:
    lo, hi = a.replan * 60, a.replan * 60 + 15 * 60
    res["after_replan_15min"] = score([r for r in preds if lo <= r[0] < hi])
    res["after_replan_15min_evaluations"] = counts([r for r in asked if lo <= r[0] < hi])
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"), indent=1)
