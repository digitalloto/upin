"""
Group E — Optical and Vision Layers (9 layers).

Layer 4:  Star Tracking with Daytime Capability
Layer 5:  Terrain Matching Vision
Layer 25a: Atmospheric Polarised Sky Navigation [N]
Layer 25b: Underwater Polarised Light Navigation [N, U]
Layer 31: Visual SLAM Live Environment Mapping
Layer 32: Visual Odometry with IMU Fusion
Layer 33: LiDAR Enhanced Visual SLAM
Layer 38: Thermal Infrared Navigation and Detection [N]
Layer 39: Hyperspectral Polarised Vision [N, U]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ===================================================================
# Layer 4 — Star Tracking with Daytime Capability
# ===================================================================

class StarTrackingLayer(NavigationLayer):
    """Layer 4 — Star Tracking with Daytime Capability.

    Celestial body tracking upgraded with Sodern Astradia tech (France, 2025)
    which locks onto fixed stellar positions regardless of solar conditions.
    """

    def __init__(self):
        super().__init__(
            layer_id="startrack_l4",
            layer_number=4,
            name="Star Tracking (Daytime Capable)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.HEADING, LayerCapability.POSITION],
            description="Daytime star tracking — Astradia technology",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.8

    def _celestial_fix(self, stars):
        """Compute lat/lon from star altitude measurements.

        Latitude is approximated from the altitude of Polaris (within
        ~1 degree for mid-latitudes).  Longitude is derived from star
        hour angles (simplified to a small noise offset).
        """
        # Latitude ~ altitude of Polaris
        polaris = next(
            (s for s in stars if s.get("name") == "Polaris"), None,
        )
        if polaris is not None:
            lat = polaris["measured_altitude_deg"] + np.random.normal(0, 0.01)
        else:
            # Use average altitude of observed stars as rough latitude proxy
            if stars:
                lat = np.mean(
                    [s["measured_altitude_deg"] for s in stars],
                ) + np.random.normal(0, 0.05)
            else:
                lat = self.world.true_lat  # ultimate fallback
        # Longitude from star hour angles (simplified)
        lon = self.world.true_lon + np.random.normal(0, 0.0002)
        return lat, lon

    def read(self) -> LayerReading:
        noise_m = 20.0

        if self.world is not None:
            # --- Physics-based: celestial fix from star positions ---
            stars = self.world.get_star_positions()
            lat, lon = self._celestial_fix(stars)

            # Heading from star azimuth measurements
            heading_noise = 0.5  # degrees
            heading = (self.world.true_heading
                       + np.random.normal(0, heading_noise)) % 360

            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                heading=heading, accuracy_m=noise_m,
                timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=heading,
                self_confidence=0.85,
                raw_data={
                    "stars_tracked": len(stars),
                    "daytime": True,
                    "polaris_visible": any(
                        s.get("name") == "Polaris" for s in stars
                    ),
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            heading = getattr(self, "_sim_heading", 45.0)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                heading=heading + np.random.normal(0, 0.5),
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=(heading + np.random.normal(0, 0.5)) % 360,
                self_confidence=0.85,
                raw_data={"stars_tracked": 8, "daytime": True},
            )
        raise NotImplementedError("Live star tracker required")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_heading = 45.0


# ===================================================================
# Layer 5 — Terrain Matching Vision
# ===================================================================

class TerrainMatchingLayer(NavigationLayer):
    """Layer 5 — Terrain Matching Vision.

    Visual comparison of observed terrain against pre-loaded database.
    """

    def __init__(self):
        super().__init__(
            layer_id="terrain_l5",
            layer_number=5,
            name="Terrain Matching Vision",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION],
            description="Visual terrain feature matching",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def read(self) -> LayerReading:
        noise_m = 15.0

        if self.world is not None:
            # --- Physics-based: terrain feature matching ---
            features = self.world.get_terrain_features()
            if features:
                # Weighted centroid of matched terrain features
                total_w = 0.0
                lat_sum = lon_sum = 0.0
                for feat in features:
                    feat_lat = feat.get("lat", feat.get("latitude", 0))
                    feat_lon = feat.get("lon", feat.get("longitude", 0))
                    dist_m = self.world._haversine_m(
                        self.world.true_lat, self.world.true_lon,
                        feat_lat, feat_lon,
                    )
                    w = 1.0 / max(dist_m, 1.0)
                    lat_sum += feat_lat * w
                    lon_sum += feat_lon * w
                    total_w += w
                if total_w > 0:
                    lat = lat_sum / total_w + np.random.normal(0, 0.00005)
                    lon = lon_sum / total_w + np.random.normal(0, 0.00005)
                else:
                    lat = self.world.true_lat + np.random.normal(
                        0, noise_m / 111_000,
                    )
                    lon = self.world.true_lon + np.random.normal(
                        0, noise_m / 111_000,
                    )
                pos = Position(
                    latitude=lat, longitude=lon, altitude=0,
                    accuracy_m=noise_m, timestamp=time.time(),
                )
                return LayerReading(
                    layer_id=self.layer_id, position=pos,
                    self_confidence=0.75,
                    raw_data={
                        "features_matched": len(features),
                        "terrain_type": "urban",
                    },
                )
            # No terrain features available
            lat = self.world.true_lat + np.random.normal(0, noise_m * 3 / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m * 3 / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m * 3, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.3,
                raw_data={"features_matched": 0, "terrain_type": "unknown"},
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.75,
                raw_data={"features_matched": 120, "terrain_type": "urban"},
            )
        raise NotImplementedError("Live terrain matching requires camera + DB")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 25a — Atmospheric Polarised Sky Navigation
# ===================================================================

class PolarisedSkyLayer(NavigationLayer):
    """Layer 25a — Atmospheric Polarised Sky Navigation [NOVEL].

    Light polarisation pattern analysis for Sun azimuth and heading.
    Works through cloud cover. Inspired by honeybee polarised sky compass.
    """

    def __init__(self):
        super().__init__(
            layer_id="polsky_l25a",
            layer_number=25,
            name="Polarised Sky Navigation",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Honeybee polarised sky compass",
            description="Atmospheric polarisation heading — works through clouds",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def read(self) -> LayerReading:
        if self.world is not None:
            # --- Physics-based: heading from sky polarisation pattern ---
            # Sky polarisation pattern depends on Sun position relative to
            # observer.  The e-vector pattern gives a compass heading.
            heading_noise = 2.0  # degrees
            heading = (self.world.true_heading
                       + np.random.normal(0, heading_noise)) % 360
            cloud_cover = 0.1 + np.random.random() * 0.5
            return LayerReading(
                layer_id=self.layer_id, heading=heading,
                self_confidence=0.75,
                raw_data={
                    "polarisation_pattern": "clear",
                    "cloud_cover": cloud_cover,
                },
            )

        # --- Fallback ---
        if self._simulated:
            heading = getattr(self, "_sim_heading", 45.0)
            h = heading + np.random.normal(0, 2.0)
            return LayerReading(
                layer_id=self.layer_id, heading=h % 360,
                self_confidence=0.75,
                raw_data={"polarisation_pattern": "clear", "cloud_cover": 0.3},
            )
        raise NotImplementedError("Live polarised sky requires polarimeter")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0


# ===================================================================
# Layer 25b — Underwater Polarised Light Navigation
# ===================================================================

class UnderwaterPolarisedLayer(NavigationLayer):
    """Layer 25b — Underwater Polarised Light Navigation [NOVEL, UNDERWATER].

    Scattered polarised light creates underwater patterns for navigation.
    Inspired by mantis shrimp underwater polarisation sensing.
    """

    def __init__(self):
        super().__init__(
            layer_id="polwater_l25b",
            layer_number=25,
            name="Underwater Polarised Light Navigation",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Mantis shrimp polarisation sensing",
            description="Underwater polarised light navigation",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def read(self) -> LayerReading:
        if self.world is not None:
            # --- Physics-based: heading from underwater polarised light ---
            # Underwater light scattering produces polarisation patterns
            # that encode the Sun direction.  Noisier than atmospheric.
            heading_noise = 5.0  # degrees (underwater degradation)
            heading = (self.world.true_heading
                       + np.random.normal(0, heading_noise)) % 360
            depth = self.world.true_alt  # negative for underwater
            light_pen = max(0.0, 1.0 - abs(depth) / 200.0)
            return LayerReading(
                layer_id=self.layer_id, heading=heading,
                self_confidence=0.5,
                raw_data={
                    "depth_m": abs(depth) if depth < 0 else 50,
                    "light_penetration": light_pen if depth < 0 else 0.4,
                },
            )

        # --- Fallback ---
        if self._simulated:
            heading = getattr(self, "_sim_heading", 45.0)
            h = heading + np.random.normal(0, 5.0)
            return LayerReading(
                layer_id=self.layer_id, heading=h % 360,
                self_confidence=0.5,
                raw_data={"depth_m": 50, "light_penetration": 0.4},
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0


# ===================================================================
# Layer 31 — Visual SLAM Live Environment Mapping
# ===================================================================

class VisualSLAMLayer(NavigationLayer):
    """Layer 31 — Visual SLAM Live Environment Mapping.

    Simultaneous Localisation and Mapping from camera images.
    NVIDIA Isaac ROS: 250 fps pose estimation on embedded hardware.
    Works in complete GPS denial, underground, and underwater.
    """

    def __init__(self):
        super().__init__(
            layer_id="vslam_l31",
            layer_number=31,
            name="Visual SLAM",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            description="Visual SLAM — real-time environment mapping",
        )
        self._map_points: list = []
        self._slam_lat: float | None = None
        self._slam_lon: float | None = None
        self._slam_alt: float | None = None
        self._drift_lat = 0.0
        self._drift_lon = 0.0
        self._read_count = 0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._map_points = []
        self._slam_lat = None
        self._slam_lon = None
        self._slam_alt = None
        self._drift_lat = 0.0
        self._drift_lon = 0.0
        self._read_count = 0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.85

    def read(self) -> LayerReading:
        noise_m = 2.0

        if self.world is not None:
            # --- Physics-based: SLAM with drift + loop closure ---
            self._read_count += 1

            # Initialise SLAM origin on first read
            if self._slam_lat is None:
                self._slam_lat = self.world.true_lat
                self._slam_lon = self.world.true_lon
                self._slam_alt = self.world.true_alt

            # Observe features from world (terrain features as proxy)
            features = self.world.get_terrain_features()
            num_features = len(features) if features else 200

            # SLAM accumulates slow drift between loop closures
            drift_rate = 0.5e-6  # degrees per read (~0.05 m)
            self._drift_lat += np.random.normal(0, drift_rate)
            self._drift_lon += np.random.normal(0, drift_rate)

            # Periodic loop closure resets drift (every ~20 reads)
            loop_closures = 0
            if self._read_count % 20 == 0:
                self._drift_lat *= 0.1
                self._drift_lon *= 0.1
                loop_closures = 1

            # SLAM position = true position + accumulated drift + noise
            slam_noise = noise_m / 111_000
            lat = (self.world.true_lat + self._drift_lat
                   + np.random.normal(0, slam_noise))
            lon = (self.world.true_lon + self._drift_lon
                   + np.random.normal(0, slam_noise))
            alt = self.world.true_alt + np.random.normal(0, 0.5)

            heading = (self.world.true_heading
                       + np.random.normal(0, 0.3)) % 360

            pos = Position(
                latitude=lat, longitude=lon, altitude=alt,
                heading=heading, accuracy_m=noise_m,
                timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=heading,
                self_confidence=0.88,
                raw_data={
                    "map_points": num_features * 25,
                    "fps": 250,
                    "loop_closures": loop_closures,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            base_alt = getattr(self, "_sim_alt", 10.0)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 0.5)
            heading = (
                getattr(self, "_sim_heading", 45.0)
                + np.random.normal(0, 0.3)
            )
            pos = Position(
                latitude=lat, longitude=lon, altitude=alt,
                heading=heading % 360, accuracy_m=noise_m,
                timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=heading % 360,
                self_confidence=0.88,
                raw_data={"map_points": 5000, "fps": 250, "loop_closures": 3},
            )
        raise NotImplementedError("Live VSLAM requires camera")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt
        self._sim_heading = 45.0


# ===================================================================
# Layer 32 — Visual Odometry with IMU Fusion
# ===================================================================

class VisualOdometryLayer(NavigationLayer):
    """Layer 32 — Visual Odometry with IMU Fusion.

    Frame-by-frame visual tracking + IMU via EKF.
    Inspired by fly haltere gyroscope.
    """

    def __init__(self):
        super().__init__(
            layer_id="vio_l32",
            layer_number=32,
            name="Visual Odometry + IMU",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY],
            bio_inspiration="Fly haltere gyroscope",
            description="Visual-inertial odometry with loop closure",
        )
        self._vio_drift_lat = 0.0
        self._vio_drift_lon = 0.0
        self._read_count = 0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._vio_drift_lat = 0.0
        self._vio_drift_lon = 0.0
        self._read_count = 0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.8

    def read(self) -> LayerReading:
        noise_m = 3.0

        if self.world is not None:
            # --- Physics-based: visual-inertial odometry ---
            self._read_count += 1

            # VIO accumulates drift (slightly faster than SLAM)
            drift_rate = 1.0e-6  # degrees per read
            self._vio_drift_lat += np.random.normal(0, drift_rate)
            self._vio_drift_lon += np.random.normal(0, drift_rate)

            vio_noise = noise_m / 111_000
            lat = (self.world.true_lat + self._vio_drift_lat
                   + np.random.normal(0, vio_noise))
            lon = (self.world.true_lon + self._vio_drift_lon
                   + np.random.normal(0, vio_noise))

            # Velocity from frame-to-frame feature displacement + IMU
            velocity = self.world.true_velocity + np.random.normal(0, 0.3)

            # Feature count from terrain features as proxy
            features = self.world.get_terrain_features()
            feat_count = len(features) * 10 if features else 200

            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                velocity=max(0.0, velocity),
                self_confidence=0.8,
                raw_data={
                    "features_tracked": feat_count,
                    "imu_fused": True,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                velocity=getattr(self, "_sim_velocity", 10.0)
                + np.random.normal(0, 0.3),
                self_confidence=0.8,
                raw_data={"features_tracked": 200, "imu_fused": True},
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 33 — LiDAR Enhanced Visual SLAM
# ===================================================================

class LiDARSLAMLayer(NavigationLayer):
    """Layer 33 — LiDAR Enhanced Visual SLAM.

    Laser point cloud + visual texture for 3D mapping.
    Works in featureless environments where camera alone fails.
    """

    def __init__(self):
        super().__init__(
            layer_id="lidar_l33",
            layer_number=33,
            name="LiDAR Enhanced SLAM",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            description="LiDAR + visual SLAM 3D mapping",
        )
        self._lidar_drift_lat = 0.0
        self._lidar_drift_lon = 0.0
        self._read_count = 0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._lidar_drift_lat = 0.0
        self._lidar_drift_lon = 0.0
        self._read_count = 0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.9

    def read(self) -> LayerReading:
        noise_m = 0.5

        if self.world is not None:
            # --- Physics-based: LiDAR SLAM with point cloud matching ---
            self._read_count += 1

            # LiDAR SLAM has very low drift (point cloud is very precise)
            drift_rate = 0.1e-6  # degrees per read
            self._lidar_drift_lat += np.random.normal(0, drift_rate)
            self._lidar_drift_lon += np.random.normal(0, drift_rate)

            # Frequent loop closures from point cloud matching
            if self._read_count % 10 == 0:
                self._lidar_drift_lat *= 0.05
                self._lidar_drift_lon *= 0.05

            lidar_noise = noise_m / 111_000
            lat = (self.world.true_lat + self._lidar_drift_lat
                   + np.random.normal(0, lidar_noise))
            lon = (self.world.true_lon + self._lidar_drift_lon
                   + np.random.normal(0, lidar_noise))
            alt = self.world.true_alt + np.random.normal(0, 0.2)

            pos = Position(
                latitude=lat, longitude=lon, altitude=alt,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.92,
                raw_data={
                    "points_per_sec": 1_000_000,
                    "range_m": 200,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            base_alt = getattr(self, "_sim_alt", 10.0)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 0.2)
            pos = Position(
                latitude=lat, longitude=lon, altitude=alt,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.92,
                raw_data={"points_per_sec": 1_000_000, "range_m": 200},
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


# ===================================================================
# Layer 38 — Thermal Infrared Navigation
# ===================================================================

class ThermalIRLayer(NavigationLayer):
    """Layer 38 — Thermal Infrared Navigation [NOVEL].

    IR field mapping for navigation and warm-body detection.
    Inspired by pit viper thermal organs (0.003°C discrimination).
    """

    def __init__(self):
        super().__init__(
            layer_id="thermal_l38",
            layer_number=38,
            name="Thermal Infrared Navigation",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.ENVIRONMENT, LayerCapability.POSITION],
            is_novel=True,
            bio_inspiration="Pit viper thermal organs",
            description="Thermal IR navigation + warm-body detection",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        noise_m = 20.0

        if self.world is not None:
            # --- Physics-based: IR feature matching for position ---
            # Use terrain features as proxy for thermal landmarks
            features = self.world.get_terrain_features()
            if features:
                # Match IR signatures to known thermal features
                total_w = 0.0
                lat_sum = lon_sum = 0.0
                for feat in features:
                    feat_lat = feat.get("lat", feat.get("latitude", 0))
                    feat_lon = feat.get("lon", feat.get("longitude", 0))
                    dist_m = self.world._haversine_m(
                        self.world.true_lat, self.world.true_lon,
                        feat_lat, feat_lon,
                    )
                    # IR detection range is limited (~500 m effective)
                    if dist_m < 500:
                        w = 1.0 / max(dist_m, 1.0) ** 2
                        lat_sum += feat_lat * w
                        lon_sum += feat_lon * w
                        total_w += w
                if total_w > 0:
                    lat = lat_sum / total_w + np.random.normal(0, 0.0001)
                    lon = lon_sum / total_w + np.random.normal(0, 0.0001)
                else:
                    lat = self.world.true_lat + np.random.normal(
                        0, noise_m / 111_000,
                    )
                    lon = self.world.true_lon + np.random.normal(
                        0, noise_m / 111_000,
                    )
            else:
                lat = self.world.true_lat + np.random.normal(
                    0, noise_m / 111_000,
                )
                lon = self.world.true_lon + np.random.normal(
                    0, noise_m / 111_000,
                )

            # Thermal body detection
            body_count = np.random.randint(0, 8)

            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.6,
                raw_data={
                    "thermal_targets": len(features) if features else 5,
                    "resolution_c": 0.003,
                    "body_heat_signatures": body_count,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.6,
                raw_data={
                    "thermal_targets": 5,
                    "resolution_c": 0.003,
                    "body_heat_signatures": 3,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 39 — Hyperspectral Polarised Vision
# ===================================================================

class HyperspectralLayer(NavigationLayer):
    """Layer 39 — Hyperspectral Polarised Vision [NOVEL, UNDERWATER].

    12-16 wavelength band imaging including UV and near-IR.
    Inspired by mantis shrimp 16-photoreceptor vision.
    Enables camouflage detection and material identification.
    """

    def __init__(self):
        super().__init__(
            layer_id="hyperspec_l39",
            layer_number=39,
            name="Hyperspectral Polarised Vision",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Mantis shrimp 16-photoreceptor vision",
            description="12-16 band hyperspectral + camouflage detection",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self.world is not None:
            # --- Physics-based: environment-only hyperspectral sensing ---
            # No position output — environment classification only
            # Spectral analysis of terrain features for material ID
            features = self.world.get_terrain_features()
            material_classes = ["vegetation", "concrete", "metal"]
            if features and len(features) > 5:
                material_classes.append("water")
            camouflage = np.random.random() < 0.05  # rare detection
            uv_anomalies = np.random.randint(0, 3)
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.7,
                raw_data={
                    "bands": 16,
                    "camouflage_detected": camouflage,
                    "material_classes": material_classes,
                    "uv_anomalies": uv_anomalies,
                },
            )

        # --- Fallback ---
        if self._simulated:
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.7,
                raw_data={
                    "bands": 16,
                    "camouflage_detected": False,
                    "material_classes": ["vegetation", "concrete", "metal"],
                    "uv_anomalies": 0,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class MonarchSunCompassLayer(NavigationLayer):
    """Sun compass heading — inspired by Monarch butterfly migration.

    Monarchs use a time-compensated sun compass: they combine the sun's
    azimuth with an internal circadian clock to maintain a constant
    heading across 4000 km of migration.  This layer measures solar
    azimuth + time-of-day to derive true heading.
    """

    def __init__(self):
        super().__init__(
            layer_id="monarch_e10",
            layer_number=66,
            name="Monarch Sun Compass",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Monarch butterfly time-compensated sun compass",
            description="Solar azimuth + circadian clock heading estimation",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.50

    def read(self) -> LayerReading:
        import math as _math
        # Simulate sun azimuth based on time of day (simplified)
        hour = (time.time() % 86400) / 3600  # 0-24
        sun_azimuth = (hour - 6) * 15.0  # rough: 15 deg/hr from 6am
        sun_azimuth = sun_azimuth % 360.0

        if self.world is not None:
            true_heading = getattr(self.world, "true_heading", 45.0)
            noise = np.random.normal(0, 5.0)
            heading = (true_heading + noise) % 360.0
            return LayerReading(
                layer_id=self.layer_id, heading=heading,
                self_confidence=0.60,
                raw_data={"sun_azimuth": sun_azimuth, "hour_utc": hour, "heading_deg": heading},
            )

        if self._simulated:
            heading = (getattr(self, "_sim_heading", 45.0) + np.random.normal(0, 5.0)) % 360.0
            return LayerReading(
                layer_id=self.layer_id, heading=heading,
                self_confidence=0.60,
                raw_data={"sun_azimuth": sun_azimuth, "hour_utc": hour, "heading_deg": heading},
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0
