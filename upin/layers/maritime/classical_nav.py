"""
Classical Maritime Navigation Layers — UPIN

Methods from the entire history of maritime navigation, from
Polynesian wayfinding to modern AIS. Each is a distinct positioning
technique that adds signal to the UPIN fusion engine.

HIGH PRIORITY for defence/maritime credibility (Captain Sinha domain).

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ═══════════════════════════════════════════════════════════════
# AIS — Automatic Identification System (maritime ADS-B equivalent)
# ═══════════════════════════════════════════════════════════════

class AISCooperativeLayer(NavigationLayer):
    """AIS — vessels broadcast position/identity on VHF.

    Receiving AIS from nearby vessels with known positions gives
    reference points for relative positioning. Like GPS but from ships.
    """

    def __init__(self):
        super().__init__(
            layer_id="ais_d09", layer_number=89,
            name="AIS Cooperative Maritime",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            is_underwater=False,
            description="AIS vessel broadcast — cooperative maritime positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 20 / 111_000),
                           longitude=base_lon + np.random.normal(0, 20 / 111_000),
                           accuracy_m=20.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.6,
                                raw_data={"vessels_in_range": 5, "protocol": "ITU-R M.1371"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class LighthouseSignatureLayer(NavigationLayer):
    """Lighthouse characteristic identification — unique flash patterns.

    Every lighthouse has a unique flash pattern (characteristic) recorded
    in light lists. Match observed pattern → identify lighthouse → bearing fix.
    """

    def __init__(self):
        super().__init__(
            layer_id="lighthouse_e16", layer_number=90,
            name="Lighthouse Signature ID",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            description="Lighthouse flash pattern matching from Light Lists",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.60

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 50 / 111_000),
                           longitude=base_lon + np.random.normal(0, 50 / 111_000),
                           accuracy_m=50.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.55,
                                raw_data={"lighthouses_matched": 2, "flash_pattern": "Fl(3)15s"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class BuoyRecognitionLayer(NavigationLayer):
    """IALA buoy/sea mark recognition — coded markings identify position.

    Lateral, cardinal, isolated danger, safe water, special marks.
    Vision-AI reads buoy colour/shape/topmark → chart match → position.
    """

    def __init__(self):
        super().__init__(
            layer_id="buoy_e17", layer_number=91,
            name="Buoy/Sea Mark Recognition (IALA)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION],
            description="IALA A/B buoy recognition — colour, shape, topmark matching",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 30 / 111_000),
                           longitude=base_lon + np.random.normal(0, 30 / 111_000),
                           accuracy_m=30.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.5,
                                raw_data={"buoys_detected": 3, "iala_system": "A"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class ThreePointFixLayer(NavigationLayer):
    """Three-point fix / cocked hat — three simultaneous bearings to landmarks.

    The classic mariner's fix. Three bearings to three known landmarks
    form a triangle (cocked hat). Your position is inside the triangle.
    """

    def __init__(self):
        super().__init__(
            layer_id="threefix_e18", layer_number=92,
            name="Three-Point Fix (Cocked Hat)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION],
            description="Three simultaneous bearing lines to known landmarks",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.70

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 15 / 111_000),
                           longitude=base_lon + np.random.normal(0, 15 / 111_000),
                           accuracy_m=15.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.7,
                                raw_data={"bearings": 3, "cocked_hat_area_m2": 225})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class CoastalPilotageLayer(NavigationLayer):
    """Coastal pilotage — visual identification of coastal features.

    Identify headlands, breakwaters, church spires, water towers
    against published nautical charts. Distinct from SLAM — this uses
    PUBLISHED feature descriptions, not self-built maps.
    """

    def __init__(self):
        super().__init__(
            layer_id="pilotage_e19", layer_number=93,
            name="Coastal Visual Pilotage",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            description="Visual feature matching against published nautical descriptions",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 25 / 111_000),
                           longitude=base_lon + np.random.normal(0, 25 / 111_000),
                           accuracy_m=25.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.6,
                                raw_data={"features_matched": 4, "chart_ref": "BA 1594"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class LeadingLightsLayer(NavigationLayer):
    """Range / leading lights (transit bearings) — two objects in line.

    Two fixed objects in line define a precise line of position.
    When the front and rear range markers align, you're on the line.
    """

    def __init__(self):
        super().__init__(
            layer_id="leadlight_e20", layer_number=94,
            name="Leading Lights / Transit Bearings",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.HEADING],
            description="Two objects in line = precise line of position",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 5 / 111_000),
                           longitude=base_lon + np.random.normal(0, 5 / 111_000),
                           accuracy_m=5.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                heading=45.0, self_confidence=0.75,
                                raw_data={"transit_bearing_deg": 45.0, "on_line": True})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class SextantAngleLayer(NavigationLayer):
    """Horizontal/Vertical Sextant Angles — circle of position from landmarks.

    HSA: angle between two charted landmarks → circle of position.
    VSA: vertical angle to landmark of known height → distance.
    Combined: precise fix from angular measurements alone.
    """

    def __init__(self):
        super().__init__(
            layer_id="sextant_e21", layer_number=95,
            name="Sextant Angle Fix (HSA/VSA)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION],
            description="Horizontal + vertical angles to charted landmarks",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.70

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 10 / 111_000),
                           longitude=base_lon + np.random.normal(0, 10 / 111_000),
                           accuracy_m=10.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.7,
                                raw_data={"hsa_deg": 32.5, "vsa_deg": 1.2, "circle_of_position": True})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class SeabedSampleLayer(NavigationLayer):
    """Sounding + bottom sample — depth + seabed composition matching.

    The tallowed lead brings up bottom sediment (sand/mud/shell/gravel/rock).
    Match depth + composition against seabed-composition charts.
    Distinct from bathymetric matching — this adds sediment type.
    """

    def __init__(self):
        super().__init__(
            layer_id="seabed_f05", layer_number=96,
            name="Seabed Sample Matching",
            group=LayerGroup.F_ACOUSTIC,
            capabilities=[LayerCapability.POSITION],
            is_underwater=True,
            description="Depth + seabed composition (sand/mud/rock) against charts",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.45

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 200 / 111_000),
                           longitude=base_lon + np.random.normal(0, 200 / 111_000),
                           accuracy_m=200.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.4,
                                raw_data={"depth_m": 45, "composition": "fine_sand_shell", "chart_match": True})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class LunarDistanceLayer(NavigationLayer):
    """Lunar distance method — pre-chronometer longitude from Moon-star angle.

    Measure angular distance between Moon and a star/Sun. Look up in
    Nautical Almanac. Gives Greenwich time → longitude from local noon.
    Historical (1760s Maskelyne) but still a valid electronic-free backup.
    """

    def __init__(self):
        super().__init__(
            layer_id="lunardist_a11", layer_number=97,
            name="Lunar Distance Longitude",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION],
            description="Longitude from Moon-star angular distance (Maskelyne 1760s)",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.30

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 500 / 111_000),
                           longitude=base_lon + np.random.normal(0, 500 / 111_000),
                           accuracy_m=500.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.25,
                                raw_data={"lunar_distance_deg": 45.3, "almanac_gmt": "14:32:15"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class MarineChronometerLayer(NavigationLayer):
    """Marine chronometer — longitude from precise Greenwich time.

    Harrison's H4 (1759). Carry accurate time, compare to local solar
    noon → time difference × 15°/hour = longitude. The method that
    solved the longitude problem. Still a valid backup.
    """

    def __init__(self):
        super().__init__(
            layer_id="chronometer_a12", layer_number=98,
            name="Marine Chronometer Longitude",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION],
            description="Longitude from precise timekeeping (Harrison 1759)",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.40

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat,
                           longitude=base_lon + np.random.normal(0, 100 / 111_000),
                           accuracy_m=100.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                self_confidence=0.35,
                                raw_data={"gmt_offset_s": 19380, "longitude_deg": base_lon})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class TidalStreamAtlasLayer(NavigationLayer):
    """Tidal stream atlas — predicted tidal currents from published tables.

    Distinct from ocean current (h_09): tidal streams are PREDICTED/PUBLISHED
    with hour-by-hour vectors. Used for dead reckoning correction.
    """

    def __init__(self):
        super().__init__(
            layer_id="tidalstream_h11", layer_number=99,
            name="Tidal Stream Atlas",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.VELOCITY],
            is_underwater=True,
            description="Published predicted tidal stream vectors for DR correction",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.50

    def read(self) -> LayerReading:
        if self._simulated:
            return LayerReading(layer_id=self.layer_id,
                                velocity=0.8, self_confidence=0.45,
                                raw_data={"stream_speed_kn": 1.5, "stream_dir_deg": 225,
                                          "hours_after_hw": 3, "source": "Admiralty TSD"})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon


class PolynesianWayfindingLayer(NavigationLayer):
    """Polynesian wayfinding — wave patterns, cloud reading, bird behaviour.

    The cognitive fusion model: read swell refraction around islands,
    lenticular clouds over peaks, green reflection over lagoons,
    seabird flight at dawn/dusk. AI can learn these patterns.
    """

    def __init__(self):
        super().__init__(
            layer_id="polynesian_e22", layer_number=100,
            name="Polynesian Wayfinding (Wave/Cloud/Bird)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Polynesian navigators — 3000 years of ocean wayfinding",
            description="Wave refraction + cloud patterns + bird behaviour for ocean nav",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.35

    def read(self) -> LayerReading:
        if self._simulated:
            base_lat = self.world.true_lat if self.world else getattr(self, "_sim_lat", 13.0827)
            base_lon = self.world.true_lon if self.world else getattr(self, "_sim_lon", 80.2707)
            pos = Position(latitude=base_lat + np.random.normal(0, 1000 / 111_000),
                           longitude=base_lon + np.random.normal(0, 1000 / 111_000),
                           accuracy_m=1000.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                heading=np.random.uniform(0, 360),
                                self_confidence=0.3,
                                raw_data={"swell_dir_deg": 210, "cloud_type": "lenticular",
                                          "birds_detected": 12, "land_bearing_est_deg": 315})
        raise NotImplementedError

    def set_simulated_position(self, lat, lon, alt=10.0):
        self._sim_lat, self._sim_lon = lat, lon
