"""
Additional Free API Integrations — UPIN

Find3 WiFi Fingerprinting: Indoor positioning via WiFi signal patterns.
Pedestrian Dead Reckoning: Step-counting IMU navigation for GPS-denied.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════
#  FIND3 — INDOOR WIFI FINGERPRINTING
# ══════════════════════════════════════════════════════════════════

class Find3WiFiFingerprinting:
    """
    Find3: Open-source indoor positioning via WiFi fingerprint matching.
    Source: https://github.com/schollz/find3
    API: https://cloud.internalpositioning.com (free hosted)

    How it works:
    1. LEARN phase: Walk around, scan WiFi at each room/location
    2. TRACK phase: Scan WiFi, send to Find3, get predicted location

    No API key needed for public cloud. Self-hostable.
    Accuracy: 1-3 metres indoors with good fingerprint database.
    UPIN layers: WiFiMilitaryNav (wifi_l8), UWB (uwb_d06)
    """

    API_BASE = "https://cloud.internalpositioning.com"

    def __init__(self, family: str = "upin_demo"):
        self.family = family
        self._cache: Dict[str, Dict] = {}
        self._call_count = 0

    def learn_location(self, location: str, wifi_networks: List[Dict]) -> Optional[Dict]:
        """
        Teach Find3 what WiFi looks like at a named location.
        wifi_networks: [{"mac": "AA:BB:CC:DD:EE:FF", "rssi": -55}, ...]
        """
        self._call_count += 1
        payload = {
            "d": self.family,
            "f": self.family,
            "l": location,
            "s": {n["mac"]: n["rssi"] for n in wifi_networks},
            "t": int(time.time()),
        }
        return self._post(f"/data", payload)

    def track_position(self, wifi_networks: List[Dict]) -> Optional[Dict]:
        """
        Send current WiFi scan to Find3, get predicted indoor location.
        Returns: {"location": "room_name", "probability": 0.85, ...}
        """
        self._call_count += 1
        payload = {
            "d": self.family,
            "f": self.family,
            "s": {n["mac"]: n["rssi"] for n in wifi_networks},
            "t": int(time.time()),
        }
        result = self._post(f"/track", payload)
        if result and "guesses" in result:
            guesses = result["guesses"]
            if guesses:
                best = max(guesses, key=lambda g: g.get("probability", 0))
                return {
                    "location": best.get("location", "unknown"),
                    "probability": best.get("probability", 0),
                    "all_guesses": guesses,
                    "source": "find3",
                }
        return None

    def _post(self, path: str, data: Dict) -> Optional[Dict]:
        try:
            payload = json.dumps(data).encode()
            req = urllib.request.Request(
                f"{self.API_BASE}{path}",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except Exception:
            return None

    def get_simulated_position(self, wifi_networks: List[Dict]) -> Dict:
        """Simulated indoor position when Find3 API unavailable."""
        # Use RSSI pattern to estimate room
        if not wifi_networks:
            return {"location": "unknown", "probability": 0.0, "source": "simulated"}

        strongest = max(wifi_networks, key=lambda n: n.get("rssi", -100))
        rssi = strongest.get("rssi", -70)

        # Simulated room mapping based on signal strength
        if rssi > -45:
            room = "same_room"
            prob = 0.9
        elif rssi > -60:
            room = "adjacent_room"
            prob = 0.7
        elif rssi > -75:
            room = "same_floor"
            prob = 0.5
        else:
            room = "different_floor"
            prob = 0.3

        return {"location": room, "probability": prob, "source": "simulated",
                "strongest_ap": strongest.get("mac", "unknown"), "rssi": rssi}

    def get_stats(self) -> Dict:
        return {"family": self.family, "api_calls": self._call_count}


# ══════════════════════════════════════════════════════════════════
#  PEDESTRIAN DEAD RECKONING (PDR)
# ══════════════════════════════════════════════════════════════════

class PedestrianDeadReckoning:
    """
    Step-counting IMU navigation for GPS-denied indoor/underground.
    Source: https://github.com/pedestrian-navigation/PDR concept

    Uses accelerometer to detect steps, magnetometer for heading,
    and step length model to estimate distance travelled.

    No API needed — pure math on IMU data.
    Accuracy: 1-5% of distance travelled (drifts over time).
    UPIN layers: INS (ins_l3), Odometer (odometer_l60), Optic Flow (opticflow_l43)
    """

    def __init__(self, step_length_m: float = 0.73):
        self.step_length_m = step_length_m  # Average human step
        self.position = np.array([0.0, 0.0])  # Local x, y in metres
        self.heading_deg = 0.0
        self.total_steps = 0
        self.total_distance_m = 0.0
        self._step_threshold = 1.2  # g-force threshold for step detection
        self._last_accel_z = 0.0
        self._step_cooldown = 0
        self._history: List[Dict] = []

    def update(self, accel_x: float, accel_y: float, accel_z: float,
               mag_heading_deg: float) -> Dict:
        """
        Process one IMU sample.
        accel_x/y/z in m/s^2, mag_heading_deg from magnetometer.

        Returns step info if a step was detected.
        """
        self.heading_deg = mag_heading_deg

        # Step detection using vertical acceleration peak
        accel_magnitude = math.sqrt(accel_x**2 + accel_y**2 + accel_z**2)

        step_detected = False
        if self._step_cooldown > 0:
            self._step_cooldown -= 1

        # Detect step: acceleration crosses threshold going up
        if (accel_magnitude > self._step_threshold * 9.81 and
                self._last_accel_z < self._step_threshold * 9.81 and
                self._step_cooldown == 0):
            step_detected = True
            self.total_steps += 1
            self.total_distance_m += self.step_length_m
            self._step_cooldown = 5  # Minimum 5 samples between steps

            # Update position
            heading_rad = math.radians(self.heading_deg)
            dx = self.step_length_m * math.sin(heading_rad)
            dy = self.step_length_m * math.cos(heading_rad)
            self.position[0] += dx
            self.position[1] += dy

        self._last_accel_z = accel_magnitude

        result = {
            "step_detected": step_detected,
            "total_steps": self.total_steps,
            "total_distance_m": round(self.total_distance_m, 2),
            "position_local_m": (round(self.position[0], 2), round(self.position[1], 2)),
            "heading_deg": round(self.heading_deg, 1),
            "accel_magnitude": round(accel_magnitude, 3),
        }

        if step_detected:
            self._history.append(result)

        return result

    def get_position_offset(self) -> Tuple[float, float]:
        """Get position offset from start in metres (x_east, y_north)."""
        return (self.position[0], self.position[1])

    def get_position_geo(self, start_lat: float, start_lon: float) -> Tuple[float, float]:
        """Convert local position to lat/lon given start coordinates."""
        lat = start_lat + self.position[1] / 111320.0  # North offset
        lon = start_lon + self.position[0] / (111320.0 * math.cos(math.radians(start_lat)))
        return (lat, lon)

    def simulate_walk(self, steps: int = 50, heading_deg: float = 45.0) -> List[Dict]:
        """Simulate a walk for testing."""
        results = []
        for i in range(steps * 8):  # ~8 IMU samples per step
            # Simulate accelerometer with step peaks
            phase = (i % 8) / 8.0 * 2 * math.pi
            accel_z = 9.81 + 3.0 * math.sin(phase)  # Walking oscillation
            accel_x = np.random.normal(0, 0.3)
            accel_y = np.random.normal(0, 0.3)

            # Heading with slight drift
            heading = heading_deg + np.random.normal(0, 1)

            result = self.update(accel_x, accel_y, accel_z, heading)
            if result["step_detected"]:
                results.append(result)

        return results

    def get_confidence(self) -> float:
        """PDR confidence degrades with distance (drift accumulation)."""
        if self.total_distance_m == 0:
            return 0.0
        # ~2% drift per 100m
        drift_factor = self.total_distance_m / 100.0
        return max(0.1, min(0.85, 0.85 - drift_factor * 0.02))

    def get_stats(self) -> Dict:
        return {
            "total_steps": self.total_steps,
            "total_distance_m": round(self.total_distance_m, 2),
            "position_local_m": tuple(round(p, 2) for p in self.position),
            "heading_deg": round(self.heading_deg, 1),
            "step_length_m": self.step_length_m,
            "confidence": round(self.get_confidence(), 3),
            "drift_estimate_m": round(self.total_distance_m * 0.02, 2),
        }

    def reset(self):
        """Reset PDR to starting position."""
        self.position = np.array([0.0, 0.0])
        self.total_steps = 0
        self.total_distance_m = 0.0
        self._history = []
