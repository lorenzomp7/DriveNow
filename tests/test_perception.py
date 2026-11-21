import math
import random

from drivenow.autopilot import AutopilotConfig, control
from drivenow.network import demo_city
from drivenow.perception import Perception, Seen
from drivenow.simulation import SimConfig, Simulation
from test_simulation import one_light


def follow(suite, weather="clear", gap0=60.0, v_lead=10.0, v=14.0, seconds=12.0, ghosts=0.0, seed=1):
    """The car closes on a slower car; returns the perceived minus true gaps (after 2 s)."""
    p = Perception(random.Random(seed), suite, weather, ghost_per_km=ghosts)
    errs, t, gap = [], 0.0, gap0
    while t < seconds:
        p.sense(t, v * t, v, (gap, v_lead, "lead"), None)
        seen = p.leader()
        if t > 2.0:
            errs.append(None if seen is None else seen.gap - gap)
        gap += (v_lead - v) * 0.2
        t += 0.2
    return errs


def rmse(errs):
    e = [x for x in errs if x is not None]
    return math.sqrt(sum(x * x for x in e) / len(e))


def test_radar_measures_the_gap_better_than_a_camera():
    cam = follow("camera")
    fused = follow("camera+radar")
    assert all(x is not None for x in fused)
    assert rmse(fused) < 0.5 < rmse(cam) < 4.0


def test_fog_shortens_the_camera_but_not_the_radar():
    # 140 m ahead: beyond the camera in fog, within the radar.
    far = follow("camera", "fog", gap0=140, v_lead=14.0, seconds=6)
    assert all(x is None for x in far)
    far_r = follow("camera+radar", "fog", gap0=140, v_lead=14.0, seconds=6)
    assert sum(x is not None for x in far_r) > 0.9 * len(far_r)


def test_radar_ghosts_are_not_used_but_a_stopped_car_is():
    # Many ghosts, nothing real ahead: the fused view never reports an object.
    p = Perception(random.Random(3), "camera+radar", ghost_per_km=20.0)
    t = 0.0
    while t < 60:
        p.sense(t, 12.0 * t, 12.0, None, None)
        assert p.leader() is None or p.leader().truth != "ghost"
        t += 0.2
    # A car that was moving and then stopped is kept even by the radar alone.
    p = Perception(random.Random(4), "radar")
    gap, v_lead, t = 50.0, 10.0, 0.0
    while t < 20:
        p.sense(t, 0.0, 0.0, (gap, v_lead, "lead"), None)
        v_lead = max(0.0, v_lead - 1.0 * 0.2)
        gap += v_lead * 0.2
        t += 0.2
    assert p.leader() is not None and p.leader().truth == "lead"


def test_radar_alone_misses_a_car_already_standing_still():
    p = Perception(random.Random(5), "radar")
    seen_any = False
    for k in range(50):
        t = k * 0.2
        p.sense(t, 12.0 * t, 12.0, (100.0 - 12.0 * t, 0.0, "parked"), None)
        seen_any |= p.leader() is not None
    assert not seen_any
    p = Perception(random.Random(5), "camera+radar")
    for k in range(30):
        t = k * 0.2
        p.sense(t, 12.0 * t, 12.0, (100.0 - 12.0 * t, 0.0, "parked"), None)
    assert p.leader() is not None and p.leader().truth == "parked"


def test_the_camera_reads_the_light_and_a_single_misreading_does_not_count():
    p = Perception(random.Random(6), "camera")
    p.sense(0.0, 0.0, 10.0, None, (200.0, "r", "J"))
    assert p.light() is None  # too far
    for k in range(1, 6):
        p.sense(k * 0.2, 0.0, 10.0, None, (60.0, "r", "J"))
    assert p.light() == "r"


