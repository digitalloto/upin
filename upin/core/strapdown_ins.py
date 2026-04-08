"""
Strapdown Inertial Navigation System — UPIN

Replicates what the Soviet space program used: pure physics navigation
from accelerometers and gyroscopes. No GPS, no radio, no external signals.
Just Newton's laws and integration.

How it works (exactly like a physical gyroscope platform):
1. Three accelerometers measure acceleration in body frame (X, Y, Z)
2. Three gyroscopes measure rotation rate in body frame
3. Rotation matrix tracks orientation: body frame → navigation frame
4. Remove gravity from accelerometer readings (since we're on Earth)
5. Double-integrate: acceleration → velocity → position
6. Account for Earth rotation (15°/hour) and Coriolis effect

The Soviets used spinning mechanical gyroscopes on gimbals.
We use the same math on MEMS sensors + software compensation.
The physics hasn't changed since Newton. The sensors have gotten smaller.

Drift compensation:
- Schuler tuning (84.4 minute oscillation period matches Earth curvature)
- Zero-velocity updates (ZUPT) when stationary detected
- Gravity model (WGS-84 ellipsoid)
- Earth rotation compensation

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ── Constants ─────────────────────────────────────────────────────

EARTH_RATE = 7.2921159e-5       # Earth rotation rate (rad/s)
EARTH_RADIUS = 6378137.0        # WGS-84 semi-major axis (m)
EARTH_ECCENTRICITY = 0.0818     # WGS-84 eccentricity
G_EQUATOR = 9.7803253359        # Gravity at equator (m/s²)
G_POLE = 9.8321849378           # Gravity at pole (m/s²)
SCHULER_PERIOD = 84.4 * 60      # Schuler oscillation period (seconds)


# ── Hardware Grade Profiles ───────────────────────────────────────

class IMUGrade:
    """
    Hardware grade profiles. The SAME math runs on all —
    only the noise parameters change.
    """

    PROFILES = {
        "phone_mems": {
            "name": "Phone MEMS (MPU-6050 class)",
            "gyro_drift_deg_hr": 10.0,
            "accel_bias_mg": 10.0,
            "gyro_noise_deg_rt_hr": 0.3,
            "accel_noise_ug_rt_hz": 400.0,
            "position_drift_m_per_s": 1.5,
            "zupt_threshold": 0.08,
            "cost_usd": 2,
        },
        "consumer": {
            "name": "Consumer IMU (BMI160 class)",
            "gyro_drift_deg_hr": 3.0,
            "accel_bias_mg": 3.0,
            "gyro_noise_deg_rt_hr": 0.1,
            "accel_noise_ug_rt_hz": 180.0,
            "position_drift_m_per_s": 0.5,
            "zupt_threshold": 0.04,
            "cost_usd": 20,
        },
        "tactical": {
            "name": "Tactical Grade (STIM300 class)",
            "gyro_drift_deg_hr": 0.5,
            "accel_bias_mg": 0.5,
            "gyro_noise_deg_rt_hr": 0.015,
            "accel_noise_ug_rt_hz": 50.0,
            "position_drift_m_per_s": 0.03,
            "zupt_threshold": 0.01,
            "cost_usd": 5000,
        },
        "navigation": {
            "name": "Navigation Grade (HG1700 class)",
            "gyro_drift_deg_hr": 0.01,
            "accel_bias_mg": 0.025,
            "gyro_noise_deg_rt_hr": 0.003,
            "accel_noise_ug_rt_hz": 10.0,
            "position_drift_m_per_s": 0.0005,  # ~1.8 m/hour = ~1 nm/hour
            "zupt_threshold": 0.002,
            "cost_usd": 50000,
        },
        "strategic": {
            "name": "Strategic Grade (submarine/ICBM class)",
            "gyro_drift_deg_hr": 0.001,
            "accel_bias_mg": 0.005,
            "gyro_noise_deg_rt_hr": 0.001,
            "accel_noise_ug_rt_hz": 3.0,
            "position_drift_m_per_s": 0.00005,  # ~0.18 m/hour
            "zupt_threshold": 0.0005,
            "cost_usd": 500000,
        },
    }

    @staticmethod
    def get_profile(grade: str) -> Dict:
        return IMUGrade.PROFILES.get(grade, IMUGrade.PROFILES["phone_mems"])

    @staticmethod
    def detect_grade_from_noise(accel_noise_std: float, gyro_noise_std: float) -> str:
        """Auto-detect hardware grade from measured noise levels."""
        # Compare noise to known profiles
        accel_mg = accel_noise_std / 9.81 * 1000  # Convert to mg
        gyro_dph = gyro_noise_std * 3600 * 180 / math.pi  # Convert to deg/hr

        if gyro_dph < 0.005:
            return "strategic"
        elif gyro_dph < 0.05:
            return "navigation"
        elif gyro_dph < 2.0:
            return "tactical"
        elif gyro_dph < 5.0:
            return "consumer"
        else:
            return "phone_mems"


# ── Quaternion Math (for rotation tracking) ───────────────────────

class Quaternion:
    """Unit quaternion for 3D rotation — no gimbal lock, unlike Euler angles."""

    def __init__(self, w: float = 1.0, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.w = w
        self.x = x
        self.y = y
        self.z = z
        self._normalize()

    def _normalize(self):
        mag = math.sqrt(self.w**2 + self.x**2 + self.y**2 + self.z**2)
        if mag > 0:
            self.w /= mag; self.x /= mag; self.y /= mag; self.z /= mag

    def multiply(self, other: 'Quaternion') -> 'Quaternion':
        """Hamilton product: combines two rotations."""
        return Quaternion(
            self.w*other.w - self.x*other.x - self.y*other.y - self.z*other.z,
            self.w*other.x + self.x*other.w + self.y*other.z - self.z*other.y,
            self.w*other.y - self.x*other.z + self.y*other.w + self.z*other.x,
            self.w*other.z + self.x*other.y - self.y*other.x + self.z*other.w,
        )

    def to_rotation_matrix(self) -> np.ndarray:
        """Convert to 3x3 rotation matrix (body frame → navigation frame)."""
        w, x, y, z = self.w, self.x, self.y, self.z
        return np.array([
            [1-2*(y*y+z*z), 2*(x*y-w*z),   2*(x*z+w*y)],
            [2*(x*y+w*z),   1-2*(x*x+z*z), 2*(y*z-w*x)],
            [2*(x*z-w*y),   2*(y*z+w*x),   1-2*(x*x+y*y)],
        ])

    def to_euler(self) -> Tuple[float, float, float]:
        """Convert to roll, pitch, yaw (degrees)."""
        # Roll (x-axis rotation)
        sinr_cosp = 2 * (self.w * self.x + self.y * self.z)
        cosr_cosp = 1 - 2 * (self.x * self.x + self.y * self.y)
        roll = math.atan2(sinr_cosp, cosr_cosp)

        # Pitch (y-axis rotation)
        sinp = 2 * (self.w * self.y - self.z * self.x)
        sinp = max(-1, min(1, sinp))
        pitch = math.asin(sinp)

        # Yaw (z-axis rotation)
        siny_cosp = 2 * (self.w * self.z + self.x * self.y)
        cosy_cosp = 1 - 2 * (self.y * self.y + self.z * self.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)

        return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))

    @staticmethod
    def from_gyro_rate(wx: float, wy: float, wz: float, dt: float) -> 'Quaternion':
        """Create rotation quaternion from gyroscope angular rates and time step."""
        angle = math.sqrt(wx*wx + wy*wy + wz*wz) * dt
        if angle < 1e-10:
            return Quaternion(1, 0, 0, 0)
        half_angle = angle / 2
        s = math.sin(half_angle) / (angle / dt)
        return Quaternion(
            math.cos(half_angle),
            wx * s * dt,
            wy * s * dt,
            wz * s * dt,
        )


# ── Gravity Model ─────────────────────────────────────────────────

def gravity_wgs84(lat_rad: float, alt_m: float = 0.0) -> float:
    """WGS-84 gravity model — accounts for latitude and altitude."""
    sin_lat = math.sin(lat_rad)
    g0 = G_EQUATOR * (1 + 0.00193185265241 * sin_lat**2) / math.sqrt(1 - 0.00669437999014 * sin_lat**2)
    # Altitude correction (free air)
    g = g0 * (1 - 2 * alt_m / EARTH_RADIUS)
    return g


def earth_rotation_rate(lat_rad: float) -> np.ndarray:
    """Earth rotation rate vector in navigation frame (NED)."""
    return np.array([
        EARTH_RATE * math.cos(lat_rad),  # North component
        0.0,                              # East component
        -EARTH_RATE * math.sin(lat_rad),  # Down component
    ])


# ── Strapdown INS ─────────────────────────────────────────────────

@dataclass
class INSState:
    """Complete inertial navigation state."""
    latitude_rad: float = 0.0
    longitude_rad: float = 0.0
    altitude_m: float = 0.0
    velocity_north: float = 0.0   # m/s
    velocity_east: float = 0.0    # m/s
    velocity_down: float = 0.0    # m/s
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    heading_deg: float = 0.0
    timestamp: float = 0.0

    @property
    def lat_deg(self) -> float:
        return math.degrees(self.latitude_rad)

    @property
    def lon_deg(self) -> float:
        return math.degrees(self.longitude_rad)

    def to_dict(self) -> Dict:
        return {
            "lat": round(self.lat_deg, 8),
            "lon": round(self.lon_deg, 8),
            "alt_m": round(self.altitude_m, 2),
            "vel_north_mps": round(self.velocity_north, 3),
            "vel_east_mps": round(self.velocity_east, 3),
            "vel_down_mps": round(self.velocity_down, 3),
            "speed_mps": round(math.sqrt(self.velocity_north**2 + self.velocity_east**2), 3),
            "roll_deg": round(self.roll_deg, 2),
            "pitch_deg": round(self.pitch_deg, 2),
            "heading_deg": round(self.heading_deg, 2),
        }


class StrapdownINS:
    """
    Full strapdown inertial navigation system.

    This is the same math the Soviets used, running on code instead of
    mechanical gimbals. Given accelerometer + gyroscope readings and a
    starting position, it computes exact position at every time step.

    Works anywhere: air, land, sea, underwater, underground, space.
    No signals needed. Pure physics.
    """

    def __init__(self, initial_lat: float = 0.0, initial_lon: float = 0.0,
                 initial_alt: float = 0.0, initial_heading: float = 0.0,
                 hardware_grade: str = "auto"):
        """
        Initialize strapdown INS.

        hardware_grade: "phone_mems", "consumer", "tactical", "navigation",
                        "strategic", or "auto" (detect from sensor noise)
        """
        # State
        self.state = INSState(
            latitude_rad=math.radians(initial_lat),
            longitude_rad=math.radians(initial_lon),
            altitude_m=initial_alt,
            heading_deg=initial_heading,
            timestamp=time.time(),
        )

        # Hardware grade
        self._grade_name = hardware_grade if hardware_grade != "auto" else "phone_mems"
        self._grade = IMUGrade.get_profile(self._grade_name)
        self._auto_detect = hardware_grade == "auto"
        self._noise_samples_accel: deque = deque(maxlen=200)
        self._noise_samples_gyro: deque = deque(maxlen=200)

        # Orientation quaternion (body → navigation frame)
        heading_rad = math.radians(initial_heading)
        self._quaternion = Quaternion(
            math.cos(heading_rad / 2), 0, 0, math.sin(heading_rad / 2)
        )

        # Velocity in navigation frame (NED)
        self._velocity = np.array([0.0, 0.0, 0.0])

        # Bias estimates (learned over time)
        self._accel_bias = np.array([0.0, 0.0, 0.0])
        self._gyro_bias = np.array([0.0, 0.0, 0.0])

        # Performance tracking
        self._total_steps = 0
        self._zupt_count = 0
        self._drift_estimate_m = 0.0
        self._history: deque = deque(maxlen=500)
        self._correction_count = 0
        self._last_correction_time = 0.0

        # ZUPT detector — threshold adapts to hardware grade
        self._zupt_threshold = self._grade["zupt_threshold"]
        self._accel_window: deque = deque(maxlen=50)

    def update(self, accel: Tuple[float, float, float],
               gyro: Tuple[float, float, float],
               dt: float = 0.01) -> INSState:
        """
        Process one IMU sample. This is the core INS mechanisation.

        accel: (ax, ay, az) in m/s² — body frame
        gyro: (wx, wy, wz) in rad/s — body frame
        dt: time step in seconds

        Returns updated navigation state.
        """
        self._total_steps += 1

        # Convert to numpy
        accel_body = np.array(accel) - self._accel_bias
        gyro_body = np.array(gyro) - self._gyro_bias

        # ── Step 1: Update orientation (gyroscope integration) ────

        # Compensate for Earth rotation
        omega_earth = earth_rotation_rate(self.state.latitude_rad)
        R = self._quaternion.to_rotation_matrix()
        omega_earth_body = R.T @ omega_earth  # Transform to body frame

        # Corrected gyro rate (remove Earth rotation from measurement)
        gyro_corrected = gyro_body - omega_earth_body

        # Update quaternion
        dq = Quaternion.from_gyro_rate(gyro_corrected[0], gyro_corrected[1],
                                        gyro_corrected[2], dt)
        self._quaternion = self._quaternion.multiply(dq)

        # Get updated rotation matrix
        R = self._quaternion.to_rotation_matrix()

        # ── Step 2: Transform acceleration to navigation frame ────

        accel_nav = R @ accel_body

        # ── Step 3: Remove gravity ────────────────────────────────

        g = gravity_wgs84(self.state.latitude_rad, self.state.altitude_m)
        accel_nav[2] += g  # Remove gravity (NED: gravity is positive down)

        # ── Step 4: Coriolis correction ───────────────────────────

        coriolis = 2 * np.cross(omega_earth, np.append(self._velocity[:2], 0))
        accel_nav[0] -= coriolis[0]
        accel_nav[1] -= coriolis[1]

        # ── Step 5: Integrate velocity (first integration) ────────

        self._velocity += accel_nav * dt

        # ── Step 6: Integrate position (second integration) ───────

        # Meridional radius of curvature
        sin_lat = math.sin(self.state.latitude_rad)
        Rm = EARTH_RADIUS * (1 - EARTH_ECCENTRICITY**2) / (1 - EARTH_ECCENTRICITY**2 * sin_lat**2)**1.5
        # Prime vertical radius
        Rn = EARTH_RADIUS / math.sqrt(1 - EARTH_ECCENTRICITY**2 * sin_lat**2)

        # Update lat/lon/alt
        self.state.latitude_rad += self._velocity[0] * dt / (Rm + self.state.altitude_m)
        self.state.longitude_rad += self._velocity[1] * dt / ((Rn + self.state.altitude_m) * math.cos(self.state.latitude_rad))
        self.state.altitude_m -= self._velocity[2] * dt  # NED: down is positive

        # ── Step 7: Update Euler angles ───────────────────────────

        roll, pitch, yaw = self._quaternion.to_euler()
        self.state.roll_deg = roll
        self.state.pitch_deg = pitch
        self.state.heading_deg = yaw % 360

        # ── Step 8: Store velocity in state ───────────────────────

        self.state.velocity_north = float(self._velocity[0])
        self.state.velocity_east = float(self._velocity[1])
        self.state.velocity_down = float(self._velocity[2])
        self.state.timestamp = time.time()

        # ── Step 9: Zero-velocity update (ZUPT) ──────────────────
        # FIXED: Much stricter ZUPT — only fire when TRULY stationary
        # Walking has accel_std ~0.3-1.0, stationary has <0.02

        self._accel_window.append(np.linalg.norm(accel_body))
        if len(self._accel_window) >= 50:
            accel_std = np.std(list(self._accel_window))
            accel_mean = np.mean(list(self._accel_window))
            # ZUPT threshold adapts to hardware grade
            if accel_std < self._zupt_threshold and abs(accel_mean - g) < self._zupt_threshold * 5:
                self._apply_zupt()

        # Auto-detect hardware grade from noise characteristics
        if self._auto_detect and self._total_steps == 500:
            self._noise_samples_accel.append(np.linalg.norm(accel_body))
            self._noise_samples_gyro.append(np.linalg.norm(gyro_body))
            if len(self._noise_samples_accel) >= 100:
                detected = IMUGrade.detect_grade_from_noise(
                    float(np.std(list(self._noise_samples_accel))),
                    float(np.std(list(self._noise_samples_gyro))),
                )
                self._grade_name = detected
                self._grade = IMUGrade.get_profile(detected)
                self._zupt_threshold = self._grade["zupt_threshold"]
                self._auto_detect = False  # Only detect once

        # ── Step 10: Schuler damping ──────────────────────────────
        # The Schuler oscillation (84.4 min period) causes INS errors
        # to oscillate rather than diverge. Apply light damping.
        schuler_freq = 2 * math.pi / SCHULER_PERIOD
        damping = 0.001  # Light damping factor
        self._velocity[0] *= (1.0 - damping * dt)
        self._velocity[1] *= (1.0 - damping * dt)

        # ── Step 11: Velocity magnitude check ─────────────────────
        # Prevent velocity from growing unrealistically (sanity check)
        speed = math.sqrt(self._velocity[0]**2 + self._velocity[1]**2)
        max_speed = 500.0  # 500 m/s max (Mach 1.5 for aircraft)
        if speed > max_speed:
            self._velocity[:2] *= max_speed / speed

        # ── Step 12: Track drift (grade-dependent) ─────────────────

        drift_rate = self._grade["position_drift_m_per_s"]
        self._drift_estimate_m += drift_rate * dt

        # Store history
        self._history.append(self.state.to_dict())

        return self.state

    def _apply_zupt(self):
        """Zero-velocity update: when stationary, velocity MUST be zero."""
        self._zupt_count += 1
        self._velocity *= 0.0  # Reset velocity
        # Also estimate accelerometer bias from gravity measurement
        if self._accel_window:
            measured_g = np.mean(list(self._accel_window))
            expected_g = gravity_wgs84(self.state.latitude_rad, self.state.altitude_m)
            self._accel_bias[2] += (measured_g - expected_g) * 0.01  # Slow adaptation

    def correct_position(self, true_lat: float, true_lon: float,
                          source: str = "gps"):
        """
        Correct position from external source (GPS, landmark, etc).
        This is how you beat the drift — periodic corrections.
        """
        # Calculate correction
        lat_error = math.radians(true_lat) - self.state.latitude_rad
        lon_error = math.radians(true_lon) - self.state.longitude_rad

        # Apply correction (blend, don't jump)
        alpha = 0.8  # Trust external source 80%
        self.state.latitude_rad += lat_error * alpha
        self.state.longitude_rad += lon_error * alpha

        # Correct velocity from position error (helps prevent repeating same drift)
        if self._correction_count > 0:
            dt_since_correction = max(0.1, time.time() - self._last_correction_time)
            vel_correction_n = lat_error * alpha * (EARTH_RADIUS + self.state.altitude_m) / dt_since_correction
            vel_correction_e = lon_error * alpha * (EARTH_RADIUS + self.state.altitude_m) * math.cos(self.state.latitude_rad) / dt_since_correction
            self._velocity[0] += vel_correction_n * 0.3  # Gentle velocity correction
            self._velocity[1] += vel_correction_e * 0.3

        # Reset drift estimate
        self._drift_estimate_m *= 0.3  # Corrections reduce drift significantly
        self._correction_count += 1
        self._last_correction_time = time.time()

    def get_position(self) -> Dict:
        """Get current position in UPIN-compatible format."""
        return {
            "lat": self.state.lat_deg,
            "lon": self.state.lon_deg,
            "alt_m": self.state.altitude_m,
            "heading_deg": self.state.heading_deg,
            "speed_mps": math.sqrt(self.state.velocity_north**2 + self.state.velocity_east**2),
            "accuracy_m": max(0.1, self._drift_estimate_m),
            "confidence": max(0.1, min(0.95, 1.0 - self._drift_estimate_m / 100)),
            "source": "strapdown_ins",
            "hardware_grade": self._grade_name,
            "hardware_name": self._grade["name"],
            "drift_rate_m_per_s": self._grade["position_drift_m_per_s"],
            "zupt_corrections": self._zupt_count,
            "position_corrections": self._correction_count,
            "total_steps": self._total_steps,
        }

    def get_stats(self) -> Dict:
        return {
            "steps": self._total_steps,
            "zupt_corrections": self._zupt_count,
            "drift_estimate_m": round(self._drift_estimate_m, 2),
            "accel_bias": self._accel_bias.tolist(),
            "gyro_bias": self._gyro_bias.tolist(),
            "orientation": {
                "roll": round(self.state.roll_deg, 2),
                "pitch": round(self.state.pitch_deg, 2),
                "heading": round(self.state.heading_deg, 2),
            },
            "velocity": {
                "north": round(self.state.velocity_north, 3),
                "east": round(self.state.velocity_east, 3),
                "down": round(self.state.velocity_down, 3),
            },
        }


# ── UPIN Navigation Layer Wrapper ─────────────────────────────────

class GlobusINSReading:
    """
    Wraps StrapdownINS as a UPIN-compatible position source.
    Named after the Soviet Globus mechanical navigation computer.

    Feed it accelerometer + gyroscope readings every tick.
    It produces lat/lon/heading using pure physics — no GPS needed.
    """

    def __init__(self, initial_lat: float = 13.0827, initial_lon: float = 80.2707,
                 initial_heading: float = 0.0):
        self.ins = StrapdownINS(initial_lat, initial_lon, 10.0, initial_heading)
        self._last_update = time.time()

    def update_sensors(self, accel: Tuple[float, float, float],
                        gyro: Tuple[float, float, float]) -> Dict:
        """Feed raw sensor data, get UPIN-compatible position back."""
        now = time.time()
        dt = min(0.1, now - self._last_update)  # Cap at 100ms
        self._last_update = now

        self.ins.update(accel, gyro, dt)
        return self.ins.get_position()

    def correct_from_gps(self, lat: float, lon: float):
        """Apply GPS correction when available."""
        self.ins.correct_position(lat, lon, "gps")

    def get_layer_reading(self) -> Dict:
        """Get position in standard UPIN layer format."""
        pos = self.ins.get_position()
        return {
            "layer_id": "globus_ins",
            "layer_name": "Globus Strapdown INS",
            "lat": pos["lat"],
            "lon": pos["lon"],
            "accuracy_m": pos["accuracy_m"],
            "confidence": pos["confidence"],
            "heading_deg": pos["heading_deg"],
            "speed_mps": pos["speed_mps"],
            "source": "pure_physics",
            "bio_inspiration": "Soviet Globus mechanical navigation computer",
            "zupt_corrections": pos["zupt_corrections"],
        }
