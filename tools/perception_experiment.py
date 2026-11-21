"""Self-driving DriveNow cars with different sensors and weather, in the built-in simulation.

    python tools/perception_experiment.py                         # demo town and 3x3 grid, seeds 1-3
    python tools/perception_experiment.py --minutes 10 --nets demo --seeds 1

Every equipped car drives itself (``SimConfig.autopilot``) from what its own
sensors see; all cars are equipped, except in the "people" row. In every case
cars double-park now and then and pedestrians use the zebra crossings (some of
them without looking). Prints the settings and a Markdown table per network:
means over the seeds for the per-trip values (min-max in brackets for the
braking events), totals over the seeds for the safety counts.
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
MEAN = ["stops", "brake_events", "brake_energy_kj", "travel_time", "gap_rmse_m", "missed_pct"]
TOTAL = ["trips", "km", "collisions", "conflicts", "red_runs", "yield_fails", "pedestrian_hits",
         "pedestrian_no_chance", "aeb", "phantom"]


def run(job):
    net_key, label, kw, a, seed = job
    path = NETS[net_key]
    net = demo_city() if path is None else load_sumo_net(path)
    pen = kw.pop("penetration", 1.0)
    cfg = SimConfig(penetration=pen, seed=seed, demand=a.demand, double_parking=a.double_parking,
                    pedestrians=a.pedestrians, careless=a.careless, **kw)
    sim = Simulation(net, cfg)
    sim.run(a.minutes * 60)
    return net_key, label, seed, sim.stats[pen > 0.5].summary(), sim.pedestrians_crossed


def fmt(x, nd=2):
    if x is None:
        return "–"
    return f"{x:.{nd}f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--nets", nargs="+", default=list(NETS))
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--demand", type=float, default=220.0, help="cars per hour per entry road")
    ap.add_argument("--double-parking", type=float, default=30.0, help="cars per hour stopping in the lane")
    ap.add_argument("--pedestrians", type=float, default=60.0, help="people per hour at each crossing")
    ap.add_argument("--careless", type=float, default=0.05, help="share of people who step in without looking")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    a = ap.parse_args()
    cases = [("Persone, senza DriveNow", {"penetration": 0.0}),
             ("Persone con il consiglio DriveNow", {})]
    for weather in ("clear", "night", "rain", "fog"):
        for suite in ("perfect", "camera", "camera+radar", "camera+radar+lidar"):
            cases.append((f"{weather} | {suite}", {"autopilot": True, "sensors": suite, "weather": weather}))
    for weather in ("clear", "fog"):
        for suite in ("camera", "camera+radar"):
            cases.append((f"{weather} | {suite}, senza tempi dei semafori",
                          {"autopilot": True, "sensors": suite, "weather": weather, "light_timing": False}))
    jobs = [(n, label, dict(kw), a, s) for n in a.nets for label, kw in cases for s in a.seeds]
    with Pool(a.jobs) as pool:
        results = pool.map(run, jobs)
    print(f"Settings: seeds {a.seeds}, {a.minutes:g} min each, no warm-up (trips counted from the start), "
          f"demand {a.demand:g} cars/h per entry road, penetration 1 (0 in the first row), "
          f"double parking {a.double_parking:g}/h, pedestrians {a.pedestrians:g}/h per crossing, "
          f"careless {a.careless:g}.")
    for n in a.nets:
        print(f"\n### {n}\n")
        print("| caso | " + " | ".join(MEAN + TOTAL) + " | pedoni passati |")
        print("|" + "---|" * (len(MEAN) + len(TOTAL) + 2))
        for label, _ in cases:
            rows = [(s, p) for key, lab, _, s, p in results if key == n and lab == label]
            cells = []
            for c in MEAN:
                vals = [s[c] for s, _ in rows if s[c] is not None]
                m = sum(vals) / len(vals) if vals else None
                cell = fmt(m, 1 if c in ("brake_energy_kj", "travel_time") else 2)
                if c == "brake_events" and vals:
                    cell += f" ({fmt(min(vals))}–{fmt(max(vals))})"
                cells.append(cell)
            for c in TOTAL:
                tot = sum(s[c] for s, _ in rows)
                cells.append(str(round(tot)) if c != "km" else str(round(tot)))
            cells.append(str(sum(p for _, p in rows)))
            print(f"| {label} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
