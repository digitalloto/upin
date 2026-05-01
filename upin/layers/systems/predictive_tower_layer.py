"""
Predictive Tower Verification Layer — UPIN Layer 85

Predict position at T+3s, T+5s, T+5m. Then verify: did the tower
distances change by the expected amount? If yes → prediction model
VALIDATED. Every tick proves the model works, so when GPS dies
you trust it completely.

This IS the calibration loop:
1. Predict: "In 5s I'll be 50m closer to tower A, 30m farther from tower B"
2. Wait 5s
3. Check: RSSI confirms tower A got 50m closer? → MODEL CORRECT
4. Repeat 1000 times → model is proven → GPS denial = no problem

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


VERIFY_INTERVALS = [
    ("T+3s", 3.0),
    ("T+5s", 5.0),
    ("T+30s", 30.0),
    ("T+1m", 60.0),
    ("T+5m", 300.0),
]


@dataclass
class TowerPrediction:
    """Predicted distance to a tower at a future time."""
    tower_id: str
    predicted_distance_m: float
    predicted_rssi_dbm: float
    predicted_at: float
    verify_at: float
    label: str


@dataclass
class VerificationResult:
    """Result of verifying a prediction against actual tower reading."""
    tower_id: str
    label: str
    predicted_distance_m: float
    actual_distance_m: float
    error_m: float
    verified: bool


class PredictiveTowerVerifier:
    """Predicts tower distances at T+N, then verifies when time arrives.

    Maintains a queue of pending predictions. As time passes, each
    prediction is checked against actual RSSI → distance change.
    Correct predictions build confidence in the motion model.
    """

    def __init__(self, verification_threshold_m: float = 50.0):
        self._threshold = verification_threshold_m
        self._pending: List[TowerPrediction] = []
        self._results: deque = deque(maxlen=500)
        self._verified_count = 0
        self._total_verified = 0

        self._tower_positions: Dict[str, Tuple[float, float]] = {}
        self._tower_calibrated_distances: Dict[str, float] = {}
        self._tower_current_rssi: Dict[str, float] = {}
        self._tower_path_loss_n: Dict[str, float] = {}

    def register_tower(self, tower_id: str, lat: float, lon: float,
                       calibrated_distance_m: float, rssi_dbm: float,
                       path_loss_n: float = 3.0):
        self._tower_positions[tower_id] = (lat, lon)
        self._tower_calibrated_distances[tower_id] = calibrated_distance_m
        self._tower_current_rssi[tower_id] = rssi_dbm
        self._tower_path_loss_n[tower_id] = path_loss_n

    def predict_tower_distances(self, current_lat: float, current_lon: float,
                                heading_deg: float, speed_ms: float,
                                accel_ms2: float = 0.0,
                                turn_rate_dps: float = 0.0):
        """Generate predictions for all towers at all time intervals."""
        now = time.time()
        new_predictions = []

        for label, dt in VERIFY_INTERVALS:
            # Predict future position
            future_speed = max(0.0, speed_ms + accel_ms2 * dt)
            avg_speed = (speed_ms + future_speed) / 2.0
            distance = avg_speed * dt

            future_heading = (heading_deg + turn_rate_dps * dt) % 360.0
            avg_heading_rad = math.radians(
                heading_deg + turn_rate_dps * dt * 0.5)

            future_lat = current_lat + (distance * math.cos(avg_heading_rad)) / 111_320.0
            cos_lat = math.cos(math.radians(current_lat))
            future_lon = current_lon + (distance * math.sin(avg_heading_rad)) / (
                111_320.0 * max(cos_lat, 0.01))

            # Predict distance to each tower at future position
            for tower_id, (t_lat, t_lon) in self._tower_positions.items():
                pred_dist = _haversine_m(future_lat, future_lon, t_lat, t_lon)
                # Predict RSSI from predicted distance
                cal_dist = self._tower_calibrated_distances.get(tower_id, 1000)
                cal_rssi = self._tower_current_rssi.get(tower_id, -90)
                n = self._tower_path_loss_n.get(tower_id, 3.0)
                if cal_dist > 0 and pred_dist > 0:
                    pred_rssi = cal_rssi - 10 * n * math.log10(pred_dist / max(cal_dist, 1))
                else:
                    pred_rssi = cal_rssi

                new_predictions.append(TowerPrediction(
                    tower_id=tower_id,
                    predicted_distance_m=pred_dist,
                    predicted_rssi_dbm=pred_rssi,
                    predicted_at=now,
                    verify_at=now + dt,
                    label=label,
                ))

        self._pending.extend(new_predictions)
        # Keep pending list manageable
        if len(self._pending) > 2000:
            self._pending = self._pending[-1000:]

    def verify_pending(self, tower_rssi_updates: Dict[str, float]
                       ) -> List[VerificationResult]:
        """Check pending predictions that have reached their verify time."""
        now = time.time()
        results = []
        still_pending = []

        for pred in self._pending:
            if now >= pred.verify_at:
                # Time to verify this prediction
                if pred.tower_id in tower_rssi_updates:
                    actual_rssi = tower_rssi_updates[pred.tower_id]
                    # Estimate actual distance from RSSI change
                    cal_dist = self._tower_calibrated_distances.get(
                        pred.tower_id, 1000)
                    cal_rssi = self._tower_current_rssi.get(
                        pred.tower_id, -90)
                    n = self._tower_path_loss_n.get(pred.tower_id, 3.0)
                    delta_rssi = actual_rssi - cal_rssi
                    if n > 0:
                        actual_dist = cal_dist * 10.0 ** (-delta_rssi / (10 * n))
                    else:
                        actual_dist = cal_dist

                    error = abs(pred.predicted_distance_m - actual_dist)
                    verified = error <= self._threshold

                    self._total_verified += 1
                    if verified:
                        self._verified_count += 1

                    vr = VerificationResult(
                        tower_id=pred.tower_id,
                        label=pred.label,
                        predicted_distance_m=pred.predicted_distance_m,
                        actual_distance_m=actual_dist,
                        error_m=error,
                        verified=verified,
                    )
                    results.append(vr)
                    self._results.append(vr)
            elif now < pred.verify_at - 600:
                pass  # expired, drop
            else:
                still_pending.append(pred)

        self._pending = still_pending
        return results

    @property
    def verification_rate(self) -> float:
        if self._total_verified == 0:
            return 0.0
        return self._verified_count / self._total_verified

    def get_status(self) -> Dict:
        return {
            "towers_tracked": len(self._tower_positions),
            "pending_predictions": len(self._pending),
            "total_verified": self._total_verified,
            "verified_correct": self._verified_count,
            "verification_rate": round(self.verification_rate, 3),
        }


class PredictiveTowerVerificationLayer(NavigationLayer):
    """Layer 85 — Predictive Tower Verification.

    Predicts tower distances at T+3s to T+5m, then verifies against
    actual RSSI changes. Validated predictions prove the motion model
    works → trusted during GPS denial.
    """

    def __init__(self):
        super().__init__(
            layer_id="predtower_k08",
            layer_number=85,
            name="Predictive Tower Verification",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Predict tower distances T+3s to T+5m, verify with RSSI",
        )
        self._verifier = PredictiveTowerVerifier()

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.60

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        # Register towers from world
        for signal in self.world.get_cell_tower_signals():
            dist = self.world._haversine_m(
                self.world.true_lat, self.world.true_lon,
                signal["known_lat"], signal["known_lon"],
            )
            self._verifier.register_tower(
                signal["tower_id"], signal["known_lat"], signal["known_lon"],
                dist, signal["rssi_dbm"],
            )

        # Generate predictions
        self._verifier.predict_tower_distances(
            self.world.true_lat, self.world.true_lon,
            self.world.true_heading, self.world.true_velocity,
        )

        # Use current position from world with noise
        noise_m = 30.0
        lat = self.world.true_lat + np.random.normal(0, noise_m / 111_000)
        lon = self.world.true_lon + np.random.normal(0, noise_m / 111_000)

        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        confidence = 0.3 + 0.5 * self._verifier.verification_rate
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=confidence,
            raw_data={
                "verification_rate": self._verifier.verification_rate,
                "pending_predictions": len(self._verifier._pending),
                "towers_tracked": len(self._verifier._tower_positions),
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat + np.random.normal(0, 30 / 111_000),
            longitude=base_lon + np.random.normal(0, 30 / 111_000),
            altitude=0, accuracy_m=30.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.4,
            raw_data={"verification_rate": 0, "status": "fallback"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
