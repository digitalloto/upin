"""
Army Ant Tactics — UPIN Swarm

Two strategies from army ants:

1. LIVING BRIDGE — ants form bridges with their bodies for others to
   cross. For drones: RELAY drones physically position themselves to
   form a communication bridge across a dead zone (mountain, valley,
   jamming area). The bridge rebuilds if a node is lost.

2. LEADERLESS EMERGENCE — no single ant controls the colony. Behaviour
   emerges from simple local rules. For drones: if the leader is
   destroyed, the swarm continues with zero disruption. Each drone
   follows 3 rules: follow pheromone (strongest signal), avoid
   collisions, reinforce successful paths.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class BridgeNode:
    """A drone acting as a relay node in the living bridge."""
    drone_id: str
    lat: float
    lon: float
    alt: float
    signal_strength_dbm: float = -60.0
    connected_to: List[str] = field(default_factory=list)
    is_anchor: bool = False  # end-points of the bridge


class AntLivingBridge:
    """Form a communication bridge across a dead zone.

    Drones space themselves evenly between two endpoints, creating
    a relay chain. If a node is lost, neighbors close the gap.
    """

    def __init__(self, max_link_distance_m: float = 500.0):
        self._max_link = max_link_distance_m
        self._nodes: Dict[str, BridgeNode] = {}
        self._start: Optional[Tuple[float, float, float]] = None
        self._end: Optional[Tuple[float, float, float]] = None

    def set_endpoints(self, start: Tuple[float, float, float],
                      end: Tuple[float, float, float]):
        self._start = start
        self._end = end

    def build_bridge(self, drone_ids: List[str]) -> List[Dict]:
        """Position drones evenly between start and end."""
        if not self._start or not self._end or not drone_ids:
            return []

        n = len(drone_ids)
        waypoints = []
        for i, did in enumerate(drone_ids):
            t = (i + 1) / (n + 1)  # evenly spaced 0→1
            lat = self._start[0] + t * (self._end[0] - self._start[0])
            lon = self._start[1] + t * (self._end[1] - self._start[1])
            alt = self._start[2] + t * (self._end[2] - self._start[2])

            self._nodes[did] = BridgeNode(
                drone_id=did, lat=lat, lon=lon, alt=alt)
            waypoints.append({
                "drone_id": did, "lat": lat, "lon": lon, "alt": alt,
                "position_in_chain": i, "total_nodes": n,
            })

        # Connect adjacent nodes
        ordered = list(self._nodes.keys())
        for i, did in enumerate(ordered):
            node = self._nodes[did]
            node.connected_to = []
            if i > 0:
                node.connected_to.append(ordered[i - 1])
            if i < len(ordered) - 1:
                node.connected_to.append(ordered[i + 1])

        return waypoints

    def remove_node(self, drone_id: str) -> Optional[Dict]:
        """Node lost — neighbors close the gap."""
        if drone_id not in self._nodes:
            return None
        del self._nodes[drone_id]
        # Reconnect remaining
        ordered = list(self._nodes.keys())
        for i, did in enumerate(ordered):
            node = self._nodes[did]
            node.connected_to = []
            if i > 0:
                node.connected_to.append(ordered[i - 1])
            if i < len(ordered) - 1:
                node.connected_to.append(ordered[i + 1])
        return {
            "event": "BRIDGE_HEALED",
            "lost_node": drone_id,
            "remaining_nodes": len(self._nodes),
            "bridge_intact": len(self._nodes) >= 1,
        }

    def get_status(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "start": self._start,
            "end": self._end,
            "chain": list(self._nodes.keys()),
        }


@dataclass
class PheromoneTrail:
    """A signal trace left by a successful path."""
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    strength: float = 1.0  # decays over time
    created_at: float = field(default_factory=time.time)


class AntLeaderlessEmergence:
    """Leaderless swarm behaviour from simple local rules.

    Each drone follows 3 rules:
    1. Follow pheromone: move toward strongest signal trail
    2. Avoid collisions: maintain minimum separation
    3. Reinforce success: mark paths that led to target

    No leader needed. If any drone is destroyed, the rest continue.
    Behaviour emerges from local interactions — like real ants.
    """

    def __init__(self, separation_m: float = 30.0,
                 pheromone_decay: float = 0.99):
        self._separation = separation_m
        self._decay = pheromone_decay
        self._trails: List[PheromoneTrail] = []
        self._max_trails = 500

    def deposit_pheromone(self, from_lat: float, from_lon: float,
                          to_lat: float, to_lon: float,
                          strength: float = 1.0):
        """Drone marks a successful path segment."""
        self._trails.append(PheromoneTrail(
            from_lat=from_lat, from_lon=from_lon,
            to_lat=to_lat, to_lon=to_lon, strength=strength,
        ))
        if len(self._trails) > self._max_trails:
            self._trails = self._trails[-self._max_trails:]

    def get_best_direction(self, lat: float, lon: float,
                           search_radius_m: float = 200.0) -> Optional[Dict]:
        """Find strongest pheromone direction from current position."""
        nearby = []
        for trail in self._trails:
            d = _haversine_m(lat, lon, trail.from_lat, trail.from_lon)
            if d <= search_radius_m and trail.strength > 0.1:
                bearing = math.degrees(math.atan2(
                    trail.to_lon - trail.from_lon,
                    trail.to_lat - trail.from_lat)) % 360
                nearby.append({"bearing": bearing, "strength": trail.strength})

        if not nearby:
            return None

        # Weighted average bearing
        total_w = 0.0
        bx = by = 0.0
        for t in nearby:
            bx += t["strength"] * math.cos(math.radians(t["bearing"]))
            by += t["strength"] * math.sin(math.radians(t["bearing"]))
            total_w += t["strength"]

        best_bearing = math.degrees(math.atan2(by, bx)) % 360
        return {
            "bearing_deg": best_bearing,
            "strength": total_w,
            "trails_nearby": len(nearby),
        }

    def decay_all(self):
        """Age all pheromone trails — weak ones fade away."""
        for trail in self._trails:
            trail.strength *= self._decay
        self._trails = [t for t in self._trails if t.strength > 0.01]

    def check_separation(self, positions: List[Tuple[str, float, float]]
                          ) -> List[Dict]:
        """Check for collision risks between drones."""
        warnings = []
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                d = _haversine_m(positions[i][1], positions[i][2],
                                 positions[j][1], positions[j][2])
                if d < self._separation:
                    warnings.append({
                        "drone_a": positions[i][0],
                        "drone_b": positions[j][0],
                        "distance_m": round(d, 1),
                        "action": "SEPARATE",
                    })
        return warnings

    def get_status(self) -> Dict:
        return {
            "active_trails": len(self._trails),
            "avg_strength": (sum(t.strength for t in self._trails)
                             / max(1, len(self._trails))),
        }


class ArmyAntTactics:
    """Combined army ant tactical suite."""

    def __init__(self):
        self.living_bridge = AntLivingBridge()
        self.emergence = AntLeaderlessEmergence()

    def get_full_status(self) -> Dict:
        return {
            "living_bridge": self.living_bridge.get_status(),
            "emergence": self.emergence.get_status(),
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
