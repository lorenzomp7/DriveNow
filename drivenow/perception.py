"""What the car sees with its own sensors: camera, radar, lidar, and their fusion.

Up to now the car in front, the queue and the colour of the light came from
the simulation itself (or, on the road, from other cars sharing their
position and from the lights' published timings). A car that drives itself
must also see them: this module models the sensors of such a car and fuses
what they report into the objects the driving code uses.

The roads are single-lane, so "the scene" is one dimension: the first
vehicle ahead along the route (the sensors cannot see through it), the next
traffic light, and the objects a radar mistakes for an obstacle. The camera
is modelled by what an image detector (a neural network that finds vehicles
and reads lights in the pixels) gives out, not by pixels: whether it finds
the object, how far it thinks it is, and how often it is wrong.

Sensors (values for clear weather; ``WEATHER`` scales them):

``camera``  vehicles up to 150 m, found almost always within 50 m and less
            and less often beyond; its distance comes from one image, so
            the error grows with the distance (about 2.5 m at 50 m, 7 m at
            100 m), and so does that of the closing speed it reads from how
            fast the car grows in the image (2 m/s at 50 m). It is the only sensor that reads the colour of a light
            (up to 120 m). Night, rain and above all fog shorten its range.
``radar``   up to 160 m, distance within 0.3 m and closing speed within
            0.15 m/s, hardly touched by weather. It cannot tell a car from a
            manhole cover or an overhead sign: now and then it reports a
            stationary obstacle that is not there (a "ghost").
``lidar``   up to 120 m, distance within a few centimetres, sure detection,
            no ghosts; it does not see colours, and rain and fog shorten its
            range a lot.
``perfect`` the simulation's truth, as a reference.

Fusion: one Kalman filter per object on (gap, rate at which the gap
changes); each detection updates the track closest to it in both distance
and closing speed, or starts a new one. A track is used once it has been seen twice. One rule is taken
from the cars on the road: an object that stands still and that only the
radar sees is ignored, unless the camera or the lidar has seen it twice in
the last second or it was seen moving before (a car that stopped). That rule
removes the ghosts, and it is also why a radar alone does not find a car
that was already standing still when it came into view.

The light's colour is read by the camera and changes only when two of the
last three readings agree.
"""

from __future__ import annotations

import math
import random
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

SUITES = {
    "perfect": ("perfect",),
    "radar": ("radar",),
    "camera": ("camera",),
    "camera+radar": ("camera", "radar"),
    "camera+radar+lidar": ("camera", "radar", "lidar"),
}

# How the weather changes each sensor: range factor, noise factor, detection factor.
WEATHER = {
    "clear": {"camera": (1.0, 1.0, 1.0), "light": 1.0, "radar": (1.0, 1.0, 1.0), "lidar": (1.0, 1.0, 1.0)},
    "night": {"camera": (0.6, 1.5, 0.9), "light": 1.0, "radar": (1.0, 1.0, 1.0), "lidar": (1.0, 1.0, 1.0)},
    "rain": {"camera": (0.7, 1.3, 0.9), "light": 0.8, "radar": (0.9, 1.0, 0.97), "lidar": (0.6, 1.5, 0.85)},
    "fog": {"camera": (0.3, 2.0, 0.8), "light": 0.4, "radar": (0.95, 1.0, 0.97), "lidar": (0.35, 2.0, 0.7)},
}

CAMERA_RANGE = 150.0
LIGHT_RANGE = 120.0
RADAR_RANGE = 160.0
LIDAR_RANGE = 120.0
GHOST_FROM = 120.0   # m: a ghost shows up this far ahead...
GHOST_UNTIL = 15.0   # ...and drops out of the beam this close (an overhead sign is above it)
STILL = 1.5          # m/s over the ground: slower than this an object counts as standing still


@dataclass
class Detection:
    sensor: str
    gap: float                   # m, bumper to bumper
    sigma: float                 # m
    rate: Optional[float] = None  # m/s, how fast the gap changes (radar only)
    sigma_rate: float = 0.0
    truth: object = None         # id of the real object, "ghost" or None (only to evaluate)


@dataclass
class Track:
    gap: float
    rate: float
    P: List[List[float]]
    t: float
    hits: int = 1
    seen: Dict[str, float] = field(default_factory=dict)  # sensor -> last time it saw this track
    moved: bool = False
    vision: Deque[float] = field(default_factory=deque)  # times the camera or the lidar saw it
    truths: Counter = field(default_factory=Counter)

    @property
    def truth(self) -> object:
        return self.truths.most_common(1)[0][0] if self.truths else None


