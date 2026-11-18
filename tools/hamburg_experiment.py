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
ap.add_argument("--no-queue", action="store_true", help="old queue handling: only the queue on the car's own edge")
ap.add_argument("--replan", type=float, default=None, help="minute at which the lights without data switch to another plan")
ap.add_argument("--learner", choices=["old", "check", "levels"], default="check",
                help="lights learnt from the cars: as before, + check of recent reports, + suspected level")
ap.add_argument("--confirm-cycles", type=float, default=None, help="cycles a confirmed timing must span (learner default if unset)")
ap.add_argument("--no-confirm-clean", action="store_true", help="recent doubt does not demote a timing to suspected")
ap.add_argument("--slow-traffic", action="store_true", help="slow-traffic rule instead of the standing-queue rule (off by default)")
ap.add_argument("--slow-standing-only", action="store_true", help="slow-traffic rule for standing queues only")
ap.add_argument("--slow-min-gap", type=float, default=None, help="m: moving slow traffic counts only this far ahead")
ap.add_argument("--slow-min-kmh", type=float, default=None, help="km/h: and only when we drive at least this fast")
ap.add_argument("--follow-shown", action="store_true", help="DriveNow drivers act on the shown (steadied) advice, not the raw one")
ap.add_argument("--display-up", type=float, default=None, help="km/h: rises of the shown speed show from this size, and faster kinds at once")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--scale", type=float, default=1.0, help="share of the hour's traffic to run (1 = all)")
a = ap.parse_args()
w = HamburgWorld(scenario=a.scenario, penetration=0.0 if a.mode == "none" else 1.0, forecast="oracle" if a.mode == "oracle" else "predict",
                 seed=a.seed, label=f"exp_{a.seed}_{a.mode}_{a.threshold}_{a.scenario}_{a.no_gaps}_{a.no_left_gaps}_{a.inconsiderate}_{a.no_learn}_{a.no_queue}_{a.replan}_{a.learner}_{a.confirm_cycles}_{a.no_confirm_clean}_{a.slow_traffic}_{a.slow_standing_only}_{a.slow_min_gap}_{a.slow_min_kmh}_{a.follow_shown}_{a.display_up}", scale=a.scale,
                 threshold=a.threshold)
w.advisor.gap_aware = not a.no_gaps
w.advisor.gap_left_turns = not a.no_left_gaps
w.advisor.considerate = not a.inconsiderate
w.learn_lights = not a.no_learn
w.advisor.queue_aware = not a.no_queue
w.advisor.slow_traffic = a.slow_traffic
w.follow_shown = a.follow_shown
if a.display_up is not None:
    w.display_options = {"deadband_up": a.display_up / 3.6, "quick_up": True}
w.advisor.slow_moving = not a.slow_standing_only
if a.slow_min_gap is not None:
    w.advisor.slow_min_gap = a.slow_min_gap
if a.slow_min_kmh is not None:
    w.advisor.slow_min_speed = a.slow_min_kmh / 3.6
if a.learner == "levels":   # also suspected timings, used for small changes only
    w.probe.levels, w.probe.confirm_cycles, w.probe.confirm_clean = True, 8.0, True
if a.learner == "old":      # timings never dropped, as before the check of recent reports
    w.probe.check = False
t0 = time.time()
for i in range(int(a.minutes * 60 / w.dt)):
    if a.replan is not None and i == int(a.replan * 60 / w.dt):
        w.replan(seed=a.seed)
    w.step()
    if i % 3000 == 0:
        print(a.mode, round(w.t), "s, vehicles", len(w.vehicles), "wall", round(time.time() - t0), flush=True)
grp = w.stats[a.mode != "none"]
res = {"scenario": a.scenario, "mode": a.mode, "seed": a.seed, "gaps": not a.no_gaps, "left_gaps": not a.no_left_gaps, "considerate": not a.inconsiderate, "learn": not a.no_learn, "queue": not a.no_queue, "slow_traffic": a.slow_traffic, "follow_shown": a.follow_shown, "display_up": a.display_up, "slow_moving": w.advisor.slow_moving, "slow_min_gap": w.advisor.slow_min_gap, "slow_min_speed": w.advisor.slow_min_speed, "replan": a.replan, "learner": a.learner, "confirm_cycles": w.probe.confirm_cycles, "confirm_clean": w.probe.confirm_clean, "timings_dropped": len(w.probe.drops), "threshold": a.threshold, "minutes": a.minutes, "scale": a.scale, **grp.summary(),
       "still_in_network": len(w.vehicles), "along_corridor": w.corridor_stats[a.mode != "none"].summary()}
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"))
w.close()
