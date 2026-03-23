"""
Group F — Acoustic Layers (3 layers).

Layer 10: Passive Acoustic Triangulation
Layer 34: Active Acoustic Sonar Mapping [N]
Layer 35: Focused Sonar Beam Imaging [N, U]
"""

from __future__ import annotations

import math
import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class PassiveAcousticLayer(NavigationLayer):
    """Layer 10 — Passive Acoustic Triangulation.

    Position from timing of known acoustic signals.
    Critical for underwater where all satellite signals fail.
    """

    def __init__(self):
        super().__init__(
            layer_id="acoustic_l10",
            layer_number=10,
            name="Passive Acoustic Triangulation",
            group=LayerGroup.F_ACOUSTIC,
            capabilities=[LayerCapability.POSITION],
            is_underwater=True,
            description="Acoustic signal timing triangulation",
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
        """TOA trilateration from acoustic beacons via SimulationWorld."""
        sound_speed = 1500.0  # m/s
        arrivals = self.world.get_acoustic_arrivals()

        if len(arrivals) < 3:
            # Not enough beacons — fall back
            return self._read_fallback()

        # Convert TOA to distance, then weighted centroid
        weights = []
        lats = []
        lons = []
        for arr in arrivals:
            dist_m = arr["toa_s"] * sound_speed
            # Weight inversely proportional to distance (closer = better)
            w = 1.0 / max(dist_m, 1.0)
            weights.append(w)
            lats.append(arr["known_lat"])
            lons.append(arr["known_lon"])

        total_w = sum(weights)
        lat = sum(w * la for w, la in zip(weights, lats)) / total_w
        lon = sum(w * lo for w, lo in zip(weights, lons)) / total_w

        # Accuracy estimate from spread of distances
        noise_m = 50.0
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.6,
            raw_data={
                "sources_detected": len(arrivals),
                "sound_speed_ms": sound_speed,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        noise_m = 50.0
        lat = base_lat + np.random.normal(0, noise_m / 111_000)
        lon = base_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.6,
            raw_data={"sources_detected": 3, "sound_speed_ms": 1500},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class ActiveSonarLayer(NavigationLayer):
    """Layer 34 — Active Acoustic Sonar Mapping.

    Ultrasonic pulse echo for 3D environment mapping.
    Inspired by bat echolocation — sub-hair-width detection in darkness.
    USAF: sub-100g bat-inspired sonar for GPS-denied drone navigation.
    """

    def __init__(self):
        super().__init__(
            layer_id="sonar_l34",
            layer_number=34,
            name="Active Sonar Mapping",
            group=LayerGroup.F_ACOUSTIC,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Bat echolocation",
            description="Bat-inspired ultrasonic 3D environment mapping",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Sonar echo mapping — true position + noise (no external reference)."""
        noise_m = 5.0
        lat = self.world.true_lat + np.random.normal(0, noise_m / 111_000)
        lon = self.world.true_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.75,
            raw_data={"obstacles": 4, "range_m": 50, "resolution_cm": 2},
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        noise_m = 5.0
        lat = base_lat + np.random.normal(0, noise_m / 111_000)
        lon = base_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.75,
            raw_data={"obstacles": 4, "range_m": 50, "resolution_cm": 2},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class FocusedSonarLayer(NavigationLayer):
    """Layer 35 — Focused Sonar Beam Imaging [NOVEL, UNDERWATER].

    Directional acoustic beam for precise object identification.
    Inspired by dolphin directional sonar — 3D acoustic images.
    """

    def __init__(self):
        super().__init__(
            layer_id="focsonar_l35",
            layer_number=35,
            name="Focused Sonar Beam Imaging",
            group=LayerGroup.F_ACOUSTIC,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Dolphin directional sonar",
            description="Dolphin-inspired directional acoustic imaging",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self._simulated:
            # Environment-only layer — no position computation
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.7,
                raw_data={
                    "objects_imaged": 2,
                    "beam_width_deg": 5,
                    "acoustic_image_resolution": "high",
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass
