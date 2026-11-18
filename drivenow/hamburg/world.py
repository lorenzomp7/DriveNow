"""SUMO on Hamburg's real street map, with the real recorded traffic lights.

Every step the lights in SUMO are set to the state Hamburg recorded at the
same moment (14 September 2023, from 17:00 local time by default).

DriveNow does not peek at that recording. Its advice uses the forecast in
``signals.CyclePredictor``, built only from what happened before the current
second. With ``forecast="oracle"`` it uses the true future instead: an upper
bound for what a perfect forecast would give.
"""

from __future__ import annotations

import json
import math
import os
import random
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..advisor import Advisor
from ..network import SIGNAL
from ..probe import ProbeLearner
from ..simulation import GroupStats
from ..sumo_world import SumoWorld
from .signals import GREEN, CyclePredictor, SignalHistory

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "hamburg")
SCENARIOS = ("gaertnerstrasse", "willy-brandt")


def scenario_dir(scenario: str) -> str:
    return os.path.join(DATA, scenario)

# Hamburg code -> SUMO signal character. Links without Hamburg data follow SUMO's own programme.
SUMO_CHAR = {3: "G", 6: "G", 2: "y", 4: "u", 1: "r", 5: "o", 0: "O", 9: "O"}
UI_CHAR = {3: "G", 6: "G", 2: "y", 4: "y", 1: "r"}


