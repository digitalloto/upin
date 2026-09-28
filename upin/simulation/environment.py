"""
The parts of the simulated world the original model left out.

`SimulationWorld` was built to give legacy layers something to add noise to.
It flies the platform at constant speed along a heading, jitters that heading
and calls the jitter "wind", jams GNSS by setting a flag nothing reads, and
has no ground a camera could look at. None of that was a problem while the
layers were inventing their answers. It is a problem now, because the layered
navigation spec cannot be tested against it:

  wind             the Map-Click Guided layer exists to crab into the wind,
                   and the Wind Learner exists to measure it. A world with no
                   wind vector gives both of them nothing to do.

  dynamics         a guided layer sends attitude commands. A world that flies
                   a fixed heading regardless of what it is told cannot close
                   the loop, so nothing can be learned about whether the
                   guidance works.

  jamming field    the Escape Manager's job is to find the edge of a jammed
                   area. A jammer that is on or off everywhere has no edge.

  ground texture   optical flow measures motion from how the ground slides
                   across the image. There has to be ground.

Each is built from published physics, not tuned to make a layer look good,
and each defaults to off, so every existing test and demo sees exactly the
world it always saw.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

G = 9.80665
DEG_M = 111_320.0


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------

@dataclass
class WindField:
    """A steady wind plus gusts, in the local north-east frame.

    Gusts are a first-order Gauss-Markov process, the standard simple model
    for turbulence: each gust component decays toward zero with time constant
    `gust_tau_s` and is driven by white noise sized so its steady-state
    standard deviation is `gust_sigma_ms`. It has its own seeded generator, so
    a gusty run is reproducible and does not disturb any other random stream.
    """
    north_ms: float = 0.0
    east_ms: float = 0.0
    gust_sigma_ms: float = 0.0
    gust_tau_s: float = 8.0
    seed: int = 0

    def __post_init__(self):
        self._rng = np.random.default_rng(self.seed)
        self._gust = np.zeros(2)

    def step(self, dt: float) -> None:
        if self.gust_sigma_ms <= 0.0 or dt <= 0.0:
            return
        a = math.exp(-dt / max(self.gust_tau_s, 1e-6))
        drive = self.gust_sigma_ms * math.sqrt(max(0.0, 1.0 - a * a))
        self._gust = a * self._gust + drive * self._rng.normal(size=2)

    @property
    def vector_ned(self) -> np.ndarray:
        """The wind right now, gusts included. Down component is zero."""
        return np.array([self.north_ms + self._gust[0],
                         self.east_ms + self._gust[1], 0.0])

    @property
    def mean_ned(self) -> np.ndarray:
        """The steady part only -- what a good learner should converge to."""
        return np.array([self.north_ms, self.east_ms, 0.0])

    @property
    def speed_ms(self) -> float:
        v = self.vector_ned
        return float(math.hypot(v[0], v[1]))

    @property
    def bearing_deg(self) -> float:
        """Direction the wind is blowing toward, degrees from north."""
        v = self.vector_ned
        return float(math.degrees(math.atan2(v[1], v[0])) % 360.0)

    @property
    def is_calm(self) -> bool:
        return (self.north_ms == 0.0 and self.east_ms == 0.0
                and self.gust_sigma_ms <= 0.0)


# ---------------------------------------------------------------------------
# GNSS reception and jamming
# ---------------------------------------------------------------------------

TRACKING_THRESHOLD_DBHZ = 28.0
"""Below this carrier-to-noise density a typical receiver loses code lock.
Commercial receivers track down to roughly 25-30 dB-Hz; 28 is a middle
value, not a flattering one."""

DENIAL_DROP_DB = 18.0
"""C/N0 reduction at a jamming zone's stated radius. The strongest
satellite, near zenith, arrives at about 46 dB-Hz; 18 dB takes it to the
tracking threshold. So a zone's radius means what it sounds like: inside it,
every satellite is lost."""

GLOBAL_JAM_DROP_DB = 40.0
"""What `set_gps_jamming(True)` does: a jammer strong enough that nothing is
tracked anywhere. Kept for the scenarios that always used the flag."""

MIN_JAMMER_RANGE_M = 10.0
"""Distance floor for the inverse-square law, so the jammer's own location
is not a singularity."""


def nominal_cn0_dbhz(elevation_deg: float) -> float:
    """Clear-sky C/N0 for a satellite at this elevation.

    Low satellites travel through more atmosphere and sit lower in the
    antenna pattern. 38 dB-Hz at the horizon rising to 46 at zenith is
    typical of a patch antenna on an open sky.
    """
    return 38.0 + 8.0 * math.sin(math.radians(max(0.0, elevation_deg)))


@dataclass
class JammingZone:
    """One jammer, as a place.

    The C/N0 drop falls off with the square of distance -- 6 dB per doubling
    -- which is what a transmitter does. So a zone is not a hard wall: just
    outside the stated radius the weakest satellites go first and the
    geometry thins out, and the drop fades to nothing by about eight radii.
    That gradient is the thing the Escape Manager is designed to follow.
    """
    lat: float
    lon: float
    radius_m: float
    constellations: Tuple[str, ...] = ("GPS", "NavIC", "LEO")
    active: bool = True
    name: str = ""

    def distance_m(self, lat: float, lon: float) -> float:
        dn = (lat - self.lat) * DEG_M
        de = ((lon - self.lon) * DEG_M
              * math.cos(math.radians((lat + self.lat) / 2.0)))
        return math.hypot(dn, de)

    def cn0_drop_db(self, lat: float, lon: float) -> float:
        if not self.active or self.radius_m <= 0:
            return 0.0
        d = max(self.distance_m(lat, lon), MIN_JAMMER_RANGE_M)
        return max(0.0, DENIAL_DROP_DB + 20.0 * math.log10(self.radius_m / d))


class JammingField:
    """All the jammers in the world.

    Where zones overlap the strongest one governs. Strictly, jammer powers
    add, so two equal jammers are about 3 dB worse than one; taking the
    maximum understates overlap slightly, which errs toward the jammer being
    weaker than it is -- the less convenient direction for an escape test.
    """

    def __init__(self, zones: Sequence[JammingZone] = ()):
        self.zones: List[JammingZone] = list(zones)

    def add(self, zone: JammingZone) -> JammingZone:
        self.zones.append(zone)
        return zone

    def clear(self) -> None:
        self.zones.clear()

    def cn0_drop_db(self, lat: float, lon: float, constellation: str) -> float:
        drops = [z.cn0_drop_db(lat, lon) for z in self.zones
                 if constellation in z.constellations]
        return max(drops) if drops else 0.0

    def inside_denial(self, lat: float, lon: float,
                      constellation: str = "GPS") -> bool:
        return any(z.active and constellation in z.constellations
                   and z.distance_m(lat, lon) <= z.radius_m
                   for z in self.zones)

    def __len__(self) -> int:
        return len(self.zones)


# ---------------------------------------------------------------------------
# Commandable platform dynamics
# ---------------------------------------------------------------------------

class PlatformDynamics:
    """The platform flies what it is commanded, not a fixed heading.

    The equations are `accel_from_command` from Layer 2 -- thrust rotated out
    of the body frame by the attitude, gravity, quadratic drag on airspeed --
    so the simulated aircraft and the dead-reckoning layer obey the same
    physics by construction. What separates them is the airframe: the world
    flies the TRUE airframe, while a layer works from a calibrated estimate of
    it. Give the two different numbers and model mismatch appears, exactly as
    it would between a real drone and its fitted model.

    Wind enters through drag, the way it does in the air: a drone holding
    level attitude in a crosswind is carried downwind until its airspeed
    through the moving air is zero.
    """

    def __init__(self, airframe, command=None):
        if not getattr(airframe, "calibrated", False):
            raise ValueError("the world's airframe must be fully specified")
        self.airframe = airframe
        self.command = command
        self.last_accel = np.zeros(3)

    def set_command(self, cmd) -> None:
        self.command = cmd

    def hover_command(self, yaw_rad: float):
        from upin.layers.inertial.command_dr import MotorCommand
        return MotorCommand(timestamp=0.0,
                            throttle=self.airframe.hover_throttle,
                            roll_rad=0.0, pitch_rad=0.0, yaw_rad=yaw_rad)

    def advance(self, world, dt: float) -> np.ndarray:
        """Integrate one step. Returns the acceleration applied, NED."""
        from upin.layers.inertial.command_dr import accel_from_command

        cmd = self.command
        if cmd is None:
            # Nothing commanded yet: hold level at hover thrust. That is what
            # a flight controller does between commands, not an invention.
            cmd = self.hover_command(math.radians(world.true_heading))

        v = np.array([world.true_vn, world.true_ve, world.true_vd], dtype=float)
        a = accel_from_command(cmd, self.airframe, v, world.wind.vector_ned)
        v = v + a * dt

        world.true_vn, world.true_ve, world.true_vd = (
            float(v[0]), float(v[1]), float(v[2]))
        world.true_heading = math.degrees(cmd.yaw_rad) % 360.0
        world.true_velocity = float(math.hypot(v[0], v[1]))
        self.last_accel = a
        return a


# ---------------------------------------------------------------------------
# Ground texture
# ---------------------------------------------------------------------------

TEXTURE_OCTAVES = ((30.0, 0.35), (12.0, 0.30), (5.0, 0.20), (2.0, 0.15))
"""Cell size in metres and weight, coarse to fine. Several scales so that
block matching has something to lock on to at any altitude, and no single
scale dominates to make the pattern periodic -- a periodic ground is one
optical flow can match to the wrong repeat."""


def _hash01(ix: np.ndarray, iy: np.ndarray, salt: int) -> np.ndarray:
    """A deterministic pseudo-random value in [0, 1) per integer lattice point."""
    x = ix.astype(np.uint64)
    y = iy.astype(np.uint64)
    h = (x * np.uint64(0x9E3779B1) ^ y * np.uint64(0x85EBCA77)
         ^ np.uint64(salt) * np.uint64(0xC2B2AE3D))
    h ^= h >> np.uint64(15)
    h *= np.uint64(0x2C1B3C6D)
    h ^= h >> np.uint64(12)
    h *= np.uint64(0x297A2D39)
    h ^= h >> np.uint64(15)
    return (h & np.uint64(0xFFFFFF)).astype(np.float64) / float(0x1000000)


def _value_noise(east: np.ndarray, north: np.ndarray, cell_m: float,
                 salt: int) -> np.ndarray:
    gx = east / cell_m
    gy = north / cell_m
    x0 = np.floor(gx)
    y0 = np.floor(gy)
    fx = gx - x0
    fy = gy - y0
    # smoothstep, so the surface has no creases at cell edges
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    # offset into the positive range before the unsigned hash
    ix = (x0 + 2 ** 30).astype(np.int64)
    iy = (y0 + 2 ** 30).astype(np.int64)
    v00 = _hash01(ix, iy, salt)
    v10 = _hash01(ix + 1, iy, salt)
    v01 = _hash01(ix, iy + 1, salt)
    v11 = _hash01(ix + 1, iy + 1, salt)
    top = v00 + (v10 - v00) * sx
    bot = v01 + (v11 - v01) * sx
    return top + (bot - top) * sy


def ground_texture(east_m: np.ndarray, north_m: np.ndarray,
                   seed: int = 911) -> np.ndarray:
    """Ground brightness at world coordinates, in [0, 1]. Pure function."""
    out = np.zeros(np.broadcast(east_m, north_m).shape, dtype=np.float64)
    for i, (cell, weight) in enumerate(TEXTURE_OCTAVES):
        out += weight * _value_noise(east_m, north_m, cell, seed * 31 + i)
    return out


def ground_patch(center_east_m: float, center_north_m: float,
                 heading_deg: float, agl_m: float, fov_deg: float,
                 size_px: int, seed: int = 911) -> Tuple[np.ndarray, float]:
    """What a downward camera sees: a square patch of ground, body-aligned.

    Row 0 is the forward edge of the frame and column 0 the left edge, so
    the image turns with the aircraft's heading the way a camera fixed to the
    airframe does. Returns (image, ground sample distance in metres/pixel).
    """
    gsd = 2.0 * agl_m * math.tan(math.radians(fov_deg) / 2.0) / size_px
    idx = (np.arange(size_px) - (size_px - 1) / 2.0) * gsd
    forward = idx[::-1][:, None]       # row 0 = furthest ahead
    right = idx[None, :]               # col 0 = furthest left
    psi = math.radians(heading_deg)
    north = center_north_m + forward * math.cos(psi) - right * math.sin(psi)
    east = center_east_m + forward * math.sin(psi) + right * math.cos(psi)
    return ground_texture(east, north, seed), gsd
