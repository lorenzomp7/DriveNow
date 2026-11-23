"""Read now what is in the way on a Hamburg scenario's streets, and save it for the simulation.

    python tools/hamburg_road_events.py                        # both scenarios, open sources
    python tools/hamburg_road_events.py --scenario willy-brandt \
        --mobilithek-subscription 1234567 --cert machine.pem   # also LSBG's DATEX II

Sources, read in the network's box (``road_events.bbox_of``):
- Hamburg police traffic messages (``sources/hamburg_police.py``), open;
- Hamburg's roadworks, "Bauweiser" (``sources/hamburg_roadworks.py``), open;
- with a Mobilithek subscription to LSBG's "Traffic Disturbance Roadworks" (DATEX II v2,
  ``sources/mobilithek.py``): every roadworks site in DATEX II. Needs the machine
  certificate and a direct connection: a proxy that intercepts TLS (as in DriveNow's
  cloud sessions) cannot carry the client certificate.

Writes data/hamburg/<scenario>/road_events.json: each source's raw answer (XML, as
read) with the time it was read, so the simulations can be repeated. HamburgWorld
(``road_events=...``) reads them back with the same parsers and applies them at the
time they were read: a "what if" on the recorded hour, since the lights are those of
14 September 2023 and the road events are today's.
"""
import argparse
import gzip
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from drivenow.road_events import bbox_of, match_all  # noqa: E402
from drivenow.hamburg.road_events import PARSERS, read  # noqa: E402
from drivenow.sources import hamburg_police, hamburg_roadworks, mobilithek  # noqa: E402

HEADERS = {"User-Agent": "DriveNow/dev (road events)", "Accept-Encoding": "gzip"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as r:
        data = r.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["willy-brandt", "gaertnerstrasse"], action="append")
    ap.add_argument("--mobilithek-subscription", default=None)
    ap.add_argument("--cert", default=None, help="Mobilithek machine certificate (PEM, with the key)")
    ap.add_argument("--key", default=None)
    a = ap.parse_args()
    for sc in a.scenario or ["willy-brandt", "gaertnerstrasse"]:
        d = os.path.join(ROOT, "data", "hamburg", sc)
        pts = json.load(open(os.path.join(d, "edge_points.json")))
        box = bbox_of(pts, margin=0.003)
        now = time.time()
        sources = {}
        for name, url in (("hamburg-police", hamburg_police.url(box)), ("hamburg-roadworks", hamburg_roadworks.url(box))):
            try:
                sources[name] = {"read_utc": now, "url": url, "data": get(url).decode("utf-8")}
            except Exception as e:  # one source down does not stop the other
                print(sc, name, "not read:", type(e).__name__, e)
        if a.mobilithek_subscription:
            sub = mobilithek.MobilithekPull(a.mobilithek_subscription, a.cert, a.key)
            status, _, body = sub._https(sub.url(), {"Accept-Encoding": "gzip"})
            if status == 200:
                body = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
                sources["lsbg-datex2"] = {"read_utc": now, "url": sub.url(), "data": body.decode("utf-8")}
            else:
                print(sc, "lsbg-datex2: Mobilithek answered", status)
        snap = {"scenario": sc, "read_utc": now, "box": box, "sources": sources}
        json.dump(snap, open(os.path.join(d, "road_events.json"), "w"), ensure_ascii=False, indent=1)
        for name in sources:
            ev = read(snap, only=name)
            on = match_all(ev, pts)
            print(f"{sc} {name}: {len(ev)} read, {sum(e.active(now) for e in ev)} in force now, "
                  f"{len(on)} on the network: " + "; ".join(f"{e.kind} {e.text[:50]!r}" for e in on if e.active(now)))
        assert set(sources) <= set(PARSERS)


if __name__ == "__main__":
    main()
