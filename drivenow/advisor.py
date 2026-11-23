"""Turns network + live traffic into speed advice and into the map layer.

The advisor knows nothing about where the traffic comes from. The built-in
simulation and the SUMO bridge both hand it the same thing: for each edge,
the vehicles on it as ``(position, speed)`` pairs sorted by position.
"""

from __future__ import annotations

import math
from dataclasses import replace, dataclass, field
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
    intersect_windows,
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
    # The next lights on the route, nearest first: (node, signal group, distance, approach edge).
    lights: List[Tuple[str, str, float, str]] = field(default_factory=list)


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
        # Which way the car turns at the junctions ahead: "known" (a route is set), or not known:
        # "straight" assumes it goes straight on, "common" uses at the next light only the green
        # that every way out shares. Within ``commit_distance`` of the line the lane the car is in
        # gives the turn away (0: never).
        self.lights_shown = 2   # lights ahead on the route the driver is shown (the map dims the others)
        self.turns = "known"
        self.commit_distance = 50.0
        self.follower_gap = 30.0  # m
        self.uncertain_drop = 10 / 3.6  # m/s: most a suspected light may slow a car (see glosa.advise)
        self.windows_fn = windows_fn
        # Where the other cars come from on the road (see fleet.py): aggregated traffic per edge,
        # (edge, time) -> speed in m/s of slow traffic there, or None; and whether the cars seen
        # show every gap in the main-road traffic, (node, time) -> bool. None: not used.
        self.segment_speed_fn: Optional[Callable[[str, float], Optional[float]]] = None
        self.gap_trust_fn: Optional[Callable[[str, float], bool]] = None
        # What is in the way (road_events.py, through FleetDB): a temporary speed limit on an
        # edge, (edge, time) -> m/s or None; and a closure, (edge, time) -> the event or None.
        self.limit_fn: Optional[Callable[[str, float], Optional[float]]] = None
        # Zebra crossings (edge -> positions in m from its start): within ``crossing_hold`` m before
        # one the advice does not ask to speed up.
        self.crossings_fn: Optional[Callable[[str], List[float]]] = None
        self.crossing_hold = 30.0
        self.blocked_fn: Optional[Callable[[str, float], object]] = None
        # A light reported out of order, (approach edge, time) -> bool: its timing is not used.
        self.signal_fault_fn: Optional[Callable[[str, float], bool]] = None
        self.profile = profile
        self.margins = margins
        self.horizon = horizon
        self.lookahead = lookahead
        self.max_signals = max_signals

    # -- traffic on the approach ----------------------------------------------

    def _traffic_ahead(self, edge_id: str, pos: float, occupancy: Occupancy,
                       t: Optional[float] = None) -> Tuple[int, float]:
        """Queue length ahead of ``pos`` and the earliest arrival behind a moving leader.

        With aggregated traffic (``segment_speed_fn``), slow traffic on the edge also
        bounds the arrival, for the cars ahead that are not seen.
        """
        edge = self.net.edges[edge_id]
        earliest = 0.0
        if self.segment_speed_fn is not None and t is not None:
            slow = self.segment_speed_fn(edge_id, t)
            if slow:
                earliest = (edge.length - pos) / slow
        ahead = [(p, v) for p, v in occupancy.get(edge_id, []) if p > pos + 0.5]
        if not ahead:
            return 0, earliest
        queue = sum(1 for p, v in ahead if v < STOPPED)
        leader_pos, leader_v = ahead[0]
        if leader_v >= STOPPED:
            earliest = max(earliest, (edge.length - leader_pos) / leader_v + self.margins.follow_headway)
        return queue, earliest

    def _signal(self, edge_id: str, next_edge: Optional[str], t: float):
        """Green windows and group for a movement, from the source or the node's plan."""
        if self.signal_fault_fn is not None and self.signal_fault_fn(edge_id, t):
            return None   # out of order: nothing is known about it, and an unknown light is no green
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
                     occupancy: Occupancy, foes, t: Optional[float] = None) -> Control:
        node = self.net.nodes[node_id]
        if current and self.considerate and self._follower_close(edge_id, pos, occupancy):
            return Control("yield", dist, node_id, entry_speed=node.entry_speed)
        if self.gap_trust_fn is not None and t is not None and not self.gap_trust_fn(node_id, t):
            # Main-road cars that are not seen may fill any gap: give way as usual.
            return Control("yield", dist, node_id, entry_speed=node.entry_speed)
        earliest = 0.0
        if current:
            queue, earliest = self._traffic_ahead(edge_id, pos, occupancy, t)
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

    def guessed_route(self, route: Sequence[str], idx: int, pos: float) -> Tuple[List[str], int]:
        """The route as known without a destination, and how many of its edges are the real ones.

        The car is where it is; beyond, it is assumed to go straight on. Close to the line
        the lane it is in tells which way it turns at the junction ahead.
        """
        known = idx + 1
        if (idx + 1 < len(route) and self.commit_distance > 0
                and self.net.edges[route[idx]].length - pos <= self.commit_distance):
            known = idx + 2
        guess = list(route[:known])
        cur, dist = guess[-1], 0.0
        while dist < self.lookahead:
            ways = [n for n in self.net.edges[cur].next_edges if self.net.turn(cur, n) != "t"]
            if not ways:
                break
            cur = next((n for n in ways if self.net.turn(cur, n) == "s"), ways[0])
            if cur in guess:
                break
            guess.append(cur)
            dist += self.net.edges[cur].length
        return guess, known

    def controls_ahead(
        self, route: Sequence[str], idx: int, pos: float, t: float, occupancy: Occupancy, v: float = 0.0,
        turn_options: Optional[Sequence[str]] = None,
    ) -> Tuple[List[Control], Optional[NextControl]]:
        """Controls along ``route``. With ``turn_options``, the first light ahead is taken as green
        only when it is green for every one of those ways out of it."""
        first_light = True
        lights: List[Tuple[str, str, float, str]] = []
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
        prev_limit = self._limit(route[idx], t)
        for k in range(idx, len(route)):
            edge = self.net.edges[route[k]]
            start = dist - (pos if k == idx else 0.0)  # distance to where this edge begins
            if k > idx and (self.limit_fn is not None or self.blocked_fn is not None):
                if self.blocked_fn is not None and self.blocked_fn(edge.id, t):
                    # The road is closed from here: the car will have to stop before it.
                    controls.append(Control("yield", max(start - 2.0, 0.0), "closure", entry_speed=0.0,
                                            shown_distance=start))
                    first = first or NextControl("closure", "closure", start)
                    break
                lim = self._limit(edge.id, t)
                # Roadworks ahead: a temporary limit below the street's own, and below where we
                # drive now. An ordinary drop of the posted limit is not one (and is not
                # anticipated without road events either).
                if lim < edge.speed - 0.5 and lim < prev_limit - 0.5:
                    controls.append(Control("limit", start, "works", entry_speed=lim))
                    first = first or NextControl("works", "works", start, str(round(lim * 3.6)))
                prev_limit = lim
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
                if first_light and turn_options and sig is not None:
                    for way in turn_options:
                        other = self._signal(edge.id, way, t)
                        if other is not None:
                            sig = (intersect_windows(sig[0], other[0]), sig[1],
                                   (sig[2] if len(sig) > 2 else True) and (other[2] if len(other) > 2 else True))
            if node.kind == SIGNAL:
                first_light = False
            if sig is not None:
                windows, group = sig[0], sig[1]
                certain = sig[2] if len(sig) > 2 else True
                queue, earliest = (0, 0.0)
                if k == idx:
                    queue, earliest = self._traffic_ahead(edge.id, pos, occupancy, t)
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
                if len(lights) < self.lights_shown:
                    lights.append((node.id, group, dist, edge.id))
            elif node.kind == ROUNDABOUT:
                controls.append(Control("yield", dist, node.id, entry_speed=node.entry_speed))
                first = first or NextControl("roundabout", node.id, dist)
            elif node.kind == PRIORITY and edge.id not in node.major:
                if self.gap_aware and node.right_before_left:
                    # No main road: give way to whoever comes from the right.
                    foes = {f for f in self.net.in_edges[node.id] if f != edge.id and self.net.turn(f, edge.id) == "r"}
                    controls.append(self._gap_control(edge.id, node.id, dist, k == idx, pos, occupancy, foes, t))
                elif self.gap_aware:
                    foes = node.major
                    nxt = route[k + 1] if k + 1 < len(route) else None
                    if nxt is not None and self.net.turn(edge.id, nxt) == "r":
                        # Turning right only merges with the main-road traffic heading the same way.
                        same_way = {e for e in node.major if nxt in self.net.edges[e].next_edges}
                        foes = same_way or foes
                    controls.append(self._gap_control(edge.id, node.id, dist, k == idx, pos, occupancy, foes, t))
                else:
                    controls.append(Control("yield", dist, node.id, entry_speed=node.entry_speed))
                first = first or NextControl("yield", node.id, dist)
            elif (node.kind == PRIORITY and self.gap_aware and self.gap_left_turns and k + 1 < len(route)
                  and self.net.turn(edge.id, route[k + 1]) == "l" and len(node.major) > 1):
                # Turning left off the main road: give way to the oncoming main-road traffic.
                controls.append(self._gap_control(edge.id, node.id, dist, k == idx, pos, occupancy,
                                                  node.major - {edge.id}, t))
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
        if first is not None:
            first.lights = lights
        return controls, first

    def advise(
        self, route: Sequence[str], idx: int, pos: float, v: float, t: float, occupancy: Occupancy,
        profile: Optional[DriverProfile] = None,
    ) -> Tuple[Advice, Optional[NextControl]]:
        """Advice for one car; ``profile`` is how that car changes speed, if known (else the default)."""
        options = None
        if self.turns != "known":
            route, known = self.guessed_route(route, idx, pos)
            if self.turns == "common":
                # The first light ahead: unless the car has already taken its way out of it,
                # use only the green that all of its ways out share.
                dist = -pos
                for k in range(idx, len(route)):
                    dist += self.net.edges[route[k]].length
                    if dist > self.lookahead:
                        break
                    if self.net.nodes[self.net.edges[route[k]].to_node].kind == SIGNAL:
                        if k + 1 >= known:
                            options = [n for n in self.net.edges[route[k]].next_edges
                                       if self.net.turn(route[k], n) != "t"]
                        break
        controls, first = self.controls_ahead(route, idx, pos, t, occupancy, v, options)
        limit = self._limit(route[idx], t)
        adv = advise(controls, v, limit, profile or self.profile, self.margins, self.max_signals,
                     self.uncertain_drop)
        if "yield:closure" in adv.notes or "limit:works" in adv.notes:
            # A closed road or roadworks ahead is what sets the speed now: tell the driver.
            name = "closure" if "yield:closure" in adv.notes else "works"
            c = next(c for c in controls if c.node == name)
            d = c.shown_distance if c.shown_distance is not None else c.distance
            first = NextControl(name, name, d, "" if name == "closure" else str(round(c.entry_speed * 3.6)),
                                first.lights if first is not None else [])
        if self.crossings_fn is not None and adv.target is not None and adv.target > v:
            d = self._crossing_ahead(route, idx, pos)
            if d is not None and d <= self.crossing_hold:
                adv = replace(adv, target=v, notes=adv.notes + ["hold:crossing"])
                first = NextControl("crossing", "crossing", d, "", first.lights if first is not None else [])
        if "yield:queue" in adv.notes:
            # The traffic ahead is what sets the speed now: tell the driver about it.
            q = next(c for c in controls if c.node == "queue")
            d = q.shown_distance if q.shown_distance is not None else q.distance
            first = NextControl("queue", "queue", d, str(round(q.entry_speed * 3.6)),
                                first.lights if first is not None else [])
        return adv, first

    def _crossing_ahead(self, route: Sequence[str], idx: int, pos: float) -> Optional[float]:
        """Metres to the next zebra crossing on the route, within ``crossing_hold``."""
        start = -pos
        for k in range(idx, len(route)):
            for p in self.crossings_fn(route[k]):
                if start + p >= 0.0:
                    return start + p
            start += self.net.edges[route[k]].length
            if start > self.crossing_hold:
                return None
        return None

    def _limit(self, edge_id: str, t: float) -> float:
        """The speed limit on an edge now: its own, or a lower temporary one (roadworks)."""
        limit = self.net.edges[edge_id].speed
        if self.limit_fn is not None:
            tmp = self.limit_fn(edge_id, t)
            if tmp:
                limit = min(limit, tmp)
        return limit

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
