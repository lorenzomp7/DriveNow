"""Run one simulation around a real US work zone (data/wzdx/<scenario>/) and print the result.

    python tools/wzdx_experiment.py none    --scenario modot-44-66-7th-st-lp-44-mo-66 --seed 1
    python tools/wzdx_experiment.py predict --scenario ... --lights learned --events unaware --seed 1

mode     none: nobody has DriveNow; predict: a share of the cars (--penetration) has it.
--lights known: the advice knows SUMO's fixed-time programme (as with SPaT);
         learned: it learns the timings from the DriveNow cars (probe.ProbeLearner).
--events aware: the advice knows the work zones; unaware: only the road has them;
         none: no work zones at all (the street as it would be without them).

Only trips that start after --warmup minutes are counted. The result has the
seed, scenario, assumed volume, penetration, duration, warm-up and completed
trips, and for the work zones: seconds the DriveNow advice asked for more than
a zone's limit (zone_speeding_s, of zone_time_s on such edges), cars sent
another way (rerouted) and cars taken out with no way round (no_way_round).
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drivenow.wzdx_world import WzdxWorld, scenarios  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["none", "predict"])
ap.add_argument("--scenario", choices=scenarios(), required=True)
ap.add_argument("--lights", choices=["known", "learned"], default="known")
ap.add_argument("--events", choices=["aware", "unaware", "none"], default="aware")
ap.add_argument("--penetration", type=float, default=0.5)
ap.add_argument("--minutes", type=float, default=60)
ap.add_argument("--warmup", type=float, default=10, help="minutes not counted at the start")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--out", default=None)
a = ap.parse_args()

w = WzdxWorld(a.scenario, penetration=0.0 if a.mode == "none" else a.penetration, lights=a.lights,
              events=a.events, seed=a.seed, scale=a.scale, warmup=a.warmup * 60,
              label=f"wzdx_{a.scenario}_{a.mode}_{a.lights}_{a.events}_{a.seed}_{a.penetration}")
t0 = time.time()
for i in range(int(a.minutes * 60 / w.dt)):
    w.step()
    if i % 3000 == 0:
        print(a.mode, round(w.t), "s, vehicles", len(w.vehicles), "wall", round(time.time() - t0), flush=True)
eq = a.mode != "none"
res = {"scenario": a.scenario, "mode": a.mode, "lights": a.lights, "events": a.events, "seed": a.seed,
       "penetration": a.penetration if eq else 0.0, "minutes": a.minutes, "warmup_min": a.warmup, "scale": a.scale,
       "veh_per_hour_assumed": w.info.get("veh_per_hour"), "work_zone": w.info.get("event"),
       "events_on_network": len(w.road_events), "events_in_force_at_start": sum(w._applied.values()),
       "all_trips": w.measured[True].trips + w.measured[False].trips,
       "drivenow": w.measured[True].summary() if eq else None, "others": w.measured[False].summary(),
       "through_zone": {"drivenow": w.through_zone[True].summary() if eq else None,
                        "others": w.through_zone[False].summary()},
       "zone_speeding_s": round(w.zone_speeding, 1), "zone_time_s": round(w.zone_time, 1),
       "rerouted": w.rerouted, "no_way_round": w.no_way_round, "still_in_network": len(w.vehicles),
       "wall_s": round(time.time() - t0)}
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"))
w.close()
