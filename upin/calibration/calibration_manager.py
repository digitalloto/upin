"""
Calibration Manager — UPIN Master Calibration Controller

Coordinates all sensor calibration across the UPIN system:
- Drift compensation for individual sensors
- Reference point matching and calibration
- Environmental corrections (temperature, humidity, pressure)
- Weather condition adjustments
- Calibration scheduling and optimization

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .drift_compensation import DriftCompensator, SensorType
from .reference_points import ReferencePointDatabase, ReferencePoint


@dataclass
class EnvironmentalConditions:
    """Current environmental conditions affecting sensor accuracy."""
    temperature_c: float
    humidity_percent: float
    pressure_hpa: float
    wind_speed_ms: float
    visibility_km: float
    precipitation_mm: float  # rain/snow in last hour
    timestamp: float

    def get_atmospheric_correction(self, sensor_type: SensorType) -> float:
        """Calculate atmospheric correction factor for different sensors."""
        corrections = {
            SensorType.BAROMETRIC: self._barometric_correction(),
            SensorType.WIFI_RSSI: self._rf_atmospheric_correction(),
            SensorType.CELLULAR_RSSI: self._rf_atmospheric_correction(),
            SensorType.GPS: self._gps_atmospheric_correction(),
            SensorType.CAMERA: self._visual_correction(),
        }
        return corrections.get(sensor_type, 0.0)

    def _barometric_correction(self) -> float:
        """Humidity affects barometric pressure readings."""
        # High humidity increases apparent pressure
        return (self.humidity_percent - 50.0) * 0.02

    def _rf_atmospheric_correction(self) -> float:
        """RF signals are affected by humidity and precipitation."""
        base_loss = 0.0
        if self.humidity_percent > 80.0:
            base_loss += (self.humidity_percent - 80.0) * 0.1
        if self.precipitation_mm > 0.1:
            base_loss += self.precipitation_mm * 2.0  # rain attenuation
        return base_loss

    def _gps_atmospheric_correction(self) -> float:
        """GPS affected by ionospheric and tropospheric delays."""
        # Simplified model: higher humidity = more tropospheric delay
        return (self.humidity_percent - 50.0) * 0.05

    def _visual_correction(self) -> float:
        """Visual sensors affected by visibility and precipitation."""
        visibility_factor = max(0.0, (10.0 - self.visibility_km) / 10.0)
        precip_factor = min(1.0, self.precipitation_mm * 0.5)
        return visibility_factor + precip_factor


@dataclass
class CalibrationSession:
    """One calibration session with a reference point."""
    reference_point: ReferencePoint
    sensor_readings: Dict[SensorType, float]
    environmental: EnvironmentalConditions
    success: bool
    error_reduction: float  # improvement in accuracy percentage
    timestamp: float


class CalibrationManager:
    """
    Master coordinator for all UPIN sensor calibration.

    Manages:
    - Individual sensor drift compensation
    - Reference point database
    - Environmental/weather corrections
    - Calibration scheduling and optimization
    - Performance tracking
    """

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._drift_compensator = DriftCompensator(device_id)
        self._reference_db = ReferencePointDatabase()
        self._calibration_history: List[CalibrationSession] = []

        # Calibration settings
        self._auto_calibration_enabled = True
        self._min_calibration_interval_minutes = 15
        self._max_reference_distance_m = 100.0
        self._min_reference_accuracy_m = 5.0

        self._last_calibration_time = 0.0
        self._environmental_cache: Optional[EnvironmentalConditions] = None

    def set_environmental_conditions(self, conditions: EnvironmentalConditions) -> None:
        """Update current environmental conditions."""
        self._environmental_cache = conditions

    def check_for_calibration_opportunity(
        self,
        current_lat: float,
        current_lon: float,
        sensor_readings: Dict[SensorType, float]
    ) -> Optional[CalibrationSession]:
        """
        Check if current position offers a calibration opportunity.
        Returns calibration session if one was performed.
        """
        if not self._auto_calibration_enabled:
            return None

        # Check time since last calibration
        time_since_last = time.time() - self._last_calibration_time
        if time_since_last < (self._min_calibration_interval_minutes * 60):
            return None

        # Find best nearby reference point
        reference = self._reference_db.get_best_reference(
            current_lat, current_lon,
            max_distance_m=self._max_reference_distance_m
        )

        if reference is None or reference.accuracy_m > self._min_reference_accuracy_m:
            return None

        # Perform calibration
        return self._perform_calibration(reference, current_lat, current_lon, sensor_readings)

    def _perform_calibration(
        self,
        reference: ReferencePoint,
        current_lat: float,
        current_lon: float,
        sensor_readings: Dict[SensorType, float]
    ) -> CalibrationSession:
        """Execute calibration against a reference point."""

        # Default environmental conditions if not set
        if self._environmental_cache is None:
            env = EnvironmentalConditions(
                temperature_c=25.0,
                humidity_percent=60.0,
                pressure_hpa=1013.25,
                wind_speed_ms=2.0,
                visibility_km=10.0,
                precipitation_mm=0.0,
                timestamp=time.time()
            )
        else:
            env = self._environmental_cache

        calibration_success = False
        total_error_reduction = 0.0
        calibrations_performed = 0

        # Calibrate each available sensor
        for sensor_type, reading in sensor_readings.items():

            # Get ground truth for this sensor type
            ground_truth = self._get_ground_truth(sensor_type, reference)
            if ground_truth is None:
                continue

            # Apply environmental correction to ground truth
            env_correction = env.get_atmospheric_correction(sensor_type)
            corrected_ground_truth = ground_truth + env_correction

            # Get error before calibration
            old_corrected, old_applied = self._drift_compensator.apply_compensation(
                sensor_type, reading, env.temperature_c
            )
            old_error = abs(old_corrected - corrected_ground_truth) if old_applied else abs(reading - corrected_ground_truth)

            # Add calibration point
            self._drift_compensator.add_calibration_point(
                sensor_type=sensor_type,
                sensor_reading=reading,
                ground_truth=corrected_ground_truth,
                temperature_c=env.temperature_c,
                lat=current_lat,
                lon=current_lon
            )

            # Calculate error reduction
            new_corrected, new_applied = self._drift_compensator.apply_compensation(
                sensor_type, reading, env.temperature_c
            )
            new_error = abs(new_corrected - corrected_ground_truth) if new_applied else abs(reading - corrected_ground_truth)

            if old_error > 0:
                error_reduction = ((old_error - new_error) / old_error) * 100.0
                total_error_reduction += error_reduction
                calibrations_performed += 1
                calibration_success = True

        # Average error reduction
        avg_error_reduction = (total_error_reduction / calibrations_performed) if calibrations_performed > 0 else 0.0

        self._last_calibration_time = time.time()

        session = CalibrationSession(
            reference_point=reference,
            sensor_readings=sensor_readings.copy(),
            environmental=env,
            success=calibration_success,
            error_reduction=avg_error_reduction,
            timestamp=time.time()
        )

        self._calibration_history.append(session)
        return session

    def _get_ground_truth(self, sensor_type: SensorType, reference: ReferencePoint) -> Optional[float]:
        """Get ground truth value for a sensor type from reference point."""
        if sensor_type == SensorType.GPS:
            return reference.lat  # Could be lat or lon depending on context
        elif sensor_type == SensorType.BAROMETRIC:
            return reference.elevation_m  # Elevation in metres
        elif sensor_type in [SensorType.WIFI_RSSI, SensorType.CELLULAR_RSSI]:
            return None  # No fixed ground truth for signal strength
        elif sensor_type == SensorType.MAGNETOMETER:
            return None  # Would need magnetic declination data
        else:
            return None

    def apply_all_compensations(
        self,
        sensor_readings: Dict[SensorType, float]
    ) -> Dict[SensorType, Tuple[float, bool]]:
        """Apply drift compensation to all sensor readings."""

        temperature = 25.0
        if self._environmental_cache:
            temperature = self._environmental_cache.temperature_c

        compensated = {}
        for sensor_type, reading in sensor_readings.items():
            corrected, applied = self._drift_compensator.apply_compensation(
                sensor_type, reading, temperature
            )
            compensated[sensor_type] = (corrected, applied)

        return compensated

    def get_calibration_status(self) -> Dict:
        """Get comprehensive calibration status."""
        drift_stats = self._drift_compensator.get_calibration_stats()

        recent_sessions = [s for s in self._calibration_history if (time.time() - s.timestamp) < 3600]

        status = {
            "device_id": self.device_id,
            "auto_calibration": self._auto_calibration_enabled,
            "last_calibration_ago_minutes": (time.time() - self._last_calibration_time) / 60.0,
            "total_calibration_sessions": len(self._calibration_history),
            "recent_sessions_1h": len(recent_sessions),
            "sensor_drift_stats": drift_stats,
            "environmental_conditions": None,
        }

        if self._environmental_cache:
            status["environmental_conditions"] = {
                "temperature_c": self._environmental_cache.temperature_c,
                "humidity_percent": self._environmental_cache.humidity_percent,
                "pressure_hpa": self._environmental_cache.pressure_hpa,
                "visibility_km": self._environmental_cache.visibility_km,
                "age_minutes": (time.time() - self._environmental_cache.timestamp) / 60.0,
            }

        return status

    def enable_auto_calibration(self, enabled: bool) -> None:
        """Enable or disable automatic calibration."""
        self._auto_calibration_enabled = enabled

    def set_calibration_params(
        self,
        interval_minutes: int = 15,
        max_distance_m: float = 100.0,
        min_accuracy_m: float = 5.0
    ) -> None:
        """Configure calibration parameters."""
        self._min_calibration_interval_minutes = interval_minutes
        self._max_reference_distance_m = max_distance_m
        self._min_reference_accuracy_m = min_accuracy_m

    def get_nearby_references(self, lat: float, lon: float) -> List[ReferencePoint]:
        """Get reference points near current location."""
        return self._reference_db.find_nearby(lat, lon, self._max_reference_distance_m)

    def force_calibration(
        self,
        lat: float,
        lon: float,
        sensor_readings: Dict[SensorType, float]
    ) -> Optional[CalibrationSession]:
        """Force calibration regardless of timing constraints."""
        reference = self._reference_db.get_best_reference(lat, lon, self._max_reference_distance_m)
        if reference is None:
            return None
        return self._perform_calibration(reference, lat, lon, sensor_readings)
