"""A small traffic simulation, so DriveNow runs without installing SUMO.

Single-lane roads, Intelligent Driver Model car following, fixed-time
traffic lights, a roundabout and a give-way junction with simple gap
acceptance.

Every vehicle gets advice; only the *equipped* share follows it. Those
drivers never press the brake pedal to follow the advice: they lift off and
coast. They still brake when the car in front forces them to, like anyone
else. Comparing the two groups shows what the advice is worth: stops,
braking events and energy thrown away in the brakes.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .advisor import Advisor, NextControl, Occupancy
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
    gps_suspended: int = 0           # advice updates suspended because the position was too uncertain
    gps_updates: int = 0

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
        }


@dataclass
class SimConfig:
    dt: float = 0.2
    demand: float = 220.0       # vehicles per hour per entry road
    penetration: float = 0.5    # share of vehicles following DriveNow
    seed: int = 1
    advice_every: float = 0.6   # s between advice updates


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

    def _major_car_close(self, node_id: str, by_edge: Dict[str, List[Vehicle]]) -> bool:
        node = self.net.nodes[node_id]
        for e in node.major:
            for other in by_edge.get(e, []):
                edge = self.net.edges[e]
                d = edge.length - other.pos
                if d < 3 or (other.v > 0.5 and d / other.v < MAJOR_GAP):
                    return True
        return False

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

        for veh in self.vehicles:
            veh.a = self._acceleration(veh, by_edge)

        finished: List[Vehicle] = []
        for veh in self.vehicles:
            v_new = max(0.0, veh.v + veh.a * dt)
            record_motion(veh, veh.v, v_new, dt)
            veh.pos += (veh.v + v_new) / 2 * dt
            veh.v = v_new
            while veh.pos >= self.net.edges[veh.edge].length:
                edge = self.net.edges[veh.edge]
                node = self.net.nodes[edge.to_node]
                if veh.idx == len(veh.route) - 1:
                    finished.append(veh)
                    break
                if node.kind in (ROUNDABOUT, PRIORITY):
                    self.node_busy[node.id] = self.t + NODE_HOLD
                veh.pos -= edge.length
                veh.idx += 1

        for veh in finished:
            self.vehicles.remove(veh)
            self.stats[veh.equipped].add(veh, self.t)

        self._spawn(by_edge)

    def _acceleration(self, veh: Vehicle, by_edge: Dict[str, List[Vehicle]]) -> float:
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
                    busy = busy or self._major_car_close(node.id, by_edge)
                must_stop = busy
            # Everyone slows down for the roundabout; normal drivers do it late, with the brakes.
            limit = min(limit, math.sqrt(node.entry_speed ** 2 + 2 * IDM_DECEL * max(to_line - 3, 0.0)))
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
            self._next_id += 1
            self.vehicles.append(veh)

    def run(self, seconds: float) -> None:
        for _ in range(int(seconds / self.cfg.dt)):
            self.step()

    # -- output for the map -------------------------------------------------------

    def snapshot(self) -> Dict:
        return snapshot(self.net, self.t, self.vehicles, self.stats)


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


def snapshot(net: Network, t: float, vehicles: List[Vehicle], stats: Dict[bool, GroupStats]) -> Dict:
    return {
        "t": round(t, 1),
        "vehicles": [vehicle_row(net, v.id, v.edge, v.pos, v.v, v.equipped, v.shown or v.advice, v.next_control,
                                 announcements=v.display.announcements) for v in vehicles],
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
