"""
Where the aircraft could physically be -- and where it could not.

Since the last fix UPIN trusted, the aircraft has moved, but not arbitrarily.
It started with a known velocity; it can accelerate only as hard as its
motors allow; it cannot fly faster than its top airspeed plus the wind. Put
together, those bound a region. A position outside it is not "unlikely" --
it is physically impossible for this airframe, and a GNSS fix claiming it is
false, whatever its accuracy figure says.

THE REGION

After tau seconds the aircraft lies in the overlap of two discs:

  manoeuvre disc   centred where the starting velocity carries it
                   (p0 + v0 tau), radius 1/2 a_max tau^2 -- the furthest any
                   sequence of manoeuvres can pull it off that line

  speed disc       centred on p0, radius v_max tau -- it cannot cover more
                   ground than top speed allows

Both are widened by how well the starting point was known (its position and
velocity sigmas, at K_SIGMA), by the checked fix's own stated sigma (also at
K_SIGMA) and by how much the wind could have changed.
Using only hard limits and generous margins means an honest fix never lands
outside: no false alarms, by construction rather than by tuning.

WHAT IT CANNOT CATCH

A spoofer who moves the reported position slowly -- no faster than the
aircraft could genuinely have flown -- stays inside the region the whole
time. This guard does not see that attack. The statistical gate in L0, which
checks each fix against an independent reference, does: it caught a 1 m/s
drag-off after 14 s in simulation. The two cover fast and slow attacks
together; neither covers both alone.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

G = 9.80665
DEG_M = 111_320.0


@dataclass(frozen=True)
class Envelope:
    """What this airframe can physically do. From its spec or its learned
    model -- never tuned to make a test pass."""
    max_accel_ms2: float          # horizontal
    max_airspeed_ms: float
    max_wind_ms: float = 15.0
    max_wind_change_ms: float = 5.0
    """How much the wind may change over the interval -- a hard bound for a
    gust front, not a typical value."""

    @classmethod
    def from_airframe(cls, thrust_to_mass: float, max_airspeed_ms: float,
                      max_wind_ms: float = 15.0) -> "Envelope":
        """Horizontal acceleration available while holding altitude:
        sqrt((T/m)^2 - g^2)."""
        if thrust_to_mass <= G:
            raise ValueError("thrust-to-mass below 1 g: the airframe cannot fly")
        return cls(math.sqrt(thrust_to_mass ** 2 - G ** 2), max_airspeed_ms,
                   max_wind_ms)


@dataclass
class Verdict:
    possible: bool
    excess_m: float              # how far outside the region; <= 0 means inside
    radius_m: float              # the manoeuvre radius at this time
    seconds_since_anchor: float
    reason: str


class ReachabilityGuard:
    K_SIGMA = 5.0
    """Margin on the anchor's own uncertainty. Five sigma: an honest anchor
    error larger than this happens less than once in a million."""

    def __init__(self, envelope: Envelope):
        self.envelope = envelope
        self._anchor: Optional[Tuple[float, float, float, float, float, float, float]] = None

    def anchor(self, lat: float, lon: float, t: float,
               velocity_ne: Tuple[float, float] = (0.0, 0.0),
               sigma_pos_m: float = 5.0, sigma_vel_ms: float = 1.0) -> None:
        """A trusted fix. The region grows from here."""
        self._anchor = (lat, lon, t, velocity_ne[0], velocity_ne[1],
                        sigma_pos_m, sigma_vel_ms)

    @property
    def anchored(self) -> bool:
        return self._anchor is not None

    def check(self, lat: float, lon: float, t: float,
              sigma_m: float = 0.0) -> Verdict:
        """sigma_m: the checked fix's own per-axis 1-sigma. Without it an
        honest fix's error alone could, rarely, carry it over the edge."""
        if self._anchor is None:
            return Verdict(True, 0.0, float("inf"), 0.0,
                           "no trusted anchor yet: nothing to bound against")
        lat0, lon0, t0, vn, ve, sp, sv = self._anchor
        tau = max(0.0, t - t0)
        env = self.envelope
        coslat = math.cos(math.radians(lat0))
        n = (lat - lat0) * DEG_M
        e = (lon - lon0) * DEG_M * coslat

        margin = (self.K_SIGMA * (sp + max(sigma_m, 0.0) + sv * tau)
                  + env.max_wind_change_ms * tau)
        r_manoeuvre = 0.5 * env.max_accel_ms2 * tau * tau + margin
        r_speed = (env.max_airspeed_ms + env.max_wind_ms) * tau + margin

        off_line = math.hypot(n - vn * tau, e - ve * tau) - r_manoeuvre
        off_speed = math.hypot(n, e) - r_speed
        excess = max(off_line, off_speed)
        if excess > 0:
            which = ("faster than the airframe can fly" if off_speed >= off_line
                     else "further off its track than its motors could pull it")
            return Verdict(False, excess, r_manoeuvre, tau,
                           f"physically impossible: {excess:.0f} m beyond the "
                           f"reachable region after {tau:.1f} s -- {which}")
        return Verdict(True, excess, r_manoeuvre, tau, "within the reachable region")
