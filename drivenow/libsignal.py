"""Attach DriveNow advice to LibSignal's existing SUMO World (TraCI/libsumo).

The adapter never steps the simulation or controls signals. windows_fn supplies
committed greens; learn_signals instead enables an experimental past-only
forecast. A network file is NOT a forecast of an adaptive controller. No LibSignal or simulator package is imported by this module.
"""
from __future__ import annotations

import hashlib
import math

from .advisor import Advisor
from .network import load_sumo_net


class LibSignalAdvisor:
    def __init__(self, world, *, windows_fn=None, penetration=0.5, seed=1, network=None, learn_signals=False):
        if not math.isfinite(penetration) or not 0 <= penetration <= 1:
            raise ValueError('penetration must be between 0 and 1')
        if learn_signals and windows_fn is not None:
            raise ValueError('Choose learned observations or explicit windows, not both')
        self.world = world
        self.net = network if network is not None else load_sumo_net(world.net)
        self.penetration = penetration
        self.seed = seed
        # Deliberately suppress plans read from the XML. LibSignal can replace
        # their phases and durations at any time, including during reset().
        self.signal_source = ObservedSignalSource(world.eng) if learn_signals else None
        self.advisor = Advisor(self.net, windows_fn=windows_fn or self.signal_source or (lambda *_: None))
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
        if self.signal_source is not None:
            self.signal_source.observe(time)
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


class ObservedSignalSource:
    """Experimental cycle forecast from live SUMO states; no XML future plans.

    Returns predictions, never guaranteed commitments. Untrained or unknown
    movements abstain. Recreate with the bridge after a simulation reset.
    """
    def __init__(self, engine, horizon=180):
        self.engine, self.horizon = engine, horizon
        self.movements, self.streams, self.rows, self.last = {}, {}, {}, {}
        self.time, self.predictor = None, None
        self.forecasts = self.nonempty_forecasts = 0
        self.cache = {}
        for tls in engine.trafficlight.getIDList():
            pairs = {}
            for index, links in enumerate(engine.trafficlight.getControlledLinks(tls)):
                for incoming, outgoing, _ in links:
                    pair = (engine.lane.getEdgeID(incoming), engine.lane.getEdgeID(outgoing))
                    pairs.setdefault(pair, set()).add(index)
            for pair, indices in pairs.items():
                stream = len(self.streams)
                self.movements[pair] = stream
                self.streams[stream] = (tls, indices)
                self.rows[stream] = []

    def observe(self, time):
        from .hamburg.signals import CyclePredictor, SignalHistory
        if self.time is not None and time <= self.time:
            raise ValueError('Signal observations must advance; recreate after reset')
        states = {tls:self.engine.trafficlight.getRedYellowGreenState(tls)
                  for tls, _ in self.streams.values()}
        for stream, (tls, indices) in self.streams.items():
            colors = [states[tls][i] if i < len(states[tls]) else '?' for i in indices]
            # g is permissive green: do not infer protected right of way from it.
            code = 3 if all(c == 'G' for c in colors) else 2 if 'y' in colors else 1 if all(c in 'rgu' for c in colors) else 9
            if self.last.get(stream) != code:
                self.rows[stream].append((time, code, stream))
                self.last[stream] = code
            rows = self.rows[stream]
            while len(rows) > 1 and rows[1][0] < time - 3600:
                rows.pop(0)
        self.time = time
        self.predictor = CyclePredictor(SignalHistory([row for rows in self.rows.values() for row in rows]), {})
        self.cache.clear()

    def __call__(self, edge, next_edge, time):
        stream = self.movements.get((edge, next_edge))
        if stream is None or self.predictor is None or time != self.time:
            return None
        if stream not in self.cache:
            windows = self.predictor.green_windows(stream, time, self.horizon)
            self.cache[stream] = None if windows is None else (windows, f'learned:{stream}')
            if windows is not None:
                self.forecasts += 1
                self.nonempty_forecasts += bool(windows)
        return self.cache[stream]
