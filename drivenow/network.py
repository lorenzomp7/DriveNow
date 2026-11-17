"""Road network: nodes (lights, roundabouts, give-way junctions) and edges.

Two ways to get one:

* ``demo_city()`` builds a small grid town with traffic lights, one
  roundabout and one give-way junction, so every kind of control appears.
* ``load_sumo_net(path)`` reads a SUMO ``.net.xml`` file, such as the grids
  in the ``data/`` folder of the Traffc_light_control repository.

Coordinates are metres, x to the east and y to the north. Traffic drives on
the right.
"""

from __future__ import annotations

import math
import random
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .signals import Phase, SignalPlan, two_group_plan

Point = Tuple[float, float]

SIGNAL = "signal"
ROUNDABOUT = "roundabout"
PRIORITY = "priority"
BORDER = "border"


@dataclass
class Node:
    id: str
    x: float
    y: float
    kind: str
    radius: float = 10.0
    plan: Optional[SignalPlan] = None
    group_of: Dict[str, str] = field(default_factory=dict)  # approach edge -> signal group
    major: Set[str] = field(default_factory=set)            # approach edges with right of way
    entry_speed: float = 25 / 3.6                           # roundabout / give-way crossing speed
    name: str = ""
    plan_source: str = ""                                   # 'sumo': read from the net file; 'drivenow': ours


@dataclass
class Edge:
    id: str
    from_node: str
    to_node: str
    length: float
    speed: float
    shape: List[Point]
    next_edges: List[str] = field(default_factory=list)
    name: str = ""

    def heading(self) -> float:
        (x0, y0), (x1, y1) = self.shape[0], self.shape[-1]
        return math.atan2(y1 - y0, x1 - x0)


class Network:
    def __init__(self, nodes: Dict[str, Node], edges: Dict[str, Edge], name: str = "") -> None:
        self.nodes = nodes
        self.edges = edges
        self.name = name
        self.in_edges: Dict[str, List[str]] = {n: [] for n in nodes}
        self.out_edges: Dict[str, List[str]] = {n: [] for n in nodes}
        for e in edges.values():
            self.out_edges[e.from_node].append(e.id)
            self.in_edges[e.to_node].append(e.id)
        self._seg_cache: Dict[str, List[Tuple[Point, Point, float, float]]] = {}

    # -- geometry ------------------------------------------------------------

    def _segments(self, edge_id: str) -> List[Tuple[Point, Point, float, float]]:
        segs = self._seg_cache.get(edge_id)
        if segs is None:
            shape = self.edges[edge_id].shape
            segs, acc = [], 0.0
            for a, b in zip(shape, shape[1:]):
                L = math.dist(a, b)
                segs.append((a, b, acc, L))
                acc += L
            self._seg_cache[edge_id] = segs
        return segs

    def point_at(self, edge_id: str, pos: float) -> Tuple[float, float, float]:
        """Position (x, y) and heading (radians) at ``pos`` metres along an edge."""
        edge = self.edges[edge_id]
        segs = self._segments(edge_id)
        geo_len = segs[-1][2] + segs[-1][3] if segs else 0.0
        s = pos * (geo_len / edge.length) if edge.length > 0 else 0.0
        for a, b, acc, L in segs:
            if s <= acc + L or (a, b) == segs[-1][:2]:
                f = 0.0 if L == 0 else min(max((s - acc) / L, 0.0), 1.0)
                return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, math.atan2(b[1] - a[1], b[0] - a[0])
        x, y = edge.shape[-1]
        return x, y, edge.heading()

    def bounds(self) -> Tuple[float, float, float, float]:
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        return min(xs), min(ys), max(xs), max(ys)

    # -- routing -------------------------------------------------------------

    def turn(self, from_edge: str, to_edge: str) -> str:
        """'s' straight, 'l' left, 'r' right, 't' turn around."""
        d = self.edges[to_edge].heading() - self.edges[from_edge].heading()
        d = (d + math.pi) % (2 * math.pi) - math.pi
        if abs(d) < math.radians(30):
            return "s"
        if abs(d) > math.radians(150):
            return "t"
        return "l" if d > 0 else "r"

    def path_to_border(self, edge_id: str) -> List[str]:
        """Shortest continuation (by edge count) from ``edge_id`` to a border."""
        if self.nodes[self.edges[edge_id].to_node].kind == BORDER:
            return []
        prev: Dict[str, Optional[str]] = {edge_id: None}
        q = deque([edge_id])
        while q:
            e = q.popleft()
            for n in self.edges[e].next_edges:
                if n in prev:
                    continue
                prev[n] = e
                if self.nodes[self.edges[n].to_node].kind == BORDER:
                    path = [n]
                    while prev[path[-1]] != edge_id:
                        path.append(prev[path[-1]])
                    return list(reversed(path))
                q.append(n)
        return []

    def random_route(self, start_edge: str, rng: random.Random, max_edges: int = 8) -> List[str]:
        """Random trip from ``start_edge`` to a border, mostly going straight."""
        route = [start_edge]
        weights = {"s": 4.0, "r": 1.0, "l": 1.0}
        while len(route) < max_edges:
            cur = route[-1]
            if self.nodes[self.edges[cur].to_node].kind == BORDER:
                return route
            options = [n for n in self.edges[cur].next_edges if n not in route]
            if not options:
                break
            w = [weights.get(self.turn(cur, n), 0.5) for n in options]
            route.append(rng.choices(options, weights=w)[0])
        if self.nodes[self.edges[route[-1]].to_node].kind != BORDER:
            route += self.path_to_border(route[-1])
        return route

    def entry_edges(self) -> List[str]:
        return [e.id for e in self.edges.values() if self.nodes[e.from_node].kind == BORDER]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def direction_group(edge: Edge) -> str:
    """'NS' for edges running mostly north-south, 'EW' otherwise."""
    (x0, y0), (x1, y1) = edge.shape[0], edge.shape[-1]
    return "NS" if abs(y1 - y0) > abs(x1 - x0) else "EW"


