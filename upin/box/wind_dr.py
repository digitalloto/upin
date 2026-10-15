"""
Wind-and-tilt dead reckoning: a ground velocity from sensors every drone
has, for when there is no flow sensor, no camera and no trained model.

    ground velocity = air velocity + wind

The wind is the Wind Learner's, learned while GNSS was trusted and frozen
when it went (its sigma widens with time, a labelled assumption). The air
velocity comes one of two ways:

  multirotor   the Speed Learner's tilt-to-airspeed curve, learned on the
               trusted leg of the same flight (or loaded for this airframe
               and payload), along the direction the thrust leans. At steady
               state a multirotor's lean balances drag:

                   g tan(tilt) . u_lean = a_horizontal + k |air| air

               so when the IMU reports the horizontal acceleration, the
               drag part of the lean is what is left after the acceleration
               is taken out, and that is what the curve maps to airspeed.
               A turn's centripetal lean is removed this way; without an
               IMU the estimate declines while turning and uses the raw
               lean when steady.

  fixed wing   the pitot airspeed along the heading (sideslip ignored,
               stated). Only when the box is told a real airspeed sensor is
               fitted: without one, ArduPilot fills VFR_HUD.airspeed from its
               own EKF, which used GNSS -- circular.

WHERE IT REFUSES, AND SAYS SO
  no wind estimate (the Wind Learner's own reason: too few steady samples,
  one heading, GNSS lost before it was learned); no tilt curve yet; a tilt
  outside the learned range (the curve never extrapolates); attitude stale;
  turning without an IMU to take the turn out.

The sigma is honest about what it knows: the curve's standard error, the
wind sigma (growing while frozen), the measured gust spread, and the IMU
correction's own noise. It is fed to the filter only when nothing better
(flow chip, camera flow, AI predictor) has fed it in the last second.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from upin.core.speed_learner import SpeedLearner
from upin.core.wind_learner import WindLearner

G = 9.80665


def body_accel_ne(acc_body, roll: float, pitch: float, yaw: float) -> Tuple[float, float]:
    """The IMU's body specific force turned into horizontal acceleration in
    north/east, with gravity taken out (the same ZYX rotation as the rest
    of the simulator and the flow integrity check)."""
    cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch),
                              math.sin(pitch), math.cos(yaw), math.sin(yaw))
    ax, ay, az = acc_body
    an = (cy * cp) * ax + (cy * sp * sr - sy * cr) * ay + (cy * sp * cr + sy * sr) * az
    ae = (sy * cp) * ax + (sy * sp * sr + cy * cr) * ay + (sy * sp * cr - cy * sr) * az
    return an, ae


class WindDeadReckoning:
    """Ground velocity from the lean (or the pitot) plus the frozen wind."""

    MAX_TURN_RATE_DEG_S = 5.0
    """**Assumption.** Faster than this, and without an IMU to take the turn's
    lean out, the steady-state curve does not apply: decline."""
    ACCEL_SIGMA_MS2 = 0.15
    """**Assumption.** Error of the one-second mean horizontal acceleration
    from the flight controller's IMU and attitude, m/s^2; it becomes an
    airspeed error through the curve's slope."""

    def __init__(self, wind: WindLearner, speed: Optional[SpeedLearner] = None):
        self.wind = wind
        self.speed = speed
        self.last: Optional[dict] = None

    @staticmethod
    def _declined(why: str, **extra) -> dict:
        return {"status": "declined", "reason": why, **extra}

    def estimate(self, t: float, tilt_deg: Optional[float], direction_deg: Optional[float],
                 accel_ne: Optional[Tuple[float, float]] = None,
                 turn_rate_deg_s: Optional[float] = None,
                 airspeed: Optional[Tuple[float, float]] = None,
                 heading_deg: Optional[float] = None) -> dict:
        """tilt_deg / direction_deg: how far and toward which compass direction
        the thrust leans (one-second means). accel_ne: the IMU's horizontal
        acceleration over the same second, if known. airspeed: (m/s, sigma)
        from a real airspeed sensor, used along heading_deg instead of the
        tilt curve."""
        w = self.wind.estimate(t)
        if w is None:
            self.last = self._declined("no wind estimate: " + (self.wind.why_not() or "not learned"))
            return self.last
        if airspeed is not None:
            if heading_deg is None:
                self.last = self._declined("airspeed without a heading")
                return self.last
            air, s_air = airspeed
            d = math.radians(heading_deg)
            an, ae = air * math.cos(d), air * math.sin(d)
            source, extra = "pitot", {}
        else:
            if tilt_deg is None or direction_deg is None:
                self.last = self._declined("attitude stale or absent")
                return self.last
            if self.speed is None:
                self.last = self._declined("no airframe_id: the tilt-to-airspeed curve is per airframe")
                return self.last
            if not self.speed.primed:
                self.last = self._declined("no tilt-to-airspeed curve yet: needs a trusted leg with "
                                           "steady flight on several headings")
                return self.last
            # the lean, as a horizontal acceleration vector
            dr = math.radians(direction_deg)
            ln = G * math.tan(math.radians(tilt_deg))
            lean = (ln * math.cos(dr), ln * math.sin(dr))
            if accel_ne is not None:
                drag = (lean[0] - accel_ne[0], lean[1] - accel_ne[1])
                corrected = True
            else:
                if turn_rate_deg_s is not None and abs(turn_rate_deg_s) > self.MAX_TURN_RATE_DEG_S:
                    self.last = self._declined(
                        f"turning at {abs(turn_rate_deg_s):.0f} deg/s with no IMU to take the "
                        "turn's lean out of the tilt")
                    return self.last
                drag, corrected = lean, False
            dmag = math.hypot(*drag)
            eff_tilt = math.degrees(math.atan2(dmag, G))
            lk = self.speed.lookup(eff_tilt)
            if lk is None:
                rng = self.speed.learned_range
                self.last = self._declined(
                    f"tilt {eff_tilt:.1f} deg outside the learned range "
                    f"{rng[0]:.1f}-{rng[1]:.1f} deg: the curve never extrapolates")
                return self.last
            air, _scatter = lk
            s_air = self.speed.mean_sigma(eff_tilt) or _scatter
            if dmag > 1e-6:
                an, ae = air * drag[0] / dmag, air * drag[1] / dmag
            else:
                an = ae = 0.0
            if corrected:
                # the acceleration error moves the effective lean; the curve's
                # slope dv/d(g tan) turns that into an airspeed error
                slope = self._slope(eff_tilt)
                s_air = math.hypot(s_air, slope * self.ACCEL_SIGMA_MS2)
            source = "tilt curve"
            extra = {"tilt_deg": tilt_deg, "direction_deg": direction_deg,
                     "effective_tilt_deg": eff_tilt, "imu_corrected": corrected,
                     "learned_range_deg": list(self.speed.learned_range or ())}
        sigma = math.hypot(s_air, w.sigma_ms, w.gust_sigma_ms)
        self.last = {
            "status": "ok", "t": t, "vn": an + w.north_ms, "ve": ae + w.east_ms,
            "sigma_ms": sigma, "airspeed_ms": math.hypot(an, ae), "airspeed_sigma_ms": s_air,
            "air_source": source,
            "wind": {"north_ms": w.north_ms, "east_ms": w.east_ms, "sigma_ms": w.sigma_ms,
                     "gust_sigma_ms": w.gust_sigma_ms, "frozen": w.frozen,
                     "age_s": w.seconds_frozen, "samples": w.samples},
            **extra,
        }
        return self.last

    def _slope(self, tilt_deg: float) -> float:
        """d(airspeed) / d(lean acceleration), s, from the curve itself."""
        h = 0.25
        lo = self.speed.lookup(max(tilt_deg - h, 0.0))
        hi = self.speed.lookup(tilt_deg + h) or self.speed.lookup(tilt_deg)
        if lo is None or hi is None:
            return 0.0
        da = G * (math.tan(math.radians(tilt_deg + h)) - math.tan(math.radians(max(tilt_deg - h, 0.0))))
        return abs(hi[0] - lo[0]) / max(da, 1e-6)
