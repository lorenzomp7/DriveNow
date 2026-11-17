"""Record a few minutes of the simulation into a self-contained page.

    python tools/record_replay.py OUT_DIR [--minutes 4] [--penetration 0.5]

OUT_DIR gets ``index.html`` (the map, with CSS and JS inlined) and
``replay.json`` (network, frames and speed map). Any static host can serve
the two files: the page plays the recording in a loop, no Python needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivenow.network import demo_city  # noqa: E402
from drivenow.simulation import SimConfig, Simulation, static_network  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE_EXTRA_CSS = """
.app { height: 100%; display: flex; flex-direction: column; }
.app .layout { flex: 1; }
.top, .panel { padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.replay-note { margin: 0 0 10px; }
"""


def record(minutes: float, penetration: float, warmup: float, seed: int, every: int = 1,
           hamburg: bool = False) -> dict:
    if hamburg:
        from drivenow.hamburg.world import HamburgWorld

        sim = HamburgWorld(penetration=penetration, seed=seed, label="replay")
        dt = sim.dt
        place = ("del corridoio di Willy-Brandt-Straße ad Amburgo, con i semafori reali registrati il "
                 "14 settembre 2023 dalle 17:00 e la mappa di OpenStreetMap")
    else:
        sim = Simulation(demo_city(), SimConfig(penetration=penetration, seed=seed))
        dt = sim.cfg.dt
        place = "della città demo"
    for _ in range(int(warmup / dt)):
        sim.step()
    frames, fields = [], []
    n = int(minutes * 60 / (dt * every))
    per_field = max(1, int(1.0 / (dt * every)))
    for i in range(n):
        for _ in range(every):
            sim.step()
        snap = sim.snapshot()
        snap["penetration"] = penetration
        snap["demand"] = None
        frames.append(snap)
        if i % per_field == 0:
            fields.append([i, sim.advisor.speed_field(sim.t, sim.occupancy())])
    if hamburg:
        sim.close()
    note = (f"Registrazione di {minutes:g} minuti {place}, con il {penetration:.0%} di auto DriveNow, "
            "riprodotta in ciclo. Per la simulazione dal vivo, con i comandi, avvia python -m drivenow.server.")
    return {"network": static_network(sim.net), "frames": frames, "fields": fields,
            "dt": dt * every, "note": note}


def build_page() -> str:
    html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    css = open(os.path.join(ROOT, "web", "style.css"), encoding="utf-8").read()
    js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    body = body.replace('<script src="app.js"></script>', "")
    return (
        "<meta charset=\"utf-8\">\n"
        "<title>DriveNow</title>\n"
        '<meta name="claude:viewport-fit-sides" content="cover">\n'
        f"<style>\n{css}\n{PAGE_EXTRA_CSS}</style>\n"
        f'<div class="app" data-replay="replay.json">{body}</div>\n'
        f"<script>\n{js}</script>\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--minutes", type=float, default=4)
    ap.add_argument("--penetration", type=float, default=0.5)
    ap.add_argument("--warmup", type=float, default=900)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--hamburg", action="store_true", help="record the real Hamburg corridor (needs SUMO)")
    ap.add_argument("--every", type=int, default=2, help="simulation steps (0.2 s) between saved frames")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    data = record(args.minutes, args.penetration, args.warmup, args.seed, every=args.every, hamburg=args.hamburg)
    with open(os.path.join(args.out, "replay.json"), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_page())
    print("frames", len(data["frames"]), "size MB", round(os.path.getsize(os.path.join(args.out, "replay.json")) / 1e6, 2))


if __name__ == "__main__":
    main()
