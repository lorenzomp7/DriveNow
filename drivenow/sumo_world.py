"""Run DriveNow on a SUMO simulation through TraCI.

This is how DriveNow plugs into the Traffc_light_control repository: same
``.net.xml`` networks, same SUMO, same TraCI. DriveNow reads every vehicle
and light from SUMO each step, computes the advice with the same Advisor as
the built-in simulation, and drives the equipped vehicles by setting their
speed (only ever lowering it gradually, like a driver lifting off).

The base repository switches its lights from an agent, so their timing
cannot be known in advance. Here the lights run the fixed-time cycle of the
repository's rule-based controller instead: DriveNow installs that program
into SUMO, so the forecast and what SUMO shows are the same thing. A test
checks this.

Needs ``pip install eclipse-sumo traci`` (or a SUMO install with
``SUMO_HOME`` set).
"""

from __future__ import annotations

import math
import os
import random
import tempfile
from bisect import bisect_right
from dataclasses import replace
from typing import Dict, List, Optional

from .advisor import Advisor, NextControl, Occupancy
from .display import AdviceDisplay
from .fleet import FleetDB
from .positioning import Phone
from .profile_learner import ProfileLearner
from .glosa import Advice, DriverProfile
from .network import SIGNAL, load_sumo_net, sumo_link_states
from .simulation import GroupStats, Vehicle, record_motion, refresh_display, signal_states, vehicle_row


def read_routes(path: str) -> Dict[str, List[str]]:
    """Vehicle id -> list of edges, from a SUMO route file (inline or named routes)."""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    named = {r.attrib["id"]: r.attrib["edges"].split() for r in root.findall("route") if "id" in r.attrib}
    out: Dict[str, List[str]] = {}
    for v in root.iter("vehicle"):
        inline = v.find("route")
        if inline is not None:
            out[v.attrib["id"]] = inline.attrib["edges"].split()
        elif v.attrib.get("route") in named:
            out[v.attrib["id"]] = named[v.attrib["route"]]
    return out


def _sumo_binary(gui: bool) -> str:
    if "SUMO_HOME" not in os.environ:
        try:
            import sumo  # the eclipse-sumo wheel

            os.environ["SUMO_HOME"] = sumo.SUMO_HOME
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise RuntimeError("SUMO not found: pip install eclipse-sumo traci, or set SUMO_HOME") from exc
    from sumolib import checkBinary

    return checkBinary("sumo-gui" if gui else "sumo")


# Cars that do not change speed the way the model assumes (0.7 m/s^2 lifting off, 1.3 speeding up):
# share, m/s^2 lost when lifting off, m/s^2 gained when speeding up gently. Plausible, not measured:
# a car that sails in neutral, a usual combustion car in gear, an electric car with strong regeneration.
VEHICLE_MIX = ((0.25, 0.35, 1.2), (0.50, 0.7, 1.4), (0.25, 1.3, 2.0))


