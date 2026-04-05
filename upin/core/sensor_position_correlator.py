"""
Sensor-Position Correlation Engine — UPIN

Records every sensor reading alongside GPS-confirmed position.
Builds a learned mapping: sensor_pattern → actual_movement.

Over time, the system learns YOUR specific device's relationship
between raw sensor data and real-world movement. This is not
bias correction — it's learning the complete transfer function.

Example learned correlations:
  "accel_z=10.2 + gyro_x=0.5 → moving forward 1.3m/s turning left 5°/s"
  "mag_heading=247 + accel_magnitude=9.9 → stationary, heading SW"
  "wifi_rssi_change=-3dB/s → moving away from AP at ~1.5m/s"

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ── Sensor-Position Sample ────────────────────────────────────────

@dataclass
class CorrelationSample:
    """One recorded moment: all sensors + confirmed position + movement."""
    timestamp: float

    # Confirmed position (from GPS/NavIC/reliable source)
    lat: float
    lon: float
    alt: float
    speed_mps: float
    heading_deg: float

    # Movement since last sample
    delta_lat: float       # degrees moved
    delta_lon: float       # degrees moved
    delta_alt: float       # metres moved vertically
    delta_distance_m: float  # total distance moved
    delta_heading_deg: float  # heading change
    delta_time_s: float

    # Raw sensor readings at this moment
    accel_x: float
    accel_y: float
    accel_z: float
    accel_magnitude: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    gyro_magnitude: float
    mag_x: float
    mag_y: float
    mag_z: float
    mag_heading: float
    pressure_hpa: float
    temperature_c: float

    # Derived features
    is_stationary: bool
    is_turning: bool
    movement_state: str    # stopped, walking, running, driving, turning


# ── Correlation Logger ────────────────────────────────────────────

class SensorPositionLogger:
    """
    Logs every sensor reading alongside GPS position.
    Builds the raw dataset for correlation learning.
    """

    def __init__(self, max_samples: int = 10000):
        self.samples: deque[CorrelationSample] = deque(maxlen=max_samples)
        self._prev_lat = 0.0
        self._prev_lon = 0.0
        self._prev_alt = 0.0
        self._prev_heading = 0.0
        self._prev_time = 0.0
        self._sample_count = 0

    def record(
        self,
        lat: float, lon: float, alt: float, speed: float, heading: float,
        accel: Tuple[float, float, float],
        gyro: Tuple[float, float, float],
        mag: Tuple[float, float, float],
        pressure: float = 1013.25,
        temperature: float = 25.0,
    ):
        """Record one sensor+position sample."""
        now = time.time()
        dt = now - self._prev_time if self._prev_time > 0 else 0.1
        dt = max(dt, 0.001)

        # Calculate movement deltas
        d_lat = lat - self._prev_lat if self._prev_lat != 0 else 0
        d_lon = lon - self._prev_lon if self._prev_lon != 0 else 0
        d_alt = alt - self._prev_alt
        d_heading = heading - self._prev_heading
        # Wrap heading delta to -180..180
        if d_heading > 180: d_heading -= 360
        if d_heading < -180: d_heading += 360

        d_dist = math.sqrt((d_lat * 111320) ** 2 +
                           (d_lon * 111320 * math.cos(math.radians(lat))) ** 2)

        # Sensor magnitudes
        accel_mag = math.sqrt(accel[0]**2 + accel[1]**2 + accel[2]**2)
        gyro_mag = math.sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        mag_heading = math.degrees(math.atan2(mag[1], mag[0])) % 360

        # Classify movement state
        is_stationary = speed < 0.3
        is_turning = abs(d_heading / dt) > 10  # >10 deg/s
        if is_stationary:
            state = "stopped"
        elif is_turning:
            state = "turning"
        elif speed < 2.0:
            state = "walking"
        elif speed < 5.0:
            state = "running"
        else:
            state = "driving"

        sample = CorrelationSample(
            timestamp=now,
            lat=lat, lon=lon, alt=alt, speed_mps=speed, heading_deg=heading,
            delta_lat=d_lat, delta_lon=d_lon, delta_alt=d_alt,
            delta_distance_m=d_dist, delta_heading_deg=d_heading, delta_time_s=dt,
            accel_x=accel[0], accel_y=accel[1], accel_z=accel[2], accel_magnitude=accel_mag,
            gyro_x=gyro[0], gyro_y=gyro[1], gyro_z=gyro[2], gyro_magnitude=gyro_mag,
            mag_x=mag[0], mag_y=mag[1], mag_z=mag[2], mag_heading=mag_heading,
            pressure_hpa=pressure, temperature_c=temperature,
            is_stationary=is_stationary, is_turning=is_turning, movement_state=state,
        )

        self.samples.append(sample)
        self._prev_lat, self._prev_lon, self._prev_alt = lat, lon, alt
        self._prev_heading = heading
        self._prev_time = now
        self._sample_count += 1

    @property
    def count(self) -> int:
        return len(self.samples)


# ── Correlation Learner ───────────────────────────────────────────

class SensorMovementCorrelator:
    """
    Learns the mapping: sensor_readings → actual_movement.

    For each movement state (stopped, walking, driving, turning),
    builds a statistical model of what sensor readings correspond
    to what real movement.

    This is not a neural network — it's a lookup table with
    interpolation, so it works on ANY device with zero training time.
    """

    def __init__(self):
        # Per-state correlation models
        self._state_models: Dict[str, Dict] = {}
        self._accel_to_speed: List[Tuple[float, float]] = []  # (accel_mag, actual_speed)
        self._gyro_to_turn: List[Tuple[float, float]] = []    # (gyro_mag, actual_turn_rate)
        self._mag_to_heading: List[Tuple[float, float]] = []  # (mag_heading, gps_heading)
        self._pressure_to_alt: List[Tuple[float, float]] = [] # (pressure, actual_alt)
        self._total_correlations = 0

    def learn_from_sample(self, sample: CorrelationSample):
        """Learn one correlation from a recorded sample."""
        self._total_correlations += 1

        # Accel magnitude → speed correlation
        self._accel_to_speed.append((sample.accel_magnitude, sample.speed_mps))
        if len(self._accel_to_speed) > 5000:
            self._accel_to_speed = self._accel_to_speed[-5000:]

        # Gyro magnitude → turn rate correlation
        turn_rate = abs(sample.delta_heading_deg / max(sample.delta_time_s, 0.01))
        self._gyro_to_turn.append((sample.gyro_magnitude, turn_rate))
        if len(self._gyro_to_turn) > 5000:
            self._gyro_to_turn = self._gyro_to_turn[-5000:]

        # Mag heading → GPS heading correlation
        self._mag_to_heading.append((sample.mag_heading, sample.heading_deg))
        if len(self._mag_to_heading) > 5000:
            self._mag_to_heading = self._mag_to_heading[-5000:]

        # Pressure → altitude correlation
        self._pressure_to_alt.append((sample.pressure_hpa, sample.alt))
        if len(self._pressure_to_alt) > 2000:
            self._pressure_to_alt = self._pressure_to_alt[-2000:]

        # Per-state model
        state = sample.movement_state
        if state not in self._state_models:
            self._state_models[state] = {
                "accel_mean": [], "speed_mean": [],
                "gyro_mean": [], "turn_mean": [],
                "count": 0,
            }
        model = self._state_models[state]
        model["accel_mean"].append(sample.accel_magnitude)
        model["speed_mean"].append(sample.speed_mps)
        model["gyro_mean"].append(sample.gyro_magnitude)
        model["turn_mean"].append(turn_rate)
        model["count"] += 1
        # Keep last 1000 per state
        for k in ("accel_mean", "speed_mean", "gyro_mean", "turn_mean"):
            if len(model[k]) > 1000:
                model[k] = model[k][-1000:]

    def learn_from_logger(self, logger: SensorPositionLogger):
        """Batch-learn from all logged samples."""
        for sample in logger.samples:
            self.learn_from_sample(sample)

    # ── Prediction from sensors only (GPS denied) ─────────────────

    def predict_speed(self, accel_magnitude: float) -> float:
        """Predict speed from accelerometer magnitude using learned correlation."""
        if len(self._accel_to_speed) < 10:
            return 0.0  # Not enough data

        # Find nearest accel readings and average their speeds
        data = np.array(self._accel_to_speed)
        distances = np.abs(data[:, 0] - accel_magnitude)
        nearest_idx = np.argsort(distances)[:20]  # 20 nearest neighbors
        return float(np.mean(data[nearest_idx, 1]))

    def predict_turn_rate(self, gyro_magnitude: float) -> float:
        """Predict turn rate from gyroscope magnitude."""
        if len(self._gyro_to_turn) < 10:
            return 0.0

        data = np.array(self._gyro_to_turn)
        distances = np.abs(data[:, 0] - gyro_magnitude)
        nearest_idx = np.argsort(distances)[:20]
        return float(np.mean(data[nearest_idx, 1]))

    def predict_heading(self, mag_heading: float) -> float:
        """Predict true heading from magnetometer heading."""
        if len(self._mag_to_heading) < 10:
            return mag_heading

        data = np.array(self._mag_to_heading)
        # Handle heading wrap-around
        mag_diff = np.abs(data[:, 0] - mag_heading)
        mag_diff = np.minimum(mag_diff, 360 - mag_diff)
        nearest_idx = np.argsort(mag_diff)[:20]

        # Average the GPS headings for nearest mag headings
        gps_headings = data[nearest_idx, 1]
        # Circular mean for headings
        sin_sum = np.sum(np.sin(np.radians(gps_headings)))
        cos_sum = np.sum(np.cos(np.radians(gps_headings)))
        return float(np.degrees(np.arctan2(sin_sum, cos_sum))) % 360

    def predict_altitude(self, pressure_hpa: float) -> float:
        """Predict altitude from barometric pressure using learned correlation."""
        if len(self._pressure_to_alt) < 10:
            # Standard barometric formula fallback
            return 44330 * (1 - (pressure_hpa / 1013.25) ** (1 / 5.255))

        data = np.array(self._pressure_to_alt)
        distances = np.abs(data[:, 0] - pressure_hpa)
        nearest_idx = np.argsort(distances)[:10]
        return float(np.mean(data[nearest_idx, 1]))

    def predict_movement_state(self, accel_mag: float, gyro_mag: float) -> str:
        """Classify current movement state from sensors only."""
        best_state = "stopped"
        best_score = -1

        for state, model in self._state_models.items():
            if model["count"] < 5:
                continue
            # How well does this state match current sensors?
            avg_accel = np.mean(model["accel_mean"][-50:])
            avg_gyro = np.mean(model["gyro_mean"][-50:])

            accel_match = 1.0 / (1.0 + abs(accel_mag - avg_accel))
            gyro_match = 1.0 / (1.0 + abs(gyro_mag - avg_gyro))
            score = accel_match * 0.6 + gyro_match * 0.4

            if score > best_score:
                best_score = score
                best_state = state

        return best_state

    def predict_position(
        self,
        last_lat: float, last_lon: float, last_alt: float,
        accel: Tuple[float, float, float],
        gyro: Tuple[float, float, float],
        mag: Tuple[float, float, float],
        pressure: float,
        dt: float,
    ) -> Tuple[float, float, float, float]:
        """
        Predict next position using ONLY sensors (GPS denied).
        Returns (lat, lon, alt, confidence).

        Uses learned correlations instead of raw physics integration.
        """
        accel_mag = math.sqrt(accel[0]**2 + accel[1]**2 + accel[2]**2)
        gyro_mag = math.sqrt(gyro[0]**2 + gyro[1]**2 + gyro[2]**2)
        mag_heading = math.degrees(math.atan2(mag[1], mag[0])) % 360

        # Predict from learned correlations
        speed = self.predict_speed(accel_mag)
        turn_rate = self.predict_turn_rate(gyro_mag)
        heading = self.predict_heading(mag_heading)
        altitude = self.predict_altitude(pressure)
        state = self.predict_movement_state(accel_mag, gyro_mag)

        # Apply predicted movement
        heading_rad = math.radians(heading + turn_rate * dt)
        distance = speed * dt

        new_lat = last_lat + distance * math.cos(heading_rad) / 111320
        new_lon = last_lon + distance * math.sin(heading_rad) / (
            111320 * math.cos(math.radians(last_lat)))

        # Confidence based on correlation data quality
        data_quality = min(1.0, self._total_correlations / 500)
        state_quality = min(1.0, self._state_models.get(state, {}).get("count", 0) / 100)
        confidence = data_quality * 0.6 + state_quality * 0.4

        return (new_lat, new_lon, altitude, confidence)

    # ── Self-improvement ──────────────────────────────────────────

    def recalibrate(self, logger: SensorPositionLogger):
        """
        Rebuild all correlations from scratch using latest data.
        Call this periodically to incorporate recent learning and
        drop old/outdated correlations.
        """
        self._accel_to_speed.clear()
        self._gyro_to_turn.clear()
        self._mag_to_heading.clear()
        self._pressure_to_alt.clear()
        self._state_models.clear()
        self._total_correlations = 0
        self.learn_from_logger(logger)

    def get_correlation_quality(self) -> Dict:
        """How good are the learned correlations?"""
        quality = {}

        if len(self._accel_to_speed) >= 20:
            data = np.array(self._accel_to_speed)
            corr = np.corrcoef(data[:, 0], data[:, 1])[0, 1]
            quality["accel_speed_correlation"] = round(float(corr), 3) if not np.isnan(corr) else 0
        else:
            quality["accel_speed_correlation"] = None

        if len(self._gyro_to_turn) >= 20:
            data = np.array(self._gyro_to_turn)
            corr = np.corrcoef(data[:, 0], data[:, 1])[0, 1]
            quality["gyro_turn_correlation"] = round(float(corr), 3) if not np.isnan(corr) else 0
        else:
            quality["gyro_turn_correlation"] = None

        if len(self._pressure_to_alt) >= 20:
            data = np.array(self._pressure_to_alt)
            corr = np.corrcoef(data[:, 0], data[:, 1])[0, 1]
            quality["pressure_alt_correlation"] = round(float(corr), 3) if not np.isnan(corr) else 0
        else:
            quality["pressure_alt_correlation"] = None

        quality["total_correlations"] = self._total_correlations
        quality["movement_states_learned"] = list(self._state_models.keys())
        quality["state_sample_counts"] = {
            s: m["count"] for s, m in self._state_models.items()
        }

        return quality

    def get_stats(self) -> Dict:
        return {
            "total_correlations": self._total_correlations,
            "accel_speed_samples": len(self._accel_to_speed),
            "gyro_turn_samples": len(self._gyro_to_turn),
            "mag_heading_samples": len(self._mag_to_heading),
            "pressure_alt_samples": len(self._pressure_to_alt),
            "states_learned": len(self._state_models),
            "quality": self.get_correlation_quality(),
        }

    def save(self, filepath: str):
        """Save learned correlations to disk."""
        data = {
            "accel_speed": self._accel_to_speed[-2000:],
            "gyro_turn": self._gyro_to_turn[-2000:],
            "mag_heading": self._mag_to_heading[-2000:],
            "pressure_alt": self._pressure_to_alt[-1000:],
            "total": self._total_correlations,
        }
        with open(filepath, "w") as f:
            json.dump(data, f)

    def load(self, filepath: str):
        """Load previously learned correlations."""
        if not os.path.exists(filepath):
            return
        try:
            with open(filepath) as f:
                data = json.load(f)
            self._accel_to_speed = [tuple(x) for x in data.get("accel_speed", [])]
            self._gyro_to_turn = [tuple(x) for x in data.get("gyro_turn", [])]
            self._mag_to_heading = [tuple(x) for x in data.get("mag_heading", [])]
            self._pressure_to_alt = [tuple(x) for x in data.get("pressure_alt", [])]
            self._total_correlations = data.get("total", len(self._accel_to_speed))
        except (json.JSONDecodeError, IOError):
            pass
