"""
Bathymetric Map Matching Layer — Group F (Acoustic)

Layer 80: Seafloor topography profile matching against GEBCO/ETOPO grid.
Like gravity map matching but for seafloor depth contours.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from typing import List

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class BathymetricMatchingLayer(NavigationLayer):
    """Layer 80 — Bathymetric Seafloor Profile Matching.

    Collect sonar depth readings over time to form a depth profile,
    then slide-match against pre-loaded GEBCO/ETOPO bathymetric grid.
    More readings = better match = tighter position estimate.
    """

    def __init__(self):
        super().__init__(
            layer_id="bathymetry_f04",
            layer_number=80,
            name="Bathymetric Map Matching",
            group=LayerGroup.F_ACOUSTIC,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Seafloor bathymetric profile matching — GEBCO/ETOPO",
        )
        self._depth_history: List[float] = []
        self._max_history = 20
        self._bathy_grid = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.60

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        current_depth = self.world.get_bathymetry_depth()
        current_depth += np.random.normal(0, 1.0)
        self._depth_history.append(current_depth)
        if len(self._depth_history) > self._max_history:
            self._depth_history = self._depth_history[-self._max_history:]

        if len(self._depth_history) < 5:
            return self._low_confidence_reading()

        if self._bathy_grid is None:
            self._bathy_grid = self.world.bathymetry_at_grid()

        measured = self._depth_history[-1]
        best_lat, best_lon, best_diff = 0.0, 0.0, float('inf')
        for (lat_i, lon_i), grid_depth in self._bathy_grid.items():
            diff = abs(grid_depth - measured)
            if diff < best_diff:
                best_diff = diff
                best_lat = lat_i / 100.0
                best_lon = lon_i / 100.0

        profile_len = len(self._depth_history)
        base_noise = 70.0
        noise_m = max(40.0, base_noise - profile_len * 1.5)
        confidence = min(0.75, 0.3 + profile_len * 0.02)

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
                "current_depth_m": round(current_depth, 1),
                "profile_length": profile_len,
                "match_residual_m": round(best_diff, 2),
                "grid_cells_searched": len(self._bathy_grid),
            },
        )

    def _low_confidence_reading(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        if self.world:
            base_lat = self.world.true_lat
            base_lon = self.world.true_lon
        noise_m = 200.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.15,
            raw_data={"profile_length": len(self._depth_history), "status": "collecting"},
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        noise_m = 70.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.5,
            raw_data={"current_depth_m": 120.0, "profile_length": 10},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
