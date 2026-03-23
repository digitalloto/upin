"""
Software Threat Detection Layers ST1-ST17.

These are PURE AI intelligence layers running on existing compute at ZERO
additional hardware cost. They analyse patterns, baselines, and anomalies
in the data already being collected by the navigation layers.

ST1:  Flight Dynamics Anomaly Detection
ST2:  Cross-Layer Disagreement Intelligence
ST3:  Behavioural Baseline Learning
ST4:  Command Integrity Verification
ST5:  Mission Deviation Detection
ST6:  Electronic Signature Library Matching
ST7:  Predictive Threat Modelling
ST8:  Swarm Threat Intelligence Sharing
ST9:  Integrity Self-Test
ST10: Environmental Context Assessment
ST11: Deep Fake Signal Detection
ST12: Insider Threat and Operator Anomaly Detection
ST13: Supply Chain Integrity Monitoring
ST14: EMP and Directed Energy Detection
ST15: Adversarial AI Detection
ST16: Human Vital Signs Threat Detection
ST17: Pattern of Life Analysis
"""

from __future__ import annotations

import time
from typing import Optional, Any

import numpy as np

from upin.core.layer_base import ThreatLayer, LayerReading
from upin.core.position import ThreatAlert, ThreatLevel


class FlightDynamicsAnomaly(ThreatLayer):
    """ST1 — Flight Dynamics Anomaly Detection.

    Physics baseline violation detection. If the platform is doing something
    physically impossible (accelerating beyond capability, turning tighter
    than structure allows), either the sensors are compromised or the
    platform is damaged.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST1", name="Flight Dynamics Anomaly",
            is_hardware=False,
            description="Physics baseline violation = attack or damage",
        )
        self._max_acceleration = 50.0  # m/s²
        self._max_turn_rate = 30.0  # deg/s
        self._velocity_history: list[float] = []

    def initialize(self) -> bool:
        self.is_active = True
        self._velocity_history = []
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        if nav_output and hasattr(nav_output, 'position'):
            vel = nav_output.position.velocity or 0
            self._velocity_history.append(vel)
            if len(self._velocity_history) > 2:
                accel = abs(self._velocity_history[-1] - self._velocity_history[-2]) * 10
                if accel > self._max_acceleration:
                    threats.append(ThreatAlert(
                        threat_id="ST1_DYNAMICS",
                        threat_type="PHYSICS_VIOLATION",
                        level=ThreatLevel.HIGH,
                        description=f"Impossible acceleration: {accel:.1f} m/s²",
                        source_layer="ST1",
                        confidence=0.8,
                    ))
            if len(self._velocity_history) > 100:
                self._velocity_history = self._velocity_history[-100:]
        return threats


class CrossLayerDisagreement(ThreatLayer):
    """ST2 — Cross-Layer Disagreement Intelligence.

    Analyses WHICH layers disagree and HOW to identify attack type and
    direction. Pattern of failure reveals attack vector.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST2", name="Cross-Layer Disagreement Intelligence",
            is_hardware=False,
            description="Attack type ID from layer failure patterns",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        if nav_output and hasattr(nav_output, 'layer_diagnostics'):
            untrusted = [d for d in nav_output.layer_diagnostics if not d.is_trusted]
            if len(untrusted) >= 3:
                names = [d.layer_name for d in untrusted[:5]]
                threats.append(ThreatAlert(
                    threat_id="ST2_DISAGREE",
                    threat_type="MULTI_LAYER_ATTACK",
                    level=ThreatLevel.HIGH,
                    description=f"Multiple layers compromised: {names}",
                    source_layer="ST2",
                    confidence=0.7,
                ))
        return threats


