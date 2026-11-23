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
ap.add_argument("--vehicle-mix", action="store_true", help="DriveNow cars differ in how fast they slow down and speed up")
ap.add_argument("--profiles", choices=["fixed", "learned", "true"], default="fixed",
                help="what the advice knows of each car: the default, learnt from its driving, or the truth")
ap.add_argument("--turns", choices=["known", "straight", "common"], default="known",
                help="which way cars turn: known (a route is set), or guessed straight on, or the green all ways share")
ap.add_argument("--commit", type=float, default=50.0, help="m before the line where the lane gives the turn away (0: never)")
ap.add_argument("--gps", choices=["perfect", "raw", "filtered"], default="perfect",
                help="where the advice thinks the car is: the truth, or a phone's fixes as they are or filtered")
ap.add_argument("--gps-max-sigma", type=float, default=15.0, help="m: more uncertain than this, the advice is suspended")
ap.add_argument("--gps-sigma", type=float, default=None, help="m: error of a phone fix (default 5)")
ap.add_argument("--gps-delay", type=float, default=None, help="s: how late a fix arrives (default 1)")
ap.add_argument("--occupancy", choices=["truth", "fleet", "fleet+flow", "fused"], default="truth",
                help="where the advice sees the other cars: all of them, only DriveNow's, also aggregated speed, also loop detectors")
ap.add_argument("--det-offset", type=float, default=2.0, help="m before the stop line where the emulated loops lie")
ap.add_argument("--penetration", type=float, default=1.0, help="share of DriveNow cars (predict/oracle)")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--scale", type=float, default=1.0, help="share of the hour's traffic to run (1 = all)")
ap.add_argument("--road-events", choices=["aware", "unaware"], default=None,
                help="apply the road events read for the scenario (road_events.json); the advice knows them or not")
ap.add_argument("--demand", choices=["assumed", "dtv"], default="assumed",
                help="traffic file: the first one, or routes_dtv.rou.xml with the main roads from the 2019 volumes")
ap.add_argument("--official-limits", action="store_true", help="Hamburg's official speed limits at the recorded hour")
ap.add_argument("--crossings", action="store_true", help="the advice does not speed up just before zebra crossings")
ap.add_argument("--warmup", type=float, default=0.0, help="minutes at the start whose trips are not in 'measured'")
a = ap.parse_args()
w = HamburgWorld(scenario=a.scenario, penetration=0.0 if a.mode == "none" else a.penetration, forecast="oracle" if a.mode == "oracle" else "predict",
                 seed=a.seed, label=f"exp_{a.seed}_{a.mode}_{a.threshold}_{a.scenario}_{a.no_gaps}_{a.no_left_gaps}_{a.inconsiderate}_{a.no_learn}_{a.no_queue}_{a.replan}_{a.learner}_{a.confirm_cycles}_{a.no_confirm_clean}_{a.slow_traffic}_{a.slow_standing_only}_{a.slow_min_gap}_{a.slow_min_kmh}_{a.follow_shown}_{a.display_up}_{a.vehicle_mix}_{a.profiles}_{a.turns}_{a.commit}_{a.gps}_{a.gps_max_sigma}_{a.gps_sigma}_{a.gps_delay}_{a.occupancy}_{a.penetration}", scale=a.scale,
                 threshold=a.threshold, road_events=a.road_events, warmup=a.warmup * 60,
                 demand=a.demand, official_limits=a.official_limits, crossings=a.crossings)
w.advisor.gap_aware = not a.no_gaps
w.advisor.gap_left_turns = not a.no_left_gaps
w.advisor.considerate = not a.inconsiderate
w.learn_lights = not a.no_learn
w.advisor.queue_aware = not a.no_queue
w.advisor.slow_traffic = a.slow_traffic
w.follow_shown = a.follow_shown
w.vehicle_mix = a.vehicle_mix
w.advisor.turns = a.turns
w.advisor.commit_distance = a.commit
w.profiles = a.profiles
w.gps, w.gps_max_sigma = a.gps, a.gps_max_sigma
w.occupancy_source = a.occupancy
w.det_offset = a.det_offset
if a.gps_sigma is not None:
    w.gps_options["sigma_pos"] = a.gps_sigma