class HamburgWorld(SumoWorld):
    def __init__(self, scenario: str = "gaertnerstrasse", penetration: float = 0.5, forecast: str = "predict",
                 seed: int = 1, dt: float = 0.2, gui: bool = False, label: str = "hamburg",
                 threshold: float = 0.8, scale: float = 1.0) -> None:
        data_dir = scenario_dir(scenario)
        scen = json.load(open(os.path.join(data_dir, "scenario.json")))
        self.scenario = scenario
        self.T0 = scen["start"]
        self.forecast = forecast
        self.history = SignalHistory.load(os.path.join(data_dir, "signals.csv.gz"))
        lanes = json.load(open(os.path.join(data_dir, "lanes.json")))
        cycle_ds = {t["datastreams"]["primary_signal"]: t["datastreams"]["cycle_second"]
                    for t in lanes if "primary_signal" in t["datastreams"] and "cycle_second" in t["datastreams"]}
        self.predictor = CyclePredictor(self.history, cycle_ds, threshold=threshold)
        self.links: Dict[str, dict] = json.load(open(os.path.join(data_dir, "links.json")))
        self._tls_links: Dict[str, List[Tuple[int, dict]]] = defaultdict(list)
        for key, rec in self.links.items():
            tls, idx = key.split("|")
            self._tls_links[tls].append((int(idx), rec))
        self._last_state: Dict[str, str] = {}
        super().__init__(os.path.join(data_dir, "corridor.net.xml"), penetration=penetration, seed=seed, dt=dt,
                         gui=gui, label=label, route_file=os.path.join(data_dir, "routes.rou.xml"), teleport=300,
                         scale=scale)
        self.net.name = scen.get("title", "Amburgo")
        self._index_movements()
        self.advisor = Advisor(self.net, windows_fn=self._windows)
        # Trips that mostly follow the corridor's main road (long approaches between lights).
        self.main_roads = set(scen.get("main_roads") or [])
        self.corridor_stats = {True: GroupStats(), False: GroupStats()}
        self._wcache: Dict[Tuple[int, int], Optional[List[Tuple[float, float]]]] = {}
        # Lights without Hamburg data: learn their timing from the DriveNow cars that pass them.
        self.learn_lights = True
        self.probe = ProbeLearner()
        self._probe_edges = {e for n in self.net.nodes.values() if n.kind == SIGNAL
                             for e in self.net.in_edges[n.id] if e not in self.edge_ds}
        self._probe_prev: Dict[str, Tuple[str, bool]] = {}

    # -- which recorded signal controls which movement ------------------------

    def _index_movements(self) -> None:
        self.move_ds: Dict[Tuple[str, str], int] = {}
        votes: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for rec in self.links.values():
            if not rec.get("ds"):
                continue
            frm, to = rec["from"], rec["to"]
            if frm not in self.net.edges or to not in self.net.edges:
                continue
            self.move_ds.setdefault((frm, to), rec["ds"])
            # The map colours an approach by its straight-ahead movement.
            straight = self.net.turn(frm, to) == "s"
            votes[frm][rec["ds"]] += (2.0 if straight else 1.0) * (2.0 if rec["how"] == "direct" else 1.0)
        self.edge_ds = {e: max(v.items(), key=lambda kv: kv[1])[0] for e, v in votes.items()}
        for node in self.net.nodes.values():
            if node.kind == SIGNAL:
                node.plan = None
                node.group_of = {e: str(self.edge_ds[e]) for e in self.net.in_edges[node.id] if e in self.edge_ds}

    def _windows(self, edge: str, next_edge: Optional[str], t: float):
        ds = self.move_ds.get((edge, next_edge)) if next_edge else None
        if ds is None:
            ds = self.edge_ds.get(edge)
        if ds is None:
            if self.learn_lights and edge in self._probe_edges:
                w = self.probe.green_windows(edge, t, 120)
                if w is None:
                    return None
                return w, "probe:" + edge, self.probe.timing(edge, t).level == "confirmed"
            return None
        key = (ds, int(t * 2))
        if key in self._wcache:
            w = self._wcache[key]
        else:
            real = self.T0 + t
            if self.forecast == "oracle":
                w = self.history.green_windows(ds, real, 120) if ds in self.history else None
            else:
                w = self.predictor.green_windows(ds, real, 120)
            if len(self._wcache) > 20000:
                self._wcache.clear()
            self._wcache[key] = w
        if w is None:
            return None  # nothing known about this light: no advice for it, rather than "never green"
        return w, str(ds)

    def along_corridor(self, route) -> bool:
        """At least 60% of the trip's length is on the main road."""
        total = sum(self.net.edges[e].length for e in route if e in self.net.edges)
        main = sum(self.net.edges[e].length for e in route
                   if e in self.net.edges and self.net.edges[e].name in self.main_roads)
        return total > 0 and main / total >= 0.6

    def _on_arrival(self, veh) -> None:
        if self.along_corridor(veh.route):
            self.corridor_stats[veh.equipped].add(veh, self.t)

    # -- learning lights without data -------------------------------------------

    def step(self) -> None:
        super().step()
        if self.learn_lights:
            self._report_probes()

    def _report_probes(self) -> None:
        """What each DriveNow car tells about the light ahead: waiting, driving off, crossing."""
        for vid, veh in self.vehicles.items():
            if not veh.equipped or not veh.route:
                continue
            edge, inside = veh.edge, vid in self._internal
            prev = self._probe_prev.get(vid)
            if prev is not None and prev[0] in self._probe_edges and not prev[1] and (inside or edge != prev[0]):
                self.probe.report(self.t, vid, prev[0], 0.0, veh.v, crossed=True)
            if edge in self._probe_edges and not inside:
                to_line = self.net.edges[edge].length - veh.pos
                self.probe.report(self.t, vid, edge, to_line, veh.v, crossed=False)
            self._probe_prev[vid] = (edge, inside)
        if len(self._probe_prev) > len(self.vehicles) + 200:
            for vid in [v for v in self._probe_prev if v not in self.vehicles]:
                del self._probe_prev[vid]
                self.probe.forget(vid)

    # -- driving SUMO's lights from the recording --------------------------------

    def _install_plans(self) -> None:
        # Keep SUMO's own (guessed) programme for links without Hamburg data.
        self._fallback: Dict[str, Tuple[List[Tuple[float, str]], float]] = {}
        self._fallback_offset: Dict[str, float] = {}
        for tls in self._tls_links:
            logic = self.conn.trafficlight.getAllProgramLogics(tls)[0]
            phases = [(p.duration, p.state) for p in logic.phases]
            self._fallback[tls] = (phases, sum(d for d, _ in phases))
        self._covered = {tls for tls, links in self._tls_links.items() if any(r.get("ds") for _, r in links)}
        self._before_step()

    def replan(self, seed: int = 0) -> None:
        """Switch every light without Hamburg data to another fixed-time plan.

        Cities change their plans at set times of day (peak, off-peak, night). For a
        test of how quickly the timings learnt from the cars notice it: each light's
        greens get 20% shorter to 25% longer (in whole seconds, as real plans), so the
        cycle changes too, and the cycle starts at a random new point.
        """
        import traci

        rng = random.Random(seed)
        for tls in sorted(self._fallback):
            phases, _ = self._fallback[tls]
            f = rng.uniform(0.8, 1.25)
            new = [(float(max(1, round(d * f))) if ("G" in s or "g" in s) else d, s) for d, s in phases]
            cycle = sum(d for d, _ in new)
            self._fallback[tls] = (new, cycle)
            self._fallback_offset[tls] = rng.uniform(0, cycle)
            if tls not in self._covered:
                # SUMO runs this light by itself: hand it the new plan.
                logic = traci.trafficlight.Logic("replan", 0, 0, [traci.trafficlight.Phase(d, s) for d, s in new])
                self.conn.trafficlight.setProgramLogic(tls, logic)
                self.conn.trafficlight.setProgram(tls, "replan")
                self.conn.trafficlight.setPhase(tls, rng.randrange(len(new)))

    def _fallback_char(self, tls: str, idx: int, t: float) -> str:
        phases, cycle = self._fallback[tls]
        tc = (t + self._fallback_offset.get(tls, 0.0)) % cycle
        for d, st in phases:
            if tc < d:
                return st[idx]
            tc -= d
        return phases[-1][1][idx]

    def _before_step(self) -> None:
        real = self.T0 + self.t + self.dt
        for tls, links in self._tls_links.items():
            if tls not in self._covered:
                continue  # no Hamburg data at all: SUMO runs its own programme
            chars = []
            for idx, rec in sorted(links):
                ds = rec.get("ds")
                if not ds or ds not in self.history:
                    chars.append(self._fallback_char(tls, idx, self.t + self.dt))
                    continue
                c = SUMO_CHAR.get(self.history.code_at(ds, real), "O")
                if c == "G" and rec["how"] != "direct":
                    c = "g"  # uncertain match: green, but yield to other movements
                chars.append(c)
            state = "".join(chars)
            if self._last_state.get(tls) != state:
                self.conn.trafficlight.setRedYellowGreenState(tls, state)
                self._last_state[tls] = state

    # -- what the map shows --------------------------------------------------------

    def snapshot(self) -> Dict:
        snap = super().snapshot()
        signals: Dict[str, Dict[str, list]] = {}
        real = self.T0 + self.t
        wanted: Dict[str, set] = defaultdict(set)
        for node in self.net.nodes.values():
            if node.kind == SIGNAL:
                wanted[node.id].update(node.group_of.values())
        for v in self.vehicles.values():  # the exact movement each car is heading for
            nc = v.next_control
            if nc is not None and nc.kind == "signal" and nc.group:
                wanted[nc.node].add(nc.group)
        for node_id, groups_wanted in wanted.items():
            if not groups_wanted:
                continue
            groups = {}
            for ds_s in groups_wanted:
                certain = True
                if ds_s.startswith("probe:"):
                    # Learnt from the cars: show the forecast, the only thing DriveNow knows.
                    w = self.probe.green_windows(ds_s[6:], self.t, 120)
                    st = "G" if w and w[0][0] <= 0 else "r"
                    tm = self.probe.timing(ds_s[6:], self.t)
                    certain = tm is not None and tm.level == "confirmed"
                else:
                    ds = int(ds_s)
                    st = UI_CHAR.get(self.history.code_at(ds, real), "r")
                    w = self._windows_for_ui(ds)
                change, nxt = None, None
                if w:
                    if st == "G" and w[0][0] <= 0:
                        change, nxt = w[0][1], "y"
                    else:
                        first = next((a for a, b in w if a > 0), None)
                        if first is not None:
                            change, nxt = first, "G"
                groups[ds_s] = [st, None if change is None else round(change, 1), nxt, certain]
            signals[node_id] = groups
        snap["signals"] = signals
        snap["clock"] = real
        return snap

    def _windows_for_ui(self, ds: int):
        key = (ds, int(self.t * 2))
        if key in self._wcache:
            return self._wcache[key]
        real = self.T0 + self.t
        return (self.history.green_windows(ds, real, 120) if self.forecast == "oracle"
                else self.predictor.green_windows(ds, real, 120))
