"""Where each edge of a SUMO network is on the globe, for traffic data providers.

    python tools/edge_points.py data/hamburg/willy-brandt/corridor.net.xml

Writes ``edge_points.json`` next to the network: for every edge (junction-internal
ones left out) the midpoint of its shape as [lon, lat], its compass heading there in
degrees and its length in metres. TomTom and Waze speak lon/lat; the network speaks
metres in a UTM projection (the ``location`` element of the .net.xml).

Standard library only: the inverse UTM projection is computed here (WGS84, the
formulas of Snyder, "Map Projections: A Working Manual", 1987, pp. 63-64), so
neither pyproj nor sumolib is needed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import xml.etree.ElementTree as ET

A = 6378137.0                 # WGS84 semi-major axis, m
F = 1 / 298.257223563
E2 = F * (2 - F)              # first eccentricity squared
K0 = 0.9996


def utm_to_lonlat(x: float, y: float, zone: int, north: bool = True):
    """UTM easting/northing (m) to (lon, lat) in degrees."""
    x -= 500000.0
    if not north:
        y -= 10000000.0
    ep2 = E2 / (1 - E2)
    m = y / K0
    mu = m / (A * (1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, tn = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = A / math.sqrt(1 - E2 * s * s)
    t1 = tn * tn
    c1 = ep2 * c * c
    r1 = A * (1 - E2) / (1 - E2 * s * s) ** 1.5
    d = x / (n1 * K0)
    lat = phi1 - (n1 * tn / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
                                    + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / c
    return math.degrees(lon) + (zone - 1) * 6 - 180 + 3, math.degrees(lat)


def lonlat_to_utm(lon: float, lat: float, zone: int):
    """(lon, lat) in degrees to UTM easting/northing (m), northern hemisphere (Snyder p. 61)."""
    ep2 = E2 / (1 - E2)
    phi, lam = math.radians(lat), math.radians(lon - ((zone - 1) * 6 - 180 + 3))
    s, c, tn = math.sin(phi), math.cos(phi), math.tan(phi)
    n = A / math.sqrt(1 - E2 * s * s)
    t = tn * tn
    cc = ep2 * c * c
    a = lam * c
    m = A * ((1 - E2 / 4 - 3 * E2 ** 2 / 64 - 5 * E2 ** 3 / 256) * phi
             - (3 * E2 / 8 + 3 * E2 ** 2 / 32 + 45 * E2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * E2 ** 2 / 256 + 45 * E2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * E2 ** 3 / 3072) * math.sin(6 * phi))
    x = K0 * n * (a + (1 - t + cc) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * cc - 58 * ep2) * a ** 5 / 120)
    y = K0 * (m + n * tn * (a * a / 2 + (5 - t + 9 * cc + 4 * cc * cc) * a ** 4 / 24
                            + (61 - 58 * t + t * t + 600 * cc - 330 * ep2) * a ** 6 / 720))
    return x + 500000.0, y


def projection(root):
    loc = root.find("location")
    ox, oy = (float(v) for v in loc.attrib["netOffset"].split(","))
    zone = int(re.search(r"\+zone=(\d+)", loc.attrib["projParameter"]).group(1))
    north = "+south" not in loc.attrib["projParameter"]
    return lambda x, y: utm_to_lonlat(x - ox, y - oy, zone, north)


def midpoint(shape):
    """Point halfway along a polyline, the compass heading there (degrees) and the length."""
    segs = [(a, b, math.dist(a, b)) for a, b in zip(shape, shape[1:])]
    total = sum(d for _, _, d in segs)
    half = total / 2
    for a, b, d in segs:
        if half <= d or (a, b, d) == segs[-1]:
            f = 0.0 if d == 0 else min(half / d, 1.0)
            p = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
            return p, math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360, total
        half -= d
    return shape[0], 0.0, 0.0


def edge_points(net_path: str):
    root = ET.parse(net_path).getroot()
    to_lonlat = projection(root)
    out = {}
    for e in root.iter("edge"):
        if e.attrib.get("function") == "internal":
            continue
        lane = e.find("lane")
        raw = e.attrib.get("shape") or (lane.attrib.get("shape") if lane is not None else None)
        if not raw:
            continue
        shape = [tuple(float(v) for v in p.split(",")[:2]) for p in raw.split()]
        (x, y), heading, length = midpoint(shape)
        lon, lat = to_lonlat(x, y)
        out[e.attrib["id"]] = [round(lon, 7), round(lat, 7), round(heading, 1), round(length, 1)]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("net")
    a = ap.parse_args()
    pts = edge_points(a.net)
    out = os.path.join(os.path.dirname(a.net), "edge_points.json")
    json.dump(pts, open(out, "w"), separators=(",", ":"))
    print(len(pts), "edges ->", out)
