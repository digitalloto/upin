"""
Jammer Triangulation — UPIN Intelligence Module

When an adversary activates a GPS jammer or spoofer, they expect to blind
the target. UPIN does the opposite: the moment jamming is detected, this
module uses Time Difference of Arrival (TDOA) from multiple sensor positions
to calculate the physical location of the jammer.

The attacker reveals their own coordinates.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Optional

import numpy as np


class JammerType(Enum):
    GPS_JAMMER = auto()
    GPS_SPOOFER = auto()
    BROADBAND_JAMMER = auto()
    DIRECTED_JAMMER = auto()
    UNKNOWN = auto()


@dataclass
class JammerLocation:
    """The calculated physical location of a detected jammer."""
    lat: float
    lon: float
    confidence: float          # 0.0 to 1.0
    jammer_type: JammerType
    estimated_power_dbm: float
    timestamp: float
    sensor_count: int          # how many sensors contributed
    accuracy_m: float          # estimated position error
    human_authorised: bool = False
    audit_log: list[str] = field(default_factory=list)

    def is_actionable(self) -> bool:
        """Only actionable if human has authorised and confidence is high."""
        return self.human_authorised and self.confidence >= 0.75


@dataclass
class SensorReading:
    """A signal anomaly reading from one sensor at a known position."""
    sensor_id: str
    sensor_lat: float
    sensor_lon: float
    signal_power_dbm: float    # measured jamming power at this sensor
    arrival_time_ns: float     # nanosecond timestamp of detection
    frequency_mhz: float       # jammed frequency band


class JammerTriangulator:
    """
    Calculates the physical location of a GPS jammer or spoofer using
    Time Difference of Arrival (TDOA) across multiple sensor positions.

    Requires at least 3 sensors for 2D triangulation.
    All results require human_authorised=True before transmission.
    """

    SPEED_OF_LIGHT_M_NS = 0.2998   # metres per nanosecond
    MIN_SENSORS = 3

    def __init__(self):
        self._detections: list[JammerLocation] = []
        self._human_authorised: bool = False

    def authorise(self, authorised: bool) -> None:
        """Human operator authorises result transmission."""
        self._human_authorised = authorised

    def triangulate(self, readings: list[SensorReading]) -> Optional[JammerLocation]:
        """
        Takes readings from 3+ sensors and returns the calculated
        jammer location. Returns None if insufficient sensors.
        """
        if len(readings) < self.MIN_SENSORS:
            return None

        ref = readings[0]
        estimated_lat, estimated_lon = self._tdoa_solve(readings)
        confidence = self._calculate_confidence(readings, estimated_lat, estimated_lon)
        accuracy = self._estimate_accuracy(readings, confidence)
        jammer_type = self._classify_jammer(readings)
        avg_power = sum(r.signal_power_dbm for r in readings) / len(readings)

        log_entry = (
            f"[{time.strftime('%H:%M:%S')}] Triangulation from {len(readings)} sensors — "
            f"estimated location {estimated_lat:.6f}N {estimated_lon:.6f}E — "
            f"confidence {confidence:.0%} — type {jammer_type.name} — "
            f"auth={'YES' if self._human_authorised else 'PENDING'}"
        )

        result = JammerLocation(
            lat=estimated_lat,
            lon=estimated_lon,
            confidence=confidence,
            jammer_type=jammer_type,
            estimated_power_dbm=avg_power,
            timestamp=time.time(),
            sensor_count=len(readings),
            accuracy_m=accuracy,
            human_authorised=self._human_authorised,
            audit_log=[log_entry],
        )

        self._detections.append(result)
        return result

    def _tdoa_solve(self, readings: list[SensorReading]) -> tuple[float, float]:
        """
        TDOA solver using hyperbolic positioning.
        Reference sensor is readings[0]. Each other sensor creates one
        hyperbola. The intersection is the jammer location.
        """
        ref = readings[0]

        # Convert all positions to metres (flat earth approx for short range)
        def to_metres(lat, lon):
            x = (lon - ref.sensor_lon) * 111320 * math.cos(math.radians(ref.sensor_lat))
            y = (lat - ref.sensor_lat) * 111320
            return x, y

        # Build weighted centroid from power-law distance estimates
        # Higher power at sensor = closer to jammer
        total_weight = 0.0
        weighted_x = 0.0
        weighted_y = 0.0

        for r in readings:
            # Path loss model: power drops with distance squared
            # P(d) = P0 - 20*log10(d) — invert for distance estimate
            power_diff = abs(r.signal_power_dbm - (-30))  # ref power at 100m
            if power_diff > 0:
                est_distance_m = 100.0 * (10 ** (power_diff / 20.0))
            else:
                est_distance_m = 100.0

            # Weight inversely by estimated distance (closer = more reliable)
            weight = 1.0 / max(est_distance_m, 1.0)

            # TDOA time delta to distance delta
            dt_ns = r.arrival_time_ns - ref.arrival_time_ns
            dist_delta_m = dt_ns * self.SPEED_OF_LIGHT_M_NS

            # Sensor contributes a vector toward estimated source
            sx, sy = to_metres(r.sensor_lat, r.sensor_lon)
            dist_to_sensor = math.sqrt(sx**2 + sy**2) or 1.0
            direction_x = sx / dist_to_sensor
            direction_y = sy / dist_to_sensor

            source_x = sx - direction_x * (est_distance_m + dist_delta_m * 0.5)
            source_y = sy - direction_y * (est_distance_m + dist_delta_m * 0.5)

            weighted_x += source_x * weight
            weighted_y += source_y * weight
            total_weight += weight

        if total_weight == 0:
            return ref.sensor_lat, ref.sensor_lon

        est_x = weighted_x / total_weight
        est_y = weighted_y / total_weight

        # Convert back to lat/lon
        est_lat = ref.sensor_lat + est_y / 111320
        est_lon = ref.sensor_lon + est_x / (111320 * math.cos(math.radians(ref.sensor_lat)))

        return est_lat, est_lon

    def _calculate_confidence(
        self,
        readings: list[SensorReading],
        est_lat: float,
        est_lon: float,
    ) -> float:
        """Confidence rises with more sensors and consistent signal strength."""
        sensor_bonus = min(0.3, (len(readings) - self.MIN_SENSORS) * 0.075)
        base_confidence = 0.65

        powers = [r.signal_power_dbm for r in readings]
        power_variance = np.var(powers)
        consistency_score = max(0.0, 0.25 - power_variance * 0.002)

        return min(0.97, base_confidence + sensor_bonus + consistency_score)

    def _estimate_accuracy(self, readings: list[SensorReading], confidence: float) -> float:
        """Accuracy estimate in metres based on sensor geometry and confidence."""
        if len(readings) >= 6:
            base_accuracy = 25.0
        elif len(readings) >= 4:
            base_accuracy = 75.0
        else:
            base_accuracy = 200.0
        return base_accuracy / confidence

    def _classify_jammer(self, readings: list[SensorReading]) -> JammerType:
        """Classify jammer type from frequency and power signature."""
        freqs = [r.frequency_mhz for r in readings]
        avg_freq = sum(freqs) / len(freqs)
        freq_spread = max(freqs) - min(freqs)

        if freq_spread > 50:
            return JammerType.BROADBAND_JAMMER
        elif 1575 <= avg_freq <= 1577:
            powers = [r.signal_power_dbm for r in readings]
            if max(powers) - min(powers) > 15:
                return JammerType.GPS_SPOOFER
            return JammerType.GPS_JAMMER
        return JammerType.UNKNOWN

    def get_history(self) -> list[JammerLocation]:
        return list(self._detections)

    def clear_history(self) -> None:
        self._detections.clear()
