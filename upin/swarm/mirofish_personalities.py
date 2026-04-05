"""
MiroFish Agent Personalities + Intel Ingestion Pipeline + RuView Interface

1. MiroFish Personalities: each agent evolves its own unique personality
   (cohesion, aggression, caution, curiosity, loyalty) through natural selection.
   Agents with good positioning instincts survive and breed.

2. Intel Pipeline: takes HUMINT/SIGINT/IMINT and continuously adjusts
   fusion engine layer weights in real-time.

3. RuView Interface: stub for WiFi DensePose body pose input when
   RuView matures.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════
#  1. MIROFISH AGENT PERSONALITIES
# ══════════════════════════════════════════════════════════════════

@dataclass
class AgentPersonality:
    """
    Each MiroFish agent has a unique personality that evolves.
    Not just parameters — a character that determines behaviour.
    """
    agent_id: str

    # Core traits (0.0-1.0)
    cohesion: float = 0.5       # How much it follows the group
    aggression: float = 0.3     # How strongly it pushes its own opinion
    caution: float = 0.5        # How much it distrusts outlier readings
    curiosity: float = 0.3      # How much it explores vs exploits
    loyalty: float = 0.7        # How much it trusts its own history vs others
    adaptability: float = 0.5   # How fast it changes its mind

    # Evolved parameters
    sma_window: int = 20
    ema_alpha: float = 0.15
    confidence_threshold: float = 0.7
    separation_radius: float = 15.0

    # Performance tracking
    fitness: float = 0.0        # Cumulative accuracy score
    generation: int = 0
    mutations: int = 0
    age: int = 0                # Ticks alive

    def mutate(self, mutation_rate: float = 0.1) -> 'AgentPersonality':
        """Create a mutated offspring."""
        child = AgentPersonality(
            agent_id=f"{self.agent_id}_g{self.generation + 1}_{random.randint(0,999)}",
            cohesion=np.clip(self.cohesion + random.gauss(0, mutation_rate), 0, 1),
            aggression=np.clip(self.aggression + random.gauss(0, mutation_rate), 0, 1),
            caution=np.clip(self.caution + random.gauss(0, mutation_rate), 0, 1),
            curiosity=np.clip(self.curiosity + random.gauss(0, mutation_rate), 0, 1),
            loyalty=np.clip(self.loyalty + random.gauss(0, mutation_rate), 0, 1),
            adaptability=np.clip(self.adaptability + random.gauss(0, mutation_rate), 0, 1),
            sma_window=max(3, self.sma_window + random.randint(-3, 3)),
            ema_alpha=np.clip(self.ema_alpha + random.gauss(0, 0.03), 0.01, 0.5),
            confidence_threshold=np.clip(self.confidence_threshold + random.gauss(0, 0.05), 0.3, 0.95),
            separation_radius=max(5, self.separation_radius + random.gauss(0, 2)),
            generation=self.generation + 1,
            mutations=self.mutations + 1,
        )
        return child

    def crossover(self, other: 'AgentPersonality') -> 'AgentPersonality':
        """Breed with another personality (sexual reproduction)."""
        child = AgentPersonality(
            agent_id=f"cross_{random.randint(0,9999)}",
            cohesion=(self.cohesion + other.cohesion) / 2 + random.gauss(0, 0.02),
            aggression=(self.aggression + other.aggression) / 2 + random.gauss(0, 0.02),
            caution=(self.caution + other.caution) / 2 + random.gauss(0, 0.02),
            curiosity=(self.curiosity + other.curiosity) / 2 + random.gauss(0, 0.02),
            loyalty=(self.loyalty + other.loyalty) / 2 + random.gauss(0, 0.02),
            adaptability=(self.adaptability + other.adaptability) / 2 + random.gauss(0, 0.02),
            sma_window=(self.sma_window + other.sma_window) // 2,
            ema_alpha=(self.ema_alpha + other.ema_alpha) / 2,
            confidence_threshold=(self.confidence_threshold + other.confidence_threshold) / 2,
            separation_radius=(self.separation_radius + other.separation_radius) / 2,
            generation=max(self.generation, other.generation) + 1,
        )
        # Clip all traits
        for attr in ('cohesion', 'aggression', 'caution', 'curiosity', 'loyalty', 'adaptability'):
            setattr(child, attr, np.clip(getattr(child, attr), 0, 1))
        return child

    def predict_position(self, readings: List[Dict], speeds: List[float],
                          headings: List[float], last_lat: float, last_lon: float,
                          blind_seconds: float) -> Tuple[float, float]:
        """
        Predict position based on this agent's unique personality.
        Aggressive agents trust recent data. Cautious agents smooth heavily.
        Curious agents explore; loyal agents stick to their history.
        """
        if not readings or not speeds:
            return (last_lat, last_lon)

        # Speed: aggression = fast SMA, caution = slow SMA
        effective_window = max(3, int(self.sma_window * (1 + self.caution - self.aggression)))
        recent_speeds = speeds[-effective_window:]
        speed = sum(recent_speeds) / len(recent_speeds)

        # Heading: loyalty = trust own EMA, curiosity = look at outliers
        effective_alpha = self.ema_alpha * (1 + self.adaptability * 0.5)
        if headings:
            heading = headings[0]
            for h in headings[1:]:
                heading = effective_alpha * h + (1 - effective_alpha) * heading
        else:
            heading = 0

        # Curiosity: add small random exploration
        if self.curiosity > 0.5:
            heading += random.gauss(0, self.curiosity * 5)

        # Cohesion: pull toward group average position
        if readings and self.cohesion > 0.3:
            avg_lat = np.mean([r.get('lat', last_lat) for r in readings[-5:]])
            avg_lon = np.mean([r.get('lon', last_lon) for r in readings[-5:]])
            cohesion_pull = self.cohesion * 0.3
            last_lat = last_lat * (1 - cohesion_pull) + avg_lat * cohesion_pull
            last_lon = last_lon * (1 - cohesion_pull) + avg_lon * cohesion_pull

        # Project forward
        heading_rad = math.radians(heading)
        dist = speed * blind_seconds
        pred_lat = last_lat + dist * math.cos(heading_rad) / 111320
        pred_lon = last_lon + dist * math.sin(heading_rad) / (111320 * math.cos(math.radians(last_lat)))

        return (pred_lat, pred_lon)

    def to_dict(self) -> Dict:
        return {
            "id": self.agent_id,
            "traits": {
                "cohesion": round(self.cohesion, 3),
                "aggression": round(self.aggression, 3),
                "caution": round(self.caution, 3),
                "curiosity": round(self.curiosity, 3),
                "loyalty": round(self.loyalty, 3),
                "adaptability": round(self.adaptability, 3),
            },
            "params": {
                "sma_window": self.sma_window,
                "ema_alpha": round(self.ema_alpha, 3),
                "conf_threshold": round(self.confidence_threshold, 3),
                "separation_r": round(self.separation_radius, 1),
            },
            "fitness": round(self.fitness, 4),
            "generation": self.generation,
            "age": self.age,
        }


class MiroFishPopulation:
    """
    Population of MiroFish agents with natural selection.
    Agents predict positions, get scored, and the best breed.
    """

    def __init__(self, population_size: int = 60):
        self.population: List[AgentPersonality] = []
        self._generation = 0
        self._evolution_interval = 20  # Evolve every 20 scoring events
        self._score_count = 0

        # Seed with diverse initial population
        self._seed_population(population_size)

    def _seed_population(self, n: int):
        """Create diverse initial population."""
        archetypes = [
            ("scout", 0.3, 0.7, 0.3, 0.8, 0.4, 0.7),     # Aggressive, curious
            ("guard", 0.8, 0.2, 0.8, 0.2, 0.9, 0.3),     # Cohesive, cautious, loyal
            ("explorer", 0.2, 0.5, 0.3, 0.9, 0.3, 0.8),   # Independent, curious
            ("analyst", 0.5, 0.3, 0.7, 0.4, 0.6, 0.5),    # Balanced, cautious
            ("leader", 0.6, 0.6, 0.4, 0.5, 0.8, 0.6),     # Cohesive, aggressive, loyal
        ]

        for i in range(n):
            archetype = archetypes[i % len(archetypes)]
            name, co, ag, ca, cu, lo, ad = archetype
            agent = AgentPersonality(
                agent_id=f"{name}_{i}",
                cohesion=co + random.gauss(0, 0.1),
                aggression=ag + random.gauss(0, 0.1),
                caution=ca + random.gauss(0, 0.1),
                curiosity=cu + random.gauss(0, 0.1),
                loyalty=lo + random.gauss(0, 0.1),
                adaptability=ad + random.gauss(0, 0.1),
                sma_window=random.randint(5, 40),
                ema_alpha=random.uniform(0.03, 0.3),
            )
            for attr in ('cohesion', 'aggression', 'caution', 'curiosity', 'loyalty', 'adaptability'):
                setattr(agent, attr, np.clip(getattr(agent, attr), 0, 1))
            self.population.append(agent)

    def predict_all(self, readings, speeds, headings, lat, lon, blind_s) -> Dict[str, Tuple[float, float]]:
        """All agents predict independently."""
        preds = {}
        for agent in self.population:
            agent.age += 1
            pred = agent.predict_position(readings, speeds, headings, lat, lon, blind_s)
            preds[agent.agent_id] = pred
        return preds

    def score_all(self, predictions: Dict[str, Tuple[float, float]],
                  actual_lat: float, actual_lon: float):
        """Score every agent against ground truth."""
        self._score_count += 1

        for agent in self.population:
            pred = predictions.get(agent.agent_id)
            if pred:
                dlat = (pred[0] - actual_lat) * 111320
                dlon = (pred[1] - actual_lon) * 111320 * math.cos(math.radians(actual_lat))
                error = math.sqrt(dlat ** 2 + dlon ** 2)
                accuracy = 1.0 / (1.0 + error)

                # Running fitness average
                alpha = 0.1
                agent.fitness = (1 - alpha) * agent.fitness + alpha * accuracy

        # Natural selection
        if self._score_count % self._evolution_interval == 0:
            self._evolve()

    def _evolve(self):
        """Natural selection: best survive, worst get replaced."""
        self._generation += 1
        self.population.sort(key=lambda a: a.fitness, reverse=True)

        n = len(self.population)
        survivors = self.population[:int(n * 0.6)]  # Top 60% survive

        # Breed from top 30%
        parents = self.population[:int(n * 0.3)]
        children = []
        while len(survivors) + len(children) < n:
            p1 = random.choice(parents)
            p2 = random.choice(parents)
            if random.random() < 0.7:
                child = p1.crossover(p2)
            else:
                child = p1.mutate(mutation_rate=0.15)
            children.append(child)

        self.population = survivors + children

    def get_consensus(self, predictions: Dict[str, Tuple[float, float]]) -> Tuple[float, float]:
        """Fitness-weighted consensus from all agents."""
        total_w = 0.0
        w_lat = 0.0
        w_lon = 0.0
        for agent in self.population:
            pred = predictions.get(agent.agent_id)
            if pred:
                w = max(0.01, agent.fitness)
                w_lat += pred[0] * w
                w_lon += pred[1] * w
                total_w += w
        if total_w == 0:
            return (0, 0)
        return (w_lat / total_w, w_lon / total_w)

    def get_stats(self) -> Dict:
        fitnesses = [a.fitness for a in self.population]
        return {
            "population": len(self.population),
            "generation": self._generation,
            "score_events": self._score_count,
            "avg_fitness": round(float(np.mean(fitnesses)), 4),
            "best_fitness": round(float(max(fitnesses)), 4),
            "worst_fitness": round(float(min(fitnesses)), 4),
            "best_agent": max(self.population, key=lambda a: a.fitness).to_dict(),
            "trait_diversity": {
                trait: round(float(np.std([getattr(a, trait) for a in self.population])), 3)
                for trait in ("cohesion", "aggression", "caution", "curiosity", "loyalty")
            },
        }


# ══════════════════════════════════════════════════════════════════
#  2. INTEL INGESTION PIPELINE
# ══════════════════════════════════════════════════════════════════

class IntelIngestionPipeline:
    """
    Takes HUMINT, SIGINT, IMINT and continuously adjusts fusion engine
    layer weights in real-time. This is the missing pipeline that connects
    mission_intel.py data structures to the actual fusion engine.

    Input types:
    - HUMINT: "informant says jammer at grid reference XY"
    - SIGINT: "intercepted RF emission at frequency F, bearing B"
    - IMINT: "satellite shows vehicle convoy at location L"
    - MASINT: "magnetic anomaly detected at position P"
    - OSINT: "social media reports GPS issues in area A"
    """

    INTEL_TYPES = ["HUMINT", "SIGINT", "IMINT", "MASINT", "OSINT"]

    def __init__(self):
        self._raw_intel: deque = deque(maxlen=500)
        self._active_adjustments: Dict[str, Dict] = {}
        self._processed_count = 0

    def ingest(self, intel_type: str, data: Dict) -> Dict:
        """
        Ingest one piece of intelligence and generate layer adjustments.
        """
        self._processed_count += 1
        entry = {
            "id": f"INTEL_{self._processed_count:05d}",
            "type": intel_type,
            "data": data,
            "timestamp": time.time(),
            "adjustments": {},
        }

        # Generate layer weight adjustments based on intel type and content
        adjustments = self._generate_adjustments(intel_type, data)
        entry["adjustments"] = adjustments
        self._raw_intel.append(entry)

        # Merge into active adjustments
        for layer_id, weight_change in adjustments.items():
            if layer_id not in self._active_adjustments:
                self._active_adjustments[layer_id] = {"weight_multiplier": 1.0, "sources": []}
            adj = self._active_adjustments[layer_id]
            adj["weight_multiplier"] *= weight_change
            adj["weight_multiplier"] = np.clip(adj["weight_multiplier"], 0.1, 3.0)
            adj["sources"].append(entry["id"])

        return entry

    def _generate_adjustments(self, intel_type: str, data: Dict) -> Dict[str, float]:
        """Generate layer weight adjustments from intelligence."""
        adjustments = {}
        threat = data.get("threat_type", "")
        severity = data.get("severity", 0.5)
        lat = data.get("lat", 0)
        lon = data.get("lon", 0)

        if threat in ("jammer", "jamming", "gps_jammer"):
            # Downweight GPS layers, boost internal
            adjustments["gps_l1"] = max(0.1, 1.0 - severity)
            adjustments["navic_l2"] = max(0.1, 1.0 - severity * 0.8)
            adjustments["ins_l3"] = min(2.0, 1.0 + severity * 0.5)
            adjustments["magano_l6"] = min(2.0, 1.0 + severity * 0.5)
            adjustments["vslam_l31"] = min(1.5, 1.0 + severity * 0.3)

        elif threat in ("spoofer", "spoofing", "gps_spoofer"):
            adjustments["gps_l1"] = 0.1  # Nearly disable GPS
            adjustments["navic_l2"] = 0.3
            adjustments["muon_l40"] = 1.8  # Boost unjammable
            adjustments["gravgrad_l28a"] = 1.5
            adjustments["schumann_l59"] = 1.5

        elif threat in ("rf_interference", "electronic_warfare"):
            for rf_layer in ["wifi_l8", "celltower_l9", "lora_d07", "bluetooth_d08"]:
                adjustments[rf_layer] = max(0.2, 1.0 - severity)
            adjustments["ins_l3"] = 1.5
            adjustments["terrain_l5"] = 1.3

        elif intel_type == "IMINT":
            # Satellite imagery — boost visual layers
            adjustments["vslam_l31"] = 1.3
            adjustments["terrain_l5"] = 1.5
            adjustments["eagle_e12"] = 1.3

        elif intel_type == "MASINT":
            # Measurement intelligence — boost corresponding sensors
            adjustments["magano_l6"] = 1.3
            adjustments["seismic_l36"] = 1.5
            adjustments["gravgrad_l28a"] = 1.3

        elif intel_type == "OSINT":
            # Open source — general awareness, mild adjustments
            if "gps" in str(data).lower():
                adjustments["gps_l1"] = max(0.5, 1.0 - severity * 0.3)

        return adjustments

    def get_active_adjustments(self) -> Dict[str, float]:
        """Get current weight multipliers for all affected layers."""
        return {
            layer_id: round(adj["weight_multiplier"], 3)
            for layer_id, adj in self._active_adjustments.items()
        }

    def clear_adjustment(self, layer_id: str):
        """Clear adjustment for a specific layer (intel resolved)."""
        self._active_adjustments.pop(layer_id, None)

    def clear_all(self):
        """Clear all adjustments (situation resolved)."""
        self._active_adjustments.clear()

    def get_stats(self) -> Dict:
        return {
            "total_ingested": self._processed_count,
            "active_adjustments": len(self._active_adjustments),
            "layers_affected": list(self._active_adjustments.keys()),
        }


# ══════════════════════════════════════════════════════════════════
#  3. RUVIEW READINESS INTERFACE
# ══════════════════════════════════════════════════════════════════

class RuViewInterface:
    """
    Stub interface for RuView WiFi DensePose integration.
    When RuView matures, its body pose output feeds here and gets
    converted to movement classification for UPIN layers.

    Current state: accepts simulated pose data.
    Future state: receives real WiFi DensePose from RuView SDK.
    """

    POSES = ["standing", "sitting", "prone", "walking", "running", "crouching", "unknown"]

    def __init__(self):
        self._connected = False
        self._last_pose: Optional[Dict] = None
        self._pose_history: deque = deque(maxlen=100)

    def connect(self, ruview_endpoint: str = "") -> bool:
        """Connect to RuView SDK when available."""
        # Future: actual SDK connection
        self._connected = False  # Not available yet
        return self._connected

    def receive_pose(self, pose_data: Dict) -> Dict:
        """
        Receive body pose data from RuView or simulation.

        pose_data: {
            "persons": [{"id": 0, "pose": "walking", "confidence": 0.85,
                          "keypoints": [...], "position_relative": (x, y, z)}],
            "timestamp": 1234567890.0
        }
        """
        self._last_pose = pose_data
        self._pose_history.append(pose_data)

        # Convert to UPIN movement classification
        persons = pose_data.get("persons", [])
        movement_pattern = "none"

        if not persons:
            movement_pattern = "none"
        elif len(persons) == 1:
            pose = persons[0].get("pose", "unknown")
            if pose in ("walking", "running"):
                movement_pattern = "civilian"
            elif pose == "crouching":
                movement_pattern = "tactical"
            elif pose == "prone":
                movement_pattern = "tactical"
            else:
                movement_pattern = "stationary"
        elif len(persons) <= 3:
            poses = [p.get("pose", "unknown") for p in persons]
            if any(p in ("crouching", "prone") for p in poses):
                movement_pattern = "tactical"
            else:
                movement_pattern = "organised"
        else:
            movement_pattern = "high_density"

        return {
            "person_count": len(persons),
            "movement_pattern": movement_pattern,
            "poses": [p.get("pose", "unknown") for p in persons],
            "source": "ruview" if self._connected else "simulated",
            "upin_compatible": True,
            "feeds_to": ["wifi_csi_sensor", "structure_analyser", "target_lock"],
        }

    def get_status(self) -> Dict:
        return {
            "connected": self._connected,
            "sdk_available": False,  # Will be True when RuView SDK ships
            "pose_history_count": len(self._pose_history),
            "last_pose": self._last_pose is not None,
            "readiness": "STUB — waiting for RuView SDK maturity",
        }
