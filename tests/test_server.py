import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from drivenow.network import demo_city
from drivenow.server import Runner, make_handler
from drivenow.simulation import SimConfig, Simulation


def test_server_serves_network_page_and_stream():
    sim = Simulation(demo_city(), SimConfig(seed=2))
    runner = Runner(sim, speed=10)
    runner.start()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runner))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        net = json.load(urllib.request.urlopen(base + "/api/network"))
        assert net["nodes"] and net["edges"]
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "DriveNow" in page

        time.sleep(1.5)
        resp = urllib.request.urlopen(base + "/api/stream", timeout=5)
        events = set()
        deadline = time.time() + 5
        while time.time() < deadline and not {"frame", "field"} <= events:
            line = resp.readline().decode().strip()
            if line.startswith("event:"):
                events.add(line.split(":", 1)[1].strip())
        assert {"frame", "field"} <= events

        req = urllib.request.Request(base + "/api/settings", data=b'{"penetration": 0.8, "speed": 2}',
                                     headers={"Content-Type": "application/json"}, method="POST")
        assert urllib.request.urlopen(req).status == 204
        assert sim.cfg.penetration == 0.8 and runner.speed == 2
    finally:
        srv.shutdown()


def test_speed_field_covers_every_controlled_approach():
    sim = Simulation(demo_city(), SimConfig(seed=2))
    sim.run(60)
    field = sim.advisor.speed_field(sim.t, sim.occupancy())
    for edge in sim.net.edges.values():
        node = sim.net.nodes[edge.to_node]
        if node.kind == "signal" or node.kind == "roundabout":
            assert edge.id in field
    for rows in field.values():
        for s, lo, hi in rows:
            if lo is not None:
                assert lo <= hi
