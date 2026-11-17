"""Live map server: runs a world in real time and streams it to the browser.

    python -m drivenow.server                         # demo town, built-in simulation
    python -m drivenow.server --net data/sumo/2_2_intersections.net.xml
    python -m drivenow.server --sumo --net data/sumo/3_3_intersections.net.xml

Then open http://localhost:8000. Only the Python standard library is needed
(plus SUMO and TraCI for ``--sumo``).

Endpoints:
  GET  /api/network   network geometry, sent once
  GET  /api/stream    Server-Sent Events: vehicles and lights 5 times a
                      second, the speed map once a second
  POST /api/settings  {"speed": 2, "penetration": 0.5, "demand": 300}
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .network import demo_city, load_sumo_net
from .simulation import SimConfig, Simulation, static_network

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class Runner:
    """Advances a world in (scaled) real time on a background thread."""

    def __init__(self, world, speed: float = 1.0) -> None:
        self.world = world
        self.speed = speed
        self.lock = threading.Lock()
        self.frame: Optional[str] = None
        self.field: Optional[str] = None
        self.version = 0
        self._stop = False
        self.static = json.dumps(static_network(world.net))

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        dt = getattr(self.world, "dt", None) or self.world.cfg.dt
        last = time.monotonic()
        budget = 0.0
        last_field = -10.0
        last_frame = -10.0
        while not self._stop:
            now = time.monotonic()
            budget += (now - last) * self.speed
            last = now
            steps = 0
            with self.lock:
                while budget >= dt and steps < 200:
                    self.world.step()
                    budget -= dt
                    steps += 1
                if steps and now - last_frame >= 0.2:
                    last_frame = now
                    snap = self.world.snapshot()
                    snap["speed"] = self.speed
                    snap["penetration"] = self._penetration()
                    snap["demand"] = self._demand()
                    self.frame = json.dumps(snap, separators=(",", ":"))
                    if now - last_field >= 1.0:
                        last_field = now
                        fld = self.world.advisor.speed_field(self.world.t, self.world.occupancy())
                        self.field = json.dumps({"t": round(self.world.t, 1), "field": fld}, separators=(",", ":"))
                    self.version += 1
            if budget > dt * 400:  # fell far behind: do not try to catch up
                budget = 0.0
            time.sleep(0.01)

    def _penetration(self) -> float:
        w = self.world
        return w.cfg.penetration if hasattr(w, "cfg") else w.penetration

    def _demand(self) -> Optional[float]:
        w = self.world
        return w.cfg.demand if hasattr(w, "cfg") else None

    def apply(self, settings: dict) -> None:
        with self.lock:
            if "speed" in settings:
                self.speed = min(max(float(settings["speed"]), 0.0), 20.0)
            w = self.world
            if "penetration" in settings:
                p = min(max(float(settings["penetration"]), 0.0), 1.0)
                if hasattr(w, "cfg"):
                    w.cfg.penetration = p
                else:
                    w.penetration = p
            if "demand" in settings and hasattr(w, "cfg"):
                w.cfg.demand = min(max(float(settings["demand"]), 0.0), 900.0)


def make_handler(runner: Runner):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/network":
                return self._send(200, runner.static.encode(), "application/json")
            if path == "/api/stream":
                return self._stream()
            if path == "/":
                path = "/index.html"
            file = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
            if not file.startswith(WEB_DIR) or not os.path.isfile(file):
                return self._send(404, b"not found", "text/plain")
            ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                     ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}.get(os.path.splitext(file)[1],
                                                                                    "application/octet-stream")
            with open(file, "rb") as f:
                self._send(200, f.read(), ctype)

        def do_POST(self) -> None:
            if self.path != "/api/settings":
                return self._send(404, b"not found", "text/plain")
            n = int(self.headers.get("Content-Length", "0") or 0)
            try:
                runner.apply(json.loads(self.rfile.read(n) or b"{}"))
            except (ValueError, TypeError):
                return self._send(400, b"bad settings", "text/plain")
            self._send(204, b"", "text/plain")

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            sent_field = None
            try:
                while True:
                    if runner.version != seen and runner.frame:
                        seen = runner.version
                        msg = f"event: frame\ndata: {runner.frame}\n\n"
                        if runner.field is not sent_field and runner.field:
                            sent_field = runner.field
                            msg += f"event: field\ndata: {runner.field}\n\n"
                        self.wfile.write(msg.encode())
                        self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def build_world(args):
    if args.sumo:
        from .sumo_world import SumoWorld

        if not args.net:
            raise SystemExit("--sumo needs --net path/to/file.net.xml")
        return SumoWorld(args.net, demand=args.demand, penetration=args.penetration, seed=args.seed,
                         duration=args.duration, gui=args.gui)
    net = load_sumo_net(args.net) if args.net else demo_city()
    return Simulation(net, SimConfig(demand=args.demand, penetration=args.penetration, seed=args.seed))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="DriveNow live speed map")
    ap.add_argument("--net", help="SUMO .net.xml network (default: the demo town)")
    ap.add_argument("--sumo", action="store_true", help="run the traffic in SUMO through TraCI")
    ap.add_argument("--gui", action="store_true", help="with --sumo, open sumo-gui as well")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed, 1 = real time")
    ap.add_argument("--demand", type=float, default=240.0, help="vehicles per hour per entry road")
    ap.add_argument("--penetration", type=float, default=0.5, help="share of DriveNow vehicles, 0-1")
    ap.add_argument("--duration", type=float, default=7200.0, help="with --sumo, seconds of traffic to generate")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    runner = Runner(build_world(args), speed=args.speed)
    runner.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(runner))
    print(f"DriveNow: http://{args.host}:{args.port}  ({runner.world.net.name})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
