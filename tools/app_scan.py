"""Fill the declaration tables of an app sheet (docs/app-analizzate/) from an APK, through REA.

REA (https://github.com/morluto/rea, MIT) decodes the APK with Apktool
(``rea decode-android-resources``) and reads its signature (``rea inspect-apk-signature``);
nothing in the APK is executed. This script reads REA's evidence and writes the parts of
the sheet that the APK declares: version, signature, permissions, foreground services,
Android Auto, background-location wiring, bundled libraries and frameworks (from the file
list), and the strings that match the sheet's topics. What the code does with them (data
sources, timing of announcements) still needs reading the code, e.g. with ``rea
search-android-classes`` once JADX is configured for REA.

The APK and REA's evidence stay outside the repository; only the Markdown goes in.

    npm install --global rea-agents          # REA 6.10.1; Apktool 2.12 on PATH (java -jar apktool.jar)
    python tools/app_scan.py ../apks/base.apk --app "Organic Maps" \
        --evidence-dir ../apks/evidence --out docs/app-analizzate/organic-maps-apk.md

Not a server dependency.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
A = "{http://schemas.android.com/apk/res/android}"

LOCATION_PERMS = ("ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "ACCESS_BACKGROUND_LOCATION",
                  "FOREGROUND_SERVICE", "FOREGROUND_SERVICE_LOCATION", "WAKE_LOCK", "POST_NOTIFICATIONS",
                  "REQUEST_IGNORE_BATTERY_OPTIMIZATIONS")
# Topic -> words looked for in string resources (case-insensitive).
TOPICS: Dict[str, Tuple[str, ...]] = {
    "semafori": ("traffic light", "traffic signal", "ampel", "semaforo", "feu", "green wave", "grüne welle",
                 "onda verde", "spat", "signal phase", "countdown"),
    "voce": ("voice", "tts", "text-to-speech", "speech", "announce", "sprach", "ansage", "voce", "vocal"),
    "auto": ("android auto", "car screen", "carplay"),
    "posizione": ("background location", "location in the background", "hintergrund", "background"),
}
# File-list markers of frameworks and libraries (entry name pattern -> label).
MARKERS: Sequence[Tuple[str, str]] = (
    (r"(^|/)libflutter\.so$", "Flutter (motore)"),
    (r"(^|/)libapp\.so$", "Flutter (codice Dart AOT)"),
    (r"(^|/)libreactnativejni\.so$|(^|/)libhermes\.so$", "React Native"),
    (r"(^|/)libunity\.so$", "Unity"),
    (r"(^|/)libmonodroid\.so$|(^|/)libxamarin", "Xamarin / .NET"),
    (r"(^|/)libmapbox|mapbox", "Mapbox"),
    (r"(^|/)libgmm|com/google/android/gms/maps", "Google Maps SDK"),
    (r"paho|mqtt", "MQTT"),
    (r"(^|/)firebase-[^/]*\.properties$", "Firebase"),
    (r"(^|/)play-services-location[^/]*\.properties$", "Google Play services location (fused)"),
    (r"(^|/)androidx\.car\.app[^/]*\.version$", "androidx.car.app (Android Auto)"),
    (r"(^|/)okhttp3?/|okhttp", "OkHttp"),
)


def _inside(path: str, folder: str) -> bool:
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([path, folder]) == folder


def run_rea(args: List[str], rea: str = "rea") -> dict:
    exe = shutil.which(rea)
    if exe is None:
        raise SystemExit("rea not found: npm install --global rea-agents")
    proc = subprocess.run([exe] + args + ["--json"], capture_output=True, text=True)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"rea {args[0]}: {proc.stdout[-800:] or proc.stderr[-800:]}")
    if proc.returncode != 0 or "normalized_result" not in out:
        raise SystemExit(f"rea {args[0]}: {out.get('message') or out}")
    return out


# -- reading the evidence ------------------------------------------------------------------

def parse_manifest(xml: str) -> dict:
    """Package, permissions, components and their declarations from the decoded manifest."""
    root = ET.fromstring(xml)
    out = {"package": root.attrib.get("package"), "permissions": [], "features": [], "services": [],
           "receivers": [], "activities_car": [], "meta": [], "queries": []}
    for p in root.iter("uses-permission"):
        out["permissions"].append(p.attrib.get(A + "name", ""))
    for p in root.iter("uses-permission-sdk-23"):
        out["permissions"].append(p.attrib.get(A + "name", ""))
    for f in root.iter("uses-feature"):
        if A + "name" in f.attrib:
            out["features"].append((f.attrib[A + "name"], f.attrib.get(A + "required", "true")))
    app = root.find("application")
    if app is None:
        return out
    for m in app.findall("meta-data"):
        out["meta"].append((m.attrib.get(A + "name", ""), m.attrib.get(A + "value") or m.attrib.get(A + "resource", "")))
    for kind in ("service", "receiver", "activity", "activity-alias"):
        for c in app.findall(kind):
            actions = [a.attrib.get(A + "name", "") for a in c.iter("action")]
            cats = [x.attrib.get(A + "name", "") for x in c.iter("category")]
            entry = {"name": c.attrib.get(A + "name", ""), "exported": c.attrib.get(A + "exported"),
                     "foreground": c.attrib.get(A + "foregroundServiceType"), "actions": actions,
                     "categories": cats, "permission": c.attrib.get(A + "permission")}
            if kind == "service":
                out["services"].append(entry)
            elif kind == "receiver":
                out["receivers"].append(entry)
            elif any("car" in x.lower() for x in actions + cats):
                out["activities_car"].append(entry)
    for q in root.iter("queries"):
        for i in q.iter("intent"):
            out["queries"] += [a.attrib.get(A + "name", "") for a in i.iter("action")]
    return out


def short(name: str) -> str:
    return name.rsplit(".", 1)[-1] if name.startswith("android.permission.") else name


def android_auto(m: dict) -> List[Tuple[str, str]]:
    rows = []
    for s in m["services"]:
        if "androidx.car.app.CarAppService" in s["actions"]:
            cats = ", ".join(c.replace("androidx.car.app.category.", "") for c in s["categories"]
                             if c.startswith("androidx.car.app.category")) or "–"
            rows.append((f"`CarAppService` `{s['name']}`, categoria {cats}", "manifest, `<service>`"))
        if "android.media.browse.MediaBrowserService" in s["actions"]:
            rows.append((f"servizio media `{s['name']}` (Android Auto per l'audio)", "manifest, `<service>`"))
    for name, value in m["meta"]:
        if name in ("com.google.android.gms.car.application", "androidx.car.app.minCarApiLevel",
                    "com.google.android.gms.car.notification.SmallIcon"):
            rows.append((f"`{name}` = `{value}`", "manifest, `<meta-data>`"))
    for p in m["permissions"]:
        if p.startswith("androidx.car.app.") or p.startswith("com.google.android.gms.permission.CAR"):
            rows.append((f"permesso `{p}`", "manifest, `<uses-permission>`"))
    return rows


def markers(apk_paths: Iterable[str]) -> List[Tuple[str, str]]:
    found: Dict[str, str] = {}
    for path in apk_paths:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                for pattern, label in MARKERS:
                    if label not in found and re.search(pattern, n, re.IGNORECASE):
                        found[label] = n
    return sorted(found.items())


def topic_strings(strings: Sequence[dict], limit: int = 12) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {}
    for topic, words in TOPICS.items():
        hits = []
        for s in strings:
            value = str(s.get("value", ""))
            low = value.lower()
            if any(w in low for w in words):
                hits.append((s.get("name", ""), value if len(value) <= 140 else value[:137] + "…"))
        out[topic] = hits[:limit]
    return out


# -- writing the sheet ---------------------------------------------------------------------

def _table(rows: Sequence[Tuple[str, str, str]]) -> List[str]:
    lines = ["| Cosa | Trovato | Dove |", "|---|---|---|"]
    for what, found, where in rows:
        lines.append(f"| {what} | {found.replace('|', '/')} | {where} |")
    return lines


def sheet(app: str, decode: dict, signature: Optional[dict], apk_paths: Sequence[str], rea_version: str,
          apktool_version: str, source: str, today: str) -> str:
    n = decode["normalized_result"]
    meta, m = n["metadata"], parse_manifest(n["manifest"])
    perms = [short(p) for p in m["permissions"]]
    loc = [p for p in perms if p in LOCATION_PERMS]
    fg = [(s["name"], s["foreground"]) for s in m["services"] if s["foreground"]]
    cert = "–"
    if signature:
        sch = signature["normalized_result"].get("schemes", {})
        for scheme in ("v3", "v2", "v1"):
            for signer in (sch.get(scheme) or {}).get("signers", []) or []:
                c = signer.get("certificate") or {}
                if c.get("sha256_fingerprint"):
                    cert = f"`{c['sha256_fingerprint']}` (schema {scheme})"
                    break
            if cert != "–":
                break
    strings = topic_strings(n.get("strings") or [])
    libs = markers(apk_paths)
    aa = android_auto(m)

    L = [f"# {app} – scheda dall'APK", "",
         f"- Pacchetto: `{meta.get('package_name')}`, versione `{meta.get('version_name')}` "
         f"(`{meta.get('version_code')}`), SDK minimo {meta.get('min_sdk_version')}, destinazione "
         f"{meta.get('target_sdk_version')}",
         f"- APK sha256: `{decode['subject']['identity']['sha256']}`"
         + (f" (più {len(apk_paths) - 1} split)" if len(apk_paths) > 1 else ""),
         f"- Firma: {cert}",
         f"- Data dell'analisi: {today}; strumenti: REA {rea_version} (`decode-android-resources`, "
         f"`inspect-apk-signature`), Apktool {apktool_version}; `tools/app_scan.py`",
         f"- Fonte dell'APK: {source}; APK e prove REA fuori dalla repo", "",
         "Questa parte è generata dalle dichiarazioni dell'APK (manifest, risorse, elenco dei file): "
         "dice che cosa l'app può fare e con quali librerie, non come lo usa.", "",
         "## Dati dei semafori (punti 2 e 12)", ""]
    rows = [("Librerie e motori", ", ".join(lbl for lbl, _ in libs) or "nessuno riconosciuto",
             "elenco dei file: " + ", ".join(f"`{p}`" for _, p in libs[:4]) if libs else "–")]
    for k, v in strings["semafori"]:
        rows.append(("Stringa", v, f"`@string/{k}`"))
    L += _table(rows) + ["", "## Annunci a voce (punto 27)", ""]
    rows = [("Servizi TTS interrogati", ", ".join(q for q in m["queries"] if "TTS" in q.upper()) or "–",
             "manifest, `<queries>`")]
    rows += [("Stringa", v, f"`@string/{k}`") for k, v in strings["voce"]]
    L += _table(rows) + ["", "## Posizione in background (punto 17)", ""]
    rows = [("Permessi di posizione e servizio", ", ".join(f"`{p}`" for p in loc) or "nessuno",
             "manifest, `<uses-permission>`")]
    rows += [("Servizio in primo piano", f"`{name}` ({kind})", "manifest, `<service>`") for name, kind in fg]
    rows += [("Stringa", v, f"`@string/{k}`") for k, v in strings["posizione"][:6]]
    L += _table(rows) + ["", "## Android Auto (punto 33)", ""]
    if aa:
        L += _table([("Dichiarazione", what, where) for what, where in aa])
    else:
        L.append("Nessuna dichiarazione Android Auto nel manifest (`CarAppService`, "
                 "`com.google.android.gms.car.application`).")
    L += ["", "## Tutti i permessi", "", ", ".join(f"`{p}`" for p in sorted(set(perms))) or "nessuno", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apks", nargs="+", help="base APK first, then any split APKs")
    ap.add_argument("--app", required=True, help="name of the app for the sheet title")
    ap.add_argument("--evidence-dir", required=True, help="where REA's evidence goes, outside the repository")
    ap.add_argument("--out", help="Markdown sheet to write (default: print)")
    ap.add_argument("--source", default="APK fornito dall'utente",
                    help="where the APK comes from (own phone via adb, publisher download)")
    ap.add_argument("--rea", default="rea")
    args = ap.parse_args(argv)

    for p in list(args.apks) + [args.evidence_dir]:
        if _inside(p, REPO):
            raise SystemExit(f"{p}: APKs and REA evidence stay outside the repository")
    os.makedirs(args.evidence_dir, exist_ok=True)
    base = os.path.abspath(args.apks[0])
    decode = run_rea(["decode-android-resources", base, "--string-limit", "20000",
                      "--max-total-strings", "20000"], args.rea)
    try:
        signature = run_rea(["inspect-apk-signature", base], args.rea)
    except SystemExit as exc:
        print(f"signature: {exc}", file=sys.stderr)
        signature = None
    stamp = decode["subject"]["identity"]["sha256"][:12]
    with open(os.path.join(args.evidence_dir, f"{stamp}.decode.json"), "w") as f:
        json.dump(decode, f)
    if signature:
        with open(os.path.join(args.evidence_dir, f"{stamp}.signature.json"), "w") as f:
            json.dump(signature, f)
    rea_version = subprocess.run([shutil.which(args.rea), "--version"], capture_output=True,
                                 text=True).stdout.strip().splitlines()[-1]
    apktool = decode["normalized_result"]["client"].get("apktool_version", "?")
    text = sheet(args.app, decode, signature, [os.path.abspath(p) for p in args.apks], rea_version, apktool,
                 args.source, _dt.date.today().isoformat())
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"sheet: {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
