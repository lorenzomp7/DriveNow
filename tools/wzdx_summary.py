"""Summarise the work zone simulations (tools/wzdx_experiment.py --out) by scenario and condition.

    python tools/wzdx_summary.py RESULTS_DIR [--out data/wzdx/results.json]

For every scenario and condition: the seeds run, and the mean and standard deviation
over the seeds of the DriveNow cars' travel time, stops and braking energy (for the
runs without DriveNow, all cars), of the share of time on work zone edges the advice
asked for more than the zone's limit, and of the cars sent another way or taken out.
"""
import argparse
import glob
import json
import math
import os
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("--out", default=None)
a = ap.parse_args()

runs = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(a.dir, "*.json")))]
groups = defaultdict(list)
for r in runs:
    cond = "senza DriveNow" if r["mode"] == "none" else f"DriveNow, tempi {r['lights']}"
    cond += {"aware": ", conosce i cantieri", "unaware": ", non conosce i cantieri", "none": ", senza cantieri"}[r["events"]]
    if r["mode"] == "none":
        cond = "senza DriveNow" + (", senza cantieri" if r["events"] == "none" else ", con i cantieri")
    groups[(r["scenario"], cond)].append(r)


def stat(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
    return {"mean": round(m, 2), "sd": round(sd, 2), "n": len(xs)}


out = []
for (sc, cond), rs in sorted(groups.items()):
    g = [r["drivenow"] if r["drivenow"] else r["others"] for r in rs]
    row = {"scenario": sc, "condition": cond, "seeds": sorted(r["seed"] for r in rs),
           "penetration": rs[0]["penetration"], "minutes": rs[0]["minutes"], "warmup_min": rs[0]["warmup_min"],
           "veh_per_hour_assumed": rs[0]["veh_per_hour_assumed"],
           "trips_counted": stat([x["trips"] for x in g]), "all_trips": stat([r["all_trips"] for r in rs]),
           "travel_time_s": stat([x["travel_time"] for x in g]), "stops": stat([x["stops"] for x in g]),
           "brake_energy_kj": stat([x["brake_energy_kj"] for x in g]),
           "zone_speeding_pct": stat([100 * r["zone_speeding_s"] / r["zone_time_s"] if r["zone_time_s"] else None for r in rs]),
           "rerouted": stat([r["rerouted"] for r in rs]), "no_way_round": stat([r["no_way_round"] for r in rs]),
           "others_travel_time_s": stat([r["others"]["travel_time"] for r in rs if r["drivenow"]])}
    out.append(row)
    f = lambda s: "—" if s is None else f"{s['mean']:.1f} ± {s['sd']:.1f}"
    print(f"{sc[:24]:<24} {cond:<52} n={len(rs)} time {f(row['travel_time_s'])} s  stops {f(row['stops'])}  "
          f"brake {f(row['brake_energy_kj'])} kJ  over-limit {f(row['zone_speeding_pct'])} %  "
          f"rerouted {f(row['rerouted'])}  no-way {f(row['no_way_round'])}")
if a.out:
    json.dump({"runs": len(runs), "summary": out}, open(a.out, "w"), indent=1, ensure_ascii=False)
