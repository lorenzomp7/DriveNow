"""Build a Hamburg scenario in data/hamburg/<scenario>/ from the original sources.

    python tools/hamburg_build.py --scenario gaertnerstrasse --cache /tmp/hh

Scenarios:
  willy-brandt     Willy-Brandt-Strasse / Ludwig-Erhard-Strasse, 1.9 km, 9 lights.
                   Only 9 of the 35 lights in the simulated area have data.
  gaertnerstrasse  Osterstrasse / Gaertnerstrasse / Breitenfelder Strasse
                   (Eimsbuettel / Hoheluft), 1.7 km, 10 lights.
                   Every light OpenStreetMap shows along the road is in
                   Hamburg's feed, and the network is cut to a band around
                   the road, so every simulated light is a real one.

Steps (each one is skipped when its output is already in the cache):

1. Lane connections of the corridor's traffic lights, with geometry and
   datastream ids, from Hamburg's SensorThings API (tld.iot.hamburg.de).
2. The street map of the corridor from the OpenStreetMap API, converted to a
   SUMO network. Traffic lights are placed where Hamburg's lane connections
   are, and removed where Hamburg has none.
3. Every SUMO signal link is matched to a Hamburg lane connection by
   geometry (stop line, exit point and directions).
4. The TU Dresden recording is streamed over HTTP (a 34 GB zip holding one
   164 GB CSV) and only the rows of this corridor are kept, for the chosen
   time window plus the lookback the forecast needs.
5. Traffic: candidate routes from SUMO's randomTrips, sampled with SUMO's
   routeSampler to match the vehicle counts of Hamburg's detectors in that
   hour, plus an assumed volume on the main road, which has no detectors.

Lights that OpenStreetMap has but Hamburg's feed does not cover keep SUMO's
guessed fixed-time programme.

Needs SUMO (pip install eclipse-sumo traci sumolib pyproj) and network access
to tld.iot.hamburg.de, api.openstreetmap.org and opara.zih.tu-dresden.de.
"""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import json
import math
import os
import re
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "hamburg")

STA = "https://tld.iot.hamburg.de/v1.1/"
OSM = "https://api.openstreetmap.org/api/0.6/map?bbox={}"
DATASET = "https://opara.zih.tu-dresden.de/server/api/core/bitstreams/686a91e8-d2d3-42af-843a-4ebb83787ba4/content"

SCENARIOS = {
    "willy-brandt": {
        "title": "Amburgo · Willy-Brandt-Straße",
        "lights": ["305", "2438", "467", "79", "78", "96", "50", "246", "310"],
        "bbox": "9.9815,53.5455,10.0165,53.5545",
        "band": None,             # keep the whole bounding box
        "main_roads": ("Willy-Brandt-Straße", "Ludwig-Erhard-Straße"),
        "main_min_lanes": 2,
    },
    "gaertnerstrasse": {
        "title": "Amburgo · Gärtnerstraße",
        # In order along the road: Osterstrasse, Gaertnerstrasse, Breitenfelder Strasse.
        # 682 sits next to 683 at the north-east end.
        "lights": ["87", "1334", "1315", "504", "1046", "910", "168", "684", "683", "682"],
        "bbox": None,             # map tiles along the road instead
        "band": 80,               # keep streets within 80 m of the road
        "main_roads": ("Osterstraße", "Gärtnerstraße", "Breitenfelder Straße"),
        "main_min_lanes": 1,
        "main_volume": 200,       # single-lane streets: about half the Willy-Brandt-Strasse figure
    },
}
KEEP_TYPES = ",".join("highway." + t for t in (
    "motorway trunk trunk_link primary primary_link secondary secondary_link tertiary tertiary_link "
    "residential unclassified").split())


def log(*a):
    print("[hamburg]", *a, flush=True)


def sumo_home() -> str:
    if "SUMO_HOME" not in os.environ:
        import sumo
        os.environ["SUMO_HOME"] = sumo.SUMO_HOME
    return os.environ["SUMO_HOME"]


def run(cmd):
    log(" ".join(cmd[:3]), "...")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


