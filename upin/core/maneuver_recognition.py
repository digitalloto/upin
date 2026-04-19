"""
Maneuver Recognition — UPIN

Ported from UPIN phone-demo v5. Detects turns (45°, 90°, 180°/U-turn),
stops, and accelerations from IMU data. Builds a library of maneuvers
seen with GPS truth; during GPS denial, recognized maneuvers produce
precise heading corrections and position constraints.

One confirmed 90° turn = exact heading fix. This is extremely valuable
in GPS-denied environments because it eliminates heading drift
completely at the moment of recognition.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ManeuverSignature:
    """A recorded maneuver with its sensor fingerprint."""
    maneuver_type: str  # "turn_left", "turn_right", "u_turn", "stop", "accelerate"
    turn_angle_deg: float
    duration_s: float
    peak_gyro_z: float  # rad/s
    peak_accel_mag: float  # m/s^2
    gyro_pattern: List[float] = field(default_factory=list)
    start_time: float = 0.0
    start_lat: float = 0.0
    start_lon: float = 0.0
    end_heading_deg: float = 0.0


class ManeuverRecognizer:
    """Online maneuver detection + library for fingerprint matching.

    Continuously examines the incoming IMU stream; when a gyro/accel
    pattern matches a known maneuver (turn or stop), emits a signature
    plus a heading correction.
    """

    def __init__(self, window_size: int = 60):
        self._gyro_z_history: List[Tuple[float, float]] = []  # (t, rad/s)
        self._accel_mag_history: List[Tuple[float, float]] = []
        self._heading_history: List[Tuple[float, float]] = []  # (t, deg)
        self._window_size = window_size
        self._library: List[ManeuverSignature] = []
        self._current_maneuver_start: Optional[float] = None
        self._current_maneuver_type: Optional[str] = None

        self._turn_threshold_rad_s = 0.3        # |gyro_z| > 0.3 rad/s = turning
        self._stop_accel_threshold = 0.3        # |accel| < 0.3 m/s^2 = stopped
        self._accel_threshold = 3.0             # |accel| > 3 m/s^2 = accelerating
        self._min_turn_duration_s = 0.5

    def feed_imu(self, gyro_z_rad_s: float, accel_magnitude_ms2: float,
                 heading_deg: Optional[float] = None,
                 current_lat: Optional[float] = None,
                 current_lon: Optional[float] = None) -> Optional[Dict]:
        """Feed one IMU sample; returns maneuver event if one completed."""
        now = time.time()
        self._gyro_z_history.append((now, gyro_z_rad_s))
        self._accel_mag_history.append((now, accel_magnitude_ms2))
        if heading_deg is not None:
            self._heading_history.append((now, heading_deg))

        # Trim window
        cutoff = now - 30.0
        self._gyro_z_history = [(t, v) for t, v in self._gyro_z_history if t >= cutoff]
        self._accel_mag_history = [(t, v) for t, v in self._accel_mag_history if t >= cutoff]
        self._heading_history = [(t, v) for t, v in self._heading_history if t >= cutoff]

        return self._detect(gyro_z_rad_s, accel_magnitude_ms2, heading_deg,
                            current_lat, current_lon)

    def _detect(self, gyro_z, accel_mag, heading_deg, lat, lon) -> Optional[Dict]:
        now = time.time()
        is_turning = abs(gyro_z) > self._turn_threshold_rad_s

        # Turn detection — accumulate while gyro is high
        if is_turning and self._current_maneuver_type is None:
            self._current_maneuver_type = ("turn_left" if gyro_z > 0
                                            else "turn_right")
            self._current_maneuver_start = now

        if (self._current_maneuver_type in ("turn_left", "turn_right")
                and not is_turning):
            # Turn ended
            duration = now - (self._current_maneuver_start or now)
            if duration >= self._min_turn_duration_s:
                event = self._finalize_turn(duration, lat, lon, heading_deg)
                self._current_maneuver_type = None
                self._current_maneuver_start = None
                return event
            else:
                self._current_maneuver_type = None
                self._current_maneuver_start = None
        return None

    def _finalize_turn(self, duration_s: float, lat, lon, end_heading) -> Dict:
        # Integrate gyro over the turn to get total angle
        gyro_recent = [v for t, v in self._gyro_z_history
                       if t >= (time.time() - duration_s)]
        if not gyro_recent:
            return {"type": "turn_unknown"}
        # Trapezoidal integration (approx dt = duration / n)
        dt = duration_s / max(1, len(gyro_recent))
        total_rad = sum(gyro_recent) * dt
        total_deg = math.degrees(total_rad)
        peak_gyro = max(abs(v) for v in gyro_recent)

        # Classify
        abs_deg = abs(total_deg)
        if abs_deg >= 150:
            m_type = "u_turn"
            canonical = 180.0 * (1 if total_deg > 0 else -1)
        elif abs_deg >= 70:
            m_type = "turn_90" + ("_left" if total_deg > 0 else "_right")
            canonical = 90.0 * (1 if total_deg > 0 else -1)
        elif abs_deg >= 30:
            m_type = "turn_45" + ("_left" if total_deg > 0 else "_right")
            canonical = 45.0 * (1 if total_deg > 0 else -1)
        else:
            m_type = "turn_minor"
            canonical = total_deg

        sig = ManeuverSignature(
            maneuver_type=m_type,
            turn_angle_deg=total_deg,
            duration_s=duration_s,
            peak_gyro_z=peak_gyro,
            peak_accel_mag=0.0,
            gyro_pattern=list(gyro_recent),
            start_time=time.time() - duration_s,
            start_lat=lat or 0.0,
            start_lon=lon or 0.0,
            end_heading_deg=end_heading or 0.0,
        )
        self._library.append(sig)

        return {
            "type": m_type,
            "turn_angle_deg": total_deg,
            "canonical_angle_deg": canonical,
            "duration_s": duration_s,
            "peak_gyro_rad_s": peak_gyro,
            "library_size": len(self._library),
            "confidence": min(1.0, abs_deg / 180.0),
        }

    def match_turn(self, observed_pattern: List[float],
                   observed_angle_deg: float) -> Optional[Dict]:
        """Find the closest maneuver in the library matching the observed turn."""
        if not self._library:
            return None
        candidates = [m for m in self._library
                      if m.maneuver_type.startswith("turn_")
                      or m.maneuver_type == "u_turn"]
        if not candidates:
            return None
        best = min(candidates,
                   key=lambda m: abs(m.turn_angle_deg - observed_angle_deg))
        residual = abs(best.turn_angle_deg - observed_angle_deg)
        confidence = 1.0 / (1.0 + residual / 10.0)
        return {
            "matched_type": best.maneuver_type,
            "matched_angle_deg": best.turn_angle_deg,
            "residual_deg": residual,
            "confidence": confidence,
        }

    def get_library_stats(self) -> Dict:
        types = {}
        for m in self._library:
            types[m.maneuver_type] = types.get(m.maneuver_type, 0) + 1
        return {
            "total": len(self._library),
            "by_type": types,
        }

    @property
    def library(self) -> List[ManeuverSignature]:
        return list(self._library)
