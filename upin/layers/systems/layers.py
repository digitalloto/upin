"""
Group K — Systems Intelligence Layers (4 layers).

Layer 13: Antenna Stabilisation Layer [N]
Layer 14: Cascade Prevention Monitor [N]
Layer 15: Swarm Relative Positioning [N]
Layer 16: RF Signal Anomaly Detection [N]
"""

from __future__ import annotations

import math
import time
import numpy as np
from typing import Optional, Any

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position, NavigationOutput


class AntennaStabilisationLayer(NavigationLayer):
    """Layer 13 — Antenna Stabilisation Layer [NOVEL].

    UPIN position output feeds antenna pointing system. When GPS is
    compromised, antenna auto-corrects using alternative sources.
    Prevents cascade failure: GPS spoofing -> antenna misalignment -> datalink loss.
    """

    def __init__(self):
        super().__init__(
            layer_id="antenna_l13",
            layer_number=13,
            name="Antenna Stabilisation",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            description="Antenna pointing auto-correction on GPS compromise",
        )
        self._target_bearing: float = 0.0
        self._current_pointing: float = 0.0
        self._datalink_active: bool = True

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def update_pointing(self, nav_output: Any) -> dict:
        """Update antenna pointing based on UPIN position output.

        Returns pointing correction data.
        """
        if hasattr(nav_output, 'position') and nav_output.position.heading is not None:
            correction = self._target_bearing - nav_output.position.heading
            self._current_pointing += correction * 0.1  # Smooth correction
            return {
                "correction_deg": correction,
                "current_pointing": self._current_pointing,
                "datalink_maintained": True,
                "source": "upin_fused" if not nav_output.spoofing_detected else "backup",
            }
        return {"correction_deg": 0, "datalink_maintained": self._datalink_active}

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Heading from antenna pointing system via SimulationWorld.

        Uses world.true_heading as the reference for antenna pointing
        with small noise representing mechanical/electronic jitter.
        """
        noise_deg = 0.5
        heading = (self.world.true_heading + np.random.normal(0, noise_deg)) % 360.0
        self._current_pointing = heading
        return LayerReading(
            layer_id=self.layer_id,
            heading=heading,
            self_confidence=0.7,
            raw_data={
                "pointing_deg": heading,
                "datalink_active": self._datalink_active,
                "auto_corrected": True,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using current pointing state."""
        return LayerReading(
            layer_id=self.layer_id,
            heading=self._current_pointing % 360,
            self_confidence=0.7,
            raw_data={
                "pointing_deg": self._current_pointing,
                "datalink_active": self._datalink_active,
                "auto_corrected": True,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class CascadePreventionLayer(NavigationLayer):
    """Layer 14 — Cascade Prevention Monitor [NOVEL].

    Monitors all subsystems dependent on position data.
    When confidence drops, alerts all dependent systems BEFORE
    cascade failure begins.
    """

    def __init__(self):
        super().__init__(
            layer_id="cascade_l14",
            layer_number=14,
            name="Cascade Prevention Monitor",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="Pre-emptive cascade failure prevention",
        )
        self._confidence_threshold = 60.0
        self._dependent_systems = [
            "antenna_pointing", "geofence", "airspace_separation",
            "lost_link_procedure", "weapon_safety", "formation_keeping",
        ]
        self._alerts_active: list[str] = []

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.8

    def check_cascade_risk(self, confidence_score: float) -> dict:
        """Evaluate cascade risk from current confidence score."""
        if confidence_score < self._confidence_threshold:
            self._alerts_active = list(self._dependent_systems)
            return {
                "cascade_risk": "HIGH",
                "confidence": confidence_score,
                "systems_alerted": self._dependent_systems,
                "action": "ALERT_ALL_DEPENDENT_SYSTEMS",
            }
        self._alerts_active = []
        return {
            "cascade_risk": "LOW",
            "confidence": confidence_score,
            "systems_alerted": [],
        }

    def read(self) -> LayerReading:
        if self._simulated:
            # System monitoring layer — no position computation
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.9,
                raw_data={
                    "dependent_systems": len(self._dependent_systems),
                    "alerts_active": len(self._alerts_active),
                    "threshold": self._confidence_threshold,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class SwarmRelativePositionLayer(NavigationLayer):
    """Layer 15 — Swarm Relative Positioning [NOVEL].

    Each platform maintains exact position relative to every other
    swarm member. Enables coherent formation, deconfliction, and
    collective intelligence without centralised control.
    """

    def __init__(self):
        super().__init__(
            layer_id="swarmrel_l15",
            layer_number=15,
            name="Swarm Relative Positioning",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Peer-to-peer swarm relative position tracking",
        )
        self._peer_positions: dict[str, Position] = {}

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def update_peer(self, peer_id: str, position: Position) -> None:
        """Update known position of a swarm peer."""
        self._peer_positions[peer_id] = position

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Position from swarm peer averaging via SimulationWorld.

        Simulates swarm peers around the true position and averages
        their positions to derive a fused estimate.  When real peers
        are registered, they are used instead.
        """
        noise_m = 5.0

        if self._peer_positions:
            # Use real registered peers
            avg_lat = np.mean([p.latitude for p in self._peer_positions.values()])
            avg_lon = np.mean([p.longitude for p in self._peer_positions.values()])
        else:
            # Simulate swarm peers around true position
            n_peers = 4
            peer_lats = []
            peer_lons = []
            for _ in range(n_peers):
                peer_noise = 20.0  # Each peer has ~20m uncertainty
                p_lat = self.world.true_lat + np.random.normal(0, peer_noise / 111_000)
                p_lon = self.world.true_lon + np.random.normal(0, peer_noise / 111_000)
                peer_lats.append(p_lat)
                peer_lons.append(p_lon)
            avg_lat = np.mean(peer_lats)
            avg_lon = np.mean(peer_lons)

        lat = avg_lat + np.random.normal(0, noise_m / 111_000)
        lon = avg_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.7,
            raw_data={
                "peers_tracked": len(self._peer_positions) or 4,
                "formation_coherent": True,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position or peer average + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        # Average position from peers for cross-validation
        if self._peer_positions:
            avg_lat = np.mean([p.latitude for p in self._peer_positions.values()])
            avg_lon = np.mean([p.longitude for p in self._peer_positions.values()])
        else:
            avg_lat = base_lat
            avg_lon = base_lon

        noise_m = 5.0
        lat = avg_lat + np.random.normal(0, noise_m / 111_000)
        lon = avg_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.7,
            raw_data={
                "peers_tracked": len(self._peer_positions),
                "formation_coherent": True,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class RFAnomalyDetectionLayer(NavigationLayer):
    """Layer 16 — RF Signal Anomaly Detection [NOVEL].

    Monitors RF characteristics (SNR, freq drift, timing, amplitude)
    for statistical spoofing signatures. Detects attacks in preparation
    BEFORE position error registers. Early warning system.
    """

    def __init__(self):
        super().__init__(
            layer_id="rfanomaly_l16",
            layer_number=16,
            name="RF Signal Anomaly Detection",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="RF spoofing early warning — detects before position error",
        )
        self._baseline_snr: float = 45.0
        self._snr_history: list[float] = []

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._snr_history = []
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def read(self) -> LayerReading:
        if self._simulated:
            # RF monitoring layer — no position computation
            # Simulate RF environment monitoring
            snr = self._baseline_snr + np.random.normal(0, 2)
            self._snr_history.append(snr)
            if len(self._snr_history) > 100:
                self._snr_history = self._snr_history[-100:]

            # Detect anomalies
            anomaly_detected = False
            if len(self._snr_history) >= 20:
                recent_std = np.std(self._snr_history[-20:])
                if recent_std > 5.0:  # Unusual variation
                    anomaly_detected = True

            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.8,
                raw_data={
                    "snr_db": snr,
                    "freq_drift_hz": np.random.normal(0, 0.1),
                    "timing_jitter_ns": abs(np.random.normal(0, 5)),
                    "anomaly_detected": anomaly_detected,
                    "spoofing_preparation": anomaly_detected,
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass
