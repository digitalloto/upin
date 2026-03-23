"""
Group G — Gravity Layers (2 layers).

Layer 28a: Quantum Gravity Gradiometer [N, U]
Layer 28b: Quantum Dual Gravimeter [N, U]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class QuantumGravityGradiometerLayer(NavigationLayer):
    """Layer 28a — Quantum Gravity Gradiometer [NOVEL, UNDERWATER].

    Atom interferometry measures gravitational gradient variations.
    Detects underground structures — Univ. Birmingham: 2m tunnel at 19cm accuracy.
    Also provides position via gravitational map matching.
    """

    def __init__(self):
        super().__init__(
            layer_id="gravgrad_l28a",
            layer_number=28,
            name="Quantum Gravity Gradiometer",
            group=LayerGroup.G_GRAVITY,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            description="Atom interferometry gravity gradient — detects underground structures",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Gravity gradient map matching via SimulationWorld."""
        measured = self.world.get_gravity(self.world.true_lat, self.world.true_lon)
        grid = self.world.gravity_at_grid()

        best_lat, best_lon, best_diff = 0.0, 0.0, float('inf')
        for (lat_i, lon_i), anomaly in grid.items():
            diff = abs(anomaly - measured["anomaly_mgal"])
            if diff < best_diff:
                best_diff = diff
                best_lat, best_lon = lat_i / 100.0, lon_i / 100.0

        noise_m = 100.0
        pos = Position(latitude=best_lat, longitude=best_lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.6,
            raw_data={
                "gradient_eotvos": measured["gradient_eotvos"],
                "underground_anomaly": False,
                "tunnel_detected": False,
                "map_match_residual_mgal": best_diff,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        noise_m = 100.0
        lat = base_lat + np.random.normal(0, noise_m / 111_000)
        lon = base_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.6,
            raw_data={
                "gradient_eotvos": 3000 + np.random.normal(0, 10),
                "underground_anomaly": False,
                "tunnel_detected": False,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class QuantumDualGravimeterLayer(NavigationLayer):
    """Layer 28b — Quantum Dual Gravimeter [NOVEL, UNDERWATER].

    Gravitational field variation for maritime navigation via gravity
    map matching. Q-CTRL: 144 hours continuous on RAN MV Sycamore (July 2025).
    """

    def __init__(self):
        super().__init__(
            layer_id="gravimeter_l28b",
            layer_number=28,
            name="Quantum Dual Gravimeter",
            group=LayerGroup.G_GRAVITY,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Gravity map matching — 144hr continuous maritime demo",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Gravity anomaly (mGal) map matching via SimulationWorld."""
        measured = self.world.get_gravity(self.world.true_lat, self.world.true_lon)
        grid = self.world.gravity_at_grid()

        best_lat, best_lon, best_diff = 0.0, 0.0, float('inf')
        for (lat_i, lon_i), anomaly in grid.items():
            diff = abs(anomaly - measured["anomaly_mgal"])
            if diff < best_diff:
                best_diff = diff
                best_lat, best_lon = lat_i / 100.0, lon_i / 100.0

        noise_m = 80.0
        pos = Position(latitude=best_lat, longitude=best_lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.6,
            raw_data={
                "gravity_mgal": measured["g_ms2"] * 1e5,
                "map_match_confidence": 0.7,
                "map_match_residual_mgal": best_diff,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        noise_m = 80.0
        lat = base_lat + np.random.normal(0, noise_m / 111_000)
        lon = base_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.6,
            raw_data={"gravity_mgal": 980000 + np.random.normal(0, 5),
                      "map_match_confidence": 0.7},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
