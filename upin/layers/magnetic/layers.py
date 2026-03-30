"""
Group C — Magnetic and Quantum Layers (6 layers).

Layer 6:  Magnetic Anomaly Navigation
Layer 17: Dual Mechanism Quantum Magnetometer [N, U]
Layer 23: Magnetic Signature Map Matching [N, U]
Layer 24: Electromagnetic Induction Navigation [N, U]
Layer 30: Nitrogen-Vacancy Diamond Magnetometer [N, U]
Layer 44: Bicoordinate Geo-Chemical-Magnetic Positioning [N, U]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ---------------------------------------------------------------------------
# Shared helper — magnetic map matching algorithm
# ---------------------------------------------------------------------------

def _magnetic_map_match(world, sensor_noise_nt: float):
    """Compute position by matching measured field against known grid.

    Parameters
    ----------
    world : SimulationWorld
        Provides ``get_magnetic_field()`` and ``magnetic_field_at_grid()``.
    sensor_noise_nt : float
        1-sigma sensor noise in nanotesla added to the measurement.

    Returns
    -------
    tuple[float, float, float, dict]
        (lat, lon, best_diff, measured_field_dict)
    """
    # 1. Measure magnetic field at current position (with sensor noise)
    measured = world.get_magnetic_field(world.true_lat, world.true_lon)
    measured_intensity = measured["intensity_nt"] + np.random.normal(0, sensor_noise_nt)

    # 2. Get grid of known magnetic field values
    grid = world.magnetic_field_at_grid()

    # 3. Find best match (minimum difference)
    best_lat, best_lon, best_diff = 0.0, 0.0, float("inf")
    for (lat_i, lon_i), intensity in grid.items():
        diff = abs(intensity - measured_intensity)
        if diff < best_diff:
            best_diff = diff
            best_lat = lat_i / 100.0
            best_lon = lon_i / 100.0

    return best_lat, best_lon, best_diff, measured


# ===================================================================
# Layer 6 — Magnetic Anomaly Navigation
# ===================================================================

class MagneticAnomalyLayer(NavigationLayer):
    """Layer 6 — Magnetic Anomaly Navigation.

    Geomagnetic field variation mapping for position determination.
    Earth's magnetic field has measurable spatial variations that
    create a unique magnetic fingerprint at each location.
    """

    def __init__(self):
        super().__init__(
            layer_id="magano_l6",
            layer_number=6,
            name="Magnetic Anomaly Navigation",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            description="Geomagnetic field variation position matching",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def read(self) -> LayerReading:
        noise_m = 200.0
        sensor_noise_nt = 100.0

        if self.world is not None:
            # --- Physics-based: magnetic map matching ---
            lat, lon, best_diff, measured = _magnetic_map_match(
                self.world, sensor_noise_nt,
            )
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.5,
                raw_data={
                    "field_nt": measured["intensity_nt"],
                    "inclination_deg": measured["inclination_deg"],
                    "declination_deg": measured["declination_deg"],
                    "grid_match_diff_nt": best_diff,
                },
            )

        # --- Fallback: old sim_lat/sim_lon + noise approach ---
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
                self_confidence=0.5,
                raw_data={
                    "field_nt": 45000 + np.random.normal(0, 100),
                    "inclination_deg": 30.0,
                    "declination_deg": -1.5,
                },
            )
        raise NotImplementedError("Live magnetic requires magnetometer")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 17 — Dual Mechanism Quantum Magnetometer
# ===================================================================

class DualQuantumMagnetometerLayer(NavigationLayer):
    """Layer 17 — Dual Mechanism Quantum Magnetometer [NOVEL, UNDERWATER].

    Combines two independent mechanisms:
    1. Quantum radical pair effect (cryptochrome proteins in bird retinas)
    2. Magnetite crystal alignment (magnetite in pigeon beaks)
    Two physically independent mechanisms in one layer = internal redundancy.
    """

    def __init__(self):
        super().__init__(
            layer_id="dualqmag_l17",
            layer_number=17,
            name="Dual Mechanism Quantum Magnetometer",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.HEADING, LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Bird cryptochrome + pigeon magnetite",
            description="Dual quantum magnetic sensing — radical pair + magnetite",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.8

    def read(self) -> LayerReading:
        noise_m = 50.0
        radical_noise_nt = 50.0
        magnetite_noise_nt = 70.0

        if self.world is not None:
            # --- Physics-based: dual mechanism ---
            measured = self.world.get_magnetic_field(
                self.world.true_lat, self.world.true_lon,
            )
            # Radical-pair mechanism
            radical_intensity = measured["intensity_nt"] + np.random.normal(
                0, radical_noise_nt,
            )
            # Magnetite mechanism
            magnetite_intensity = measured["intensity_nt"] + np.random.normal(
                0, magnetite_noise_nt,
            )
            mechanisms_agree = abs(radical_intensity - magnetite_intensity) < 200.0

            # Fused measurement (weighted average — radical pair is more precise)
            fused_intensity = 0.6 * radical_intensity + 0.4 * magnetite_intensity

            # Map-match using fused intensity
            grid = self.world.magnetic_field_at_grid()
            best_lat, best_lon, best_diff = 0.0, 0.0, float("inf")
            for (lat_i, lon_i), intensity in grid.items():
                diff = abs(intensity - fused_intensity)
                if diff < best_diff:
                    best_diff = diff
                    best_lat = lat_i / 100.0
                    best_lon = lon_i / 100.0

            # Heading from declination
            heading = (self.world.true_heading
                       + measured["declination_deg"]
                       + np.random.normal(0, 1.0)) % 360

            pos = Position(
                latitude=best_lat, longitude=best_lon, altitude=0,
                heading=heading, accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=heading,
                self_confidence=0.8,
                raw_data={
                    "radical_pair_field_nt": radical_intensity,
                    "magnetite_field_nt": magnetite_intensity,
                    "mechanisms_agree": mechanisms_agree,
                    "grid_match_diff_nt": best_diff,
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
                heading=heading + np.random.normal(0, 1.0),
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=(heading + np.random.normal(0, 1.0)) % 360,
                self_confidence=0.8,
                raw_data={
                    "radical_pair_field_nt": 45000,
                    "magnetite_field_nt": 44980,
                    "mechanisms_agree": True,
                },
            )
        raise NotImplementedError("Live dual magnetometer requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_heading = 45.0


# ===================================================================
# Layer 23 — Magnetic Signature Map Matching
# ===================================================================

class MagneticMapMatchingLayer(NavigationLayer):
    """Layer 23 — Magnetic Signature Map Matching [NOVEL, UNDERWATER].

    Pre-loaded high-resolution magnetic signature database of India.
    Quantum magnetometer readings matched against stored signatures.
    Inspired by sea turtle bicoordinate magnetic navigation.
    """

    def __init__(self):
        super().__init__(
            layer_id="magmap_l23",
            layer_number=23,
            name="Magnetic Signature Map Matching",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Sea turtle bicoordinate magnetic navigation",
            description="Position from magnetic signature database matching",
        )
        self._magnetic_db: dict[tuple[int, int], float] = {}
        self._load_simulated_db()

    def _load_simulated_db(self):
        """Load simulated magnetic signature database for India."""
        for lat_i in range(50, 400, 10):  # 5.0 to 40.0
            for lon_i in range(550, 1100, 10):  # 55.0 to 110.0
                lat = lat_i / 10.0
                lon = lon_i / 10.0
                intensity = (45000 + 100 * np.sin(lat * 0.1)
                             + 80 * np.cos(lon * 0.15)
                             + np.random.normal(0, 10))
                self._magnetic_db[(lat_i, lon_i)] = intensity

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        noise_m = 100.0
        sensor_noise_nt = 50.0  # Better sensor than Layer 6

        if self.world is not None:
            # --- Physics-based: high-res magnetic map matching ---
            # Measure at true position
            measured = self.world.get_magnetic_field(
                self.world.true_lat, self.world.true_lon,
            )
            measured_intensity = measured["intensity_nt"] + np.random.normal(
                0, sensor_noise_nt,
            )
            measured_inclination = measured["inclination_deg"] + np.random.normal(
                0, 0.5,
            )

            # Match against SimulationWorld grid (primary)
            grid = self.world.magnetic_field_at_grid()
            best_lat, best_lon, best_diff = 0.0, 0.0, float("inf")
            for (lat_i, lon_i), intensity in grid.items():
                diff = abs(intensity - measured_intensity)
                if diff < best_diff:
                    best_diff = diff
                    best_lat = lat_i / 100.0
                    best_lon = lon_i / 100.0

            db_match_confidence = max(0.0, 1.0 - best_diff / 500.0)

            pos = Position(
                latitude=best_lat, longitude=best_lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.65,
                raw_data={
                    "db_match_confidence": db_match_confidence,
                    "intensity_nt": measured_intensity,
                    "inclination_deg": measured_inclination,
                    "grid_match_diff_nt": best_diff,
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
                self_confidence=0.65,
                raw_data={
                    "db_match_confidence": 0.8,
                    "intensity_nt": 45000,
                    "inclination_deg": 30.0,
                },
            )
        raise NotImplementedError("Live magnetic map matching requires magnetometer")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 24 — Electromagnetic Induction Navigation
# ===================================================================

class EMInductionLayer(NavigationLayer):
    """Layer 24 — Electromagnetic Induction Navigation [NOVEL, UNDERWATER].

    Platform moving through Earth's magnetic field generates electrical
    currents (Faraday induction). Measuring these provides heading and
    velocity with zero emissions. Inspired by shark ampullae of Lorenzini.
    """

    def __init__(self):
        super().__init__(
            layer_id="eminduct_l24",
            layer_number=24,
            name="Electromagnetic Induction Navigation",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.HEADING, LayerCapability.VELOCITY],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Shark ampullae of Lorenzini electroreception",
            description="Faraday induction heading/velocity — zero emissions",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self.world is not None:
            # --- Physics-based: Faraday induction from Earth's field ---
            measured = self.world.get_magnetic_field(
                self.world.true_lat, self.world.true_lon,
            )
            # Heading derived from field declination + platform heading
            heading_noise = 3.0  # degrees
            heading = (self.world.true_heading
                       + measured["declination_deg"]
                       + np.random.normal(0, heading_noise)) % 360

            # Velocity from induced EMF magnitude: EMF = B * L * v * sin(theta)
            # theta is angle between velocity vector and field lines
            field_t = measured["intensity_nt"] * 1e-9  # convert to Tesla
            effective_length_m = 1.0  # sensor baseline
            inclination_rad = np.radians(measured["inclination_deg"])
            velocity_true = self.world.true_velocity
            induced_v = field_t * effective_length_m * velocity_true * np.cos(
                inclination_rad,
            )
            # Recover velocity from induced voltage (with noise)
            induced_v_noisy = induced_v + np.random.normal(0, 1e-8)
            denom = field_t * effective_length_m * np.cos(inclination_rad)
            if abs(denom) > 1e-15:
                velocity = abs(induced_v_noisy / denom)
            else:
                velocity = velocity_true + np.random.normal(0, 0.5)

            return LayerReading(
                layer_id=self.layer_id,
                heading=heading,
                velocity=max(0.0, velocity),
                self_confidence=0.65,
                raw_data={
                    "induced_uv": induced_v * 1e6,
                    "zero_emissions": True,
                    "field_intensity_nt": measured["intensity_nt"],
                },
            )

        # --- Fallback ---
        if self._simulated:
            heading = getattr(self, "_sim_heading", 45.0)
            velocity = getattr(self, "_sim_velocity", 10.0)
            h = heading + np.random.normal(0, 3.0)
            v = velocity + np.random.normal(0, 0.5)
            return LayerReading(
                layer_id=self.layer_id,
                heading=h % 360,
                velocity=max(0, v),
                self_confidence=0.65,
                raw_data={"induced_uv": 2.5, "zero_emissions": True},
            )
        raise NotImplementedError("Live EM induction requires sensor array")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0
        self._sim_velocity = 10.0


# ===================================================================
# Layer 30 — Nitrogen-Vacancy Diamond Magnetometer
# ===================================================================

class NVDiamondMagnetometerLayer(NavigationLayer):
    """Layer 30 — Nitrogen-Vacancy Diamond Magnetometer [NOVEL, UNDERWATER].

    Carbon crystal with NV defects — exquisitely sensitive to magnetic
    fields. Orders of magnitude more sensitive than conventional
    magnetometers. Enables high-range magnetic map matching.
    """

    def __init__(self):
        super().__init__(
            layer_id="nvdiamond_l30",
            layer_number=30,
            name="NV Diamond Magnetometer",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            description="Nitrogen-vacancy diamond quantum magnetic sensor",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def read(self) -> LayerReading:
        noise_m = 30.0
        sensor_noise_nt = 10.0  # Ultra-sensitive — ~10 pT class

        if self.world is not None:
            # --- Physics-based: best-in-class magnetic map matching ---
            lat, lon, best_diff, measured = _magnetic_map_match(
                self.world, sensor_noise_nt,
            )
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.78,
                raw_data={
                    "sensitivity_pt": 10,
                    "nv_centers": 1e12,
                    "field_nt": measured["intensity_nt"],
                    "grid_match_diff_nt": best_diff,
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
                self_confidence=0.78,
                raw_data={"sensitivity_pt": 10, "nv_centers": 1e12},
            )
        raise NotImplementedError("Live NV diamond requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 44 — Bicoordinate Geo-Chemical-Magnetic Positioning
# ===================================================================

class BiocoordinateGeoChemMagLayer(NavigationLayer):
    """Layer 44 — Bicoordinate Geo-Chemical-Magnetic Positioning [NOVEL, U].

    Fuses magnetic field + ocean chemical gradients for bicoordinate fix.
    Inspired by the spiny lobster — first animal to perform true navigation
    using only magnetic field + chemical gradients simultaneously.
    """

    def __init__(self):
        super().__init__(
            layer_id="bicoord_l44",
            layer_number=44,
            name="Bicoordinate Geo-Chemical-Magnetic",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Spiny lobster bicoordinate navigation",
            description="Fused magnetic + chemical gradient positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def read(self) -> LayerReading:
        noise_m = 150.0
        sensor_noise_nt = 120.0  # Coarser biological-style sensor

        if self.world is not None:
            # --- Physics-based: magnetic map match + chemical gradient ---
            mag_lat, mag_lon, best_diff, measured = _magnetic_map_match(
                self.world, sensor_noise_nt,
            )

            # Simulated chemical gradient provides a latitude-correlated signal
            # (salinity, temperature, dissolved O2 vary with latitude in ocean)
            chem_lat_offset = np.random.normal(0, 0.001)  # chemical gradient noise
            chem_lon_offset = np.random.normal(0, 0.001)

            # Fuse magnetic position with chemical correction
            fused_lat = mag_lat + chem_lat_offset
            fused_lon = mag_lon + chem_lon_offset

            # Simulated chemical readings at true position
            salinity = 35.0 + 0.5 * np.sin(self.world.true_lat * 0.3)
            temperature = 26.0 - 0.3 * (self.world.true_lat - 13.0)
            dissolved_o2 = 7.5 + np.random.normal(0, 0.2)

            pos = Position(
                latitude=fused_lat, longitude=fused_lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.55,
                raw_data={
                    "magnetic_nt": measured["intensity_nt"],
                    "salinity_psu": salinity,
                    "temperature_c": temperature,
                    "dissolved_o2_mgl": dissolved_o2,
                    "ph": 8.1 + np.random.normal(0, 0.05),
                    "grid_match_diff_nt": best_diff,
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
                self_confidence=0.55,
                raw_data={
                    "magnetic_nt": 45000,
                    "salinity_psu": 35.0,
                    "temperature_c": 26.0,
                    "dissolved_o2_mgl": 7.5,
                    "ph": 8.1,
                },
            )
        raise NotImplementedError("Live bicoordinate requires sensor suite")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class ElectricFieldSensingLayer(NavigationLayer):
    """Electric field gradient sensing — inspired by electric eel electrolocation.

    Detects ambient electric field distortions caused by geological structures,
    power lines, and subsurface conductivity variations.
    Bio-inspired by Electrophorus electricus passive electrolocation.
    """

    def __init__(self):
        super().__init__(
            layer_id="efield_c07",
            layer_number=65,
            name="Electric Field Gradient Sensing",
            group=LayerGroup.C_MAGNETIC_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            bio_inspiration="Electric eel passive electrolocation",
            description="Ambient electric field gradient navigation",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.35

    def read(self) -> LayerReading:
        noise_m = 40.0
        if self.world is not None:
            lat = self.world.true_lat + np.random.normal(0, noise_m / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0, accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos, self_confidence=0.45,
                raw_data={"field_mv_m": 50 + np.random.normal(0, 5), "gradient_deg": np.random.uniform(0, 360)})
        if self._simulated:
            lat = getattr(self, "_sim_lat", 13.0827) + np.random.normal(0, noise_m / 111_000)
            lon = getattr(self, "_sim_lon", 80.2707) + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0, accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos, self_confidence=0.45,
                raw_data={"field_mv_m": 50.0, "gradient_deg": 180.0})
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
