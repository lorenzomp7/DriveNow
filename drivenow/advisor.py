"""Turns network + live traffic into speed advice and into the map layer.

The advisor knows nothing about where the traffic comes from. The built-in
simulation and the SUMO bridge both hand it the same thing: for each edge,
the vehicles on it as ``(position, speed)`` pairs sorted by position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .glosa import (
    Advice,
    Control,
    DriverProfile,
    Margins,
    advise,
    coast_cap,
    constant_speed_band,
    effective_windows,
)
from .network import BORDER, PRIORITY, ROUNDABOUT, SIGNAL, Network

Occupancy = Dict[str, List[Tuple[float, float]]]  # edge -> [(pos, speed), ...] ascending pos

# Optional signal source: (approach edge, next edge or None, time) -> (green windows, group label),
# or None when that movement has no known signal. Used instead of the nodes' fixed plans.
WindowsFn = Callable[[str, Optional[str], float], Optional[Tuple[List[Tuple[float, float]], str]]]

STOPPED = 2.0  # m/s; slower than this counts as queued


@dataclass
class NextControl:
    kind: str          # 'signal' | 'roundabout' | 'yield'
    node: str
    distance: float
    group: str = ""


class Advisor:
    def __init__(
        self,
        net: Network,
        profile: DriverProfile = DriverProfile(),
        margins: Margins = Margins(),
        horizon: float = 180.0,
        lookahead: float = 700.0,
        max_signals: int = 1,
        windows_fn: Optional[WindowsFn] = None,
    ) -> None:
        self.net = net
        self.windows_fn = windows_fn
        self.profile = profile
        self.margins = margins
        self.horizon = horizon
        self.lookahead = lookahead
        self.max_signals = max_signals

    # -- traffic on the approach ----------------------------------------------

    def _traffic_ahead(self, edge_id: str, pos: float, occupancy: Occupancy) -> Tuple[int, float]:
        """Queue length ahead of ``pos`` and the earliest arrival behind a moving leader."""
        edge = self.net.edges[edge_id]
        ahead = [(p, v) for p, v in occupancy.get(edge_id, []) if p > pos + 0.5]
        if not ahead:
            return 0, 0.0
        queue = sum(1 for p, v in ahead if v < STOPPED)
        earliest = 0.0
        leader_pos, leader_v = ahead[0]
        if leader_v >= STOPPED:
            earliest = (edge.length - leader_pos) / leader_v + self.margins.follow_headway
        return queue, earliest

    def _signal(self, edge_id: str, next_edge: Optional[str], t: float):
        """Green windows and group for a movement, from the source or the node's plan."""
        if self.windows_fn is not None:
            return self.windows_fn(edge_id, next_edge, t)
        node = self.net.nodes[self.net.edges[edge_id].to_node]
        if node.plan is None:
            return None
        group = node.group_of.get(edge_id, "")
        return node.plan.green_windows(t, group, self.horizon), group

    # -- controls along a route -----------------------------------------------

    def controls_ahead(
        self, route: Sequence[str], idx: int, pos: float, t: float, occupancy: Occupancy
    ) -> Tuple[List[Control], Optional[NextControl]]:
        controls: List[Control] = []
        first: Optional[NextControl] = None
        dist = 0.0
        for k in range(idx, len(route)):
            edge = self.net.edges[route[k]]
            dist += edge.length - (pos if k == idx else 0.0)
            node = self.net.nodes[edge.to_node]
            if node.kind == BORDER:
                break
            sig = None
            if node.kind == SIGNAL:
                sig = self._signal(edge.id, route[k + 1] if k + 1 < len(route) else None, t)
            if sig is not None:
                windows, group = sig
                queue, earliest = (0, 0.0)
                if k == idx:
                    queue, earliest = self._traffic_ahead(edge.id, pos, occupancy)
                    if queue and windows and windows[0][0] <= 0:
                        # Green now, but the queue in front is still pulling away.
                        earliest = max(earliest, self.margins.startup_lost_time + queue * self.margins.queue_headway)
                controls.append(Control("signal", dist, node.id, windows, queue, earliest))
                first = first or NextControl("signal", node.id, dist, group)
            elif node.kind == ROUNDABOUT:
                controls.append(Control("yield", dist, node.id, entry_speed=node.entry_speed))
                first = first or NextControl("roundabout", node.id, dist)
            elif node.kind == PRIORITY and edge.id not in node.major:
                controls.append(Control("yield", dist, node.id, entry_speed=node.entry_speed))
                first = first or NextControl("yield", node.id, dist)
            if dist > self.lookahead:
                break
        return controls, first

    def advise(
        self, route: Sequence[str], idx: int, pos: float, v: float, t: float, occupancy: Occupancy
    ) -> Tuple[Advice, Optional[NextControl]]:
        controls, first = self.controls_ahead(route, idx, pos, t, occupancy)
        limit = self.net.edges[route[idx]].speed
        return advise(controls, v, limit, self.profile, self.margins, self.max_signals), first

    # -- the map layer --------------------------------------------------------

    def speed_field(self, t: float, occupancy: Occupancy, step: float = 20.0) -> Dict[str, List[List[Optional[float]]]]:
        """For every approach, the speed band to hold from each point onwards.

        Returns ``{edge_id: [[pos, low_kmh, high_kmh], ...]}``. For a traffic
        light ``low``/``high`` bound the speeds that arrive on green while
        cruising (``None`` for both means a red is unavoidable from there). For
        a roundabout or give-way point only ``high`` is set: the fastest speed
        from which lifting off is enough.
        """
        out: Dict[str, List[List[Optional[float]]]] = {}
        p = self.profile
        for edge in self.net.edges.values():
            node = self.net.nodes[edge.to_node]
            limit = edge.speed
            samples: List[List[Optional[float]]] = []
            positions = [s * step for s in range(int(edge.length // step) + 1)]
            sig = self._signal(edge.id, None, t) if node.kind == SIGNAL else None
            if sig is not None:
                raw = sig[0]
                queue = sum(1 for _, v in occupancy.get(edge.id, []) if v < STOPPED)
                wins = effective_windows(raw, self.margins, queue)
                for s in positions:
                    d = edge.length - s
                    best = None
                    for w in wins:
                        b = constant_speed_band(d, w, min(p.min_speed, limit), limit)
                        if b is not None and (best is None or b.high > best.high):
                            best = b
                    if best is None:
                        samples.append([round(s, 1), None, None])
                    else:
                        samples.append([round(s, 1), round(best.low * 3.6), round(best.high * 3.6)])
            elif node.kind == ROUNDABOUT or (node.kind == PRIORITY and edge.id not in node.major):
                for s in positions:
                    cap = min(limit, coast_cap(edge.length - s, node.entry_speed, p))
                    samples.append([round(s, 1), None, round(cap * 3.6)])
            else:
                continue
            out[edge.id] = samples
        return out
