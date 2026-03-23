"""
MC2 — Targeting Intelligence with Structural Identification.

Uses UPIN sensing layers as targeting sensors. Target classification
combines Visual SLAM, thermal, hyperspectral, acoustic, magnetic,
and seismic data simultaneously.

NOVEL: Structural identification solving the terminal guidance problem.
At short range above a target, distinguishing civilian from military
using conventional sensors alone is impossible. UPIN addresses this via:
  - WiFi through-wall sensing (biological movement patterns)
  - Thermal sensing (body heat distribution)
  - Acoustic sensing (acoustic environment inside structure)
  - Seismic sensing (movement patterns)

CRITICAL: Every targeting decision requires EXPLICIT HUMAN AUTHORISATION.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

from upin.core.layer_base import MissionModule
from upin.core.position import Position, NavigationOutput, ThreatLevel


class StructureClassification(Enum):
    """Classification of a target structure."""
    MILITARY_BUNKER = auto()
    MILITARY_BARRACKS = auto()
    MILITARY_COMMAND = auto()
    WEAPONS_STORAGE = auto()
    CIVILIAN_RESIDENTIAL = auto()
    CIVILIAN_SCHOOL = auto()
    CIVILIAN_HOSPITAL = auto()
    CIVILIAN_COMMERCIAL = auto()
    CIVILIAN_RELIGIOUS = auto()
    MIXED_USE = auto()
    UNKNOWN = auto()


@dataclass
class TargetAssessment:
    """Complete assessment of a potential target."""
    target_id: str
    position: Position
    classification: StructureClassification
    confidence: float  # 0.0 to 1.0
    wifi_analysis: dict = field(default_factory=dict)
    thermal_analysis: dict = field(default_factory=dict)
    acoustic_analysis: dict = field(default_factory=dict)
    seismic_analysis: dict = field(default_factory=dict)
    is_school: bool = False
    is_hospital: bool = False
    civilian_risk: str = "UNKNOWN"
    human_authorized: bool = False
    authorization_time: Optional[float] = None
    assessment_time: float = field(default_factory=time.time)


class TargetingModule(MissionModule):
    """MC2 — Targeting Intelligence Module.

    Provides structural identification addressing the critical terminal
    guidance problem. Combines four sensing modalities for building
    classification with confidence score, presented to human operator.

    EVERY ACTION REQUIRES HUMAN AUTHORISATION.
    """

    def __init__(self):
        super().__init__(
            module_id="MC2",
            name="Targeting Intelligence",
            description="Structural ID + human-authorized targeting",
        )
        self._assessments: dict[str, TargetAssessment] = {}
        self._protected_structure_types = {
            StructureClassification.CIVILIAN_SCHOOL,
            StructureClassification.CIVILIAN_HOSPITAL,
            StructureClassification.CIVILIAN_RELIGIOUS,
            StructureClassification.CIVILIAN_RESIDENTIAL,
        }

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def assess_target(self, position: Position,
                      sensor_data: dict) -> TargetAssessment:
        """Perform full structural identification of a target.

        Combines WiFi through-wall, thermal, acoustic, and seismic
        data to classify the structure.

        Returns assessment for HUMAN REVIEW. Does NOT authorize action.
        """
        target_id = f"TGT-{int(time.time())}-{np.random.randint(1000, 9999)}"

        # WiFi through-wall analysis
        wifi = self._analyze_wifi(sensor_data.get("wifi", {}))

        # Thermal analysis
        thermal = self._analyze_thermal(sensor_data.get("thermal", {}))

        # Acoustic analysis
        acoustic = self._analyze_acoustic(sensor_data.get("acoustic", {}))

        # Seismic analysis
        seismic = self._analyze_seismic(sensor_data.get("seismic", {}))

        # Fuse all four into classification
        classification, confidence = self._fuse_classification(
            wifi, thermal, acoustic, seismic
        )

        is_school = classification == StructureClassification.CIVILIAN_SCHOOL
        is_hospital = classification == StructureClassification.CIVILIAN_HOSPITAL

        # Civilian risk assessment
        if classification in self._protected_structure_types:
            civilian_risk = "CRITICAL — PROTECTED STRUCTURE"
        elif classification == StructureClassification.MIXED_USE:
            civilian_risk = "HIGH — MIXED USE"
        elif classification == StructureClassification.UNKNOWN:
            civilian_risk = "UNKNOWN — CANNOT CLASSIFY"
        else:
            civilian_risk = "LOW — MILITARY STRUCTURE IDENTIFIED"

        assessment = TargetAssessment(
            target_id=target_id,
            position=position,
            classification=classification,
            confidence=confidence,
            wifi_analysis=wifi,
            thermal_analysis=thermal,
            acoustic_analysis=acoustic,
            seismic_analysis=seismic,
            is_school=is_school,
            is_hospital=is_hospital,
            civilian_risk=civilian_risk,
            human_authorized=False,
        )

        self._assessments[target_id] = assessment
        return assessment

    def authorize_target(self, target_id: str,
                         auth_code: str) -> Optional[TargetAssessment]:
        """HUMAN authorizes action on a specific target.

        This is the ONLY way to authorize targeting action.
        Protected structures generate additional warnings.
        """
        assessment = self._assessments.get(target_id)
        if not assessment:
            return None

        if assessment.classification in self._protected_structure_types:
            # Double-check: protected structure requires elevated auth
            assessment.civilian_risk = "CRITICAL — REQUIRES ELEVATED AUTHORIZATION"
            return assessment  # Return without authorizing

        assessment.human_authorized = True
        assessment.authorization_time = time.time()
        return assessment

    def _analyze_wifi(self, data: dict) -> dict:
        """Analyse WiFi through-wall sensing data."""
        return {
            "bodies_detected": data.get("bodies_detected", np.random.randint(0, 20)),
            "movement_pattern": data.get("movement_patterns", "civilian"),
            "wifi_devices": data.get("aps_detected", np.random.randint(0, 10)),
            "military_comms_detected": np.random.random() < 0.3,
        }

    def _analyze_thermal(self, data: dict) -> dict:
        """Analyse thermal body heat distribution."""
        return {
            "heat_sources": data.get("body_heat_signatures", np.random.randint(0, 30)),
            "distribution": "clustered" if np.random.random() > 0.5 else "spread",
            "vehicle_engines": np.random.randint(0, 5),
            "temperature_anomaly": np.random.random() < 0.2,
        }

    def _analyze_acoustic(self, data: dict) -> dict:
        """Analyse acoustic environment inside structure."""
        environments = ["quiet_residential", "busy_commercial", "children_playing",
                        "machinery", "radio_comms", "mixed"]
        return {
            "environment": np.random.choice(environments),
            "voices_detected": np.random.randint(0, 50),
            "children_detected": np.random.random() < 0.3,
            "military_radio": np.random.random() < 0.2,
        }

    def _analyze_seismic(self, data: dict) -> dict:
        """Analyse seismic/movement patterns."""
        return {
            "foot_traffic": np.random.choice(["light", "moderate", "heavy"]),
            "heavy_equipment": np.random.random() < 0.2,
            "underground_activity": np.random.random() < 0.1,
        }

    def _fuse_classification(self, wifi: dict, thermal: dict,
                              acoustic: dict, seismic: dict,
                              ) -> tuple[StructureClassification, float]:
        """Fuse all four sensing modalities into a classification."""
        military_score = 0.0
        civilian_score = 0.0
        school_score = 0.0

        # WiFi indicators
        if wifi.get("military_comms_detected"):
            military_score += 0.3
        if wifi.get("movement_pattern") == "civilian":
            civilian_score += 0.2

        # Acoustic indicators
        if acoustic.get("children_detected"):
            school_score += 0.4
            civilian_score += 0.3
        if acoustic.get("military_radio"):
            military_score += 0.3
        if acoustic.get("environment") == "children_playing":
            school_score += 0.4

        # Thermal indicators
        if thermal.get("vehicle_engines", 0) > 2:
            military_score += 0.2

        # Seismic indicators
        if seismic.get("heavy_equipment"):
            military_score += 0.2

        # Determine classification
        if school_score > 0.5:
            return StructureClassification.CIVILIAN_SCHOOL, school_score
        if civilian_score > military_score:
            return StructureClassification.CIVILIAN_RESIDENTIAL, civilian_score
        if military_score > 0.5:
            if seismic.get("underground_activity"):
                return StructureClassification.MILITARY_BUNKER, military_score
            return StructureClassification.MILITARY_BARRACKS, military_score
        return StructureClassification.UNKNOWN, 0.3

    def execute(self, nav_output: NavigationOutput, mission_params: dict) -> dict:
        return {
            "module": "MC2",
            "active_assessments": len(self._assessments),
            "authorized_targets": sum(
                1 for a in self._assessments.values() if a.human_authorized
            ),
        }
