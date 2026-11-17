"""One hour of Hamburg's evening peak, with and without DriveNow.

    python tools/hamburg_experiment.py none|predict|oracle [--minutes 60]
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drivenow.hamburg.world import HamburgWorld

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["none", "predict", "oracle"])
ap.add_argument("--minutes", type=float, default=60)
ap.add_argument("--out", default=None)
ap.add_argument("--scenario", default="gaertnerstrasse")
ap.add_argument("--threshold", type=float, default=0.8, help="green probability a forecast second needs")
ap.add_argument("--no-gaps", action="store_true", help="at give-way lines only cap the speed (old advice)")
ap.add_argument("--no-left-gaps", action="store_true", help="gap advice only on minor roads, not for left turns off the main road")
ap.add_argument("--inconsiderate", action="store_true", help="aim for gaps even with a car close behind")
ap.add_argument("--no-learn", action="store_true", help="do not learn lights without data from the cars")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--scale", type=float, default=1.0, help="share of the hour's traffic to run (1 = all)")
a = ap.parse_args()
w = HamburgWorld(scenario=a.scenario, penetration=0.0 if a.mode == "none" else 1.0, forecast="oracle" if a.mode == "oracle" else "predict",
                 seed=a.seed, label=f"exp_{a.seed}_{a.mode}_{a.threshold}_{a.scenario}_{a.no_gaps}_{a.no_left_gaps}_{a.inconsiderate}_{a.no_learn}", scale=a.scale,
                 threshold=a.threshold)
w.advisor.gap_aware = not a.no_gaps
w.advisor.gap_left_turns = not a.no_left_gaps
w.advisor.considerate = not a.inconsiderate
w.learn_lights = not a.no_learn
t0 = time.time()
for i in range(int(a.minutes * 60 / w.dt)):
    w.step()
    if i % 3000 == 0:
        print(a.mode, round(w.t), "s, vehicles", len(w.vehicles), "wall", round(time.time() - t0), flush=True)
grp = w.stats[a.mode != "none"]
res = {"scenario": a.scenario, "mode": a.mode, "seed": a.seed, "gaps": not a.no_gaps, "left_gaps": not a.no_left_gaps, "considerate": not a.inconsiderate, "learn": not a.no_learn, "threshold": a.threshold, "minutes": a.minutes, "scale": a.scale, **grp.summary(),
       "still_in_network": len(w.vehicles), "along_corridor": w.corridor_stats[a.mode != "none"].summary()}
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"))
w.close()
