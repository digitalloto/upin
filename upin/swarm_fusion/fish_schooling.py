"""
Fish Schooling Fusion Algorithm — UPIN Swarm Intelligence

Treats each sensor reading as a "fish" in a school. Each fish follows
simple local rules:
1. Cohesion: Stay close to neighbors (similar readings)
2. Separation: Avoid bad readings (low confidence)
3. Alignment: Move toward consensus
4. Goal Seeking: Optimize for accuracy

The swarm collectively finds optimal position through emergent behavior.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.position import Position
from upin.core.layer_base import LayerReading


@dataclass
class Fish:
    """One fish in the school - represents a sensor reading with behavior."""
    fish_id: str
    position_lat: float
    position_lon: float
    velocity_lat: float = 0.0
    velocity_lon: float = 0.0
    confidence: float = 0.5
    accuracy: float = 10.0
    energy: float = 1.0        # Fish energy (health)
    age: int = 0               # How long this fish has existed
    original_reading: Optional[LayerReading] = None

    def distance_to(self, other: 'Fish') -> float:
        """Calculate distance to another fish in meters."""
        dlat = (self.position_lat - other.position_lat) * 111320
        dlon = (self.position_lon - other.position_lon) * 111320 * math.cos(math.radians(self.position_lat))
        return math.sqrt(dlat**2 + dlon**2)

    def update_position(self, dt: float = 1.0):
        """Update fish position based on velocity."""
        self.position_lat += self.velocity_lat * dt
        self.position_lon += self.velocity_lon * dt
        self.age += 1

        # Energy decay over time (older fish lose influence)
        self.energy *= 0.98

    def apply_force(self, force_lat: float, force_lon: float, strength: float = 1.0):
        """Apply a force to the fish (changes velocity)."""
        max_force = 0.0001  # Maximum force per timestep
        force_lat = max(-max_force, min(max_force, force_lat * strength))
        force_lon = max(-max_force, min(max_force, force_lon * strength))

        self.velocity_lat += force_lat
        self.velocity_lon += force_lon

        # Velocity limits (prevent fish from moving too fast)
        max_velocity = 0.0005
        speed = math.sqrt(self.velocity_lat**2 + self.velocity_lon**2)
        if speed > max_velocity:
            self.velocity_lat = (self.velocity_lat / speed) * max_velocity
            self.velocity_lon = (self.velocity_lon / speed) * max_velocity


class FishSchool:
    """A school of fish representing sensor readings."""

    def __init__(self, cohesion_radius: float = 50.0, separation_radius: float = 20.0):
        self.fish: List[Fish] = []
        self.cohesion_radius = cohesion_radius      # meters - how close fish want to be
        self.separation_radius = separation_radius   # meters - minimum distance between fish
        self.alignment_strength = 0.3
        self.cohesion_strength = 0.5
        self.separation_strength = 0.8
        self.goal_seeking_strength = 0.6

    def add_fish_from_reading(self, reading: LayerReading) -> Fish:
        """Add a new fish based on a sensor reading."""
        fish = Fish(
            fish_id=f"fish_{reading.layer_id}_{len(self.fish)}",
            position_lat=reading.position.latitude,
            position_lon=reading.position.longitude,
            confidence=reading.self_confidence,
            accuracy=reading.position.accuracy_m,
            energy=reading.self_confidence,  # High confidence = high energy
            original_reading=reading
        )
        self.fish.append(fish)
        return fish

    def update_school(self, iterations: int = 20) -> None:
        """Run the schooling simulation for specified iterations."""
        for iteration in range(iterations):
            # Calculate forces for each fish
            for fish in self.fish:
                if fish.energy < 0.1:  # Skip very weak fish
                    continue

                neighbors = self._get_neighbors(fish, self.cohesion_radius)

                # Apply flocking forces
                cohesion_force = self._cohesion_force(fish, neighbors)
                separation_force = self._separation_force(fish, neighbors)
                alignment_force = self._alignment_force(fish, neighbors)
                goal_force = self._goal_seeking_force(fish)

                # Weight forces by fish energy and confidence
                weight = fish.energy * fish.confidence

                fish.apply_force(
                    cohesion_force[0] * self.cohesion_strength * weight +
                    separation_force[0] * self.separation_strength +
                    alignment_force[0] * self.alignment_strength * weight +
                    goal_force[0] * self.goal_seeking_strength,

                    cohesion_force[1] * self.cohesion_strength * weight +
                    separation_force[1] * self.separation_strength +
                    alignment_force[1] * self.alignment_strength * weight +
                    goal_force[1] * self.goal_seeking_strength
                )

            # Update all fish positions
            for fish in self.fish:
                fish.update_position(dt=0.1)

    def _get_neighbors(self, fish: Fish, radius: float) -> List[Fish]:
        """Get neighboring fish within radius."""
        neighbors = []
        for other in self.fish:
            if other != fish and fish.distance_to(other) <= radius:
                neighbors.append(other)
        return neighbors

    def _cohesion_force(self, fish: Fish, neighbors: List[Fish]) -> Tuple[float, float]:
        """Force toward center of neighboring fish."""
        if not neighbors:
            return (0.0, 0.0)

        # Weighted center based on neighbor confidence
        total_weight = 0.0
        center_lat = 0.0
        center_lon = 0.0

        for neighbor in neighbors:
            weight = neighbor.confidence * neighbor.energy
            center_lat += neighbor.position_lat * weight
            center_lon += neighbor.position_lon * weight
            total_weight += weight

        if total_weight == 0:
            return (0.0, 0.0)

        center_lat /= total_weight
        center_lon /= total_weight

        # Force toward center
        force_lat = center_lat - fish.position_lat
        force_lon = center_lon - fish.position_lon

        return (force_lat, force_lon)

    def _separation_force(self, fish: Fish, neighbors: List[Fish]) -> Tuple[float, float]:
        """Force away from too-close neighbors."""
        force_lat = 0.0
        force_lon = 0.0

        for neighbor in neighbors:
            distance = fish.distance_to(neighbor)
            if distance < self.separation_radius and distance > 0:
                # Stronger force for closer fish and lower confidence fish
                strength = (self.separation_radius - distance) / self.separation_radius
                strength *= (1.0 - neighbor.confidence)  # Push away from low-confidence fish

                # Direction away from neighbor
                away_lat = fish.position_lat - neighbor.position_lat
                away_lon = fish.position_lon - neighbor.position_lon

                # Normalize and apply strength
                norm = math.sqrt(away_lat**2 + away_lon**2) or 1.0
                force_lat += (away_lat / norm) * strength * 0.0001
                force_lon += (away_lon / norm) * strength * 0.0001

        return (force_lat, force_lon)

    def _alignment_force(self, fish: Fish, neighbors: List[Fish]) -> Tuple[float, float]:
        """Force to align velocity with neighbors."""
        if not neighbors:
            return (0.0, 0.0)

        # Average neighbor velocity weighted by confidence
        total_weight = 0.0
        avg_vel_lat = 0.0
        avg_vel_lon = 0.0

        for neighbor in neighbors:
            weight = neighbor.confidence * neighbor.energy
            avg_vel_lat += neighbor.velocity_lat * weight
            avg_vel_lon += neighbor.velocity_lon * weight
            total_weight += weight

        if total_weight == 0:
            return (0.0, 0.0)

        avg_vel_lat /= total_weight
        avg_vel_lon /= total_weight

        # Force toward average velocity
        force_lat = (avg_vel_lat - fish.velocity_lat) * 0.5
        force_lon = (avg_vel_lon - fish.velocity_lon) * 0.5

        return (force_lat, force_lon)

    def _goal_seeking_force(self, fish: Fish) -> Tuple[float, float]:
        """Force toward optimal position (center of mass of high-confidence fish)."""
        high_confidence_fish = [f for f in self.fish if f.confidence > 0.7 and f != fish]

        if not high_confidence_fish:
            return (0.0, 0.0)

        # Center of mass of high-confidence fish
        total_weight = 0.0
        goal_lat = 0.0
        goal_lon = 0.0

        for hc_fish in high_confidence_fish:
            weight = hc_fish.confidence * hc_fish.energy * (1.0 / max(hc_fish.accuracy, 1.0))
            goal_lat += hc_fish.position_lat * weight
            goal_lon += hc_fish.position_lon * weight
            total_weight += weight

        if total_weight == 0:
            return (0.0, 0.0)

        goal_lat /= total_weight
        goal_lon /= total_weight

        # Force toward goal
        force_lat = goal_lat - fish.position_lat
        force_lon = goal_lon - fish.position_lon

        return (force_lat, force_lon)

    def get_swarm_consensus(self) -> Tuple[float, float, float, float]:
        """Get final position from swarm consensus."""
        if not self.fish:
            return (0.0, 0.0, 1000.0, 0.0)

        # Weighted average based on fish energy and confidence
        total_weight = 0.0
        consensus_lat = 0.0
        consensus_lon = 0.0

        for fish in self.fish:
            weight = fish.energy * fish.confidence * (1.0 / max(fish.accuracy, 1.0))
            consensus_lat += fish.position_lat * weight
            consensus_lon += fish.position_lon * weight
            total_weight += weight

        if total_weight == 0:
            return (0.0, 0.0, 1000.0, 0.0)

        consensus_lat /= total_weight
        consensus_lon /= total_weight

        # Calculate consensus accuracy from fish spread
        distances = []
        for fish in self.fish:
            if fish.energy > 0.3:  # Only consider healthy fish
                dlat = (fish.position_lat - consensus_lat) * 111320
                dlon = (fish.position_lon - consensus_lon) * 111320 * math.cos(math.radians(consensus_lat))
                dist = math.sqrt(dlat**2 + dlon**2)
                distances.append(dist)

        accuracy = max(3.0, float(np.std(distances))) if distances else 50.0
        confidence = min(0.95, total_weight / len(self.fish))

        return (consensus_lat, consensus_lon, accuracy, confidence)


class FishSchoolingFusion:
    """Fish Schooling fusion algorithm for UPIN."""

    def __init__(self):
        self.cohesion_radius = 30.0    # meters
        self.separation_radius = 15.0  # meters
        self.simulation_iterations = 25

    def fuse_readings(self, readings: List[LayerReading]) -> Tuple[Position, Dict]:
        """Fuse sensor readings using fish schooling algorithm."""
        start_time = time.time()

        if not readings:
            empty_pos = Position(0.0, 0.0, accuracy_m=1000.0)
            return empty_pos, {"error": "No readings provided"}

        # Create fish school
        school = FishSchool(self.cohesion_radius, self.separation_radius)

        # Add fish for each reading
        for reading in readings:
            school.add_fish_from_reading(reading)

        # Run schooling simulation
        school.update_school(iterations=self.simulation_iterations)

        # Get consensus result
        consensus_lat, consensus_lon, accuracy, confidence = school.get_swarm_consensus()

        processing_time = (time.time() - start_time) * 1000

        position = Position(
            latitude=consensus_lat,
            longitude=consensus_lon,
            accuracy_m=accuracy,
        )

        metadata = {
            "algorithm": "Fish_Schooling",
            "fish_count": len(school.fish),
            "iterations": self.simulation_iterations,
            "cohesion_radius_m": self.cohesion_radius,
            "processing_time_ms": processing_time,
            "confidence": confidence,
            "consensus_method": "swarm_intelligence"
        }

        return position, metadata
