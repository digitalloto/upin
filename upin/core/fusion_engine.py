"""
UPIN AI Fusion Engine — Core of the Present Invention.

Patent Section 6.1: At each processing cycle (10-1000 Hz), the engine executes:
    1. COLLECT  — Receive position/nav data from all active layers
    2. COMPARE  — Cross-validate via EKF + ML anomaly detection
    3. CANCEL   — Flag/downweight disagreeing layers
    4. OUTPUT   — Unified position + confidence score

The engine is architecturally extensible: any new layer can be added
without modifying this core code. The engine dynamically adjusts to
whatever layers are currently active.
"""

from __future__ import annotations

import time
import logging
from typing import Optional

import numpy as np
from scipy.linalg import block_diag

from upin.core.position import (
    Position, NavigationOutput, ThreatAlert, ThreatLevel, LayerDiagnostic,
)
from upin.core.layer_base import NavigationLayer, ThreatLayer, LayerReading
from upin.core.confidence import ConfidenceScorer

logger = logging.getLogger(__name__)


class ExtendedKalmanFilter:
    """Extended Kalman Filter for multi-layer sensor fusion.

    State vector: [lat, lon, alt, v_north, v_east, v_down, heading]
    Units: degrees, degrees, metres, m/s, m/s, m/s, radians
    """

    STATE_DIM = 7  # lat, lon, alt, vn, ve, vd, heading

    def __init__(self):
        # State vector
        self.x = np.zeros(self.STATE_DIM)
        # State covariance
        self.P = np.eye(self.STATE_DIM) * 100.0
        # Process noise
        self.Q = np.diag([1e-8, 1e-8, 0.1, 0.01, 0.01, 0.01, 1e-4])
        self._initialized = False

    def predict(self, dt: float) -> None:
        """Predict step: propagate state forward by dt seconds."""
        if not self._initialized:
            return

        # State transition: position += velocity * dt
        # lat += v_north * dt / R_earth (convert m/s to deg/s)
        R_earth = 6_371_000.0
        self.x[0] += self.x[3] * dt / R_earth * (180.0 / np.pi)
        self.x[1] += (self.x[4] * dt /
                       (R_earth * np.cos(np.radians(self.x[0]))) *
                       (180.0 / np.pi))
        self.x[2] -= self.x[5] * dt  # alt decreases with positive v_down

        # State transition matrix (Jacobian)
        F = np.eye(self.STATE_DIM)
        F[0, 3] = dt / R_earth * (180.0 / np.pi)
        cos_lat = np.cos(np.radians(self.x[0]))
        if abs(cos_lat) > 1e-10:
            F[1, 4] = dt / (R_earth * cos_lat) * (180.0 / np.pi)
        F[2, 5] = -dt

        # Covariance prediction
        self.P = F @ self.P @ F.T + self.Q * dt

    def update(self, z: np.ndarray, H: np.ndarray, R: np.ndarray) -> None:
        """Update step: incorporate a measurement.

        Args:
            z: Measurement vector.
            H: Measurement matrix mapping state to measurement.
            R: Measurement noise covariance.
        """
        if not self._initialized:
            # First measurement initializes the state
            if len(z) >= 3:
                self.x[0] = z[0]  # lat
                self.x[1] = z[1]  # lon
                self.x[2] = z[2]  # alt
            self._initialized = True
            return

        y = z - H @ self.x  # Innovation
        S = H @ self.P @ H.T + R  # Innovation covariance
        try:
            K = self.P @ H.T @ np.linalg.inv(S)  # Kalman gain
        except np.linalg.LinAlgError:
            logger.warning("Singular innovation covariance, skipping update")
            return

        self.x = self.x + K @ y
        I_KH = np.eye(self.STATE_DIM) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T  # Joseph form

    @property
    def position(self) -> tuple[float, float, float]:
        return (float(self.x[0]), float(self.x[1]), float(self.x[2]))

    @property
    def velocity(self) -> tuple[float, float, float]:
        return (float(self.x[3]), float(self.x[4]), float(self.x[5]))

    @property
    def heading(self) -> float:
        return float(np.degrees(self.x[6]) % 360)