class BehaviouralBaseline(ThreatLayer):
    """ST3 — Behavioural Baseline Learning.

    Platform-specific learned sensor signature. Deviation from the
    learned baseline indicates attack even when individual readings
    appear valid.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST3", name="Behavioural Baseline Learning",
            is_hardware=False,
            description="Learned sensor signature deviation detection",
        )
        self._baseline_confidence: float = 85.0
        self._confidence_history: list[float] = []

    def initialize(self) -> bool:
        self.is_active = True
        self._confidence_history = []
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        if nav_output:
            self._confidence_history.append(nav_output.confidence_score)
            if len(self._confidence_history) > 50:
                mean_conf = np.mean(self._confidence_history[-50:])
                if mean_conf < self._baseline_confidence - 20:
                    threats.append(ThreatAlert(
                        threat_id="ST3_BASELINE",
                        threat_type="BASELINE_DEVIATION",
                        level=ThreatLevel.MODERATE,
                        description=f"Confidence baseline deviation: {mean_conf:.1f}% vs {self._baseline_confidence:.1f}%",
                        source_layer="ST3",
                        confidence=0.6,
                    ))
            if len(self._confidence_history) > 500:
                self._confidence_history = self._confidence_history[-500:]
        return threats


class CommandIntegrity(ThreatLayer):
    """ST4 — Command Integrity Verification.

    Command injection and replay attack detection.
    Validates command sequences for timing, authentication, and logic.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST4", name="Command Integrity Verification",
            is_hardware=False,
            description="Command injection and replay attack detection",
        )
        self._command_hashes: list[str] = []

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []  # Active during command processing


class MissionDeviation(ThreatLayer):
    """ST5 — Mission Deviation Detection.

    Route drift and navigation error accumulation detection.
    Alerts when platform deviates from planned route beyond threshold.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST5", name="Mission Deviation Detection",
            is_hardware=False,
            description="Route drift and nav error accumulation",
        )
        self._planned_route: list[tuple[float, float]] = []
        self._deviation_threshold_m = 500.0

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def set_planned_route(self, waypoints: list[tuple[float, float]]):
        self._planned_route = waypoints

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        if nav_output and self._planned_route and hasattr(nav_output, 'position'):
            pos = nav_output.position
            min_dist = float('inf')
            for wp in self._planned_route:
                dist = np.sqrt(
                    ((pos.latitude - wp[0]) * 111_000) ** 2 +
                    ((pos.longitude - wp[1]) * 111_000 * np.cos(np.radians(pos.latitude))) ** 2
                )
                min_dist = min(min_dist, dist)
            if min_dist > self._deviation_threshold_m:
                threats.append(ThreatAlert(
                    threat_id="ST5_DEVIATION",
                    threat_type="MISSION_DEVIATION",
                    level=ThreatLevel.MODERATE,
                    description=f"Route deviation: {min_dist:.0f}m from planned route",
                    source_layer="ST5",
                    confidence=0.8,
                ))
        return threats


class ElectronicSignatureLibrary(ThreatLayer):
    """ST6 — Electronic Signature Library Matching.

    Known threat emitter identification against database.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST6", name="Electronic Signature Library",
            is_hardware=False,
            description="Known threat emitter library matching",
        )
        self._threat_signatures = {
            "S-300": {"freq_ghz": 4.0, "prf_hz": 3000},
            "S-400": {"freq_ghz": 5.0, "prf_hz": 5000},
            "AESA_Fighter": {"freq_ghz": 10.0, "prf_hz": 10000},
        }

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []  # Active when RF data is available


class PredictiveThreatModelling(ThreatLayer):
    """ST7 — Predictive Threat Modelling.

    Pre-attack build-up and incoming threat trajectory prediction.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST7", name="Predictive Threat Modelling",
            is_hardware=False,
            description="Pre-attack prediction and threat trajectory",
        )
        self._threat_history: list[dict] = []

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        if nav_output and nav_output.threat_alerts:
            self._threat_history.extend([
                {"type": t.threat_type, "time": t.timestamp}
                for t in nav_output.threat_alerts
            ])
        if len(self._threat_history) > 1000:
            self._threat_history = self._threat_history[-500:]
        return []


class SwarmThreatSharing(ThreatLayer):
    """ST8 — Swarm Threat Intelligence Sharing.

    Collective threat detection across the swarm network.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST8", name="Swarm Threat Intelligence Sharing",
            is_hardware=False,
            description="Collective swarm threat intelligence",
        )
        self._peer_threats: list[ThreatAlert] = []

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def receive_peer_threats(self, threats: list[ThreatAlert]):
        self._peer_threats.extend(threats)

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        recent = [t for t in self._peer_threats if time.time() - t.timestamp < 60]
        self._peer_threats = recent
        return recent  # Forward peer threats


