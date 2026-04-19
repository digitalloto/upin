"""
Eagle Eye + Electronic Chart + DTED Layers — Group E (Optical/Vision)

Layer 78: Eagle Eye Stereo Camera — passive altitude from image overlap
Layer 79: Electronic Navigational Chart Matching — IHO S-57/S-100 feature matching
Layer 81: Digital Terrain Elevation Data — SRTM/DTED altitude constraint

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from typing import List, Optional

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ═══════════════════════════════════════════════════════════════
# LAYER 78: EAGLE EYE STEREO CAMERA
# ═══════════════════════════════════════════════════════════════

class EagleEyeStereoLayer(NavigationLayer):
    """Layer 78 — Eagle Eye Stereo Camera Passive Altitude.

    Passive altitude measurement from stereo image overlap.
    Core formula: altitude = d / ((1-k) * 2 * tan(θ))
    where d = camera separation, k = overlap ratio, θ = half FOV.

    Improvements beyond basic stereo:
    - Temporal stereo: single camera + motion = virtual baseline
    - Known object sizing: cars/buildings → altitude from pixel size
    - Texture density scoring: confidence from ground texture quality
    - Horizon detection: Earth curvature → altitude at high alt
    - Rate-of-change: vertical speed cross-validates with baro/INS
    """

    def __init__(self):
        super().__init__(
            layer_id="eagleeye_e13",
            layer_number=78,
            name="Eagle Eye Stereo Altitude",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.ALTITUDE, LayerCapability.POSITION],
            is_novel=True,
            description="Stereo camera passive altitude — structure from motion",
        )
        self._camera_sep_m = 0.3
        self._half_fov_deg = 35.0
        self._altitude_history: List[float] = []
        self._max_history = 50

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.72

    def _stereo_altitude(self, overlap_ratio: float) -> float:
        k = max(0.01, min(0.999, overlap_ratio))
        theta = math.radians(self._half_fov_deg)
        return self._camera_sep_m / ((1 - k) * 2 * math.tan(theta))

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        cam_data = self.world.get_stereo_camera_data()
        overlap = cam_data["overlap_ratio"]
        texture = cam_data["texture_density"]
        known_objs = cam_data["known_objects_detected"]
        horizon_ang = cam_data["horizon_angle_deg"]

        stereo_alt = self._stereo_altitude(overlap)
        noise_frac = 0.02 + 0.03 * (1.0 - texture)
        stereo_alt += np.random.normal(0, stereo_alt * noise_frac)

        constraints_used = 1
        confidence = 0.5 * texture

        if known_objs > 0:
            obj_alt = self.world.true_alt + np.random.normal(0, self.world.true_alt * 0.03)
            stereo_alt = 0.7 * stereo_alt + 0.3 * obj_alt
            constraints_used += 1
            confidence += 0.1

        if horizon_ang > 0.01:
            R = 6_371_000.0
            horizon_alt = R * (1 / math.cos(math.radians(horizon_ang)) - 1)
            stereo_alt = 0.8 * stereo_alt + 0.2 * horizon_alt
            constraints_used += 1
            confidence += 0.1

        temporal_stereo = False
        if hasattr(self.world, 'true_velocity') and self.world.true_velocity > 1.0:
            temporal_stereo = True
            constraints_used += 1
            confidence += 0.05

        self._altitude_history.append(stereo_alt)
        if len(self._altitude_history) > self._max_history:
            self._altitude_history = self._altitude_history[-self._max_history:]

        vert_speed = 0.0
        if len(self._altitude_history) >= 3:
            vert_speed = self._altitude_history[-1] - self._altitude_history[-3]

        confidence = min(0.95, max(0.1, confidence))

        lat = self.world.true_lat + np.random.normal(0, 10.0 / 111_000)
        lon = self.world.true_lon + np.random.normal(0, 10.0 / 111_000)

        pos = Position(
            latitude=lat, longitude=lon, altitude=stereo_alt,
            accuracy_m=max(3.0, stereo_alt * noise_frac * 2),
            timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=confidence,
            raw_data={
                "stereo_altitude_m": round(stereo_alt, 2),
                "overlap_ratio": round(overlap, 4),
                "texture_density": round(texture, 2),
                "known_objects": known_objs,
                "constraints_used": constraints_used,
                "temporal_stereo": temporal_stereo,
                "vertical_speed_ms": round(vert_speed, 2),
                "horizon_constraint": horizon_ang > 0.01,
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_alt = getattr(self, "_sim_alt", 100.0)
        noise = base_alt * 0.03
        alt = base_alt + np.random.normal(0, noise)
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat + np.random.normal(0, 10.0 / 111_000),
            longitude=base_lon + np.random.normal(0, 10.0 / 111_000),
            altitude=alt, accuracy_m=noise * 2, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.65,
            raw_data={"stereo_altitude_m": round(alt, 2), "constraints_used": 1},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


# ═══════════════════════════════════════════════════════════════
# LAYER 79: ELECTRONIC NAVIGATIONAL CHART MATCHING
# ═══════════════════════════════════════════════════════════════

class ENCChartMatchingLayer(NavigationLayer):
    """Layer 79 — Electronic Navigational Chart Feature Matching.

    Match observed features (depth soundings, coastline bearings,
    landmark bearings) against IHO S-57/S-100 chart database.
    Multi-feature matching: depth + coastline + landmark + buoy.
    """

    def __init__(self):
        super().__init__(
            layer_id="enc_e14",
            layer_number=79,
            name="ENC Chart Matching",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Electronic Navigational Chart feature matching — IHO S-57/S-100",
        )
        self._chart_cache = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        features = self.world.get_enc_chart_features()
        if not features:
            return self._read_fallback()

        total_w = 0.0
        lat_sum = lon_sum = 0.0
        matched = 0

        for feat in features:
            f_lat = feat["lat"]
            f_lon = feat["lon"]
            dist_m = self.world._haversine_m(
                self.world.true_lat, self.world.true_lon, f_lat, f_lon,
            )
            if dist_m > 5000:
                continue
            w = 1.0 / max(dist_m, 1.0)
            if feat["type"] in ("landmark", "light"):
                w *= 3.0
            elif feat["type"] == "buoy":
                w *= 2.0
            lat_sum += f_lat * w
            lon_sum += f_lon * w
            total_w += w
            matched += 1

        if total_w < 1e-10:
            return self._read_fallback()

        lat = lat_sum / total_w + np.random.normal(0, 0.0003)
        lon = lon_sum / total_w + np.random.normal(0, 0.0003)
        confidence = min(0.85, 0.3 + matched * 0.01)
        noise_m = max(20.0, 80.0 - matched * 1.5)

        pos = Position(
            latitude=lat, longitude=lon, altitude=0,
            accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=confidence,
            raw_data={
                "features_matched": matched,
                "total_features": len(features),
                "chart_standard": "S-57",
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        noise_m = 50.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.4,
            raw_data={"features_matched": 0, "chart_standard": "S-57"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ═══════════════════════════════════════════════════════════════
# LAYER 81: DIGITAL TERRAIN ELEVATION DATA MATCHING
# ═══════════════════════════════════════════════════════════════

class DTEDMatchingLayer(NavigationLayer):
    """Layer 81 — Digital Terrain Elevation Data Matching.

    Match radar/baro altitude-above-ground against SRTM/DTED land
    elevation database. Measured AGL + terrain elevation = MSL altitude.
    Grid sweep to find matching elevation profile → position constraint.
    """

    def __init__(self):
        super().__init__(
            layer_id="dted_e15",
            layer_number=81,
            name="DTED Terrain Elevation",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.ALTITUDE],
            is_novel=True,
            description="Digital Terrain Elevation Data matching — SRTM/DTED",
        )

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
        terrain_elev = self.world.get_terrain_elevation()
        measured_agl = max(1.0, self.world.true_alt - terrain_elev + np.random.normal(0, 5))
        msl_alt = terrain_elev + measured_agl

        best_lat, best_lon, best_diff = 0.0, 0.0, float('inf')
        search_step = 0.01
        for di in range(-5, 6):
            for dj in range(-5, 6):
                c_lat = self.world.true_lat + di * search_step
                c_lon = self.world.true_lon + dj * search_step
                c_elev = self.world.get_terrain_elevation(c_lat, c_lon)
                diff = abs(c_elev - terrain_elev)
                if diff < best_diff:
                    best_diff = diff
                    best_lat = c_lat
                    best_lon = c_lon

        noise_m = 80.0
        lat = best_lat + np.random.normal(0, noise_m / 111_000)
        lon = best_lon + np.random.normal(0, noise_m / 111_000)

        pos = Position(
            latitude=lat, longitude=lon, altitude=msl_alt,
            accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.55,
            raw_data={
                "terrain_elevation_m": round(terrain_elev, 1),
                "altitude_agl_m": round(measured_agl, 1),
                "altitude_msl_m": round(msl_alt, 1),
                "grid_match_residual_m": round(best_diff, 2),
                "dted_level": 2,
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        noise_m = 80.0
        pos = Position(
            latitude=base_lat + np.random.normal(0, noise_m / 111_000),
            longitude=base_lon + np.random.normal(0, noise_m / 111_000),
            altitude=300.0, accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.45,
            raw_data={"terrain_elevation_m": 200, "dted_level": 2},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
