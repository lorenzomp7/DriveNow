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
from typing import Dict, List, Optional

from .advisor import Advisor, NextControl, Occupancy
from .glosa import Advice
from .network import SIGNAL, load_sumo_net, sumo_link_states
from .simulation import GroupStats, Vehicle, record_motion, signal_states, vehicle_row


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
                      sumo_link_states(self.net_path, node.id, node.plan, node.group_of)]
            logic = traci.trafficlight.Logic("drivenow", 0, 0, phases)
            self.conn.trafficlight.setProgramLogic(node.id, logic)
            self.conn.trafficlight.setProgram(node.id, "drivenow")
            i, left = node.plan.locate(self.t)
            self.conn.trafficlight.setPhase(node.id, i)
            self.conn.trafficlight.setPhaseDuration(node.id, left)

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

        for vid in c.simulation.getDepartedIDList():
            c.vehicle.subscribe(vid, [tc.VAR_ROAD_ID, tc.VAR_LANEPOSITION, tc.VAR_SPEED,
                                      tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_ROUTE_INDEX])
            self.vehicles[vid] = Vehicle(vid, self.routes.get(vid, []), self.rng.random() < self.penetration, self.t)
        for vid in c.simulation.getArrivedIDList():
            veh = self.vehicles.pop(vid, None)
            self._xy.pop(vid, None)
            self._internal.discard(vid)
            if veh is not None:
                self.stats[veh.equipped].add(veh, self.t)
                self._on_arrival(veh)

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

        self._advice_clock -= self.dt
        if self._advice_clock <= 0:
            self._advice_clock = 0.6
            occ = self.occupancy()
            for veh in self.vehicles.values():
                if veh.route:
                    veh.advice, veh.next_control = self.advisor.advise(veh.route, veh.idx, veh.pos, veh.v, self.t, occ)
        self._drive_equipped()

    def _drive_equipped(self) -> None:
        coast = self.advisor.profile.coast_decel
        for vid, veh in self.vehicles.items():
            if not veh.equipped or veh.advice is None or veh.advice.target is None:
                continue
            to_line = self.net.edges[veh.edge].length - veh.pos
            if vid in self._internal or to_line < 10.0:
                # Inside or right before the junction SUMO's own driver decides:
                # never hold a car still on a junction with an old target.
                self.conn.vehicle.setSpeed(vid, -1)
                continue
            target = veh.advice.target
            if veh.advice.kind == "stop" and veh.next_control is not None:
                target = min(target, math.sqrt(2 * coast * max(to_line - 2.0, 0.0)))
            if veh.advice.kind == "free":
                self.conn.vehicle.setSpeed(vid, -1)
            elif target < veh.v:
                self.conn.vehicle.setSpeed(vid, max(target, veh.v - coast * self.dt))
            else:
                self.conn.vehicle.setSpeed(vid, target)

    def occupancy(self) -> Occupancy:
        occ: Occupancy = {}
        for veh in self.vehicles.values():
            if veh.route:
                occ.setdefault(veh.edge, []).append((veh.pos, veh.v))
        for lst in occ.values():
            lst.sort()
        return occ

    def snapshot(self) -> Dict:
        rows = [vehicle_row(self.net, v.id, v.edge, v.pos, v.v, v.equipped, v.advice, v.next_control, self._xy.get(v.id))
                for v in self.vehicles.values() if v.route and v.id in self._xy]
        return {
            "t": round(self.t, 1),
            "vehicles": rows,
            "signals": signal_states(self.net, self.t),
            "stats": {"drivenow": self.stats[True].summary(), "normal": self.stats[False].summary(),
                      "live": len(self.vehicles)},
        }

    def sumo_state(self, node_id: str) -> str:
        return self.conn.trafficlight.getRedYellowGreenState(node_id)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover
            pass
