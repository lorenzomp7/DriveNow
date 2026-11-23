"""Read the public traffic sources live and see what lands on DriveNow's networks.

    python tools/public_data_check.py [--out result.json]

For every adapter with an open source (no key): fetch it now, parse it, and report
how many records came, how many were read (with coordinates, active now) and,
for the Hamburg sources, how many fall on the Willy-Brandt-Straße and
Gärtnerstraße networks (edges matched from data/hamburg/*/edge_points.json).
A source that cannot be reached is reported as such; nothing is made up.
"""
import argparse, gzip, json, os, sys, time, urllib.request
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from drivenow.fleet import FleetDB
from drivenow.road_events import bbox_of, match_all
from drivenow.sources import autobahn, datex2, digitraffic, hamburg_police, hamburg_traffic, torino, wzdx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADERS = {"User-Agent": "DriveNow/dev (open data check)", "Accept-Encoding": "gzip"}

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=None)
a = ap.parse_args()


def get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


nets = {}
for sc in ("willy-brandt", "gaertnerstrasse"):
    pts = json.load(open(os.path.join(ROOT, "data", "hamburg", sc, "edge_points.json")))
    nets[sc] = pts
now = time.time()
report = {"checked_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "sources": {}}


def run(name, fn):
    t0 = time.time()
    try:
        res = fn()
        res["seconds"] = round(time.time() - t0, 1)
    except Exception as e:  # report and go on: one source down does not stop the others
        res = {"error": f"{type(e).__name__}: {e}"[:200]}
    report["sources"][name] = res
    print(name, json.dumps(res, ensure_ascii=False), flush=True)


def on_networks(events):
    out = {}
    for sc, pts in nets.items():
        m = match_all([e for e in events if e.active(now)], pts)
        out[sc] = dict(Counter(e.kind for e in m))
    return out


def hamburg_police_check():
    ev = hamburg_police.parse(get(hamburg_police.url()))
    return {"messages": len(ev), "active_now": sum(e.active(now) for e in ev),
            "kinds": dict(Counter(e.kind for e in ev)), "on_networks": on_networks(ev)}


def hamburg_traffic_check():
    out = {}
    for sc, pts in nets.items():
        rows = hamburg_traffic.parse(get(hamburg_traffic.url(bbox_of(pts))))
        db = FleetDB({e: p[3] for e, p in pts.items()})
        n = hamburg_traffic.apply(rows, pts, db, {e: 50 / 3.6 for e in pts})
        ages = [now - r["time"] for r in rows if r["time"]]
        out[sc] = {"stretches": len(rows), "states": dict(Counter(r["state"] for r in rows)),
                   "edges_with_a_speed": len(db.segments), "of_edges": len(pts),
                   "age_min": round(min(ages) / 60, 1) if ages else None}
    return out


def autobahn_check():
    # The motorways around Hamburg; the two networks are inner-city streets.
    ev = []
    for road in ("A1", "A7", "A23", "A24", "A25", "A255"):
        ev += autobahn.fetch_road(road, lambda u: json.loads(get(u)))
    return {"events": len(ev), "kinds": dict(Counter(e.kind for e in ev)),
            "with_speed_limit": sum(1 for e in ev if e.speed_limit), "on_networks": on_networks(ev)}


def ndw_check():
    base = "https://opendata.ndw.nu/"
    out = {}
    for f in ("actueel_beeld.xml.gz", "tijdelijke_verkeersmaatregelen_maximum_snelheden.xml.gz",
              "tijdelijke_verkeersmaatregelen_afsluitingen.xml.gz", "planningsfeed_brugopeningen.xml.gz",
              "veiligheidsgerelateerde_informatie_srti.xml.gz"):
        ev, st = datex2.parse_situations(get(base + f), "ndw")
        out[f.split(".")[0]] = {**st, "kinds": dict(Counter(e.kind for e in ev)),
                                "active_now": sum(e.active(now) for e in ev)}
    rows = datex2.parse_measured(get(base + "trafficspeed.xml.gz"))
    tt = datex2.parse_measured(get(base + "traveltime.xml.gz"))
    out["trafficspeed"] = {"sites": len(rows), "with_speed": sum(1 for r in rows if r["speed"])}
    out["traveltime"] = {"sections": len(tt), "with_travel_time": sum(1 for r in tt if r["travel_time"])}
    return out


def belgium_check():
    ev, st = datex2.parse_situations(get("https://www.verkeerscentrum.be/uitwisseling/datex2full"), "be")
    return {**st, "kinds": dict(Counter(e.kind for e in ev))}


def finland_check():
    out = {}
    for t in ("ROAD_WORK", "TRAFFIC_ANNOUNCEMENT", "WEIGHT_RESTRICTION"):
        ev = digitraffic.parse(json.loads(get(f"{digitraffic.URL}?inactiveHours=0&includeAreaGeometry=false&situationType={t}",
                                              {"Digitraffic-User": "DriveNow"})))
        out[t] = {"events": len(ev), "kinds": dict(Counter(e.kind for e in ev)),
                  "with_speed_limit": sum(1 for e in ev if e.speed_limit)}
    return out


def torino_check():
    rows = torino.parse(get(torino.URL))
    return {"points": len(rows), "with_traffic": sum(1 for r in rows if r["flow"] > 0),
            "mean_speed_kmh": round(sum(r["speed"] for r in rows if r["speed"] > 0) /
                                    max(1, sum(1 for r in rows if r["speed"] > 0)), 1)}


def wzdx_check():
    # Every active feed of the registry that needs no key, read now.
    reg = wzdx.parse_registry(json.loads(get(wzdx.REGISTRY)))
    feeds, failed, ev = {}, {}, []
    for r in reg:
        if not r["url"] or r["needs_key"] or not r["active"]:
            continue
        try:
            got = wzdx.parse(json.loads(get(r["url"], timeout=30)), "wzdx:" + r["name"])
        except Exception as e:  # one feed down does not stop the others
            failed[r["name"]] = type(e).__name__
            continue
        feeds[r["name"]] = len(got)
        ev += got
    return {"feeds_in_registry": len(reg), "open_active": len(feeds) + len(failed), "read": len(feeds),
            "failed": failed, "events": len(ev), "kinds": dict(Counter(e.kind for e in ev)),
            "active_now": sum(e.active(now) for e in ev), "with_speed_limit": sum(1 for e in ev if e.speed_limit),
            "per_feed": feeds}


def porto_check():
    url = ("https://dadosabertos.cm-porto.pt/dataset/539db002-9e19-11f1-84ed-6abdb6d5cf34/resource/"
           "75a3447c-bf9d-4c02-b3b7-aaecf5f00d2c/download/condicionamentos_nao_programados.xml")
    ev, st = datex2.parse_situations(get(url), "porto")
    return {**st, "kinds": dict(Counter(e.kind for e in ev)), "active_now": sum(e.active(now) for e in ev)}


for name, fn in (("hamburg_police", hamburg_police_check), ("hamburg_traffic", hamburg_traffic_check),
                 ("autobahn", autobahn_check), ("ndw_netherlands", ndw_check), ("belgium", belgium_check),
                 ("finland", finland_check), ("turin", torino_check), ("porto", porto_check),
                 ("wzdx_usa", wzdx_check)):
    run(name, fn)
if a.out:
    json.dump(report, open(a.out, "w"), ensure_ascii=False, indent=1)
