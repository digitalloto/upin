"""
Classical Celestial Navigation Layers — UPIN

Historical celestial methods promoted to first-class layers for
patent specificity. Each is a distinct technique from generic celestial.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations
import time
import numpy as np
from upin.core.layer_base import NavigationLayer, LayerGroup, LayerCapability, LayerReading
from upin.core.position import Position

def _stub_read(self, noise_m, confidence, raw_data):
    if self.world is not None:
        lat = self.world.true_lat + np.random.normal(0, noise_m / 111_000)
        lon = self.world.true_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(layer_id=self.layer_id, position=pos,
                            self_confidence=confidence, raw_data=raw_data)
    if self._simulated:
        lat = getattr(self, "_sim_lat", 13.0827) + np.random.normal(0, noise_m / 111_000)
        lon = getattr(self, "_sim_lon", 80.2707) + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(layer_id=self.layer_id, position=pos,
                            self_confidence=confidence, raw_data=raw_data)
    raise NotImplementedError

class PolarisAltitudeLayer(NavigationLayer):
    """Polaris altitude → latitude directly. Simplest classical latitude method."""
    def __init__(self):
        super().__init__(layer_id="polaris_a15", layer_number=121, name="Polaris Altitude Latitude",
                         group=LayerGroup.A_SATELLITE_CELESTIAL, capabilities=[LayerCapability.POSITION],
                         description="Latitude from Polaris altitude — simplest celestial fix")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.50
    def read(self): return _stub_read(self, 50, 0.45, {"polaris_alt_deg": 13.1, "latitude_deg": 13.1})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class SolarNoonSightLayer(NavigationLayer):
    """Solar meridian altitude (noon sight) — latitude from sun at local noon."""
    def __init__(self):
        super().__init__(layer_id="noonsight_a16", layer_number=122, name="Solar Noon Sight Latitude",
                         group=LayerGroup.A_SATELLITE_CELESTIAL, capabilities=[LayerCapability.POSITION],
                         description="Latitude from sun altitude at local apparent noon")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.50
    def read(self): return _stub_read(self, 30, 0.45, {"sun_alt_deg": 76.5, "declination_deg": 23.1})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class SunAzimuthCompassLayer(NavigationLayer):
    """Sun compass — azimuth from sun bearing + accurate time."""
    def __init__(self):
        super().__init__(layer_id="sunazimuth_a17", layer_number=123, name="Sun Azimuth Compass",
                         group=LayerGroup.A_SATELLITE_CELESTIAL,
                         capabilities=[LayerCapability.HEADING],
                         description="True heading from sun bearing + time (azimuth compass)")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.55
    def read(self):
        if self._simulated:
            pos = Position(latitude=getattr(self, "_sim_lat", 13.0827),
                           longitude=getattr(self, "_sim_lon", 80.2707),
                           accuracy_m=50.0, timestamp=time.time())
            return LayerReading(layer_id=self.layer_id, position=pos,
                                heading=np.random.uniform(0, 360), self_confidence=0.5,
                                raw_data={"sun_bearing_deg": 180, "local_hour_angle": 0})
        raise NotImplementedError
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class PlanetSightingLayer(NavigationLayer):
    """Planet sightings — Venus, Mars, Jupiter, Saturn for celestial fixes."""
    def __init__(self):
        super().__init__(layer_id="planets_a18", layer_number=124, name="Planet Sighting Navigation",
                         group=LayerGroup.A_SATELLITE_CELESTIAL, capabilities=[LayerCapability.POSITION],
                         description="Position from Venus/Mars/Jupiter/Saturn altitude + azimuth")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.45
    def read(self): return _stub_read(self, 100, 0.4, {"planet": "Venus", "alt_deg": 35.2, "az_deg": 260})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class AtmosphericRefractionLayer(NavigationLayer):
    """Atmospheric refraction correction — systematic error in celestial sightings."""
    def __init__(self):
        super().__init__(layer_id="refraction_a19", layer_number=125, name="Atmospheric Refraction Correction",
                         group=LayerGroup.A_SATELLITE_CELESTIAL, capabilities=[LayerCapability.POSITION],
                         description="Atmospheric bending correction for celestial observations")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.55
    def read(self): return _stub_read(self, 20, 0.5, {"refraction_arcmin": 0.57, "temp_c": 25, "pressure_hpa": 1013})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class VisualHorizonLayer(NavigationLayer):
    """Visual horizon reference — bubble horizon, pendulum, liquid levels.

    For aircraft/submarines lacking natural horizon. Historical and current.
    """
    def __init__(self):
        super().__init__(layer_id="vhorizon_b11", layer_number=126, name="Visual Horizon Reference",
                         group=LayerGroup.B_INERTIAL_TIMING,
                         capabilities=[LayerCapability.ALTITUDE],
                         description="Artificial horizon (bubble/pendulum/liquid) for celestial sights")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.45
    def read(self): return _stub_read(self, 30, 0.4, {"horizon_type": "bubble", "correction_arcmin": 2.1})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon
