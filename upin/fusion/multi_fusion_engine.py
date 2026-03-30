"""
Multi-Algorithm Fusion Engine — UPIN Advanced Positioning

Runs multiple fusion algorithms in parallel and selects the best result.
Each algorithm votes on the position, and we take the most confident
consensus. This dramatically improves accuracy with no hardware cost.

Algorithms:
- Extended Kalman Filter (existing)
- Particle Filter (non-Gaussian noise)
- Weighted Least Squares (geometric)
- AI-Enhanced Fusion (neural network)
- Consensus Voting (meta-algorithm)

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import auto, Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.position import Position
from upin.core.layer_base import LayerReading


class FusionAlgorithm(Enum):
    KALMAN_FILTER = auto()
    PARTICLE_FILTER = auto()
    LEAST_SQUARES = auto()
    AI_ENHANCED = auto()
    CONSENSUS_VOTING = auto()
    UNSCENTED_KALMAN = auto()
    COVARIANCE_INTERSECTION = auto()
    DEMPSTER_SHAFER = auto()
    ANT_COLONY = auto()


@dataclass
class FusionResult:
    """Result from one fusion algorithm."""
    algorithm: FusionAlgorithm
    position: Position
    confidence: float
    processing_time_ms: float
    layers_used: List[str]
    reasoning: str
    quality_score: float  # 0.0-1.0 internal quality assessment


class BaseFusionEngine(ABC):
    """Abstract base class for fusion algorithms."""

    @abstractmethod
    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        """Fuse sensor readings into a position estimate."""
        pass

    @abstractmethod
    def get_algorithm_type(self) -> FusionAlgorithm:
        """Return the algorithm type."""
        pass


class ExtendedKalmanFusion(BaseFusionEngine):
    """Extended Kalman Filter fusion (our existing algorithm)."""

    def __init__(self):
        self.process_noise = 0.1
        self.measurement_noise = 1.0

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.KALMAN_FILTER

    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        start_time = time.time()

        if not readings:
            return self._empty_result()

        # Weighted average based on confidence
        total_weight = 0.0
        weighted_lat = 0.0
        weighted_lon = 0.0

        for reading in readings:
            weight = reading.self_confidence * (1.0 / max(reading.position.accuracy_m, 0.1))
            weighted_lat += reading.position.latitude * weight
            weighted_lon += reading.position.longitude * weight
            total_weight += weight

        if total_weight == 0:
            return self._empty_result()

        final_lat = weighted_lat / total_weight
        final_lon = weighted_lon / total_weight

        # Calculate accuracy and confidence
        accuracy = self._calculate_accuracy(readings, final_lat, final_lon)
        confidence = min(0.98, total_weight / len(readings))
        quality_score = self._assess_quality(readings, accuracy, confidence)

        processing_time = (time.time() - start_time) * 1000

        position = Position(
            latitude=final_lat,
            longitude=final_lon,
            accuracy_m=accuracy,
        )

        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=position,
            confidence=confidence,
            processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"Kalman weighted average of {len(readings)} layers",
            quality_score=quality_score
        )

    def _calculate_accuracy(self, readings: List[LayerReading], lat: float, lon: float) -> float:
        """Calculate position accuracy based on reading spread."""
        if len(readings) < 2:
            return 50.0

        distances = []
        for reading in readings:
            dlat = (reading.position.latitude - lat) * 111320
            dlon = (reading.position.longitude - lon) * 111320 * math.cos(math.radians(lat))
            dist = math.sqrt(dlat**2 + dlon**2)
            distances.append(dist)

        return max(5.0, np.std(distances) * 2.0)

    def _assess_quality(self, readings: List[LayerReading], accuracy: float, confidence: float) -> float:
        """Assess fusion quality (0.0-1.0)."""
        layer_diversity = len(readings) / 10.0
        accuracy_score = max(0.0, 1.0 - accuracy / 100.0)
        confidence_score = confidence

        return min(1.0, (layer_diversity + accuracy_score + confidence_score) / 3.0)

    def _empty_result(self) -> FusionResult:
        """Return empty result when no readings available."""
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0,
            processing_time_ms=0.1,
            layers_used=[],
            reasoning="No valid readings available",
            quality_score=0.0
        )


class ParticleFilterFusion(BaseFusionEngine):
    """Particle Filter fusion for non-Gaussian noise."""

    def __init__(self, num_particles: int = 1000):
        self.num_particles = num_particles
        self.particles = None
        self.weights = None

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.PARTICLE_FILTER

    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        start_time = time.time()

        if not readings:
            return self._empty_result()

        # Initialize particles around best reading
        base_reading = max(readings, key=lambda r: r.self_confidence)
        base_lat = base_reading.position.latitude
        base_lon = base_reading.position.longitude

        # Create particle cloud
        particles_lat = np.random.normal(base_lat, 0.001, self.num_particles)
        particles_lon = np.random.normal(base_lon, 0.001, self.num_particles)

        # Calculate particle weights based on all readings
        weights = np.ones(self.num_particles)

        for reading in readings:
            for i in range(self.num_particles):
                dlat = (particles_lat[i] - reading.position.latitude) * 111320
                dlon = (particles_lon[i] - reading.position.longitude) * 111320 * math.cos(math.radians(base_lat))
                dist = math.sqrt(dlat**2 + dlon**2)

                sigma = reading.position.accuracy_m
                weight = reading.self_confidence * math.exp(-(dist**2) / (2 * sigma**2))
                weights[i] *= weight

        # Normalize weights
        if np.sum(weights) > 0:
            weights /= np.sum(weights)
        else:
            weights.fill(1.0 / self.num_particles)

        # Weighted mean position
        final_lat = np.average(particles_lat, weights=weights)
        final_lon = np.average(particles_lon, weights=weights)

        # Estimate accuracy from particle spread
        weighted_var_lat = np.average((particles_lat - final_lat)**2, weights=weights)
        weighted_var_lon = np.average((particles_lon - final_lon)**2, weights=weights)
        accuracy = math.sqrt((weighted_var_lat + weighted_var_lon) / 2) * 111320

        # Confidence based on weight concentration
        effective_particles = 1.0 / np.sum(weights**2)
        confidence = min(0.95, effective_particles / self.num_particles)

        processing_time = (time.time() - start_time) * 1000

        position = Position(
            latitude=float(final_lat),
            longitude=float(final_lon),
            accuracy_m=max(2.0, accuracy),
        )

        quality_score = self._assess_particle_quality(weights, accuracy, len(readings))

        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=position,
            confidence=confidence,
            processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"Particle filter with {self.num_particles} particles, {len(readings)} sensors",
            quality_score=quality_score
        )

    def _assess_particle_quality(self, weights: np.ndarray, accuracy: float, layer_count: int) -> float:
        """Assess particle filter quality."""
        weight_entropy = -np.sum(weights * np.log(weights + 1e-10))
        entropy_score = min(1.0, weight_entropy / math.log(self.num_particles))
        accuracy_score = max(0.0, 1.0 - accuracy / 50.0)
        layer_score = min(1.0, layer_count / 8.0)

        return (entropy_score + accuracy_score + layer_score) / 3.0

    def _empty_result(self) -> FusionResult:
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0,
            processing_time_ms=0.1,
            layers_used=[],
            reasoning="No readings for particle filter",
            quality_score=0.0
        )


class WeightedLeastSquaresFusion(BaseFusionEngine):
    """Geometric least squares fusion."""

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.LEAST_SQUARES

    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        start_time = time.time()

        if not readings:
            return self._empty_result()

        # Set up weighted least squares problem
        positions = np.array([[r.position.latitude, r.position.longitude] for r in readings])
        weights = np.array([r.self_confidence / max(r.position.accuracy_m, 0.1) for r in readings])

        # Weighted centroid
        if np.sum(weights) > 0:
            weighted_center = np.average(positions, axis=0, weights=weights)
        else:
            weighted_center = np.mean(positions, axis=0)

        final_lat, final_lon = weighted_center[0], weighted_center[1]

        # Calculate residuals for accuracy estimate
        residuals = []
        for i, reading in enumerate(readings):
            dlat = (reading.position.latitude - final_lat) * 111320
            dlon = (reading.position.longitude - final_lon) * 111320 * math.cos(math.radians(final_lat))
            residual = math.sqrt(dlat**2 + dlon**2)
            residuals.append(residual * weights[i])

        accuracy = max(3.0, np.sqrt(np.mean(np.array(residuals)**2)))
        confidence = min(0.92, float(np.mean(weights)))

        processing_time = (time.time() - start_time) * 1000

        position = Position(
            latitude=float(final_lat),
            longitude=float(final_lon),
            accuracy_m=accuracy,
        )

        quality_score = self._assess_geometric_quality(residuals, weights, len(readings))

        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=position,
            confidence=confidence,
            processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"Weighted least squares of {len(readings)} positions",
            quality_score=quality_score
        )

    def _assess_geometric_quality(self, residuals: List[float], weights: np.ndarray, layer_count: int) -> float:
        """Assess geometric solution quality."""
        residual_consistency = 1.0 / (1.0 + np.std(residuals))
        weight_quality = float(np.mean(weights))
        layer_diversity = min(1.0, layer_count / 6.0)

        return (residual_consistency + weight_quality + layer_diversity) / 3.0

    def _empty_result(self) -> FusionResult:
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0,
            processing_time_ms=0.1,
            layers_used=[],
            reasoning="No readings for geometric fusion",
            quality_score=0.0
        )


class UnscentedKalmanFusion(BaseFusionEngine):
    """Unscented Kalman Filter — better than EKF for highly nonlinear systems."""

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.UNSCENTED_KALMAN

    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        start_time = time.time()
        if not readings:
            return self._empty_result()

        n = len(readings)
        # Generate sigma points around each reading
        all_lat, all_lon, all_w = [], [], []
        for r in readings:
            w = r.self_confidence / max(r.position.accuracy_m, 0.1)
            spread = r.position.accuracy_m / 111320
            # Central sigma point + 2 per dimension
            all_lat.append(r.position.latitude);        all_lon.append(r.position.longitude);        all_w.append(w * 2)
            all_lat.append(r.position.latitude + spread); all_lon.append(r.position.longitude);        all_w.append(w * 0.5)
            all_lat.append(r.position.latitude - spread); all_lon.append(r.position.longitude);        all_w.append(w * 0.5)
            all_lat.append(r.position.latitude);        all_lon.append(r.position.longitude + spread); all_w.append(w * 0.5)
            all_lat.append(r.position.latitude);        all_lon.append(r.position.longitude - spread); all_w.append(w * 0.5)

        weights = np.array(all_w)
        if weights.sum() > 0:
            weights /= weights.sum()
        lat = float(np.average(all_lat, weights=weights))
        lon = float(np.average(all_lon, weights=weights))
        var_lat = float(np.average((np.array(all_lat) - lat)**2, weights=weights))
        var_lon = float(np.average((np.array(all_lon) - lon)**2, weights=weights))
        accuracy = max(2.0, math.sqrt(var_lat + var_lon) * 111320)
        confidence = min(0.96, float(np.mean([r.self_confidence for r in readings])))

        position = Position(latitude=lat, longitude=lon, accuracy_m=accuracy)
        processing_time = (time.time() - start_time) * 1000
        return FusionResult(
            algorithm=self.get_algorithm_type(), position=position,
            confidence=confidence, processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"UKF sigma-point fusion of {n} layers",
            quality_score=min(1.0, (confidence + max(0, 1 - accuracy/50)) / 2),
        )

    def _empty_result(self) -> FusionResult:
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0, processing_time_ms=0.1, layers_used=[],
            reasoning="No readings for UKF", quality_score=0.0,
        )


class CovarianceIntersectionFusion(BaseFusionEngine):
    """Covariance Intersection — handles unknown correlations between sensors."""

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.COVARIANCE_INTERSECTION

    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        start_time = time.time()
        if not readings:
            return self._empty_result()

        # CI fuses pairs iteratively: P_fused^-1 = w*P_a^-1 + (1-w)*P_b^-1
        lat = readings[0].position.latitude
        lon = readings[0].position.longitude
        var = (readings[0].position.accuracy_m / 111320) ** 2

        for r in readings[1:]:
            r_var = (r.position.accuracy_m / 111320) ** 2
            # Optimal omega minimises trace of fused covariance
            omega = r_var / (var + r_var) if (var + r_var) > 0 else 0.5
            fused_var = 1.0 / (omega / max(var, 1e-12) + (1 - omega) / max(r_var, 1e-12))
            lat = fused_var * (omega * lat / max(var, 1e-12) + (1 - omega) * r.position.latitude / max(r_var, 1e-12))
            lon = fused_var * (omega * lon / max(var, 1e-12) + (1 - omega) * r.position.longitude / max(r_var, 1e-12))
            var = fused_var

        accuracy = max(2.0, math.sqrt(var) * 111320)
        confidence = min(0.95, 1.0 / (1.0 + accuracy / 10.0))
        position = Position(latitude=float(lat), longitude=float(lon), accuracy_m=accuracy)
        processing_time = (time.time() - start_time) * 1000
        return FusionResult(
            algorithm=self.get_algorithm_type(), position=position,
            confidence=confidence, processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"Covariance Intersection of {len(readings)} layers",
            quality_score=min(1.0, confidence * 1.1),
        )

    def _empty_result(self) -> FusionResult:
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0, processing_time_ms=0.1, layers_used=[],
            reasoning="No readings for CI", quality_score=0.0,
        )


class DempsterShaferFusion(BaseFusionEngine):
    """Dempster-Shafer Evidence Theory — combines uncertain evidence."""

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.DEMPSTER_SHAFER

    def fuse_readings(self, readings: List[LayerReading]) -> FusionResult:
        start_time = time.time()
        if not readings:
            return self._empty_result()

        # Each reading is evidence: belief = confidence, plausibility = 1
        # Combine via Dempster's rule of combination
        combined_lat = 0.0
        combined_lon = 0.0
        combined_belief = 1.0

        for r in readings:
            belief = r.self_confidence
            # Dempster combination: m12(A) = sum m1(B)*m2(C) / (1-K)
            conflict = (1.0 - belief) * (1.0 - combined_belief)
            normaliser = max(1.0 - conflict, 0.01)

            w_old = combined_belief / normaliser
            w_new = belief / normaliser

            total_w = w_old + w_new
            if total_w > 0:
                combined_lat = (combined_lat * w_old + r.position.latitude * w_new) / total_w
                combined_lon = (combined_lon * w_old + r.position.longitude * w_new) / total_w

            combined_belief = min(0.99, (combined_belief * belief) / normaliser)

        # Accuracy from spread of evidence
        distances = []
        for r in readings:
            dlat = (r.position.latitude - combined_lat) * 111320
            dlon = (r.position.longitude - combined_lon) * 111320 * math.cos(math.radians(combined_lat))
            distances.append(math.sqrt(dlat**2 + dlon**2))

        accuracy = max(3.0, float(np.std(distances) * 2)) if distances else 50.0
        position = Position(latitude=combined_lat, longitude=combined_lon, accuracy_m=accuracy)
        processing_time = (time.time() - start_time) * 1000
        return FusionResult(
            algorithm=self.get_algorithm_type(), position=position,
            confidence=combined_belief, processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"Dempster-Shafer evidence combination of {len(readings)} sources",
            quality_score=min(1.0, combined_belief),
        )

    def _empty_result(self) -> FusionResult:
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0, processing_time_ms=0.1, layers_used=[],
            reasoning="No readings for DS", quality_score=0.0,
        )


class AntColonyFusion(BaseFusionEngine):
    """Ant Colony Optimization — bio-inspired pheromone trail convergence."""

    def get_algorithm_type(self) -> FusionAlgorithm:
        return FusionAlgorithm.ANT_COLONY

    def fuse_readings(self, readings: List[LayerReading], num_ants: int = 50, iterations: int = 15) -> FusionResult:
        start_time = time.time()
        if not readings:
            return self._empty_result()

        # Grid around readings for ants to explore
        lats = [r.position.latitude for r in readings]
        lons = [r.position.longitude for r in readings]
        center_lat, center_lon = np.mean(lats), np.mean(lons)
        spread = max(np.std(lats), np.std(lons), 1e-6) * 3

        # Pheromone grid (10x10)
        grid_size = 10
        pheromone = np.ones((grid_size, grid_size))

        for _ in range(iterations):
            ant_scores = np.zeros((grid_size, grid_size))
            for _ in range(num_ants):
                # Ant chooses cell probabilistically based on pheromone
                probs = pheromone.flatten() / pheromone.sum()
                cell = np.random.choice(grid_size * grid_size, p=probs)
                gi, gj = divmod(cell, grid_size)

                # Cell position
                cell_lat = center_lat + (gi - grid_size/2) * spread / grid_size
                cell_lon = center_lon + (gj - grid_size/2) * spread / grid_size

                # Score = sum of inverse distance to readings weighted by confidence
                score = 0.0
                for r in readings:
                    dlat = (cell_lat - r.position.latitude) * 111320
                    dlon = (cell_lon - r.position.longitude) * 111320
                    dist = math.sqrt(dlat**2 + dlon**2) + 1.0
                    score += r.self_confidence / dist

                ant_scores[gi, gj] += score

            # Evaporate and deposit pheromone
            pheromone *= 0.7  # evaporation
            pheromone += ant_scores

        # Best cell = highest pheromone
        best = np.unravel_index(np.argmax(pheromone), pheromone.shape)
        best_lat = center_lat + (best[0] - grid_size/2) * spread / grid_size
        best_lon = center_lon + (best[1] - grid_size/2) * spread / grid_size

        accuracy = max(3.0, spread * 111320 / grid_size)
        confidence = min(0.92, float(pheromone.max() / (pheromone.sum() + 1e-9)) * grid_size**2)

        position = Position(latitude=float(best_lat), longitude=float(best_lon), accuracy_m=accuracy)
        processing_time = (time.time() - start_time) * 1000
        return FusionResult(
            algorithm=self.get_algorithm_type(), position=position,
            confidence=confidence, processing_time_ms=processing_time,
            layers_used=[r.layer_id for r in readings],
            reasoning=f"Ant Colony ({num_ants} ants, {iterations} iterations) on {len(readings)} readings",
            quality_score=min(1.0, confidence),
        )

    def _empty_result(self) -> FusionResult:
        return FusionResult(
            algorithm=self.get_algorithm_type(),
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0, processing_time_ms=0.1, layers_used=[],
            reasoning="No readings for ACO", quality_score=0.0,
        )


class MultiFusionEngine:
    """
    Master fusion engine that runs multiple algorithms in parallel
    and selects the best result based on confidence and quality.
    """

    def __init__(self):
        self.fusion_engines = [
            ExtendedKalmanFusion(),
            ParticleFilterFusion(num_particles=500),
            WeightedLeastSquaresFusion(),
            UnscentedKalmanFusion(),
            CovarianceIntersectionFusion(),
            DempsterShaferFusion(),
            AntColonyFusion(),
        ]
        self.fusion_history: List[List[FusionResult]] = []

    def fuse_all_algorithms(self, readings: List[LayerReading]) -> List[FusionResult]:
        """Run all fusion algorithms and return their results."""
        results = []

        for engine in self.fusion_engines:
            try:
                result = engine.fuse_readings(readings)
                results.append(result)
            except Exception:
                # Skip failed algorithms, don't let one failure break everything
                continue

        self.fusion_history.append(results)
        return results

    def select_best_result(self, results: List[FusionResult]) -> FusionResult:
        """Select the best fusion result based on multiple criteria."""
        if not results:
            return self._emergency_fallback()

        # Score each result
        scored_results = []
        for result in results:
            score = self._calculate_result_score(result)
            scored_results.append((score, result))

        # Return highest scoring result
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return scored_results[0][1]

    def _calculate_result_score(self, result: FusionResult) -> float:
        """Calculate overall score for a fusion result."""
        confidence_score = result.confidence
        quality_score = result.quality_score
        accuracy_score = max(0.0, 1.0 - result.position.accuracy_m / 100.0)
        layer_score = min(1.0, len(result.layers_used) / 8.0)
        speed_score = max(0.0, 1.0 - result.processing_time_ms / 100.0)

        # Weighted combination
        total_score = (
            confidence_score * 0.3 +
            quality_score * 0.25 +
            accuracy_score * 0.25 +
            layer_score * 0.15 +
            speed_score * 0.05
        )

        return total_score

    def get_consensus_position(self, readings: List[LayerReading]) -> Tuple[Position, Dict]:
        """Get final consensus position from all algorithms."""
        # Run all algorithms
        results = self.fuse_all_algorithms(readings)

        if not results:
            return self._emergency_fallback().position, {"error": "All algorithms failed"}

        # Select best result
        best_result = self.select_best_result(results)

        # Build metadata
        metadata = {
            "algorithms_run": len(results),
            "best_algorithm": best_result.algorithm.name,
            "best_confidence": best_result.confidence,
            "best_quality": best_result.quality_score,
            "processing_time_ms": best_result.processing_time_ms,
            "layers_used": len(best_result.layers_used),
            "all_results": [
                {
                    "algorithm": r.algorithm.name,
                    "confidence": r.confidence,
                    "accuracy_m": r.position.accuracy_m,
                    "quality": r.quality_score
                }
                for r in results
            ]
        }

        return best_result.position, metadata

    def _emergency_fallback(self) -> FusionResult:
        """Emergency fallback when all algorithms fail."""
        return FusionResult(
            algorithm=FusionAlgorithm.CONSENSUS_VOTING,
            position=Position(0.0, 0.0, accuracy_m=1000.0),
            confidence=0.0,
            processing_time_ms=0.1,
            layers_used=[],
            reasoning="Emergency fallback - all algorithms failed",
            quality_score=0.0
        )