class AnomalyDetector:
    """ML-based anomaly detection for cross-layer disagreement.

    Augments the EKF with statistical analysis to detect:
    - Sudden position jumps (spoofing)
    - Gradual drift (slow spoofing)
    - Layer cluster divergence (multi-vector attack)
    """

    def __init__(self, history_size: int = 200):
        self._history: list[dict] = []
        self._history_size = history_size
        self._baseline_variance: Optional[float] = None

    def analyze(
        self,
        readings: list[LayerReading],
        consensus: tuple[float, float, float],
    ) -> dict:
        """Analyse readings for anomalies.

        Returns dict with:
            - outlier_ids: list of layer_ids that are outliers
            - attack_type: None, 'spoofing', 'jamming', 'gradual_drift'
            - anomaly_score: 0.0 (normal) to 1.0 (definite attack)
        """
        if not readings:
            return {"outlier_ids": [], "attack_type": None, "anomaly_score": 0.0}

        deviations = []
        for r in readings:
            if r.position is None or not r.is_valid:
                continue
            dev = self._deviation_m(r.position.as_array(), consensus)
            deviations.append((r.layer_id, dev))

        if not deviations:
            return {"outlier_ids": [], "attack_type": None, "anomaly_score": 0.0}

        devs = np.array([d[1] for d in deviations])
        median_dev = np.median(devs)
        mad = np.median(np.abs(devs - median_dev))  # Median Absolute Deviation
        if mad < 1.0:
            mad = 1.0

        # Outliers: deviation > 3 * MAD from median
        outlier_ids = []
        for layer_id, dev in deviations:
            if abs(dev - median_dev) > 3 * mad:
                outlier_ids.append(layer_id)

        # Determine attack type
        attack_type = None
        anomaly_score = len(outlier_ids) / max(len(deviations), 1)

        if outlier_ids:
            # Check if outliers are satellite layers (spoofing indicator)
            sat_prefixes = ("gps", "navic", "leo", "gnss")
            sat_outliers = [o for o in outlier_ids
                           if any(o.lower().startswith(p) for p in sat_prefixes)]
            if sat_outliers and len(outlier_ids) <= len(sat_outliers) + 1:
                attack_type = "spoofing"
                anomaly_score = min(1.0, anomaly_score * 2)

        # Check for gradual drift
        self._history.append({"median_dev": median_dev, "time": time.time()})
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

        if len(self._history) >= 50 and attack_type is None:
            recent = [h["median_dev"] for h in self._history[-50:]]
            drift_rate = (recent[-1] - recent[0]) / 50
            if drift_rate > 0.5:  # 0.5m per cycle drift
                attack_type = "gradual_drift"
                anomaly_score = min(1.0, drift_rate / 2.0)

        return {
            "outlier_ids": outlier_ids,
            "attack_type": attack_type,
            "anomaly_score": anomaly_score,
        }

    def _deviation_m(self, pos: tuple, consensus: tuple) -> float:
        lat1, lon1 = np.radians(pos[0]), np.radians(pos[1])
        lat2, lon2 = np.radians(consensus[0]), np.radians(consensus[1])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = (np.sin(dlat/2)**2 +
             np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2)
        horiz = 6_371_000 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
        vert = abs(pos[2] - consensus[2])
        return float(np.sqrt(horiz**2 + vert**2))


class FusionEngine:
    """The UPIN AI Fusion Engine.

    This is the core of the present invention. It orchestrates all
    positioning layers, threat layers, and produces the unified
    NavigationOutput with confidence score at each cycle.

    Usage:
        engine = FusionEngine()
        engine.register_layer(gps_layer)
        engine.register_layer(navic_layer)
        engine.register_layer(ins_layer)
        ...
        engine.initialize()

        while running:
            output = engine.cycle()
            print(output.position, output.confidence_score)
    """

    def __init__(
        self,
        cycle_rate_hz: float = 10.0,
        agreement_threshold_m: float = 50.0,
        navic_primary: bool = True,
    ):
        self.cycle_rate_hz = cycle_rate_hz
        self.navic_primary = navic_primary

        # Layer registries
        self._nav_layers: dict[str, NavigationLayer] = {}
        self._threat_layers: dict[str, ThreatLayer] = {}

        # Core components
        self._ekf = ExtendedKalmanFilter()
        self._anomaly_detector = AnomalyDetector()
        self._confidence_scorer = ConfidenceScorer(
            agreement_threshold_m=agreement_threshold_m,
            min_layers_for_full_trust=10,
        )

        # State
        self._cycle_count = 0
        self._last_cycle_time = 0.0
        self._last_output: Optional[NavigationOutput] = None
        self._layer_weights: dict[str, float] = {}
        self._layer_reliabilities: dict[str, float] = {}
        self._initialized = False

    # ── Registration ──────────────────────────────────────────────

    def register_layer(self, layer: NavigationLayer) -> None:
        """Register a navigation/positioning layer with the engine."""
        self._nav_layers[layer.layer_id] = layer
        self._layer_weights[layer.layer_id] = layer.get_accuracy_rating()
        self._layer_reliabilities[layer.layer_id] = 1.0
        logger.info(f"Registered navigation layer: {layer}")

    def register_threat_layer(self, layer: ThreatLayer) -> None:
        """Register a threat detection layer."""
        self._threat_layers[layer.threat_id] = layer
        logger.info(f"Registered threat layer: {layer}")

    def unregister_layer(self, layer_id: str) -> None:
        """Remove a layer. Engine adapts dynamically."""
        self._nav_layers.pop(layer_id, None)
        self._layer_weights.pop(layer_id, None)
        self._layer_reliabilities.pop(layer_id, None)

    # ── Initialization ────────────────────────────────────────────

    def initialize(self) -> bool:
        """Initialize all registered layers and the fusion engine."""
        logger.info(f"Initializing UPIN Fusion Engine with "
                     f"{len(self._nav_layers)} navigation layers, "
                     f"{len(self._threat_layers)} threat layers")

        for layer in self._nav_layers.values():
            try:
                layer.initialize()
            except Exception as e:
                logger.error(f"Failed to initialize {layer}: {e}")
                layer.status.is_healthy = False

        for tlayer in self._threat_layers.values():
            try:
                tlayer.initialize()
            except Exception as e:
                logger.error(f"Failed to initialize {tlayer}: {e}")
                tlayer.is_active = False

        # Apply NavIC primary weighting
        if self.navic_primary:
            for lid, layer in self._nav_layers.items():
                if "navic" in lid.lower():
                    self._layer_weights[lid] *= 1.5
                    logger.info(f"NavIC primary: boosted weight for {lid}")

        self._initialized = True
        self._last_cycle_time = time.time()
        logger.info("UPIN Fusion Engine initialized")
        return True

    # ── Main Processing Cycle ─────────────────────────────────────

    def cycle(self) -> NavigationOutput:
        """Execute one complete fusion cycle: COLLECT → COMPARE → CANCEL → OUTPUT.

        This is the method called at 10-1000 Hz in operation.
        """
        if not self._initialized:
            raise RuntimeError("FusionEngine not initialized. Call initialize() first.")

        now = time.time()
        dt = now - self._last_cycle_time if self._last_cycle_time else 1.0 / self.cycle_rate_hz
        self._last_cycle_time = now
        self._cycle_count += 1

        # ── STEP 1: COLLECT ──
        readings = self._collect_readings()

        # ── STEP 2: COMPARE (EKF predict + update) ──
        self._ekf.predict(dt)
        self._process_measurements(readings)

        consensus = self._ekf.position

        # ── STEP 3: CANCEL ERRORS (anomaly detection + weight adjustment) ──
        anomaly = self._anomaly_detector.analyze(readings, consensus)
        self._adjust_weights(anomaly)

        # ── STEP 4: OUTPUT (confidence scoring + threat detection) ──
        # Build layer position list for confidence scorer
        layer_positions = []
        for r in readings:
            if r.position is not None and r.is_valid:
                layer_positions.append({
                    "layer_id": r.layer_id,
                    "position": r.position.as_array(),
                    "weight": self._layer_weights.get(r.layer_id, 1.0),
                    "reliability": self._layer_reliabilities.get(r.layer_id, 1.0),
                    "accuracy_rating": self._nav_layers[r.layer_id].get_accuracy_rating()
                    if r.layer_id in self._nav_layers else 1.0,
                })

        confidence = self._confidence_scorer.compute(layer_positions, consensus)

        # Run threat detection
        threats = self._run_threat_detection(readings)

        # Determine overall threat level
        threat_level = ThreatLevel.NONE
        if threats:
            max_threat = max(t.level.value for t in threats)
            threat_level = ThreatLevel(max_threat)

        # Add spoofing/jamming threat alerts
        if anomaly["attack_type"] == "spoofing" or confidence.spoofing_suspected:
            threats.append(ThreatAlert(
                threat_id="SPOOF_DETECT",
                threat_type="GPS_SPOOFING",
                level=ThreatLevel.CRITICAL,
                description=(f"GPS spoofing detected via cross-layer disagreement. "
                             f"Outlier layers: {anomaly['outlier_ids']}"),
                source_layer="fusion_engine",
                confidence=anomaly["anomaly_score"] * 100,
            ))
            if threat_level.value < ThreatLevel.CRITICAL.value:
                threat_level = ThreatLevel.CRITICAL

        if confidence.jamming_suspected:
            threats.append(ThreatAlert(
                threat_id="JAM_DETECT",
                threat_type="SIGNAL_JAMMING",
                level=ThreatLevel.HIGH,
                description="Signal jamming suspected: sudden confidence drop detected",
                source_layer="fusion_engine",
                confidence=75.0,
            ))
            if threat_level.value < ThreatLevel.HIGH.value:
                threat_level = ThreatLevel.HIGH

        # Build layer diagnostics
        diagnostics = self._build_diagnostics(readings, anomaly)

        # Determine GPS/NavIC trust
        gps_trusted = "gps_l1" not in anomaly.get("outlier_ids", [])
        navic_trusted = "navic_l2" not in anomaly.get("outlier_ids", [])

        # Build final output
        position = Position(
            latitude=consensus[0],
            longitude=consensus[1],
            altitude=consensus[2],
            heading=self._ekf.heading,
            velocity=float(np.linalg.norm(self._ekf.velocity[:2])),
            timestamp=now,
            accuracy_m=self._estimate_accuracy(confidence.score),
        )

        output = NavigationOutput(
            position=position,
            confidence_score=confidence.score,
            num_active_layers=confidence.num_active,
            num_agreeing_layers=confidence.num_agreeing,
            threat_level=threat_level,
            threat_alerts=threats,
            layer_diagnostics=diagnostics,
            timestamp=now,
            cycle_hz=self.cycle_rate_hz,
            spoofing_detected=confidence.spoofing_suspected,
            jamming_detected=confidence.jamming_suspected,
            gps_trusted=gps_trusted,
            navic_trusted=navic_trusted,
        )

        self._last_output = output
        return output

    # ── Internal Methods ──────────────────────────────────────────

    def _collect_readings(self) -> list[LayerReading]:
        """STEP 1: Collect readings from all active layers."""
        readings = []
        for layer_id, layer in self._nav_layers.items():
            if not layer.status.is_active or not layer.status.is_healthy:
                continue
            try:
                reading = layer.read()
                reading.layer_id = layer_id
                readings.append(reading)
                layer.status.last_update = time.time()
                layer.status.consecutive_failures = 0
            except Exception as e:
                layer.status.consecutive_failures += 1
                layer.status.error_count += 1
                if layer.status.consecutive_failures >= 5:
                    layer.status.is_healthy = False
                    logger.warning(f"Layer {layer_id} marked unhealthy: {e}")
        return readings

    def _process_measurements(self, readings: list[LayerReading]) -> None:
        """STEP 2: Feed measurements into the EKF."""
        for r in readings:
            if r.position is None or not r.is_valid:
                continue

            pos = r.position.as_array()
            z = np.array([pos[0], pos[1], pos[2]])

            # Measurement matrix: we observe lat, lon, alt directly
            H = np.zeros((3, ExtendedKalmanFilter.STATE_DIM))
            H[0, 0] = 1.0  # lat
            H[1, 1] = 1.0  # lon
            H[2, 2] = 1.0  # alt

            # Measurement noise based on layer accuracy and weight
            w = self._layer_weights.get(r.layer_id, 1.0)
            acc = r.position.accuracy_m
            # Convert accuracy in metres to degrees for lat/lon
            deg_noise = (acc / 111_000.0) ** 2  # ~111km per degree
            R = np.diag([deg_noise / max(w, 0.01),
                         deg_noise / max(w, 0.01),
                         acc ** 2 / max(w, 0.01)])

            self._ekf.update(z, H, R)

            # Also update velocity/heading if available
            if r.heading is not None:
                z_h = np.array([np.radians(r.heading)])
                H_h = np.zeros((1, ExtendedKalmanFilter.STATE_DIM))
                H_h[0, 6] = 1.0
                R_h = np.array([[0.1 / max(w, 0.01)]])
                self._ekf.update(z_h, H_h, R_h)

    def _adjust_weights(self, anomaly: dict) -> None:
        """STEP 3: Reduce weight of outlier/compromised layers."""
        for layer_id in anomaly.get("outlier_ids", []):
            if layer_id in self._layer_weights:
                # Reduce weight by 50% per detection
                self._layer_weights[layer_id] *= 0.5
                if layer_id in self._nav_layers:
                    self._nav_layers[layer_id].status.spoofing_suspected = True
                logger.debug(f"Weight reduced for outlier layer: {layer_id}")

        # Slowly restore weights for non-outlier layers
        for layer_id in self._nav_layers:
            if layer_id not in anomaly.get("outlier_ids", []):
                base = self._nav_layers[layer_id].get_accuracy_rating()
                current = self._layer_weights.get(layer_id, base)
                if current < base:
                    self._layer_weights[layer_id] = min(
                        base, current * 1.01  # 1% recovery per cycle
                    )

    def _run_threat_detection(self, readings: list[LayerReading]) -> list[ThreatAlert]:
        """Run all registered threat detection layers."""
        threats = []
        for tid, tlayer in self._threat_layers.items():
            if not tlayer.is_active:
                continue
            try:
                detected = tlayer.scan(readings, self._last_output)
                threats.extend(detected)
            except Exception as e:
                logger.error(f"Threat layer {tid} failed: {e}")
        return threats

    def _build_diagnostics(
        self, readings: list[LayerReading], anomaly: dict
    ) -> list[LayerDiagnostic]:
        """Build per-layer diagnostic information."""
        diagnostics = []
        for layer_id, layer in self._nav_layers.items():
            reading = next((r for r in readings if r.layer_id == layer_id), None)
            diagnostics.append(LayerDiagnostic(
                layer_id=layer_id,
                layer_name=layer.name,
                is_active=layer.status.is_active,
                is_trusted=layer_id not in anomaly.get("outlier_ids", []),
                current_weight=self._layer_weights.get(layer_id, 0.0),
                reliability_coefficient=self._layer_reliabilities.get(layer_id, 1.0),
                last_position=reading.position if reading else None,
                spoofing_suspected=layer_id in anomaly.get("outlier_ids", []),
            ))
        return diagnostics

    def _estimate_accuracy(self, confidence_score: float) -> float:
        """Estimate position accuracy in metres from confidence score."""
        if confidence_score >= 95:
            return 0.5  # Sub-metre with 10+ layers
        elif confidence_score >= 80:
            return 2.0
        elif confidence_score >= 60:
            return 10.0
        elif confidence_score >= 40:
            return 50.0
        else:
            return 200.0

    # ── Query Methods ─────────────────────────────────────────────

    @property
    def num_active_layers(self) -> int:
        return sum(1 for l in self._nav_layers.values()
                   if l.status.is_active and l.status.is_healthy)

    @property
    def registered_layers(self) -> list[str]:
        return list(self._nav_layers.keys())

    @property
    def registered_threat_layers(self) -> list[str]:
        return list(self._threat_layers.keys())

    def get_layer(self, layer_id: str) -> Optional[NavigationLayer]:
        return self._nav_layers.get(layer_id)

    @property
    def last_output(self) -> Optional[NavigationOutput]:
        return self._last_output

    @property
    def ekf_state(self) -> dict:
        return {
            "position": self._ekf.position,
            "velocity": self._ekf.velocity,
            "heading": self._ekf.heading,
            "covariance_trace": float(np.trace(self._ekf.P)),
        }

    def status_report(self) -> str:
        """Human-readable status report."""
        lines = [
            "═══════════════════════════════════════════════",
            "  UPIN FUSION ENGINE STATUS",
            "═══════════════════════════════════════════════",
            f"  Cycle count:      {self._cycle_count}",
            f"  Active layers:    {self.num_active_layers}/{len(self._nav_layers)}",
            f"  Threat layers:    {len(self._threat_layers)}",
            f"  Cycle rate:       {self.cycle_rate_hz} Hz",
            f"  NavIC primary:    {self.navic_primary}",
        ]
        if self._last_output:
            o = self._last_output
            lines.extend([
                f"  ─────────────────────────────────────────────",
                f"  Position:         {o.position.latitude:.6f}°N, "
                f"{o.position.longitude:.6f}°E",
                f"  Altitude:         {o.position.altitude:.1f} m",
                f"  Confidence:       {o.confidence_score:.1f}% — {o.trust_level}",
                f"  Agreeing layers:  {o.num_agreeing_layers}/{o.num_active_layers}",
                f"  Spoofing:         {'DETECTED' if o.spoofing_detected else 'Clear'}",
                f"  Jamming:          {'DETECTED' if o.jamming_detected else 'Clear'}",
                f"  Threat level:     {o.threat_level.name}",
                f"  Active threats:   {len(o.threat_alerts)}",
            ])
        lines.append("═══════════════════════════════════════════════")
        return "\n".join(lines)

    # ── Extended Kalman Filter property (for direct access) ──
    ExtendedKalmanFilter = ExtendedKalmanFilter
