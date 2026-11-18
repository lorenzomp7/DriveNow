"""What the driver is shown, as opposed to what the engine computes.

The advice is recomputed several times a second. Its speed can wobble by a
km/h or two from one update to the next (the car moves, the queue ahead
changes), and the kind of advice can flip back and forth at a boundary. A
number that keeps changing is hard to follow and distracting, so the display
changes it only when the change matters:

- the speed moves by at least ``deadband`` (3 km/h), or the shown speed falls
  out of the new band (too fast now means arriving on red);
- a new kind of advice ("slow" after "go", say) must last ``hold`` seconds
  (2 s) before it replaces the old one, unless it is urgent: "stop", or a shown
  speed too fast for the new band;
- a new control ahead (the next light, a roundabout) always shows at once.

Announcements, for a voice or a chime, are rarer still: only a new kind of
advice or a new control ahead, and at most one every ``announce_gap`` seconds
(8 s) unless urgent.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from .glosa import Advice

KMH = 1 / 3.6


class AdviceDisplay:
    def __init__(self, deadband: float = 3 * KMH, hold: float = 2.0, announce_gap: float = 8.0,
                 slack: float = 2 * KMH, deadband_up: Optional[float] = None, quick_up: bool = False) -> None:
        self.deadband = deadband          # m/s: smaller changes of the speed are not shown
        # Rises of the speed can be shown sooner (deadband_up), and a change to a faster kind
        # of advice ("go", "free") at once (quick_up): showing too low a speed costs time.
        self.deadband_up = deadband if deadband_up is None else deadband_up
        self.quick_up = quick_up
        self.hold = hold                  # s a new kind of advice must last before it is shown
        self.announce_gap = announce_gap  # s between two announcements, unless urgent
        self.slack = slack                # m/s: how far out of the new band the shown speed may be
        self.shown: Optional[Advice] = None
        self.control: Optional[str] = None
        self._pending: Optional[str] = None
        self._pending_since = 0.0
        self._last_announce = -1e9
        self.changes = 0                  # times the shown speed or kind changed
        self.announcements = 0
        self.announce = False             # set by the last update that should be announced

    def _urgent(self, adv: Advice) -> bool:
        s = self.shown
        if adv.kind == "stop" and s.kind != "stop":
            return True
        return (s.target is not None and adv.high is not None and s.target > adv.high + self.slack)

    def _show(self, t: float, adv: Advice, announce: bool, urgent: bool) -> None:
        old = self.shown
        self.shown = replace(adv, notes=list(adv.notes))
        self._pending = None
        if old is None or old.kind != adv.kind or _kmh(old.target) != _kmh(adv.target):
            self.changes += 1
        if announce and (urgent or t - self._last_announce >= self.announce_gap):
            self.announce = True
            self.announcements += 1
            self._last_announce = t

    def update(self, t: float, adv: Advice, control: Optional[str]) -> Advice:
        """Feed the advice just computed; returns the advice to show."""
        self.announce = False
        if self.shown is None or control != self.control:
            self.control = control
            self._show(t, adv, announce=True, urgent=self.shown is None)
            return self.shown
        urgent = self._urgent(adv)
        s = self.shown
        if adv.kind != s.kind:
            faster = adv.kind in ("go", "free") and (adv.target or 0) >= (s.target or 0)
            if urgent or (self.quick_up and faster):
                self._show(t, adv, announce=True, urgent=True)
            elif self._pending != adv.kind:
                self._pending, self._pending_since = adv.kind, t
            elif t - self._pending_since >= self.hold:
                self._show(t, adv, announce=True, urgent=False)
            return self.shown
        self._pending = None
        if s.target is None or adv.target is None:
            if s.target is not adv.target:
                self._show(t, adv, announce=False, urgent=False)
            return self.shown
        too_slow = adv.low is not None and s.target < adv.low - self.slack
        step = adv.target - s.target
        if urgent or too_slow or -step >= self.deadband or step >= self.deadband_up:
            self._show(t, adv, announce=False, urgent=urgent)
        return self.shown


def _kmh(v: Optional[float]) -> Optional[int]:
    return None if v is None else round(v * 3.6)
