"""
Hardware Threat Detection Layers T1-T8.

These layers repurpose the same navigation sensors for threat detection,
adding zero hardware weight. The same magnetometer that provides
navigation also detects submarines. The same sonar mapping obstacles
also identifies torpedo launches.

T1: RF Threat Localisation
T2: Acoustic Threat Signatures
T3: Magnetic Anomaly Threat Detection
T4: Subsurface Structure Detection
T5: Visual Object Recognition
T6: Thermal Threat Detection
T7: Seismic Threat Detection
T8: Hydrodynamic Trail Tracking
"""

from __future__ import annotations

import time
from typing import Optional, Any

import numpy as np

from upin.core.layer_base import ThreatLayer, LayerReading
from upin.core.position import ThreatAlert, ThreatLevel


class RFThreatLocalisation(ThreatLayer):
    """T1 — RF Threat Localisation.

    Direction and source identification of jamming and spoofing transmitters.
    Uses RF anomaly data from Layer 16 and directional antenna data.
    """

    def __init__(self):
        super().__init__(
            threat_id="T1",
            name="RF Threat Localisation",
            is_hardware=True,
            description="Jammer/spoofer direction finding and source ID",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id == "rfanomaly_l16" and r.raw_data:
                if r.raw_data.get("anomaly_detected"):
                    threats.append(ThreatAlert(
                        threat_id="T1_RF",
                        threat_type="RF_THREAT",
                        level=ThreatLevel.HIGH,
                        description="RF anomaly: possible jammer/spoofer detected",
                        source_layer="T1",
                        bearing=np.random.uniform(0, 360),
                        range_m=np.random.uniform(500, 5000),
                        confidence=r.raw_data.get("snr_db", 0) / 50,
                    ))
        return threats


class AcousticThreatSignatures(ThreatLayer):
    """T2 — Acoustic Threat Signatures.

    Submarine propeller signatures, torpedo launch acoustics,
    diver breathing apparatus detection.
    """

    def __init__(self):
        super().__init__(
            threat_id="T2",
            name="Acoustic Threat Signatures",
            is_hardware=True,
            description="Submarine, torpedo, diver acoustic detection",
        )
        self._signature_library = {
            "submarine_propeller": {"freq_range": (10, 500), "pattern": "cyclic"},
            "torpedo_launch": {"freq_range": (200, 2000), "pattern": "impulse"},
            "diver_breathing": {"freq_range": (50, 400), "pattern": "rhythmic"},
        }

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id in ("acoustic_l10", "sonar_l34") and r.raw_data:
                # Simulate signature matching
                if np.random.random() < 0.02:  # 2% chance per scan
                    threats.append(ThreatAlert(
                        threat_id="T2_ACOUSTIC",
                        threat_type="ACOUSTIC_THREAT",
                        level=ThreatLevel.MODERATE,
                        description="Acoustic signature match: possible submarine",
                        source_layer="T2",
                        confidence=0.6,
                    ))
        return threats


class MagneticAnomalyThreat(ThreatLayer):
    """T3 — Magnetic Anomaly Threat Detection.

    Large ferrous objects: submarines, armoured vehicles, buried weapons caches.
    """

    def __init__(self):
        super().__init__(
            threat_id="T3",
            name="Magnetic Anomaly Threat",
            is_hardware=True,
            description="Ferrous object detection — subs, armour, weapons",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id in ("magano_l6", "dualqmag_l17", "nvdiamond_l30") and r.raw_data:
                field = r.raw_data.get("field_nt", r.raw_data.get("sensitivity_pt", 0))
                if isinstance(field, (int, float)) and abs(field - 45000) > 200:
                    threats.append(ThreatAlert(
                        threat_id="T3_MAG",
                        threat_type="MAGNETIC_ANOMALY",
                        level=ThreatLevel.MODERATE,
                        description="Large ferrous object detected via magnetic anomaly",
                        source_layer="T3",
                        confidence=0.5,
                    ))
        return threats


class SubsurfaceStructureDetection(ThreatLayer):
    """T4 — Subsurface Structure Detection.

    Underground bunkers, tunnels, weapon storage via gravity gradiometry.
    """

    def __init__(self):
        super().__init__(
            threat_id="T4",
            name="Subsurface Structure Detection",
            is_hardware=True,
            description="Underground bunker/tunnel detection via gravity",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id == "gravgrad_l28a" and r.raw_data:
                if r.raw_data.get("tunnel_detected") or r.raw_data.get("underground_anomaly"):
                    threats.append(ThreatAlert(
                        threat_id="T4_SUBSURFACE",
                        threat_type="UNDERGROUND_STRUCTURE",
                        level=ThreatLevel.MODERATE,
                        description="Underground structure detected via gravity gradient",
                        source_layer="T4",
                        confidence=0.7,
                    ))
        return threats


class VisualObjectRecognition(ThreatLayer):
    """T5 — Visual Object Recognition.

    Vehicle and personnel classification using deep learning on SLAM camera.
    """

    def __init__(self):
        super().__init__(
            threat_id="T5",
            name="Visual Object Recognition",
            is_hardware=True,
            description="AI vehicle/personnel classification from camera",
        )
        self._threat_classes = [
            "tank", "apc", "artillery", "missile_launcher",
            "armed_personnel", "anti_aircraft",
        ]

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id in ("vslam_l31", "vio_l32") and r.raw_data:
                # Simulate object detection
                if np.random.random() < 0.01:
                    obj_class = np.random.choice(self._threat_classes)
                    threats.append(ThreatAlert(
                        threat_id="T5_VISUAL",
                        threat_type="VISUAL_THREAT",
                        level=ThreatLevel.HIGH,
                        description=f"Visual classification: {obj_class}",
                        source_layer="T5",
                        confidence=0.75,
                    ))
        return threats


class ThermalThreatDetection(ThreatLayer):
    """T6 — Thermal Threat Detection.

    Body heat signatures, vehicle engine signatures, submarine reactor thermal.
    """

    def __init__(self):
        super().__init__(
            threat_id="T6",
            name="Thermal Threat Detection",
            is_hardware=True,
            description="Body heat, engine, reactor thermal detection",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id == "thermal_l38" and r.raw_data:
                sigs = r.raw_data.get("body_heat_signatures", 0)
                if sigs > 5:
                    threats.append(ThreatAlert(
                        threat_id="T6_THERMAL",
                        threat_type="THERMAL_CONCENTRATION",
                        level=ThreatLevel.MODERATE,
                        description=f"Thermal: {sigs} body heat signatures concentrated",
                        source_layer="T6",
                        confidence=0.7,
                    ))
        return threats


class SeismicThreatDetection(ThreatLayer):
    """T7 — Seismic Threat Detection.

    Footstep patterns, vehicle movement, explosion seismic signatures.
    """

    def __init__(self):
        super().__init__(
            threat_id="T7",
            name="Seismic Threat Detection",
            is_hardware=True,
            description="Footsteps, vehicles, explosions via seismic",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id == "seismic_l36" and r.raw_data:
                vehicles = r.raw_data.get("vehicle_signatures", 0)
                if vehicles > 2:
                    threats.append(ThreatAlert(
                        threat_id="T7_SEISMIC",
                        threat_type="GROUND_MOVEMENT",
                        level=ThreatLevel.MODERATE,
                        description=f"Seismic: {vehicles} vehicle signatures detected",
                        source_layer="T7",
                        confidence=0.65,
                    ))
        return threats


class HydrodynamicTrailTracking(ThreatLayer):
    """T8 — Hydrodynamic Trail Tracking.

    Submarine wake detection minutes after passage.
    """

    def __init__(self):
        super().__init__(
            threat_id="T8",
            name="Hydrodynamic Trail Tracking",
            is_hardware=True,
            description="Submarine wake detection and tracking",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id == "hydrowake_l37" and r.raw_data:
                if r.raw_data.get("wake_detected"):
                    obj = r.raw_data.get("object_class", "unknown")
                    threats.append(ThreatAlert(
                        threat_id="T8_HYDRO",
                        threat_type="SUBMARINE_WAKE",
                        level=ThreatLevel.HIGH,
                        description=f"Hydrodynamic wake: {obj} trail detected",
                        source_layer="T8",
                        bearing=r.raw_data.get("wake_bearing_deg"),
                        confidence=0.6,
                    ))
        return threats


# Convenience list of all hardware threat layers
ALL_HARDWARE_THREAT_LAYERS = [
    RFThreatLocalisation,
    AcousticThreatSignatures,
    MagneticAnomalyThreat,
    SubsurfaceStructureDetection,
    VisualObjectRecognition,
    ThermalThreatDetection,
    SeismicThreatDetection,
    HydrodynamicTrailTracking,
]
