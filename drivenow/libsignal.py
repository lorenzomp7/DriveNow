"""Attach DriveNow advice to LibSignal's existing SUMO World (TraCI/libsumo).

The adapter never steps the simulation or controls signals. A windows_fn must
supply committed future greens; a network file is NOT a forecast of an adaptive
controller. No LibSignal or simulator package is imported by this module.
"""
from __future__ import annotations

import hashlib
import math

from .advisor import Advisor
from .network import load_sumo_net


class LibSignalAdvisor:
    def __init__(self, world, *, windows_fn=None, penetration=0.5, seed=1, network=None):
        if not math.isfinite(penetration) or not 0 <= penetration <= 1:
            raise ValueError('penetration must be between 0 and 1')
        self.world = world
        self.net = network if network is not None else load_sumo_net(world.net)
        self.penetration = penetration
        self.seed = seed
        # Deliberately suppress plans read from the XML. LibSignal can replace
        # their phases and durations at any time, including during reset().
        self.advisor = Advisor(self.net, windows_fn=windows_fn or (lambda *_: None))
        self._controlled = set()
        self._last_time = None

    def _equipped(self, vid):
        digest = hashlib.sha256(f'{self.seed}:{vid}'.encode()).digest()
        return int.from_bytes(digest[:8], 'big') / 2**64 < self.penetration

    def release(self):
        """Release this adapter's live overrides before ending an experiment."""
        vehicle = self.world.eng.vehicle
        live = set(vehicle.getIDList())
        for vid in self._controlled & live:
            vehicle.setSpeed(vid, -1)
        self._controlled.clear()

    def step(self, *, apply=False):
        """Read the state AFTER world.step(action); return advice by vehicle ID.

        apply=False performs no writes. apply=True also drives the equipped
        cohort, retaining SUMO's default collision/signal checks and releasing
        overrides near/inside junctions or when advice becomes unavailable.
        Recreate the adapter after world.reset(). All units are metres/seconds.
        """
        engine = self.world.eng  # reset() may have replaced the connection
        time = engine.simulation.getTime()
        if self._last_time is not None and time <= self._last_time:
            raise ValueError('Call once after each world.step(); recreate after world.reset().')
        dt = time - self._last_time if self._last_time is not None else float(self.world.interval if hasattr(self.world, 'interval') else 1)
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError('Simulation step duration must be positive and finite')
        self._last_time = time
        vehicle = engine.vehicle
        live = set(vehicle.getIDList())
        self._controlled.intersection_update(live)
        rows, occupancy = {}, {}
        for vid in sorted(live):
            road = vehicle.getRoadID(vid)
            if road not in self.net.edges:  # internal lane, teleport or unknown
                continue
            route = list(vehicle.getRoute(vid))
            index = vehicle.getRouteIndex(vid)
            if not 0 <= index < len(route) or route[index] != road:
                continue
            if any(edge not in self.net.edges for edge in route[index:]):
                continue
            pos, speed = vehicle.getLanePosition(vid), vehicle.getSpeed(vid)
            if not math.isfinite(pos) or not math.isfinite(speed) or pos < 0 or speed < 0:
                continue
            pos = min(pos, self.net.edges[road].length)
            rows[vid] = (route, index, pos, speed)
            occupancy.setdefault(road, []).append((pos, speed))
        for values in occupancy.values():
            values.sort()
        report, active = {}, set()
        for vid, (route, index, pos, speed) in rows.items():
            advice, control = self.advisor.advise(route, index, pos, speed, time, occupancy)
            report[vid] = advice
            if not apply or not self._equipped(vid):
                continue
            edge = self.net.edges[route[index]]
            remaining = edge.length - pos
            if advice.target is None or advice.kind == 'free' or remaining < 10:
                continue
            target = advice.target
            coast = self.advisor.profile.coast_decel
            if advice.kind == 'stop' and control is not None:
                target = min(target, math.sqrt(2 * coast * max(remaining - 2, 0)))
            target = min(max(target, speed - coast * dt), edge.speed, vehicle.getAllowedSpeed(vid))
            vehicle.setSpeed(vid, max(0, target))
            active.add(vid)
        if apply:
            for vid in self._controlled - active:
                vehicle.setSpeed(vid, -1)
            self._controlled = active
        return report
