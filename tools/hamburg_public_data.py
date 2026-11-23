"""Read Hamburg's open street data for a scenario and save it: limits, volumes, zebra crossings.

    python tools/hamburg_public_data.py                    # both scenarios

Three datasets of the Behörde für Verkehr und Mobilitätswende (WFS on geodienste.hamburg.de,
Datenlizenz Deutschland Namensnennung 2.0), read in the network's box:
- the official speed limits per section and direction, with rules by hours;
- the 2019 traffic volumes (DTV) on main roads;
- the zebra crossings.

Writes data/hamburg/<scenario>/public_data.json (the raw answers, gzip + base64, with the
time read) and prints how they match the network: edges whose official limit at the
recorded hour differs from the network's, the volume on the main roads against the
simulated one, the crossings found on edges.
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from drivenow.hamburg import public_data as pd  # noqa: E402
from drivenow.network import load_sumo_net  # noqa: E402
from drivenow.road_events import bbox_of  # noqa: E402
from drivenow.sumo_world import read_routes  # noqa: E402


def get(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": "DriveNow/dev (open data)", "Accept-Encoding": "gzip"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        except urllib.error.HTTPError as e:   # the city's server answers 502 now and then
            if e.code < 500 or i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["willy-brandt", "gaertnerstrasse"], action="append")
    ap.add_argument("--from-dir", default=None,
                    help="answers saved earlier as <scenario>_<limits|volumes|crossings>.xml (read time: the file's)")
    a = ap.parse_args()
    for sc in a.scenario or ["willy-brandt", "gaertnerstrasse"]:
        d = os.path.join(ROOT, "data", "hamburg", sc)
        points = json.load(open(os.path.join(d, "edge_points.json")))
        scen = json.load(open(os.path.join(d, "scenario.json")))
        box = bbox_of(points)
        now = time.time()
        snap = {"scenario": sc, "read_utc": now, "box": box, "sources": {}}
        files = {"speed-limits": "limits", "volumes": "volumes", "crossings": "crossings"}
        for name, mod in pd.SOURCES.items():
            u = mod.url(box)
            if a.from_dir:
                f = os.path.join(a.from_dir, f"{sc}_{files[name]}.xml")
                snap["sources"][name] = {"read_utc": os.path.getmtime(f), "url": u, "data": pd.pack(open(f, "rb").read())}
            else:
                snap["sources"][name] = {"read_utc": now, "url": u, "data": pd.pack(get(u))}
        snap["read_utc"] = min(x["read_utc"] for x in snap["sources"].values())
        json.dump(snap, open(os.path.join(d, "public_data.json"), "w"), indent=1)
        net = load_sumo_net(os.path.join(d, "corridor.net.xml"))
        names = {e.id: e.name for e in net.edges.values()}
        lim = pd.limits(snap, points, names, scen["start"])
        diff = Counter((round(net.edges[e].speed * 3.6), k) for e, k in lim.items() if round(net.edges[e].speed * 3.6) != k)
        print(f"{sc}: official limit at the recorded hour on {len(lim)} of {len(net.edges)} edges; "
              f"differs on {sum(diff.values())}: {dict(diff)}")
        vol = pd.volumes(snap, points, names, scen["main_roads"])
        flow = Counter(e for r in read_routes(os.path.join(d, "routes.rou.xml")).values() for e in r)
        if vol:
            ratio = sorted(v * 0.09 / 2 / max(flow[e], 1) for e, v in vol.items())
            print(f"{sc}: DTV on {len(vol)} main-road edges ({min(vol.values())}-{max(vol.values())}); "
                  f"9% peak hour per direction / simulated: median {ratio[len(ratio) // 2]:.1f}x")
        cr = pd.crossings(snap, net, points)
        print(f"{sc}: {len(pd.rows(snap, 'crossings'))} zebra crossings read, on {len(cr)} edges")


if __name__ == "__main__":
    main()