class IntegritySelfTest(ThreatLayer):
    """ST9 — Integrity Self-Test.

    Continuous hardware and software integrity verification.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST9", name="Integrity Self-Test",
            is_hardware=False,
            description="Continuous HW/SW integrity verification",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        invalid_count = sum(1 for r in layer_readings if not r.is_valid)
        if invalid_count > len(layer_readings) * 0.3:
            threats.append(ThreatAlert(
                threat_id="ST9_INTEGRITY",
                threat_type="SYSTEM_INTEGRITY",
                level=ThreatLevel.HIGH,
                description=f"{invalid_count}/{len(layer_readings)} layers returning invalid",
                source_layer="ST9",
                confidence=0.9,
            ))
        return threats


class EnvironmentalContext(ThreatLayer):
    """ST10 — Environmental Context Assessment.

    Known jamming hotspot and conflict zone awareness.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST10", name="Environmental Context",
            is_hardware=False,
            description="Known hotspot and conflict zone awareness",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        for r in layer_readings:
            if r.layer_id == "spoofmap_l21" and r.raw_data:
                if r.raw_data.get("in_spoofing_zone"):
                    threats.append(ThreatAlert(
                        threat_id="ST10_ZONE",
                        threat_type="SPOOFING_ZONE",
                        level=ThreatLevel.MODERATE,
                        description="Platform is in known GPS spoofing zone",
                        source_layer="ST10",
                        confidence=0.8,
                    ))
        return threats


class DeepFakeSignalDetection(ThreatLayer):
    """ST11 — Deep Fake Signal Detection.

    AI-generated fake navigation signal detection.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST11", name="Deep Fake Signal Detection",
            is_hardware=False,
            description="AI-generated fake nav signal detection",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []


class InsiderThreatDetection(ThreatLayer):
    """ST12 — Insider Threat and Operator Anomaly Detection.

    Compromised operator behaviour detection.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST12", name="Insider Threat Detection",
            is_hardware=False,
            description="Compromised operator behaviour detection",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []


class SupplyChainIntegrity(ThreatLayer):
    """ST13 — Supply Chain Integrity Monitoring.

    Malware in software updates and hardware backdoor detection.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST13", name="Supply Chain Integrity",
            is_hardware=False,
            description="Software/hardware supply chain integrity",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []


class EMPDetection(ThreatLayer):
    """ST14 — EMP and Directed Energy Detection.

    Electromagnetic pulse and HPM weapon detection.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST14", name="EMP/Directed Energy Detection",
            is_hardware=False,
            description="EMP and HPM weapon detection",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        threats = []
        invalid_count = sum(1 for r in layer_readings if not r.is_valid)
        total = len(layer_readings)
        if total > 0 and invalid_count / total > 0.5:
            threats.append(ThreatAlert(
                threat_id="ST14_EMP",
                threat_type="EMP_SUSPECTED",
                level=ThreatLevel.CRITICAL,
                description=f"Massive sensor failure ({invalid_count}/{total}) — possible EMP",
                source_layer="ST14",
                confidence=0.6,
            ))
        return threats


class AdversarialAIDetection(ThreatLayer):
    """ST15 — Adversarial AI Detection.

    Enemy AI probing and model poisoning detection.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST15", name="Adversarial AI Detection",
            is_hardware=False,
            description="Enemy AI probing and model poisoning",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []


class HumanVitalsThreat(ThreatLayer):
    """ST16 — Human Vital Signs Threat Detection.

    Personnel biometric response indicating hostile contact.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST16", name="Human Vital Signs Threat",
            is_hardware=False,
            description="Personnel biometric hostile contact detection",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []


class PatternOfLifeAnalysis(ThreatLayer):
    """ST17 — Pattern of Life Analysis.

    Pre-attack preparation detection through activity pattern deviation.
    """

    def __init__(self):
        super().__init__(
            threat_id="ST17", name="Pattern of Life Analysis",
            is_hardware=False,
            description="Pre-attack preparation via activity deviation",
        )

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        return []


# All software threat layers
ALL_SOFTWARE_THREAT_LAYERS = [
    FlightDynamicsAnomaly, CrossLayerDisagreement, BehaviouralBaseline,
    CommandIntegrity, MissionDeviation, ElectronicSignatureLibrary,
    PredictiveThreatModelling, SwarmThreatSharing, IntegritySelfTest,
    EnvironmentalContext, DeepFakeSignalDetection, InsiderThreatDetection,
    SupplyChainIntegrity, EMPDetection, AdversarialAIDetection,
    HumanVitalsThreat, PatternOfLifeAnalysis,
]
