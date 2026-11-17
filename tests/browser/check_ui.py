"""Browser smoke checks against a real demo server; no AI/API key required."""
import re
import os
import sys
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivenow.network import demo_city
from drivenow.simulation import Simulation, SimConfig
from drivenow.server import Runner, make_handler
from playwright.sync_api import sync_playwright, expect


def main():
    runner = Runner(Simulation(demo_city(), SimConfig(seed=1, penetration=1.0, demand=600)), speed=5)
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(runner))
    server.daemon_threads = True
    runner.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("DRIVENOW_CHROMIUM"))
            try:
                for width, height in [(1440, 900), (390, 844)]:
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='domcontentloaded')
                    expect(page.locator('#net-name')).not_to_have_text('…')
                    expect(page.locator('#live')).to_have_class(re.compile(r'\bon\b'))
                    expect(page.locator('#clock')).not_to_have_text('00:00', timeout=15000)
                    expect(page.locator('#veh-tag')).to_have_text('Segue DriveNow', timeout=15000)
                    expect(page.locator('#target')).not_to_have_text('—')
                    box = page.locator('#map').bounding_box()
                    assert box and box['width'] > 100 and box['height'] > 100
                    page.locator('#btn-fit').click()
                    expect(page.locator('#btn-follow')).to_have_attribute('aria-pressed', 'false')
                    page.locator('#btn-follow').click()
                    expect(page.locator('#btn-follow')).to_have_attribute('aria-pressed', 'true')
                    before = page.evaluate('selected')
                    page.locator('#btn-next').click()
                    page.wait_for_function('(old) => selected !== old', arg=before)
                    with page.expect_response(lambda r: '/api/settings' in r.url and r.request.method == 'POST') as response:
                        page.locator('[data-speed="2"]').click()
                    assert response.value.ok
                    expect(page.locator('[data-speed="2"]')).to_have_class('on')
                    for selector, value, payload in [('#pen', '75', {'penetration': .75}), ('#dem', '400', {'demand': 400})]:
                        with page.expect_response(lambda r: '/api/settings' in r.url and r.request.method == 'POST' and r.request.post_data_json == payload) as response:
                            page.locator(selector).fill(value)
                        assert response.value.ok
                        assert response.value.request.post_data_json == payload
                    with runner.lock:
                        assert runner.world.cfg.penetration == .75
                        assert runner.world.cfg.demand == 400
                    page.locator('#map').hover()
                    zoom = page.evaluate('view.s')
                    page.mouse.wheel(0, -200)
                    page.wait_for_function('(old) => view.s !== old', arg=zoom)
                    assert not errors, errors
                    page.close()
                    print(f'PASS: live map, vehicle, controls, zoom ({width}x{height})')
            finally:
                browser.close()
    finally:
        runner._stop = True
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
