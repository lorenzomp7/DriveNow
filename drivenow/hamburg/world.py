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
from ..estimator import QueueEstimator
from ..network import SIGNAL
from ..probe import ProbeLearner
from ..probe_reports import ProbeReports
from ..simulation import GroupStats
from ..sumo_world import SumoWorld
from .detectors import LoopEmulator, place_loops, recorded_passages
from .signals import GREEN, CyclePredictor, SignalHistory

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "hamburg")
SCENARIOS = ("gaertnerstrasse", "willy-brandt")


def scenario_dir(scenario: str) -> str:
    return os.path.join(DATA, scenario)

# Hamburg code -> SUMO signal character. Links without Hamburg data follow SUMO's own programme.
SUMO_CHAR = {3: "G", 6: "G", 2: "y", 4: "u", 1: "r", 5: "o", 0: "O", 9: "O"}
UI_CHAR = {3: "G", 6: "G", 2: "y", 4: "y", 1: "r"}


class HamburgWorld(ProbeReports, SumoWorld):
    def __init__(self, scenario: str = "gaertnerstrasse", penetration: float = 0.5, forecast: str = "predict",
                 seed: int = 1, dt: float = 0.2, gui: bool = False, label: str = "hamburg",
                 threshold: float = 0.8, scale: float = 1.0, road_events: Optional[str] = None,
                 warmup: float = 0.0, demand: str = "assumed", official_limits: bool = False,
                 crossings: bool = False) -> None:
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
                         gui=gui, label=label, teleport=300,
                         route_file=os.path.join(data_dir, {"assumed": "routes.rou.xml", "dtv": "routes_dtv.rou.xml"}[demand]),
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
        # Hamburg's loop detectors at the lights, emulated (see detectors.py). With the "fused"
        # source the advice sees the queues they imply (estimator.py); every 5 s the standing
        # cars at each light are compared with what "fleet" and "fused" would show.
        self._data_dir = data_dir
        self.det_offset = 2.0
        self.loops = None
        self._loop_em: Optional[LoopEmulator] = None
        self._queue_clock = 0.0
        self.queue_errors: Dict[str, Dict[str, List[Tuple[int, int]]]] = {}  # group -> source -> [(estimated, true)]
        # Trips that started after the warm-up (s).
        self.warmup = warmup
        self.measured = {True: GroupStats(), False: GroupStats()}
        # Road events read for this scenario (data/hamburg/<scenario>/road_events.json, see
        # hamburg/road_events.py): "aware" the advice knows them, "unaware" only the road has
        # them. They apply as they were when read (clock0): a "what if" on the recorded hour,
        # whose lights stay those recorded in 2023.
        self.road_events: List = []
        if road_events is not None:
            self._load_road_events(road_events)
        # Hamburg's open street data (public_data.json, see hamburg/public_data.py): the
        # official limits at the recorded hour, on the advice's map and on SUMO's lanes; the
        # zebra crossings, before which the advice does not ask to speed up.
        self.demand = demand
        self.official_limits: Dict[str, int] = {}
        self.crossings: Dict[str, List[float]] = {}
        if official_limits or crossings:
            self._load_public_data(official_limits, crossings)

    def _load_public_data(self, limits: bool, crossings: bool) -> None:
        from . import public_data as pd
        snap = json.load(open(os.path.join(self._data_dir, "public_data.json")))
        points = json.load(open(os.path.join(self._data_dir, "edge_points.json")))
        if limits:
            names = {e.id: e.name for e in self.net.edges.values()}
            self.official_limits = pd.limits(snap, points, names, self.T0)
            for e, kmh in self.official_limits.items():
                self.net.edges[e].speed = kmh / 3.6
                for i in range(self.conn.edge.getLaneNumber(e)):
                    self.conn.lane.setMaxSpeed(f"{e}_{i}", kmh / 3.6)
        if crossings:
            self.crossings = pd.crossings(snap, self.net, points)
            self.advisor.crossings_fn = lambda e: self.crossings.get(e, [])

    def _load_road_events(self, mode: str) -> None:
        from .road_events import on_network, read
        if mode not in ("aware", "unaware"):
            raise ValueError("road_events: aware or unaware")
        snap = json.load(open(os.path.join(self._data_dir, "road_events.json")))
        points = json.load(open(os.path.join(self._data_dir, "edge_points.json")))
        names = {e.id: e.name for e in self.net.edges.values()}
        self.clock0 = float(snap["read_utc"])
        self.road_events = on_network(read(snap), points, names, self.clock0)
        self.road_events_advice = mode == "aware"
        self.load_road_events(self.road_events)

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
        if veh.t_start >= self.warmup:
            self.measured[veh.equipped].add(veh, self.t)
        if self.along_corridor(veh.route):
            self.corridor_stats[veh.equipped].add(veh, self.t)

    # -- learning lights without data -------------------------------------------

    def step(self) -> None:
        if self.occupancy_source == "fused" and self.loops is None:
            self._setup_loops()
        super().step()
        if self.learn_lights:
            self._report_probes()
        if self.loops is not None:
            self._step_loops()

    # -- loop detectors ---------------------------------------------------------

    def _upstream(self, edge: str) -> Optional[str]:
        """The edge a queue on ``edge`` reaches back over: the one leading straight into it."""
        e = self.net.edges[edge]
        prev = [p for p in self.net.in_edges.get(e.from_node, []) if edge in self.net.edges[p].next_edges]
        straight = [p for p in prev if self.net.turn(p, edge) == "s"]
        cand = straight if straight else prev
        return cand[0] if len(cand) == 1 and self.net.nodes[e.from_node].kind != SIGNAL else None

    def _setup_loops(self) -> None:
        lengths = {e.id: e.length for e in self.net.edges.values()}
        self.loops = place_loops(self._data_dir, lengths, self.det_offset)
        self._loop_em = LoopEmulator(self.loops)
        self.estimator = QueueEstimator([(lp.edge, lp.lane) for lp in self.loops], lengths, self._upstream,
                                        car_space=self.advisor.car_space)
        # Each approach to a light: its last edge and the edges before it that its queue reaches over.
        self._approaches: Dict[str, List[str]] = {}
        for n in self.net.nodes.values():
            if n.kind == SIGNAL:
                for e in self.net.in_edges[n.id]:
                    chain, x = [], e
                    while x is not None and len(chain) < 6 and x not in chain:
                        chain.append(x)
                        x = self._upstream(x)
                    self._approaches[e] = chain

    def _step_loops(self) -> None:
        cars = [(v.edge, v.lane, v.pos) for vid, v in self.vehicles.items() if v.route and vid not in self._internal]
        # The colour of each loop's light first (yellow counts as red, unknown changes nothing),
        # then what the loops see.
        real = self.T0 + self.t
        for lp in self.loops:
            codes = [c for c in (self.history.code_at(ds, real) for ds in lp.signal_ds) if c in (1, 2, 3, 4, 6)]
            if codes:
                self.estimator.signal(lp.edge, lp.lane, self.t, any(c in GREEN for c in codes))
        for lp, occ in self._loop_em.step(cars):
            self.estimator.event(lp.edge, lp.lane, self.t, occ)
        # A DriveNow car driving through close to the line without stopping: no queue left there.
        for vid, v in self.vehicles.items():
            if v.equipped and v.route and v.edge in self.estimator.edges and v.v > 5.0 \
                    and self.net.edges[v.edge].length - v.pos < 15.0:
                self.estimator.drove_through(v.edge)
        self._queue_clock -= self.dt
        if self._queue_clock <= 1e-9 and self.fleet is not None:
            self._queue_clock = 5.0
            truth: Dict[str, int] = defaultdict(int)
            for vid, v in self.vehicles.items():
                if v.route and vid not in self._internal and v.v < 2.0:
                    truth[v.edge] += 1
            fleet = self.fleet.occupancy(self.t)
            fused = self.estimator.merge(fleet, self.t)
            for e, chain in self._approaches.items():
                group = "loops" if e in self.estimator.edges else "others"
                real = sum(truth[x] for x in chain)
                for name, occ in (("fleet", fleet), ("fused", fused)):
                    est = sum(1 for x in chain for _, u in occ.get(x, []) if u < 2.0)
                    self.queue_errors.setdefault(group, {}).setdefault(name, []).append((est, real))
                    self.queue_errors.setdefault("all", {}).setdefault(name, []).append((est, real))

    def loop_counts(self) -> List[Tuple[str, int, int]]:
        """(Hamburg lane connection, cars the emulated loop counted, cars the real one counted)
        over the time simulated so far."""
        rec = recorded_passages(self._data_dir, self.loops, self.T0, self.T0 + self.t)
        return [(lp.thing, lp.passages, rec.get(lp.ds, 0)) for lp in self.loops]

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
