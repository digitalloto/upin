"""
Fusion Microservices Architecture — UPIN

Each fusion algorithm runs as an independent service/agent with
configurable parameters. Services can be scaled independently,
tuned for specific environments, and provide fault isolation.

This implements a microservices pattern for positioning algorithms.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import auto, Enum
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from upin.core.position import Position
from upin.core.layer_base import LayerReading


class ServiceStatus(Enum):
    STARTING = auto()
    RUNNING = auto()
    DEGRADED = auto()
    FAILED = auto()
    STOPPED = auto()


@dataclass
class ServiceConfig:
    """Configuration for a fusion microservice."""
    service_id: str
    algorithm_name: str
    parameters: Dict[str, Any]
    priority: int = 1          # 1=low, 5=high priority
    max_instances: int = 1     # How many instances to run
    timeout_ms: float = 500    # Max processing time
    memory_limit_mb: int = 100
    cpu_limit_percent: int = 25
    environment_tags: List[str] = field(default_factory=list)  # urban, rural, maritime, etc.


@dataclass
class ServiceResult:
    """Result from a fusion microservice."""
    service_id: str
    instance_id: str
    algorithm_name: str
    position: Position
    confidence: float
    processing_time_ms: float
    parameters_used: Dict[str, Any]
    reasoning: str
    success: bool
    error_message: Optional[str] = None


class FusionMicroservice(ABC):
    """Base class for fusion algorithm microservices."""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.service_id = config.service_id
        self.instance_id = str(uuid.uuid4())[:8]
        self.status = ServiceStatus.STARTING
        self.start_time = time.time()
        self.request_count = 0
        self.success_count = 0

    @abstractmethod
    def process_readings(self, readings: List[LayerReading]) -> ServiceResult:
        """Process sensor readings and return position."""
        pass

    def get_health_status(self) -> Dict[str, Any]:
        """Return service health information."""
        uptime = time.time() - self.start_time
        success_rate = self.success_count / max(self.request_count, 1)

        return {
            "service_id": self.service_id,
            "instance_id": self.instance_id,
            "status": self.status.name,
            "uptime_seconds": uptime,
            "request_count": self.request_count,
            "success_rate": success_rate,
            "algorithm": self.config.algorithm_name,
            "priority": self.config.priority,
            "parameters": self.config.parameters
        }

    def update_parameters(self, new_params: Dict[str, Any]) -> bool:
        """Update service parameters dynamically."""
        try:
            self.config.parameters.update(new_params)
            return True
        except Exception:
            return False


class KalmanMicroservice(FusionMicroservice):
    """Kalman Filter as a microservice."""

    def process_readings(self, readings: List[LayerReading]) -> ServiceResult:
        start_time = time.time()
        self.request_count += 1

        try:
            # Get parameters from config
            process_noise = self.config.parameters.get('process_noise', 0.1)
            measurement_noise = self.config.parameters.get('measurement_noise', 1.0)
            min_readings = self.config.parameters.get('min_readings', 2)

            if len(readings) < min_readings:
                return self._error_result(f"Need at least {min_readings} readings", start_time)

            # Kalman fusion with configurable parameters
            total_weight = 0.0
            weighted_lat = 0.0
            weighted_lon = 0.0

            for reading in readings:
                # Weight based on confidence and noise parameters
                noise_factor = measurement_noise / max(reading.position.accuracy_m, 0.1)
                weight = reading.self_confidence * noise_factor
                weighted_lat += reading.position.latitude * weight
                weighted_lon += reading.position.longitude * weight
                total_weight += weight

            if total_weight == 0:
                return self._error_result("Zero total weight", start_time)

            final_lat = weighted_lat / total_weight
            final_lon = weighted_lon / total_weight

            # Accuracy calculation with process noise
            base_accuracy = self._calculate_accuracy(readings, final_lat, final_lon)
            final_accuracy = base_accuracy + process_noise

            confidence = min(0.98, total_weight / len(readings))

            processing_time = (time.time() - start_time) * 1000

            position = Position(
                latitude=final_lat,
                longitude=final_lon,
                accuracy_m=final_accuracy,
            )

            self.success_count += 1
            self.status = ServiceStatus.RUNNING

            return ServiceResult(
                service_id=self.service_id,
                instance_id=self.instance_id,
                algorithm_name="Kalman_Filter",
                position=position,
                confidence=confidence,
                processing_time_ms=processing_time,
                parameters_used=self.config.parameters.copy(),
                reasoning=f"Kalman fusion with process_noise={process_noise}, measurement_noise={measurement_noise}",
                success=True
            )

        except Exception as e:
            return self._error_result(str(e), start_time)

    def _calculate_accuracy(self, readings: List[LayerReading], lat: float, lon: float) -> float:
        """Calculate position accuracy."""
        if len(readings) < 2:
            return 20.0

        distances = []
        for reading in readings:
            dlat = (reading.position.latitude - lat) * 111320
            dlon = (reading.position.longitude - lon) * 111320 * np.cos(np.radians(lat))
            dist = np.sqrt(dlat**2 + dlon**2)
            distances.append(dist)

        return max(3.0, float(np.std(distances) * 2.0))

    def _error_result(self, error: str, start_time: float) -> ServiceResult:
        """Create error result."""
        self.status = ServiceStatus.DEGRADED
        processing_time = (time.time() - start_time) * 1000

        return ServiceResult(
            service_id=self.service_id,
            instance_id=self.instance_id,
            algorithm_name="Kalman_Filter",
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0,
            processing_time_ms=processing_time,
            parameters_used=self.config.parameters.copy(),
            reasoning=f"Kalman service error: {error}",
            success=False,
            error_message=error
        )


class ParticleMicroservice(FusionMicroservice):
    """Particle Filter as a microservice."""

    def process_readings(self, readings: List[LayerReading]) -> ServiceResult:
        start_time = time.time()
        self.request_count += 1

        try:
            # Configurable parameters
            num_particles = self.config.parameters.get('num_particles', 1000)
            convergence_threshold = self.config.parameters.get('convergence_threshold', 0.8)
            resampling_enabled = self.config.parameters.get('resampling', True)

            if not readings:
                return self._error_result("No readings provided", start_time)

            # Initialize particles around best reading
            base_reading = max(readings, key=lambda r: r.self_confidence)
            base_lat = base_reading.position.latitude
            base_lon = base_reading.position.longitude

            # Particle spread based on accuracy
            spread = base_reading.position.accuracy_m / 111320  # Convert to degrees
            particles_lat = np.random.normal(base_lat, spread, num_particles)
            particles_lon = np.random.normal(base_lon, spread, num_particles)

            # Calculate weights
            weights = np.ones(num_particles)

            for reading in readings:
                for i in range(num_particles):
                    dlat = (particles_lat[i] - reading.position.latitude) * 111320
                    dlon = (particles_lon[i] - reading.position.longitude) * 111320 * np.cos(np.radians(base_lat))
                    dist = np.sqrt(dlat**2 + dlon**2)

                    sigma = reading.position.accuracy_m
                    weight = reading.self_confidence * np.exp(-(dist**2) / (2 * sigma**2))
                    weights[i] *= weight

            # Normalize weights
            if np.sum(weights) > 0:
                weights /= np.sum(weights)
            else:
                weights.fill(1.0 / num_particles)

            # Resampling if enabled and needed
            if resampling_enabled:
                effective_particles = 1.0 / np.sum(weights**2)
                if effective_particles < (num_particles * convergence_threshold):
                    # Resample particles
                    indices = np.random.choice(num_particles, num_particles, p=weights)
                    particles_lat = particles_lat[indices]
                    particles_lon = particles_lon[indices]
                    weights.fill(1.0 / num_particles)

            # Final position
            final_lat = float(np.average(particles_lat, weights=weights))
            final_lon = float(np.average(particles_lon, weights=weights))

            # Accuracy from particle spread
            weighted_var_lat = np.average((particles_lat - final_lat)**2, weights=weights)
            weighted_var_lon = np.average((particles_lon - final_lon)**2, weights=weights)
            accuracy = float(np.sqrt((weighted_var_lat + weighted_var_lon) / 2) * 111320)

            # Confidence from weight concentration
            effective_particles = 1.0 / np.sum(weights**2)
            confidence = min(0.95, effective_particles / num_particles)

            processing_time = (time.time() - start_time) * 1000

            position = Position(
                latitude=final_lat,
                longitude=final_lon,
                accuracy_m=max(2.0, accuracy),
            )

            self.success_count += 1
            self.status = ServiceStatus.RUNNING

            return ServiceResult(
                service_id=self.service_id,
                instance_id=self.instance_id,
                algorithm_name="Particle_Filter",
                position=position,
                confidence=confidence,
                processing_time_ms=processing_time,
                parameters_used=self.config.parameters.copy(),
                reasoning=f"Particle filter: {num_particles} particles, resampling={resampling_enabled}",
                success=True
            )

        except Exception as e:
            return self._error_result(str(e), start_time)

    def _error_result(self, error: str, start_time: float) -> ServiceResult:
        self.status = ServiceStatus.FAILED
        processing_time = (time.time() - start_time) * 1000

        return ServiceResult(
            service_id=self.service_id,
            instance_id=self.instance_id,
            algorithm_name="Particle_Filter",
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0,
            processing_time_ms=processing_time,
            parameters_used=self.config.parameters.copy(),
            reasoning=f"Particle service error: {error}",
            success=False,
            error_message=error
        )


class ServiceOrchestrator:
    """Orchestrates multiple fusion microservices."""

    def __init__(self):
        self.services: Dict[str, FusionMicroservice] = {}
        self.service_configs: Dict[str, ServiceConfig] = {}
        self.executor = ThreadPoolExecutor(max_workers=10)

    def register_service(self, config: ServiceConfig, service_class) -> str:
        """Register a new fusion service."""
        service = service_class(config)
        self.services[config.service_id] = service
        self.service_configs[config.service_id] = config
        return config.service_id

    def process_parallel(self, readings: List[LayerReading], timeout_s: float = 2.0) -> List[ServiceResult]:
        """Process readings across all services in parallel."""
        if not self.services:
            return []

        # Submit all services
        future_to_service = {}
        for service_id, service in self.services.items():
            if service.status in [ServiceStatus.RUNNING, ServiceStatus.STARTING]:
                future = self.executor.submit(service.process_readings, readings)
                future_to_service[future] = service_id

        # Collect results with timeout
        results = []
        for future in as_completed(future_to_service, timeout=timeout_s):
            try:
                result = future.result(timeout=0.1)
                results.append(result)
            except Exception:
                continue

        return results

    def get_best_result(self, results: List[ServiceResult]) -> Optional[ServiceResult]:
        """Select best result from parallel services."""
        if not results:
            return None

        # Filter successful results
        successful = [r for r in results if r.success]
        if not successful:
            return None

        # Score results
        scored = []
        for result in successful:
            service_config = self.service_configs.get(result.service_id)
            priority_bonus = service_config.priority * 0.1 if service_config else 0.0

            score = (
                result.confidence * 0.4 +
                max(0.0, 1.0 - result.position.accuracy_m / 100.0) * 0.3 +
                max(0.0, 1.0 - result.processing_time_ms / 1000.0) * 0.2 +
                priority_bonus * 0.1
            )
            scored.append((score, result))

        # Return highest scoring
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def update_service_params(self, service_id: str, new_params: Dict[str, Any]) -> bool:
        """Update parameters for a specific service."""
        service = self.services.get(service_id)
        if service:
            return service.update_parameters(new_params)
        return False

    def get_system_health(self) -> Dict[str, Any]:
        """Get health status of all services."""
        health = {
            "total_services": len(self.services),
            "services": {}
        }

        status_counts = {}
        for service in self.services.values():
            status = service.status.name
            status_counts[status] = status_counts.get(status, 0) + 1
            health["services"][service.service_id] = service.get_health_status()

        health["status_summary"] = status_counts
        return health
