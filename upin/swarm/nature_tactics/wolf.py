"""
Wolf Pack Tactics — UPIN Swarm

Three hunting strategies from wolf packs applied to drone swarms:

1. RELAY CHASE — wolves take turns leading so none tire. For drones:
   when lead drone's battery drops below 30%, next drone takes lead.
   Continuous pursuit with fresh leaders.

2. FLANKING — wolves split to cut off escape routes. For drones:
   swarm splits into sub-groups approaching from different vectors.
   Target is surrounded before it knows what's happening.

3. HOWL COORDINATION — wolves howl to coordinate across kilometres.
   For drones: LoRa long-range mesh for swarm-wide coordination
   when sub-groups are far apart.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class PackMember:
    """One drone in the wolf pack."""
    drone_id: str
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 0.0
    battery_pct: float = 100.0
    role: str = "chase"  # lead, chase, flank_left, flank_right, reserve
    speed_ms: float = 0.0
    heading_deg: float = 0.0
    fatigue: float = 0.0  # 0-1, increases while leading


class WolfRelayChase:
    """Relay chase — rotate lead position to conserve battery/endurance.

    The alpha leads the chase. When its battery or endurance drops,
    the beta takes over and the alpha falls back to recover.
    The pack never stops pursuing — always a fresh leader.
    """

    def __init__(self, lead_swap_battery_pct: float = 30.0,
                 lead_swap_fatigue: float = 0.8):
        self._pack: Dict[str, PackMember] = {}
        self._current_lead: Optional[str] = None
        self._swap_battery = lead_swap_battery_pct
        self._swap_fatigue = lead_swap_fatigue
        self._swap_count = 0
        self._chase_target: Optional[Tuple[float, float]] = None

    def add_member(self, drone_id: str, battery_pct: float = 100.0):
        self._pack[drone_id] = PackMember(drone_id=drone_id,
                                           battery_pct=battery_pct)
        if self._current_lead is None:
            self._current_lead = drone_id
            self._pack[drone_id].role = "lead"

    def set_target(self, lat: float, lon: float):
        self._chase_target = (lat, lon)

    def tick(self, dt: float = 1.0) -> List[Dict]:
        """Advance the chase. Returns swap events."""
        events = []
        if self._current_lead is None:
            return events

        lead = self._pack.get(self._current_lead)
        if lead is None:
            return events

        # Lead accumulates fatigue
        lead.fatigue = min(1.0, lead.fatigue + 0.005 * dt)

        # Check if lead needs to swap
        if (lead.battery_pct < self._swap_battery
                or lead.fatigue >= self._swap_fatigue):
            # Find best replacement
            candidates = [(did, m) for did, m in self._pack.items()
                          if did != self._current_lead
                          and m.battery_pct > self._swap_battery
                          and m.fatigue < 0.5]
            if candidates:
                candidates.sort(key=lambda x: (-x[1].battery_pct, x[1].fatigue))
                new_lead_id = candidates[0][0]
                old_lead_id = self._current_lead

                self._pack[old_lead_id].role = "reserve"
                self._pack[new_lead_id].role = "lead"
                self._current_lead = new_lead_id
                self._swap_count += 1

                events.append({
                    "event": "LEAD_SWAP",
                    "old_lead": old_lead_id,
                    "new_lead": new_lead_id,
                    "reason": ("low_battery" if lead.battery_pct < self._swap_battery
                               else "fatigue"),
                    "swap_number": self._swap_count,
                })

        # Recovery: reserves slowly reduce fatigue
        for m in self._pack.values():
            if m.role == "reserve":
                m.fatigue = max(0, m.fatigue - 0.002 * dt)

        return events

    def get_status(self) -> Dict:
        return {
            "pack_size": len(self._pack),
            "current_lead": self._current_lead,
            "swaps": self._swap_count,
            "target": self._chase_target,
            "members": {did: {"role": m.role, "battery": m.battery_pct,
                              "fatigue": round(m.fatigue, 2)}
                        for did, m in self._pack.items()},
        }


class WolfFlanking:
    """Flanking maneuver — split pack to surround target from multiple vectors.

    Swarm splits into 3 sub-groups:
    - Center: direct approach, maintains pressure
    - Left flank: arcs left to cut off escape
    - Right flank: arcs right to cut off escape
    Target finds itself surrounded from 3 directions.
    """

    def __init__(self, flank_angle_deg: float = 60.0,
                 flank_lead_m: float = 200.0):
        self._flank_angle = flank_angle_deg
        self._flank_lead = flank_lead_m
        self._assignments: Dict[str, str] = {}  # drone_id → group

    def assign_groups(self, drone_ids: List[str]):
        """Split drones into center, left flank, right flank."""
        n = len(drone_ids)
        center_n = max(1, n // 3)
        flank_n = (n - center_n) // 2
        for i, did in enumerate(drone_ids):
            if i < center_n:
                self._assignments[did] = "center"
            elif i < center_n + flank_n:
                self._assignments[did] = "flank_left"
            else:
                self._assignments[did] = "flank_right"

    def get_waypoint(self, drone_id: str, target_lat: float, target_lon: float,
                     own_lat: float, own_lon: float) -> Dict:
        """Get the flanking waypoint for a drone."""
        group = self._assignments.get(drone_id, "center")
        bearing_to_target = math.degrees(math.atan2(
            target_lon - own_lon, target_lat - own_lat)) % 360

        if group == "center":
            wp_lat = target_lat
            wp_lon = target_lon
        elif group == "flank_left":
            flank_bearing = math.radians(bearing_to_target - self._flank_angle)
            wp_lat = target_lat + self._flank_lead * math.cos(flank_bearing) / 111_320
            cos_lat = math.cos(math.radians(target_lat))
            wp_lon = target_lon + self._flank_lead * math.sin(flank_bearing) / (111_320 * max(cos_lat, 0.01))
        else:  # flank_right
            flank_bearing = math.radians(bearing_to_target + self._flank_angle)
            wp_lat = target_lat + self._flank_lead * math.cos(flank_bearing) / 111_320
            cos_lat = math.cos(math.radians(target_lat))
            wp_lon = target_lon + self._flank_lead * math.sin(flank_bearing) / (111_320 * max(cos_lat, 0.01))

        return {
            "drone_id": drone_id,
            "group": group,
            "waypoint_lat": wp_lat,
            "waypoint_lon": wp_lon,
            "bearing_to_target": bearing_to_target,
        }

    def get_status(self) -> Dict:
        groups = {}
        for did, g in self._assignments.items():
            groups.setdefault(g, []).append(did)
        return {"groups": {g: len(v) for g, v in groups.items()},
                "total": len(self._assignments)}


class WolfHowlCoordination:
    """Long-range coordination — howl messages across the pack.

    When sub-groups are separated, periodic howl messages keep
    them coordinated on target position and pack status.
    """

    def __init__(self, howl_interval_s: float = 30.0):
        self._interval = howl_interval_s
        self._last_howl: float = 0.0
        self._howl_log: List[Dict] = []

    def should_howl(self) -> bool:
        return (time.time() - self._last_howl) >= self._interval

    def howl(self, from_drone: str, target_lat: float, target_lon: float,
             pack_status: Dict) -> Dict:
        """Broadcast a howl message to all pack members."""
        self._last_howl = time.time()
        msg = {
            "from": from_drone,
            "target": (target_lat, target_lon),
            "pack_status": pack_status,
            "timestamp": self._last_howl,
            "howl_number": len(self._howl_log) + 1,
        }
        self._howl_log.append(msg)
        return msg

    def get_status(self) -> Dict:
        return {"howls_sent": len(self._howl_log),
                "interval_s": self._interval}


class WolfPackTactics:
    """Combined wolf pack tactical suite."""

    def __init__(self):
        self.relay_chase = WolfRelayChase()
        self.flanking = WolfFlanking()
        self.howl = WolfHowlCoordination()

    def add_drone(self, drone_id: str, battery_pct: float = 100.0):
        self.relay_chase.add_member(drone_id, battery_pct)

    def get_full_status(self) -> Dict:
        return {
            "relay_chase": self.relay_chase.get_status(),
            "flanking": self.flanking.get_status(),
            "howl": self.howl.get_status(),
        }
