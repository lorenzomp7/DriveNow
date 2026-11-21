"""A small traffic simulation, so DriveNow runs without installing SUMO.

Single-lane roads, Intelligent Driver Model car following, fixed-time
traffic lights, a roundabout and a give-way junction with simple gap
acceptance.

Every vehicle gets advice; only the *equipped* share follows it. Those
drivers never press the brake pedal to follow the advice: they lift off and
coast. They still brake when the car in front forces them to, like anyone
else. Comparing the two groups shows what the advice is worth: stops,
braking events and energy thrown away in the brakes.

With ``SimConfig.autopilot`` the equipped cars drive themselves instead
(``autopilot.py``), from what their own sensors see (``perception.py``):
the car in front and the light's colour come from the sensors, not from the
simulation. Safety is counted on the truth: collisions, close calls, red
lights crossed, emergency and phantom braking. ``double_parking`` makes cars
stop in the lane for a while, as when someone double-parks: a standing
obstacle that was never seen moving.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import autopilot as ap
from .advisor import Advisor, NextControl, Occupancy
from .perception import Perception, Seen
from .display import AdviceDisplay
from .profile_learner import ProfileLearner
from .glosa import Advice
from .network import BORDER, PRIORITY, ROUNDABOUT, SIGNAL, Network

# Intelligent Driver Model
IDM_ACCEL = 1.4
IDM_DECEL = 2.0
IDM_S0 = 2.0
IDM_T = 1.2
VEH_LENGTH = 4.5
MASS = 1300.0           # kg, for braking energy
BRAKE_THRESHOLD = 1.2   # m/s^2: slowing faster than this means the brake pedal
NATURAL_DECEL = 0.7     # what lifting off gives for free
YELLOW_DECEL = 3.0      # stop on yellow only if this is enough
NODE_HOLD = 1.6         # s a vehicle occupies a roundabout or give-way node
MERGE_ZONE = 40.0       # m: cars this close to a junction take turns into the same street
PED_DECEL = 3.0         # m/s^2: a driver stops for someone waiting at a crossing if this is enough
PED_WAIT = 1.5          # s a pedestrian waits on the kerb before stepping in
PED_CROSS = 4.0         # s in the lane
HUMAN_PED_SIGHT = 60.0  # m: people see a pedestrian at a crossing from here


@dataclass
class Crossing:
    """A zebra crossing in the middle of a street."""

    id: int
    edge: str
    pos: float
    state: Optional[str] = None   # None, 'waiting' or 'crossing'
    until: float = 0.0
    careless: bool = False
    no_chance: set = field(default_factory=set)  # cars too close to stop at all when this person stepped in
MAJOR_GAP = 4.0         # s a minor-road car needs before the next major-road car arrives


@dataclass
class Vehicle:
    id: int
    route: List[str]
    equipped: bool
    t_start: float
    idx: int = 0
    pos: float = 0.0
    v: float = 0.0
    a: float = 0.0
    stops: int = 0
    brake_events: int = 0
    brake_energy: float = 0.0  # J
    moving: bool = True
    braking: bool = False
    advice: Optional[Advice] = None
    next_control: Optional[NextControl] = None
    display: AdviceDisplay = field(default_factory=AdviceDisplay)
    shown: Optional[Advice] = None   # what the driver sees (see display.py)
    raw_changes: int = 0             # times the computed speed or kind changed
    _raw_key: Optional[tuple] = None
    coast_true: Optional[float] = None  # m/s^2 this car really loses when lifting off (None: the model's)
    accel_true: Optional[float] = None  # m/s^2 it really gains when speeding up gently
    doing: Optional[str] = None      # what the driver is doing for the advice: "coast", "accel" or None
    learner: Optional[ProfileLearner] = None
    phone: Optional[object] = None   # positioning.Phone: where the car's phone thinks it is
    cum: Optional[List[float]] = None  # distance along the route at the start of each edge
    odo: float = 0.0                 # m really driven (junctions included, unlike cum + pos)
    gps_offset: float = 0.0          # odo - (cum[idx] + pos): the junctions crossed so far
    gps_suspended: int = 0           # advice updates suspended because the position was too uncertain
    gps_updates: int = 0
    # Self-driving (SimConfig.autopilot)
    perception: Optional[Perception] = None
    why: str = ""                    # what set the autopilot's acceleration in the last step
    parked_until: Optional[float] = None  # a double-parked car: stands still until then, not counted
    dist: float = 0.0                # m driven
    collisions: int = 0
    conflicts: int = 0               # true time to collision under 1.5 s
    red_runs: int = 0
    aeb: int = 0
    phantom: int = 0                 # braking for an object that is not there
    gap_err2: float = 0.0            # sum of squared errors of the perceived gap to the real car ahead
    gap_n: int = 0
    near_n: int = 0                  # steps with a real car within 40 m ahead...
    missed: int = 0                  # ...that the car did not perceive
    _hit: set = field(default_factory=set)
    _conflict: bool = False
    _lead_id: Optional[int] = None
    pedestrian_hits: int = 0         # drove over a crossing while someone was in the lane...
    pedestrian_no_chance: int = 0    # ...counted apart when they stepped in too close to stop at all
    yield_fails: int = 0             # entered a give-way junction less than 2 s before a main-road car
    _last_gap: float = 0.0
    _phantom_on: bool = False

    @property
    def edge(self) -> str:
        return self.route[self.idx]

    def followed(self, shown: bool) -> Optional[Advice]:
        """The advice the driver acts on: what is shown, or the raw computed one."""
        return self.shown if shown else self.advice


def refresh_display(veh: Vehicle, t: float) -> None:
    """After a new advice: update what the driver sees, and count how often each changes."""
    if veh.advice is None:
        return
    key = (veh.advice.kind, _kmh(veh.advice.target))
    if key != veh._raw_key:
        veh.raw_changes += 1
        veh._raw_key = key
    nc = veh.next_control
    veh.shown = veh.display.update(t, veh.advice, None if nc is None else nc.kind + ":" + nc.node)


def record_motion(veh: Vehicle, v_old: float, v_new: float, dt: float) -> None:
    """Count stops, braking events and the energy lost in the brakes.

    What a car loses by lifting off is free (engine braking, or regeneration for an
    electric car), so only slowing beyond that counts: beyond the car's own figure
    when it has one (``coast_true``), else beyond NATURAL_DECEL.
    """
    decel = (v_old - v_new) / dt
    natural = NATURAL_DECEL if veh.coast_true is None else veh.coast_true
    if decel > natural:
        veh.brake_energy += MASS * (decel - natural) * (v_old + v_new) / 2 * dt
    is_braking = decel > natural + (BRAKE_THRESHOLD - NATURAL_DECEL)
    if is_braking and not veh.braking:
        veh.brake_events += 1
    veh.braking = is_braking
    if veh.moving and v_new < 0.3:
        veh.stops += 1
        veh.moving = False
    elif not veh.moving and v_new > 3.0:
        veh.moving = True


@dataclass
class GroupStats:
    trips: int = 0
    travel_time: float = 0.0
    stops: int = 0
    brake_events: int = 0
    brake_energy: float = 0.0
    raw_changes: int = 0
    shown_changes: int = 0
    announcements: int = 0
    gps_updates: int = 0
    gps_suspended: int = 0
    km: float = 0.0
    collisions: int = 0
    conflicts: int = 0
    red_runs: int = 0
    aeb: int = 0
    phantom: int = 0
    gap_err2: float = 0.0
    gap_n: int = 0
    near_n: int = 0
    missed: int = 0
    pedestrian_hits: int = 0
    pedestrian_no_chance: int = 0
    yield_fails: int = 0

    def add(self, v: Vehicle, t: float) -> None:
        self.trips += 1
        self.travel_time += t - v.t_start
        self.stops += v.stops
        self.brake_events += v.brake_events
        self.brake_energy += v.brake_energy
        self.raw_changes += v.raw_changes
        self.shown_changes += v.display.changes
        self.announcements += v.display.announcements
        self.gps_updates += v.gps_updates
        self.gps_suspended += v.gps_suspended
        self.km += v.dist / 1000
        for k in ("collisions", "conflicts", "red_runs", "aeb", "phantom", "gap_err2", "gap_n", "near_n", "missed",
                  "pedestrian_hits", "pedestrian_no_chance", "yield_fails"):
            setattr(self, k, getattr(self, k) + getattr(v, k))

    def summary(self) -> Dict[str, float]:
        n = max(self.trips, 1)
        return {
            "trips": self.trips,
            "travel_time": round(self.travel_time / n, 1),
            "stops": round(self.stops / n, 2),
            "brake_events": round(self.brake_events / n, 2),
            "brake_energy_kj": round(self.brake_energy / n / 1000, 1),
            "advice_changes": round(self.raw_changes / n, 1),
            "shown_changes": round(self.shown_changes / n, 1),
            "announcements": round(self.announcements / n, 1),
            "advice_suspended_pct": round(100 * self.gps_suspended / max(self.gps_updates, 1), 1),
            "km": round(self.km, 1),
            "collisions": self.collisions,
            "conflicts": self.conflicts,
            "red_runs": self.red_runs,
            "aeb": self.aeb,
            "phantom": self.phantom,
            "gap_rmse_m": round(math.sqrt(self.gap_err2 / self.gap_n), 2) if self.gap_n else None,
            "missed_pct": round(100 * self.missed / self.near_n, 2) if self.near_n else None,
            "pedestrian_hits": self.pedestrian_hits,
            "pedestrian_no_chance": self.pedestrian_no_chance,
            "yield_fails": self.yield_fails,
        }


@dataclass
class SimConfig:
    dt: float = 0.2
    demand: float = 220.0       # vehicles per hour per entry road
    penetration: float = 0.5    # share of vehicles following DriveNow
    seed: int = 1
    advice_every: float = 0.6   # s between advice updates
    # Self-driving equipped cars (see autopilot.py and perception.py)
    autopilot: bool = False
    sensors: str = "camera+radar"   # perfect | camera | camera+radar | camera+radar+lidar
    weather: str = "clear"          # clear | night | rain | fog
    light_timing: bool = True       # the lights' timings are known (SPaT/V2I); else only the camera
    ghost_per_km: float = 2.0       # radar ghosts along the road
    double_parking: float = 0.0     # cars per hour that stop in the lane somewhere in the network...
    parked_for: Tuple[float, float] = (15.0, 40.0)  # ...for this long (s)
    pedestrians: float = 0.0        # people per hour at each zebra crossing (one mid-street, streets > 150 m)
    careless: float = 0.05          # share of them who step in without looking, whatever the traffic


class Simulation:
    def __init__(self, net: Network, config: SimConfig = SimConfig(), advisor: Optional[Advisor] = None) -> None:
        self.net = net
        self.cfg = config
        self.advisor = advisor or Advisor(net)
        self.rng = random.Random(config.seed)
        self.t = 0.0
        self.vehicles: List[Vehicle] = []
        self._next_id = 0
        self._advice_clock = 0.0
        self.follow_shown = False  # equipped drivers act on the shown advice instead of the raw one
        self.node_busy: Dict[str, float] = {}
        self.stats = {True: GroupStats(), False: GroupStats()}
        self._entries = net.entry_edges()
        self._perc_rng = random.Random(config.seed * 7919 + 11)
        self.autopilot_cfg = ap.AutopilotConfig()
        self.crossings: List[Crossing] = []
        self.pedestrians_crossed = 0
        if config.pedestrians > 0:
            for e in net.edges.values():
                if e.length > 150:
                    self.crossings.append(Crossing(len(self.crossings), e.id, e.length / 2))
        self._crossings_on: Dict[str, List[Crossing]] = {}
        for c in self.crossings:
            self._crossings_on.setdefault(c.edge, []).append(c)
        if not config.light_timing:
            # No timings: the advice knows nothing about the lights (only roundabouts, give-ways, queues).
            self.advisor.windows_fn = lambda e, n, t: None

    # -- helpers ----------------------------------------------------------------

    def occupancy(self) -> Occupancy:
        occ: Occupancy = {}
        for v in self.vehicles:
            occ.setdefault(v.edge, []).append((v.pos, v.v))
        for lst in occ.values():
            lst.sort()
        return occ

    def _by_edge(self) -> Dict[str, List[Vehicle]]:
        d: Dict[str, List[Vehicle]] = {}
        for v in self.vehicles:
            d.setdefault(v.edge, []).append(v)
        for lst in d.values():
            lst.sort(key=lambda x: x.pos)
        return d

    @staticmethod
    def _idm(v: float, v0: float, gap: float, dv: float) -> float:
        v0 = max(v0, 0.1)
        free = 1 - (v / v0) ** 4
        if gap == math.inf:
            return IDM_ACCEL * free
        s_star = IDM_S0 + max(0.0, v * IDM_T + v * dv / (2 * math.sqrt(IDM_ACCEL * IDM_DECEL)))
        gap = max(gap, 0.1)
        return IDM_ACCEL * (free - (s_star / gap) ** 2)

    def _major_cars(self, node_id: str, by_edge: Dict[str, List[Vehicle]]) -> List[Tuple[float, float, int]]:
        """Cars on the main road coming to a give-way junction: (distance to it, speed, id)."""
        node = self.net.nodes[node_id]
        out = []
        for e in node.major:
            edge = self.net.edges[e]
            for other in by_edge.get(e, []):
                out.append((edge.length - other.pos, other.v, other.id))
        return out

    @staticmethod
    def _close(cars, margin: float = 0.0) -> bool:
        """A main-road car (distance, speed, sigma) arrives too soon to cross in front of it."""
        for d, v, sg in cars:
            d -= margin * sg
            if d < 3 or (v > 0.5 and d / v < MAJOR_GAP):
                return True
        return False

    def _major_car_close(self, node_id: str, by_edge: Dict[str, List[Vehicle]]) -> bool:
        return self._close([(d, v, 0.0) for d, v, _ in self._major_cars(node_id, by_edge)])

    def _pedestrians(self, by_edge: Dict[str, List[Vehicle]]) -> None:
        """People arrive at the crossings, wait on the kerb, and cross when no car is too close to stop."""
        p = self.cfg.pedestrians / 3600.0 * self.cfg.dt
        for c in self.crossings:
            if c.state is None:
                if self.rng.random() < p:
                    c.state, c.until = "waiting", self.t + PED_WAIT
                    c.careless = self.rng.random() < self.cfg.careless
                    if c.careless:  # straight into the lane, without stopping on the kerb
                        c.state, c.until = "crossing", self.t + PED_CROSS
                        self.pedestrians_crossed += 1
                        # Cars that could not stop even braking as hard as possible (8 m/s^2).
                        c.no_chance = {v.id for v in by_edge.get(c.edge, [])
                                       if v.pos < c.pos and c.pos - v.pos < v.v * v.v / 16.0 + 0.5}
            elif c.state == "waiting" and self.t >= c.until:
                # Nobody steps in front of a moving car that could not stop for them.
                close = any(v.v > 0.5 and c.pos - v.pos < v.v * v.v / (2 * PED_DECEL) + 3.0
                            for v in by_edge.get(c.edge, []) if v.pos < c.pos)
                if close:
                    c.until = self.t + 0.5
                else:
                    c.state, c.until = "crossing", self.t + PED_CROSS
                    c.no_chance = set()
                    self.pedestrians_crossed += 1
            elif c.state == "crossing" and self.t >= c.until:
                c.state = None

    def _crossing_stop(self, veh: Vehicle, sees) -> Optional[Tuple[float, str]]:
        """(distance to stop at, state) before the next crossing if someone is at it, else None.

        ``sees(crossing, distance)`` says what the driver sees there. Someone still on the kerb
        is let through only if the car can stop comfortably.
        """
        for c in self._crossings_on.get(veh.edge, ()):
            d = c.pos - veh.pos
            if d <= 0:
                continue
            state = sees(c, d)
            if state == "crossing" or (state == "waiting" and veh.v * veh.v / (2 * PED_DECEL) < d - 2.0):
                return d - 2.0, state
            return None
        return None

    # -- one step ---------------------------------------------------------------

    def step(self) -> None:
        dt = self.cfg.dt
        self.t += dt
        by_edge = self._by_edge()

        self._advice_clock -= dt
        if self._advice_clock <= 0:
            self._advice_clock = self.cfg.advice_every
            occ = self.occupancy()
            for veh in self.vehicles:
                veh.advice, veh.next_control = self.advisor.advise(veh.route, veh.idx, veh.pos, veh.v, self.t, occ)
                refresh_display(veh, self.t)

        self._pedestrians(by_edge)
        if self.cfg.autopilot:
            for veh in self.vehicles:
                if veh.perception is not None:
                    lead = self.ahead(veh, by_edge)
                    leader = None if lead is None else (lead[0], lead[1].v, lead[1].id)
                    veh.perception.sense(self.t, self._route_s(veh), veh.v, leader, self._light_ahead(veh))
                    self._score_perception(veh, lead)
                    if self.crossings:
                        veh.perception.see_pedestrians(
                            self.t, [(c.id, c.pos - veh.pos, c.state) for c in self._crossings_on.get(veh.edge, [])
                                     if c.pos > veh.pos])
                    node = self.net.nodes[self.net.edges[veh.edge].to_node]
                    if node.kind == PRIORITY and veh.edge not in node.major and \
                            self.net.edges[veh.edge].length - veh.pos < 60:
                        veh.perception.see_cross(self.t, self._major_cars(node.id, by_edge))

        self._entering = self._entering_index()
        for veh in self.vehicles:
            veh.a = self._acceleration(veh, by_edge)

        finished: List[Vehicle] = []
        for veh in self.vehicles:
            v_new = max(0.0, veh.v + veh.a * dt)
            record_motion(veh, veh.v, v_new, dt)
            pos_old = veh.pos
            veh.pos += (veh.v + v_new) / 2 * dt
            for c in self._crossings_on.get(veh.edge, ()):
                if pos_old < c.pos <= veh.pos and c.state == "crossing":
                    if veh.id in c.no_chance:
                        veh.pedestrian_no_chance += 1
                    else:
                        veh.pedestrian_hits += 1
            veh.dist += (veh.v + v_new) / 2 * dt
            veh.v = v_new
            while veh.pos >= self.net.edges[veh.edge].length:
                edge = self.net.edges[veh.edge]
                node = self.net.nodes[edge.to_node]
                if node.kind == SIGNAL and node.plan is not None and \
                        node.plan.state(self.t, node.group_of.get(edge.id, "")) == "r":
                    veh.red_runs += 1
                if veh.idx == len(veh.route) - 1:
                    finished.append(veh)
                    break
                if node.kind == PRIORITY and edge.id not in node.major and \
                        any(d < 5 or (v > 0.5 and d / v < 2.0) for d, v, _ in self._major_cars(node.id, by_edge)):
                    veh.yield_fails += 1
                if node.kind in (ROUNDABOUT, PRIORITY):
                    self.node_busy[node.id] = self.t + NODE_HOLD
                veh.pos -= edge.length
                veh.idx += 1

        for veh in finished:
            self.vehicles.remove(veh)
            if veh.parked_until is None:
                self.stats[veh.equipped].add(veh, self.t)

        if self.cfg.autopilot or self.cfg.double_parking:
            self._safety()
        self._spawn(by_edge)
        self._double_park()

    # -- seeing the road -----------------------------------------------------------

    def ahead(self, veh: Vehicle, by_edge: Dict[str, List[Vehicle]], horizon: float = 200.0):
        """The first vehicle ahead along the route: (bumper-to-bumper gap, vehicle), or None."""
        dist = -veh.pos
        for k in range(veh.idx, len(veh.route)):
            e = veh.route[k]
            for other in by_edge.get(e, []):
                if other is veh or (k == veh.idx and other.pos <= veh.pos):
                    continue
                return dist + other.pos - VEH_LENGTH, other
            dist += self.net.edges[e].length
            if dist > horizon:
                return None
        return None

    def _route_s(self, veh: Vehicle) -> float:
        return sum(self.net.edges[e].length for e in veh.route[:veh.idx]) + veh.pos

    def _light_ahead(self, veh: Vehicle, horizon: float = 200.0):
        """The next light on the route: (distance to its line, colour now, node id), or None."""
        dist = -veh.pos
        for k in range(veh.idx, len(veh.route)):
            edge = self.net.edges[veh.route[k]]
            dist += edge.length
            if dist > horizon:
                return None
            node = self.net.nodes[edge.to_node]
            if node.kind == SIGNAL and node.plan is not None:
                return dist, node.plan.state(self.t, node.group_of.get(edge.id, "")), node.id
        return None

    def _score_perception(self, veh: Vehicle, lead) -> None:
        """How well the car sees the real car in front (only to evaluate)."""
        seen = veh.perception.leader()
        if lead is None or lead[0] > 40:
            return
        veh.near_n += 1
        if seen is None or seen.truth != lead[1].id:
            veh.missed += 1
        else:
            veh.gap_err2 += (seen.gap - lead[0]) ** 2
            veh.gap_n += 1

    def _safety(self) -> None:
        """Collisions and close calls, from the truth."""
        by_edge = self._by_edge()
        for veh in self.vehicles:
            if veh.parked_until is not None:
                continue
            lead = self.ahead(veh, by_edge, horizon=60.0)
            if lead is None:
                veh._conflict = False
                continue
            gap, other = lead
            if other.id != veh._lead_id:
                veh._lead_id, veh._last_gap = other.id, gap
            last, veh._last_gap = veh._last_gap, gap
            if gap < 0.3:
                if last >= 0.3 and other.id not in veh._hit:
                    veh._hit.add(other.id)
                    veh.collisions += 1
                veh.v = min(veh.v, other.v)
            closing = veh.v - other.v
            conflict = closing > 0.5 and max(gap, 0.0) / closing < 1.5
            if conflict and not veh._conflict:
                veh.conflicts += 1
            veh._conflict = conflict

    def _double_park(self) -> None:
        """Now and then a car stops in the lane for a while (double parking, a delivery)."""
        if self.cfg.double_parking <= 0 or self.rng.random() >= self.cfg.double_parking / 3600.0 * self.cfg.dt:
            return
        edges = [e for e in self.net.edges.values() if e.length > 120]
        if not edges:
            return
        edge = self.rng.choice(edges)
        pos = self.rng.uniform(80.0, edge.length - 30.0)
        if any(pos - 80 < o.pos < pos + 15 for o in self._by_edge().get(edge.id, [])):
            return
        route = self.net.random_route(edge.id, self.rng)
        if self.net.nodes[self.net.edges[route[-1]].to_node].kind != BORDER:
            return
        veh = Vehicle(self._next_id, route, False, self.t, pos=pos, v=0.0,
                      parked_until=self.t + self.rng.uniform(*self.cfg.parked_for))
        veh.moving = False
        self._next_id += 1
        self.vehicles.append(veh)

    def _entering_index(self) -> Dict[str, List[Tuple[float, "Vehicle"]]]:
        """For each street, the cars about to turn into it: (distance to their line, car)."""
        idx: Dict[str, List[Tuple[float, Vehicle]]] = {}
        for veh in self.vehicles:
            if veh.idx + 1 < len(veh.route) and (veh.parked_until is None or self.t >= veh.parked_until):
                to_line = self.net.edges[veh.edge].length - veh.pos
                if to_line < MERGE_ZONE:
                    idx.setdefault(veh.route[veh.idx + 1], []).append((to_line, veh))
        return idx

    def _may_go(self, veh: Vehicle) -> bool:
        """The car is not held by a red light at its line."""
        edge = self.net.edges[veh.edge]
        node = self.net.nodes[edge.to_node]
        if node.kind == SIGNAL and node.plan is not None:
            return node.plan.state(self.t, node.group_of.get(edge.id, "")) != "r"
        return True

    def merge_leader(self, veh: Vehicle) -> Optional[Tuple[float, "Vehicle"]]:
        """A car from another street that turns into ours just before us: (gap it will leave, car).

        Two cars turning into the same street take turns: the one that reaches the junction
        first goes first, the other follows it. Cars standing at their line (a red light,
        a give-way) do not count until they move.
        """
        if veh.idx + 1 >= len(veh.route):
            return None
        to_line = self.net.edges[veh.edge].length - veh.pos
        if to_line >= MERGE_ZONE:
            return None
        eta = to_line / max(veh.v, 0.1)
        best = None
        for d, other in getattr(self, "_entering", {}).get(veh.route[veh.idx + 1], []):
            if other is veh or other.edge == veh.edge or other.v < 0.5 or not self._may_go(other):
                continue
            eta_o = d / other.v
            if eta_o < eta or (eta_o == eta and other.id < veh.id):
                gap = to_line - d - VEH_LENGTH
                if best is None or gap < best[0]:
                    best = (gap, other)
        return best

    def _acceleration(self, veh: Vehicle, by_edge: Dict[str, List[Vehicle]]) -> float:
        if veh.parked_until is not None and self.t < veh.parked_until:
            return -9.0
        edge = self.net.edges[veh.edge]
        node = self.net.nodes[edge.to_node]
        limit = edge.speed
        to_line = edge.length - veh.pos

        # Car in front: same edge, or the last car on the next edge of the route.
        gap, dv = math.inf, 0.0
        same = by_edge.get(veh.edge, [])
        i = same.index(veh)
        if i + 1 < len(same):
            ld = same[i + 1]
            gap, dv = ld.pos - VEH_LENGTH - veh.pos, veh.v - ld.v
        elif veh.idx + 1 < len(veh.route):
            nxt = by_edge.get(veh.route[veh.idx + 1], [])
            if nxt:
                ld = nxt[0]
                gap, dv = to_line + ld.pos - VEH_LENGTH, veh.v - ld.v
        merge = self.merge_leader(veh)
        if merge is not None and merge[0] < gap:
            gap, dv = merge[0], veh.v - merge[1].v

        # The stop line acts as a stopped car when we may not cross it.
        must_stop = False
        if node.kind == SIGNAL and node.plan is not None:
            st = node.plan.state(self.t, node.group_of.get(edge.id, ""))
            if st == "r":
                must_stop = True
            elif st == "y":
                must_stop = veh.v * veh.v / (2 * YELLOW_DECEL) < to_line - 1.0
            adv = veh.followed(self.follow_shown)
            if must_stop and veh.equipped and adv is not None and adv.kind in ("go", "slow"):
                # A DriveNow driver knows the light turns green before they get there,
                # so they do not brake for it, unless it is still red at stopping distance.
                safe = veh.v * veh.v / (2 * YELLOW_DECEL) + 3.0
                t_arrive = to_line / max(veh.v, 0.5)
                group = node.group_of.get(edge.id, "")
                if to_line > safe and node.plan.state(self.t + t_arrive, group) == "G":
                    must_stop = False
        elif node.kind == ROUNDABOUT or (node.kind == PRIORITY and edge.id not in node.major):
            if to_line < 25:
                busy = self.node_busy.get(node.id, -1) > self.t
                if node.kind == PRIORITY:
                    if veh.perception is not None:
                        # What its side cameras and radars see, two sigmas on the safe side.
                        busy = busy or self._close(veh.perception.cross(self.t), margin=2.0)
                    else:
                        busy = busy or self._major_car_close(node.id, by_edge)
                must_stop = busy
            # Everyone slows down for the roundabout; normal drivers do it late, with the brakes.
            limit = min(limit, math.sqrt(node.entry_speed ** 2 + 2 * IDM_DECEL * max(to_line - 3, 0.0)))
        if veh.perception is not None:
            return self._autopilot(veh, node, edge, limit, to_line, junction_stop=must_stop and node.kind != SIGNAL,
                                   merge=merge, by_edge=by_edge)
        ped = self._crossing_stop(veh, lambda c, d: c.state if d < HUMAN_PED_SIGHT else None)
        if ped is not None and ped[0] < gap:
            gap, dv = ped[0], veh.v
        if must_stop and to_line - 1.0 < gap:
            gap, dv = to_line - 1.0, veh.v

        a_idm = self._idm(veh.v, limit, gap, dv)
        adv = veh.followed(self.follow_shown)
        if not veh.equipped or adv is None or adv.target is None:
            return max(a_idm, -9.0)

        # DriveNow driver: track the advised speed, but only by lifting off.
        target = adv.target
        if adv.kind == "stop" and veh.next_control is not None and veh.next_control.node == node.id:
            # Red is unavoidable: roll towards the line so the car arrives slowly.
            d = max(to_line - 2.0, 0.0)
            target = min(target, math.sqrt(2 * self.advisor.profile.coast_decel * d))
        tau = 1.0
        a_track = (target - veh.v) / tau
        a_track = min(max(a_track, -self.advisor.profile.coast_decel), self.advisor.profile.accel)
        return max(min(a_track, a_idm), -9.0)

    def _autopilot(self, veh: Vehicle, node, edge, limit: float, to_line: float, junction_stop: bool,
                   merge=None, by_edge=None) -> float:
        """A self-driving car: the car in front and the light come from its own sensors."""
        perc = veh.perception
        seen = perc.leader()
        adv = veh.followed(self.follow_shown)
        b = self.autopilot_cfg.comfort_decel
        must_stop = junction_stop
        if node.kind == SIGNAL and node.plan is not None:
            group = node.group_of.get(edge.id, "")
            cam = perc.light()
            plan = node.plan.state(self.t, group) if self.cfg.light_timing else None
            seen_colours = {c for c in (cam, plan) if c is not None}
            if "r" in seen_colours:
                must_stop = True
            elif "y" in seen_colours:
                must_stop = veh.v * veh.v / (2 * YELLOW_DECEL) < to_line - 1.0
            elif not seen_colours:
                # Neither timing nor a reading: be able to stop at the line until it is seen green.
                if to_line <= perc.light_range():
                    must_stop = True
                else:
                    limit = min(limit, math.sqrt(2 * b * max(to_line - 1.0, 0.0)))
            if must_stop and self.cfg.light_timing and adv is not None and adv.kind in ("go", "slow"):
                # The timing says it is green by the time the car gets there: keep coasting.
                safe = veh.v * veh.v / (2 * YELLOW_DECEL) + 3.0
                t_arrive = to_line / max(veh.v, 0.5)
                if to_line > safe and node.plan.state(self.t + t_arrive, group) == "G":
                    must_stop = False
        target = None
        if adv is not None and adv.target is not None:
            target = adv.target
            if adv.kind == "stop" and veh.next_control is not None and veh.next_control.node == node.id:
                target = min(target, math.sqrt(2 * self.advisor.profile.coast_decel * max(to_line - 2.0, 0.0)))
        others = []
        if merge is not None:
            others.append(Seen(merge[0], merge[1].v - veh.v, 0.0, 0.0, ("side",), merge[1].id))
        stop_at = to_line - 1.0 if must_stop else None
        # Zebra crossings: stop for someone it sees; slow down for one it cannot see yet.
        ped_range = perc.pedestrian_range()
        for c in self._crossings_on.get(veh.edge, ()):
            d = c.pos - veh.pos
            if d > ped_range:
                limit = min(limit, math.sqrt(2 * b * max(d - 2.0, 0.0)))
        ped = self._crossing_stop(veh, lambda c, d: perc.pedestrian(c.id))
        if ped is not None:
            stop_at = ped[0] if stop_at is None else min(stop_at, ped[0])
            if ped[1] == "crossing":  # someone in the lane: emergency braking if needed
                others.append(Seen(ped[0] + 1.0, -veh.v, 0.0, 0.0, ("pedestrian",), "pedestrian"))
        a, why = ap.control(veh.v, limit, seen, stop_at, target,
                            self.advisor.profile.coast_decel, self.advisor.profile.accel,
                            perc.stationary_range(), self.autopilot_cfg, others)
        if why == "aeb" and veh.why != "aeb":
            veh.aeb += 1
        # Braking for nothing: the object is not a real car, and no real car is near where it is seen.
        real = perc._truth_leader
        ghost = seen is not None and (seen.truth is None or seen.truth == "ghost") and \
            (real is None or real[0] > seen.gap + 10.0)
        phantom = ghost and why in ("leader", "aeb") and a < -BRAKE_THRESHOLD
        if phantom and not veh._phantom_on:
            veh.phantom += 1
        veh._phantom_on = phantom
        veh.why = why
        return a

    def _spawn(self, by_edge: Dict[str, List[Vehicle]]) -> None:
        p = self.cfg.demand / 3600.0 * self.cfg.dt
        for e in self._entries:
            if self.rng.random() >= p:
                continue
            on_edge = by_edge.get(e, [])
            if on_edge and on_edge[0].pos < VEH_LENGTH + IDM_S0 + 6:
                continue
            route = self.net.random_route(e, self.rng)
            if self.net.nodes[self.net.edges[route[-1]].to_node].kind != BORDER:
                continue
            edge = self.net.edges[e]
            v0 = edge.speed * 0.85
            if on_edge:
                v0 = min(v0, on_edge[0].v + 1.0)
            veh = Vehicle(self._next_id, route, self.rng.random() < self.cfg.penetration, self.t, v=v0)
            if veh.equipped and self.cfg.autopilot:
                veh.perception = Perception(self._perc_rng, self.cfg.sensors, self.cfg.weather, self.cfg.ghost_per_km)
            self._next_id += 1
            self.vehicles.append(veh)

    def run(self, seconds: float) -> None:
        for _ in range(int(seconds / self.cfg.dt)):
            self.step()

    # -- output for the map -------------------------------------------------------

    def snapshot(self) -> Dict:
        snap = snapshot(self.net, self.t, self.vehicles, self.stats)
        if self.crossings:
            # Zebra crossings: [x, y, heading, 0 nobody / 1 waiting on the kerb / 2 in the lane]
            code = {None: 0, "waiting": 1, "crossing": 2}
            snap["crossings"] = [[round(x, 1), round(y, 1), round(h, 2), code[c.state]]
                                 for c in self.crossings for x, y, h in [self.net.point_at(c.edge, c.pos)]]
        return snap


KIND_CODE = {"free": 0, "go": 1, "slow": 2, "stop": 3, "cap": 4}


def _kmh(x: Optional[float]) -> Optional[int]:
    return None if x is None else int(round(x * 3.6))


def vehicle_row(net: Network, vid, edge: str, pos: float, v: float, equipped: bool,
                advice: Optional[Advice], nxt: Optional[NextControl],
                xy: Optional[Tuple[float, float, float]] = None, announcements: int = 0) -> List:
    x, y, h = xy if xy is not None else net.point_at(edge, pos)
    row = [vid, round(x, 1), round(y, 1), round(h, 2), _kmh(v), 1 if equipped else 0, round(net.edges[edge].speed * 3.6)]
    if advice is None:
        row += [0, None, None, None]
    else:
        row += [KIND_CODE.get(advice.kind, 0), _kmh(advice.low), _kmh(advice.high), _kmh(advice.target)]
    if nxt is None:
        row += [None, None, None, None]
    else:
        row += [nxt.kind, nxt.node, round(nxt.distance), nxt.group]
    row.append(announcements)  # grows by one at each announcement (a chime or a voice could follow it)
    # The next lights on the route: [node, group, distance, approach edge], nearest first.
    row.append([] if nxt is None else [[n, g, round(d), e] for n, g, d, e in nxt.lights])
    return row


def signal_states(net: Network, t: float) -> Dict[str, Dict[str, List]]:
    out: Dict[str, Dict[str, List]] = {}
    for node in net.nodes.values():
        if node.kind != SIGNAL or node.plan is None:
            continue
        groups = {}
        for g in sorted(set(node.group_of.values())):
            dt, nxt = node.plan.time_to_change(t, g)
            groups[g] = [node.plan.state(t, g), None if dt == math.inf else round(dt, 1), nxt]
        out[node.id] = groups
    return out


def seen_row(net: Network, veh: Vehicle) -> Optional[List]:
    """What a self-driving car perceives, for the map: [gap, sensors, light colour, x, y, pedestrian] or None."""
    perc = getattr(veh, "perception", None)
    if perc is None:
        return None
    seen = perc.leader()
    peds = [st for st in (perc.pedestrian(cid) for cid in perc._peds) if st is not None]
    row: List = [None, "", perc.light(), None, None, None]
    if seen is not None:
        row[0], row[1] = round(seen.gap, 1), "+".join(seen.sensors)
        d = veh.pos + seen.gap + VEH_LENGTH / 2
        for k in range(veh.idx, len(veh.route)):
            length = net.edges[veh.route[k]].length
            if d <= length or k == len(veh.route) - 1:
                x, y, _ = net.point_at(veh.route[k], min(d, length))
                row[3], row[4] = round(x, 1), round(y, 1)
                break
            d -= length
    if peds:
        row[5] = "crossing" if "crossing" in peds else "waiting"
    return row


def snapshot(net: Network, t: float, vehicles: List[Vehicle], stats: Dict[bool, GroupStats]) -> Dict:
    rows = []
    for v in vehicles:
        row = vehicle_row(net, v.id, v.edge, v.pos, v.v, v.equipped, v.shown or v.advice, v.next_control,
                          announcements=v.display.announcements)
        row.append(seen_row(net, v))  # [17]: what a self-driving car sees, or None
        rows.append(row)
    return {
        "t": round(t, 1),
        "vehicles": rows,
        "signals": signal_states(net, t),
        "stats": {"drivenow": stats[True].summary(), "normal": stats[False].summary(), "live": len(vehicles)},
    }


def static_network(net: Network) -> Dict:
    """Geometry for the map, sent once."""
    nodes = []
    for n in net.nodes.values():
        nodes.append({
            "id": n.id, "x": n.x, "y": n.y, "kind": n.kind, "r": n.radius, "name": n.name or n.id,
            "groups": n.group_of, "major": sorted(n.major), "entry_kmh": round(n.entry_speed * 3.6),
            "cycle": round(n.plan.cycle, 1) if n.plan else None,
        })
    edges = [{"id": e.id, "from": e.from_node, "to": e.to_node, "shape": e.shape, "len": round(e.length, 1),
              "kmh": round(e.speed * 3.6), "name": e.name} for e in net.edges.values()]
    return {"name": net.name, "bounds": net.bounds(), "nodes": nodes, "edges": edges}
