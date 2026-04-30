"""
Orca (Killer Whale) Swarm Tactics — UPIN

Four hunting strategies from orca pods applied to drone swarms:

1. WAVE WASH — coordinated synchronized attack that creates a
   combined effect stronger than individual efforts. Multiple drones
   sync their jamming pulses to create 10× resonance.

2. CAROUSEL FEEDING — encircle target, rotate positions so no single
   drone exhausts battery. Continuous pressure with fresh attackers.

3. POD DIALECT — each swarm generates unique encrypted comms that
   change when membership changes. Captured drone = old keys useless.

4. TEACHING — experienced swarms transfer learned weights, route DTW
   data, and formula agent parameters to new drones joining the mesh.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 1. WAVE WASH — Synchronized coordinated attack
# ═══════════════════════════════════════════════════════════════

@dataclass
class WaveParticipant:
    """A drone participating in a wave wash attack."""
    drone_id: str
    position: Tuple[float, float, float]  # lat, lon, alt
    jam_power_w: float = 5.0
    phase_offset_s: float = 0.0
    ready: bool = False


class OrcaWaveWash:
    """Coordinated synchronized attack — EW resonance.

    3-4 drones synchronize their jamming pulses so they arrive
    at the target simultaneously, creating constructive interference
    that's 10× stronger than any single jammer.

    Like orcas creating a wave to knock seals off ice — the
    synchronized timing is what makes it devastating.
    """

    def __init__(self, pulse_duration_s: float = 0.5,
                 cycle_period_s: float = 2.0):
        self._participants: Dict[str, WaveParticipant] = {}
        self._target: Optional[Tuple[float, float, float]] = None
        self._pulse_duration = pulse_duration_s
        self._cycle_period = cycle_period_s
        self._active = False
        self._wave_count = 0
        self._sync_time: Optional[float] = None

    def add_participant(self, drone_id: str,
                        position: Tuple[float, float, float],
                        jam_power_w: float = 5.0):
        """Add a drone to the wave wash formation."""
        self._participants[drone_id] = WaveParticipant(
            drone_id=drone_id, position=position,
            jam_power_w=jam_power_w,
        )

    def set_target(self, lat: float, lon: float, alt: float = 0.0):
        """Set the target location for the wave wash."""
        self._target = (lat, lon, alt)
        self._compute_phase_offsets()

    def _compute_phase_offsets(self):
        """Compute timing offsets so all pulses arrive at target simultaneously.

        Each drone's signal travels at light speed (3e8 m/s), so farther
        drones need to transmit earlier. The offset = distance / c.
        """
        if self._target is None:
            return
        for p in self._participants.values():
            dist = _haversine_m(
                p.position[0], p.position[1],
                self._target[0], self._target[1],
            )
            p.phase_offset_s = dist / 3e8  # propagation delay
            p.ready = True

    def execute_wave(self) -> Dict:
        """Execute one synchronized wave pulse."""
        if not self._active or self._target is None:
            return {"status": "not_active"}
        if len(self._participants) < 2:
            return {"status": "need_minimum_2_drones"}

        self._wave_count += 1
        self._sync_time = time.time()

        # Each drone transmits at sync_time - phase_offset
        schedule = {}
        total_power = 0.0
        for drone_id, p in self._participants.items():
            if p.ready:
                tx_time = self._sync_time - p.phase_offset_s
                schedule[drone_id] = {
                    "transmit_at": tx_time,
                    "power_w": p.jam_power_w,
                    "duration_s": self._pulse_duration,
                    "phase_offset_ns": round(p.phase_offset_s * 1e9, 1),
                }
                total_power += p.jam_power_w

        # Constructive interference: coherent addition = N^2 power gain
        n = len(schedule)
        effective_power = total_power * n  # coherent gain

        return {
            "status": "wave_executed",
            "wave_number": self._wave_count,
            "participants": n,
            "individual_power_w": total_power / max(1, n),
            "effective_power_w": effective_power,
            "gain_factor": n,
            "target": self._target,
            "schedule": schedule,
        }

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def get_status(self) -> Dict:
        return {
            "active": self._active,
            "participants": len(self._participants),
            "target": self._target,
            "waves_executed": self._wave_count,
            "ready": all(p.ready for p in self._participants.values()),
        }


# ═══════════════════════════════════════════════════════════════
# 2. CAROUSEL FEEDING — Rotating containment perimeter
# ═══════════════════════════════════════════════════════════════

@dataclass
class CarouselSlot:
    """A position slot in the carousel rotation."""
    slot_id: int
    angle_deg: float      # position on the circle
    radius_m: float       # distance from target center
    altitude_m: float
    assigned_drone: Optional[str] = None
    time_on_station_s: float = 0.0
    max_time_on_station_s: float = 300.0  # 5 min then rotate


class OrcaCarousel:
    """Carousel feeding — encircle and rotate.

    Drones form a ring around a target area. Each drone occupies
    a slot on the perimeter. When a drone's time-on-station expires
    (or battery gets low), it swaps with the next drone in rotation.

    Like orcas herding fish into a ball and taking turns attacking —
    continuous pressure with fresh attackers. The target never gets relief.
    """

    def __init__(self, radius_m: float = 200.0,
                 altitude_m: float = 100.0,
                 rotation_speed_dps: float = 2.0):
        self._center: Optional[Tuple[float, float]] = None
        self._radius_m = radius_m
        self._altitude_m = altitude_m
        self._rotation_speed = rotation_speed_dps
        self._slots: List[CarouselSlot] = []
        self._reserve_queue: List[str] = []
        self._rotation_count = 0

    def set_target_area(self, lat: float, lon: float, n_slots: int = 6):
        """Define the containment perimeter around a target."""
        self._center = (lat, lon)
        self._slots = []
        angle_step = 360.0 / n_slots
        for i in range(n_slots):
            self._slots.append(CarouselSlot(
                slot_id=i,
                angle_deg=i * angle_step,
                radius_m=self._radius_m,
                altitude_m=self._altitude_m,
            ))

    def assign_drone(self, drone_id: str) -> Optional[int]:
        """Assign a drone to the next empty slot. Returns slot_id or None."""
        for slot in self._slots:
            if slot.assigned_drone is None:
                slot.assigned_drone = drone_id
                slot.time_on_station_s = 0.0
                return slot.slot_id
        self._reserve_queue.append(drone_id)
        return None

    def tick(self, dt: float = 1.0) -> List[Dict]:
        """Advance the carousel. Returns rotation events."""
        events = []
        # Rotate all slots
        for slot in self._slots:
            slot.angle_deg = (slot.angle_deg + self._rotation_speed * dt) % 360.0
            if slot.assigned_drone:
                slot.time_on_station_s += dt

        # Check for drones that need to swap out
        for slot in self._slots:
            if (slot.assigned_drone
                    and slot.time_on_station_s >= slot.max_time_on_station_s
                    and self._reserve_queue):
                old_drone = slot.assigned_drone
                new_drone = self._reserve_queue.pop(0)
                slot.assigned_drone = new_drone
                slot.time_on_station_s = 0.0
                self._reserve_queue.append(old_drone)
                self._rotation_count += 1
                events.append({
                    "event": "SWAP",
                    "slot": slot.slot_id,
                    "old_drone": old_drone,
                    "new_drone": new_drone,
                    "rotation": self._rotation_count,
                })

        return events

    def get_drone_waypoint(self, drone_id: str) -> Optional[Dict]:
        """Get the current target waypoint for a drone in the carousel."""
        if self._center is None:
            return None
        for slot in self._slots:
            if slot.assigned_drone == drone_id:
                angle_rad = math.radians(slot.angle_deg)
                d_north = slot.radius_m * math.cos(angle_rad)
                d_east = slot.radius_m * math.sin(angle_rad)
                lat = self._center[0] + d_north / 111_320.0
                cos_lat = math.cos(math.radians(self._center[0]))
                lon = self._center[1] + d_east / (111_320.0 * max(cos_lat, 0.01))
                return {
                    "lat": lat, "lon": lon, "alt": slot.altitude_m,
                    "slot_id": slot.slot_id,
                    "angle_deg": slot.angle_deg,
                    "heading_toward_center": (slot.angle_deg + 180) % 360,
                    "time_remaining_s": max(0, slot.max_time_on_station_s
                                            - slot.time_on_station_s),
                }
        return None

    def get_status(self) -> Dict:
        assigned = sum(1 for s in self._slots if s.assigned_drone)
        return {
            "center": self._center,
            "radius_m": self._radius_m,
            "slots": len(self._slots),
            "assigned": assigned,
            "reserve_queue": len(self._reserve_queue),
            "rotations": self._rotation_count,
        }


# ═══════════════════════════════════════════════════════════════
# 3. POD DIALECT — Per-swarm encryption with membership keys
# ═══════════════════════════════════════════════════════════════

class OrcaPodDialect:
    """Pod-specific encrypted communication protocol.

    Each orca pod has unique vocalizations that other pods can't
    mimic. Applied to drones: the swarm generates a shared encryption
    key derived from the current membership list. If a drone is
    captured or leaves, the remaining swarm re-keys immediately.

    The key is a hash of all member IDs + a rolling nonce. Even if
    the enemy captures one drone and extracts its key, the swarm
    has already re-keyed with the captured drone excluded.
    """

    def __init__(self):
        self._members: List[str] = []
        self._current_key: bytes = b""
        self._key_generation: int = 0
        self._nonce: int = 0
        self._key_history: List[Tuple[int, bytes, List[str]]] = []

    def add_member(self, drone_id: str):
        """Add a drone to the pod — triggers re-key."""
        if drone_id not in self._members:
            self._members.append(drone_id)
            self._members.sort()
            self._rekey("member_added")

    def remove_member(self, drone_id: str):
        """Remove a drone (captured/lost) — triggers immediate re-key."""
        if drone_id in self._members:
            self._members.remove(drone_id)
            self._rekey("member_removed_compromised")

    def _rekey(self, reason: str):
        """Generate new swarm key from current membership + nonce."""
        self._nonce += 1
        self._key_generation += 1
        member_string = "|".join(self._members) + f"|NONCE:{self._nonce}"
        self._current_key = hashlib.sha256(member_string.encode()).digest()
        self._key_history.append(
            (self._key_generation, self._current_key, list(self._members)))

    def get_current_key(self) -> bytes:
        return self._current_key

    def verify_membership(self, drone_id: str) -> bool:
        """Check if a drone is in the current pod."""
        return drone_id in self._members

    def encrypt_message(self, plaintext: bytes) -> bytes:
        """XOR-based stream cipher with the pod key (simplified)."""
        if not self._current_key:
            return plaintext
        key_stream = self._current_key * ((len(plaintext) // 32) + 1)
        return bytes(a ^ b for a, b in zip(plaintext, key_stream))

    def decrypt_message(self, ciphertext: bytes) -> bytes:
        return self.encrypt_message(ciphertext)  # XOR is symmetric

    def get_status(self) -> Dict:
        return {
            "members": len(self._members),
            "member_ids": list(self._members),
            "key_generation": self._key_generation,
            "key_fingerprint": self._current_key[:4].hex() if self._current_key else "none",
            "rekeys": len(self._key_history),
        }


# ═══════════════════════════════════════════════════════════════
# 4. TEACHING — Transfer learned knowledge to new drones
# ═══════════════════════════════════════════════════════════════

@dataclass
class SwarmKnowledge:
    """Transferable knowledge package from experienced swarm."""
    source_swarm: str
    created_at: float = field(default_factory=time.time)
    # Learned sensor calibrations (from formula agents)
    sensor_calibrations: Dict[str, Dict] = field(default_factory=dict)
    # Route DTW fingerprints
    learned_routes: List[Dict] = field(default_factory=list)
    # Terrain fingerprint map samples
    terrain_fingerprints: List[Dict] = field(default_factory=list)
    # Maneuver library (turn signatures)
    maneuver_signatures: List[Dict] = field(default_factory=list)
    # Fish school evolved DNA (best weights)
    evolved_fish_dna: List[Dict] = field(default_factory=list)
    # Threat database (known jammer locations, enemy patterns)
    threat_intel: List[Dict] = field(default_factory=list)
    # Auto-combo best formula combinations
    best_combos: List[Dict] = field(default_factory=list)


class OrcaTeaching:
    """Knowledge transfer between experienced and new swarm members.

    Orcas teach hunting techniques to young calves — they don't let
    them learn from scratch. Applied to drones: when a new drone joins
    the mesh, experienced drones transfer their learned knowledge:
    - Sensor calibrations (what biases this type of IMU has)
    - Route fingerprints (sensor patterns along known routes)
    - Terrain maps (mag+baro+cell signatures at known positions)
    - Maneuver library (what a 90° turn looks like in gyro data)
    - Evolved parameters (fish school DNA, formula agent params)
    - Threat intel (known jammer positions, enemy behavior patterns)

    This means a new drone is immediately as smart as the swarm —
    no learning period needed.
    """

    def __init__(self, swarm_id: str):
        self._swarm_id = swarm_id
        self._knowledge = SwarmKnowledge(source_swarm=swarm_id)
        self._transfer_log: List[Dict] = []

    def collect_knowledge(self,
                          sensor_cals: Optional[Dict] = None,
                          routes: Optional[List[Dict]] = None,
                          terrain_fps: Optional[List[Dict]] = None,
                          maneuvers: Optional[List[Dict]] = None,
                          fish_dna: Optional[List[Dict]] = None,
                          threats: Optional[List[Dict]] = None,
                          combos: Optional[List[Dict]] = None):
        """Collect knowledge from the swarm's learned systems."""
        if sensor_cals:
            self._knowledge.sensor_calibrations.update(sensor_cals)
        if routes:
            self._knowledge.learned_routes.extend(routes)
        if terrain_fps:
            self._knowledge.terrain_fingerprints.extend(terrain_fps)
        if maneuvers:
            self._knowledge.maneuver_signatures.extend(maneuvers)
        if fish_dna:
            self._knowledge.evolved_fish_dna.extend(fish_dna)
        if threats:
            self._knowledge.threat_intel.extend(threats)
        if combos:
            self._knowledge.best_combos.extend(combos)

    def teach_new_drone(self, drone_id: str) -> SwarmKnowledge:
        """Transfer the full knowledge package to a new drone."""
        self._transfer_log.append({
            "drone_id": drone_id,
            "time": time.time(),
            "knowledge_items": self._count_items(),
        })
        return self._knowledge

    def _count_items(self) -> Dict:
        k = self._knowledge
        return {
            "sensor_calibrations": len(k.sensor_calibrations),
            "routes": len(k.learned_routes),
            "terrain_fingerprints": len(k.terrain_fingerprints),
            "maneuver_signatures": len(k.maneuver_signatures),
            "fish_dna": len(k.evolved_fish_dna),
            "threat_intel": len(k.threat_intel),
            "combos": len(k.best_combos),
        }

    def get_status(self) -> Dict:
        return {
            "swarm_id": self._swarm_id,
            "knowledge_items": self._count_items(),
            "drones_taught": len(self._transfer_log),
            "last_transfer": (self._transfer_log[-1]["drone_id"]
                              if self._transfer_log else None),
        }


