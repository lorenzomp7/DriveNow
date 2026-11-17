"""Build the Hamburg scenario in data/hamburg/ from the original sources.

    python tools/hamburg_build.py --cache /tmp/hh

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
OUT = os.path.join(ROOT, "data", "hamburg")

STA = "https://tld.iot.hamburg.de/v1.1/"
OSM = "https://api.openstreetmap.org/api/0.6/map?bbox={}"
DATASET = "https://opara.zih.tu-dresden.de/server/api/core/bitstreams/686a91e8-d2d3-42af-843a-4ebb83787ba4/content"

# Willy-Brandt-Strasse / Ludwig-Erhard-Strasse, 1.9 km, 9 traffic lights.
LIGHTS = ["305", "2438", "467", "79", "78", "96", "50", "246", "310"]
BBOX = "9.9815,53.5455,10.0165,53.5545"
MAIN_ROADS = ("Willy-Brandt-Straße", "Ludwig-Erhard-Straße")
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
def fetch_things(path):
    if os.path.exists(path):
        return json.load(open(path))
    things = []
    for tl in LIGHTS:
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


def heading(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def angdiff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


# ------------------------------------------------------------------ 2. network
def build_network(things, cache, net_out):
    if os.path.exists(net_out):
        return
    import sumolib

    osm = os.path.join(cache, "corridor.osm")
    if not os.path.exists(osm):
        log("downloading OpenStreetMap", BBOX)
        urllib.request.urlretrieve(OSM.format(BBOX), osm)
    raw = os.path.join(cache, "raw.net.xml")
    run(["netconvert", "--osm-files", osm, "-o", raw, "--keep-edges.by-type", KEEP_TYPES,
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
    run(["netconvert", "--sumo-net-file", raw, "--plain-output-prefix", prefix, "--no-warnings"])
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
        cands.append(dict(name=t["name"], ds=t["datastreams"]["primary_signal"], stop=ing[-1],
                          h_in=heading(ing[-2], ing[-1]), start=egr[0], h_out=heading(egr[0], egr[1])))

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


def build_demand(things, net_path, links, rec_path, t0, t1, main_volume, cache, out):
    if os.path.exists(out):
        return
    import sumolib

    tools = os.path.join(sumo_home(), "tools")
    cand = os.path.join(cache, "candidates.rou.xml")
    if not os.path.exists(cand):
        run([sys.executable, os.path.join(tools, "randomTrips.py"), "-n", net_path, "-o",
             os.path.join(cache, "trips.xml"), "-r", cand, "-e", "3600", "-p", "0.4", "--fringe-factor", "100",
             "--min-distance", "250", "--seed", "7", "--validate"])
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
    main = [e for e in net.getEdges() if e.getName() in MAIN_ROADS and e.getLaneNumber() >= 2]
    with open(edges, "w") as f:
        f.write('<data>\n  <interval id="hour" begin="0" end="3600">\n')
        for e in main:
            f.write(f'    <edge id="{e.getID()}" entered="{main_volume}"/>\n')
        f.write("  </interval>\n</data>\n")
    log(len(rel), "movements with real detector counts,", len(main), "main-road edges at", main_volume, "veh/h")
    run([sys.executable, os.path.join(tools, "routeSampler.py"), "-r", cand, "--turn-files", turns,
         "--edgedata-files", edges, "-o", out, "--seed", "7"])
    # Same moderate driver imperfection for every car (SUMO's default sigma=0.5 adds a lot of random braking).
    s = open(out).read()
    s = re.sub(r"(<routes[^>]*>)", r'\1\n    <vType id="DEFAULT_VEHTYPE" length="4.5" minGap="2.5" accel="1.4" '
               r'decel="4.5" sigma="0.2" speedFactor="1" speedDev="0.05"/>', s, count=1)
    open(out, "w").write(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", required=True, help="folder for downloads and intermediate files")
    ap.add_argument("--start", type=int, default=1694703600, help="test hour start, unix time (default Thu 14 Sep 2023 15:00 UTC)")
    ap.add_argument("--lookback", type=int, default=5400, help="seconds of history kept before the test hour")
    ap.add_argument("--main-volume", type=int, default=400, help="assumed vehicles/hour per main-road edge")
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    sumo_home()
    things = fetch_things(os.path.join(OUT, "lanes.json"))
    net = os.path.join(OUT, "corridor.net.xml")
    build_network(things, a.cache, net)
    links = match_links(things, net, os.path.join(OUT, "links.json"))
    rec = os.path.join(OUT, "signals.csv.gz")
    t0, t1 = a.start - a.lookback, a.start + 3600 + 600
    extract(things, a.cache, t0, t1, rec)
    build_demand(things, net, links, rec, a.start, a.start + 3600, a.main_volume, a.cache,
                 os.path.join(OUT, "routes.rou.xml"))
    json.dump({"start": a.start, "lookback": a.lookback, "main_volume": a.main_volume, "lights": LIGHTS,
               "bbox": BBOX}, open(os.path.join(OUT, "scenario.json"), "w"), indent=1)
    log("done:", OUT)


if __name__ == "__main__":
    main()
