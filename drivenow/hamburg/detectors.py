"""Hamburg's car detectors at the lights, placed on the SUMO network and emulated.

Hamburg publishes, for some lanes at its lights, the state of an induction loop
("Signal change request - car": a detector that asks for green). It only says
whether the loop is occupied; a car is one change from free to occupied, which
is how ``tools/hamburg_build.py`` counted the recorded traffic.

``place_loops`` puts one loop on the SUMO lane each detector watches, found from
``links.json`` (Hamburg lane connection -> SUMO light link) and the network's
connections (light link -> lane). Where on the lane the loop lies is not in the
data: ``offset`` metres before the stop line is an assumption (2 m by default).

``LoopEmulator`` tells, step by step, which loops the simulated cars cover, as
the real ones would report it.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

CAR_LENGTH = 5.0  # m, SUMO's default passenger car


@dataclass
class Loop:
    thing: str        # Hamburg lane connection, e.g. "96_21"
    ds: int           # its detector datastream
    edge: str
    lane: int         # SUMO lane index on the edge (0 = rightmost)
    pos: float        # m from the start of the edge
    occupied: bool = False
    passages: int = 0
    # The lights of every movement leaving from this lane (straight, right...): the lane can
    # drive off when any of them is green.
    signal_ds: List[int] = field(default_factory=list)


def place_loops(data_dir: str, lengths: Dict[str, float], offset: float = 2.0) -> List[Loop]:
    links = json.load(open(os.path.join(data_dir, "links.json")))
    lanes = json.load(open(os.path.join(data_dir, "lanes.json")))
    det = {t["name"]: t["datastreams"]["detector_car"] for t in lanes if "detector_car" in t["datastreams"]}
    from_lane: Dict[Tuple[str, int], Tuple[str, int]] = {}
    for c in ET.parse(os.path.join(data_dir, "corridor.net.xml")).getroot().iter("connection"):
        if "tl" in c.attrib and "linkIndex" in c.attrib:
            from_lane[(c.attrib["tl"], int(c.attrib["linkIndex"]))] = (c.attrib["from"], int(c.attrib["fromLane"]))
    lane_ds: Dict[Tuple[str, int], List[int]] = {}
    for key, rec in links.items():
        tls, idx = key.split("|")
        where = from_lane.get((tls, int(idx)))
        if where is not None and rec.get("ds") and rec["ds"] not in lane_ds.setdefault(where, []):
            lane_ds[where].append(rec["ds"])
    loops: Dict[Tuple[str, int], Loop] = {}
    for key, rec in links.items():
        thing = rec.get("thing")
        if rec.get("how") != "direct" or thing not in det:
            continue
        tls, idx = key.split("|")
        where = from_lane.get((tls, int(idx)))
        if where is None or where[0] not in lengths:
            continue
        loops.setdefault(where, Loop(thing, det[thing], where[0], where[1], max(lengths[where[0]] - offset, 0.0),
                                     signal_ds=lane_ds.get(where, [])))
    return list(loops.values())


class LoopEmulator:
    def __init__(self, loops: List[Loop]) -> None:
        self.loops = loops
        self._by_lane: Dict[Tuple[str, int], List[Loop]] = {}
        for lp in loops:
            self._by_lane.setdefault((lp.edge, lp.lane), []).append(lp)

    def step(self, cars: Iterable[Tuple[str, int, float]]) -> List[Tuple[Loop, bool]]:
        """``cars``: (edge, lane, front position). Returns the loops that changed, with their new state."""
        covered = set()
        for edge, lane, front in cars:
            for lp in self._by_lane.get((edge, lane), ()):
                if front - CAR_LENGTH <= lp.pos <= front:
                    covered.add(id(lp))
        changes = []
        for lp in self.loops:
            occ = id(lp) in covered
            if occ != lp.occupied:
                lp.occupied = occ
                if occ:
                    lp.passages += 1
                changes.append((lp, occ))
        return changes


def recorded_passages(data_dir: str, loops: List[Loop], t0: float, t1: float) -> Dict[int, int]:
    """Cars each loop's real detector counted between ``t0`` and ``t1`` (Unix time), from the recording."""
    want = {lp.ds for lp in loops}
    rows: Dict[int, List[Tuple[int, int]]] = {}
    with gzip.open(os.path.join(data_dir, "signals.csv.gz"), "rt") as f:
        r = csv.reader(f)
        next(r)
        for t, code, ds in r:
            if int(ds) in want:
                rows.setdefault(int(ds), []).append((int(t), int(code)))
    out = {}
    for ds, s in rows.items():
        s.sort()
        prev, n = 0, 0
        for t, code in s:
            if t0 <= t < t1 and prev == 0 and code > 0:
                n += 1
            prev = code
        out[ds] = n
    return out
