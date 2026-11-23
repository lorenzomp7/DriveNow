"""Build data/traffic_sources.json: the traffic data sources found for DriveNow.

    python tools/build_sources_catalog.py            # fetches the list from GitHub
    python tools/build_sources_catalog.py LIST.md    # or reads a local copy

From three places: the links of graphhopper/open-traffic-collection (its README,
read for its links only: name, URL, and the type, format and access its text
mentions), USDOT's WZDx feed registry (data/wzdx_registry.json, downloaded from
data.transportation.gov) and the sources checked by hand on 23 November 2026,
with what was found. Then ``tools/sources_catalog.py`` lists and checks them.
"""
import json, os, re, sys, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_URL = "https://raw.githubusercontent.com/graphhopper/open-traffic-collection/master/README.md"
reg_path = os.path.join(ROOT, "data", "wzdx_registry.json")
out = os.path.join(ROOT, "data", "traffic_sources.json")
if len(sys.argv) > 1:
    md_text = open(sys.argv[1], encoding="utf-8").read()
else:
    md_text = urllib.request.urlopen(LIST_URL, timeout=30).read().decode("utf-8")

def kinds_of(text):
    t = text.lower()
    k = []
    for word, kind in (("count", "counts"), ("intensit", "counts"), ("flow", "flow"), ("speed", "speed"),
                       ("travel time", "travel_time"), ("journey time", "travel_time"), ("roadwork", "roadworks"),
                       ("construction", "roadworks"), ("closure", "closures"), ("restriction", "restrictions"),
                       ("incident", "incidents"), ("event", "incidents"), ("traffic messages", "incidents"),
                       ("accident", "incidents"), ("weather", "weather"), ("brug", "bridges"), ("bridge", "bridges"),
                       ("signal", "signals"), ("traffic information", "incidents"), ("live traffic", "flow"),
                       ("real-time traffic", "flow"), ("traffic data", "flow"), ("interruption", "incidents"),
                       ("mountain pass", "closures"), ("weight", "restrictions"), ("jam", "queues"),
                       ("situation", "incidents"), ("conditions", "incidents"), ("trafficmessages", "incidents"),
                       ("aadt", "counts"), ("taxi", "trips")):
        if word in t and kind not in k:
            k.append(kind)
    return k or ["traffic"]

def access_of(text):
    t = text.lower()
    if "open rss" in t and len(t) < 40:
        return "open"
    if re.search(r"\bfee\b|unfree", t):
        return "paid or restricted"
    if "registration" in t or "account is required" in t or "requires registration" in t or "running a server" in t:
        return "registration"
    if "broken" in t or "no longer available" in t or "inactive" in t:
        return "unavailable"
    return "open"

def fmt_of(text, url):
    t = (text + " " + url).lower()
    if "datex" in t:
        return "DATEX II"
    for f in ("geojson", "json", "gml", "csv", "xml", "rss", "wfs"):
        if f in t:
            return f.upper() if f != "geojson" else "GeoJSON"
    return "portal"

entries = []
region = []
for line in md_text.splitlines():
    h = re.match(r"^(#+)\s+(.*)", line)
    if h:
        level = len(h.group(1))
        region = region[:max(level - 2, 0)] + [h.group(2).strip()]
        top = None
        continue
    m = re.match(r"^(\s*)[*-]\s+(.*)", line)
    if not m:
        continue
    indent, body = len(m.group(1)), m.group(2)
    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", body)
    plain = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", body)
    if indent == 0:
        top = re.split(r"[:(]", plain)[0].strip()
    if not links:
        continue
    for name, url in links:
        if url.startswith("#") or "github.com/graphhopper/open-traffic-collection/issues" in url:
            continue
        place = ", ".join([r for r in region[1:] if r and r not in ("Europe", "Misc", "Europe Misc")] or region[:1])
        area = top if indent > 0 and top and top != name else name
        entries.append({"name": name if indent > 0 or ":" in plain else name, "area": area, "region": place or "World",
                        "url": url, "kinds": kinds_of(plain), "format": fmt_of(plain, url), "access": access_of(plain),
                        "adapter": "datex2" if "datex" in plain.lower() else None,
                        "notes": "", "from": "graphhopper/open-traffic-collection"})

