"""
Group J — Human, Crowd, and Distributed Layers (3 layers).

Layer 20: Human Ground Beacon Network [N]
Layer 21: India Crowdsourced GPS Spoofing Map [N]
Layer 22: Radius Containment and Convergence Lock [N]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class HumanBeaconNetworkLayer(NavigationLayer):
    """Layer 20 — Human Ground Beacon Network [NOVEL].

    Personal devices (phones, wearables, tactical transponders)
    triangulate own position via cell towers. Encrypted position
    transmitted to UPIN as ground reference beacon. Invisible in
    civilian mobile traffic.
    """

    def __init__(self):
        super().__init__(
            layer_id="beacon_l20",
            layer_number=20,
            name="Human Ground Beacon Network",
            group=LayerGroup.J_HUMAN_CROWD,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Encrypted human device ground reference beacons",
        )
        self._beacons: list[dict] = []

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def add_beacon(self, beacon_id: str, lat: float, lon: float) -> None:
        """Register a ground beacon device."""
        self._beacons.append({
            "id": beacon_id, "lat": lat, "lon": lon,
            "timestamp": time.time(),
        })

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            # Simulate 5 nearby beacons
            n_beacons = 5
            noise_m = 30.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.6,
                raw_data={
                    "beacons_active": n_beacons,
                    "encrypted": True,
                    "civilian_traffic_blend": True,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class CrowdsourcedSpoofingMapLayer(NavigationLayer):
    """Layer 21 — India Crowdsourced GPS Spoofing Map [NOVEL].

    Real-time map of GPS anomalies reported by smartphones across India.
    Pre-emptive warning before entering known spoofing zones.
    Covers western and northeastern borders — strategically critical.
    """

    def __init__(self):
        super().__init__(
            layer_id="spoofmap_l21",
            layer_number=21,
            name="Crowdsourced GPS Spoofing Map",
            group=LayerGroup.J_HUMAN_CROWD,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="India-wide real-time GPS anomaly map from smartphones",
        )
        # Known spoofing hotspots (simulated)
        self._hotspots = [
            {"lat": 31.63, "lon": 74.87, "radius_km": 50, "name": "Amritsar corridor"},
            {"lat": 32.73, "lon": 74.86, "radius_km": 40, "name": "Jammu corridor"},
            {"lat": 27.17, "lon": 78.02, "radius_km": 30, "name": "Agra region"},
            {"lat": 34.08, "lon": 77.57, "radius_km": 60, "name": "Ladakh sector"},
        ]

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.3  # Not position — provides threat intelligence

    def read(self) -> LayerReading:
        if self._simulated:
            current_lat = getattr(self, '_sim_lat', 13.0827)
            current_lon = getattr(self, '_sim_lon', 80.2707)

            # Check proximity to known hotspots
            nearby_hotspots = []
            for hs in self._hotspots:
                dist_km = np.sqrt(
                    ((current_lat - hs["lat"]) * 111) ** 2 +
                    ((current_lon - hs["lon"]) * 111 * np.cos(np.radians(current_lat))) ** 2
                )
                if dist_km < hs["radius_km"] * 2:
                    nearby_hotspots.append({
                        "name": hs["name"],
                        "distance_km": round(dist_km, 1),
                        "severity": "HIGH" if dist_km < hs["radius_km"] else "MODERATE",
                    })

            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.7,
                raw_data={
                    "in_spoofing_zone": len(nearby_hotspots) > 0,
                    "nearby_hotspots": nearby_hotspots,
                    "reports_24h": np.random.randint(0, 500),
                    "smartphones_contributing": np.random.randint(10000, 100000),
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class RadiusContainmentLayer(NavigationLayer):
    """Layer 22 — Radius Containment and Convergence Lock [NOVEL].

    Multiple devices define geometric perimeter. AI calculates exact
    dimensions and uses density of reference points inside perimeter
    for centimetre-level accuracy.
    Inspired by spider web distributed vibration sensing.
    """

    def __init__(self):
        super().__init__(
            layer_id="radius_l22",
            layer_number=22,
            name="Radius Containment and Convergence Lock",
            group=LayerGroup.J_HUMAN_CROWD,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            bio_inspiration="Spider web distributed vibration sensing",
            description="Multi-device perimeter convergence — cm accuracy",
        )
        self._perimeter_devices: list[dict] = []

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.85  # Centimetre-level when perimeter is dense

    def add_perimeter_device(self, device_id: str, lat: float, lon: float):
        self._perimeter_devices.append({
            "id": device_id, "lat": lat, "lon": lon,
        })

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            # With enough perimeter devices, achieve cm accuracy
            n_devices = max(6, len(self._perimeter_devices))
            noise_m = max(0.01, 10.0 / n_devices)  # Improves with more devices
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=min(0.95, 0.5 + n_devices * 0.05),
                raw_data={
                    "perimeter_devices": n_devices,
                    "perimeter_radius_m": 500,
                    "convergence_accuracy_m": noise_m,
                    "lock_achieved": n_devices >= 6,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
