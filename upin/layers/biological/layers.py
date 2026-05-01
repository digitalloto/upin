"""
Biological Predator-Prey Navigation Layers — UPIN Layers 64-68

Five new bio-inspired layers plus a biological consensus spoofing detector.
These integrate with the existing UPIN NavigationLayer architecture.

Layer 64: Wolf Pack Coordination — multi-unit tactical movement
Layer 65: Owl Silent Approach — noise-minimal stealth navigation
Layer 66: Salmon Magnetic+Chemical — combined magnetic/olfactory homing
Layer 67: Eagle Thermal Vision — high-acuity threat detection + SLAM
Layer 68: Predator-Prey Fusion — biological consensus for spoof detection

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ═══════════════════════════════════════════════════════════════
# LAYER 64: WOLF PACK COORDINATION
# ═══════════════════════════════════════════════════════════════

class WolfPackCoordinationLayer(NavigationLayer):
    """Wolf pack tactical coordination — multi-unit movement patterns.

    Wolves hunt in coordinated packs using:
    - Alpha leader provides primary direction
    - Beta scouts flank and report back
    - Pack maintains formation geometry
    - Encirclement pattern narrows position uncertainty

    Applied to UPIN: multiple units share position estimates,
    the geometric spread of the pack reduces position error
    faster than any single unit.
    """

    def __init__(self):
        super().__init__(
            layer_id="wolf_k06",
            layer_number=69,
            name="Wolf Pack Coordination",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            bio_inspiration="Wolf pack coordinated hunting geometry",
            description="Multi-unit geometric position refinement via pack coordination",
        )
        self._pack_size = 4
        self._formation_radius_m = 50.0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        noise_m = 15.0

        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
        elif self._simulated:
            true_lat = getattr(self, "_sim_lat", 13.0827)
            true_lon = getattr(self, "_sim_lon", 80.2707)
        else:
            raise NotImplementedError

        # Simulate pack members at formation positions
        pack_lats, pack_lons = [], []
        for i in range(self._pack_size):
            angle = 2 * math.pi * i / self._pack_size
            member_noise = noise_m / math.sqrt(self._pack_size)  # Pack reduces error
            lat = true_lat + np.random.normal(0, member_noise / 111320)
            lon = true_lon + np.random.normal(0, member_noise / 111320)
            pack_lats.append(lat)
            pack_lons.append(lon)

        # Pack centroid is more accurate than any single member
        est_lat = float(np.mean(pack_lats))
        est_lon = float(np.mean(pack_lons))
        accuracy = noise_m / math.sqrt(self._pack_size)

        pos = Position(latitude=est_lat, longitude=est_lon, accuracy_m=accuracy, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.70,
            raw_data={"pack_size": self._pack_size, "formation_radius_m": self._formation_radius_m,
                      "accuracy_improvement": f"{math.sqrt(self._pack_size):.1f}x from pack geometry"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ═══════════════════════════════════════════════════════════════
# LAYER 65: OWL SILENT APPROACH
# ═══════════════════════════════════════════════════════════════

class OwlSilentApproachLayer(NavigationLayer):
    """Owl silent approach — noise-minimal stealth navigation.

    Owls navigate in near-total silence using:
    - Asymmetric ears for 3D sound localisation
    - Facial disc focuses sound like a radar dish
    - Silent flight feathers eliminate self-noise
    - Passive-only sensing (zero emissions)

    Applied to UPIN: this layer uses ONLY passive sensors (no RF emissions)
    for covert operations. Combines passive acoustic + passive thermal +
    passive magnetic for zero-emission positioning.
    """

    def __init__(self):
        super().__init__(
            layer_id="owl_e11",
            layer_number=70,
            name="Owl Silent Approach",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Barn owl passive 3D sound localisation + silent flight",
            description="Zero-emission passive-only positioning for covert operations",
        )
        self._emission_mode = "PASSIVE_ONLY"

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.45  # Lower accuracy but zero emissions

    def read(self) -> LayerReading:
        noise_m = 25.0  # Passive sensors are less accurate

        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
        elif self._simulated:
            true_lat = getattr(self, "_sim_lat", 13.0827)
            true_lon = getattr(self, "_sim_lon", 80.2707)
        else:
            raise NotImplementedError

        # Passive acoustic bearing
        acoustic_bearing = np.random.uniform(0, 360)
        # Passive thermal detection
        thermal_offset = np.random.normal(0, noise_m / 111320)
        # Passive magnetic heading
        mag_heading = (np.random.normal(45, 3)) % 360

        lat = true_lat + np.random.normal(0, noise_m / 111320)
        lon = true_lon + np.random.normal(0, noise_m / 111320)

        pos = Position(latitude=lat, longitude=lon, accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos, heading=mag_heading,
            self_confidence=0.55,
            raw_data={"emission_mode": self._emission_mode,
                      "acoustic_bearing": round(acoustic_bearing, 1),
                      "sensors_used": ["passive_acoustic", "passive_thermal", "passive_magnetic"]},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ═══════════════════════════════════════════════════════════════
# LAYER 66: SALMON MAGNETIC + CHEMICAL HOMING
# ═══════════════════════════════════════════════════════════════

class SalmonHomingLayer(NavigationLayer):
    """Salmon magnetic + chemical homing — combined navigation.

    Salmon navigate thousands of kilometres using:
    - Magnetic map matching (intensity + inclination = bicoordinate)
    - Olfactory gradient following (chemical trail homing)
    - 60% magnetic weight + 40% chemical weight

    This combines both modalities into a single fused layer,
    unlike the separate magano_l6 and chemgrad_l26 layers.
    """

    def __init__(self):
        super().__init__(
            layer_id="salmon_h08",
            layer_number=71,
            name="Salmon Magnetic+Chemical Homing",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Salmon bicoordinate magnetic + olfactory homing",
            description="Combined magnetic map matching and chemical gradient following",
        )
        self._magnetic_weight = 0.6
        self._chemical_weight = 0.4
        self._declination_rad = 0.074  # Chennai

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.50

    def read(self) -> LayerReading:
        noise_m = 30.0

        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
        elif self._simulated:
            true_lat = getattr(self, "_sim_lat", 13.0827)
            true_lon = getattr(self, "_sim_lon", 80.2707)
        else:
            raise NotImplementedError

        # Magnetic component
        mag_field = np.array([23000, 5000, 39000]) + np.random.normal(0, 100, 3)
        mag_heading = math.degrees(math.atan2(mag_field[1], mag_field[0]) + self._declination_rad) % 360
        mag_noise = noise_m * (1 - self._magnetic_weight)

        # Chemical component
        temp = 28.5 + np.random.normal(0, 0.5)
        salinity = 35.0 + np.random.normal(0, 0.2)
        chem_gradient = np.array([(temp - 28) * 0.1, (salinity - 35) * 0.05])
        chem_noise = noise_m * (1 - self._chemical_weight)

        # Combined position estimate
        combined_noise = mag_noise * self._magnetic_weight + chem_noise * self._chemical_weight
        lat = true_lat + np.random.normal(0, combined_noise / 111320)
        lon = true_lon + np.random.normal(0, combined_noise / 111320)

        pos = Position(latitude=lat, longitude=lon, accuracy_m=combined_noise, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos, heading=mag_heading,
            self_confidence=0.60,
            raw_data={"magnetic_field_nt": mag_field.tolist(), "heading_deg": round(mag_heading, 1),
                      "temperature_c": round(temp, 1), "salinity_psu": round(salinity, 1),
                      "weights": {"magnetic": self._magnetic_weight, "chemical": self._chemical_weight}},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ═══════════════════════════════════════════════════════════════
# LAYER 67: EAGLE THERMAL VISION
# ═══════════════════════════════════════════════════════════════

class EagleThermalVisionLayer(NavigationLayer):
    """Eagle thermal vision — high-acuity threat detection + visual SLAM.

    Eagles have 8x human visual acuity plus UV sensitivity.
    This layer combines:
    - High-resolution visual feature tracking (SLAM)
    - Thermal signature detection for threats
    - Altitude-dependent resolution scaling
    """

    def __init__(self, rfdetr_extractor=None):
        super().__init__(
            layer_id="eagle_e12",
            layer_number=72,
            name="Eagle Thermal Vision",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.THREAT_DETECT],
            is_novel=True,
            bio_inspiration="Eagle 8x visual acuity + thermal detection",
            description="High-acuity visual SLAM with integrated threat detection",
        )
        self._visual_acuity = 8.0
        self._altitude_m = 100.0
        self._threats_detected: List[Dict] = []
        # RF-DETR: planned default feature extractor for threat detection
        self._rfdetr = rfdetr_extractor

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def read(self) -> LayerReading:
        noise_m = 5.0 / self._visual_acuity * (self._altitude_m / 100.0)

        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
        elif self._simulated:
            true_lat = getattr(self, "_sim_lat", 13.0827)
            true_lon = getattr(self, "_sim_lon", 80.2707)
        else:
            raise NotImplementedError

        lat = true_lat + np.random.normal(0, noise_m / 111320)
        lon = true_lon + np.random.normal(0, noise_m / 111320)

        # Simulate threat detection
        self._threats_detected = []
        num_sigs = np.random.choice([0, 0, 0, 1, 2], p=[0.5, 0.2, 0.15, 0.1, 0.05])
        for i in range(num_sigs):
            strength = np.random.randint(180, 280)
            ttype = "vehicle" if strength > 250 else "personnel" if strength > 220 else "equipment"
            self._threats_detected.append({
                "type": ttype, "strength": int(strength),
                "range_m": round(np.random.uniform(50, 500)),
                "threat_level": "HIGH" if strength > 250 else "MEDIUM" if strength > 220 else "LOW",
            })

        conf = min(0.95, 0.5 + 0.3 * (1.0 / max(noise_m, 0.1)) + 0.1 * min(1, self._visual_acuity / 8))

        pos = Position(latitude=lat, longitude=lon, accuracy_m=max(1, noise_m), timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=conf,
            raw_data={"visual_acuity": self._visual_acuity, "altitude_m": self._altitude_m,
                      "threats": self._threats_detected, "threat_count": len(self._threats_detected)},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._altitude_m = alt


# ═══════════════════════════════════════════════════════════════
# BIOLOGICAL CONSENSUS SPOOFING DETECTOR
# ═══════════════════════════════════════════════════════════════

class BiologicalConsensusSpoofDetector:
    """
    Uses consensus across ALL biological navigation layers to detect
    GPS spoofing. If GPS disagrees with the biological majority,
    GPS is likely spoofed.

    This is the key insight: biological navigation methods cannot be
    spoofed because they use physics that an attacker cannot fake
    (magnetic fields, chemical gradients, acoustic returns, etc.).
    """

    def __init__(self):
        self._history: List[Dict] = []

    def check_spoofing(
        self,
        gps_lat: float, gps_lon: float,
        bio_readings: List[LayerReading],
        threshold_m: float = 500.0,
    ) -> Dict:
        """Compare GPS against biological consensus."""
        if not bio_readings:
            return {"spoofing_detected": False, "confidence": 0.0, "reason": "no_bio_readings"}

        # Collect biological positions
        bio_lats, bio_lons, bio_weights = [], [], []
        for r in bio_readings:
            if r.position and r.self_confidence > 0.2:
                bio_lats.append(r.position.latitude)
                bio_lons.append(r.position.longitude)
                bio_weights.append(r.self_confidence)

        if len(bio_lats) < 2:
            return {"spoofing_detected": False, "confidence": 0.0, "reason": "insufficient_bio_data"}

        # Weighted biological consensus
        weights = np.array(bio_weights)
        weights /= weights.sum()
        consensus_lat = float(np.average(bio_lats, weights=weights))
        consensus_lon = float(np.average(bio_lons, weights=weights))

        # Distance from GPS to biological consensus
        dlat = (gps_lat - consensus_lat) * 111320
        dlon = (gps_lon - consensus_lon) * 111320 * math.cos(math.radians(consensus_lat))
        distance_m = math.sqrt(dlat ** 2 + dlon ** 2)

        # Biological internal agreement
        bio_spread = float(np.std(bio_lats) * 111320 + np.std(bio_lons) * 111320)

        # Spoofing if GPS far from consensus AND bio layers agree with each other
        spoofed = distance_m > threshold_m and bio_spread < threshold_m * 0.5
        conf = min(0.95, distance_m / (threshold_m * 2)) if spoofed else 0.0

        result = {
            "spoofing_detected": spoofed,
            "confidence": round(conf, 3),
            "gps_to_bio_distance_m": round(distance_m, 1),
            "bio_internal_spread_m": round(bio_spread, 1),
            "bio_layers_used": len(bio_lats),
            "consensus_lat": round(consensus_lat, 6),
            "consensus_lon": round(consensus_lon, 6),
            "threshold_m": threshold_m,
        }
        self._history.append(result)
        return result

    def get_history(self) -> List[Dict]:
        return list(self._history)