def _lane_shape(a: Node, b: Node, offset: float = 1.8) -> List[Point]:
    dx, dy = b.x - a.x, b.y - a.y
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    rx, ry = uy, -ux  # right-hand side
    p0 = (a.x + ux * a.radius + rx * offset, a.y + uy * a.radius + ry * offset)
    p1 = (b.x - ux * b.radius + rx * offset, b.y - uy * b.radius + ry * offset)
    return [p0, p1]


def _connect(nodes: Dict[str, Node], edges: Dict[str, Edge], a: str, b: str, speed: float, name: str = "") -> None:
    shape = _lane_shape(nodes[a], nodes[b])
    eid = f"{a}>{b}"
    edges[eid] = Edge(eid, a, b, math.dist(*shape), speed, shape, name=name)


def _link_turns(net_nodes: Dict[str, Node], edges: Dict[str, Edge]) -> None:
    by_from: Dict[str, List[Edge]] = {}
    for e in edges.values():
        by_from.setdefault(e.from_node, []).append(e)
    for e in edges.values():
        for n in by_from.get(e.to_node, []):
            if n.to_node != e.from_node:  # no U-turns
                e.next_edges.append(n.id)


# --------------------------------------------------------------------------
# Demo town
# --------------------------------------------------------------------------

def demo_city(seed: int = 7) -> Network:
    """A 3x3 grid town, 260 m blocks, 50 km/h.

    * Seven traffic lights with fixed-time plans (cycles of 60-80 s).
    * The bottom avenue (Viale Roma) is coordinated as a green wave at 45 km/h
      for traffic heading east.
    * The centre is a roundabout; the top-left junction is a give-way
      junction where north-south traffic has priority.
    """
    rng = random.Random(seed)
    spacing = 260.0
    reach = 220.0
    v_urban = 50 / 3.6
    v_wave = 45 / 3.6
    nodes: Dict[str, Node] = {}
    edges: Dict[str, Edge] = {}

    street_names_x = ["Via Verdi", "Via Mazzini", "Via Dante"]
    street_names_y = ["Viale Roma", "Corso Italia", "Via Garibaldi"]

    def nid(i: int, j: int) -> str:
        return f"J{i}{j}"

    for i in range(3):
        for j in range(3):
            x, y = i * spacing, j * spacing
            nodes[nid(i, j)] = Node(nid(i, j), x, y, SIGNAL, radius=10.0,
                                    name=f"{street_names_x[i]} / {street_names_y[j]}")
    nodes["J11"].kind = ROUNDABOUT
    nodes["J11"].radius = 18.0
    nodes["J11"].entry_speed = 25 / 3.6
    nodes["J11"].name = "Rotonda Piazza Centrale"
    nodes["J02"].kind = PRIORITY
    nodes["J02"].entry_speed = 20 / 3.6
    nodes["J02"].name = f"{street_names_x[0]} / {street_names_y[2]} (precedenza)"

    # Border stubs: one per perimeter direction.
    for i in range(3):
        nodes[f"S{i}"] = Node(f"S{i}", i * spacing, -reach, BORDER, radius=0.0)
        nodes[f"N{i}"] = Node(f"N{i}", i * spacing, 2 * spacing + reach, BORDER, radius=0.0)
    for j in range(3):
        nodes[f"W{j}"] = Node(f"W{j}", -reach, j * spacing, BORDER, radius=0.0)
        nodes[f"E{j}"] = Node(f"E{j}", 2 * spacing + reach, j * spacing, BORDER, radius=0.0)

    pairs: List[Tuple[str, str, str]] = []
    for j in range(3):
        row = [f"W{j}"] + [nid(i, j) for i in range(3)] + [f"E{j}"]
        pairs += [(a, b, street_names_y[j]) for a, b in zip(row, row[1:])]
    for i in range(3):
        col = [f"S{i}"] + [nid(i, j) for j in range(3)] + [f"N{i}"]
        pairs += [(a, b, street_names_x[i]) for a, b in zip(col, col[1:])]
    for a, b, name in pairs:
        _connect(nodes, edges, a, b, v_urban, name)
        _connect(nodes, edges, b, a, v_urban, name)
    _link_turns(nodes, edges)

    # Signal groups and plans.
    for node in nodes.values():
        approaches = [e for e in edges.values() if e.to_node == node.id]
        if node.kind == SIGNAL:
            node.group_of = {e.id: direction_group(e) for e in approaches}
            if node.y == 0:
                # Viale Roma: same 70 s cycle everywhere, more green to EW, and
                # EW green starts when a car leaving the west end at 45 km/h arrives.
                cycle, green_ew = 70.0, 38.0
                green_ns = cycle - 10 - green_ew
                plan = two_group_plan(green_ns, green_ew)
                ew_start = green_ns + 3 + 2
                plan.offset = (node.x / v_wave - ew_start) % cycle
            else:
                cycle = rng.choice([60.0, 70.0, 80.0])
                green_ns = rng.uniform(0.4, 0.6) * (cycle - 10)
                plan = two_group_plan(green_ns, cycle - 10 - green_ns, offset=rng.uniform(0, cycle))
            node.plan = plan
        elif node.kind == PRIORITY:
            node.major = {e.id for e in approaches if direction_group(e) == "NS"}

    return Network(nodes, edges, name="Città demo")


