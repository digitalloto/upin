"""
Quantum inertial bridge — Q4 feeding the strapdown INS.

Heading drift is what ultimately destroys every dead-reckoning solution.
Position error from a gyro bias grows as the *integral* of the heading error,
so it accumulates quadratically with time: a constant bias b produces heading
error b*t and cross-track error roughly v*b*t^2/2. Doubling the endurance
quadruples the error. No amount of clever filtering fixes a biased gyro,
because the bias is not noise — it is signal the filter has no reason to
reject.

That is why the gyro grade sets the whole GPS-denied endurance budget:

    phone MEMS     10      deg/hr
    consumer        3      deg/hr
    tactical        0.5    deg/hr
    navigation      0.01   deg/hr
    strategic       0.001  deg/hr
    quantum         0.000002 deg/hr      <- atomgyro_q04

Four orders of magnitude below navigation grade is not an incremental gain.
It moves the binding constraint off the gyro entirely and onto the
accelerometer and the gravity model, which is a different engineering
problem with different answers.

This module reads the Q4 layer, extracts its measured bias stability, and
reconfigures a StrapdownINS to match — including re-deriving how long the
platform can run before its position error crosses a given threshold.

Additive by construction: StrapdownINS gains a profile entry, nothing in its
propagation maths changes, and a platform with no atom gyro never calls this.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from upin.core.layer_base import LayerReading
from upin.core.strapdown_ins import IMUGrade, StrapdownINS


@dataclass
class DriftBudget:
    """How long this platform can navigate before error crosses a limit."""
    grade: str
    gyro_drift_deg_hr: float
    heading_error_after_1hr_deg: float
    cross_track_error_after_1hr_m: float
    seconds_to_10m_error: float
    seconds_to_100m_error: float
    hours_to_1km_error: float


class QuantumInertialBridge:
    """Reconfigures a StrapdownINS from a live Q4 atom-gyro reading.

    The bridge does three things and nothing else:
      1. reads the measured bias stability out of the Q4 layer
      2. selects (or synthesises) the matching IMU grade
      3. reports the honest endurance budget that grade buys
    """

    QUANTUM_GRADE = "quantum"

    def __init__(self, cruise_speed_ms: float = 30.0):
        self._cruise = cruise_speed_ms
        self._ins: Optional[StrapdownINS] = None
        self._active_grade: Optional[str] = None
        self._measured_drift_deg_hr: Optional[float] = None
        self._updates = 0

    # -- input ------------------------------------------------------

    def read_q4(self, q4_reading: LayerReading) -> Dict:
        """Extract the measured bias stability from an atomgyro_q04 reading."""
        d = q4_reading.raw_data or {}
        raw = d.get("bias_drift_deg_per_hr")
        if raw is None:
            return {"accepted": False, "reason": "no bias_drift_deg_per_hr in reading"}
        try:
            drift = float(raw)
        except (TypeError, ValueError):
            return {"accepted": False, "reason": f"unparseable drift value: {raw!r}"}
        if not math.isfinite(drift) or drift < 0:
            return {"accepted": False, "reason": f"implausible drift: {drift}"}

        self._measured_drift_deg_hr = drift
        self._updates += 1
        return {
            "accepted": True,
            "measured_drift_deg_hr": drift,
            "grade": self.grade_for_drift(drift),
            "beats_navigation_grade": drift < 0.01,
            "orders_of_magnitude_vs_navigation": (
                math.log10(0.01 / drift) if drift > 0 else float("inf")),
            "squeezing_db": d.get("squeezing_db"),
            "per_particle_advantage": d.get("per_particle_advantage"),
        }

    @staticmethod
    def grade_for_drift(drift_deg_hr: float) -> str:
        """Map a measured bias stability onto the closest IMU grade."""
        ordered = sorted(
            IMUGrade.PROFILES.items(),
            key=lambda kv: kv[1]["gyro_drift_deg_hr"])
        for name, prof in ordered:
            if drift_deg_hr <= prof["gyro_drift_deg_hr"] * 1.5:
                return name
        return ordered[-1][0]

    # -- configuration ----------------------------------------------

    def configure_ins(self, ins: Optional[StrapdownINS] = None,
                      lat: float = 13.0827, lon: float = 80.2707,
                      alt: float = 100.0) -> StrapdownINS:
        """Build or reconfigure a StrapdownINS at the measured grade."""
        grade = (self.grade_for_drift(self._measured_drift_deg_hr)
                 if self._measured_drift_deg_hr is not None
                 else self.QUANTUM_GRADE)
        self._active_grade = grade
        if ins is None:
            ins = StrapdownINS(initial_lat=lat, initial_lon=lon,
                               initial_alt=alt, hardware_grade=grade)
        else:
            # Re-point an existing INS at the new profile. Only the noise
            # parameters move — the propagation maths is untouched.
            ins._grade_name = grade
            ins._grade = IMUGrade.get_profile(grade)
            ins._auto_detect = False
        self._ins = ins
        return self._ins

    # -- the number that actually matters ---------------------------

    def drift_budget(self, grade: Optional[str] = None,
                     speed_ms: Optional[float] = None) -> DriftBudget:
        """Endurance budget for a grade.

        Cross-track error from a constant gyro bias b (rad/s) at speed v is
        approximately v*b*t^2/2 — quadratic in time, which is why bias
        stability dominates long-endurance GPS-denied navigation.
        """
        g = grade or self._active_grade or self.QUANTUM_GRADE
        prof = IMUGrade.get_profile(g)
        drift_deg_hr = prof["gyro_drift_deg_hr"]
        v = speed_ms if speed_ms is not None else self._cruise

        b_rad_s = math.radians(drift_deg_hr) / 3600.0

        def err_at(t: float) -> float:
            return 0.5 * v * b_rad_s * t * t

        def time_to(limit_m: float) -> float:
            if b_rad_s <= 0 or v <= 0:
                return float("inf")
            return math.sqrt(2.0 * limit_m / (v * b_rad_s))

        return DriftBudget(
            grade=g,
            gyro_drift_deg_hr=drift_deg_hr,
            heading_error_after_1hr_deg=drift_deg_hr,
            cross_track_error_after_1hr_m=err_at(3600.0),
            seconds_to_10m_error=time_to(10.0),
            seconds_to_100m_error=time_to(100.0),
            hours_to_1km_error=time_to(1000.0) / 3600.0,
        )

    def compare_grades(self, speed_ms: Optional[float] = None) -> Dict:
        """Side-by-side endurance for every grade, quantum included."""
        rows = {}
        for name in IMUGrade.PROFILES:
            b = self.drift_budget(name, speed_ms)
            rows[name] = {
                "gyro_drift_deg_hr": b.gyro_drift_deg_hr,
                "cross_track_1hr_m": round(b.cross_track_error_after_1hr_m, 4),
                "minutes_to_100m": round(b.seconds_to_100m_error / 60.0, 2),
                "hours_to_1km": round(b.hours_to_1km_error, 3),
                "cost_usd": IMUGrade.get_profile(name)["cost_usd"],
            }
        q = rows.get(self.QUANTUM_GRADE, {})
        nav = rows.get("navigation", {})
        if q and nav and q["hours_to_1km"] > 0 and nav["hours_to_1km"] > 0:
            gain = q["hours_to_1km"] / nav["hours_to_1km"]
        else:
            gain = 1.0
        return {
            "speed_ms": speed_ms if speed_ms is not None else self._cruise,
            "grades": rows,
            "quantum_vs_navigation_endurance_x": round(gain, 1),
        }

    def get_status(self) -> Dict:
        b = self.drift_budget()
        return {
            "active_grade": self._active_grade,
            "measured_drift_deg_hr": self._measured_drift_deg_hr,
            "updates": self._updates,
            "ins_configured": self._ins is not None,
            "cruise_speed_ms": self._cruise,
            "cross_track_1hr_m": round(b.cross_track_error_after_1hr_m, 6),
            "minutes_to_100m_error": round(b.seconds_to_100m_error / 60.0, 2),
            "hours_to_1km_error": round(b.hours_to_1km_error, 3),
        }
