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
                self_confidence=0.5,
                raw_data={"field_nt": 45000 + np.random.normal(0, 100),
                          "inclination_deg": 30.0, "declination_deg": -1.5},
            )
        raise NotImplementedError("Live magnetic requires magnetometer")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


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
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            heading = getattr(self, '_sim_heading', 45.0)
            noise_m = 50.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           heading=heading + np.random.normal(0, 1.0),
                           accuracy_m=noise_m, timestamp=time.time())
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
        # Simulate magnetic intensity map across Indian subcontinent
        for lat_i in range(50, 400, 10):  # 5.0 to 40.0
            for lon_i in range(550, 1100, 10):  # 55.0 to 110.0
                lat = lat_i / 10.0
                lon = lon_i / 10.0
                # Simulate varying magnetic field
                intensity = (45000 + 100 * np.sin(lat * 0.1) +
                             80 * np.cos(lon * 0.15) +
                             np.random.normal(0, 10))
                self._magnetic_db[(lat_i, lon_i)] = intensity

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
            # Match against database with noise
            noise_m = 100.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.65,
                raw_data={"db_match_confidence": 0.8,
                          "intensity_nt": 45000, "inclination_deg": 30.0},
            )
        raise NotImplementedError("Live magnetic map matching requires magnetometer")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


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
        if self._simulated:
            heading = getattr(self, '_sim_heading', 45.0)
            velocity = getattr(self, '_sim_velocity', 10.0)
            h = heading + np.random.normal(0, 3.0)
            v = velocity + np.random.normal(0, 0.5)
            return LayerReading(
                layer_id=self.layer_id,
                heading=h % 360, velocity=max(0, v),
                self_confidence=0.65,
                raw_data={"induced_uv": 2.5, "zero_emissions": True},
            )
        raise NotImplementedError("Live EM induction requires sensor array")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0
        self._sim_velocity = 10.0


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
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 30.0  # Better than conventional magnetometer
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.78,
                raw_data={"sensitivity_pt": 10, "nv_centers": 1e12},
            )
        raise NotImplementedError("Live NV diamond requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


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
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            noise_m = 150.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(latitude=lat, longitude=lon, altitude=0,
                           accuracy_m=noise_m, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.55,
                raw_data={
                    "magnetic_nt": 45000, "salinity_psu": 35.0,
                    "temperature_c": 26.0, "dissolved_o2_mgl": 7.5,
                    "ph": 8.1,
                },
            )
        raise NotImplementedError("Live bicoordinate requires sensor suite")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
