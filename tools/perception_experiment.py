"""Self-driving DriveNow cars with different sensors and weather, in the built-in simulation.

    python tools/perception_experiment.py                    # demo town and the 3x3 grid
    python tools/perception_experiment.py --minutes 10 --nets demo

Every equipped car drives itself (``SimConfig.autopilot``) from what its own
sensors see; all cars are equipped, except in the "people" row. Cars
double-park now and then (30 an hour), to have cars standing in the lane.
Prints a Markdown table per network.
"""

from __future__ import annotations

import argparse
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivenow.network import demo_city, load_sumo_net  # noqa: E402
from drivenow.simulation import SimConfig, Simulation  # noqa: E402

NETS = {"demo": None, "grid3": "data/sumo/3_3_intersections.net.xml"}
COLS = ["stops", "brake_events", "brake_energy_kj", "travel_time", "collisions", "conflicts", "red_runs",
        "aeb", "phantom", "gap_rmse_m", "missed_pct", "km"]


def run(job):
    net_key, label, kw, minutes, seed = job
    path = NETS[net_key]
    net = demo_city() if path is None else load_sumo_net(path)
    pen = kw.pop("penetration", 1.0)
    sim = Simulation(net, SimConfig(penetration=pen, seed=seed, double_parking=30.0, **kw))
    sim.run(minutes * 60)
    return net_key, label, sim.stats[pen > 0.5].summary()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--nets", nargs="+", default=list(NETS))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    cases = [("people (no DriveNow)", {"penetration": 0.0}),
             ("DriveNow, people drive", {})]
    for weather in ("clear", "night", "rain", "fog"):
        for suite in ("perfect", "camera", "camera+radar", "camera+radar+lidar"):
            cases.append((f"{weather} | {suite}", {"autopilot": True, "sensors": suite, "weather": weather}))
    for weather in ("clear", "fog"):
        for suite in ("camera", "camera+radar"):
            cases.append((f"{weather} | {suite}, no timings",
                          {"autopilot": True, "sensors": suite, "weather": weather, "light_timing": False}))
    jobs = [(n, label, dict(kw), a.minutes, a.seed) for n in a.nets for label, kw in cases]
    with Pool(a.jobs) as pool:
        results = pool.map(run, jobs)
    for n in a.nets:
        print(f"\n### {n}\n")
        print("| case | " + " | ".join(COLS) + " |")
        print("|" + "---|" * (len(COLS) + 1))
        for key, label, s in results:
            if key == n:
                print(f"| {label} | " + " | ".join(str(s[c]) for c in COLS) + " |")


if __name__ == "__main__":
    main()
