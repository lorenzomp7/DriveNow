"""Check the live demo HTTP endpoints without a browser or external services."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drivenow.network import demo_city
from drivenow.server import Runner, make_handler
from drivenow.simulation import SimConfig, Simulation

runner = Runner(Simulation(demo_city(), SimConfig(seed=1)), speed=1)
runner.start()
server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(runner))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    base = f'http://127.0.0.1:{server.server_port}'
    with urllib.request.urlopen(base + '/', timeout=10) as response:
        assert b'DriveNow' in response.read()
    with urllib.request.urlopen(base + '/api/network', timeout=10) as response:
        data = json.load(response)
        assert data['nodes'] and data['edges']
    print('DRIVENOW_CONTAINER_DEMO_OK')
finally:
    server.shutdown()
    server.server_close()
