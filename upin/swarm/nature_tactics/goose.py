"""
Goose V-Formation — UPIN Swarm

Two strategies from geese:

1. V-FORMATION DRAFTING — each drone flies in the upwash of the one
   ahead, reducing energy consumption by up to 70%. The formation
   self-organises — no central assignment needed.

2. LEADERSHIP ROTATION — front drone rotates when tired/low battery.
   Next in line moves forward. The formation never breaks — continuous
   progress with fresh leaders.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class FormationSlot:
    """One position slot in the V-formation."""
    slot_id: int
    drone_id: Optional[str] = None
    offset_x_m: float = 0.0  # lateral offset from center line
    offset_y_m: float = 0.0  # longitudinal offset from leader
    energy_savings_pct: float = 0.0


class GooseVFormation:
    """V-formation with energy drafting and leadership rotation.

    The V shape creates aerodynamic upwash that reduces drag for
    following drones. Lead position has 0% savings but followers
    get up to 70% energy savings depending on position.
    """

    def __init__(self, arm_angle_deg: float = 35.0,
                 spacing_m: float = 30.0,
                 rotation_battery_pct: float = 40.0):
        self._arm_angle = arm_angle_deg
        self._spacing = spacing_m
        self._rotation_trigger = rotation_battery_pct
        self._slots: List[FormationSlot] = []
        self._leader_id: Optional[str] = None
        self._heading_deg: float = 0.0
        self._rotation_count = 0
        self._drones: Dict[str, float] = {}  # drone_id → battery_pct

    def build_formation(self, drone_ids: List[str], heading_deg: float = 0.0):
        """Build the V-formation slot assignments."""
        self._heading_deg = heading_deg
        self._slots = []
        n = len(drone_ids)
        if n == 0:
            return

        # Slot 0 = leader (tip of V)
        self._slots.append(FormationSlot(
            slot_id=0, drone_id=drone_ids[0],
            offset_x_m=0, offset_y_m=0, energy_savings_pct=0,
        ))
        self._leader_id = drone_ids[0]
        self._drones[drone_ids[0]] = 100.0

        # Alternating left/right arms of the V
        angle_rad = math.radians(self._arm_angle)
        for i in range(1, n):
            rank = (i + 1) // 2  # 1,1,2,2,3,3...
            side = 1 if i % 2 == 1 else -1  # left, right, left...
            offset_y = -rank * self._spacing * math.cos(angle_rad)
            offset_x = side * rank * self._spacing * math.sin(angle_rad)
            # Energy savings increase with position in formation
            savings = min(70.0, 20.0 + rank * 15.0)
            self._slots.append(FormationSlot(
                slot_id=i, drone_id=drone_ids[i],
                offset_x_m=offset_x, offset_y_m=offset_y,
                energy_savings_pct=savings,
            ))
            self._drones[drone_ids[i]] = 100.0

    def get_waypoint(self, drone_id: str,
                     leader_lat: float, leader_lon: float) -> Optional[Dict]:
        """Get the formation waypoint for a specific drone."""
        for slot in self._slots:
            if slot.drone_id == drone_id:
                heading_rad = math.radians(self._heading_deg)
                # Rotate offset by heading
                rx = (slot.offset_x_m * math.cos(heading_rad)
                      - slot.offset_y_m * math.sin(heading_rad))
                ry = (slot.offset_x_m * math.sin(heading_rad)
                      + slot.offset_y_m * math.cos(heading_rad))
                cos_lat = math.cos(math.radians(leader_lat))
                lat = leader_lat + ry / 111_320
                lon = leader_lon + rx / (111_320 * max(cos_lat, 0.01))
                return {
                    "lat": lat, "lon": lon,
                    "slot_id": slot.slot_id,
                    "energy_savings_pct": slot.energy_savings_pct,
                    "is_leader": slot.slot_id == 0,
                }
        return None

    def update_battery(self, drone_id: str, battery_pct: float):
        self._drones[drone_id] = battery_pct

    def check_rotation(self) -> Optional[Dict]:
        """Check if leader needs to rotate — returns swap event."""
        if not self._leader_id or not self._slots:
            return None
        leader_battery = self._drones.get(self._leader_id, 100)
        if leader_battery > self._rotation_trigger:
            return None

        # Find best replacement (highest battery in first few slots)
        candidates = [(s.drone_id, self._drones.get(s.drone_id, 0))
                       for s in self._slots[1:4] if s.drone_id]
        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[1])
        new_leader = candidates[0][0]
        old_leader = self._leader_id

        # Swap: new leader goes to slot 0, old leader goes to new leader's slot
        old_slot = next(s for s in self._slots if s.drone_id == old_leader)
        new_slot = next(s for s in self._slots if s.drone_id == new_leader)
        old_slot.drone_id, new_slot.drone_id = new_slot.drone_id, old_slot.drone_id
        self._leader_id = new_leader
        self._rotation_count += 1

        return {
            "event": "LEADER_ROTATION",
            "old_leader": old_leader,
            "new_leader": new_leader,
            "old_battery": leader_battery,
            "rotation_number": self._rotation_count,
        }

    def get_formation_energy_stats(self) -> Dict:
        total_savings = sum(s.energy_savings_pct for s in self._slots)
        avg_savings = total_savings / max(1, len(self._slots))
        return {
            "drones": len(self._slots),
            "avg_energy_savings_pct": round(avg_savings, 1),
            "leader": self._leader_id,
            "rotations": self._rotation_count,
            "arm_angle_deg": self._arm_angle,
            "spacing_m": self._spacing,
        }

    def get_status(self) -> Dict:
        return self.get_formation_energy_stats()
