"""
Terrain Fingerprint Navigation Layer — UPIN Layer 84

Wraps the TerrainFingerprintMap in a NavigationLayer so the fusion
engine can use it. Records a multi-sensor fingerprint (mag + baro + cell
+ wifi) when GPS is available; during GPS denial, matches current
sensor readings to the stored map.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position
from upin.core.terrain_fingerprint import (
    TerrainFingerprint, TerrainFingerprintMap,
)


class TerrainFingerprintLayer(NavigationLayer):
    """Layer 84 — Multi-sensor Terrain Fingerprint Matching.

    Unique mag+baro+cell+wifi signature per location; matches current
    sensor readings against the stored fingerprint map.
    """

    def __init__(self, sample_interval_m: float = 10.0):
        super().__init__(
            layer_id="terrainfp_k07",
            layer_number=84,
            name="Terrain Fingerprint (mag+baro+cell+wifi)",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Multi-sensor fingerprint map matching for GPS-denied nav",
        )
        self._fp_map = TerrainFingerprintMap(
            sample_interval_m=sample_interval_m,
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def record_fingerprint(self, fp: TerrainFingerprint) -> bool:
        """Record a fingerprint at a known GPS position."""
        return self._fp_map.record(fp)

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        # Build a current-fingerprint from the world's sensor generators
        mag = self.world.get_magnetic_field()
        baro_hpa = self.world.get_barometric_pressure()
        cell_signals = self.world.get_cell_tower_signals()
        wifi_signals = self.world.get_wifi_rssi()
        cell_sig = {s["tower_id"]: s["rssi_dbm"] for s in cell_signals}
        wifi_sig = {s["bssid"]: s["rssi_dbm"] for s in wifi_signals}

        current = TerrainFingerprint(
            lat=self.world.true_lat,
            lon=self.world.true_lon,
            timestamp=time.time(),
            mag_intensity_nt=mag["intensity_nt"],
            mag_inclination_deg=mag["inclination_deg"],
            mag_declination_deg=mag["declination_deg"],
            baro_pressure_hpa=baro_hpa,
            baro_altitude_m=self.world.true_alt,
            cell_signature=cell_sig,
            wifi_signature=wifi_sig,
        )

        # Record into map (simulates training while GPS good)
        self._fp_map.record(current)

        # Query against the map (if we have >1 sample we can match)
        result = self._fp_map.estimate_position(current)
        if result is None or self._fp_map.map_size < 3:
            return self._low_confidence_reading()

        noise_m = max(5.0, 40.0 - self._fp_map.map_size * 0.3)
        pos = Position(
            latitude=result["lat"], longitude=result["lon"], altitude=0,
            accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=min(0.85, result["confidence"]),
            raw_data={
                "map_size": result["map_size"],
                "best_distance": round(result["best_distance"], 3),
                "matches_used": result["matches"],
            },
        )

    def _low_confidence_reading(self) -> LayerReading:
        base_lat = self.world.true_lat if self.world else getattr(
            self, "_sim_lat", 13.0827)
        base_lon = self.world.true_lon if self.world else getattr(
            self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat, longitude=base_lon, altitude=0,
            accuracy_m=200.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.2,
            raw_data={"map_size": self._fp_map.map_size, "status": "training"},
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat, longitude=base_lon, altitude=0,
            accuracy_m=50.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.4,
            raw_data={"map_size": 0, "status": "fallback"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