# ═══════════════════════════════════════════════════════════════
# COMBINED ORCA TACTICS MANAGER
# ═══════════════════════════════════════════════════════════════

class OrcaTactics:
    """Combined orca-inspired tactical suite.

    Provides all four orca behaviors as a unified interface:
    - wave_wash: synchronized EW attack
    - carousel: rotating containment perimeter
    - pod_dialect: membership-based encryption
    - teaching: knowledge transfer to new drones
    """

    def __init__(self, swarm_id: str = "ORCA-PACK"):
        self.wave_wash = OrcaWaveWash()
        self.carousel = OrcaCarousel()
        self.pod_dialect = OrcaPodDialect()
        self.teaching = OrcaTeaching(swarm_id)
        self._swarm_id = swarm_id

    def add_drone(self, drone_id: str,
                  position: Tuple[float, float, float] = (0, 0, 0)):
        """Add a drone to all orca subsystems."""
        self.wave_wash.add_participant(drone_id, position)
        self.pod_dialect.add_member(drone_id)
        # Teach the new drone everything the swarm knows
        knowledge = self.teaching.teach_new_drone(drone_id)
        return {
            "drone_id": drone_id,
            "pod_key_gen": self.pod_dialect.get_status()["key_generation"],
            "knowledge_transferred": self.teaching._count_items(),
        }

    def remove_drone(self, drone_id: str, compromised: bool = False):
        """Remove a drone — re-keys encryption if compromised."""
        self.pod_dialect.remove_member(drone_id)
        return {
            "drone_id": drone_id,
            "rekey_triggered": compromised or True,
            "new_key_gen": self.pod_dialect.get_status()["key_generation"],
        }

    def get_full_status(self) -> Dict:
        return {
            "swarm_id": self._swarm_id,
            "wave_wash": self.wave_wash.get_status(),
            "carousel": self.carousel.get_status(),
            "pod_dialect": self.pod_dialect.get_status(),
            "teaching": self.teaching.get_status(),
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