class SumoWorld:
    def __init__(
        self,
        net_path: str,
        demand: float = 300.0,
        penetration: float = 0.5,
        seed: int = 1,
        dt: float = 0.2,
        duration: float = 3600.0,
        gui: bool = False,
        cycle_length: float = 40.0,
        label: str = "drivenow",
        route_file: Optional[str] = None,
        teleport: float = -1,
        scale: float = 1.0,
    ) -> None:
        import traci

        self.net_path = os.path.abspath(net_path)
        self.net = load_sumo_net(self.net_path, fallback_cycle=cycle_length)
        self.advisor = Advisor(self.net)
        self.dt = dt
        self.penetration = penetration
        self.rng = random.Random(seed)
        self.t = 0.0
        self.vehicles: Dict[str, Vehicle] = {}
        self.stats = {True: GroupStats(), False: GroupStats()}
        self._advice_clock = 0.0
        self.follow_shown = False  # equipped drivers act on the shown advice instead of the raw one
        self.display_options: Dict = {}  # AdviceDisplay settings for each new car
        # Cars that differ from the model (see VEHICLE_MIX), and what the advice knows about each:
        # "fixed" (the same default for all), "learned" (ProfileLearner) or "true" (an upper bound).
        self.vehicle_mix = False
        self.profiles = "fixed"
        self.speed_noise = 0.2          # m/s: error of the speed a phone measures
        self._mix_rng = random.Random(seed * 7919 + 1)
        # Where the advice thinks each car is: "perfect" (the simulation's truth), or what a phone
        # reports (see positioning.py), "raw" or "filtered"; with more than gps_max_sigma metres
        # of uncertainty the advice is suspended (the driver sees no advice and drives as usual).
        self.gps = "perfect"
        self.gps_max_sigma = 15.0
        self.gps_options: Dict = {}
        self._gps_rng = random.Random(seed * 104729 + 3)
        self.gps_errors: List[float] = []  # m: estimated minus true position, at each advice update
        # Where the advice sees the other cars: "truth" (every car, as the simulation knows them),
        # "fleet" (only the DriveNow cars, as their phones report them, see fleet.py) or
        # "fleet+flow" (and aggregated speed per edge, like a traffic data provider's, emulated
        # from the cars on each edge: a mean over flow_window seconds, delivered flow_delay late).
        self.occupancy_source = "truth"
        self.flow_window = 60.0
        self.flow_delay = (60.0, 120.0)
        self.fleet: Optional[FleetDB] = None
        self.estimator = None   # with "fused": a QueueEstimator from loop detectors (see hamburg/world.py)
        self._road_events: Dict[str, object] = {}
        self._road_db: Optional[FleetDB] = None
        # Road events (see load_road_events). ``clock0`` is the real time (Unix) at t = 0, so that
        # events with real dates apply when they do; None: their times are simulation seconds.
        # ``road_events_advice`` False: SUMO's cars drive by them but the advice does not know them.
        self.clock0: Optional[float] = None
        self.road_events_advice = True
        self._apply_events = False
        self._applied: Dict[str, bool] = {}           # event id -> in force in SUMO now
        self._lane_saved: Dict[str, tuple] = {}       # lane -> (max speed, disallowed) before any event
        self._closed_edges: set = set()
        self._lanes_shut = False                       # some lane is closed: routes may not connect
        self._waiting: set = set()                     # loaded by SUMO, not yet on the road
        self._event_clock = 0.0
        self.no_way_round = 0                          # cars taken out: a closure left them no way
        self.rerouted = 0
        self.zone_speeding = 0.0                       # s: DriveNow advice above a roadworks limit
        self.zone_time = 0.0                           # s: DriveNow cars on edges with such a limit
        self._fleet_clock = 0.0
        self._flow_rng = random.Random(seed * 15485863 + 7)
        self._flow_sum: Dict[str, List[float]] = {}   # edge -> [sum of speeds, samples] this window
        self._flow_start = 0.0
        self._flow_pending: List[tuple] = []          # (delivered at, edge, speed, free speed, measured at)
        self.learnt: List[tuple] = []   # (coast true, coast learnt, accel true, accel learnt) per finished car
        self._learn_clock = 0.0
        self._xy: Dict[str, tuple] = {}
        self._internal: set = set()  # vehicles crossing a junction right now

        self._tmp = tempfile.mkdtemp(prefix="drivenow_")
        if route_file:
            self._route_file = os.path.abspath(route_file)
            self.routes = read_routes(self._route_file)
        else:
            self.routes = self._write_routes(demand, duration)
        cmd = [
            _sumo_binary(gui), "-n", self.net_path, "-r", self._route_file,
            "--step-length", str(dt), "--no-step-log", "true", "--no-warnings", "true",
            "--time-to-teleport", str(teleport), "--seed", str(seed), "--scale", str(scale),
            # A closed lane can leave a car's route undrivable: SUMO then drops the car instead of
            # stopping (cars are rerouted first, see _reroute). Valid routes are not affected.
            "--ignore-route-errors", "true",
        ]
        traci.start(cmd, label=label)
        self.conn = traci.getConnection(label)
        self._install_plans()

    # -- setup ------------------------------------------------------------------

    def _write_routes(self, demand: float, duration: float) -> Dict[str, List[str]]:
        routes: Dict[str, List[str]] = {}
        departures = []
        rate = demand / 3600.0
        for e in self.net.entry_edges():
            t = self.rng.expovariate(rate)
            while t < duration:
                vid = f"v{len(routes)}"
                routes[vid] = self.net.random_route(e, self.rng)
                departures.append((t, vid))
                t += max(self.rng.expovariate(rate), 2.0)
        departures.sort()
        self._route_file = os.path.join(self._tmp, "drivenow.rou.xml")
        with open(self._route_file, "w") as f:
            f.write('<routes>\n  <vType id="car" length="4.5" minGap="2.5" accel="1.4" decel="4.5" '
                    'sigma="0.3" speedFactor="1" speedDev="0"/>\n')
            for t, vid in departures:
                f.write(f'  <vehicle id="{vid}" type="car" depart="{t:.1f}" departSpeed="max">'
                        f'<route edges="{" ".join(routes[vid])}"/></vehicle>\n')
            f.write("</routes>\n")
        return routes

    def _install_plans(self) -> None:
        """Replace agent-driven programs with DriveNow's known fixed-time plan."""
        import traci

        for node in self.net.nodes.values():
            if node.kind != SIGNAL or node.plan_source != "drivenow":
                continue
            phases = [traci.trafficlight.Phase(d, s) for d, s in
                      sumo_link_states(self.net_path, node.tl or node.id, node.plan, node.group_of)]
            logic = traci.trafficlight.Logic("drivenow", 0, 0, phases)
            tl = node.tl or node.id
            self.conn.trafficlight.setProgramLogic(tl, logic)
            self.conn.trafficlight.setProgram(tl, "drivenow")
            i, left = node.plan.locate(self.t)
            self.conn.trafficlight.setPhase(tl, i)
            self.conn.trafficlight.setPhaseDuration(tl, left)

    def _before_step(self) -> None:
        """Hook for subclasses: runs before every SUMO step."""

    def _on_arrival(self, veh: Vehicle) -> None:
        """Hook for subclasses: a vehicle finished its trip."""

    # -- stepping ---------------------------------------------------------------

    def step(self) -> None:
        import traci.constants as tc

        c = self.conn
        v_old = {vid: v.v for vid, v in self.vehicles.items()}
        self._before_step()
        c.simulationStep()
        self.t = c.simulation.getTime()

        departed = c.simulation.getDepartedIDList()
        for vid in departed:
            c.vehicle.subscribe(vid, [tc.VAR_ROAD_ID, tc.VAR_LANEPOSITION, tc.VAR_SPEED,
                                      tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_ROUTE_INDEX,
                                      tc.VAR_LANE_INDEX])
            veh = Vehicle(vid, self.routes.get(vid, []), self.rng.random() < self.penetration, self.t,
                          display=AdviceDisplay(**self.display_options))
            self.vehicles[vid] = veh
            if veh.equipped and self.vehicle_mix:
                r = self._mix_rng.random()
                for share, coast, accel in VEHICLE_MIX:
                    if r < share:
                        break
                    r -= share
                veh.coast_true, veh.accel_true = coast, accel
                c.vehicle.setAccel(vid, accel)
            if veh.equipped and self.profiles == "learned":
                veh.learner = ProfileLearner()
            if veh.equipped and self.gps != "perfect" and veh.route:
                veh.phone = Phone(self._gps_rng, mode=self.gps, **self.gps_options)
                veh.cum = [0.0]
                for e in veh.route[:-1]:
                    veh.cum.append(veh.cum[-1] + self.net.edges[e].length)
        for vid in c.simulation.getArrivedIDList():
            veh = self.vehicles.pop(vid, None)
            self._xy.pop(vid, None)
            self._internal.discard(vid)
            if self.fleet is not None:
                self.fleet.leave(vid)
            if veh is not None:
                self.stats[veh.equipped].add(veh, self.t)
                if veh.learner is not None:
                    lp = veh.learner.profile(self.advisor.profile)
                    n = veh.learner.min_samples
                    self.learnt.append((veh.coast_true, lp.coast_decel if len(veh.learner.coast) >= n else None,
                                        veh.accel_true, lp.accel if veh.learner.learn_accel and len(veh.learner.accel) >= n else None))
                self._on_arrival(veh)

        # SUMO loads cars from the route file ahead of their departure: a closure that starts
        # later must reach them too.
        loaded = c.simulation.getLoadedIDList()
        self._waiting.update(loaded)
        self._waiting.difference_update(departed)
        if self._apply_events:
            if (self._closed_edges or self._lanes_shut) and loaded:
                self._reroute(loaded, waiting=True)
            self._event_clock -= self.dt
            if self._event_clock <= 1e-9:
                self._event_clock = 1.0
                self._apply_road_events()

        data = c.vehicle.getAllSubscriptionResults()
        for vid, veh in self.vehicles.items():
            d = data.get(vid)
            if not d:
                continue
            road = d[tc.VAR_ROAD_ID]
            if d[tc.VAR_SPEED] < 0 or not road:
                continue  # teleporting or not on the road: SUMO reports invalid values
            veh.idx = max(d[tc.VAR_ROUTE_INDEX], 0)
            veh.v = d[tc.VAR_SPEED]
            veh.lane = d.get(tc.VAR_LANE_INDEX, 0)
            on_internal = road.startswith(":") or road not in self.net.edges
            if on_internal:
                self._internal.add(vid)
            else:
                self._internal.discard(vid)
            edge = self.net.edges[veh.edge]
            veh.pos = edge.length if on_internal else min(d[tc.VAR_LANEPOSITION], edge.length)
            x, y = d[tc.VAR_POSITION]
            self._xy[vid] = (x, y, math.radians(90 - d[tc.VAR_ANGLE]))
            record_motion(veh, v_old.get(vid, veh.v), veh.v, self.dt)
            if veh.phone is not None:
                # The phone sees the distance really driven, junctions included; the map (here the
                # route's edges, which leave junctions out) is matched with the junctions crossed so far.
                veh.odo += veh.v * self.dt
                veh.gps_offset = veh.odo - (veh.cum[veh.idx] + veh.pos)
                veh.phone.tick(self.t, veh.odo, veh.v)

        self._learn_clock -= self.dt
        if self._learn_clock <= 1e-9:
            self._learn_clock = 1.0  # a phone reports its speed once a second
            for veh in self.vehicles.values():
                if veh.learner is not None:
                    veh.learner.observe(self.t, veh.v + self._mix_rng.gauss(0.0, self.speed_noise), veh.doing)

        if self.occupancy_source != "truth":
            self._feed_fleet()

        self._advice_clock -= self.dt
        if self._advice_clock <= 0:
            self._advice_clock = 0.6
            occ = self.occupancy()
            for veh in self.vehicles.values():
                if veh.route:
                    where = self._where(veh)
                    if where is None:
                        lim = self.net.edges[veh.edge].speed
                        veh.advice, veh.next_control = Advice("free", None, lim, lim), None
                    else:
                        idx, pos, v = where
                        veh.advice, veh.next_control = self.advisor.advise(veh.route, idx, pos, v, self.t, occ,
                                                                           self._profile_of(veh))
                    refresh_display(veh, self.t)
            if self._road_events:
                self._zone_check()
        self._drive_equipped()

    def _where(self, veh: Vehicle) -> Optional[tuple]:
        """(route index, position on that edge, speed) as the advice knows them, or None: too uncertain."""
        if veh.phone is None:
            return veh.idx, veh.pos, veh.v
        veh.gps_updates += 1
        where = self._estimated(veh)
        if where is None:
            veh.gps_suspended += 1
            return None
        idx, pos, v = where
        self.gps_errors.append(veh.cum[idx] + pos - (veh.cum[veh.idx] + veh.pos))
        return where

    def _estimated(self, veh: Vehicle) -> Optional[tuple]:
        """Where the car's phone puts it: (route index, position, speed), or None."""
        est = veh.phone.estimate(self.t)
        if est is None or est[2] > self.gps_max_sigma:
            return None
        s, v, _ = est
        s = min(max(s - veh.gps_offset, 0.0), veh.cum[-1] + self.net.edges[veh.route[-1]].length)
        idx = max(0, bisect_right(veh.cum, s) - 1)
        pos = min(s - veh.cum[idx], self.net.edges[veh.route[idx]].length)
        return idx, pos, v

    # -- the other cars, as DriveNow knows them on the road ------------------------

    def load_road_events(self, events, apply_to_sumo: bool = True) -> int:
        """Roadworks, closures and the like (road_events.RoadEvent, already matched to this
        network's edges). Unless ``road_events_advice`` is off, the advice knows them; with
        ``apply_to_sumo`` every simulated car drives by them too, while each is in force
        (``clock0``): the temporary limit on the edge's lanes, the closed lanes shut, a closed
        edge shut with the cars that would cross it sent another way.
        Returns how many events touch the network."""
        events = [ev for ev in events if any(e in self.net.edges for e in ev.edges)]
        self._road_events.update({ev.id: ev for ev in events})
        db = self.fleet
        if db is None:
            if self._road_db is None:
                self._road_db = FleetDB({e.id: e.length for e in self.net.edges.values()})
            db = self._road_db
        db.events.update(self._road_events)
        self._wire_road_events(db)
        self._apply_events = self._apply_events or apply_to_sumo
        if apply_to_sumo:
            self._apply_road_events()
        return len(events)

    def real_time(self, t: Optional[float] = None) -> float:
        """The events' clock at simulation time ``t`` (now by default)."""
        return (self.clock0 or 0.0) + (self.t if t is None else t)

    def _wire_road_events(self, db: FleetDB) -> None:
        if not self.road_events_advice:
            return
        if not self.clock0:
            self.advisor.limit_fn, self.advisor.blocked_fn = db.speed_limit, db.blocked
            self.advisor.signal_fault_fn = db.signal_fault
            return
        t0 = self.clock0
        self.advisor.limit_fn = lambda e, t: db.speed_limit(e, t0 + t)
        self.advisor.blocked_fn = lambda e, t: db.blocked(e, t0 + t)
        self.advisor.signal_fault_fn = lambda e, t: db.signal_fault(e, t0 + t)

    # -- road events in SUMO ------------------------------------------------------

    def _lane(self, lane: str) -> tuple:
        if lane not in self._lane_saved:
            self._lane_saved[lane] = (self.conn.lane.getMaxSpeed(lane), tuple(self.conn.lane.getDisallowed(lane)))
        return self._lane_saved[lane]

    def _closed_lane_indices(self, ev, n: int) -> List[int]:
        """SUMO lane indices (0 = rightmost) the event closes on an edge with ``n`` lanes."""
        if ev.blocked:
            return list(range(n))
        if ev.closed_lanes and ev.lane_count == n:
            idx = sorted(n - k for k in ev.closed_lanes if 1 <= k <= n)
        else:
            idx = list(range(ev.lanes_closed or 0))       # unknown which: from the right
        return idx[:max(n - 1, 0)]                         # one lane stays open unless the road is closed

    def _apply_road_events(self) -> None:
        """Put in SUMO the events in force now; undo those that ended."""
        now = self.real_time()
        changed = {}
        for ev in self._road_events.values():
            on = ev.active(now)
            if self._applied.get(ev.id, False) != on:
                self._applied[ev.id] = on
                changed.update({e: True for e in ev.edges if e in self.net.edges})
        if not changed:
            return
        for e in changed:
            n = self.conn.edge.getLaneNumber(e)
            lanes = [f"{e}_{i}" for i in range(n)]
            saved = [self._lane(lane) for lane in lanes]
            limit, closed = None, set()
            for ev in self._road_events.values():
                if self._applied.get(ev.id) and e in ev.edges:
                    if ev.speed_limit:
                        limit = ev.speed_limit if limit is None else min(limit, ev.speed_limit)
                    closed.update(self._closed_lane_indices(ev, n))
            for i, lane in enumerate(lanes):
                speed, disallowed = saved[i]
                self.conn.lane.setMaxSpeed(lane, speed if limit is None else min(speed, limit))
                self.conn.lane.setDisallowed(lane, ["all"] if i in closed else list(disallowed))
            if len(closed) == n:
                self._closed_edges.add(e)
            else:
                self._closed_edges.discard(e)
        self._lanes_shut = any(self._applied.get(ev.id) and (ev.blocked or ev.lanes_closed)
                               for ev in self._road_events.values())
        if self._closed_edges or self._lanes_shut:
            self._reroute(list(self.vehicles))
            self._reroute(list(self._waiting), waiting=True)

    def _reroute(self, vids, waiting: bool = False) -> None:
        """Send the cars whose way ahead crosses a closed edge another way, or take them out.
        ``waiting``: cars SUMO has loaded but not yet put on the road (their whole route counts;
        SUMO would stop on a route it can no longer drive)."""
        c = self.conn
        for vid in vids:
            veh = None if waiting else self.vehicles.get(vid)
            if not waiting and (veh is None or not veh.route):
                continue
            route = veh.route if veh is not None else list(self.routes.get(vid) or c.vehicle.getRoute(vid))
            first = veh.idx + 1 if veh is not None else 0       # a car on the road may finish its edge
            if not self._closed_edges.intersection(route[first:]) and not (self._lanes_shut and not self._valid(vid)):
                continue
            # A way from where the car is (its edge, or its first one) to its destination; SUMO's
            # router respects the closed lanes. Not rerouteTraveltime: SUMO stops on a car it
            # cannot route.
            here = route[veh.idx] if veh is not None else route[0]
            new = None
            if veh is not None or here not in self._closed_edges:
                try:
                    found = list(c.simulation.findRoute(here, route[-1], vType=c.vehicle.getTypeID(vid)).edges)
                except Exception:
                    found = []
                if found and found[0] == here and not self._closed_edges.intersection(found[1:]):
                    new = found   # SUMO's route now starts at the car's edge (index 0)
                    try:
                        c.vehicle.setRoute(vid, found)
                        if self._lanes_shut and not self._valid(vid):
                            new = None
                    except Exception:
                        new = None
            if new is None:
                try:
                    if veh is not None:
                        c.vehicle.unsubscribe(vid)   # or SUMO keeps asking for a car it no longer has
                    c.vehicle.remove(vid)
                except Exception:  # pragma: no cover - already gone
                    pass
                self.vehicles.pop(vid, None)
                self._waiting.discard(vid)
                self._xy.pop(vid, None)
                self._internal.discard(vid)
                if self.fleet is not None:
                    self.fleet.leave(vid)
                self.no_way_round += 1
                continue
            if new == route:
                continue
            self.rerouted += 1
            self.routes[vid] = new
            if veh is not None:
                start = veh.cum[veh.idx] if veh.cum else 0.0     # distance driven to this edge so far
                veh.route, veh.idx = new, 0
                if veh.cum:
                    veh.cum = [start]
                    for r in new[:-1]:
                        veh.cum.append(veh.cum[-1] + self.net.edges[r].length)

    def _valid(self, vid) -> bool:
        try:
            return bool(self.conn.vehicle.isRouteValid(vid))
        except Exception:
            return False

    def _zone_check(self) -> None:
        """Seconds the DriveNow advice asks for more than a roadworks limit (every 0.6 s)."""
        now = self.real_time()
        for veh in self.vehicles.values():
            if not veh.equipped or not veh.route or veh.advice is None or veh.advice.target is None:
                continue
            limits = [ev.speed_limit for ev in self._road_events.values()
                      if ev.speed_limit and veh.edge in ev.edges and ev.active(now)]
            if limits:
                self.zone_time += 0.6
                if veh.advice.target > min(limits) + 2 / 3.6:
                    self.zone_speeding += 0.6

    def _feed_fleet(self) -> None:
        if self.fleet is None:
            self.fleet = FleetDB({e.id: e.length for e in self.net.edges.values()},
                                 car_space=self.advisor.car_space, share=self.penetration)
            self.advisor.gap_trust_fn = self.fleet.gap_trust
            if self.occupancy_source in ("fleet+flow", "fused"):
                self.advisor.segment_speed_fn = self._segment_speed
            self.fleet.events.update(self._road_events)
            if self._road_events:
                self._wire_road_events(self.fleet)
        self._fleet_clock -= self.dt
        if self._fleet_clock > 1e-9:
            return
        self._fleet_clock = 1.0  # a phone reports once a second
        for vid, veh in self.vehicles.items():
            if not veh.equipped or not veh.route:
                continue
            where = (veh.idx, veh.pos, veh.v) if veh.phone is None else self._estimated(veh)
            if where is not None:
                self.fleet.report(vid, self.t, veh.route[where[0]], where[1], where[2])
        if self.occupancy_source in ("fleet+flow", "fused"):
            self._emulate_flow()

    def _segment_speed(self, edge: str, t: float) -> Optional[float]:
        # Where loops count the queue at the light, the edge's mean speed (low on red) is left out.
        if self.estimator is not None and edge in self.estimator.edges:
            return None
        return self.fleet.segment_speed(edge, t)

    def _emulate_flow(self) -> None:
        """Aggregated speed per edge from every car on it, as a provider would publish it."""
        for veh in self.vehicles.values():
            if veh.route:
                acc = self._flow_sum.setdefault(veh.edge, [0.0, 0])
                acc[0] += veh.v
                acc[1] += 1
        if self.t - self._flow_start >= self.flow_window:
            for edge, (total, n) in self._flow_sum.items():
                due = self.t + self._flow_rng.uniform(*self.flow_delay)
                self._flow_pending.append((due, edge, total / n, self.net.edges[edge].speed, self.t))
            self._flow_sum, self._flow_start = {}, self.t
        due = [x for x in self._flow_pending if x[0] <= self.t]
        if due:
            self._flow_pending = [x for x in self._flow_pending if x[0] > self.t]
            for _, edge, speed, free, measured in due:
                self.fleet.segment(edge, speed, free, measured, "emulated")

    def _profile_of(self, veh: Vehicle) -> Optional[DriverProfile]:
        """How the advice thinks this car changes speed."""
        if self.profiles == "learned" and veh.learner is not None:
            return veh.learner.profile(self.advisor.profile)
        if self.profiles == "true" and veh.coast_true is not None:
            return replace(self.advisor.profile, coast_decel=veh.coast_true)  # what learning could reach
        return None

    def _drive_equipped(self) -> None:
        for vid, veh in self.vehicles.items():
            veh.doing = None
            adv = veh.followed(self.follow_shown)
            if not veh.equipped or adv is None or adv.target is None:
                continue
            coast = veh.coast_true if veh.coast_true is not None else self.advisor.profile.coast_decel
            to_line = self.net.edges[veh.edge].length - veh.pos
            if vid in self._internal or to_line < 10.0:
                # Inside or right before the junction SUMO's own driver decides:
                # never hold a car still on a junction with an old target.
                self.conn.vehicle.setSpeed(vid, -1)
                continue
            target = adv.target
            if adv.kind == "stop" and veh.next_control is not None:
                target = min(target, math.sqrt(2 * coast * max(to_line - 2.0, 0.0)))
            if adv.kind == "free":
                self.conn.vehicle.setSpeed(vid, -1)
            elif target < veh.v:
                self.conn.vehicle.setSpeed(vid, max(target, veh.v - coast * self.dt))
                veh.doing = "coast" if target < veh.v - 0.3 else None
            else:
                self.conn.vehicle.setSpeed(vid, target)
                veh.doing = "accel" if target > veh.v + 0.5 else None

    def occupancy(self) -> Occupancy:
        if self.occupancy_source != "truth" and self.fleet is not None:
            occ = self.fleet.occupancy(self.t)
            return occ if self.estimator is None else self.estimator.merge(occ, self.t)
        occ: Occupancy = {}
        for veh in self.vehicles.values():
            if veh.route:
                occ.setdefault(veh.edge, []).append((veh.pos, veh.v))
        for lst in occ.values():
            lst.sort()
        return occ

    def snapshot(self) -> Dict:
        rows = [vehicle_row(self.net, v.id, v.edge, v.pos, v.v, v.equipped, v.shown or v.advice, v.next_control,
                             self._xy.get(v.id), v.display.announcements)
                for v in self.vehicles.values() if v.route and v.id in self._xy]
        return {
            "t": round(self.t, 1),
            "vehicles": rows,
            "signals": signal_states(self.net, self.t),
            "stats": {"drivenow": self.stats[True].summary(), "normal": self.stats[False].summary(),
                      "live": len(self.vehicles)},
        }

    def sumo_state(self, node_id: str) -> str:
        node = self.net.nodes.get(node_id)
        return self.conn.trafficlight.getRedYellowGreenState(node.tl if node is not None and node.tl else node_id)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass
