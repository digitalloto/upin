"""
Sensor Drift Compensation — UPIN Calibration Module

Every physical sensor has systematic biases and drift over time.
This module learns each device's specific error patterns and
corrects them in real-time, making UPIN more accurate as it
operates longer.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Dict, List, Optional, Tuple

import numpy as np


class SensorType(Enum):
    GPS = auto()
    IMU_ACCEL = auto()
    IMU_GYRO = auto()
    BAROMETRIC = auto()
    WIFI_RSSI = auto()
    CELLULAR_RSSI = auto()
    MAGNETOMETER = auto()
    CAMERA = auto()
    CLOCK = auto()


@dataclass
class SensorBias:
    """Learned bias parameters for one sensor on one device."""
    sensor_type: SensorType
    device_id: str
    bias_offset: float      # constant offset error
    drift_rate: float       # how much it drifts per hour
    temperature_coeff: float  # temperature dependency
    last_calibrated: float  # timestamp
    samples_count: int      # how many calibration points
    confidence: float       # 0.0-1.0 how reliable this bias estimate is

    def apply_correction(self, raw_value: float, temperature_c: float = 20.0) -> float:
        """Apply learned bias correction to a raw sensor reading."""
        elapsed_hours = (time.time() - self.last_calibrated) / 3600.0
        drift_error = self.drift_rate * elapsed_hours
        temp_error = self.temperature_coeff * (temperature_c - 20.0)
        corrected = raw_value - self.bias_offset - drift_error - temp_error
        return corrected


@dataclass
class CalibrationEvent:
    """One calibration measurement — comparing sensor to ground truth."""
    timestamp: float
    sensor_type: SensorType
    sensor_reading: float
    ground_truth: float
    error: float
    temperature_c: float
    location_lat: float
    location_lon: float


class DriftCompensator:
    """
    Learns and compensates for individual sensor drift patterns.

    Each device gets its own bias profile. As UPIN operates,
    it continuously updates these profiles when it encounters
    known reference points.
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._biases: Dict[SensorType, SensorBias] = {}
        self._calibration_history: List[CalibrationEvent] = []
        self._min_samples_for_confidence = 5

    def get_bias(self, sensor_type: SensorType) -> Optional[SensorBias]:
        """Get current bias parameters for a sensor type."""
        return self._biases.get(sensor_type)

    def apply_compensation(
        self,
        sensor_type: SensorType,
        raw_value: float,
        temperature_c: float = 20.0
    ) -> Tuple[float, bool]:
        """
        Apply drift compensation to a raw sensor reading.
        Returns (corrected_value, compensation_applied).
        """
        bias = self._biases.get(sensor_type)
        if bias is None or bias.confidence < 0.3:
            return raw_value, False

        corrected = bias.apply_correction(raw_value, temperature_c)
        return corrected, True

    def add_calibration_point(
        self,
        sensor_type: SensorType,
        sensor_reading: float,
        ground_truth: float,
        temperature_c: float,
        lat: float,
        lon: float,
    ) -> None:
        """
        Add a calibration measurement when sensor reading
        can be compared to a known ground truth value.
        """
        error = sensor_reading - ground_truth

        event = CalibrationEvent(
            timestamp=time.time(),
            sensor_type=sensor_type,
            sensor_reading=sensor_reading,
            ground_truth=ground_truth,
            error=error,
            temperature_c=temperature_c,
            location_lat=lat,
            location_lon=lon,
        )

        self._calibration_history.append(event)
        self._update_bias_model(sensor_type)

    def _update_bias_model(self, sensor_type: SensorType) -> None:
        """Recalculate bias parameters from calibration history."""
        events = [e for e in self._calibration_history if e.sensor_type == sensor_type]

        if len(events) < 2:
            return

        # Simple linear regression for drift rate
        times = np.array([e.timestamp for e in events])
        errors = np.array([e.error for e in events])
        temps = np.array([e.temperature_c for e in events])

        # Normalize times to hours from first measurement
        times_hours = (times - times[0]) / 3600.0

        # Fit: error = offset + drift_rate * hours + temp_coeff * (temp - 20)
        try:
            # Multi-variable linear regression
            X = np.column_stack([
                np.ones(len(times_hours)),  # constant offset
                times_hours,                 # drift rate
                temps - 20.0                # temperature coefficient
            ])
            coeffs, residuals, rank, s = np.linalg.lstsq(X, errors, rcond=None)

            bias_offset = coeffs[0]
            drift_rate = coeffs[1] if len(coeffs) > 1 else 0.0
            temp_coeff = coeffs[2] if len(coeffs) > 2 else 0.0

            # Calculate confidence based on residuals and sample count
            if len(residuals) > 0 and residuals[0] > 0:
                mse = residuals[0] / len(events)
                confidence = max(0.1, min(0.95, 1.0 / (1.0 + mse)))
            else:
                confidence = 0.5

            # Boost confidence with more samples
            sample_confidence = min(1.0, len(events) / self._min_samples_for_confidence)
            final_confidence = confidence * sample_confidence

            self._biases[sensor_type] = SensorBias(
                sensor_type=sensor_type,
                device_id=self.device_id,
                bias_offset=bias_offset,
                drift_rate=drift_rate,
                temperature_coeff=temp_coeff,
                last_calibrated=time.time(),
                samples_count=len(events),
                confidence=final_confidence,
            )

        except np.linalg.LinAlgError:
            # Fall back to simple mean offset if regression fails
            mean_error = np.mean(errors)
            self._biases[sensor_type] = SensorBias(
                sensor_type=sensor_type,
                device_id=self.device_id,
                bias_offset=mean_error,
                drift_rate=0.0,
                temperature_coeff=0.0,
                last_calibrated=time.time(),
                samples_count=len(events),
                confidence=0.3,
            )

    def get_calibration_stats(self) -> Dict:
        """Return calibration status for all sensors."""
        stats = {}
        for sensor_type, bias in self._biases.items():
            stats[sensor_type.name] = {
                "confidence": bias.confidence,
                "samples": bias.samples_count,
                "bias_offset": bias.bias_offset,
                "drift_rate_per_hour": bias.drift_rate,
                "last_calibrated_ago_hours": (time.time() - bias.last_calibrated) / 3600.0,
            }
        return stats

    def save_to_file(self, filepath: str) -> None:
        """Save calibration data to persistent storage."""
        data = {
            "device_id": self.device_id,
            "biases": {},
            "history": []
        }

        for sensor_type, bias in self._biases.items():
            data["biases"][sensor_type.name] = {
                "bias_offset": bias.bias_offset,
                "drift_rate": bias.drift_rate,
                "temperature_coeff": bias.temperature_coeff,
                "last_calibrated": bias.last_calibrated,
                "samples_count": bias.samples_count,
                "confidence": bias.confidence,
            }

        # Save recent calibration events (last 100)
        recent_events = self._calibration_history[-100:]
        for event in recent_events:
            data["history"].append({
                "timestamp": event.timestamp,
                "sensor_type": event.sensor_type.name,
                "sensor_reading": event.sensor_reading,
                "ground_truth": event.ground_truth,
                "error": event.error,
                "temperature_c": event.temperature_c,
                "location_lat": event.location_lat,
                "location_lon": event.location_lon,
            })

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def load_from_file(self, filepath: str) -> bool:
        """Load calibration data from persistent storage."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            if data.get("device_id") != self.device_id:
                return False

            # Load biases
            for sensor_name, bias_data in data.get("biases", {}).items():
                try:
                    sensor_type = SensorType[sensor_name]
                    self._biases[sensor_type] = SensorBias(
                        sensor_type=sensor_type,
                        device_id=self.device_id,
                        bias_offset=bias_data["bias_offset"],
                        drift_rate=bias_data["drift_rate"],
                        temperature_coeff=bias_data["temperature_coeff"],
                        last_calibrated=bias_data["last_calibrated"],
                        samples_count=bias_data["samples_count"],
                        confidence=bias_data["confidence"],
                    )
                except (KeyError, ValueError):
                    continue

            # Load history
            for event_data in data.get("history", []):
                try:
                    sensor_type = SensorType[event_data["sensor_type"]]
                    event = CalibrationEvent(
                        timestamp=event_data["timestamp"],
                        sensor_type=sensor_type,
                        sensor_reading=event_data["sensor_reading"],
                        ground_truth=event_data["ground_truth"],
                        error=event_data["error"],
                        temperature_c=event_data["temperature_c"],
                        location_lat=event_data["location_lat"],
                        location_lon=event_data["location_lon"],
                    )
                    self._calibration_history.append(event)
                except (KeyError, ValueError):
                    continue

            return True

        except (FileNotFoundError, json.JSONDecodeError):
            return False
