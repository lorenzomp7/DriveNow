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
a = ap.parse_args()
w = HamburgWorld(penetration=0.0 if a.mode == "none" else 1.0, forecast="oracle" if a.mode == "oracle" else "predict",
                 label="exp_" + a.mode)
t0 = time.time()
for i in range(int(a.minutes * 60 / w.dt)):
    w.step()
    if i % 3000 == 0:
        print(a.mode, round(w.t), "s, vehicles", len(w.vehicles), "wall", round(time.time() - t0), flush=True)
grp = w.stats[a.mode != "none"]
res = {"mode": a.mode, "minutes": a.minutes, **grp.summary(), "still_in_network": len(w.vehicles)}
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"))
w.close()
