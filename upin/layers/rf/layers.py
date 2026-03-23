"""
Group D — RF and Terrestrial Signal Layers (5 layers).

Layer 7:  Ground Based Emitters
Layer 8:  WiFi Signal Mapping as Military Navigation [N]
Layer 9:  Cell Tower Triangulation in Hostile Territory [N]
Layer 41: eLORAN Terrestrial Navigation [N, U]
Layer 42: Commercial Satellite Signals of Opportunity (SOOP) [N]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class GroundEmitterLayer(NavigationLayer):
    """Layer 7 — Ground Based Emitters.

    Position triangulation from known fixed RF emitters.
    """

    def __init__(self):
        super().__init__(
            layer_id="groundrf_l7",
            layer_number=7,
            name="Ground Based Emitters",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
            description="RF emitter triangulation positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 50.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.65,
                raw_data={"emitters_visible": 4, "triangulation_quality": 0.8},
            )
        raise NotImplementedError("Live ground emitter requires RF receiver")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class WiFiMilitaryNavLayer(NavigationLayer):
    """Layer 8 — WiFi Signal Mapping as Military Navigation [NOVEL].

    Adversary WiFi infrastructure as passive navigation landmarks.
    Cannot be removed without disrupting their own operations.
    Also provides WiFi radar through-wall sensing for structural
    identification — critical for terminal guidance.
    """

    def __init__(self):
        super().__init__(
            layer_id="wifi_l8",
            layer_number=8,
            name="WiFi Military Navigation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="WiFi as military nav landmarks + through-wall sensing",
        )
        self._wifi_map: dict[str, dict] = {}

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 30.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.6,
                raw_data={
                    "aps_detected": 15,
                    "known_aps_matched": 8,
                    "through_wall_targets": 3,
                    "movement_patterns_inside": True,
                },
            )
        raise NotImplementedError("Live WiFi nav requires WiFi radio")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon

    def scan_through_wall(self) -> dict:
        """WiFi radar through-wall sensing for structural identification."""
        if self._simulated:
            return {
                "bodies_detected": np.random.randint(0, 10),
                "movement_patterns": "civilian" if np.random.random() > 0.3 else "military",
                "confidence": 0.7 + np.random.random() * 0.2,
            }
        raise NotImplementedError


class CellTowerHostileLayer(NavigationLayer):
    """Layer 9 — Cell Tower Triangulation in Hostile Territory [NOVEL].

    Adversary cell towers as position reference. Cannot be disabled
    without destroying their own comms — navigation reference that
    costs the adversary significant self-harm to deny.
    """

    def __init__(self):
        super().__init__(
            layer_id="celltower_l9",
            layer_number=9,
            name="Cell Tower Triangulation (Hostile)",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Adversary cell infrastructure triangulation",
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
            noise_m = 100.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.5,
                raw_data={"towers_detected": 6, "hostile_territory": True},
            )
        raise NotImplementedError("Live cell tower requires radio")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class ELORANLayer(NavigationLayer):
    """Layer 41 — eLORAN Terrestrial Navigation [NOVEL, UNDERWATER].

    Enhanced LORAN using low-frequency terrestrial transmitters.
    Signals 3-5 million times stronger than GPS. Penetrates buildings,
    underground, and underwater.
    """

    def __init__(self):
        super().__init__(
            layer_id="eloran_l41",
            layer_number=41,
            name="eLORAN Terrestrial Navigation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            is_novel=True,
            is_underwater=True,
            description="Enhanced LORAN — 3-5M x stronger than GPS",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 20.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.7,
                raw_data={"signal_strength_dbm": -40, "penetrates": True},
            )
        raise NotImplementedError("Live eLORAN requires receiver")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class CommercialSOOPLayer(NavigationLayer):
    """Layer 42 — Commercial Satellite Signals of Opportunity [NOVEL].

    Doppler from Starlink, Iridium, OneWeb, Globalstar, Orbcomm.
    Operators can't disable without destroying revenue.
    Persistent nav reference independent of dedicated nav sats.
    """

    def __init__(self):
        super().__init__(
            layer_id="soop_l42",
            layer_number=42,
            name="Commercial SOOP",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Starlink/Iridium/OneWeb Doppler positioning",
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
            noise_m = 50.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.55,
                raw_data={"constellations": ["starlink", "iridium"],
                          "sats_tracked": 8},
            )
        raise NotImplementedError("Live SOOP requires wideband receiver")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
