"""GLOSA core: the speed band that reaches the next controls without braking.

GLOSA stands for Green Light Optimal Speed Advisory. Given how far the
vehicle is from a traffic light and when that light will be green, it finds
every speed the driver can hold so that the car reaches the stop line while
the light is green. Any speed in the band works: drive faster and you arrive
on red, drive slower and you arrive after the light has turned red again.

The driver is never asked to brake. To lose speed they lift off the
accelerator and the car slows by itself (engine braking plus rolling and air
resistance, about 0.5-1 m/s^2). The kinematic model below uses exactly that
deceleration, ``coast_decel``, whenever the target speed is lower than the
current one.

All quantities are SI: metres, seconds, m/s. Times are relative to "now".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

Window = Tuple[float, float]  # (start, end) seconds from now


@dataclass(frozen=True)
class DriverProfile:
    """How the driver (or the car) changes speed without braking."""

    accel: float = 1.3          # comfortable acceleration, m/s^2
    coast_decel: float = 0.7    # deceleration when lifting off the pedal, m/s^2
    min_speed: float = 15 / 3.6  # slowest speed worth recommending, m/s


@dataclass(frozen=True)
class Margins:
    """Safety margins applied to the green windows."""

    after_green_start: float = 1.0   # do not arrive the instant it turns green
    before_green_end: float = 1.0    # nor the instant it turns yellow
    startup_lost_time: float = 2.0   # the first queued car needs time to react
    queue_headway: float = 2.0       # each further queued car leaves this much later
    follow_headway: float = 1.5      # keep this time gap to a moving leader
    target_buffer: float = 1.5       # aim to arrive this long after the green starts


@dataclass
class Band:
    """A range of constant cruise speeds, plus the green window it hits."""

    low: float
    high: float
    window: Window

    @property
    def width(self) -> float:
        return self.high - self.low


@dataclass
class Advice:
    """What to tell the driver right now.

    kind:
      ``go``    the speed limit already reaches a green: keep at most ``high``.
      ``slow``  lift off and settle between ``low`` and ``high``.
      ``stop``  no speed reaches a green; coast towards the stop line.
      ``cap``   no light ahead, but a roundabout or yield point caps the speed.

    At a give-way line where the main road can be seen (a ``gap`` control),
    ``slow`` and ``stop`` mean the same as at a light, with "green" read as
    "a gap in the main-road traffic".
      ``free``  nothing to manage: drive at the limit.
    """

    kind: str
    low: Optional[float]
    high: Optional[float]
    target: Optional[float]
    window: Optional[Window] = None
    eta: Optional[float] = None
    controls_used: int = 0
    notes: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Kinematics
# --------------------------------------------------------------------------

def arrival_time(distance: float, v0: float, v: float, profile: DriverProfile) -> float:
    """Seconds to cover ``distance`` starting at ``v0`` and settling at ``v``.

    The car accelerates at ``profile.accel`` (when ``v > v0``) or coasts at
    ``profile.coast_decel`` (when ``v < v0``) until it reaches ``v``, then
    holds ``v``. If the line comes before the transition ends, the car crosses
    it mid-transition.

    The result never increases as ``v`` grows, which is what lets the band
    edges be found by bisection.
    """
    if distance <= 0:
        return 0.0
    v0 = max(v0, 0.0)
    v = max(v, 0.0)
    if abs(v - v0) < 1e-9:
        return distance / v if v > 0 else math.inf

    if v > v0:
        a = profile.accel
        t1 = (v - v0) / a
        d1 = (v0 + v) / 2 * t1
        if d1 >= distance:
            return (-v0 + math.sqrt(v0 * v0 + 2 * a * distance)) / a
        return t1 + (distance - d1) / v

    b = profile.coast_decel
    t1 = (v0 - v) / b
    d1 = (v0 + v) / 2 * t1
    if d1 >= distance:
        disc = max(v0 * v0 - 2 * b * distance, 0.0)
        return (v0 - math.sqrt(disc)) / b
    if v <= 0:
        return math.inf
    return t1 + (distance - d1) / v


def coast_cap(distance: float, v_end: float, profile: DriverProfile) -> float:
    """Highest speed from which coasting alone gets down to ``v_end`` in ``distance``.

    Used for roundabouts, yield and stop points, and for the "coast to the
    red light" profile (``v_end = 0``).
    """
    return math.sqrt(max(v_end, 0.0) ** 2 + 2 * profile.coast_decel * max(distance, 0.0))


def _bisect(pred: Callable[[float], bool], lo: float, hi: float, iters: int = 40) -> float:
    """Boundary between pred False (at lo) and pred True (at hi)."""
    for _ in range(iters):
        mid = (lo + hi) / 2
        if pred(mid):
            hi = mid
        else:
            lo = mid
    return hi


def band_for_window(
    arrival: Callable[[float], float],
    window: Window,
    v_floor: float,
    v_cap: float,
) -> Optional[Band]:
    """Speeds in ``[v_floor, v_cap]`` whose arrival time falls inside ``window``.

    ``arrival(v)`` must never increase with ``v`` (as ``arrival_time`` does).
    """
    start, end = window
    if end <= start or v_cap <= 0 or v_cap < v_floor:
        return None
    # Arrive before the end: arrival(v) <= end  <=>  v >= low.
    if arrival(v_cap) > end:
        return None
    if arrival(v_floor) <= end:
        low = v_floor
    else:
        low = _bisect(lambda v: arrival(v) <= end, v_floor, v_cap)
    # Arrive after the start: arrival(v) >= start  <=>  v <= high.
    if arrival(v_floor) < start:
        return None
    if arrival(v_cap) >= start:
        high = v_cap
    else:
        high = _bisect(lambda v: arrival(v) < start, v_floor, v_cap)
        # _bisect returns the first speed that arrives too early; step back.
        high = max(low, high - 1e-6)
    if high < low:
        return None
    return Band(low=low, high=high, window=window)


def constant_speed_band(distance: float, window: Window, v_floor: float, v_cap: float) -> Optional[Band]:
    """Closed-form band for a car already cruising (no speed transition).

    This is what the map draws: the speeds to hold from this point onwards.
    """
    start, end = window
    if distance <= 0:
        return Band(v_floor, v_cap, window) if start <= 0 < end else None
    low = distance / end if end > 0 else math.inf
    high = distance / start if start > 0 else math.inf
    low = max(low, v_floor)
    high = min(high, v_cap)
    if high < low:
        return None
    return Band(low=low, high=high, window=window)


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

def effective_windows(
    windows: Iterable[Window],
    margins: Margins,
    queue_len: int = 0,
    earliest: float = 0.0,
) -> List[Window]:
    """Shrink raw green windows by margins, queue discharge and a leader.

    A queue of ``queue_len`` stopped cars delays the moment our car can
    actually cross: the first queued car needs ``startup_lost_time`` and each
    car after it ``queue_headway``. ``earliest`` is the soonest our car may
    arrive because of a moving leader ahead.

    The queue only delays a window that starts in the future. If the light is
    already green the queue is already moving; the moving leader constraint
    (``earliest``) covers it.
    """
    out: List[Window] = []
    for start, end in windows:
        if start > 0:
            s = start + margins.after_green_start
            if queue_len > 0:
                s = start + margins.startup_lost_time + queue_len * margins.queue_headway
        else:
            s = start
        s = max(s, earliest)
        e = end - margins.before_green_end
        if e > s and e > 0:
            out.append((s, e))
    return out


# --------------------------------------------------------------------------
# Advice along a route
# --------------------------------------------------------------------------

@dataclass
class Control:
    """Something ahead on the route that may need a speed change.

    kind ``signal``: a traffic light, with its green ``windows`` for our
    approach, and optionally the queue length and earliest arrival.
    kind ``yield``: a roundabout entry or give-way line, crossed at no more
    than ``entry_speed``.
    kind ``gap``: a give-way line whose main-road traffic is known. Also
    crossed at no more than ``entry_speed``; ``windows`` are the gaps in
    that traffic (times when no main-road car is close to the junction),
    already including the safety margins.
    """

    kind: str
    distance: float
    node: str = ""
    windows: Sequence[Window] = ()
    queue_len: int = 0
    earliest: float = 0.0
    entry_speed: float = 0.0
    certain: bool = True   # a signal whose timing is only suspected: see ``advise``


def recommend(
    arrival: Callable[[float], float],
    low: float,
    high: float,
    window: Window,
    v_cap: float,
    buffer: float,
) -> float:
    """Pick the one speed to show as the big number.

    If the light is green now, the top of the band. Otherwise aim to arrive
    ``buffer`` seconds after the (effective) green starts, or in the middle of
    a short window; that may well be the limit itself. Aiming at a time rather than at a point of the
    band keeps the advice steady: a driver who holds the speed gets the same
    number at the next update.
    """
    start, end = window
    if start <= 0:
        return high  # green now: just do not arrive after it ends
    t_goal = min(start + buffer, (start + end) / 2)
    if arrival(high) >= t_goal:
        return high
    if arrival(low) <= t_goal:
        return low
    return _bisect(lambda v: arrival(v) <= t_goal, low, high)


def advise(
    controls: Sequence[Control],
    v0: float,
    speed_limit: float,
    profile: DriverProfile = DriverProfile(),
    margins: Margins = Margins(),
    max_signals: int = 1,
    uncertain_drop: float = 10 / 3.6,
) -> Advice:
    """Speed band for the controls ahead.

    A light whose timing is only suspected (``certain`` false) is used for
    small changes only: if catching its green would mean slowing more than
    ``uncertain_drop`` below the advice without it, or coasting to its line,
    the light is left out. A wrong forecast then costs little time, and a right
    one still spares some braking.
    """
    res = _advise(controls, v0, speed_limit, profile, margins, max_signals)
    first = None
    for c in controls:
        if c.kind in ("yield", "gap"):
            break
        if c.kind == "signal":
            first = c
            break
    if first is None or first.certain or res.kind not in ("slow", "stop"):
        return res
    alt = advise([c for c in controls if c is not first], v0, speed_limit, profile, margins, max_signals,
                 uncertain_drop)
    if res.kind == "stop" or res.target is None or alt.target is None or res.target < alt.target - uncertain_drop:
        alt.notes.append(f"uncertain-skipped:{first.node}")
        return alt
    res.notes.append(f"uncertain:{first.node}")
    return res


def _advise(
    controls: Sequence[Control],
    v0: float,
    speed_limit: float,
    profile: DriverProfile,
    margins: Margins,
    max_signals: int,
) -> Advice:
    """Speed band for the controls ahead, every light taken at its word.

    With ``max_signals > 1``, that many consecutive traffic lights are
    chained: the band is narrowed so that the same cruise speed catches the
    green at each of them, as long as at least one speed still does. The
    default looks at the next light only: in the simulation, chaining cost
    about 3 s per trip and saved no stops, because queues at the later lights
    cannot be known in advance. A roundabout or yield point caps
    the band and ends the chain, because the car slows there anyway.
    """
    v_cap = speed_limit
    notes: List[str] = []
    signals: List[Control] = []
    gap: Optional[Control] = None
    for c in controls:
        if c.kind in ("yield", "gap"):
            cap = coast_cap(c.distance, c.entry_speed, profile)
            if cap < v_cap:
                v_cap = cap
                notes.append(f"yield:{c.node}")
            if c.kind == "gap" and not signals:
                gap = c
            break
        if c.kind == "signal":
            signals.append(c)
            if len(signals) >= max_signals:
                break

    v_floor = min(profile.min_speed, v_cap)

    if gap is not None:
        return _gap_advice(gap, v0, v_cap, v_floor, speed_limit, profile, margins, notes)

    if not signals:
        if v_cap < speed_limit - 1e-6:
            return Advice("cap", None, v_cap, v_cap, notes=notes)
        return Advice("free", None, speed_limit, speed_limit, notes=notes)

    def bands_for(c: Control) -> List[Band]:
        wins = effective_windows(c.windows, margins, c.queue_len, c.earliest)

        def arr(v: float, d: float = c.distance) -> float:
            return arrival_time(d, v0, v, profile)

        out = []
        for w in wins:
            b = band_for_window(arr, w, v_floor, v_cap)
            if b is not None:
                out.append(b)
        return out

    first = bands_for(signals[0])
    if not first:
        # No cruise speed reaches a green: coast to the line instead of braking.
        d = signals[0].distance
        target = min(v_cap, coast_cap(max(d - 2.0, 0.0), 0.0, profile))
        return Advice("stop", None, None, target, controls_used=1, notes=notes)

    # Prefer the fastest band (earliest green), then narrow with later signals.
    first.sort(key=lambda b: b.high, reverse=True)
    best: Optional[Tuple[float, float, Window, int]] = None
    for b in first:
        low, high, used = b.low, b.high, 1
        for c in signals[1:]:
            narrowed = None
            for nb in bands_for(c):
                lo2, hi2 = max(low, nb.low), min(high, nb.high)
                if lo2 <= hi2:
                    narrowed = (lo2, hi2) if narrowed is None or hi2 > narrowed[1] else narrowed
            if narrowed is None:
                break
            low, high = narrowed
            used += 1
        if best is None or used > best[3]:
            best = (low, high, b.window, used)
        if used == len(signals):
            break

    low, high, window, used = best

    def arr_first(v: float) -> float:
        return arrival_time(signals[0].distance, v0, v, profile)

    target = recommend(arr_first, low, high, window, v_cap, margins.target_buffer)
    eta = arr_first(target)
    kind = "go" if target >= speed_limit - 1e-6 else "slow"
    return Advice(kind, low, high, target, window=window, eta=eta, controls_used=used, notes=notes)


def _gap_advice(
    c: Control,
    v0: float,
    v_cap: float,
    v_floor: float,
    speed_limit: float,
    profile: DriverProfile,
    margins: Margins,
    notes: List[str],
) -> Advice:
    """Give way without stopping: reach the line when the main road is clear.

    If the car already gets there in a gap at the usual approach speed, the
    advice is the plain cap. Otherwise it is the speed band that arrives in
    the next gap, exactly as for a green light; and if no reasonable speed
    does, roll slowly to the line.
    """

    def arr(v: float) -> float:
        return arrival_time(c.distance, v0, v, profile)

    wins = []
    for s, e in c.windows:
        s = max(s, c.earliest)
        if e > s:
            wins.append((s, e))
    notes.append(f"gap:{c.node}")
    t_fast = arr(v_cap)
    if any(s <= t_fast < e for s, e in wins):
        kind = "cap" if v_cap < speed_limit - 1e-6 else "free"
        return Advice(kind, None, v_cap, v_cap, eta=t_fast, controls_used=1, notes=notes)
    bands = [b for w in wins if (b := band_for_window(arr, w, v_floor, v_cap)) is not None]
    if not bands:
        target = min(v_cap, coast_cap(max(c.distance - 2.0, 0.0), 0.0, profile))
        return Advice("stop", None, None, target, controls_used=1, notes=notes)
    best = max(bands, key=lambda b: b.high)  # the earliest gap that can be reached
    target = recommend(arr, best.low, best.high, best.window, v_cap, margins.target_buffer)
    return Advice("slow", best.low, best.high, target, window=best.window, eta=arr(target),
                  controls_used=1, notes=notes)
