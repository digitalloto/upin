"""
Sensor Programming & Layer Accuracy Optimization — UPIN

Unified interface for:
1. Configuring any sensor type with calibration parameters
2. Automated layer performance analysis with recommendations
3. Parameter optimization for accuracy improvement
4. RSSI-to-distance path loss model
5. Camera intrinsics calibration

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


# ── Sensor Configuration ──────────────────────────────────────────

class SensorType(Enum):
    GPS = "gps"
    IMU = "imu"
    CAMERA = "camera"
    LIDAR = "lidar"
    RADAR = "radar"
    ULTRASONIC = "ultrasonic"
    BAROMETRIC = "barometric"
    WIFI = "wifi"
    BLUETOOTH = "bluetooth"
    CELLULAR = "cellular"
    AUDIO = "audio"
    CUSTOM = "custom"


@dataclass
class SensorConfig:
    """Full configuration for one sensor."""
    sensor_type: SensorType
    sampling_rate_hz: float
    resolution: Optional[float] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    calibration: Dict[str, float] = field(default_factory=dict)
    filters: Dict[str, Any] = field(default_factory=dict)
    power_mode: str = "normal"  # low, normal, high


class SensorProgrammer:
    """
    Unified interface for configuring any sensor type.
    Stores calibration params, filter settings, and power modes.
    """

    # Default configs per sensor type
    DEFAULTS = {
        SensorType.IMU: SensorConfig(
            sensor_type=SensorType.IMU, sampling_rate_hz=100,
            range_min=-16.0, range_max=16.0,
            calibration={
                "accel_bias_x": 0, "accel_bias_y": 0, "accel_bias_z": 0,
                "gyro_bias_x": 0, "gyro_bias_y": 0, "gyro_bias_z": 0,
                "mag_hard_iron_x": 0, "mag_hard_iron_y": 0, "mag_hard_iron_z": 0,
            },
            filters={"low_pass_hz": 20, "kalman_q": 0.01, "kalman_r": 0.1},
        ),
        SensorType.CAMERA: SensorConfig(
            sensor_type=SensorType.CAMERA, sampling_rate_hz=30,
            resolution=1920 * 1080,
            calibration={
                "fx": 800, "fy": 800, "cx": 960, "cy": 540,
                "k1": 0, "k2": 0, "p1": 0, "p2": 0,
            },
            filters={"auto_exposure": True, "noise_reduction": True},
            power_mode="high",
        ),
        SensorType.LIDAR: SensorConfig(
            sensor_type=SensorType.LIDAR, sampling_rate_hz=10,
            resolution=0.01, range_min=0.1, range_max=100,
            calibration={"range_bias": 0, "angle_offset": 0},
            filters={"outlier_filter": True, "min_intensity": 10},
            power_mode="high",
        ),
        SensorType.WIFI: SensorConfig(
            sensor_type=SensorType.WIFI, sampling_rate_hz=1,
            range_min=-100, range_max=-10,
            calibration={"rssi_offset": 0, "antenna_gain": 0, "path_loss_exp": 2.0},
            filters={"min_rssi": -90, "scan_duration_s": 1.0},
            power_mode="low",
        ),
        SensorType.BAROMETRIC: SensorConfig(
            sensor_type=SensorType.BAROMETRIC, sampling_rate_hz=10,
            calibration={"pressure_offset_hpa": 0, "temperature_offset_c": 0},
        ),
    }

    def __init__(self):
        self._configs: Dict[str, SensorConfig] = {}
        self._callbacks: Dict[str, List[Callable]] = {}

    def configure(self, sensor_id: str, sensor_type: SensorType,
                  overrides: Optional[Dict] = None) -> SensorConfig:
        """Configure a sensor using defaults + optional overrides."""
        cfg = SensorConfig(sensor_type=sensor_type, sampling_rate_hz=1)

        # Start from defaults if available
        if sensor_type in self.DEFAULTS:
            default = self.DEFAULTS[sensor_type]
            cfg = SensorConfig(
                sensor_type=default.sensor_type,
                sampling_rate_hz=default.sampling_rate_hz,
                resolution=default.resolution,
                range_min=default.range_min,
                range_max=default.range_max,
                calibration=dict(default.calibration),
                filters=dict(default.filters),
                power_mode=default.power_mode,
            )

        # Apply overrides
        if overrides:
            for k, v in overrides.items():
                if k == "calibration" and isinstance(v, dict):
                    cfg.calibration.update(v)
                elif k == "filters" and isinstance(v, dict):
                    cfg.filters.update(v)
                elif hasattr(cfg, k):
                    setattr(cfg, k, v)

        self._configs[sensor_id] = cfg
        return cfg

    def get_config(self, sensor_id: str) -> Optional[SensorConfig]:
        return self._configs.get(sensor_id)

    def update_calibration(self, sensor_id: str, cal_params: Dict[str, float]) -> bool:
        cfg = self._configs.get(sensor_id)
        if cfg:
            cfg.calibration.update(cal_params)
            return True
        return False

    def apply_imu_calibration(self, raw: Dict) -> Dict:
        """Apply IMU calibration to raw accelerometer/gyro/mag data."""
        cfg = None
        for c in self._configs.values():
            if c.sensor_type == SensorType.IMU:
                cfg = c
                break
        if not cfg:
            return raw

        cal = cfg.calibration
        result = {}
        if "accelerometer" in raw:
            a = list(raw["accelerometer"])
            a[0] -= cal.get("accel_bias_x", 0)
            a[1] -= cal.get("accel_bias_y", 0)
            a[2] -= cal.get("accel_bias_z", 0)
            result["accelerometer"] = a
        if "gyroscope" in raw:
            g = list(raw["gyroscope"])
            g[0] -= cal.get("gyro_bias_x", 0)
            g[1] -= cal.get("gyro_bias_y", 0)
            g[2] -= cal.get("gyro_bias_z", 0)
            result["gyroscope"] = g
        if "magnetometer" in raw:
            m = list(raw["magnetometer"])
            m[0] -= cal.get("mag_hard_iron_x", 0)
            m[1] -= cal.get("mag_hard_iron_y", 0)
            m[2] -= cal.get("mag_hard_iron_z", 0)
            result["magnetometer"] = m
        return result

    @staticmethod
    def rssi_to_distance(rssi: float, freq_mhz: float,
                          path_loss_exp: float = 2.0,
                          antenna_gain: float = 0.0) -> float:
        """Convert WiFi/BLE RSSI to distance using calibrated path loss model."""
        fspl = 20 * math.log10(freq_mhz) + 20 * math.log10(4 * math.pi / 0.3) - 30
        distance = 10 ** ((fspl - rssi - antenna_gain) / (10 * path_loss_exp))
        return max(0.5, min(1000.0, distance))

    def list_sensors(self) -> List[Dict]:
        return [
            {"id": sid, "type": cfg.sensor_type.value,
             "rate_hz": cfg.sampling_rate_hz, "power": cfg.power_mode}
            for sid, cfg in self._configs.items()
        ]


# ── Accuracy Improvement Engine ───────────────────────────────────

class AccuracyAnalyzer:
    """
    Automated layer performance analysis with recommendations.
    Feed it position history + optional ground truth, get back
    stability, drift, accuracy metrics, and improvement suggestions.
    """

    def analyze(self, positions: List[Tuple[float, float, float]],
                ground_truth: Optional[List[Tuple[float, float, float]]] = None) -> Dict:
        """Analyze positioning accuracy."""
        if len(positions) < 5:
            return {"error": "need 5+ positions"}

        arr = np.array(positions)
        stability = np.std(arr, axis=0)
        stability_m = (stability[0] * 111320, stability[1] * 111320, stability[2])

        # Drift: distance from first to last position
        d_lat = (arr[-1, 0] - arr[0, 0]) * 111320
        d_lon = (arr[-1, 1] - arr[0, 1]) * 111320
        drift_m = math.sqrt(d_lat ** 2 + d_lon ** 2)
        drift_rate = drift_m / (len(positions) * 0.1)  # assuming 10Hz

        result: Dict[str, Any] = {
            "samples": len(positions),
            "stability_lat_m": round(stability_m[0], 2),
            "stability_lon_m": round(stability_m[1], 2),
            "stability_alt_m": round(stability_m[2], 2),
            "drift_total_m": round(drift_m, 2),
            "drift_rate_mps": round(drift_rate, 3),
        }

        # Accuracy vs ground truth
        if ground_truth and len(ground_truth) == len(positions):
            errors = []
            for p, t in zip(positions, ground_truth):
                dlat = (p[0] - t[0]) * 111320
                dlon = (p[1] - t[1]) * 111320 * math.cos(math.radians(p[0]))
                errors.append(math.sqrt(dlat ** 2 + dlon ** 2))
            result["mean_error_m"] = round(float(np.mean(errors)), 2)
            result["rms_error_m"] = round(float(np.sqrt(np.mean(np.square(errors)))), 2)
            result["max_error_m"] = round(float(np.max(errors)), 2)
            result["p95_error_m"] = round(float(np.percentile(errors, 95)), 2)

        # Recommendations
        recs = []
        if max(stability_m[0], stability_m[1]) > 10:
            recs.append("High variance — increase sampling rate or add temporal filter")
        if drift_rate > 1.0:
            recs.append("High drift — implement drift correction or add reference sensor")
        if result.get("mean_error_m", 0) > 10:
            recs.append("High mean error — recalibrate sensors or check for systematic bias")
        if result.get("mean_error_m", 0) > 50:
            recs.append("CRITICAL: error >50m — check for spoofing or hardware failure")
        if not recs:
            recs.append("Performance within acceptable parameters")
        result["recommendations"] = recs

        return result

    def optimize_parameters(self, current_errors: List[float]) -> Dict:
        """Suggest optimized filter parameters based on error distribution."""
        if not current_errors:
            return {}

        err = np.array(current_errors)
        median_err = float(np.median(err))
        std_err = float(np.std(err))

        # Adaptive parameters based on error characteristics
        return {
            "kalman_process_noise": round(max(0.001, std_err * 0.01), 4),
            "kalman_measurement_noise": round(max(0.01, median_err * 0.1), 4),
            "outlier_rejection_sigma": round(max(2.0, min(5.0, 3.0 * std_err / median_err)), 1),
            "temporal_smoothing": round(max(0.05, min(0.5, 1.0 / (1 + median_err))), 3),
            "confidence_threshold": round(max(0.5, min(0.9, 1.0 - median_err / 100)), 2),
            "expected_improvement_pct": round(min(40, std_err / median_err * 20), 0),
        }
