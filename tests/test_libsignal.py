from types import SimpleNamespace

import pytest

from drivenow.libsignal import LibSignalAdvisor
from drivenow.network import demo_city


class Vehicles:
    def __init__(self, route):
        self.route = route
        self.commands = []
        self.road = route[0]

    def getIDList(self): return ['car']
    def getRoadID(self, vid): return self.road
    def getRoute(self, vid): return self.route
    def getRouteIndex(self, vid): return 0
    def getLanePosition(self, vid): return 20.0
    def getSpeed(self, vid): return 10.0
    def getAllowedSpeed(self, vid): return 8.0
    def setSpeed(self, vid, speed): self.commands.append((vid, speed))


def world_and_bridge(**kwargs):
    net = demo_city()
    edge = next(e for e in net.edges.values() if net.nodes[e.to_node].kind == 'signal')
    vehicles = Vehicles([edge.id] + net.path_to_border(edge.id))
    world = SimpleNamespace(eng=SimpleNamespace(vehicle=vehicles,
                            simulation=SimpleNamespace(getTime=lambda: 10.0)))
    return vehicles, LibSignalAdvisor(world, network=net, penetration=1, **kwargs)


def test_unknown_adaptive_signals_never_use_network_fixed_plan():
    vehicles, bridge = world_and_bridge()
    # Verify the source presented to the advisor, even though the net has a plan.
    edge = vehicles.route[0]
    assert bridge.advisor._signal(edge, vehicles.route[1], 10) is None
    result = bridge.step()
    assert 'car' in result
    assert vehicles.commands == []  # read-only by default


def test_explicit_windows_are_passed_with_current_time():
    observed = []
    def windows(edge, next_edge, t):
        observed.append((edge, next_edge, t))
        return [(0.0, 60.0)], 'committed'
    vehicles, bridge = world_and_bridge(windows_fn=windows)
    bridge.step()
    assert observed and all(row[2] == 10.0 for row in observed)


def test_applying_advice_respects_allowed_speed_and_release():
    vehicles, bridge = world_and_bridge()
    bridge.advisor.advise = lambda *a: (SimpleNamespace(target=15.0, kind='green'), None)
    bridge.step(apply=True)
    assert vehicles.commands == [('car', 8.0)]
    bridge.release()
    assert vehicles.commands[-1] == ('car', -1)


def test_missing_advice_releases_previous_speed_override():
    vehicles, bridge = world_and_bridge()
    bridge.advisor.advise = lambda *a: (SimpleNamespace(target=5.0, kind='green'), None)
    bridge.step(apply=True)
    bridge.world.eng.simulation.getTime = lambda: 11.0
    bridge.advisor.advise = lambda *a: (SimpleNamespace(target=None, kind='free'), None)
    bridge.step(apply=True)
    assert vehicles.commands[-1] == ('car', -1)


def test_internal_junctions_release_control_and_zero_penetration_never_drives():
    vehicles, bridge = world_and_bridge()
    vehicles.road = ':junction_0'
    assert bridge.step(apply=True) == {}
    assert vehicles.commands == []
    bridge.penetration = 0
    bridge.world.eng.simulation.getTime = lambda: 11.0
    vehicles.road = vehicles.route[0]
    bridge.step(apply=True)
    assert vehicles.commands == []


def test_invalid_penetration():
    with pytest.raises(ValueError, match='penetration'):
        LibSignalAdvisor(SimpleNamespace(), penetration=2)


def test_duplicate_tick_is_rejected_and_coasting_is_gradual():
    vehicles, bridge = world_and_bridge()
    vehicles.getAllowedSpeed = lambda vid: 15.0
    bridge.advisor.advise = lambda *a: (SimpleNamespace(target=2.0, kind='green'), None)
    bridge.step(apply=True)
    assert vehicles.commands[-1][1] == pytest.approx(10.0 - bridge.advisor.profile.coast_decel)
    with pytest.raises(ValueError, match='once after each'):
        bridge.step(apply=True)
    vehicles.road = ':junction_0'
    bridge.world.eng.simulation.getTime = lambda: 11.0
    bridge.step(apply=True)
    assert vehicles.commands[-1] == ('car', -1)


def test_observed_source_learns_only_past_protected_greens():
    from drivenow.libsignal import ObservedSignalSource
    light = SimpleNamespace(getIDList=lambda:['tls'],
        getControlledLinks=lambda _: [(('a_0','b_0',''),)],
        getRedYellowGreenState=lambda _: 'G')
    engine = SimpleNamespace(trafficlight=light, lane=SimpleNamespace(getEdgeID=lambda lane: lane[:-2]))
    source = ObservedSignalSource(engine)
    source.observe(0)
    assert source('a','b',0) is None  # not enough past cycles
    for t in range(1, 721):
        light.getRedYellowGreenState = lambda _, t=t: 'G' if t % 60 < 25 else 'r'
        source.observe(t)
    windows, label = source('a','b',720)
    assert windows and label.startswith('learned:')
    assert source('a','b',721) is None  # do not reuse a stale forecast at a new time
    for t in range(721, 750):
        light.getRedYellowGreenState = lambda _: 'y'
        source.observe(t)
    got, _ = source('a','b',749)
    assert not any(a <= 0 < b for a,b in got)  # yellow is never observed as green