# ------------------------------------------------------------------ 1. lanes
def fetch_things(lights, path):
    if os.path.exists(path):
        return json.load(open(path))
    things = []
    for tl in lights:
        q = urllib.parse.urlencode({
            "$filter": f"properties/trafficLightsID eq '{tl}'",
            "$expand": "Locations,Datastreams($select=@iot.id,name,properties)", "$top": "500"})
        url = STA + "Things?" + q
        while url:
            d = json.load(urllib.request.urlopen(url, timeout=60))
            things += d["value"]
            url = d.get("@iot.nextLink")
    slim = [{"name": t["name"], "properties": t["properties"],
             "geometry": t["Locations"][0]["location"]["geometry"] if t["Locations"] else None,
             "datastreams": {d["properties"].get("layerName"): d["@iot.id"] for d in t["Datastreams"]}}
            for t in things]
    json.dump(slim, open(path, "w"))
    log(len(slim), "lane connections")
    return slim


def car_lanes(things):
    return [t for t in things if "KFZ" in t["properties"].get("laneType", "") and t["geometry"]
            and len(t["geometry"]["coordinates"]) >= 2 and "primary_signal" in t["datastreams"]]


def orient(ing, egr):
    """Ingress ending at the stop line, egress starting at the junction."""
    best = None
    for a in (ing, ing[::-1]):
        for b in (egr, egr[::-1]):
            d = math.dist(a[-1], b[0])
            if best is None or d < best[0]:
                best = (d, a, b)
    return best[1], best[2]


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def heading(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def angdiff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


# ------------------------------------------------------------------ 2. network
M_LON, M_LAT = 66000.0, 111320.0  # metres per degree around 53.5 N


def light_centres(things, lights):
    """Average stop-line position of each light's car lanes, in lon/lat."""
    pts = collections.defaultdict(list)
    for t in car_lanes(things):
        g = t["geometry"]["coordinates"]
        ing, egr = orient(g[0], g[1])
        pts[t["properties"]["trafficLightsID"]].append(ing[-1])
    return [(sum(p[0] for p in pts[k]) / len(pts[k]), sum(p[1] for p in pts[k]) / len(pts[k]))
            for k in lights if pts.get(k)]


def osm_tiles(centres, cache, half=300, step=450):
    """Download 600 m map tiles along the road (the OSM API limits one request's size)."""
    xy = [((lo - 10) * M_LON, (la - 53.55) * M_LAT) for lo, la in centres]
    pts = []
    for a, b in zip(xy, xy[1:]):
        n = max(1, int(math.dist(a, b) // step))
        pts += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]
    chosen = []
    for p in pts:
        if all(math.dist(p, q) > 300 for q in chosen):
            chosen.append(p)
    files = []
    for x, y in chosen:
        bbox = "{:.5f},{:.5f},{:.5f},{:.5f}".format((x - half) / M_LON + 10, (y - half) / M_LAT + 53.55,
                                                    (x + half) / M_LON + 10, (y + half) / M_LAT + 53.55)
        path = os.path.join(cache, "tile_" + bbox.replace(",", "_") + ".osm")
        if not os.path.exists(path):
            log("downloading OpenStreetMap tile", bbox)
            urllib.request.urlretrieve(OSM.format(bbox), path)
        files.append(path)
    return files


def build_network(sc, things, cache, net_out):
    if os.path.exists(net_out):
        return
    import sumolib

    centres = light_centres(things, sc["lights"])
    if sc["bbox"]:
        osm = os.path.join(cache, "corridor.osm")
        if not os.path.exists(osm):
            log("downloading OpenStreetMap", sc["bbox"])
            urllib.request.urlretrieve(OSM.format(sc["bbox"]), osm)
        osm_files = [osm]
    else:
        osm_files = osm_tiles(centres, cache)
    raw = os.path.join(cache, "raw.net.xml")
    run(["netconvert", "--osm-files", ",".join(osm_files), "-o", raw, "--keep-edges.by-type", KEEP_TYPES,
         "--keep-edges.by-vclass", "passenger", "--remove-edges.isolated", "--geometry.remove",
         "--ramps.guess", "--junctions.join", "--tls.guess-signals", "--tls.discard-simple", "--tls.join",
         "--tls.default-type", "static", "--output.street-names", "--osm.turn-lanes", "--no-turnarounds",
         "--proj.utm", "--no-warnings"])
    net = sumolib.net.readNet(raw)
    P = lambda p: net.convertLonLat2XY(*p)
    nodes = [n for n in net.getNodes() if n.getType() != "dead_end" and n.getIncoming() and n.getOutgoing()]
    signalised = set()
    for t in car_lanes(things):
        g = t["geometry"]["coordinates"]
        ing, egr = orient([P(p) for p in g[0]], [P(p) for p in g[1]])
        mid = ((ing[-1][0] + egr[0][0]) / 2, (ing[-1][1] + egr[0][1]) / 2)
        n = min(nodes, key=lambda n: math.dist(n.getCoord(), mid))
        if math.dist(n.getCoord(), mid) < 50:
            signalised.add(n.getID())
    log(len(signalised), "junctions get Hamburg's lights")
    prefix = os.path.join(cache, "plain")
    trim = []
    if sc["band"]:
        # Keep only streets near the road, so no light without data ends up in the network.
        road = [P(c) for c in centres]
        keep = [e.getID() for e in net.getEdges()
                if any(min(seg_dist(p, a, b) for a, b in zip(road, road[1:])) < sc["band"] for p in e.getShape())]
        keep_file = os.path.join(cache, "keep_edges.txt")
        open(keep_file, "w").write("\n".join(keep) + "\n")
        trim = ["--keep-edges.input-file", keep_file, "--remove-edges.isolated"]
        log(len(keep), "of", len(net.getEdges()), "streets kept within", sc["band"], "m of the road")
    run(["netconvert", "--sumo-net-file", raw, "--plain-output-prefix", prefix, "--no-warnings"] + trim)
    tree = ET.parse(prefix + ".nod.xml")
    for n in tree.getroot().iter("node"):
        if n.get("id") in signalised:
            n.set("type", "traffic_light")
            n.set("tlType", "static")
            for k in ("tl", "controlledInner"):
                n.attrib.pop(k, None)
        # Other lights from OpenStreetMap stay: Hamburg's feed does not cover them, so they keep
        # SUMO's guessed fixed-time programme (removing them jams the side streets).
    tree.write(prefix + ".nod.xml")
    run(["netconvert", "--node-files", prefix + ".nod.xml", "--edge-files", prefix + ".edg.xml",
         "--connection-files", prefix + ".con.xml", "--type-files", prefix + ".typ.xml", "-o", net_out,
         "--tls.join", "--tls.join-dist", "40", "--tls.default-type", "static", "--no-turnarounds",
         "--no-warnings"])


# ------------------------------------------------------------------ 3. matching
def match_links(things, net_path, out):
    if os.path.exists(out):
        return json.load(open(out))
    import sumolib

    net = sumolib.net.readNet(net_path, withPrograms=True)
    P = lambda p: net.convertLonLat2XY(*p)
    cands = []
    for t in car_lanes(things):
        g = t["geometry"]["coordinates"]
        ing, egr = orient([P(p) for p in g[0]], [P(p) for p in g[1]])
        path = ing + egr  # the whole lane connection, for crossings it passes through
        cands.append(dict(name=t["name"], ds=t["datastreams"]["primary_signal"], stop=ing[-1],
                          h_in=heading(ing[-2], ing[-1]), start=egr[0], h_out=heading(egr[0], egr[1]),
                          path=path))

    def passes(c, stop, h_in):
        """Distance from a stop line to the lane connection, if it runs the same way there."""
        best = math.inf
        for a, b in zip(c["path"], c["path"][1:]):
            if a == b or angdiff(heading(a, b), h_in) > math.radians(30):
                continue
            best = min(best, seg_dist(stop, a, b))
        return best

    def cost(c, stop, h_in, start, h_out):
        return (math.dist(c["stop"], stop) + math.dist(c["start"], start)
                + 25 * angdiff(c["h_in"], h_in) + 25 * angdiff(c["h_out"], h_out))

    links = {}
    for tls in net.getTrafficLights():
        for idx, l in tls.getLinks().items():
            inl, outl = l[0][0], l[0][1]
            a, b = inl.getShape(), outl.getShape()
            geo = (a[-1], heading(a[-2], a[-1]), b[0], heading(b[0], b[1]))
            best = min(((cost(c, *geo), c) for c in cands), key=lambda x: x[0], default=None)
            rec = {"from": inl.getEdge().getID(), "to": outl.getEdge().getID()}
            if best and best[0] < 60:
                rec.update(thing=best[1]["name"], ds=best[1]["ds"], how="direct")
            elif best and best[0] < 110:
                rec.update(thing=best[1]["name"], ds=best[1]["ds"], how="relaxed")
            else:
                rec.update(thing=None, ds=None, how="none")
            links[f"{tls.getID()}|{idx}"] = rec
    # A loose match is only trusted at a light that also has exact matches.
    exact = {k.split("|")[0] for k, v in links.items() if v["how"] == "direct"}
    for k, v in links.items():
        if v["how"] == "relaxed" and k.split("|")[0] not in exact:
            v.update(thing=None, ds=None, how="none")
    # Mid-block crossings: Hamburg describes them as part of the nearby junction, so the car
    # lane connection simply runs over the stop line. Use that signal for straight-on links.
    for k, v in links.items():
        if v["how"] != "none":
            continue
        tls_id, idx = k.split("|")
        l = net.getTLS(tls_id).getLinks()[int(idx)][0]
        a = l[0].getShape()
        stop, h_in = a[-1], heading(a[-2], a[-1])
        if angdiff(h_in, heading(l[1].getShape()[0], l[1].getShape()[-1])) > math.radians(30):
            continue  # only straight-on movements
        options = sorted((passes(c, stop, h_in), c["name"], c["ds"]) for c in cands)
        options = [[name, ds, round(d, 1)] for d, name, ds in options if d < 8]
        if options:
            # The final pick happens in vet_links, which knows how often each one is green.
            v.update(thing=options[0][0], ds=options[0][1], how="along", options=options)
    json.dump(links, open(out, "w"), indent=0)
    c = collections.Counter(v["how"] for v in links.values())
    log("signal links matched:", dict(c))
    return links


# ------------------------------------------------------------------ 4. recording
def extract(things, cache, t0, t1, out):
    if os.path.exists(out):
        return
    want = {}
    for t in things:
        for layer in ("primary_signal", "cycle_second", "detector_car"):
            if layer in t["datastreams"] and ("KFZ" in t["properties"].get("laneType", "") or layer == "detector_car"):
                want[t["datastreams"][layer]] = layer
    cached = os.path.join(cache, "recording.csv")
    if not os.path.exists(cached):
        stream_dataset(set(want), t1 + 3600, cached)
    n = 0
    with open(cached) as f, gzip.open(out, "wt") as g:
        r = csv.reader(f)
        next(r)
        g.write("phenomenon_time,result,datastream_id\n")
        for t, code, ds in r:
            if t0 <= int(t) < t1 and int(ds) in want:
                g.write(f"{t},{code},{ds}\n")
                n += 1
    log(n, "recorded state changes kept")


def stream_dataset(keep, until_received, out):
    """Read the zip from the start and keep rows of ``keep`` until ``until_received``."""
    log("streaming the TU Dresden recording (this reads about 1 GB per day of data)")
    resp = urllib.request.urlopen(urllib.request.Request(DATASET), timeout=120)
    head = resp.read(30)
    nlen, xlen = struct.unpack("<HH", head[26:30])
    resp.read(nlen + xlen)
    dec = zlib.decompressobj(-15)
    buf = b""
    with open(out, "w") as f:
        f.write("phenomenon_time,result,datastream_id\n")
        done = False
        while not done:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            buf += dec.decompress(chunk)
            lines = buf.split(b"\n")
            buf = lines.pop()
            for ln in lines:
                p = ln.split(b",")
                if len(p) < 5 or not p[0].isdigit():
                    continue
                if int(p[2]) // 1000 > until_received:
                    done = True
                    break
                if int(p[4]) in keep:
                    f.write(f"{p[0].decode()},{p[3].decode()},{p[4].decode()}\n")


def vet_links(links, rec_path, t0, t1, out, min_green=0.10):
    """Drop loose matches whose signal is almost never green: they would block the street.

    Exact (direct) matches are kept as they are: they are the real signal of that lane.
    """
    series = collections.defaultdict(list)
    with gzip.open(rec_path, "rt") as f:
        r = csv.reader(f)
        next(r)
        for t, code, ds in r:
            series[int(ds)].append((int(t), int(code)))
    share = {}
    for ds, s in series.items():
        s.sort()
        green = 0.0
        for (ta, ca), (tb, _) in zip(s, s[1:] + [(t1, 0)]):
            a, b = max(ta, t0), min(tb, t1)
            if b > a and ca in (3, 6):
                green += b - a
        share[ds] = green / (t1 - t0)
    dropped = 0
    for v in links.values():
        if v.get("options"):
            # A straight-on crossing: take the passing lane connection that is green most often.
            name, ds, _ = max(v["options"], key=lambda o: share.get(o[1], 0.0))
            v.update(thing=name, ds=ds)
        if v["ds"] and v["how"] != "direct" and share.get(v["ds"], 0.0) < min_green:
            v.update(thing=None, ds=None, how="none")
            dropped += 1
    json.dump(links, open(out, "w"), indent=0)
    log(dropped, "loose matches dropped (their signal is green less than", f"{min_green:.0%} of the hour)")
    lights = {k.split("|")[0] for k in links}
    covered = {k.split("|")[0] for k, v in links.items() if v["ds"] in share}
    with_data = sum(1 for v in links.values() if v["ds"] in share)
    log(f"{len(covered)} of {len(lights)} signal controllers and {with_data} of {len(links)} signal links "
        "have Hamburg data")
    return links


# ------------------------------------------------------------------ 5. traffic
def detector_counts(things, rec_path, t0, t1):
    det = {t["datastreams"]["detector_car"]: t["name"] for t in things if "detector_car" in t["datastreams"]}
    rows = collections.defaultdict(list)
    with gzip.open(rec_path, "rt") as f:
        r = csv.reader(f)
        next(r)
        for t, code, ds in r:
            if int(ds) in det:
                rows[int(ds)].append((int(t), int(code)))
    counts = {}
    for ds, s in rows.items():
        s.sort()
        prev, n = 0, 0
        for t, code in s:
            if t0 <= t < t1 and prev == 0 and code > 0:
                n += 1
            prev = code
        counts[det[ds]] = counts.get(det[ds], 0) + n
    return counts


def build_demand(sc, things, net_path, links, rec_path, t0, t1, main_volume, cache, out, edge_volume=None, period=0.4,
                 other_volume=None):
    """``edge_volume`` (edge -> vehicles/hour) replaces the one assumed ``main_volume`` on the
    main roads where it is given (see --demand dtv); ``other_volume`` (edge -> vehicles/hour) is
    a target for edges without a measured volume; ``period`` is randomTrips' spacing of
    candidate trips (lower: more candidates, needed for heavier traffic)."""
    if os.path.exists(out):
        return
    import sumolib

    tools = os.path.join(sumo_home(), "tools")
    cand = os.path.join(cache, "candidates.rou.xml")
    if not os.path.exists(cand):
        run([sys.executable, os.path.join(tools, "randomTrips.py"), "-n", net_path, "-o",
             os.path.join(cache, "trips.xml"), "-r", cand, "-e", "3600", "-p", str(period), "--fringe-factor", "100",
             "--min-distance", "250", "--seed", "7", "--validate"])
    routes_in = cand
    if edge_volume:
        # Candidates for the main roads' traffic that start and end on the roads with a volume, so
        # that it does not come in through the side streets (they would carry it otherwise).
        cand2 = os.path.join(cache, "candidates_main.rou.xml")
        if not os.path.exists(cand2):
            prefix = os.path.join(cache, "main_weights")
            for kind in ("src", "dst"):
                with open(f"{prefix}.{kind}.xml", "w") as f:
                    f.write('<edgedata>\n  <interval begin="0" end="3600">\n')
                    for e in edge_volume:
                        f.write(f'    <edge id="{e}" value="1"/>\n')
                    f.write("  </interval>\n</edgedata>\n")
            run([sys.executable, os.path.join(tools, "randomTrips.py"), "-n", net_path, "-o",
                 os.path.join(cache, "trips_main.xml"), "-r", cand2, "-e", "3600", "-p", str(period),
                 "--weights-prefix", prefix, "--min-distance", "250", "--seed", "11", "--validate",
                 "--prefix", "m"])
        routes_in = cand + "," + cand2
    counts = detector_counts(things, rec_path, t0, t1)
    rel = collections.Counter()
    for v in links.values():
        if v["how"] == "direct" and v["thing"] in counts:
            rel[(v["from"], v["to"])] = max(rel[(v["from"], v["to"])], counts[v["thing"]])
    turns = os.path.join(cache, "turns.xml")
    with open(turns, "w") as f:
        f.write('<data>\n  <interval id="hour" begin="0" end="3600">\n')
        for (a, b), n in rel.items():
            f.write(f'    <edgeRelation from="{a}" to="{b}" count="{n}"/>\n')
        f.write("  </interval>\n</data>\n")
    net = sumolib.net.readNet(net_path)
    edges = os.path.join(cache, "edges.xml")
    if edge_volume is None:
        main = [e for e in net.getEdges() if e.getName() in sc["main_roads"] and e.getLaneNumber() >= sc["main_min_lanes"]]
    else:
        main = [e for e in net.getEdges() if e.getID() in edge_volume]
    with open(edges, "w") as f:
        f.write('<data>\n  <interval id="hour" begin="0" end="3600">\n')
        for e in main:
            if edge_volume is None:
                f.write(f'    <edge id="{e.getID()}" entered="{main_volume}"/>\n')
            elif e.getID() in edge_volume:
                f.write(f'    <edge id="{e.getID()}" entered="{round(edge_volume[e.getID()])}"/>\n')
        for eid, v in (other_volume or {}).items():
            f.write(f'    <edge id="{eid}" entered="{round(v)}"/>\n')
        f.write("  </interval>\n</data>\n")
    if edge_volume is None:
        log(len(rel), "movements with real detector counts,", len(main), "main-road edges at", main_volume, "veh/h")
    else:
        log(len(rel), "movements with real detector counts,", sum(1 for e in main if e.getID() in edge_volume),
            "main-road edges from the 2019 volumes")
    run([sys.executable, os.path.join(tools, "routeSampler.py"), "-r", routes_in, "--turn-files", turns,
         "--edgedata-files", edges, "-o", out, "--seed", "7"])
    # Same moderate driver imperfection for every car (SUMO's default sigma=0.5 adds a lot of random braking).
    s = open(out).read()
    s = re.sub(r"(<routes[^>]*>)", r'\1\n    <vType id="DEFAULT_VEHTYPE" length="4.5" minGap="2.5" accel="1.4" '
               r'decel="4.5" sigma="0.2" speedFactor="1" speedDev="0.05"/>', s, count=1)
    open(out, "w").write(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="gaertnerstrasse")
    ap.add_argument("--cache", required=True, help="folder for downloads and intermediate files")
    ap.add_argument("--start", type=int, default=1694703600, help="test hour start, unix time (default Thu 14 Sep 2023 15:00 UTC)")
    ap.add_argument("--lookback", type=int, default=5400, help="seconds of history kept before the test hour")
    ap.add_argument("--demand", choices=["assumed", "dtv"], default="assumed",
                    help="dtv: a second traffic file, routes_dtv.rou.xml, with the main roads from Hamburg's 2019 "
                         "volumes (public_data.json, tools/hamburg_public_data.py): DTV x --peak-share / 2 per direction")
    ap.add_argument("--peak-share", type=float, default=0.09, help="share of the daily volume in the test hour (assumed)")
    ap.add_argument("--main-volume", type=int, default=None,
                    help="assumed vehicles/hour per main-road edge (default: the scenario's own, else 400)")
    a = ap.parse_args()
    sc = SCENARIOS[a.scenario]
    if a.main_volume is None:
        a.main_volume = sc.get("main_volume", 400)
    cache = os.path.join(a.cache, a.scenario)
    out = os.path.join(DATA, a.scenario)
    os.makedirs(cache, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    sumo_home()
    if a.demand == "dtv":
        build_dtv_demand(a, sc, cache, out)
        return
    things = fetch_things(sc["lights"], os.path.join(out, "lanes.json"))
    net = os.path.join(out, "corridor.net.xml")
    build_network(sc, things, cache, net)
    links = match_links(things, net, os.path.join(out, "links.json"))
    rec = os.path.join(out, "signals.csv.gz")
    t0, t1 = a.start - a.lookback, a.start + 3600 + 600
    extract(things, cache, t0, t1, rec)
    links = vet_links(links, rec, a.start, a.start + 3600, os.path.join(out, "links.json"))
    build_demand(sc, things, net, links, rec, a.start, a.start + 3600, a.main_volume, cache,
                 os.path.join(out, "routes.rou.xml"))
    json.dump({"scenario": a.scenario, "title": sc["title"], "main_roads": list(sc["main_roads"]),
               "start": a.start, "lookback": a.lookback,
               "main_volume": a.main_volume, "lights": sc["lights"], "bbox": sc["bbox"], "band": sc["band"]},
              open(os.path.join(out, "scenario.json"), "w"), indent=1)
    log("done:", out)


def build_dtv_demand(a, sc, cache, out):
    """The test hour's traffic with the main roads from the city's 2019 volumes."""
    sys.path.insert(0, ROOT)
    from drivenow.hamburg import public_data as pd
    from drivenow.network import load_sumo_net
    scen_path = os.path.join(out, "scenario.json")
    scen = json.load(open(scen_path))
    snap = json.load(open(os.path.join(out, "public_data.json")))
    points = json.load(open(os.path.join(out, "edge_points.json")))
    net_path = os.path.join(out, "corridor.net.xml")
    names = {e.id: e.name for e in load_sumo_net(net_path).edges.values()}
    # Every main road of the box with a 2019 volume, not only the scenario's axis: a constraint
    # only there would fill the side streets with the extra traffic.
    dtv = pd.volumes(snap, points, names, None)
    edge_volume = {e: v * a.peak_share / 2 for e, v in dtv.items()}
    things = json.load(open(os.path.join(out, "lanes.json")))
    links = json.load(open(os.path.join(out, "links.json")))
    rec = os.path.join(out, "signals.csv.gz")
    dcache = os.path.join(cache, "dtv")
    os.makedirs(dcache, exist_ok=True)
    # Streets without a measured volume keep the traffic of the first traffic file (counted by the
    # loop detectors where there are some): otherwise the extra main-road traffic fills them.
    from collections import Counter
    from drivenow.sumo_world import read_routes
    old = Counter(e for r in read_routes(os.path.join(out, "routes.rou.xml")).values() for e in r)
    other = {e: n for e, n in old.items() if e not in edge_volume and names.get(e)}
    build_demand(sc, things, net_path, links, rec, scen["start"], scen["start"] + 3600, a.main_volume, dcache,
                 os.path.join(out, "routes_dtv.rou.xml"), edge_volume=edge_volume, period=0.06, other_volume=other)
    scen["demand_dtv"] = {"file": "routes_dtv.rou.xml", "source": "Verkehrsmengen auf Hauptverkehrsstraßen 2019 (DTV), "
                          "Behörde für Verkehr und Mobilitätswende, DL-DE BY 2.0", "peak_share": a.peak_share,
                          "peak_share_is": "assumed: share of the daily volume in the test hour, split evenly by direction",
                          "main_edges_with_volume": len(edge_volume),
                          "other_streets": "target: the traffic of routes.rou.xml (assumed: no open counts there)"}
    json.dump(scen, open(scen_path, "w"), indent=1)
    log("done:", os.path.join(out, "routes_dtv.rou.xml"))


if __name__ == "__main__":
    main()
