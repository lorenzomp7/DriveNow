"""Turns network + live traffic into speed advice and into the map layer.

The advisor knows nothing about where the traffic comes from. The built-in
simulation and the SUMO bridge both hand it the same thing: for each edge,
the vehicles on it as ``(position, speed)`` pairs sorted by position.
"""

from __future__ import annotations

import math
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
# It may add a third item, false when the windows are only a suspected timing.
WindowsFn = Callable[[str, Optional[str], float], Optional[Tuple[List[Tuple[float, float]], str]]]

STOPPED = 2.0  # m/s; slower than this counts as queued


@dataclass
class NextControl:
    kind: str          # 'signal' | 'roundabout' | 'yield' | 'queue'
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
        gap_aware: bool = True,
    ) -> None:
        self.net = net
        # At give-way lines, look at the main-road traffic and aim for a gap in it.
        # Needs to know where the main-road cars are (a sensor at the junction, or
        # the cars themselves sharing their position).
        self.gap_aware = gap_aware
        self.gap_left_turns = True  # also when turning left off the main road, across oncoming traffic
        self.gap_before = 3.5    # s: enter at least this long before the next main-road car arrives
        self.gap_after = 1.5     # s: and at least this long after the previous one has passed
        self.observe = 150.0     # m of main road watched on each side
        self.queue_aware = True   # count queues over the whole route; coast up to a standing queue
        # Slow traffic ahead (not only a standing queue): lift off early enough to reach it at
        # its speed. Not for the queue of a light with a confident forecast: the green advice
        # already counts that queue. Off by default: in Hamburg's evening peak it cost
        # throughput and travel time (see the README); the standing-queue rule below stays.
        self.slow_traffic = False
        self.slow_diff = 15 / 3.6   # m/s: traffic this much slower than us counts as slow
        self.slow_moving = True     # moving slow traffic counts, not only standing queues...
        self.slow_min_gap = 0.0     # m: ...when at least this far ahead...
        self.slow_min_speed = 0.0   # m/s: ...and we drive at least this fast
        self.light_buffer = 50.0    # m: slow traffic this close to a known light (beyond its queue) is its queue
        self.car_space = 7.5        # m of road per queued car (length plus gap)
        self.considerate = True  # no early slowing for a gap with a car close behind
        self.follower_gap = 30.0  # m
        self.uncertain_drop = 10 / 3.6  # m/s: most a suspected light may slow a car (see glosa.advise)
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

    # -- give-way junctions ------------------------------------------------------

    def _follower_close(self, edge_id: str, pos: float, occupancy: Occupancy) -> bool:
        """Someone drives right behind us: slowing early for a gap would hold them up."""
        return any(pos - self.follower_gap < p < pos - 0.5 and v >= STOPPED for p, v in occupancy.get(edge_id, []))

    def _gap_control(self, edge_id: str, node_id: str, dist: float, current: bool, pos: float,
                     occupancy: Occupancy, foes) -> Control:
        node = self.net.nodes[node_id]
        if current and self.considerate and self._follower_close(edge_id, pos, occupancy):
            return Control("yield", dist, node_id, entry_speed=node.entry_speed)
        earliest = 0.0
        if current:
            queue, earliest = self._traffic_ahead(edge_id, pos, occupancy)
            earliest = max(earliest, queue * self.margins.queue_headway)
        return Control("gap", dist, node_id, windows=self.main_road_gaps(node_id, occupancy, foes),
                       earliest=earliest, entry_speed=self.net.nodes[node_id].entry_speed)

    def main_road_arrivals(self, node_id: str, occupancy: Occupancy, foes=None) -> List[float]:
        """Seconds until each watched main-road car reaches the junction."""
        out: List[float] = []

        def walk(edge_id: str, offset: float, depth: int) -> None:
            edge = self.net.edges[edge_id]
            for p, v in occupancy.get(edge_id, []):
                d = offset + edge.length - p
                if d > self.observe:
                    continue
                if v >= STOPPED:
                    out.append(d / v)
                elif d < 8.0:
                    out.append(0.0)  # waiting right at the junction: it is about to go
            # Main roads are often split into short edges: keep looking upstream.
            if depth < 3 and offset + edge.length < self.observe:
                for prev in self.net.in_edges.get(edge.from_node, []):
                    if edge_id in self.net.edges[prev].next_edges:
                        walk(prev, offset + edge.length, depth + 1)

        for e in self.net.nodes[node_id].major if foes is None else foes:
            walk(e, 0.0, 0)
        return sorted(out)

    def main_road_gaps(self, node_id: str, occupancy: Occupancy, foes=None) -> List[Tuple[float, float]]:
        """Times (from now) when no watched main-road car is close to the junction.

        Beyond what is watched nothing is known, so the last gap is open-ended:
        the advice is refreshed every second and the far end fills in as cars come into view.
        """
        gaps: List[Tuple[float, float]] = []
        free_from = 0.0
        for t in self.main_road_arrivals(node_id, occupancy, foes):
            a, b = t - self.gap_before, t + self.gap_after
            if a > free_from:
                gaps.append((free_from, a))
            free_from = max(free_from, b)
        gaps.append((free_from, 1e9))
        return gaps

    # -- controls along a route -----------------------------------------------

    def controls_ahead(
        self, route: Sequence[str], idx: int, pos: float, t: float, occupancy: Occupancy, v: float = 0.0
    ) -> Tuple[List[Control], Optional[NextControl]]:
        controls: List[Control] = []
        first: Optional[NextControl] = None
        dist = 0.0
        stopped = 0                       # cars standing between us and the current point of the route
        tail: Optional[float] = None      # distance to the nearest standing car ahead
        slow_below = STOPPED
        if self.slow_moving and v >= self.slow_min_speed:
            slow_below = max(STOPPED, v - self.slow_diff)
        slow: Optional[Tuple[float, float, int]] = None  # nearest slow car: distance, speed, cars before it
        seen = 0                          # cars ahead so far
        signal_queues: List[Tuple[float, int]] = []  # confident lights: distance, standing cars before them
        for k in range(idx, len(route)):
            edge = self.net.edges[route[k]]
            start = dist - (pos if k == idx else 0.0)  # distance to where this edge begins
            dist += edge.length - (pos if k == idx else 0.0)
            ahead = [(p, u) for p, u in occupancy.get(edge.id, []) if k != idx or p > pos + 0.5]
            standing = [p for p, u in ahead if u < STOPPED]
            if standing:
                stopped += len(standing)
                if tail is None:
                    tail = start + min(standing)
            if slow is None:
                for p, u in ahead:
                    if u < STOPPED or (u < slow_below and start + p >= self.slow_min_gap):
                        slow = (start + p, u, seen)
                        break
                    seen += 1
            node = self.net.nodes[edge.to_node]
            if node.kind == BORDER:
                break
            sig = None
            if node.kind == SIGNAL:
                sig = self._signal(edge.id, route[k + 1] if k + 1 < len(route) else None, t)
            if sig is not None:
                windows, group = sig[0], sig[1]
                certain = sig[2] if len(sig) > 2 else True
                queue, earliest = (0, 0.0)
                if k == idx:
                    queue, earliest = self._traffic_ahead(edge.id, pos, occupancy)
                # The queue can reach back over several edges (and over junctions before the light).
                if self.queue_aware:
                    queue = max(queue, stopped)
                if queue and windows and windows[0][0] <= 0:
                        # Green now, but the queue in front is still pulling away.
                        earliest = max(earliest, self.margins.startup_lost_time + queue * self.margins.queue_headway)
                controls.append(Control("signal", dist, node.id, windows, queue, earliest, certain=certain))
                if certain:
                    signal_queues.append((dist, stopped))
                first = first or NextControl("signal", node.id, dist, group)
            elif node.kind == ROUNDABOUT:
                controls.append(Control("yield", dist, node.id, entry_speed=node.entry_speed))
                first = first or NextControl("roundabout", node.id, dist)
            elif node.kind == PRIORITY and edge.id not in node.major:
                if self.gap_aware and node.right_before_left:
                    # No main road: give way to whoever comes from the right.
                    foes = {f for f in self.net.in_edges[node.id] if f != edge.id and self.net.turn(f, edge.id) == "r"}
                    controls.append(self._gap_control(edge.id, node.id, dist, k == idx, pos, occupancy, foes))
                elif self.gap_aware:
                    foes = node.major
                    nxt = route[k + 1] if k + 1 < len(route) else None
                    if nxt is not None and self.net.turn(edge.id, nxt) == "r":
                        # Turning right only merges with the main-road traffic heading the same way.
                        same_way = {e for e in node.major if nxt in self.net.edges[e].next_edges}
                        foes = same_way or foes
                    controls.append(self._gap_control(edge.id, node.id, dist, k == idx, pos, occupancy, foes))
                else:
                    controls.append(Control("yield", dist, node.id, entry_speed=node.entry_speed))
                first = first or NextControl("yield", node.id, dist)
            elif (node.kind == PRIORITY and self.gap_aware and self.gap_left_turns and k + 1 < len(route)
                  and self.net.turn(edge.id, route[k + 1]) == "l" and len(node.major) > 1):
                # Turning left off the main road: give way to the oncoming main-road traffic.
                controls.append(self._gap_control(edge.id, node.id, dist, k == idx, pos, occupancy,
                                                  node.major - {edge.id}))
                first = first or NextControl("yield", node.id, dist)
            if dist > self.lookahead:
                break
        q = None
        if self.queue_aware and self.slow_traffic:
            if slow is not None and slow[0] <= self.lookahead and not any(
                    d >= slow[0] and d - slow[0] <= n * self.car_space + self.light_buffer for d, n in signal_queues):
                # Slow or standing traffic ahead that no known light explains: reach it at its speed by
                # lifting off. The cars before it will have to slow down too, so aim behind them.
                d_slow, v_slow, before = slow
                gap = max(d_slow - before * self.car_space - 2.0, 0.0)
                # Coasting from v to v_slow behind a car that keeps moving needs only
                # (v - v_slow)^2 / (2 b) of gap: as a fixed point, that is this much further on.
                b = self.profile.coast_decel
                q = Control("yield", gap + v_slow * math.sqrt(2 * gap / b), "queue", entry_speed=v_slow,
                            shown_distance=gap)
        elif self.queue_aware and tail is not None and not any(c.kind == "signal" and c.certain for c in controls):
            # A queue ahead with no known light behind it (a light without data or with only a
            # suspected timing, a busy junction): coast up to its end instead of braking there.
            q = Control("yield", max(tail - 2.0, 0.0), "queue", entry_speed=0.0)
        if q is not None:
            d = q.shown_distance if q.shown_distance is not None else q.distance
            controls.insert(next((i for i, c in enumerate(controls) if c.distance > d), len(controls)), q)
        return controls, first

    def advise(
        self, route: Sequence[str], idx: int, pos: float, v: float, t: float, occupancy: Occupancy
    ) -> Tuple[Advice, Optional[NextControl]]:
        controls, first = self.controls_ahead(route, idx, pos, t, occupancy, v)
        limit = self.net.edges[route[idx]].speed
        adv = advise(controls, v, limit, self.profile, self.margins, self.max_signals, self.uncertain_drop)
        if "yield:queue" in adv.notes:
            # The traffic ahead is what sets the speed now: tell the driver about it.
            q = next(c for c in controls if c.node == "queue")
            d = q.shown_distance if q.shown_distance is not None else q.distance
            first = NextControl("queue", "queue", d, str(round(q.entry_speed * 3.6)))
        return adv, first

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
