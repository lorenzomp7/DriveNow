"""SUMO around a real US work zone, with the work zones its WZDx feed reported.

A scenario (``tools/wzdx_build.py``, in data/wzdx/<name>/) holds the street map
from OpenStreetMap, assumed traffic, and the feed's work zones in the area as
they were read. The simulation's clock starts when they were read
(``clock0``), so each zone applies from its start to its end, as reported.

Every simulated car drives by the work zones: the lowered limit, the closed
lanes, a closed road with the cars sent another way (see SumoWorld). With
``events="unaware"`` the DriveNow advice does not know them.

There are no open signal timings for these roads: the lights are
OpenStreetMap's, running the fixed-time programme SUMO guesses. With
``lights="known"`` the advice knows that programme (as if the city broadcast
it, SPaT); with ``lights="learned"`` it learns each approach's timing from what
the DriveNow cars report (``probe.ProbeLearner``), as for the Hamburg lights
without data, and knows nothing about a light it has not learned.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from .advisor import Advisor
from .network import SIGNAL
from .probe import ProbeLearner
from .probe_reports import ProbeReports
from .road_events import match_all
from .simulation import GroupStats
from .sources import wzdx
from .sumo_world import SumoWorld

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "wzdx")


def scenarios():
    return sorted(d for d in os.listdir(DATA) if os.path.exists(os.path.join(DATA, d, "scenario.json"))) \
        if os.path.isdir(DATA) else []


class WzdxWorld(ProbeReports, SumoWorld):
    def __init__(self, scenario: str, penetration: float = 0.5, lights: str = "known", events: str = "aware",
                 seed: int = 1, dt: float = 0.2, gui: bool = False, label: str = "wzdx", scale: float = 1.0,
                 warmup: float = 0.0) -> None:
        if lights not in ("known", "learned") or events not in ("aware", "unaware", "none"):
            raise ValueError("lights: known|learned, events: aware|unaware|none")
        d = os.path.join(DATA, scenario)
        self.scenario = scenario
        self.info = json.load(open(os.path.join(d, "scenario.json")))
        super().__init__(os.path.join(d, "corridor.net.xml"), penetration=penetration, seed=seed, dt=dt, gui=gui,
                         label=label, route_file=os.path.join(d, "routes.rou.xml"), teleport=300, scale=scale)
        self.net.name = self.info.get("title", scenario)
        self.lights, self.events_mode, self.warmup = lights, events, warmup
        # Trips that started after the warm-up, and those of them that drove through a work zone.
        self.measured = {True: GroupStats(), False: GroupStats()}
        self.through_zone = {True: GroupStats(), False: GroupStats()}
        self.probe = ProbeLearner()
        self._probe_edges = {e for n in self.net.nodes.values() if n.kind == SIGNAL for e in self.net.in_edges[n.id]}
        self._probe_prev: Dict[str, tuple] = {}
        if lights == "learned":
            self.advisor = Advisor(self.net, windows_fn=self._learned_windows)
        # The work zones, as the feed reported them.
        self.clock0 = float(self.info["clock0"])
        raw = json.load(open(os.path.join(d, "events.json")))
        pts = json.load(open(os.path.join(d, "edge_points.json")))
        self.road_events = match_all(wzdx.parse({"features": raw["features"]}, "wzdx:" + raw["feed"]), pts)
        self.zone_edges = {e for ev in self.road_events if ev.kind != "other" for e in ev.edges}
        if events != "none":
            self.road_events_advice = events == "aware"
            self.load_road_events(self.road_events)

    def _learned_windows(self, edge: str, next_edge: Optional[str], t: float):
        if edge not in self._probe_edges:
            return None
        w = self.probe.green_windows(edge, t, 120)
        if w is None:
            return None   # not learned yet: no advice for this light, never a guessed green
        return w, "probe:" + edge, self.probe.timing(edge, t).level == "confirmed"

    def step(self) -> None:
        super().step()
        if self.lights == "learned":
            self._report_probes()

    def _on_arrival(self, veh) -> None:
        if veh.t_start >= self.warmup:
            self.measured[veh.equipped].add(veh, self.t)
            if self.zone_edges.intersection(veh.route):
                self.through_zone[veh.equipped].add(veh, self.t)