# --------------------------------------------------------------------------
# SUMO networks
# --------------------------------------------------------------------------

def _parse_shape(s: str) -> List[Point]:
    pts = []
    for pair in s.split():
        x, y = pair.split(",")[:2]
        pts.append((float(x), float(y)))
    return pts


def _sumo_char(c: str) -> str:
    if c in "Gg":
        return "G"
    if c in "yY":
        return "y"
    return "r"


def base_repo_cycle_plan(cycle_length: float = 40.0, yellow: float = 3.0) -> SignalPlan:
    """The CycleRuleSet of Traffc_light_control with uniform demand.

    There, NS and EW share ``cycle_length`` seconds of green (20 s each with
    the default 40) and each green is followed by a 3 s yellow, no all-red.
    """
    half = cycle_length / 2
    return two_group_plan(half, half, yellow=yellow, all_red=0.0)


def load_sumo_net(path: str, fallback_cycle: float = 40.0) -> Network:
    """Read a SUMO .net.xml into a Network.

    Traffic light programs with realistic durations are used as they are,
    with one signal group per approach edge. Programs with very long phases
    (the base repository uses 100000 s phases because its agent switches the
    lights itself) are replaced with ``base_repo_cycle_plan``, the fixed-time
    cycle of the repository's rule-based controller, so the future is known.
    """
    root = ET.parse(path).getroot()
    nodes: Dict[str, Node] = {}
    for j in root.iter("junction"):
        if j.attrib.get("type") == "internal":
            continue
        t = j.attrib["type"]
        if t.startswith("traffic_light"):
            kind = SIGNAL
        elif t == "dead_end":
            kind = BORDER
        else:
            kind = PRIORITY
        nodes[j.attrib["id"]] = Node(j.attrib["id"], float(j.attrib["x"]), float(j.attrib["y"]), kind, name=j.attrib["id"])

    edges: Dict[str, Edge] = {}
    for e in root.iter("edge"):
        if "function" in e.attrib:
            continue
        lane = e.find("lane")
        if lane is None:
            continue
        edges[e.attrib["id"]] = Edge(
            e.attrib["id"], e.attrib["from"], e.attrib["to"],
            float(lane.attrib["length"]), float(lane.attrib["speed"]),
            _parse_shape(lane.attrib["shape"]), name=e.attrib.get("name", ""),
        )

    tl_links: Dict[str, Dict[int, Tuple[str, str]]] = {}
    for c in root.iter("connection"):
        frm, to = c.attrib["from"], c.attrib["to"]
        if frm not in edges or to not in edges:
            continue
        if c.attrib.get("dir") != "t" and to not in edges[frm].next_edges:
            edges[frm].next_edges.append(to)
        if "tl" in c.attrib:
            tl_links.setdefault(c.attrib["tl"], {})[int(c.attrib["linkIndex"])] = (frm, c.attrib.get("dir", "s"))

    for r in root.iter("roundabout"):
        for n in r.attrib.get("nodes", "").split():
            if n in nodes:
                nodes[n].kind = ROUNDABOUT

    for node in nodes.values():
        ends = [math.dist(edges[e].shape[-1], (node.x, node.y)) for e in edges if edges[e].to_node == node.id]
        node.radius = max(ends) if ends else 0.0

    logics = {tl.attrib["id"]: tl for tl in root.iter("tlLogic")}
    for node in nodes.values():
        if node.kind != SIGNAL:
            continue
        approaches = [e for e in edges.values() if e.to_node == node.id]
        logic = logics.get(node.id)
        phases_xml = list(logic.iter("phase")) if logic is not None else []
        realistic = phases_xml and all(float(p.attrib["duration"]) < 1000 for p in phases_xml)
        links = tl_links.get(node.id, {})
        if realistic and links:
            # One group per approach edge, coloured like its straight movement.
            pick: Dict[str, int] = {}
            for idx, (frm, d) in sorted(links.items()):
                if frm not in pick or d == "s":
                    pick[frm] = idx
            phases = []
            for p in phases_xml:
                st = p.attrib["state"]
                phases.append(Phase(float(p.attrib["duration"]), {e: _sumo_char(st[i]) for e, i in pick.items()}))
            node.plan = SignalPlan(phases, offset=float(logic.attrib.get("offset", 0.0)))
            node.group_of = {e: e for e in pick}
            node.plan_source = "sumo"
        else:
            node.plan = base_repo_cycle_plan(fallback_cycle)
            node.group_of = {e.id: direction_group(e) for e in approaches}
            node.plan_source = "drivenow"

    return Network(nodes, edges, name=path.rsplit("/", 1)[-1])


def sumo_link_states(net_path: str, node_id: str, plan: SignalPlan, group_of: Dict[str, str]) -> List[Tuple[float, str]]:
    """Translate a plan into SUMO phases (duration, state string) for ``node_id``.

    Used to install DriveNow's fixed-time plan into a running SUMO, so that
    SUMO's lights and DriveNow's forecast are the same thing.
    """
    root = ET.parse(net_path).getroot()
    links: Dict[int, str] = {}
    for c in root.iter("connection"):
        if c.attrib.get("tl") == node_id:
            links[int(c.attrib["linkIndex"])] = c.attrib["from"]
    n = max(links) + 1 if links else 0
    out = []
    for p in plan.phases:
        chars = []
        for i in range(n):
            g = group_of.get(links.get(i, ""), "")
            s = p.states.get(g, "r")
            chars.append({"G": "G", "y": "y"}.get(s, "r"))
        out.append((p.duration, "".join(chars)))
    return out
