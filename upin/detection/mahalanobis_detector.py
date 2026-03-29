"""
Mahalanobis Distance Spoofing Detection — UPIN

Standalone module for detecting GPS spoofing and sensor anomalies using
statistical distance analysis. This is our core patent claim for turning
jamming attacks into targeting intelligence.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.position import Position
from upin.core.layer_base import LayerReading


class AnomalyType(Enum):
    SPOOFING = auto()
    JAMMING = auto()
    MULTIPATH = auto()
    HARDWARE_FAILURE = auto()
    ENVIRONMENTAL = auto()
    UNKNOWN = auto()


@dataclass
class AnomalyDetection:
    """One detected anomaly from Mahalanobis analysis."""
    detection_id: str
    timestamp: float
    anomaly_type: AnomalyType
    mahalanobis_distance: float
    confidence: float
    affected_layers: List[str]
    suspected_source: Optional[Tuple[float, float]] = None  # lat, lon of spoofing source
    severity: float = 0.5  # 0.0-1.0


class MahalanobisDetector:
    """
    Real-time anomaly detection using Mahalanobis distance.

    Builds statistical models of normal sensor behavior and detects
    outliers that indicate spoofing, jamming, or hardware failure.
    """

    def __init__(self, sensitivity: float = 3.0):
        self.sensitivity = sensitivity  # Standard deviations for threshold
        self.detection_threshold = sensitivity ** 2

        self.position_history: List[Position] = []
        self.layer_statistics: Dict[str, Dict] = {}
        self.anomaly_history: List[AnomalyDetection] = []

        # Statistical models
        self.baseline_mean: Optional[np.ndarray] = None
        self.baseline_covariance: Optional[np.ndarray] = None
        self.baseline_samples = 0
        self.min_samples_for_detection = 10

    def update_baseline(self, readings: List[LayerReading]) -> None:
        """Update statistical baseline from normal readings."""
        if len(readings) < 2:
            return

        # Extract position vector
        positions = np.array([
            [r.position.latitude, r.position.longitude] for r in readings
        ])

        if self.baseline_mean is None:
            # Initialize baseline
            self.baseline_mean = np.mean(positions, axis=0)
            if len(positions) > 1:
                self.baseline_covariance = np.cov(positions.T)
            else:
                self.baseline_covariance = np.eye(2) * 1e-6
            self.baseline_samples = len(positions)
        else:
            # Update baseline using exponential moving average
            alpha = min(0.1, 10.0 / (10.0 + self.baseline_samples))

            new_mean = np.mean(positions, axis=0)
            self.baseline_mean = (1 - alpha) * self.baseline_mean + alpha * new_mean

            if len(positions) > 1:
                new_cov = np.cov(positions.T)
                self.baseline_covariance = (1 - alpha) * self.baseline_covariance + alpha * new_cov

            self.baseline_samples += len(positions)

        # Update per-layer statistics
        for reading in readings:
            layer_id = reading.layer_id
            if layer_id not in self.layer_statistics:
                self.layer_statistics[layer_id] = {
                    'positions': [],
                    'confidences': [],
                    'accuracies': []
                }

            stats = self.layer_statistics[layer_id]
            stats['positions'].append([reading.position.latitude, reading.position.longitude])
            stats['confidences'].append(reading.self_confidence)
            stats['accuracies'].append(reading.position.accuracy_m)

            # Keep only recent samples (sliding window)
            max_samples = 100
            for key in stats:
                if len(stats[key]) > max_samples:
                    stats[key] = stats[key][-max_samples:]

    def detect_anomalies(self, readings: List[LayerReading]) -> List[AnomalyDetection]:
        """Detect anomalies in current readings using Mahalanobis distance."""
        anomalies = []

        if (self.baseline_mean is None or
            self.baseline_covariance is None or
            self.baseline_samples < self.min_samples_for_detection):
            return anomalies

        current_time = time.time()

        # Check each reading against baseline
        for reading in readings:
            position_vector = np.array([reading.position.latitude, reading.position.longitude])

            # Calculate Mahalanobis distance
            try:
                diff = position_vector - self.baseline_mean
                inv_cov = np.linalg.inv(self.baseline_covariance + np.eye(2) * 1e-8)
                mahal_distance = float(np.sqrt(diff.T @ inv_cov @ diff))
            except np.linalg.LinAlgError:
                continue  # Skip if covariance is singular

            # Check if anomalous
            if mahal_distance > self.detection_threshold:
                anomaly_type = self._classify_anomaly(reading, mahal_distance)
                confidence = min(0.99, (mahal_distance - self.detection_threshold) / self.detection_threshold)

                anomaly = AnomalyDetection(
                    detection_id=f"anom_{int(current_time*1000)}_{reading.layer_id}",
                    timestamp=current_time,
                    anomaly_type=anomaly_type,
                    mahalanobis_distance=mahal_distance,
                    confidence=confidence,
                    affected_layers=[reading.layer_id],
                    severity=min(1.0, mahal_distance / (self.detection_threshold * 2))
                )

                # Try to locate spoofing source
                if anomaly_type == AnomalyType.SPOOFING:
                    suspected_source = self._estimate_spoofing_source(reading)
                    anomaly.suspected_source = suspected_source

                anomalies.append(anomaly)

        self.anomaly_history.extend(anomalies)
        return anomalies

    def _classify_anomaly(self, reading: LayerReading, distance: float) -> AnomalyType:
        """Classify type of anomaly based on characteristics."""
        layer_id = reading.layer_id

        # GPS-specific anomaly detection
        if layer_id.lower().startswith('gps'):
            if distance > self.detection_threshold * 3:
                return AnomalyType.SPOOFING
            else:
                return AnomalyType.MULTIPATH

        # RF-based layers (WiFi, cellular)
        elif any(rf in layer_id.lower() for rf in ['wifi', 'cellular', 'bluetooth']):
            if reading.self_confidence < 0.3:
                return AnomalyType.JAMMING
            else:
                return AnomalyType.ENVIRONMENTAL

        # IMU/sensor-based
        elif any(sensor in layer_id.lower() for sensor in ['imu', 'accel', 'gyro', 'mag']):
            if distance > self.detection_threshold * 2:
                return AnomalyType.HARDWARE_FAILURE
            else:
                return AnomalyType.ENVIRONMENTAL

        return AnomalyType.UNKNOWN

    def _estimate_spoofing_source(self, reading: LayerReading) -> Optional[Tuple[float, float]]:
        """Estimate location of spoofing source (simplified)."""
        if self.baseline_mean is None:
            return None

        true_lat, true_lon = self.baseline_mean[0], self.baseline_mean[1]
        false_lat, false_lon = reading.position.latitude, reading.position.longitude

        dlat = false_lat - true_lat
        dlon = false_lon - true_lon

        estimated_range = 5000.0
        range_factor = estimated_range / 111320.0

        spoofer_lat = true_lat + dlat * range_factor
        spoofer_lon = true_lon + dlon * range_factor

        return (spoofer_lat, spoofer_lon)

    def get_detection_summary(self) -> Dict:
        """Get summary of recent anomaly detections."""
        recent_time = time.time() - 300
        recent_anomalies = [a for a in self.anomaly_history if a.timestamp > recent_time]

        type_counts: Dict[str, int] = {}
        severity_levels = []

        for anomaly in recent_anomalies:
            type_name = anomaly.anomaly_type.name
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
            severity_levels.append(anomaly.severity)

        return {
            'baseline_samples': self.baseline_samples,
            'detection_threshold': self.detection_threshold,
            'recent_anomalies_5min': len(recent_anomalies),
            'anomaly_types': type_counts,
            'avg_severity': float(np.mean(severity_levels)) if severity_levels else 0.0,
            'max_severity': max(severity_levels) if severity_levels else 0.0,
            'baseline_established': self.baseline_mean is not None
        }
