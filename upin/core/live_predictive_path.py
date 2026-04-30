"""
Live Predictive Path — UPIN

Generates a dotted predictive path extending forward in time with
position markers at T+3s, T+5s, T+10s, T+30s, T+1m, T+2m, T+5m, T+10m.

The path updates EVERY tick as sensors report changes:
- Gyro detects a turn → path curves immediately
- Accelerometer detects braking → path shortens (dots closer together)
- Speed up → path extends (dots spread apart)
- Stop → dots collapse to current position

Fuses with MapMatcher (follow roads) and TerrainFollower (follow terrain).
Like a missile tracking system — one predicted path that adjusts in
real-time. The sniper shoots where the target WILL be.

Each dot carries:
- Position (lat, lon, alt)
- Confidence (fades with time — T+3s green, T+10m faint)
- Whether it's on a known road (road name)
- Terrain elevation at that point

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# Time markers along the predictive path
PATH_TIME_MARKERS = [
    ("T+3s", 3.0),
    ("T+5s", 5.0),
    ("T+10s", 10.0),
    ("T+30s", 30.0),
    ("T+1m", 60.0),
    ("T+2m", 120.0),
    ("T+5m", 300.0),
    ("T+10m", 600.0),
]


@dataclass
class PathDot:
    """A single dot on the predictive path."""
    label: str               # "T+3s", "T+5s", etc.
    time_offset_s: float     # seconds ahead of now
    lat: float
    lon: float
    altitude_m: float
    heading_deg: float
    speed_ms: float
    confidence: float        # 0-1, fades with time
    on_road: bool = False
    road_name: str = ""
    road_offset_m: float = 0.0
    terrain_elevation_m: float = 0.0


@dataclass
class PredictivePath:
    """The complete dotted predictive path at one instant."""
    timestamp: float
    origin_lat: float
    origin_lon: float
    dots: List[PathDot]
    motion_state: str       # STOPPED, CRUISING, ACCELERATING, DECELERATING, TURNING
    total_distance_m: float # total predicted distance from origin to last dot


class LivePredictivePathEngine:
    """Generates and updates the predictive dotted path every tick.

    Inputs (fed every tick):
    - Current position, heading, speed
    - Acceleration (forward component)
    - Turn rate (from gyro)
    - Optional: road network for map matching
    - Optional: terrain elevation function

    Output:
    - PredictivePath with 8 dots at time markers T+3s to T+10m
    - Each dot has position, confidence, road info, terrain info
    """

    def __init__(self):
        # Sensor state (updated every tick)
        self._lat = 0.0
        self._lon = 0.0
        self._alt = 0.0
        self._heading_deg = 0.0
        self._speed_ms = 0.0
        self._accel_ms2 = 0.0
        self._turn_rate_dps = 0.0

        # Moving averages for smooth prediction
        self._accel_window: deque = deque(maxlen=20)
        self._turn_window: deque = deque(maxlen=20)
        self._speed_window: deque = deque(maxlen=20)

        # Optional fusion modules
        self._road_snap_fn = None   # fn(lat, lon, heading) -> MatchResult or None
        self._terrain_fn = None     # fn(lat, lon) -> elevation_m
        self._route_waypoints: List[Tuple[float, float]] = []

        # History for validation
        self._path_history: deque = deque(maxlen=50)
        self._validation_count = 0
        self._validated_count = 0

    def set_road_snap(self, snap_fn):
        """Set a road-snapping function: fn(lat, lon, heading) -> dict or None."""
        self._road_snap_fn = snap_fn

    def set_terrain_source(self, terrain_fn):
        """Set terrain elevation function: fn(lat, lon) -> elevation_m."""
        self._terrain_fn = terrain_fn

    def set_route(self, waypoints: List[Tuple[float, float]]):
        """Set destination route waypoints for path to follow."""
        self._route_waypoints = waypoints

    def update(self, lat: float, lon: float, alt: float,
               heading_deg: float, speed_ms: float,
               accel_forward_ms2: float = 0.0,
               turn_rate_dps: float = 0.0) -> PredictivePath:
        """Feed current sensor state and generate the predictive path.

        Call this every tick (1-10 Hz). The path regenerates from scratch
        each time using the latest sensor state.
        """
        self._lat = lat
        self._lon = lon
        self._alt = alt
        self._heading_deg = heading_deg
        self._speed_ms = speed_ms

        self._accel_window.append(accel_forward_ms2)
        self._turn_window.append(turn_rate_dps)
        self._speed_window.append(speed_ms)

        self._accel_ms2 = sum(self._accel_window) / len(self._accel_window)
        self._turn_rate_dps = sum(self._turn_window) / len(self._turn_window)
        avg_speed = sum(self._speed_window) / len(self._speed_window)

        # Determine motion state
        motion_state = self._classify_motion()

        # Generate dots
        dots = []
        total_distance = 0.0
        cur_lat, cur_lon, cur_alt = lat, lon, alt
        cur_heading = heading_deg
        cur_speed = speed_ms
        prev_t = 0.0

        for label, t_offset in PATH_TIME_MARKERS:
            dt = t_offset - prev_t
            prev_t = t_offset

            if cur_speed < 0.1 and self._accel_ms2 <= 0:
                # Stopped — all future dots stay at current position
                dot = PathDot(
                    label=label, time_offset_s=t_offset,
                    lat=cur_lat, lon=cur_lon, altitude_m=cur_alt,
                    heading_deg=cur_heading, speed_ms=0.0,
                    confidence=0.1,
                )
                dots.append(dot)
                continue

            # Advance position using physics
            # Speed at this future time
            future_speed = max(0.0, cur_speed + self._accel_ms2 * dt)
            avg_seg_speed = (cur_speed + future_speed) / 2.0
            distance = avg_seg_speed * dt
            total_distance += distance

            # Heading at this future time (with turn rate)
            cur_heading = (cur_heading + self._turn_rate_dps * dt) % 360.0
            # Average heading for this segment
            avg_heading_rad = math.radians(
                cur_heading - self._turn_rate_dps * dt * 0.5)

            # Project position
            d_north = distance * math.cos(avg_heading_rad)
            d_east = distance * math.sin(avg_heading_rad)
            cur_lat += d_north / 111_320.0
            cos_lat = math.cos(math.radians(cur_lat))
            cur_lon += d_east / (111_320.0 * max(cos_lat, 0.01))
            cur_speed = future_speed

            # Confidence decays with time (exponential)
            confidence = math.exp(-t_offset / 300.0)  # ~0.98 at 3s, ~0.14 at 10m

            # Road snapping
            on_road = False
            road_name = ""
            road_offset = 0.0
            if self._road_snap_fn:
                match = self._road_snap_fn(cur_lat, cur_lon, cur_heading)
                if match is not None:
                    on_road = True
                    if isinstance(match, dict):
                        cur_lat = match.get("snapped_lat", cur_lat)
                        cur_lon = match.get("snapped_lon", cur_lon)
                        road_name = match.get("road_name", "")
                        road_offset = match.get("offset_m", 0)
                    elif hasattr(match, "snapped_lat"):
                        cur_lat = match.snapped_lat
                        cur_lon = match.snapped_lon
                        road_name = match.road_name
                        road_offset = match.offset_m

            # Terrain elevation
            terrain_elev = 0.0
            if self._terrain_fn:
                terrain_elev = self._terrain_fn(cur_lat, cur_lon)
                # If flying, maintain AGL
                if cur_alt > terrain_elev + 10:
                    cur_alt = terrain_elev + (alt - (
                        self._terrain_fn(lat, lon) if self._terrain_fn else 0))

            dot = PathDot(
                label=label, time_offset_s=t_offset,
                lat=cur_lat, lon=cur_lon, altitude_m=cur_alt,
                heading_deg=cur_heading, speed_ms=cur_speed,
                confidence=confidence,
                on_road=on_road, road_name=road_name,
                road_offset_m=road_offset,
                terrain_elevation_m=terrain_elev,
            )
            dots.append(dot)

        path = PredictivePath(
            timestamp=time.time(),
            origin_lat=lat, origin_lon=lon,
            dots=dots,
            motion_state=motion_state,
            total_distance_m=total_distance,
        )
        self._path_history.append(path)
        return path

    def validate_prediction(self, predicted_dot: PathDot,
                            actual_lat: float, actual_lon: float,
                            threshold_m: float = 20.0) -> Dict:
        """Validate a past prediction against actual position."""
        error = _haversine_m(predicted_dot.lat, predicted_dot.lon,
                             actual_lat, actual_lon)
        self._validation_count += 1
        validated = error <= threshold_m
        if validated:
            self._validated_count += 1
        return {
            "label": predicted_dot.label,
            "error_m": round(error, 1),
            "validated": validated,
            "threshold_m": threshold_m,
            "lifetime_accuracy": (self._validated_count / max(1, self._validation_count)),
        }

    def _classify_motion(self) -> str:
        avg_speed = sum(self._speed_window) / max(1, len(self._speed_window))
        avg_accel = self._accel_ms2
        avg_turn = abs(sum(self._turn_window) / max(1, len(self._turn_window)))

        if avg_speed < 0.5:
            return "STOPPED"
        if avg_turn > 3.0:
            return "TURNING"
        if avg_accel > 0.5:
            return "ACCELERATING"
        if avg_accel < -0.5:
            return "DECELERATING"
        return "CRUISING"

    def get_status(self) -> Dict:
        return {
            "motion_state": self._classify_motion(),
            "speed_ms": round(self._speed_ms, 1),
            "accel_avg_ms2": round(self._accel_ms2, 3),
            "turn_rate_avg_dps": round(
                sum(self._turn_window) / max(1, len(self._turn_window)), 2),
            "has_road_snap": self._road_snap_fn is not None,
            "has_terrain": self._terrain_fn is not None,
            "has_route": len(self._route_waypoints) > 0,
            "validation_rate": round(
                self._validated_count / max(1, self._validation_count), 3),
            "total_validations": self._validation_count,
            "path_updates": len(self._path_history),
        }

    def get_latest_path_summary(self) -> Optional[Dict]:
        """Get a compact summary of the latest predicted path."""
        if not self._path_history:
            return None
        path = self._path_history[-1]
        return {
            "motion_state": path.motion_state,
            "total_distance_m": round(path.total_distance_m, 1),
            "dots": [{
                "label": d.label,
                "lat": round(d.lat, 8),
                "lon": round(d.lon, 8),
                "confidence": round(d.confidence, 3),
                "speed_ms": round(d.speed_ms, 1),
                "on_road": d.on_road,
                "road": d.road_name if d.on_road else "",
            } for d in path.dots],
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
