"""
Multi-Layer Fish Schooling Enhancement for UPIN

This implements your concept: 10 fish schools per layer, each with different
parameters, learning which parameters work best for each device through
real-world position confirmations.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

import numpy as np
import time
import json
import random
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import deque

@dataclass
class FishSchoolParameters:
    """Parameters for a single fish school"""
    school_id: str
    cohesion_radius: float = 30.0
    separation_radius: float = 15.0
    simulation_iterations: int = 25
    energy_decay_rate: float = 0.98
    confidence_threshold: float = 0.7
    learning_rate: float = 0.1
    performance_score: float = 0.0
    usage_count: int = 0

class MultiLayerFishSchooling:
    """
    Multi-Layer Fish Schooling with Adaptive Parameter Learning

    Each layer has 10 fish schools with different parameters.
    System learns which parameters work best through position confirmations.
    """

    def __init__(self, num_layers: int = 6, schools_per_layer: int = 10):
        self.num_layers = num_layers
        self.schools_per_layer = schools_per_layer
        self.total_schools = num_layers * schools_per_layer

        # Initialize fish schools with diverse parameters
        self.fish_schools = self._initialize_fish_schools()

        # Performance tracking
        self.performance_history = deque(maxlen=1000)  # Last 1000 confirmations
        self.position_confirmations = []
        self.learning_enabled = True

        # Parameter evolution tracking
        self.generation = 0
        self.evolution_frequency = 50  # Evolve parameters every 50 confirmations

    def _initialize_fish_schools(self) -> Dict[str, Dict[str, FishSchoolParameters]]:
        """Initialize fish schools with diverse parameter sets"""
        schools = {}

        # Parameter ranges for diversity
        param_ranges = {
            'cohesion_radius': (15.0, 50.0),
            'separation_radius': (5.0, 30.0),
            'simulation_iterations': (10, 40),
            'energy_decay_rate': (0.9, 0.995),
            'confidence_threshold': (0.5, 0.85)
        }

        for layer in range(self.num_layers):
            layer_name = f"layer_{layer}"
            schools[layer_name] = {}

            for school in range(self.schools_per_layer):
                school_id = f"school_{layer}_{school}"

                # Generate diverse parameters using different strategies
                if school < 3:
                    # Conservative schools (proven ranges)
                    params = self._generate_conservative_params(school_id)
                elif school < 6:
                    # Aggressive schools (wider exploration)
                    params = self._generate_aggressive_params(school_id, param_ranges)
                elif school < 8:
                    # Hybrid schools (mixed strategies)
                    params = self._generate_hybrid_params(school_id, param_ranges)
                else:
                    # Experimental schools (random exploration)
                    params = self._generate_experimental_params(school_id, param_ranges)

                schools[layer_name][school_id] = params

        return schools

    def _generate_conservative_params(self, school_id: str) -> FishSchoolParameters:
        """Generate conservative parameter set (proven effective)"""
        base_params = {
            'cohesion_radius': 30.0,
            'separation_radius': 15.0,
            'simulation_iterations': 25,
            'energy_decay_rate': 0.98,
            'confidence_threshold': 0.7
        }

        # Add small random variations
        for key in base_params:
            if key in ['cohesion_radius', 'separation_radius']:
                base_params[key] += random.uniform(-3.0, 3.0)
            elif key == 'simulation_iterations':
                base_params[key] += random.randint(-3, 3)
            elif key == 'energy_decay_rate':
                base_params[key] += random.uniform(-0.02, 0.02)
            elif key == 'confidence_threshold':
                base_params[key] += random.uniform(-0.05, 0.05)

        return FishSchoolParameters(school_id=school_id, **base_params)

    def _generate_aggressive_params(self, school_id: str, ranges: Dict) -> FishSchoolParameters:
        """Generate aggressive parameter set (wider exploration)"""
        params = {}
        for key, (min_val, max_val) in ranges.items():
            if key in ['cohesion_radius', 'separation_radius', 'energy_decay_rate', 'confidence_threshold']:
                params[key] = random.uniform(min_val, max_val)
            else:  # simulation_iterations
                params[key] = random.randint(int(min_val), int(max_val))

        return FishSchoolParameters(school_id=school_id, **params)

    def _generate_hybrid_params(self, school_id: str, ranges: Dict) -> FishSchoolParameters:
        """Generate hybrid parameter set (mix of conservative and aggressive)"""
        conservative = self._generate_conservative_params(school_id)

        aggressive_params = random.sample(list(ranges.keys()), random.randint(2, 3))

        for param in aggressive_params:
            min_val, max_val = ranges[param]
            if param in ['cohesion_radius', 'separation_radius', 'energy_decay_rate', 'confidence_threshold']:
                setattr(conservative, param, random.uniform(min_val, max_val))
            else:
                setattr(conservative, param, random.randint(int(min_val), int(max_val)))

        return conservative

    def _generate_experimental_params(self, school_id: str, ranges: Dict) -> FishSchoolParameters:
        """Generate experimental parameter set (extreme exploration)"""
        params = {}
        for key, (min_val, max_val) in ranges.items():
            extended_range = (max_val - min_val) * 0.2
            extended_min = max(0, min_val - extended_range)
            extended_max = max_val + extended_range

            if key in ['cohesion_radius', 'separation_radius', 'energy_decay_rate', 'confidence_threshold']:
                params[key] = random.uniform(extended_min, extended_max)
            else:
                params[key] = random.randint(int(extended_min), int(extended_max))

        return FishSchoolParameters(school_id=school_id, **params)

    def run_multi_layer_fusion(self, sensor_readings: List[Dict], layer_weights: List[float]) -> Dict:
        """
        Run all fish schools across all layers and select the best results
        """
        layer_results = {}
        all_school_results = []

        for layer_idx in range(self.num_layers):
            layer_name = f"layer_{layer_idx}"
            layer_schools = self.fish_schools[layer_name]
            layer_school_results = []

            for school_id, school_params in layer_schools.items():
                school_result = self._run_single_fish_school(
                    sensor_readings, school_params, layer_idx
                )
                school_result['layer'] = layer_idx
                school_result['school_id'] = school_id

                layer_school_results.append(school_result)
                all_school_results.append(school_result)

            best_school = max(layer_school_results, key=lambda x: x['confidence'])
            layer_results[layer_name] = {
                'best_school': best_school,
                'all_schools': layer_school_results,
                'layer_weight': layer_weights[layer_idx] if layer_idx < len(layer_weights) else 1.0
            }

        final_result = self._fuse_layer_results(layer_results)
        final_result['all_school_results'] = all_school_results

        return final_result

    def _run_single_fish_school(self, sensor_readings: List[Dict], params: FishSchoolParameters, layer_idx: int) -> Dict:
        """Run fish schooling algorithm with specific parameters"""
        fish_positions = []
        fish_confidences = []

        for reading in sensor_readings:
            if 'lat' in reading and 'lon' in reading:
                fish_positions.append([reading['lat'], reading['lon']])
                fish_confidences.append(reading.get('confidence', 0.5))

        if len(fish_positions) < 2:
            return {
                'lat': 0.0, 'lon': 0.0, 'confidence': 0.0,
                'school_params': asdict(params), 'fish_count': 0
            }

        for iteration in range(params.simulation_iterations):
            new_positions = []
            new_confidences = []

            for i, (pos, conf) in enumerate(zip(fish_positions, fish_confidences)):
                nearby_positions = []
                for j, other_pos in enumerate(fish_positions):
                    if i != j:
                        distance = np.sqrt((pos[0] - other_pos[0])**2 + (pos[1] - other_pos[1])**2) * 111320
                        if distance < params.cohesion_radius:
                            nearby_positions.append(other_pos)

                if nearby_positions:
                    avg_pos = np.mean(nearby_positions, axis=0)
                    cohesion_force = (avg_pos - np.array(pos)) * 0.1
                else:
                    cohesion_force = np.array([0, 0])

                separation_force = np.array([0.0, 0.0])
                for j, other_pos in enumerate(fish_positions):
                    if i != j:
                        distance = np.sqrt((pos[0] - other_pos[0])**2 + (pos[1] - other_pos[1])**2) * 111320
                        if distance < params.separation_radius and distance > 0:
                            diff = np.array(pos) - np.array(other_pos)
                            separation_force += diff / (distance / 111320)

                new_pos = np.array(pos) + cohesion_force + separation_force * 0.05
                new_conf = conf * params.energy_decay_rate

                new_positions.append(new_pos.tolist())
                new_confidences.append(new_conf)

            fish_positions = new_positions
            fish_confidences = new_confidences

        high_confidence_fish = [
            (pos, conf) for pos, conf in zip(fish_positions, fish_confidences)
            if conf > params.confidence_threshold
        ]

        if high_confidence_fish:
            positions = np.array([pos for pos, conf in high_confidence_fish])
            confidences = np.array([conf for pos, conf in high_confidence_fish])

            weights = confidences / np.sum(confidences)
            consensus_pos = np.average(positions, axis=0, weights=weights)
            consensus_confidence = float(np.mean(confidences))
        else:
            consensus_pos = np.mean(fish_positions, axis=0)
            consensus_confidence = float(np.mean(fish_confidences))

        params.usage_count += 1

        return {
            'lat': float(consensus_pos[0]),
            'lon': float(consensus_pos[1]),
            'confidence': min(1.0, consensus_confidence),
            'school_params': asdict(params),
            'fish_count': len(fish_positions),
            'high_confidence_fish': len(high_confidence_fish) if high_confidence_fish else 0
        }

    def _fuse_layer_results(self, layer_results: Dict) -> Dict:
        """Fuse results from all layers using weighted averaging"""
        positions = []
        confidences = []
        weights = []

        for layer_name, layer_data in layer_results.items():
            best_result = layer_data['best_school']
            layer_weight = layer_data['layer_weight']

            positions.append([best_result['lat'], best_result['lon']])
            confidences.append(best_result['confidence'])
            weights.append(layer_weight * best_result['confidence'])

        if not positions:
            return {'lat': 0.0, 'lon': 0.0, 'confidence': 0.0}

        positions = np.array(positions)
        weights = np.array(weights)
        if weights.sum() > 0:
            weights = weights / weights.sum()
        else:
            weights = np.ones(len(weights)) / len(weights)

        final_position = np.average(positions, axis=0, weights=weights)
        final_confidence = float(np.average(confidences, weights=weights))

        return {
            'lat': float(final_position[0]),
            'lon': float(final_position[1]),
            'confidence': min(1.0, final_confidence),
            'layer_results': {k: {'best_lat': v['best_school']['lat'],
                                   'best_lon': v['best_school']['lon'],
                                   'best_conf': v['best_school']['confidence'],
                                   'weight': v['layer_weight']}
                              for k, v in layer_results.items()},
            'fusion_weights': weights.tolist(),
            'timestamp': time.time()
        }

    def record_position_confirmation(self, true_position: Tuple[float, float], upin_result: Dict):
        """
        Record when we get GPS/landmark confirmation of true position.
        This is where the learning happens!
        """
        if not self.learning_enabled:
            return

        confirmation = {
            'timestamp': time.time(),
            'true_lat': true_position[0],
            'true_lon': true_position[1],
            'upin_lat': upin_result['lat'],
            'upin_lon': upin_result['lon'],
            'upin_confidence': upin_result['confidence'],
        }

        true_pos = np.array([true_position[0], true_position[1]])

        for school_result in upin_result.get('all_school_results', []):
            predicted_pos = np.array([school_result['lat'], school_result['lon']])
            error_meters = float(np.linalg.norm((true_pos - predicted_pos) * 111320))

            school_id = school_result['school_id']
            layer_idx = school_result['layer']
            layer_name = f"layer_{layer_idx}"

            if layer_name in self.fish_schools and school_id in self.fish_schools[layer_name]:
                school_params = self.fish_schools[layer_name][school_id]

                current_performance = 1.0 / (1.0 + error_meters)

                if school_params.performance_score == 0.0:
                    school_params.performance_score = current_performance
                else:
                    alpha = school_params.learning_rate
                    school_params.performance_score = (1 - alpha) * school_params.performance_score + alpha * current_performance

        self.position_confirmations.append(confirmation)
        self.performance_history.append(confirmation)

        if len(self.position_confirmations) % self.evolution_frequency == 0:
            self._evolve_parameters()

    def _evolve_parameters(self):
        """
        Evolve fish school parameters based on performance.
        Top performers breed, worst performers get replaced.
        """
        self.generation += 1

        for layer_name, layer_schools in self.fish_schools.items():
            schools = list(layer_schools.values())
            schools.sort(key=lambda s: s.performance_score, reverse=True)

            if len(schools) < 4:
                continue

            # Top 30% are parents
            parent_count = max(2, len(schools) * 3 // 10)
            parents = schools[:parent_count]

            # Bottom 20% get replaced by offspring of parents
            replace_count = max(1, len(schools) * 2 // 10)

            for i in range(replace_count):
                child_idx = len(schools) - 1 - i
                if child_idx < parent_count:
                    break

                p1 = random.choice(parents)
                p2 = random.choice(parents)

                child = schools[child_idx]
                # Crossover
                child.cohesion_radius = (p1.cohesion_radius + p2.cohesion_radius) / 2 + random.uniform(-2, 2)
                child.separation_radius = (p1.separation_radius + p2.separation_radius) / 2 + random.uniform(-1, 1)
                child.simulation_iterations = (p1.simulation_iterations + p2.simulation_iterations) // 2 + random.randint(-2, 2)
                child.energy_decay_rate = (p1.energy_decay_rate + p2.energy_decay_rate) / 2 + random.uniform(-0.01, 0.01)
                child.confidence_threshold = (p1.confidence_threshold + p2.confidence_threshold) / 2 + random.uniform(-0.03, 0.03)
                child.performance_score = 0.0  # Reset — must prove itself
                child.usage_count = 0

    def get_performance_summary(self) -> Dict:
        """Get summary of all school performances for monitoring."""
        summary = {
            'generation': self.generation,
            'total_schools': self.total_schools,
            'total_confirmations': len(self.position_confirmations),
            'layers': {}
        }

        for layer_name, layer_schools in self.fish_schools.items():
            schools = list(layer_schools.values())
            scores = [s.performance_score for s in schools]
            summary['layers'][layer_name] = {
                'school_count': len(schools),
                'best_score': round(max(scores), 4) if scores else 0,
                'avg_score': round(sum(scores) / len(scores), 4) if scores else 0,
                'worst_score': round(min(scores), 4) if scores else 0,
                'best_school': max(schools, key=lambda s: s.performance_score).school_id if schools else None,
                'total_usage': sum(s.usage_count for s in schools),
            }

        return summary