@dataclass
class Seen:
    """The object ahead as the car perceives it."""

    gap: float
    rate: float       # negative: closing in
    sigma: float      # m, uncertainty of the gap
    sigma_rate: float  # m/s, uncertainty of the rate
    sensors: Tuple[str, ...]
    truth: object = None


class Perception:
    def __init__(self, rng: random.Random, suite: str = "camera+radar", weather: str = "clear",
                 ghost_per_km: float = 2.0, accel_noise: float = 3.0) -> None:
        if suite not in SUITES:
            raise ValueError(f"unknown sensor suite {suite!r}")
        if weather not in WEATHER:
            raise ValueError(f"unknown weather {weather!r}")
        self.rng = rng
        self.suite = suite
        self.sensors = SUITES[suite]
        self.weather = weather
        self.w = WEATHER[weather]
        self.ghost_per_km = ghost_per_km
        self.accel_noise = accel_noise
        self.tracks: List[Track] = []
        self._ghosts: Deque[float] = deque()   # route positions where the radar sees something
        self._ghost_horizon = 0.0
        self._t: Optional[float] = None
        self._light_reads: Deque[Optional[str]] = deque(maxlen=3)
        self._light: Optional[str] = None
        self._light_t = -1e9
        self._light_node: Optional[str] = None
        self._truth_leader = None
        self._v = 0.0
        self._rate_true = 0.0

    # -- ranges ----------------------------------------------------------------

    def stationary_range(self) -> float:
        """How far ahead this car can trust itself to see a car standing still (camera or lidar)."""
        if "perfect" in self.sensors:
            return math.inf
        r = 0.0
        if "camera" in self.sensors:
            r = max(r, 0.8 * CAMERA_RANGE * self.w["camera"][0])
        if "lidar" in self.sensors:
            r = max(r, 0.9 * LIDAR_RANGE * self.w["lidar"][0])
        return r

    def light_range(self) -> float:
        if "perfect" in self.sensors:
            return math.inf
        return LIGHT_RANGE * self.w["light"] if "camera" in self.sensors else 0.0

    # -- sensors -----------------------------------------------------------------

    def _camera(self, leader) -> List[Detection]:
        rng_f, noise_f, pd_f = self.w["camera"]
        out = []
        if leader is not None:
            gap, _, vid = leader
            rmax = CAMERA_RANGE * rng_f
            if gap < rmax:
                near = 50.0 * rng_f
                pd = 0.99 if gap <= near else 0.99 - 0.29 * (gap - near) / max(rmax - near, 1.0)
                if self.rng.random() < pd * pd_f:
                    sigma = (0.3 + 0.03 * gap + 0.0004 * gap * gap) * noise_f
                    # How fast the image of the car grows gives a rough closing speed.
                    sr = (0.5 + 0.03 * gap) * noise_f
                    out.append(Detection("camera", max(0.5, gap + self.rng.gauss(0.0, sigma)), sigma,
                                         rate=self._rate_true + self.rng.gauss(0.0, sr), sigma_rate=sr, truth=vid))
        # Now and then (once every 200 s at 5 frames a second) the detector finds a vehicle
        # where there is none (a shadow, a poster).
        if self.rng.random() < 0.001:
            g = self.rng.uniform(5.0, CAMERA_RANGE * rng_f)
            out.append(Detection("camera", g, (0.3 + 0.03 * g + 0.0004 * g * g) * noise_f,
                                 rate=self.rng.gauss(-self._v, 3.0), sigma_rate=(0.5 + 0.03 * g) * noise_f, truth=None))
        return out

    def _radar(self, s: float, leader) -> List[Detection]:
        rng_f, noise_f, pd_f = self.w["radar"]
        rmax = RADAR_RANGE * rng_f
        out = []
        if leader is not None:
            gap, v_lead, vid = leader
            if gap < rmax:
                pd = 0.97 if gap < 120 else 0.9
                if self.rng.random() < pd * pd_f:
                    out.append(Detection("radar", max(0.3, gap + self.rng.gauss(0.0, 0.3 * noise_f)), 0.3 * noise_f,
                                         rate=self._rate_true + self.rng.gauss(0.0, 0.15), sigma_rate=0.15, truth=vid))
        for g_s in self._ghosts:
            d = g_s - s
            lead_gap = leader[0] if leader is not None else math.inf
            if GHOST_UNTIL < d < min(GHOST_FROM, rmax) and d < lead_gap - 2 and self.rng.random() < 0.8:
                out.append(Detection("radar", d + self.rng.gauss(0.0, 0.3), 0.3,
                                     rate=-self._v + self.rng.gauss(0.0, 0.15), sigma_rate=0.15, truth="ghost"))
        return out

    def _lidar(self, leader) -> List[Detection]:
        rng_f, noise_f, pd_f = self.w["lidar"]
        if leader is None:
            return []
        gap, _, vid = leader
        if gap >= LIDAR_RANGE * rng_f or self.rng.random() >= 0.98 * pd_f:
            return []
        sigma = (0.05 + 0.001 * gap) * noise_f
        return [Detection("lidar", max(0.3, gap + self.rng.gauss(0.0, sigma)), sigma, truth=vid)]

    def _read_light(self, light) -> Optional[str]:
        """One camera reading of the light ahead: its colour, a wrong colour, or nothing."""
        if light is None:
            return None
        dist, colour = light[0], light[1]
        if "perfect" in self.sensors:
            return colour
        rmax = self.light_range()
        if dist > rmax:
            return None
        p_read = 0.95 if dist < 0.5 * rmax else 0.95 - 0.35 * (dist - 0.5 * rmax) / (0.5 * rmax)
        if self.rng.random() >= p_read:
            return None
        p_right = 0.99 if dist < 0.5 * rmax else 0.95
        if self.rng.random() < p_right:
            return colour
        return self.rng.choice([c for c in ("G", "y", "r") if c != colour])

    # -- one frame ----------------------------------------------------------------

    def sense(self, t: float, s: float, v: float, leader: Optional[Tuple[float, float, object]],
              light: Optional[Tuple[float, str, str]]) -> None:
        """A frame at time ``t``: the car is at ``s`` along its route with speed ``v``.

        ``leader`` is the truth about the first vehicle ahead, (gap, speed, id) or None;
        ``light`` the next light, (distance to the line, colour now, node id) or None.
        """
        self._v = v
        self._truth_leader = leader
        self._rate_true = 0.0 if leader is None else leader[1] - v
        # Radar ghosts: fixed points along the route, drawn as the car gets near them.
        while self._ghost_horizon < s + GHOST_FROM + 50:
            self._ghost_horizon += self.rng.expovariate(self.ghost_per_km / 1000.0) if self.ghost_per_km > 0 else 1e9
            self._ghosts.append(self._ghost_horizon)
        while self._ghosts and self._ghosts[0] < s:
            self._ghosts.popleft()

        dt = 0.0 if self._t is None else t - self._t
        self._t = t
        if "perfect" in self.sensors:
            self.tracks = []
            if leader is not None:
                tr = Track(leader[0], leader[1] - v, [[0.0, 0.0], [0.0, 0.0]], t, hits=99, seen={"perfect": t},
                           moved=leader[1] > STILL)
                tr.truths[leader[2]] = 1
                self.tracks.append(tr)
        else:
            for tr in self.tracks:
                self._predict(tr, dt)
                tr.t = t
            dets: List[Detection] = []
            if "camera" in self.sensors:
                dets += self._camera(leader)
            if "radar" in self.sensors:
                dets += self._radar(s, leader)
            if "lidar" in self.sensors:
                dets += self._lidar(leader)
            for det in dets:
                self._associate(det, t, v)
            self.tracks = [tr for tr in self.tracks if t - max(tr.seen.values()) <= 1.0 and tr.gap > -5]

        # The light
        node = None if light is None else light[2]
        if node != self._light_node:
            self._light_node = node
            self._light_reads.clear()
            self._light = None
        reading = self._read_light(light)
        if reading is not None:
            self._light_reads.append(reading)
            self._light_t = t
            top, n = Counter(self._light_reads).most_common(1)[0]
            if n >= 2 or "perfect" in self.sensors:
                self._light = top
        if t - self._light_t > 1.0:
            self._light = None
            self._light_reads.clear()

    def _predict(self, tr: Track, dt: float) -> None:
        if dt <= 0:
            return
        P = tr.P
        q = self.accel_noise ** 2
        tr.gap += tr.rate * dt
        p00 = P[0][0] + 2 * dt * P[0][1] + dt * dt * P[1][1] + q * dt ** 4 / 4
        p01 = P[0][1] + dt * P[1][1] + q * dt ** 3 / 2
        p11 = P[1][1] + q * dt * dt
        tr.P = [[p00, p01], [p01, p11]]

    def _associate(self, det: Detection, t: float, v: float) -> None:
        best, best_score = None, 3.5
        for tr in self.tracks:
            if tr.seen.get(det.sensor) == t:
                continue  # one detection per sensor per track in a frame
            score = abs(det.gap - tr.gap) / math.sqrt(tr.P[0][0] + det.sigma ** 2)
            if det.rate is not None:
                # A detection also says how fast it closes: a standing object is not a moving car.
                score = math.hypot(score, (det.rate - tr.rate) / math.sqrt(tr.P[1][1] + det.sigma_rate ** 2))
            if score < best_score and abs(det.gap - tr.gap) < max(3.0, 3 * det.sigma):
                best, best_score = tr, score
        if best is None:
            rate = det.rate if det.rate is not None else 0.0
            sr = det.sigma_rate if det.rate is not None else 5.0
            tr = Track(det.gap, rate, [[det.sigma ** 2, 0.0], [0.0, sr * sr]], t, seen={det.sensor: t})
            tr.truths[det.truth] += 1
            if det.sensor in ("camera", "lidar"):
                tr.vision.append(t)
            self.tracks.append(tr)
            return
        self._update(best, det)
        best.hits += 1
        best.seen[det.sensor] = t
        best.truths[det.truth] += 1
        if det.sensor in ("camera", "lidar"):
            best.vision.append(t)
            while best.vision and best.vision[0] < t - 1.0:
                best.vision.popleft()
        ground = v + best.rate
        if ground > 3.0 and best.P[1][1] < 1.5 ** 2:
            best.moved = True

    @staticmethod
    def _update(tr: Track, det: Detection) -> None:
        P = tr.P
        if det.rate is None:
            # Gap only: H = [1, 0]
            s = P[0][0] + det.sigma ** 2
            k0, k1 = P[0][0] / s, P[1][0] / s
            y = det.gap - tr.gap
            tr.gap += k0 * y
            tr.rate += k1 * y
            tr.P = [[(1 - k0) * P[0][0], (1 - k0) * P[0][1]],
                    [P[1][0] - k1 * P[0][0], P[1][1] - k1 * P[0][1]]]
            return
        # Gap and rate: H = I
        a, b, d = P[0][0] + det.sigma ** 2, P[0][1], P[1][1] + det.sigma_rate ** 2
        det_ = a * d - b * b
        inv = [[d / det_, -b / det_], [-b / det_, a / det_]]
        K = [[P[0][0] * inv[0][0] + P[0][1] * inv[1][0], P[0][0] * inv[0][1] + P[0][1] * inv[1][1]],
             [P[1][0] * inv[0][0] + P[1][1] * inv[1][0], P[1][0] * inv[0][1] + P[1][1] * inv[1][1]]]
        ys, yr = det.gap - tr.gap, det.rate - tr.rate
        tr.gap += K[0][0] * ys + K[0][1] * yr
        tr.rate += K[1][0] * ys + K[1][1] * yr
        tr.P = [[(1 - K[0][0]) * P[0][0] - K[0][1] * P[1][0], (1 - K[0][0]) * P[0][1] - K[0][1] * P[1][1]],
                [-K[1][0] * P[0][0] + (1 - K[1][1]) * P[1][0], -K[1][0] * P[0][1] + (1 - K[1][1]) * P[1][1]]]

    # -- what the driving code gets ------------------------------------------------

    def confirmed(self, tr: Track) -> bool:
        if "perfect" in self.sensors:
            return True
        if tr.hits < 2:
            return False
        still = self._v + tr.rate < STILL
        if still and not tr.moved:
            # Standing still and never seen moving: radar alone is not enough, the camera or
            # the lidar must have seen it at least twice in the last second.
            return sum(1 for ts in tr.vision if ts >= self._t - 1.0) >= 2
        return True

    def leader(self) -> Optional[Seen]:
        """The nearest confirmed object ahead, or None."""
        best = None
        for tr in self.tracks:
            if self.confirmed(tr) and (best is None or tr.gap < best.gap):
                best = tr
        if best is None:
            return None
        sensors = tuple(sorted(s for s, ts in best.seen.items() if self._t - ts <= 1.0))
        return Seen(best.gap, best.rate, math.sqrt(max(best.P[0][0], 0.0)), math.sqrt(max(best.P[1][1], 0.0)),
                    sensors, best.truth)

    def light(self) -> Optional[str]:
        """Colour of the next light as the camera reads it: 'G', 'y', 'r', or None (not seen)."""
        return self._light
