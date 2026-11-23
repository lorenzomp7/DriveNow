"""Set the simulated main-road speeds beside Hamburg's real traffic state (Verkehrslage).

    python tools/hamburg_verkehrslage_check.py --read            # read now, save per scenario
    python tools/hamburg_verkehrslage_check.py --compare FILE     # FILE: the simulations' summary

The Verkehrslage (geodienste.hamburg.de, ``sources/hamburg_traffic.py``) gives, every 5
minutes, a class per stretch: fliessend, dicht, zäh, stockend. It exists live only, so the
reading is of today, not of the recorded hour (14 September 2023, 17:00): read it on a
weekday near 17:00 Hamburg time for a fair comparison; the time read is saved and shown.

--read saves data/hamburg/<scenario>/verkehrslage.json (the raw answer, gzip + base64, and
the Hamburg local time). --compare classes each main-road edge twice: by the reading
(matched as in ``hamburg_traffic.apply``) and by the simulation (its mean speed after the
warm-up over its limit, put in the class whose share in ``hamburg_traffic.SPEED_SHARE`` is
nearest; those shares are assumptions), and counts how often they agree, per condition.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from drivenow.fleet import FleetDB  # noqa: E402
from drivenow.hamburg.public_data import pack, unpack  # noqa: E402
from drivenow.road_events import bbox_of  # noqa: E402
from drivenow.sources import hamburg_traffic  # noqa: E402

CLASSES = ["fliessend", "dicht", "zäh", "stockend"]


def klass(share: float) -> str:
    return min(CLASSES, key=lambda c: abs(hamburg_traffic.SPEED_SHARE[c] - share))


def observed(sc):
    d = os.path.join(ROOT, "data", "hamburg", sc)
    snap = json.load(open(os.path.join(d, "verkehrslage.json")))
    points = json.load(open(os.path.join(d, "edge_points.json")))
    rows = hamburg_traffic.parse(unpack(snap["data"]))
    db = FleetDB({e: p[3] for e, p in points.items()})
    hamburg_traffic.apply(rows, points, db, {e: 1.0 for e in points})   # free speed 1: speed = share
    return {e: klass(s.speed) for e, s in db.segments.items()}, snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--compare", default=None)
    a = ap.parse_args()
    if a.read:
        for sc in ("willy-brandt", "gaertnerstrasse"):
            d = os.path.join(ROOT, "data", "hamburg", sc)
            points = json.load(open(os.path.join(d, "edge_points.json")))
            u = hamburg_traffic.url(bbox_of(points))
            data = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "DriveNow/dev"}), timeout=120).read()
            now = time.time()
            try:
                from zoneinfo import ZoneInfo
                local = dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Berlin")).strftime("%a %Y-%m-%d %H:%M")
            except Exception:
                local = None
            json.dump({"read_utc": now, "hamburg_time": local, "url": u, "data": pack(data)},
                      open(os.path.join(d, "verkehrslage.json"), "w"))
            print(sc, "read at", local, "-", len(hamburg_traffic.parse(data)), "stretches")
    if a.compare:
        summary = json.load(open(a.compare))
        out = {}
        for sc in ("willy-brandt", "gaertnerstrasse"):
            try:
                obs, snap = observed(sc)
            except FileNotFoundError:
                continue
            print(f"\n{sc}: traffic state read {snap['hamburg_time']} (Hamburg time); "
                  f"observed on main-road edges: {dict(Counter(obs.values()))}")
            for cond, row in summary.get(sc, {}).items():
                sim = {e: klass(s) for e, s in row.get("main_edge_speed_share", {}).items()}
                both = [e for e in sim if e in obs]
                if not both:
                    continue
                agree = sum(sim[e] == obs[e] for e in both)
                slower = sum(CLASSES.index(sim[e]) > CLASSES.index(obs[e]) for e in both)
                out.setdefault(sc, {})[cond] = {"edges": len(both), "agree": agree, "sim_slower": slower,
                                                "sim_faster": len(both) - agree - slower,
                                                "sim_classes": dict(Counter(sim[e] for e in both))}
                print(f"  {cond:<44} edges {len(both):>4}  same class {agree / len(both):.0%}  "
                      f"simulated slower {slower / len(both):.0%}  faster {(len(both) - agree - slower) / len(both):.0%}")
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