def test_emergency_braking_and_speed_within_sight():
    cfg = AutopilotConfig()
    a, why = control(14.0, 14.0, Seen(15.0, -14.0, 0.3, 0.1, ("radar",)), None, None, 0.7, 1.3, math.inf, cfg)
    assert why == "aeb" and a == -cfg.aeb_decel
    # A noisy closing speed is not enough for emergency braking.
    a, why = control(14.0, 14.0, Seen(30.0, -10.0, 3.0, 8.0, ("camera",)), None, None, 0.7, 1.3, math.inf, cfg)
    assert why != "aeb"
    # Seeing only 30 m ahead, it slows down to what it can stop from within 30 m.
    a, why = control(14.0, 14.0, None, None, None, 0.7, 1.3, 30.0, cfg)
    assert a < 0 and why == "sight"


def test_autopilot_reaches_the_green_without_stopping():
    net = one_light(40)
    sim = Simulation(net, SimConfig(demand=0, autopilot=True, sensors="camera+radar"))
    from drivenow.perception import Perception as P
    from drivenow.simulation import Vehicle
    veh = Vehicle(0, ["a", "b"], True, 0.0, v=50 / 3.6)
    veh.perception = P(random.Random(1), "camera+radar")
    sim.vehicles.append(veh)
    sim.run(120)
    assert not sim.vehicles
    assert veh.stops == 0 and veh.red_runs == 0 and veh.brake_events == 0


def test_autopilot_without_timings_stops_at_the_red_it_sees():
    net = one_light(40)
    sim = Simulation(net, SimConfig(demand=0, autopilot=True, sensors="camera", light_timing=False))
    from drivenow.simulation import Vehicle
    veh = Vehicle(0, ["a", "b"], True, 0.0, v=50 / 3.6)
    veh.perception = Perception(random.Random(2), "camera")
    sim.vehicles.append(veh)
    sim.run(120)
    assert not sim.vehicles
    assert veh.red_runs == 0 and veh.stops == 1


def test_self_driving_town_is_safe_with_double_parking():
    sim = Simulation(demo_city(), SimConfig(penetration=1.0, seed=2, autopilot=True, sensors="camera+radar",
                                            double_parking=30))
    sim.run(600)
    s = sim.stats[True].summary()
    assert s["trips"] > 100
    assert s["collisions"] == 0 and s["red_runs"] == 0
    assert s["gap_rmse_m"] < 1.0 and s["missed_pct"] < 5


def test_pedestrians_are_seen_closer_at_night():
    seen = {}
    for weather in ("clear", "night"):
        p = Perception(random.Random(7), "camera", weather)
        for k in range(10):
            p.see_pedestrians(k * 0.2, [("c", 60.0, "waiting")])
        seen[weather] = p.pedestrian("c")
    assert seen == {"clear": "waiting", "night": None}
    # A radar alone does not make a pedestrian: a person is a weak, slow radar target.
    p = Perception(random.Random(7), "radar")
    for k in range(10):
        p.see_pedestrians(k * 0.2, [("c", 20.0, "crossing")])
    assert p.pedestrian("c") is None


def test_side_sensors_see_the_main_road():
    p = Perception(random.Random(8), "camera+radar", "fog")
    p.see_cross(0.0, [(50.0, 12.0, "x")])   # beyond the camera in fog, within the radar
    cars = p.cross(0.0)
    assert len(cars) == 1 and abs(cars[0][0] - 50.0) < 3 and cars[0][2] == 0.5
    # Carried forward at its speed, more uncertain, then forgotten after a second.
    later = p.cross(0.5)
    assert later[0][0] < cars[0][0] and later[0][2] > cars[0][2]
    p.see_cross(1.5, [])
    assert p.cross(1.5) == []


def test_self_driving_car_stops_for_a_pedestrian_and_goes_on_after():
    from drivenow.simulation import Vehicle
    net = one_light(0.1)
    sim = Simulation(net, SimConfig(demand=0, autopilot=True, sensors="camera+radar", pedestrians=1e-9))
    cross = next(c for c in sim.crossings if c.edge == "a")
    cross.state, cross.until = "crossing", 30.0
    veh = Vehicle(0, ["a", "b"], True, 0.0, v=50 / 3.6)
    veh.perception = Perception(random.Random(3), "camera+radar")
    sim.vehicles.append(veh)
    sim.run(25)
    assert veh.edge == "a" and veh.pos < cross.pos and veh.v < 0.5
    sim.run(60)
    assert not sim.vehicles and veh.pedestrian_hits == 0
