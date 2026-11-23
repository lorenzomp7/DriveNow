"""Build a SUMO scenario around a real US work zone, from its WZDx feed and OpenStreetMap.

    python tools/wzdx_build.py --pick 2 --cache /tmp/wzdx          # the two best work zones now
    python tools/wzdx_build.py --feed indot --event 1234 --cache /tmp/wzdx

Steps:

1. The open WZDx feeds of USDOT's registry (data/wzdx_registry.json) are read
   now. Candidates are work zones in force for the next hour, with a reduced
   speed limit or closed lanes, 300 to 2,000 m long. Detours are left out:
   they are the open diversion routes.
2. For up to 15 candidates (taken from the feeds in turn) the OpenStreetMap
   map around the zone (its box plus 400 m) is downloaded and the traffic
   lights (highway=traffic_signals) within 150 m of the zone are counted. The
   zone with the most lights wins (at least 2); with ``--pick 2`` the second
   comes from another feed.
3. The map becomes a SUMO network with the same netconvert options as the
   Hamburg scenarios. The lights are OpenStreetMap's, with the fixed-time
   programme SUMO guesses: there are no open signal timings for these roads.
4. Traffic: SUMO's randomTrips at an assumed volume (``--veh-per-hour``,
   written in scenario.json), since these roads have no open counts.
5. Saved in data/wzdx/<name>/: corridor.net.xml, routes.rou.xml,
   edge_points.json, events.json (the feed's raw features in the area, as
   read: a recording, so runs can be repeated) and scenario.json.

Needs SUMO and network access to the feeds' hosts and api.openstreetmap.org.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from drivenow.road_events import match_all  # noqa: E402
from drivenow.sources import wzdx  # noqa: E402
from edge_points import edge_points  # noqa: E402
from hamburg_build import KEEP_TYPES, OSM, sumo_home  # noqa: E402

DATA = os.path.join(ROOT, "data", "wzdx")
HEADERS = {"User-Agent": "DriveNow/dev (work zone scenario)", "Accept-Encoding": "gzip"}


def log(*a):
    print("[wzdx]", *a, flush=True)


def run(cmd):
    import subprocess
    log(" ".join(os.path.basename(c) for c in cmd[:3]), "...")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        data = r.read()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def metres(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((b[0] - a[0]) * 111320 * math.cos(lat), (b[1] - a[1]) * 110540)


def length(line):
    return sum(metres(a, b) for a, b in zip(line, line[1:]))


def to_line(p, line):
    """Metres from point p to a lon/lat polyline."""
    lat0 = math.radians(p[1])
    xy = lambda q: ((q[0] - p[0]) * 111320 * math.cos(lat0), (q[1] - p[1]) * 110540)
    best = float("inf")
    for a, b in zip(line, line[1:]):
        (ax, ay), (bx, by) = xy(a), xy(b)
        dx, dy = bx - ax, by - ay
        u = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
        best = min(best, math.hypot(ax + u * dx, ay + u * dy))
    return best


def box(line, margin):
    lat = sum(p[1] for p in line) / len(line)
    dlon, dlat = margin / (111320 * math.cos(math.radians(lat))), margin / 110540
    return (min(p[0] for p in line) - dlon, min(p[1] for p in line) - dlat,
            max(p[0] for p in line) + dlon, max(p[1] for p in line) + dlat)


def candidates(feeds, now, max_limit=None):
    """(feed, event, feature) of every usable work zone, feed by feed."""
    out = {}
    for r in feeds:
        try:
            raw = json.loads(get(r["url"], 40))
            events = wzdx.parse(raw, "wzdx:" + r["name"])
        except Exception as e:  # one feed down does not stop the others
            log("feed", r["name"], "not read:", type(e).__name__)
            continue
        feats = {f"wzdx:{r['name']}:{f.get('id') or (f.get('properties', {}).get('core_details') or {}).get('road_event_id')}": f
                 for f in raw.get("features", [])}
        good = [ev for ev in events
                if ev.kind != "other" and ev.active(now) and (ev.end is None or ev.end >= now + 3600)
                and (ev.speed_limit or ev.lanes_closed) and len(ev.line) >= 2 and 300 <= length(ev.line) <= 2000
                and (max_limit is None or (ev.speed_limit and ev.speed_limit * 3.6 <= max_limit))]
        good.sort(key=lambda ev: (ev.speed_limit is None, -(ev.lanes_closed or 0)))
        out[r["name"]] = (r, raw, [(ev, feats.get(ev.id)) for ev in good])
        log("feed", r["name"], len(events), "events,", len(good), "usable work zones")
    return out


def osm_signals(bbox, line, cache):
    path = os.path.join(cache, "osm_%.5f_%.5f_%.5f_%.5f.xml" % bbox)
    if not os.path.exists(path):
        open(path, "wb").write(get(OSM.format(",".join("%.6f" % v for v in bbox)), 120))
        time.sleep(1.0)  # gentle with the OpenStreetMap API
    n = 0
    for node in ET.parse(path).getroot().iter("node"):
        if any(t.get("k") == "highway" and t.get("v") == "traffic_signals" for t in node.iter("tag")):
            if to_line((float(node.get("lon")), float(node.get("lat"))), line) <= 150:
                n += 1
    return n, path


def build(name, feed, raw, ev, osm, bbox, signals, a, now):
    out = os.path.join(DATA, name)
    os.makedirs(out, exist_ok=True)
    net = os.path.join(out, "corridor.net.xml")
    run(["netconvert", "--osm-files", osm, "-o", net, "--keep-edges.by-type", KEEP_TYPES,
         "--keep-edges.by-vclass", "passenger", "--remove-edges.isolated", "--geometry.remove",
         "--ramps.guess", "--junctions.join", "--tls.guess-signals", "--tls.discard-simple", "--tls.join",
         "--tls.default-type", "static", "--output.street-names", "--osm.turn-lanes", "--no-turnarounds",
         "--proj.utm", "--no-warnings"])
    pts = edge_points(net)
    # The lights that are left in SUMO's network near the zone (netconvert drops or joins
    # some of OpenStreetMap's, e.g. on motorway ramps).
    root = ET.parse(net).getroot()
    tls = {j.get("id") for j in root.iter("junction") if j.get("type", "").startswith("traffic_light")}
    near = {n for e in root.iter("edge") if e.get("id") in pts and to_line(pts[e.get("id")][:2], ev.line) <= 150
            for n in (e.get("from"), e.get("to")) if n in tls}
    log(len(tls), "lights in the network,", len(near), "near the zone")
    if len(near) < a.min_lights:
        import shutil
        shutil.rmtree(out)
        log("too few lights near the zone: skipped")
        return False
    json.dump(pts, open(os.path.join(out, "edge_points.json"), "w"))
    # The feed's features in the area, as read.
    inside = lambda f: any(bbox[0] <= p[0] <= bbox[2] and bbox[1] <= p[1] <= bbox[3]
                           for p in wzdx._line(f.get("geometry")))
    feats = [f for f in raw.get("features", []) if inside(f)]
    json.dump({"feed": feed["name"], "organization": feed["organization"], "url": feed["url"],
               "read_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
               "feed_info": raw.get("feed_info"), "features": feats},
              open(os.path.join(out, "events.json"), "w"), indent=1)
    events = match_all(wzdx.parse({"features": feats}, "wzdx:" + feed["name"]), pts)
    on = [e for e in events if e.active(now)]
    main = next((e for e in events if e.id == ev.id), None)
    log(len(feats), "features in the area,", len(events), "on the network,", len(on), "in force;",
        "the chosen zone on", len(main.edges) if main else 0, "edges")
    tools = os.path.join(sumo_home(), "tools")
    routes = os.path.join(out, "routes.rou.xml")
    trips = os.path.join(a.cache, name + ".trips.xml")
    run([sys.executable, os.path.join(tools, "randomTrips.py"), "-n", net, "-o", trips, "-r", routes,
         "-e", "3600", "-p", "%.3f" % (3600.0 / a.veh_per_hour), "--fringe-factor", "10",
         "--min-distance", "300", "--seed", "7", "--validate"])
    s = open(routes).read()   # the same drivers as in the Hamburg scenarios
    s = re.sub(r"(<routes[^>]*>)", r'\1\n    <vType id="DEFAULT_VEHTYPE" length="4.5" minGap="2.5" accel="1.4" '
               r'decel="4.5" sigma="0.2" speedFactor="1" speedDev="0.05"/>', s, count=1)
    open(routes, "w").write(s)
    for f in os.listdir(out):
        if f.endswith(".alt.xml"):
            os.remove(os.path.join(out, f))
    core = ev.text or "work zone"
    json.dump({"scenario": name, "title": f"{feed['organization']} · {core[:60]}", "feed": feed["name"],
               "organization": feed["organization"], "state": feed.get("state"), "event_id": ev.id,
               "event": {"kind": ev.kind, "road": core, "speed_limit_kmh": round(ev.speed_limit * 3.6, 1) if ev.speed_limit else None,
                         "lanes_closed": ev.lanes_closed, "closed_lanes": ev.closed_lanes, "lane_count": ev.lane_count,
                         "length_m": round(length(ev.line)), "start": ev.start, "end": ev.end},
               "clock0": now, "read_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
               "bbox": [round(v, 6) for v in bbox], "osm_signals_near_zone": signals,
               "sumo_lights": len(tls), "sumo_lights_near_zone": len(near),
               "events_on_network": len(events), "events_in_force": len(on),
               "veh_per_hour": a.veh_per_hour, "veh_per_hour_is": "assumed: no open counts for these roads",
               "lights": "OpenStreetMap's, with SUMO's guessed fixed-time programme (no open timings)",
               "sources": {"work_zones": f"WZDx feed '{feed['name']}' of {feed['organization']}, listed in USDOT's "
                                         "Work Zone Data Feed Registry", "map": "© OpenStreetMap contributors, ODbL"}},
              open(os.path.join(out, "scenario.json"), "w"), indent=1, ensure_ascii=False)
    log("done:", out)
    return main is not None and bool(main.edges)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", required=True, help="folder for downloads")
    ap.add_argument("--pick", type=int, default=None, help="build this many scenarios from the best work zones now")
    ap.add_argument("--feed", default=None, help="feed names in the registry, comma-separated")
    ap.add_argument("--event", default=None, help="the work zone's id in that feed (default: the best one)")
    ap.add_argument("--veh-per-hour", type=float, default=900.0, help="assumed vehicles entering per hour")
    ap.add_argument("--tries", type=int, default=15, help="work zones whose map is downloaded and checked")
    ap.add_argument("--max-limit-kmh", type=float, default=None,
                    help="only work zones with a reduced limit at most this (e.g. 72 for city streets)")
    ap.add_argument("--min-lights", type=int, default=3, help="lights SUMO's network must have near the zone")
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    sumo_home()
    reg = wzdx.parse_registry(json.load(open(os.path.join(ROOT, "data", "wzdx_registry.json"))))
    names = a.feed.split(",") if a.feed else None
    feeds = [r for r in reg if r["url"] and r["active"] and not r["needs_key"] and (names is None or r["name"] in names)]
    now = float(int(time.time()))
    cands = candidates(feeds, now, a.max_limit_kmh)
    if a.event:
        cands = {k: (r, raw, [c for c in lst if c[0].id.endswith(":" + a.event)]) for k, (r, raw, lst) in cands.items()}
    # Feeds in turn, so the tries are not all spent on one state.
    queue, i = [], 0
    while len(queue) < a.tries and any(i < len(v[2]) for v in cands.values()):
        for name, (r, raw, lst) in cands.items():
            if i < len(lst) and len(queue) < a.tries:
                queue.append((r, raw) + lst[i])
        i += 1
    scored = []
    for r, raw, ev, feat in queue:
        bbox = box(ev.line, 400)
        try:
            n, osm = osm_signals(bbox, ev.line, a.cache)
        except Exception as e:
            log("map not read for", ev.id, type(e).__name__)
            continue
        log(ev.id, ev.text[:40], "lights near the zone:", n)
        scored.append((n, r, raw, ev, osm, bbox))
    scored.sort(key=lambda s: -s[0])
    want, used = a.pick or 1, set()
    built = 0
    for n, r, raw, ev, osm, bbox in scored:
        if n < 2 or r["name"] in used:
            continue
        name = re.sub(r"[^a-z0-9]+", "-", f"{r['name']}-{ev.text[:30]}".lower()).strip("-")
        if build(name, r, raw, ev, osm, bbox, n, a, now):
            used.add(r["name"])
            built += 1
        if built >= want:
            break
    log(built, "scenario(s) built")


if __name__ == "__main__":
    main()
