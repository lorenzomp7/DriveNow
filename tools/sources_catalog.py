"""The catalogue of traffic data sources (data/traffic_sources.json): list, filter, check.

    python tools/sources_catalog.py                          # summary by country and kind
    python tools/sources_catalog.py --region Italy           # the sources of a country
    python tools/sources_catalog.py --kind roadworks --open  # open sources of roadworks
    python tools/sources_catalog.py --adapter datex2         # what an adapter can read
    python tools/sources_catalog.py --check [--region ...]   # try to reach them, write the result

``--check`` asks each URL (15 s timeout) and records, with the date, "reached"
(the host answered; a service asked without its parameters may answer 400),
"error (HTTP n)" (404 or a server error), "blocked" (this machine's network
refused the host), "unreachable" (no answer at all) or "moved" (the page now
sends to a site's home page: the data is no longer at that address).
"""
import argparse, datetime, json, os, subprocess, sys, urllib.parse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "traffic_sources.json")

ap = argparse.ArgumentParser()
ap.add_argument("--region")
ap.add_argument("--kind")
ap.add_argument("--adapter")
ap.add_argument("--open", action="store_true", help="only sources open without registration or key")
ap.add_argument("--check", action="store_true", help="try to reach each source and write the result")
a = ap.parse_args()

cat = json.load(open(PATH, encoding="utf-8"))
src = cat["sources"]
sel = [s for s in src
       if (not a.region or a.region.lower() in s["region"].lower() or a.region.lower() in s["area"].lower())
       and (not a.kind or a.kind in s["kinds"])
       and (not a.adapter or (s.get("adapter") or "").startswith(a.adapter))
       and (not a.open or s["access"] == "open")]


def check(url):
    if not url.startswith("http"):
        return "not checked"
    r = subprocess.run(["curl", "-sS", "-o", "/dev/null", "-L", "-m", "15", "-w", "%{http_code} %{url_effective}", url],
                       capture_output=True, text=True)
    code, _, final = (r.stdout.strip() or "000").partition(" ")
    if code == "000":
        # No HTTP answer. The proxy answers 403 to a host this machine's network does
        # not allow; 502/504 mean the host was allowed but did not answer.
        return "blocked" if "CONNECT tunnel failed, response 403" in r.stderr else "unreachable"
    # The page asked for now sends to a site's home page: the data is no longer there.
    path = urllib.parse.urlsplit(url).path.strip("/")
    if path and not urllib.parse.urlsplit(final).path.strip("/") and code == "200":
        return "moved (to a home page)"
    # An HTTP answer: the host is there. A service endpoint asked without its parameters
    # (a WFS, an API) often answers 400 or 406: still reached.
    return "reached" if int(code) < 500 and code != "404" else f"error (HTTP {code})"


if a.check:
    today = datetime.date.today().isoformat()
    for s in sel:
        if s.get("checked", {}).get("status", "").startswith("moved"):
            # Found sending to a home page (with the host allowed): the data is gone, and
            # the host may since have been taken off this machine's allowed list.
            print(f'{s["checked"]["status"]:<22} {s["region"]:<12} {s["name"][:70]} (kept)', flush=True)
            continue
        s["checked"] = {"date": today, "status": check(s["url"])}
        print(f'{s["checked"]["status"]:<22} {s["region"]:<12} {s["name"][:70]}', flush=True)
    json.dump(cat, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(Counter(s["checked"]["status"].split(" ")[0] for s in sel))
    sys.exit(0)

if a.region or a.kind or a.adapter or a.open:
    for s in sel:
        st = s.get("checked", {}).get("status", "")
        print(f'{s["region"]:<12} {s["access"]:<14} {s["format"]:<12} {",".join(s["kinds"]):<34} '
              f'{(s.get("adapter") or "-"):<16} {st:<10} {s["name"][:60]}\n{"":<12} {s["url"]}')
    print(len(sel), "sources")
else:
    print(len(src), "sources\n")
    print("By country/region:", ", ".join(f"{k} {n}" for k, n in Counter(s["region"] for s in src).most_common()))
    print("By kind:", ", ".join(f"{k} {n}" for k, n in Counter(k for s in src for k in s["kinds"]).most_common()))
    print("By access:", ", ".join(f"{k} {n}" for k, n in Counter(s["access"] for s in src).most_common()))
    print("Readable by an adapter:", sum(1 for s in src if s.get("adapter")))
