"""
Aviation Navigation Layers — UPIN

Civil and military aviation navigation infrastructure.
HIGH PRIORITY for IAF/DGCA credibility.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class ADSBCooperativeLayer(NavigationLayer):
    """ADS-B — aircraft broadcast position/velocity continuously.

    Receiving ADS-B from nearby aircraft gives cooperative reference
    points. Like AIS but for aviation.
    """

    def __init__(self):
        super().__init__(
            layer_id="adsb_d10", layer_number=101,
            name="ADS-B Cooperative Aviation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            description="ADS-B aircraft broadcast — cooperative aviation positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.70

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 10 / 111_000),
                           longitude=base_lon + np.random.normal(0, 10 / 111_000),
                           accuracy_m=10.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.65,
                                raw_data={"aircraft_in_range": 8, "protocol": "1090ES"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class TACANLayer(NavigationLayer):
    """TACAN — Tactical Air Navigation. Distance + bearing from beacon.

    Military UHF beacon providing slant range (DME) and bearing.
    Critical for IAF/defence deployments.
    """

    def __init__(self):
        super().__init__(
            layer_id="tacan_d11", layer_number=102,
            name="TACAN Tactical Air Navigation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            description="Military UHF distance + bearing beacon (DME/bearing)",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 15 / 111_000),
                           longitude=base_lon + np.random.normal(0, 15 / 111_000),
                           accuracy_m=15.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                heading=np.random.uniform(0, 360),
                                self_confidence=0.7,
                                raw_data={"slant_range_nm": 12.5, "bearing_deg": 270,
                                          "channel": "108X", "station": "MAA"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class VORDMELayer(NavigationLayer):
    """VOR/DME — civil VHF Omnidirectional Range + Distance Measuring Equipment.

    Rotating VHF pattern gives bearing; paired UHF transponder gives range.
    Core civil aviation navigation worldwide.
    """

    def __init__(self):
        super().__init__(
            layer_id="vordme_d12", layer_number=103,
            name="VOR/DME Civil Aviation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            description="VHF omnidirectional range + distance measuring equipment",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.70

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 20 / 111_000),
                           longitude=base_lon + np.random.normal(0, 20 / 111_000),
                           accuracy_m=20.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                heading=np.random.uniform(0, 360),
                                self_confidence=0.65,
                                raw_data={"radial_deg": 180, "dme_nm": 8.3,
                                          "station_id": "MAA", "frequency_mhz": 116.7})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class ILSLayer(NavigationLayer):
    """ILS — Instrument Landing System. Precision approach guidance.

    Localiser (lateral) + glideslope (vertical) beams guide aircraft
    to runway threshold. Categories I/II/III for visibility minimums.
    """

    def __init__(self):
        super().__init__(
            layer_id="ils_d13", layer_number=104,
            name="ILS Precision Approach",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ALTITUDE],
            description="Instrument Landing System — localiser + glideslope",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.90

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 2 / 111_000),
                           longitude=base_lon + np.random.normal(0, 2 / 111_000),
                           altitude=50.0, accuracy_m=2.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.9,
                                raw_data={"localiser_deviation_dots": 0.3,
                                          "glideslope_deviation_dots": -0.1,
                                          "category": "CAT_IIIA", "runway": "07"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class GAGANLayer(NavigationLayer):
    """GAGAN — GPS Aided GEO Augmented Navigation. Indian SBAS.

    India's sovereign satellite-based augmentation system.
    Broadcasts integrity + differential corrections over India.
    Critical for patriotism + technical credibility in Indian defence.
    """

    def __init__(self):
        super().__init__(
            layer_id="gagan_a13", layer_number=105,
            name="GAGAN Indian SBAS",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION],
            description="GPS Aided GEO Augmented Navigation — Indian sovereign SBAS",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.85

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 1.5 / 111_000),
                           longitude=base_lon + np.random.normal(0, 1.5 / 111_000),
                           accuracy_m=1.5, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.85,
                                raw_data={"correction_m": 0.8, "integrity": True,
                                          "prn": [127, 128], "coverage": "Indian_FIR"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class PseudoliteLayer(NavigationLayer):
    """Pseudolite — ground-based GPS-like transmitters.

    Synthetic GNSS constellation on the ground. Defence and remote-area
    use where satellite coverage is denied or insufficient.
    Conceptually aligned with GARUDA-as-anchor thinking.
    """

    def __init__(self):
        super().__init__(
            layer_id="pseudolite_d14", layer_number=106,
            name="Pseudolite Ground GNSS",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            is_novel=True,
            description="Ground-based GPS-like transmitters — synthetic GNSS",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.80

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 3 / 111_000),
                           longitude=base_lon + np.random.normal(0, 3 / 111_000),
                           accuracy_m=3.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.8,
                                raw_data={"pseudolites_visible": 4, "pdop": 1.8,
                                          "mode": "ground_constellation"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon
