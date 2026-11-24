"""Fixed workloads to time and profile DriveNow's simulations (Piano DriveNow, punto 9, 24, 25).

How many cases a comparison can afford depends on the seconds of computer time per simulated
second. Each workload prints one JSON line: wall time, simulated time, their ratio and a
fingerprint of the results (trips, stops, brake energy, travel time of both groups), so that
a run before and after an optimisation, same seed, shows the same results.

    python tools/sim_profile.py sim --seconds 900            # built-in simulator, demo town
    python tools/sim_profile.py server --speed 10 --wall 30  # the server's loop at speed 10, no HTTP
    python tools/sim_profile.py sumo --seconds 900           # SUMO 2x2 grid (Python side)

Profile one with flameox (MCP or CLI, see docs/operational.md):

    flameox capture --provider py-spy --operation capture_and_rank_cpu_hotspots \\
        --cwd "$PWD" -- python tools/sim_profile.py sim --seconds 900
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def fingerprint(stats) -> dict:
    out = {}
    for group, g in stats.items():
        s = g.summary()
        out["drivenow" if group else "others"] = {k: s[k] for k in ("trips", "travel_time", "stops", "brake_energy_kj")}
    out["sha256"] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:16]
    return out


def run_sim(args) -> dict:
    from drivenow.network import demo_city, load_sumo_net
    from drivenow.simulation import SimConfig, Simulation

    net = load_sumo_net(args.net) if args.net else demo_city()
    sim = Simulation(net, SimConfig(demand=args.demand, penetration=args.penetration, seed=args.seed))
    t0 = time.perf_counter()
    while sim.t < args.seconds - 1e-9:
        sim.step()
    wall = time.perf_counter() - t0
    return {"workload": "sim", "net": net.name, "sim_s": round(sim.t, 1), "wall_s": round(wall, 2),
            "wall_per_sim_s": round(wall / sim.t, 5), "results": fingerprint(sim.stats)}


def run_server(args) -> dict:
    from drivenow.network import demo_city
    from drivenow.server import Runner
    from drivenow.simulation import SimConfig, Simulation

    sim = Simulation(demo_city(), SimConfig(demand=args.demand, penetration=args.penetration, seed=args.seed))
    runner = Runner(sim, speed=args.speed)
    t0 = time.perf_counter()
    runner.start()
    time.sleep(args.wall)
    runner._stop = True
    time.sleep(0.05)
    wall = time.perf_counter() - t0
    with runner.lock:
        reached, frames = sim.t, runner.version
    return {"workload": "server", "speed": args.speed, "wall_s": round(wall, 2), "sim_s": round(reached, 1),
            "achieved_speed": round(reached / wall, 2), "frames": frames}


def run_sumo(args) -> dict:
    from drivenow.sumo_world import SumoWorld

    net = args.net or os.path.join(REPO, "data", "sumo", "2_2_intersections.net.xml")
    w = SumoWorld(net, demand=args.demand, penetration=args.penetration, seed=args.seed,
                  duration=args.seconds, label=f"profile_{os.getpid()}")
    t0 = time.perf_counter()
    try:
        while w.t < args.seconds - 1e-9:
            w.step()
    finally:
        wall = time.perf_counter() - t0
        res = fingerprint(w.stats)
        w.close()
    return {"workload": "sumo", "net": os.path.basename(net), "sim_s": round(w.t, 1), "wall_s": round(wall, 2),
            "wall_per_sim_s": round(wall / w.t, 5), "results": res}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("workload", choices=["sim", "server", "sumo"])
    ap.add_argument("--net", help="SUMO .net.xml (sim: instead of the demo town; sumo: default the 2x2 grid)")
    ap.add_argument("--seconds", type=float, default=900.0, help="simulated seconds (sim, sumo)")
    ap.add_argument("--speed", type=float, default=10.0, help="server: simulation speed")
    ap.add_argument("--wall", type=float, default=30.0, help="server: wall-clock seconds to run")
    ap.add_argument("--demand", type=float, default=240.0)
    ap.add_argument("--penetration", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    out = {"sim": run_sim, "server": run_server, "sumo": run_sumo}[args.workload](args)
    out.update(seed=args.seed, demand=args.demand, penetration=args.penetration)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