if a.gps_delay is not None:
    w.gps_options["delay"] = a.gps_delay
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
# Mean speed on the main roads' edges after the warm-up, every 5 s, against their limit: to be
# set beside Hamburg's traffic state (Verkehrslage), see tools/hamburg_verkehrslage_check.py.
main_edges = [e.id for e in w.net.edges.values() if e.name in w.main_roads]
speed_sum = {e: [0.0, 0] for e in main_edges}
for i in range(int(a.minutes * 60 / w.dt)):
    if a.replan is not None and i == int(a.replan * 60 / w.dt):
        w.replan(seed=a.seed)
    w.step()
    if w.t >= a.warmup * 60 and i % 25 == 0:
        for e in main_edges:
            if w.conn.edge.getLastStepVehicleNumber(e):
                acc = speed_sum[e]
                acc[0] += w.conn.edge.getLastStepMeanSpeed(e)
                acc[1] += 1
    if i % 3000 == 0:
        print(a.mode, round(w.t), "s, vehicles", len(w.vehicles), "wall", round(time.time() - t0), flush=True)
grp = w.stats[a.mode != "none"]
res = {"scenario": a.scenario, "mode": a.mode, "seed": a.seed, "gaps": not a.no_gaps, "left_gaps": not a.no_left_gaps, "considerate": not a.inconsiderate, "learn": not a.no_learn, "queue": not a.no_queue, "slow_traffic": a.slow_traffic, "follow_shown": a.follow_shown, "vehicle_mix": a.vehicle_mix, "profiles": a.profiles, "turns": a.turns, "commit": a.commit, "display_up": a.display_up, "slow_moving": w.advisor.slow_moving, "slow_min_gap": w.advisor.slow_min_gap, "slow_min_speed": w.advisor.slow_min_speed, "replan": a.replan, "learner": a.learner, "confirm_cycles": w.probe.confirm_cycles, "confirm_clean": w.probe.confirm_clean, "timings_dropped": len(w.probe.drops), "threshold": a.threshold, "minutes": a.minutes, "scale": a.scale, **grp.summary(),
       "still_in_network": len(w.vehicles), "along_corridor": w.corridor_stats[a.mode != "none"].summary()}
if w.learnt:
    def err(i, j):
        e = [abs(x[j] - x[i]) for x in w.learnt if x[j] is not None]
        return {"cars": len(w.learnt), "learnt": len(e), "mean_abs_error": round(sum(e) / len(e), 3) if e else None}
    res["learnt_coast"] = err(0, 1)
    res["learnt_accel"] = err(2, 3)
if w.gps_errors:
    e = sorted(abs(x) for x in w.gps_errors)
    res["gps"] = a.gps
    res["gps_error_m"] = {"median": round(e[len(e) // 2], 1), "p90": round(e[int(0.9 * len(e))], 1),
                          "mean_signed": round(sum(w.gps_errors) / len(w.gps_errors), 1)}
res["occupancy"], res["penetration"] = a.occupancy, a.penetration
if w.queue_errors:
    def qerr(xs):
        n = len(xs)
        return {"samples": n, "true_mean": round(sum(b for _, b in xs) / n, 2),
                "mae": round(sum(abs(e - b) for e, b in xs) / n, 2), "bias": round(sum(e - b for e, b in xs) / n, 2)}
    res["queue_error"] = {g: {k: qerr(v) for k, v in d.items()} for g, d in w.queue_errors.items()}
    res["loops"] = [{"thing": th, "emulated": em, "recorded": rec} for th, em, rec in w.loop_counts()]
res["unequipped"] = w.stats[False].summary() if a.mode != "none" else None
res["warmup_min"] = a.warmup
res["measured"] = {"drivenow": w.measured[True].summary() if a.mode != "none" else None,
                   "others": w.measured[False].summary()}
res["road_events"] = a.road_events
res["main_edge_speed_share"] = {e: round(sv / n / w.net.edges[e].speed, 3) for e, (sv, n) in speed_sum.items() if n}
res.update({"demand": a.demand, "official_limits": a.official_limits, "crossings": a.crossings,
            "official_limit_edges": len(w.official_limits), "crossing_edges": len(w.crossings),
            "loaded_trips": len(w.routes)})
if a.road_events:
    res["road_events_on_network"] = [{"kind": e.kind, "blocked": e.blocked, "lanes_closed": e.lanes_closed,
                                      "edges": len(e.edges), "text": e.text[:80]} for e in w.road_events]
    res.update({"events_in_force_at_start": sum(w._applied.values()), "zone_speeding_s": round(w.zone_speeding, 1),
                "zone_time_s": round(w.zone_time, 1), "rerouted": w.rerouted, "no_way_round": w.no_way_round})
print(json.dumps(res))
if a.out:
    json.dump(res, open(a.out, "w"))
w.close()