reg = json.load(open(reg_path))
cols = [c["name"] for c in reg["meta"]["view"]["columns"]]
for row in reg["data"]:
    r = dict(zip(cols, row))
    url = r.get("url")
    url = url[0] if isinstance(url, list) else url
    if not url:
        continue
    entries.append({"name": f"WZDx: {r.get('issuingOrganization')} ({r.get('feedName')})", "area": r.get("state") or "",
                    "region": "USA", "url": url, "kinds": ["roadworks", "closures"], "format": "WZDx " + str(r.get("version") or ""),
                    "access": "API key" if r.get("needAPIKey") else "open", "adapter": "wzdx",
                    "notes": "From USDOT's Work Zone Data Feed Registry" + ("" if r.get("active") else " (inactive)"),
                    "from": "data.transportation.gov 69qe-yiui"})

checked = "2026-11-23"
manual = [
 ("Hamburg traffic lights and loop detectors (live, MQTT)", "Hamburg", "Germany", "wss://tld.iot.hamburg.de/mqtt", ["signals", "counts", "queues"], "SensorThings + MQTT", "open", "hamburg.live", "Signal colours, cycle seconds, car loop detectors; ~1-2 s late.", "reached"),
 ("Hamburg traffic state per road (Verkehrslage)", "Hamburg", "Germany", "https://geodienste.hamburg.de/wfs_hh_verkehrslage", ["flow"], "WFS (GML)", "open", "hamburg_traffic", "State class per stretch (fliessend/dicht/zäh/stockend), every 5 min.", "reached"),
 ("Hamburg police traffic messages (in force now)", "Hamburg", "Germany", "https://geodienste.hamburg.de/wfs_verkehrsinformation", ["roadworks", "closures", "queues", "incidents", "signals"], "WFS (GML)", "open", "hamburg_police", "Roadworks, closures, queues, accidents, lights out of order. DL-DE BY 2.0.", "reached"),
 ("Autobahn GmbH API (roadworks, warnings, closures)", "Germany motorways", "Germany", "https://verkehr.autobahn.de/o/autobahn/", ["roadworks", "closures", "incidents", "queues"], "JSON", "open", "autobahn", "No key. A7 alone: 217 roadworks, 26 closures on 23 Nov 2026.", "reached"),
 ("NDW open data (speeds, travel times, situations, bridges)", "Netherlands", "Netherlands", "https://opendata.ndw.nu/", ["speed", "flow", "travel_time", "roadworks", "closures", "incidents", "bridges", "restrictions"], "DATEX II", "open", "datex2", "Updated every minute; situations with coordinates (DATEX II v3).", "reached"),
 ("Verkeerscentrum Vlaanderen DATEX II", "Flanders", "Belgium", "https://www.verkeerscentrum.be/uitwisseling/datex2full", ["roadworks", "incidents", "queues"], "DATEX II", "open", "datex2", "Locations in Alert-C only: need Belgium's location table.", "reached"),
 ("Digitraffic traffic messages", "Finland", "Finland", "https://tie.digitraffic.fi/api/traffic-message/v1/messages", ["roadworks", "incidents", "restrictions"], "GeoJSON", "open", "digitraffic", "Needs Accept-Encoding: gzip and a Digitraffic-User header.", "reached"),
 ("5T Turin real-time flows", "Turin", "Italy", "https://opendata.5t.torino.it/get_fdt", ["flow", "speed"], "XML", "open", "torino", "Flow and speed per point, 5-minute periods.", "reached"),
 ("Väylä roadworks (DATEX II)", "Finland", "Finland", "https://aineistot.vayla.fi/roadworks/roadworks_d2.xml", ["roadworks"], "DATEX II", "open", "datex2", "Answered 400 on 23 Nov 2026.", "failed"),
 ("Porto unplanned road conditions (DATEX II v3)", "Porto", "Portugal", "https://opendata.porto.digital/dataset/condicionamentos-nao-programados", ["closures", "restrictions"], "DATEX II", "open", "datex2", "Unplanned closures and restrictions in the city.", None),
 ("OpenStreetMap via Overpass (lights, limits, roadworks)", "World", "World", "https://overpass-api.de/api/interpreter", ["signals", "roadworks", "speed_limits"], "JSON", "open", "osm", "Connection reset from this environment on 23 Nov 2026.", "failed"),
 ("Hamburg roadworks (Bauweiser, WFS)", "Hamburg", "Germany", "https://geodienste.hamburg.de/hh_wfs_baustellen", ["roadworks", "closures"], "WFS (GML)", "open", "hamburg_roadworks", "About 135 sites, points with start and end day and a free text. DL-DE BY 2.0.", "reached"),
 ("LSBG Hamburg roadworks (Traffic Disturbance Roadworks, DATEX II v2)", "Hamburg", "Germany", "https://mobilithek.info/offers/110000000003540000", ["roadworks", "closures", "restrictions"], "DATEX II", "registration", "mobilithek", "Every roadworks site on Hamburg's streets, hourly; Mobilithek subscription with provider approval and a machine certificate (mutual TLS, port 8443).", None),
 ("Mobilithek (German national access point)", "Germany", "Germany", "https://mobilithek.info/", ["flow", "incidents", "roadworks", "travel_time"], "DATEX II", "registration", "datex2", "Many datasets open, some need registration (e.g. Bavaria's jams every 3 min).", None),
 ("BayernInfo / VIZ Bayern", "Bavaria", "Germany", "https://bayerninfo.de/en/about-bayerninfo-1/data-offer/private-transport-data", ["queues", "incidents", "roadworks"], "DATEX II", "registration", "datex2", "Jams from connected vehicles and apps, every 3 min, via Mobilithek.", None),
 ("Bolzano / South Tyrol Open Data Hub", "South Tyrol", "Italy", "https://mobility.api.opendatahub.com/", ["flow", "speed", "travel_time"], "JSON", "open", None, "Traffic sensors and Bluetooth travel times.", None),
 ("Waze for Cities data feed", "World", "World", "https://support.google.com/waze/partners/answer/10618035", ["queues", "incidents", "closures"], "JSON/XML GeoRSS", "public bodies only", "traffic_sources.WazeJams", "Jams with speed, length, delay; every 2 min; free for partners.", None),
 ("TomTom Traffic Flow", "World", "World", "https://developer.tomtom.com/traffic-api", ["flow", "speed"], "JSON", "API key", "traffic_sources.TomTomFlow", "Free quota; probe data from >600 million devices.", None),
 ("HERE Traffic API v7", "World", "World", "https://docs.here.com/traffic-api/docs/here-traffic-api-v7-concepts", ["flow", "speed", "incidents", "roadworks", "closures"], "JSON", "API key", "here", "5,000 free transactions a month listed on HERE's pricing page.", None),
 ("USDOT Work Zone Data Feed Registry", "USA", "USA", "https://data.transportation.gov/Transportation/Work-Zone-Data-Exchange-WZDx-Feed-Registry/69qe-yiui", ["roadworks", "closures"], "JSON", "open", "wzdx", "The list of public WZDx feeds (43 on 23 Nov 2026).", "reached"),
 ("NYC real-time traffic speed", "New York City", "USA", "https://data.cityofnewyork.us/Transportation/Real-Time-Traffic-Speed-Data/xsat-x5sa", ["speed", "travel_time"], "JSON/CSV", "open", None, "Speeds and travel times on major roads.", None),
 ("Telraam", "World", "World", "https://telraam.net", ["counts"], "JSON", "API key (free)", None, "Citizen traffic counters in many cities.", None),
 ("Google Maps Platform (Routes API)", "World", "World", "https://developers.google.com/maps/documentation/routes/policies", ["travel_time"], "JSON", "API key, restrictive terms", None, "Traffic-aware route times only; caching restricted, results on Google maps: not usable as a database.", None),
 ("Apple MapKit", "World", "World", "https://developer.apple.com/documentation/mapkit", ["travel_time"], "SDK", "developer account", None, "Shows traffic and ETAs; no traffic data API found.", None),
]
for name, area, region_, url, kinds, fmt, access, adapter, notes, status in manual:
    e = {"name": name, "area": area, "region": region_, "url": url, "kinds": kinds, "format": fmt, "access": access,
         "adapter": adapter, "notes": notes, "from": "checked by hand"}
    if status:
        e["checked"] = {"date": checked, "status": status}
    entries.append(e)

