"""
Terrain Fingerprint Navigation — UPIN

Ported from UPIN phone-demo v5. Records a multi-sensor fingerprint
(magnetometer + barometer + cell-tower signature + wifi AP set)
every N metres along a GPS-known trajectory. During GPS denial,
current sensor readings are cross-correlated against the stored
fingerprint map → position match.

Each sensor modality is a constraint; the combination is unique
enough to disambiguate position in most environments.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class TerrainFingerprint:
    """A single fingerprint sample taken at a known GPS position."""
    lat: float
    lon: float
    timestamp: float
    mag_intensity_nt: float = 0.0
    mag_inclination_deg: float = 0.0
    mag_declination_deg: float = 0.0
    baro_pressure_hpa: float = 0.0
    baro_altitude_m: float = 0.0
    cell_signature: Dict[str, float] = field(default_factory=dict)  # tower_id -> rssi
    wifi_signature: Dict[str, float] = field(default_factory=dict)  # bssid -> rssi

    def distance_to(self, other: "TerrainFingerprint") -> float:
        """Cross-modal distance in 'fingerprint space' (lower = more similar)."""
        d_mag = abs(self.mag_intensity_nt - other.mag_intensity_nt) / 100.0
        d_baro = abs(self.baro_pressure_hpa - other.baro_pressure_hpa) * 2.0
        # Cell: intersect common towers
        d_cell = 0.0
        common = set(self.cell_signature) & set(other.cell_signature)
        if common:
            d_cell = sum(abs(self.cell_signature[t] - other.cell_signature[t])
                         for t in common) / len(common)
        else:
            d_cell = 30.0  # large penalty if no overlap
        # Wifi: intersect common APs
        d_wifi = 0.0
        common_wifi = set(self.wifi_signature) & set(other.wifi_signature)
        if common_wifi:
            d_wifi = sum(abs(self.wifi_signature[b] - other.wifi_signature[b])
                         for b in common_wifi) / len(common_wifi)
        else:
            d_wifi = 15.0
        # Weighted combination (mag gets high weight — most discriminative)
        return d_mag * 1.0 + d_baro * 0.5 + d_cell * 5.0 + d_wifi * 3.0


class TerrainFingerprintMap:
    """Records and matches terrain fingerprints.

    Records a new fingerprint every `sample_interval_m` along
    a GPS-known trajectory. During GPS denial, matches the current
    reading against the map to return a position estimate.
    """

    def __init__(self, sample_interval_m: float = 10.0, max_samples: int = 5000):
        self._map: List[TerrainFingerprint] = []
        self._sample_interval_m = sample_interval_m
        self._max_samples = max_samples
        self._last_recorded: Optional[TerrainFingerprint] = None

    def record(self, fp: TerrainFingerprint) -> bool:
        """Record a new fingerprint if we've moved far enough."""
        if self._last_recorded is not None:
            d = self._haversine_m(
                self._last_recorded.lat, self._last_recorded.lon,
                fp.lat, fp.lon,
            )
            if d < self._sample_interval_m:
                return False
        self._map.append(fp)
        self._last_recorded = fp
        if len(self._map) > self._max_samples:
            self._map = self._map[-self._max_samples:]
        return True

    def match(self, query: TerrainFingerprint,
              top_k: int = 5) -> List[Tuple[TerrainFingerprint, float]]:
        """Find the best matching fingerprints in the map.

        Returns list of (fingerprint, distance) sorted by distance ascending.
        """
        if not self._map:
            return []
        scored = [(fp, query.distance_to(fp)) for fp in self._map]
        scored.sort(key=lambda x: x[1])
        return scored[:top_k]

    def estimate_position(self, query: TerrainFingerprint,
                          top_k: int = 5) -> Optional[Dict]:
        """Cross-correlate and return best position estimate."""
        matches = self.match(query, top_k)
        if not matches:
            return None
        # Weighted centroid of top-k (inverse-distance weighting)
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for fp, dist in matches:
            w = 1.0 / max(dist, 0.01)
            lat_sum += fp.lat * w
            lon_sum += fp.lon * w
            total_w += w
        lat = lat_sum / total_w
        lon = lon_sum / total_w
        best_dist = matches[0][1]
        # Confidence from match tightness
        confidence = 1.0 / (1.0 + best_dist)
        return {
            "lat": lat,
            "lon": lon,
            "confidence": confidence,
            "best_distance": best_dist,
            "matches": len(matches),
            "map_size": len(self._map),
        }

    @property
    def map_size(self) -> int:
        return len(self._map)

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2) -> float:
        R = 6_371_000.0
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
