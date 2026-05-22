"""
Historical & Specialist Radio Navigation Layers — UPIN

Legacy and specialised radio techniques that complete the UPIN
inventory for patent coverage and historical navigation literacy.

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

class OMEGALayer(NavigationLayer):
    """OMEGA VLF navigation (1971-1997). 8 stations, global coverage, ~2nm accuracy."""
    def __init__(self):
        super().__init__(layer_id="omega_d15", layer_number=107, name="OMEGA VLF Navigation",
                         group=LayerGroup.D_RF_TERRESTRIAL, capabilities=[LayerCapability.POSITION],
                         description="OMEGA VLF global positioning (1971-1997)")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.35
    def read(self): return _stub_read(self, 3700, 0.3, {"stations": 8, "frequency_khz": 10.2})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class DeccaNavigatorLayer(NavigationLayer):
    """Decca Navigator — phase-comparison radio (1946-2000). Maritime/aviation."""
    def __init__(self):
        super().__init__(layer_id="decca_d16", layer_number=108, name="Decca Navigator",
                         group=LayerGroup.D_RF_TERRESTRIAL, capabilities=[LayerCapability.POSITION],
                         description="Decca phase-comparison radio navigation (1946-2000)")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.45
    def read(self): return _stub_read(self, 500, 0.4, {"chain": "English_Channel", "lanes": 3})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class ConsolSonneLayer(NavigationLayer):
    """Consol/Sonne — German WWII rotating-beacon system."""
    def __init__(self):
        super().__init__(layer_id="consol_d17", layer_number=109, name="Consol/Sonne Beacon",
                         group=LayerGroup.D_RF_TERRESTRIAL, capabilities=[LayerCapability.POSITION],
                         description="WWII rotating-beacon radio navigation")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.30
    def read(self): return _stub_read(self, 5000, 0.25, {"dots": 30, "dashes": 30})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class RDFBearingLayer(NavigationLayer):
    """Radio Direction Finding — bearing-only on known transmitters."""
    def __init__(self):
        super().__init__(layer_id="rdf_d18", layer_number=110, name="Radio Direction Finding (RDF)",
                         group=LayerGroup.D_RF_TERRESTRIAL,
                         capabilities=[LayerCapability.HEADING, LayerCapability.POSITION],
                         description="Bearing-only fix from known radio transmitters")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.50
    def read(self): return _stub_read(self, 200, 0.45, {"bearings_taken": 3, "transmitters": ["NDB_MAA", "NDB_BLR"]})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class APRSLayer(NavigationLayer):
    """APRS — Amateur Packet Reporting System. Position via ham radio."""
    def __init__(self):
        super().__init__(layer_id="aprs_d19", layer_number=111, name="APRS Amateur Radio Position",
                         group=LayerGroup.D_RF_TERRESTRIAL, capabilities=[LayerCapability.POSITION],
                         description="Amateur packet radio position reporting (144.39 MHz)")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.40
    def read(self): return _stub_read(self, 100, 0.35, {"stations_heard": 4, "frequency_mhz": 144.39})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class DopplerBeaconLayer(NavigationLayer):
    """Doppler beacon localisation — Doppler shift on known-frequency beacon while moving."""
    def __init__(self):
        super().__init__(layer_id="dopbeacon_d20", layer_number=112, name="Doppler Beacon Localisation",
                         group=LayerGroup.D_RF_TERRESTRIAL, capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY],
                         description="Position from Doppler shift on known-frequency beacons (Transit-style)")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.55
    def read(self): return _stub_read(self, 100, 0.5, {"doppler_shift_hz": 12.3, "beacon_freq_mhz": 400})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon

class IridiumDopplerLayer(NavigationLayer):
    """Iridium/Globalstar LEO Doppler — position from LEO satellite Doppler shift."""
    def __init__(self):
        super().__init__(layer_id="iriddop_a14", layer_number=113, name="LEO Satellite Doppler (Iridium)",
                         group=LayerGroup.A_SATELLITE_CELESTIAL, capabilities=[LayerCapability.POSITION],
                         description="Position from Doppler shift of LEO satellite signals (Transit/Iridium)")
    def initialize(self): self.status.is_active = True; self.status.is_healthy = True; return True
    def get_accuracy_rating(self): return 0.55
    def read(self): return _stub_read(self, 50, 0.5, {"passes_used": 2, "constellation": "Iridium"})
    def set_simulated_position(self, lat, lon, alt=10.0): self._sim_lat, self._sim_lon = lat, lon
