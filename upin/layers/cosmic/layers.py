"""
Group I — Cosmic and Atmospheric Layers (3 layers).

Layer 40: Cosmic Ray Muon Navigation (MuWNS) [N, U]
Layer 29b: Pulsar-Based Extended Navigation [N, U]
Layer 59: Schumann Resonance ELF Navigation [N, U]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class MuonNavigationLayer(NavigationLayer):
    """Layer 40 — Cosmic Ray Muon Navigation (MuWNS) [NOVEL, UNDERWATER].

    Cosmic ray muons strike every m² at ~10,000/min. 200x heavier than
    electrons — penetrate buildings, underground, deep underwater.
    Univ. Tokyo: GPS-comparable accuracy in building basements (2023, iScience).
    Cannot be jammed by any known terrestrial technology.
    """

    def __init__(self):
        super().__init__(
            layer_id="muon_l40",
            layer_number=40,
            name="Cosmic Ray Muon Navigation",
            group=LayerGroup.I_COSMIC_ATMOSPHERIC,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Muon-based navigation — unjammable, penetrates everything",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 10.0  # GPS-comparable in controlled environments
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.6,
                raw_data={
                    "muons_detected_per_min": 10000 + np.random.randint(-500, 500),
                    "reference_stations": 3,
                    "unjammable": True,
                    "underground_capable": True,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class PulsarExtendedLayer(NavigationLayer):
    """Layer 29b — Pulsar-Based Extended Navigation [NOVEL, UNDERWATER].

    Timing arrays of multiple pulsar sources for 3D position in deep
    space and underwater. US Naval Research Laboratory active development.
    """

    def __init__(self):
        super().__init__(
            layer_id="pulsar_l29b",
            layer_number=29,
            name="Pulsar Extended Navigation",
            group=LayerGroup.I_COSMIC_ATMOSPHERIC,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Multi-pulsar timing array positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 200.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.45,
                raw_data={"pulsars_in_array": 5, "timing_precision_ns": 100},
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class SchumannResonanceLayer(NavigationLayer):
    """Layer 59 — Schumann Resonance ELF Navigation [NOVEL, UNDERWATER].

    Earth's atmosphere resonates at 7.83 Hz from ~2000 simultaneous
    thunderstorms (50 lightning/sec). These ELF waves penetrate underground
    and underwater. Cannot be jammed without eliminating global thunderstorms.
    Position from local resonance signature matching.
    """

    def __init__(self):
        super().__init__(
            layer_id="schumann_l59",
            layer_number=59,
            name="Schumann Resonance ELF Navigation",
            group=LayerGroup.I_COSMIC_ATMOSPHERIC,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="7.83 Hz Earth resonance positioning — unjammable",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.4

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 500.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.4,
                raw_data={
                    "fundamental_hz": 7.83 + np.random.normal(0, 0.01),
                    "harmonics": [14.3, 20.8, 27.3, 33.8],
                    "amplitude_pv": 0.5 + np.random.normal(0, 0.05),
                    "unjammable": True,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