# Countries: the list puts European sources under "Europe" with the country in the bullet.
NAMES = ["Austria", "Belgium", "Czechia", "Estonia", "Finland", "France", "Germany", "Italy", "Latvia", "Lithuania",
         "Luxembourg", "Netherlands", "Norway", "Poland", "Portugal", "Slovenia", "Spain", "Sweden", "Switzerland",
         "Ukraine", "UK"]
ALIAS = {"Catalonia": "Spain", "Bolzano": "Italy", "South Tyrol": "Italy", "Turin": "Italy", "Porto": "Portugal",
         "Madrid": "Spain", "Gothenbury": "Sweden", "Kyiv": "Ukraine", "England": "UK", "Scotland": "UK",
         "Brussels": "Belgium", "Paris": "France", "Cologne": "Germany", "Hamburg": "Germany", "Darmstadt": "Germany",
         "Jena": "Germany", "Düsseldorf": "Germany", "Nordrhein-Westfalen": "Germany", "Entire DE": "Germany",
         "German Mobilithek": "Germany", "Mobilithek": "Germany", "Datex-II live": "France", "Traffic count": "France",
         "Flanders": "Belgium", "Roadworks": None}
for e in entries:
    if e["region"] != "Europe":
        e["region"] = {"Misc": "World", "Europe Misc": "Europe"}.get(e["region"], e["region"])
        continue
    text = e["area"] + " " + e["name"] + " " + e["notes"][:60]
    found = next((n for n in NAMES if re.search(r"\b" + n + r"\b", e["area"])), None)
    if found is None:
        found = next((ALIAS[a] for a in ALIAS if ALIAS[a] and a in e["area"]), None)
    if found is None:
        found = next((n for n in NAMES if re.search(r"\b" + n + r"\b", text)), None)
    if found is None:
        found = next((ALIAS[a] for a in ALIAS if ALIAS[a] and a in text), "Europe")
    e["region"] = found
# Links that are documentation, discussions or blog posts, not data.
DOCS = {"here", "#1", "#2", "#13", "#16", "#25", "blog post", "this blog post", "this stackexchange answer",
        "this github repository", "general documentation", "API docs", "limitations", "replaces the MDM platform and mCLOUD",
        "VILD", "here", "described here"}
entries = [e for e in entries if e["name"] not in DOCS and "open-traffic-collection/pull" not in e["url"]
           and "dalelane.co.uk" not in e["url"] and "toddwschneider" not in e["url"]]
for e in entries:
    if e["from"] != "checked by hand" and e["area"] and e["area"] != e["name"] and e["area"] not in e["name"]:
        e["name"] = f"{e['area']}: {e['name']}"
# Addresses that have moved (the old one redirects here; checked on 23 November 2026).
MOVED = {"https://opendata.porto.digital/": "https://dadosabertos.cm-porto.pt/",
         "https://www.quandl.com/": "https://data.nasdaq.com/",
         "https://bayerninfo.de/": "https://www.bayerninfo.de/",
         "https://www.europeandataportal.eu/data/#/datasets/": "https://data.europa.eu/data/datasets/",
         "https://www.trafficengland.com/": "https://www.nationalhighways.co.uk/",
         "https://trafficscotland.org/": "https://www.traffic.gov.scot/",
         "https://data.gov.uk/": "https://www.data.gov.uk/",
         "https://www.datex2.eu/": "https://datex2.eu/"}
for e in entries:
    for old, new in MOVED.items():
        if e["url"].startswith(old):
            e["moved_from"], e["url"] = e["url"], new + e["url"][len(old):]
# One entry per URL; the hand-checked one wins.
seen = {}
for e in entries:
    key = re.sub(r"^https?://", "", e["url"]).rstrip("/")
    if key not in seen or e["from"] == "checked by hand":
        seen[key] = e
cat = sorted(seen.values(), key=lambda e: (e["region"], e["area"], e["name"]))
json.dump({"about": "Public and commercial traffic data sources found for DriveNow: flow, speed, travel times, "
                    "roadworks, closures, incidents, queues, lights. Built on 23 November 2026 from "
                    "graphhopper/open-traffic-collection, USDOT's WZDx registry and sources checked by hand. "
                    "'adapter' names the module in drivenow/sources that reads the format; 'checked' is a live "
                    "check from DriveNow's development environment.",
           "sources": cat}, open(out, "w"), ensure_ascii=False, indent=1)
print(len(cat), "sources")
