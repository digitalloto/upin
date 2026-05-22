"""
Dolphin Tactics — UPIN Swarm

Two strategies from dolphins:

1. MUD RING — one dolphin creates a ring of mud, fish panic and jump
   out, others catch them. For drones: one EW drone creates a ring
   of jamming around the target. Enemy drones inside lose control and
   their behaviour becomes predictable. Spotter drones track them.

2. ECHOLOCATION RELAY — dolphins pass echolocation data to each other.
   For drones: one drone's sensor data is shared across the mesh so
   all drones benefit from any single drone's detection.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class DolphinMudRing:
    """Mud ring jamming — one EW drone creates a ring of electronic denial.

    The EW drone orbits the target at radius R, jamming outward.
    Everything inside the ring loses GPS/comms. Enemy drones panic
    and behave predictably. Spotter drones outside the ring track
    the confused targets.
    """

    def __init__(self, ring_radius_m: float = 300.0,
                 jam_power_w: float = 10.0):
        self._radius = ring_radius_m
        self._jam_power = jam_power_w
        self._target: Optional[Tuple[float, float]] = None
        self._ew_drone: Optional[str] = None
        self._spotter_drones: List[str] = []
        self._orbit_angle_deg: float = 0.0
        self._orbit_speed_dps: float = 10.0  # degrees per second
        self._active = False
        self._targets_flushed: int = 0

    def set_target(self, lat: float, lon: float):
        self._target = (lat, lon)

    def assign_roles(self, ew_drone_id: str, spotter_ids: List[str]):
        self._ew_drone = ew_drone_id
        self._spotter_drones = spotter_ids

    def activate(self) -> Dict:
        if not self._target or not self._ew_drone:
            return {"error": "Need target and EW drone assigned"}
        self._active = True
        return {
            "status": "MUD_RING_ACTIVE",
            "ew_drone": self._ew_drone,
            "spotters": self._spotter_drones,
            "radius_m": self._radius,
            "target": self._target,
        }

    def tick(self, dt: float = 1.0) -> Dict:
        """Advance the orbiting EW drone."""
        if not self._active or not self._target:
            return {"status": "inactive"}

        self._orbit_angle_deg = (self._orbit_angle_deg
                                  + self._orbit_speed_dps * dt) % 360

        # Compute EW drone's orbit position
        angle_rad = math.radians(self._orbit_angle_deg)
        ew_lat = self._target[0] + (self._radius * math.cos(angle_rad)) / 111_320
        cos_lat = math.cos(math.radians(self._target[0]))
        ew_lon = self._target[1] + (self._radius * math.sin(angle_rad)) / (
            111_320 * max(cos_lat, 0.01))

        return {
            "ew_position": {"lat": ew_lat, "lon": ew_lon},
            "orbit_angle_deg": self._orbit_angle_deg,
            "jam_radius_m": self._radius,
            "denial_zone": {
                "center": self._target,
                "radius_m": self._radius * 0.8,
            },
        }

    def report_flushed_target(self):
        """A spotter detected an enemy drone flushed by the jamming ring."""
        self._targets_flushed += 1

    def get_status(self) -> Dict:
        return {
            "active": self._active,
            "ew_drone": self._ew_drone,
            "spotters": len(self._spotter_drones),
            "radius_m": self._radius,
            "targets_flushed": self._targets_flushed,
            "orbit_angle_deg": round(self._orbit_angle_deg, 1),
        }


class DolphinEchoRelay:
    """Echolocation relay — share sensor detections across the mesh.

    When one drone detects something (radar return, visual ID, acoustic),
    it broadcasts the detection to all other drones instantly. Every
    drone benefits from every other drone's sensors.
    """

    def __init__(self, relay_range_m: float = 5000.0):
        self._relay_range = relay_range_m
        self._detections: List[Dict] = []
        self._max_detections = 200

    def share_detection(self, from_drone: str, detection: Dict):
        """One drone shares a sensor detection with the mesh."""
        entry = {
            "from": from_drone,
            "detection": detection,
            "timestamp": time.time(),
            "relayed_to": [],
        }
        self._detections.append(entry)
        if len(self._detections) > self._max_detections:
            self._detections = self._detections[-self._max_detections:]

    def get_shared_picture(self, for_drone: str,
                           max_age_s: float = 30.0) -> List[Dict]:
        """Get all recent detections shared by other drones."""
        now = time.time()
        shared = []
        for det in self._detections:
            if det["from"] != for_drone and (now - det["timestamp"]) <= max_age_s:
                shared.append(det["detection"])
                det["relayed_to"].append(for_drone)
        return shared

    def get_status(self) -> Dict:
        return {
            "total_detections_shared": len(self._detections),
            "relay_range_m": self._relay_range,
        }


class DolphinTactics:
    """Combined dolphin tactical suite."""

    def __init__(self):
        self.mud_ring = DolphinMudRing()
        self.echo_relay = DolphinEchoRelay()

    def get_full_status(self) -> Dict:
        return {
            "mud_ring": self.mud_ring.get_status(),
            "echo_relay": self.echo_relay.get_status(),
        }
