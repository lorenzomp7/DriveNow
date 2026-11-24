"""Green windows a traffic-light agent is committed to (Piano DriveNow, punto 7).

An adaptive controller (LibSignal, or the PPO agent of the repository DriveNow came from)
decides its next phase as it goes, so the future of its lights is not known. What it
cannot do is break its own rules: a green lasts at least ``min_green``, the agent only
decides every ``decision_interval`` seconds, a change always goes through ``yellow`` (and
``all_red``), and with ``max_green`` a green ends by then at the latest. From the present
state alone (which phase is on, since when) those rules give

* *certain* windows: the light is green then whatever the agent decides;
* *likely* windows: green if the agent keeps the phase as long as it may (to ``max_green``),
  or switches as soon as it may (the next green). A suspected timing, not a commitment.

Nothing here reads a future plan: only the current phase and its elapsed time. Times are
seconds; windows are relative to ``now``, like every ``windows_fn`` of the Advisor.

``committed_windows`` is the pure function. ``CommittedSignalSource`` applies it to a
SUMO grid through a TraCI connection (two green phases, each followed by its yellow, as in
the repository's grids) and is a ``windows_fn`` for the Advisor or LibSignalAdvisor.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

Window = Tuple[float, float]

GREEN, YELLOW, CONFLICT_GREEN, CONFLICT_YELLOW = "green", "yellow", "conflict_green", "conflict_yellow"
EPS = 1e-6


@dataclass(frozen=True)
class AgentTiming:
    """The rules the agent keeps. ``max_green`` None: it may hold a green for ever."""

    min_green: float = 5.0
    max_green: Optional[float] = None
    yellow: float = 3.0
    all_red: float = 0.0
    decision_interval: float = 1.0
    decision_offset: float = 0.0   # decisions at offset + k * interval

    def __post_init__(self) -> None:
        if self.decision_interval <= 0 or self.min_green < 0 or self.yellow < 0 or self.all_red < 0:
            raise ValueError("decision_interval must be positive; min_green, yellow, all_red not negative")
        if self.max_green is not None and self.max_green < self.min_green:
            raise ValueError("max_green below min_green")

    def decision_at_or_after(self, t: float) -> float:
        """The first decision instant at ``t`` or later."""
        k = math.ceil((t - self.decision_offset) / self.decision_interval - EPS)
        return self.decision_offset + k * self.decision_interval

    def earliest_end(self, green_start: float, now: float) -> float:
        """Soonest a green that began at ``green_start`` can end, seen at ``now``."""
        end = self.decision_at_or_after(max(green_start + self.min_green, now))
        latest = self.latest_end(green_start)
        return end if latest is None else min(end, latest)

    def latest_end(self, green_start: float) -> Optional[float]:
        """Latest it can end: the first decision once ``max_green`` is reached; None without a maximum."""
        if self.max_green is None:
            return None
        return self.decision_at_or_after(green_start + self.max_green)


@dataclass
class Committed:
    certain: List[Window] = field(default_factory=list)
    likely: List[Window] = field(default_factory=list)


def _clip(windows: Sequence[Window], now: float, horizon: float) -> List[Window]:
    out = []
    for s, e in windows:
        s, e = max(s - now, 0.0), min(e - now, horizon)
        if e > s + EPS:
            out.append((round(s, 3), round(e, 3)))
    return out


def committed_windows(state: str, since: float, now: float, timing: AgentTiming,
                      horizon: float = 180.0) -> Committed:
    """Certain and likely green windows of one movement, relative to ``now``.

    ``state`` is the movement's situation now and ``since`` when it began:
    ``green`` (its green began at ``since``), ``yellow`` (its yellow began at ``since``),
    ``conflict_green`` (the other phase's green began at ``since``) or ``conflict_yellow``
    (the other phase's yellow began at ``since``: this movement is next).
    """
    t = timing
    change = t.yellow + t.all_red
    if state == YELLOW:      # the other phase gets its green next, then this one
        return committed_windows(CONFLICT_GREEN, since + change, now, t, horizon)
    if state == GREEN:
        end = t.earliest_end(since, now)
        latest = t.latest_end(since)
        certain = [(now, end)]
        likely = [(now, latest)] if latest is not None else [(now, now + horizon)]
        return Committed(_clip(certain, now, horizon), _clip(likely, now, horizon))
    if state == CONFLICT_YELLOW:
        start = since + change
        end = t.earliest_end(start, max(now, start))
        latest = t.latest_end(start)
        certain = [(start, end)]
        likely = [(start, latest if latest is not None else start + horizon)]
        return Committed(_clip(certain, now, horizon), _clip(likely, now, horizon))
    if state == CONFLICT_GREEN:
        first = t.earliest_end(since, now) + change      # soonest this movement turns green
        other_latest = t.latest_end(since)
        certain: List[Window] = []
        if other_latest is not None:
            last = other_latest + change                  # it is green by then at the latest...
            hold = t.earliest_end(first, max(now, first))  # ...and a green that began at ``first`` lasts to here
            if last < hold:
                certain.append((last, hold))
            likely = [(last, last + t.min_green)]
        else:
            likely = [(first, first + t.min_green)]
        return Committed(_clip(certain, now, horizon), _clip(likely, now, horizon))
    raise ValueError(f"unknown state {state!r}")


# -- a SUMO grid driven by an agent -------------------------------------------------

@dataclass
class _Movement:
    tl: str
    links: Tuple[int, ...]
    green: int       # phase index of its green
    yellow: int      # its yellow, after that green
    other: int       # the conflicting green
    other_yellow: int


class CommittedSignalSource:
    """``windows_fn`` from the live state of agent-controlled SUMO lights.

    ``mode``: ``"certain"`` returns only the certain windows (the windows_fn contract of
    LibSignalAdvisor: guaranteed greens, flagged certain), None when there are none;
    ``"committed"`` returns the certain windows, flagged certain, when they tell all there is
    to tell (the likely ones are no longer); otherwise the likely windows, flagged not certain,
    so the advice uses them only for small changes (glosa.advise).

    ``record`` keeps every certain window handed out as absolute times, for ``check``.
    """

    def __init__(self, conn, net_path: str, timing: AgentTiming, mode: str = "committed",
                 horizon: float = 180.0, record: bool = False) -> None:
        if mode not in ("certain", "committed"):
            raise ValueError("mode is 'certain' or 'committed'")
        self.conn, self.timing, self.mode, self.horizon = conn, timing, mode, horizon
        self.movements: Dict[Tuple[str, Optional[str]], _Movement] = _movements(net_path)
        self.record = record
        self.promised: Dict[Tuple[str, Optional[str]], List[Window]] = {}
        self._cache: Dict[Tuple[str, Optional[str]], object] = {}
        self._cache_t: Optional[float] = None
        self.calls = self.certain_given = self.likely_given = 0

    def state(self, m: _Movement, now: float) -> Tuple[str, float]:
        tl = self.conn.trafficlight
        phase = tl.getPhase(m.tl)
        elapsed = tl.getPhaseDuration(m.tl) - (tl.getNextSwitch(m.tl) - now)
        since = now - max(elapsed, 0.0)
        kind = {m.green: GREEN, m.yellow: YELLOW, m.other: CONFLICT_GREEN, m.other_yellow: CONFLICT_YELLOW}
        if phase not in kind:
            raise ValueError(f"{m.tl}: phase {phase} is not part of a two-green program")
        return kind[phase], since

    def windows(self, edge: str, next_edge: Optional[str], now: float) -> Optional[Committed]:
        m = self.movements.get((edge, next_edge)) or self.movements.get((edge, None))
        if m is None:
            return None
        state, since = self.state(m, now)
        return committed_windows(state, since, now, self.timing, self.horizon)

    def __call__(self, edge: str, next_edge: Optional[str], now: float):
        if self._cache_t != now:
            self._cache, self._cache_t = {}, now
        key = (edge, next_edge)
        if key in self._cache:
            return self._cache[key]
        self.calls += 1
        w = self.windows(edge, next_edge, now)
        out = None
        if w is not None:
            m = self.movements.get(key) or self.movements[(edge, None)]
            group = f"{m.tl}:{m.green}"
            if w.certain and (self.mode == "certain" or w.certain == w.likely):
                out = (w.certain, group, True)
                self.certain_given += 1
                if self.record:
                    self._promise(key, w.certain, now)
            elif self.mode == "committed" and w.likely:
                out = (w.likely, group, False)
                self.likely_given += 1
        self._cache[key] = out
        return out

    def _promise(self, key, windows: Sequence[Window], now: float) -> None:
        lst = self.promised.setdefault(key, [])
        for s, e in windows:
            s, e = now + s, now + e
            if lst and s <= lst[-1][1] + EPS:
                lst[-1] = (min(lst[-1][0], s), max(lst[-1][1], e))
            else:
                lst.append((s, e))

    def check(self, now: float, tolerance: float) -> List[Tuple[str, Optional[str]]]:
        """Movements promised green at ``now`` (more than ``tolerance`` inside a certain window)
        whose SUMO light is not green. An empty list: no false promise right now."""
        wrong = []
        states: Dict[str, str] = {}
        for key, lst in self.promised.items():
            if not any(s + tolerance < now < e - tolerance for s, e in lst):
                continue
            m = self.movements.get(key) or self.movements[(key[0], None)]
            if m.tl not in states:
                states[m.tl] = self.conn.trafficlight.getRedYellowGreenState(m.tl)
            if not all(states[m.tl][i] in "Gg" for i in m.links):
                wrong.append(key)
        return wrong


def _movements(net_path: str) -> Dict[Tuple[str, Optional[str]], _Movement]:
    """(approach edge, next edge or None) -> its links and phases, for two-green programs."""
    root = ET.parse(net_path).getroot()
    programs = {}
    for tl in root.iter("tlLogic"):
        programs[tl.attrib["id"]] = [p.attrib["state"] for p in tl.iter("phase")]
    links: Dict[Tuple[str, str], Dict[Optional[str], List[int]]] = {}
    for c in root.iter("connection"):
        if "tl" in c.attrib:
            per = links.setdefault((c.attrib["tl"], c.attrib["from"]), {})
            per.setdefault(c.attrib["to"], []).append(int(c.attrib["linkIndex"]))
            per.setdefault(None, []).append(int(c.attrib["linkIndex"]))
    out: Dict[Tuple[str, Optional[str]], _Movement] = {}
    for (tl, frm), per in links.items():
        states = programs[tl]
        if len(states) != 4:
            raise ValueError(f"{tl}: expected green, yellow, green, yellow; got {len(states)} phases")
        for to, idx in per.items():
            greens = [p for p in (0, 2) if all(states[p][i] in "Gg" for i in idx)]
            if len(greens) != 1:
                continue   # never green, or green in both: not a movement this source can tell
            g = greens[0]
            o = 2 - g
            out[(frm, to)] = _Movement(tl, tuple(sorted(set(idx))), g, g + 1, o, o + 1)
    return out
