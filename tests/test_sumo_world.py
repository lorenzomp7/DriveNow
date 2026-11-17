"""SUMO bridge tests. Skipped when SUMO is not installed."""

import os
import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("traci")
pytest.importorskip("sumolib")

from drivenow.network import SIGNAL  # noqa: E402

HERE = os.path.dirname(__file__)
NET = os.path.join(HERE, "..", "data", "sumo", "2_2_intersections.net.xml")


@pytest.fixture(scope="module")
def world():
    try:
        from drivenow.sumo_world import SumoWorld

        w = SumoWorld(NET, demand=300, penetration=0.5, seed=3, label="drivenow_test")
    except RuntimeError as exc:
        pytest.skip(str(exc))
    yield w
    w.close()


def _links(node_id):
    root = ET.parse(NET).getroot()
    return {int(c.attrib["linkIndex"]): c.attrib["from"] for c in root.iter("connection") if c.attrib.get("tl") == node_id}


def test_sumo_lights_match_the_forecast(world):
    signals = [n for n in world.net.nodes.values() if n.kind == SIGNAL]
    links = {n.id: _links(n.id) for n in signals}
    checked = 0
    for _ in range(int(240 / world.dt)):
        world.step()
        for n in signals:
            state = world.sumo_state(n.id)
            # Skip the instant of a switch: SUMO and the plan may sit on either side.
            _, left = n.plan.locate(world.t)
            if left < world.dt * 1.5 or left > n.plan.phases[n.plan.locate(world.t)[0]].duration - world.dt * 1.5:
                continue
            for idx, frm in links[n.id].items():
                expected = n.plan.state(world.t, n.group_of[frm])
                got = {"G": "G", "g": "G", "y": "y"}.get(state[idx], "r")
                assert got == expected, (n.id, world.t, idx)
                checked += 1
    assert checked > 1000


def test_sumo_vehicles_get_advice(world):
    for _ in range(int(120 / world.dt)):
        world.step()
    snap = world.snapshot()
    assert snap["vehicles"]
    kinds = {row[7] for row in snap["vehicles"]}
    assert kinds - {0}, "some vehicle should be approaching a light"
