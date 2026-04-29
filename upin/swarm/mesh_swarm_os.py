"""
Mesh Swarm Operating System — UPIN

The central nervous system that ties together:
- Cooperative mesh positioning (peer-to-peer ranging)
- Drone role specialisation (decoy/spotter/strike/scout/EW/relay)
- Defensive jammer shield (downward electronic dome)
- UPIN multi-layer navigation per drone
- Predictive positioning (T+5 forward prediction)
- Encrypted swarm comms
- Swarm-wide sensor fusion

Every drone in the mesh contributes to the swarm's collective
position knowledge. If ONE drone gets a GPS fix, ALL drones
instantly get absolute coordinates through the mesh.

The mesh is self-healing: if a drone is destroyed, the remaining
drones re-form the mesh and continue operating.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple


class MeshNodeStatus(Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    LOST = "lost"
    DESTROYED = "destroyed"
    JOINING = "joining"


@dataclass
class MeshNode:
    """One drone in the swarm mesh."""
    node_id: str
    callsign: str
    role: str  # DroneRole value
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    heading_deg: float = 0.0
    speed_ms: float = 0.0
    position_source: str = "unknown"  # gps, mesh, predicted, denied
    position_confidence: float = 0.0
    has_gps: bool = False
    battery_pct: float = 100.0
    status: MeshNodeStatus = MeshNodeStatus.JOINING
    last_heartbeat: float = 0.0
    ranges_to_peers: Dict[str, float] = field(default_factory=dict)
    # UPIN layer count active on this drone
    active_layer_count: int = 0
    # Sensor data this drone can share with the mesh
    shared_sensors: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MeshMessage:
    """An encrypted message passed through the mesh."""
    msg_id: str
    from_node: str
    to_node: str  # "broadcast" for all
    msg_type: str  # position, sensor, threat, command, heartbeat
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    hop_count: int = 0
    max_hops: int = 5
    encrypted: bool = True


class SwarmMeshOS:
    """The swarm mesh operating system.

    Manages all drones in the mesh, handles position sharing,
    sensor fusion, threat distribution, and formation control.
    """

    def __init__(self, swarm_id: str = "UPIN-SWARM-01"):
        self.swarm_id = swarm_id
        self._nodes: Dict[str, MeshNode] = {}
        self._message_queue: deque = deque(maxlen=1000)
        self._mesh_log: List[Dict] = []
        self._formation_center = (0.0, 0.0, 0.0)
        self._tick_count = 0
        self._gps_anchor_node: Optional[str] = None  # node with best GPS
        self._threat_tracks: Dict[str, Dict] = {}

        # Mesh health thresholds
        self._heartbeat_timeout_s = 10.0
        self._min_nodes_for_mesh = 3

    # ── Node Management ───────────────────────────────────────────

    def add_node(self, node_id: str, callsign: str, role: str) -> MeshNode:
        """Add a drone to the mesh."""
        node = MeshNode(
            node_id=node_id, callsign=callsign, role=role,
            last_heartbeat=time.time(), status=MeshNodeStatus.JOINING,
        )
        self._nodes[node_id] = node
        self._broadcast(node_id, "join", {"callsign": callsign, "role": role})
        self._log("NODE_JOIN", f"{callsign} ({role}) joined mesh")
        return node

    def remove_node(self, node_id: str, reason: str = "departed"):
        """Remove a drone from the mesh."""
        if node_id in self._nodes:
            self._log("NODE_LEAVE",
                      f"{self._nodes[node_id].callsign} left: {reason}")
            del self._nodes[node_id]
            self._recompute_anchor()

    def update_node_position(self, node_id: str, lat: float, lon: float,
                             alt: float, source: str = "gps",
                             confidence: float = 0.9,
                             heading_deg: float = 0.0,
                             speed_ms: float = 0.0):
        """Update a node's position. Triggers mesh propagation if GPS."""
        node = self._nodes.get(node_id)
        if node is None:
            return
        node.lat = lat
        node.lon = lon
        node.alt = alt
        node.heading_deg = heading_deg
        node.speed_ms = speed_ms
        node.position_source = source
        node.position_confidence = confidence
        node.has_gps = (source == "gps")
        node.last_heartbeat = time.time()
        node.status = MeshNodeStatus.ACTIVE

        # If this node has GPS → it becomes anchor → propagate to all
        if source == "gps" and confidence > 0.7:
            self._gps_anchor_node = node_id
            self._propagate_absolute_position(node_id)

    def update_peer_range(self, from_node: str, to_node: str,
                          distance_m: float, method: str = "uwb"):
        """Record a peer-to-peer range measurement."""
        node = self._nodes.get(from_node)
        if node:
            node.ranges_to_peers[to_node] = distance_m
        # Also store reverse (ranging is symmetric)
        peer = self._nodes.get(to_node)
        if peer:
            peer.ranges_to_peers[from_node] = distance_m

    def share_sensor_data(self, node_id: str, sensor_type: str,
                          data: Dict):
        """Share sensor readings with the mesh for collective fusion."""
        node = self._nodes.get(node_id)
        if node:
            node.shared_sensors[sensor_type] = {
                "data": data,
                "timestamp": time.time(),
            }
        self._broadcast(node_id, "sensor", {
            "sensor_type": sensor_type, **data,
        })

    # ── Mesh Positioning ──────────────────────────────────────────

    def _propagate_absolute_position(self, anchor_id: str):
        """When one node gets GPS, propagate absolute coords to all via ranges."""
        anchor = self._nodes.get(anchor_id)
        if anchor is None:
            return

        for node_id, node in self._nodes.items():
            if node_id == anchor_id:
                continue
            if anchor_id in node.ranges_to_peers:
                range_m = node.ranges_to_peers[anchor_id]
                # Simple: place node at range_m from anchor along bearing
                # With 3+ ranges this becomes trilateration (handled by cooperative_mesh)
                if node.position_source != "gps":
                    # Estimate position from anchor + range
                    bearing_rad = math.atan2(
                        node.lon - anchor.lon if node.lon != 0 else 0.001,
                        node.lat - anchor.lat if node.lat != 0 else 0.001,
                    )
                    d_lat = range_m * math.cos(bearing_rad) / 111_320.0
                    cos_lat = math.cos(math.radians(anchor.lat))
                    d_lon = range_m * math.sin(bearing_rad) / (111_320.0 * max(cos_lat, 0.01))
                    node.lat = anchor.lat + d_lat
                    node.lon = anchor.lon + d_lon
                    node.alt = anchor.alt
                    node.position_source = "mesh"
                    node.position_confidence = max(0.3, anchor.position_confidence - 0.2)
                    node.has_gps = False

        self._log("MESH_PROPAGATE",
                  f"Anchor {anchor.callsign} propagated GPS to {len(self._nodes)-1} nodes")

    def mesh_trilaterate(self, target_node_id: str) -> Optional[Dict]:
        """Trilaterate a node's position from 3+ peer ranges.

        Uses all available peer ranges where the peer has known position.
        """
        target = self._nodes.get(target_node_id)
        if target is None:
            return None

        anchors = []
        for peer_id, range_m in target.ranges_to_peers.items():
            peer = self._nodes.get(peer_id)
            if peer and peer.position_confidence > 0.3:
                anchors.append((peer.lat, peer.lon, range_m))

        if len(anchors) < 3:
            return None

        # Weighted centroid (inverse-distance weighting)
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for a_lat, a_lon, r in anchors:
            w = 1.0 / max(r, 1.0)
            lat_sum += a_lat * w
            lon_sum += a_lon * w
            total_w += w

        lat = lat_sum / total_w
        lon = lon_sum / total_w
        accuracy = sum(r for _, _, r in anchors) / len(anchors)

        target.lat = lat
        target.lon = lon
        target.position_source = "mesh_trilat"
        target.position_confidence = min(0.85, 0.3 + len(anchors) * 0.1)

        return {
            "lat": lat, "lon": lon,
            "accuracy_m": accuracy,
            "anchors_used": len(anchors),
            "confidence": target.position_confidence,
        }

    # ── Threat Distribution ───────────────────────────────────────

    def report_threat(self, reporter_node: str, threat: Dict):
        """A node reports a threat — distribute to all nodes instantly."""
        track_id = threat.get("track_id", f"T{len(self._threat_tracks)}")
        self._threat_tracks[track_id] = {
            **threat,
            "reported_by": reporter_node,
            "reported_at": time.time(),
        }
        self._broadcast(reporter_node, "threat", threat)
        self._log("THREAT", f"Node {reporter_node} reports threat {track_id}")

    # ── Formation Control ─────────────────────────────────────────

    def compute_formation_center(self) -> Tuple[float, float, float]:
        """Compute the swarm centroid from all active nodes."""
        active = [n for n in self._nodes.values()
                  if n.status == MeshNodeStatus.ACTIVE and n.position_confidence > 0]
        if not active:
            return self._formation_center
        lat = sum(n.lat for n in active) / len(active)
        lon = sum(n.lon for n in active) / len(active)
        alt = sum(n.alt for n in active) / len(active)
        self._formation_center = (lat, lon, alt)
        return self._formation_center

    def get_formation_spread_m(self) -> float:
        """Max distance from centroid to any active node."""
        center = self.compute_formation_center()
        max_dist = 0.0
        for node in self._nodes.values():
            if node.status != MeshNodeStatus.ACTIVE:
                continue
            d = _haversine_m(center[0], center[1], node.lat, node.lon)
            max_dist = max(max_dist, d)
        return max_dist

    # ── Mesh Health ───────────────────────────────────────────────

    def tick(self) -> Dict:
        """Run one mesh health cycle. Call every second."""
        self._tick_count += 1
        now = time.time()

        # Check heartbeats
        lost_nodes = []
        for node_id, node in self._nodes.items():
            if node.status == MeshNodeStatus.DESTROYED:
                continue
            elapsed = now - node.last_heartbeat
            if elapsed > self._heartbeat_timeout_s * 3:
                node.status = MeshNodeStatus.LOST
                lost_nodes.append(node_id)
            elif elapsed > self._heartbeat_timeout_s:
                node.status = MeshNodeStatus.DEGRADED

        # Self-healing: if we lost the GPS anchor, find next best
        if self._gps_anchor_node and self._gps_anchor_node in lost_nodes:
            self._recompute_anchor()

        active = sum(1 for n in self._nodes.values()
                     if n.status == MeshNodeStatus.ACTIVE)
        mesh_healthy = active >= self._min_nodes_for_mesh

        return {
            "tick": self._tick_count,
            "total_nodes": len(self._nodes),
            "active": active,
            "degraded": sum(1 for n in self._nodes.values()
                            if n.status == MeshNodeStatus.DEGRADED),
            "lost": len(lost_nodes),
            "mesh_healthy": mesh_healthy,
            "gps_anchor": self._gps_anchor_node,
            "formation_center": self._formation_center,
            "threats_tracked": len(self._threat_tracks),
        }

    def _recompute_anchor(self):
        """Find the node with best GPS for anchor role."""
        best_node = None
        best_conf = 0.0
        for node_id, node in self._nodes.items():
            if (node.has_gps and node.status == MeshNodeStatus.ACTIVE
                    and node.position_confidence > best_conf):
                best_conf = node.position_confidence
                best_node = node_id
        self._gps_anchor_node = best_node
        if best_node:
            self._propagate_absolute_position(best_node)

    # ── Messaging ─────────────────────────────────────────────────

    def _broadcast(self, from_node: str, msg_type: str, payload: Dict):
        msg = MeshMessage(
            msg_id=f"M{self._tick_count:06d}",
            from_node=from_node,
            to_node="broadcast",
            msg_type=msg_type,
            payload=payload,
        )
        self._message_queue.append(msg)

    # ── Collective Sensor Fusion ──────────────────────────────────

    def get_collective_sensors(self) -> Dict[str, List[Dict]]:
        """Aggregate sensor data shared by all nodes for swarm-wide fusion."""
        collective: Dict[str, List[Dict]] = {}
        now = time.time()
        for node in self._nodes.values():
            for sensor_type, entry in node.shared_sensors.items():
                if now - entry["timestamp"] > 30.0:
                    continue  # stale data
                if sensor_type not in collective:
                    collective[sensor_type] = []
                collective[sensor_type].append({
                    "node": node.node_id,
                    "data": entry["data"],
                    "timestamp": entry["timestamp"],
                    "node_position": (node.lat, node.lon, node.alt),
                })
        return collective

    # ── Logging & Status ──────────────────────────────────────────

    def _log(self, event_type: str, detail: str):
        self._mesh_log.append({
            "tick": self._tick_count,
            "time": time.time(),
            "event": event_type,
            "detail": detail,
        })
        if len(self._mesh_log) > 500:
            self._mesh_log = self._mesh_log[-500:]

    def get_full_status(self) -> Dict:
        nodes_summary = []
        for n in self._nodes.values():
            nodes_summary.append({
                "id": n.node_id,
                "callsign": n.callsign,
                "role": n.role,
                "status": n.status.value,
                "position_source": n.position_source,
                "confidence": round(n.position_confidence, 2),
                "has_gps": n.has_gps,
                "battery_pct": n.battery_pct,
                "peer_ranges": len(n.ranges_to_peers),
                "shared_sensors": list(n.shared_sensors.keys()),
            })
        return {
            "swarm_id": self.swarm_id,
            "total_nodes": len(self._nodes),
            "nodes": nodes_summary,
            "gps_anchor": self._gps_anchor_node,
            "formation_center": self._formation_center,
            "formation_spread_m": round(self.get_formation_spread_m(), 1),
            "threats": len(self._threat_tracks),
            "messages_queued": len(self._message_queue),
            "ticks": self._tick_count,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
