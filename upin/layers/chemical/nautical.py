"""
Nautical Navigation Layers — Group H (Chemical/Seismic/Flow)

Layer 82: Ocean Current Drift Correction — subtract known current vectors
Layer 83: Tidal Timing Position — match tidal signature to location database

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class OceanCurrentDriftLayer(NavigationLayer):
    """Layer 82 — Ocean Current Drift Correction.

    Look up current vector at estimated position from pre-loaded atlas,
    compute accumulated drift, subtract from dead reckoning position.
    """

    def __init__(self):
        super().__init__(
            layer_id="oceancurrent_h09",
            layer_number=82,
            name="Ocean Current Drift Correction",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY],
            is_novel=True,
            is_underwater=True,
            description="Ocean current drift correction from pre-loaded current atlas",
        )
        self._drift_lat = 0.0
        self._drift_lon = 0.0
        self._last_time: Optional[float] = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.45

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        current = self.world.get_ocean_current()
        speed = current["speed_ms"]
        direction_rad = math.radians(current["direction_deg"])

        now = time.time()
        dt = 1.0
        if self._last_time is not None:
            dt = min(10.0, now - self._last_time)
        self._last_time = now

        drift_n = speed * math.cos(direction_rad) * dt
        drift_e = speed * math.sin(direction_rad) * dt
        self._drift_lat += drift_n / 111_000.0
        cos_lat = math.cos(math.radians(self.world.true_lat))
        self._drift_lon += drift_e / (111_000.0 * max(cos_lat, 0.01))

        noise_m = 150.0
        lat = self.world.true_lat - self._drift_lat + np.random.normal(0, noise_m / 111_000)
        lon = self.world.true_lon - self._drift_lon + np.random.normal(0, noise_m / 111_000)

        cumulative_drift_m = math.sqrt(
            (self._drift_lat * 111_000) ** 2 +
            (self._drift_lon * 111_000 * max(cos_lat, 0.01)) ** 2
        )

        pos = Position(
            latitude=lat, longitude=lon, altitude=0,
            accuracy_m=noise_m, timestamp=now,
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            velocity=speed,
            self_confidence=0.4,
            raw_data={
                "current_speed_ms": round(speed, 2),
                "current_direction_deg": round(current["direction_deg"], 1),
                "drift_correction_lat": round(self._drift_lat, 8),
                "drift_correction_lon": round(self._drift_lon, 8),
                "cumulative_drift_m": round(cumulative_drift_m, 1),
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        noise_m = 150.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            velocity=0.5,
            self_confidence=0.35,
            raw_data={"current_speed_ms": 0.5, "cumulative_drift_m": 0.0},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class TidalTimingPositionLayer(NavigationLayer):
    """Layer 83 — Coastal Position from Tidal Signature Matching.

    Different coastal locations have unique tidal signatures
    (amplitude, phase offset, harmonic mix). Record observed tide
    pattern, match against database → coarse position estimate.
    """

    def __init__(self):
        super().__init__(
            layer_id="tidaltiming_h10",
            layer_number=83,
            name="Tidal Timing Position",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Coastal position from tidal signature matching",
        )
        self._observations: List[Tuple[float, float]] = []
        self._max_obs = 50

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.40

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        tidal = self.world.get_tidal_signature()
        self._observations.append((time.time(), tidal["height_m"]))
        if len(self._observations) > self._max_obs:
            self._observations = self._observations[-self._max_obs:]

        obs_count = len(self._observations)
        if obs_count < 10:
            return self._low_confidence_reading(tidal)

        best_lat, best_lon, best_corr = 0.0, 0.0, -1.0
        search_step = 0.05
        for di in range(-10, 11):
            for dj in range(-10, 11):
                c_lat = self.world.true_lat + di * search_step
                c_lon = self.world.true_lon + dj * search_step
                c_tidal = self.world.get_tidal_signature(c_lat, c_lon)
                corr = 1.0 / (1.0 + abs(c_tidal["amplitude_m"] - tidal["amplitude_m"])
                              + abs(c_tidal["phase"] - tidal["phase"]) * 2.0)
                if corr > best_corr:
                    best_corr = corr
                    best_lat = c_lat
                    best_lon = c_lon

        confidence = min(0.6, 0.15 + obs_count * 0.008)
        noise_m = max(500.0, 2000.0 - obs_count * 30.0)

        lat = best_lat + np.random.normal(0, noise_m / 111_000)
        lon = best_lon + np.random.normal(0, noise_m / 111_000)

        pos = Position(
            latitude=lat, longitude=lon, altitude=0,
            accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=confidence,
            raw_data={
                "tide_height_m": round(tidal["height_m"], 2),
                "observations": obs_count,
                "correlation_strength": round(best_corr, 3),
                "tidal_amplitude_m": round(tidal["amplitude_m"], 2),
                "tidal_phase": round(tidal["phase"], 3),
            },
        )

    def _low_confidence_reading(self, tidal: dict) -> LayerReading:
        base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
        base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
        noise_m = 3000.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.1,
            raw_data={
                "tide_height_m": round(tidal.get("height_m", 0), 2),
                "observations": len(self._observations),
                "status": "collecting",
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        noise_m = 2000.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.2,
            raw_data={"observations": 0, "tide_height_m": 0.5},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
