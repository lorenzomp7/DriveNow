"""Run the real Playwriter MCP UI checks against a local disposable demo."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drivenow.network import demo_city
from drivenow.server import Runner, make_handler
from drivenow.simulation import Simulation, SimConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mcp-config', action='store_true', help='Print client configuration; do not run UI tests')
    args = parser.parse_args()
    node = shutil.which('node')
    cli = ROOT / 'tools/playwriter/node_modules/playwriter/bin.js'
    if not node or not cli.is_file():
        parser.error('Install Node 22+ and run npm ci --prefix tools/playwriter')
    if args.mcp_config:
        print(json.dumps({'mcpServers': {'playwriter': {'command': node, 'args': [str(cli)],
                          'env': {'PLAYWRITER_TELEMETRY': '0', 'DO_NOT_TRACK': '1'}}}}, indent=2))
        return 0
    chrome = os.environ.get('DRIVENOW_CHROMIUM') or next((shutil.which(name) for name in
             ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'] if shutil.which(name)), None)
    if not chrome:
        parser.error('Set DRIVENOW_CHROMIUM to a Chrome/Chromium executable')
    runner = Runner(Simulation(demo_city(), SimConfig(seed=1, penetration=1, demand=600)), speed=5)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(runner))
    server.daemon_threads = True
    runner.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {**os.environ, 'DRIVENOW_CHROMIUM': chrome, 'PLAYWRITER_TELEMETRY':'0', 'DO_NOT_TRACK':'1'}
        return subprocess.run([node, str(ROOT / 'tools/playwriter/check.mjs'),
                               f'http://127.0.0.1:{server.server_port}'], env=env, cwd=ROOT, timeout=240).returncode
    finally:
        runner._stop = True
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
