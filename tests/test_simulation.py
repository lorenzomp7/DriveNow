from drivenow.network import BORDER, SIGNAL, Edge, Network, Node
from drivenow.signals import Phase, SignalPlan
from drivenow.simulation import SimConfig, Simulation, Vehicle
from drivenow.network import demo_city


def one_light(red_for: float) -> Network:
    """W --400 m--> J --200 m--> E, with J red for ``red_for`` seconds, then green."""
    nodes = {
        "W": Node("W", -400, 0, BORDER, radius=0),
        "J": Node("J", 0, 0, SIGNAL, radius=0),
        "E": Node("E", 200, 0, BORDER, radius=0),
    }
    edges = {
        "a": Edge("a", "W", "J", 400, 50 / 3.6, [(-400, 0), (0, 0)], next_edges=["b"]),
        "b": Edge("b", "J", "E", 200, 50 / 3.6, [(0, 0), (200, 0)]),
    }
    nodes["J"].plan = SignalPlan([Phase(red_for, {"EW": "r"}), Phase(600, {"EW": "G"})])
    nodes["J"].group_of = {"a": "EW"}
    return Network(nodes, edges)


def drive(equipped: bool, red_for: float) -> Vehicle:
    net = one_light(red_for)
    sim = Simulation(net, SimConfig(demand=0))
    veh = Vehicle(0, ["a", "b"], equipped, 0.0, v=50 / 3.6)
    sim.vehicles.append(veh)
    sim.run(120)
    assert not sim.vehicles, "vehicle should have finished"
    return veh


def test_drivenow_driver_does_not_stop_when_a_band_exists():
    # 400 m at 50 km/h takes 29 s; red for 40 s. A slower cruise reaches the green.
    normal = drive(False, red_for=40)
    guided = drive(True, red_for=40)
    assert normal.stops == 1
    assert guided.stops == 0
    assert guided.brake_events == 0
    assert guided.brake_energy < normal.brake_energy / 5


def test_no_change_when_green_is_already_reachable():
    guided = drive(True, red_for=1)
    assert guided.stops == 0 and guided.brake_events == 0


def test_demo_city_runs_and_drivenow_brakes_less():
    totals = {}
    for pen in (0.0, 1.0):
        sim = Simulation(demo_city(), SimConfig(penetration=pen, seed=5))
        sim.run(1200)
        totals[pen] = sim.stats[pen > 0.5].summary()
        snap = sim.snapshot()
        assert snap["vehicles"] and snap["signals"]
    assert totals[1.0]["trips"] > 200 and totals[0.0]["trips"] > 200
    assert totals[1.0]["stops"] < totals[0.0]["stops"] * 0.7
    assert totals[1.0]["brake_energy_kj"] < totals[0.0]["brake_energy_kj"] * 0.6


def test_cars_turning_into_the_same_street_take_turns():
    """W->J and S->J both lead into J->E, green for both: the cars must not end up on top of each other."""
    nodes = {
        "W": Node("W", -300, 0, BORDER, radius=0),
        "S": Node("S", 0, -300, BORDER, radius=0),
        "J": Node("J", 0, 0, SIGNAL, radius=0),
        "E": Node("E", 300, 0, BORDER, radius=0),
    }
    edges = {
        "w": Edge("w", "W", "J", 300, 50 / 3.6, [(-300, 0), (0, 0)], next_edges=["e"]),
        "s": Edge("s", "S", "J", 300, 50 / 3.6, [(0, -300), (0, 0)], next_edges=["e"]),
        "e": Edge("e", "J", "E", 300, 50 / 3.6, [(0, 0), (300, 0)]),
    }
    nodes["J"].plan = SignalPlan([Phase(600, {"A": "G"})])
    nodes["J"].group_of = {"w": "A", "s": "A"}
    sim = Simulation(Network(nodes, edges), SimConfig(demand=0))
    a = Vehicle(0, ["w", "e"], False, 0.0, v=50 / 3.6)
    b = Vehicle(1, ["s", "e"], False, 0.0, pos=1.0, v=50 / 3.6)
    sim.vehicles += [a, b]
    closest = float("inf")
    for _ in range(400):
        sim.step()
        on_e = sorted((v for v in sim.vehicles if v.edge == "e"), key=lambda v: v.pos)
        if len(on_e) == 2:
            closest = min(closest, on_e[1].pos - on_e[0].pos - 4.5)
    assert closest > 1.5
