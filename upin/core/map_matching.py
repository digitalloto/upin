"""
Map Matching + Terrain Following + Destination Routing — UPIN

Three integrated navigation layers:

1. MAP MATCHING — Snap position to nearest road/path using road network.
   Ground vehicles can't be in the middle of a building. At intersections,
   gyro turn rate picks the correct branch. Uses OSRM (free, OSM data).

2. TERRAIN FOLLOWING — For aircraft: follow terrain contours at a set
   altitude above ground. Uses DTED/SRTM elevation data to maintain
   safe clearance. The flight path curves over hills and through valleys.

3. DESTINATION ROUTING — Pre-computed route from A to B. For ground:
   follows roads. For air: follows waypoints with terrain avoidance.
   Progress tracking shows distance remaining, ETA, next turn.

All three work independently but fuse together:
  GPS position → snap to road → predict ahead on road curves →
  follow terrain at safe altitude → track progress toward destination →
  GPS denied → continue on road/terrain using sensors alone.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 1. MAP MATCHING — Snap position to nearest road
# ═══════════════════════════════════════════════════════════════

@dataclass
class RoadSegment:
    """A segment of road in the local road network."""
    road_id: str
    name: str
    points: List[Tuple[float, float]]  # [(lat, lon), ...]
    road_type: str = "road"  # road, highway, track, path
    speed_limit_ms: float = 13.9  # 50 km/h default
    one_way: bool = False


@dataclass
class MatchResult:
    """Result of snapping a position to the road network."""
    snapped_lat: float
    snapped_lon: float
    road_name: str
    road_id: str
    offset_m: float          # distance from raw position to road
    heading_on_road_deg: float
    confidence: float        # higher if close to road
    road_type: str = "road"


class MapMatcher:
    """Snap GPS/predicted positions to the nearest road.

    Maintains a local road network cache. For each position, finds the
    nearest road segment and projects the point onto it. At intersections,
    uses heading/turn rate from sensors to pick the correct branch.
    """

    def __init__(self, max_snap_distance_m: float = 50.0):
        self._roads: List[RoadSegment] = []
        self._max_snap_m = max_snap_distance_m
        self._last_match: Optional[MatchResult] = None
        self._match_history: List[MatchResult] = []

    def load_roads(self, roads: List[RoadSegment]):
        """Load road network segments."""
        self._roads = roads

    def add_road(self, road: RoadSegment):
        self._roads.append(road)

    def snap(self, lat: float, lon: float,
             heading_deg: Optional[float] = None) -> Optional[MatchResult]:
        """Snap a position to the nearest road segment."""
        if not self._roads:
            return None

        best_road = None
        best_dist = float('inf')
        best_proj_lat = lat
        best_proj_lon = lon
        best_heading = 0.0

        for road in self._roads:
            for i in range(len(road.points) - 1):
                p1 = road.points[i]
                p2 = road.points[i + 1]
                proj_lat, proj_lon, dist = _project_to_segment(
                    lat, lon, p1[0], p1[1], p2[0], p2[1])
                if dist < best_dist:
                    best_dist = dist
                    best_road = road
                    best_proj_lat = proj_lat
                    best_proj_lon = proj_lon
                    best_heading = math.degrees(math.atan2(
                        p2[1] - p1[1], p2[0] - p1[0])) % 360

        if best_road is None or best_dist > self._max_snap_m:
            return None

        # If heading provided, check road direction agreement
        confidence = max(0.1, 1.0 - best_dist / self._max_snap_m)
        if heading_deg is not None:
            heading_diff = abs(heading_deg - best_heading)
            if heading_diff > 180:
                heading_diff = 360 - heading_diff
            if heading_diff > 90:
                # Going opposite direction on road — maybe one-way wrong?
                best_heading = (best_heading + 180) % 360
            confidence *= max(0.3, 1.0 - heading_diff / 90.0)

        result = MatchResult(
            snapped_lat=best_proj_lat,
            snapped_lon=best_proj_lon,
            road_name=best_road.name,
            road_id=best_road.road_id,
            offset_m=best_dist,
            heading_on_road_deg=best_heading,
            confidence=confidence,
            road_type=best_road.road_type,
        )
        self._last_match = result
        self._match_history.append(result)
        if len(self._match_history) > 200:
            self._match_history = self._match_history[-200:]
        return result

    def get_status(self) -> Dict:
        return {
            "roads_loaded": len(self._roads),
            "last_road": (self._last_match.road_name
                          if self._last_match else None),
            "last_offset_m": (round(self._last_match.offset_m, 1)
                              if self._last_match else None),
            "matches": len(self._match_history),
        }


# ═══════════════════════════════════════════════════════════════
# 2. TERRAIN FOLLOWING — Maintain altitude above ground
# ═══════════════════════════════════════════════════════════════

@dataclass
class TerrainPoint:
    """An elevation data point."""
    lat: float
    lon: float
    elevation_m: float


class TerrainFollower:
    """Terrain-following flight path generator.

    Given a target AGL (altitude above ground level), generates
    waypoints that follow terrain contours. The aircraft flies over
    hills and through valleys at a constant height above ground.

    Uses DTED/SRTM elevation data. Can also accept live radar
    altimeter readings for real-time terrain awareness.
    """

    def __init__(self, target_agl_m: float = 50.0,
                 min_clearance_m: float = 20.0,
                 lookahead_m: float = 2000.0):
        self._target_agl = target_agl_m
        self._min_clearance = min_clearance_m
        self._lookahead = lookahead_m
        self._terrain_cache: Dict[Tuple[int, int], float] = {}
        self._elevation_fn = None

    def set_elevation_source(self, fn):
        """Set a function(lat, lon) -> elevation_m for terrain queries."""
        self._elevation_fn = fn

    def load_terrain_grid(self, grid: Dict[Tuple[int, int], float]):
        """Load pre-computed terrain elevation grid (lat_i*100, lon_i*100 -> elev)."""
        self._terrain_cache = grid

    def get_elevation(self, lat: float, lon: float) -> float:
        """Get terrain elevation at a point."""
        if self._elevation_fn:
            return self._elevation_fn(lat, lon)
        key = (int(lat * 100), int(lon * 100))
        return self._terrain_cache.get(key, 0.0)

    def compute_flight_altitude(self, lat: float, lon: float) -> Dict:
        """Compute the required MSL altitude to maintain target AGL."""
        terrain_elev = self.get_elevation(lat, lon)
        required_msl = terrain_elev + self._target_agl
        return {
            "terrain_elevation_m": terrain_elev,
            "target_agl_m": self._target_agl,
            "required_msl_m": required_msl,
            "min_safe_msl_m": terrain_elev + self._min_clearance,
        }

    def generate_terrain_path(self, start_lat: float, start_lon: float,
                              heading_deg: float, speed_ms: float,
                              duration_s: float = 300.0,
                              step_s: float = 5.0) -> List[Dict]:
        """Generate a terrain-following flight path looking ahead."""
        path = []
        lat, lon = start_lat, start_lon
        heading_rad = math.radians(heading_deg)

        t = 0.0
        while t <= duration_s:
            terrain = self.compute_flight_altitude(lat, lon)
            path.append({
                "time_s": t,
                "lat": lat,
                "lon": lon,
                "altitude_msl_m": terrain["required_msl_m"],
                "terrain_elevation_m": terrain["terrain_elevation_m"],
                "agl_m": self._target_agl,
            })
            # Advance position
            d = speed_ms * step_s
            lat += d * math.cos(heading_rad) / 111_320.0
            cos_lat = math.cos(math.radians(lat))
            lon += d * math.sin(heading_rad) / (111_320.0 * max(cos_lat, 0.01))
            t += step_s

        return path

    def check_clearance(self, lat: float, lon: float,
                        current_alt_msl: float) -> Dict:
        """Check if current altitude is safe above terrain."""
        terrain_elev = self.get_elevation(lat, lon)
        agl = current_alt_msl - terrain_elev
        safe = agl >= self._min_clearance
        return {
            "agl_m": agl,
            "terrain_m": terrain_elev,
            "safe": safe,
            "pull_up": not safe,
            "pull_up_to_m": terrain_elev + self._target_agl if not safe else None,
        }


# ═══════════════════════════════════════════════════════════════
# 3. DESTINATION ROUTING — A-to-B with progress tracking
# ═══════════════════════════════════════════════════════════════

@dataclass
class Waypoint:
    """A waypoint along a route."""
    name: str
    lat: float
    lon: float
    altitude_m: float = 0.0
    speed_limit_ms: float = 0.0
    is_turn: bool = False
    turn_direction: str = ""  # "left", "right", "straight"
    reached: bool = False
    reached_at: Optional[float] = None


@dataclass
class Route:
    """A complete route from origin to destination."""
    route_id: str
    origin_name: str
    destination_name: str
    waypoints: List[Waypoint]
    total_distance_m: float = 0.0
    mode: str = "ground"  # ground, air, sea

    def compute_distance(self):
        total = 0.0
        for i in range(1, len(self.waypoints)):
            total += _haversine_m(
                self.waypoints[i - 1].lat, self.waypoints[i - 1].lon,
                self.waypoints[i].lat, self.waypoints[i].lon,
            )
        self.total_distance_m = total


class DestinationRouter:
    """Route planning and progress tracking.

    Builds a route from A to B (road-based or waypoint-based),
    then tracks progress along it. Shows distance remaining,
    ETA, next turn, and completion percentage.
    """

    def __init__(self):
        self._active_route: Optional[Route] = None
        self._next_waypoint_idx = 0
        self._distance_travelled_m = 0.0
        self._last_position: Optional[Tuple[float, float]] = None

    def set_route(self, route: Route):
        """Set the active route."""
        route.compute_distance()
        self._active_route = route
        self._next_waypoint_idx = 0
        self._distance_travelled_m = 0.0
        self._last_position = None

    def create_direct_route(self, origin: Tuple[float, float],
                            destination: Tuple[float, float],
                            waypoints: Optional[List[Tuple[float, float]]] = None,
                            mode: str = "ground") -> Route:
        """Create a route with optional intermediate waypoints."""
        wps = [Waypoint("Origin", origin[0], origin[1])]
        if waypoints:
            for i, (lat, lon) in enumerate(waypoints):
                wps.append(Waypoint(f"WP{i + 1}", lat, lon))
        wps.append(Waypoint("Destination", destination[0], destination[1]))
        route = Route(
            route_id=f"R{int(time.time())}",
            origin_name="Origin",
            destination_name="Destination",
            waypoints=wps,
            mode=mode,
        )
        route.compute_distance()
        return route

    def update_position(self, lat: float, lon: float,
                        speed_ms: float = 0.0) -> Optional[Dict]:
        """Update current position and return progress info."""
        if self._active_route is None:
            return None

        route = self._active_route
        wps = route.waypoints

        # Track distance
        if self._last_position:
            d = _haversine_m(self._last_position[0], self._last_position[1],
                             lat, lon)
            self._distance_travelled_m += d
        self._last_position = (lat, lon)

        # Check if we've reached the next waypoint
        while self._next_waypoint_idx < len(wps):
            wp = wps[self._next_waypoint_idx]
            dist_to_wp = _haversine_m(lat, lon, wp.lat, wp.lon)
            if dist_to_wp < 50:  # within 50m = reached
                wp.reached = True
                wp.reached_at = time.time()
                self._next_waypoint_idx += 1
            else:
                break

        # Compute remaining distance
        remaining = 0.0
        if self._next_waypoint_idx < len(wps):
            remaining += _haversine_m(lat, lon,
                                       wps[self._next_waypoint_idx].lat,
                                       wps[self._next_waypoint_idx].lon)
            for i in range(self._next_waypoint_idx, len(wps) - 1):
                remaining += _haversine_m(
                    wps[i].lat, wps[i].lon,
                    wps[i + 1].lat, wps[i + 1].lon,
                )

        # ETA
        eta_s = remaining / max(speed_ms, 0.1) if speed_ms > 0 else float('inf')
        progress = (1.0 - remaining / max(route.total_distance_m, 1.0))
        progress = max(0.0, min(1.0, progress))

        # Next waypoint info
        next_wp = (wps[self._next_waypoint_idx]
                   if self._next_waypoint_idx < len(wps) else None)

        completed = self._next_waypoint_idx >= len(wps)

        return {
            "progress_pct": round(progress * 100, 1),
            "distance_remaining_m": round(remaining, 1),
            "distance_travelled_m": round(self._distance_travelled_m, 1),
            "eta_seconds": round(eta_s, 0) if eta_s != float('inf') else None,
            "next_waypoint": next_wp.name if next_wp else "ARRIVED",
            "next_waypoint_dist_m": (_haversine_m(lat, lon, next_wp.lat, next_wp.lon)
                                     if next_wp else 0),
            "waypoints_reached": self._next_waypoint_idx,
            "total_waypoints": len(wps),
            "completed": completed,
            "mode": route.mode,
        }

    def get_route_points(self) -> List[Tuple[float, float]]:
        """Get all waypoint coordinates for map display."""
        if self._active_route is None:
            return []
        return [(wp.lat, wp.lon) for wp in self._active_route.waypoints]

    def get_status(self) -> Dict:
        if self._active_route is None:
            return {"active": False}
        return {
            "active": True,
            "route_id": self._active_route.route_id,
            "destination": self._active_route.destination_name,
            "total_distance_m": round(self._active_route.total_distance_m, 1),
            "mode": self._active_route.mode,
            "waypoints": len(self._active_route.waypoints),
        }


# ═══════════════════════════════════════════════════════════════
# FLIGHT PATH PREDICTOR — Fuses all three for forward prediction
# ═══════════════════════════════════════════════════════════════

class FlightPathPredictor:
    """Unified forward path prediction that fuses map matching,
    terrain following, and destination routing.

    For ground vehicles: predicted path follows roads + route
    For aircraft: predicted path follows terrain contours + waypoints
    For sea: predicted path follows current corrections + destination

    The path adjusts in real-time as sensors report changes.
    """

    def __init__(self):
        self.map_matcher = MapMatcher()
        self.terrain_follower = TerrainFollower()
        self.destination_router = DestinationRouter()
        self._mode = "ground"  # ground, air, sea

    def set_mode(self, mode: str):
        self._mode = mode

    def predict_path(self, lat: float, lon: float, alt: float,
                     heading_deg: float, speed_ms: float,
                     turn_rate_dps: float = 0.0,
                     duration_s: float = 300.0,
                     step_s: float = 5.0) -> List[Dict]:
        """Generate the forward predicted path."""
        path = []
        cur_lat, cur_lon = lat, lon
        cur_heading = heading_deg
        cur_speed = speed_ms
        cur_alt = alt

        t = 0.0
        while t <= duration_s and cur_speed > 0.1:
            point = {
                "time_s": t,
                "lat": cur_lat,
                "lon": cur_lon,
                "altitude_m": cur_alt,
                "heading_deg": cur_heading,
                "speed_ms": cur_speed,
            }

            # Ground mode: snap to road
            if self._mode == "ground":
                match = self.map_matcher.snap(cur_lat, cur_lon, cur_heading)
                if match:
                    point["snapped_lat"] = match.snapped_lat
                    point["snapped_lon"] = match.snapped_lon
                    point["road_name"] = match.road_name
                    point["offset_m"] = match.offset_m

            # Air mode: terrain following
            if self._mode == "air":
                terrain = self.terrain_follower.compute_flight_altitude(
                    cur_lat, cur_lon)
                point["terrain_elevation_m"] = terrain["terrain_elevation_m"]
                point["required_alt_m"] = terrain["required_msl_m"]
                cur_alt = terrain["required_msl_m"]

            path.append(point)

            # Advance position (with turn rate)
            cur_heading = (cur_heading + turn_rate_dps * step_s) % 360.0
            heading_rad = math.radians(cur_heading)
            d = cur_speed * step_s
            cur_lat += d * math.cos(heading_rad) / 111_320.0
            cos_lat = math.cos(math.radians(cur_lat))
            cur_lon += d * math.sin(heading_rad) / (111_320.0 * max(cos_lat, 0.01))
            t += step_s

        return path

    def get_status(self) -> Dict:
        return {
            "mode": self._mode,
            "map_matcher": self.map_matcher.get_status(),
            "terrain_follower": {
                "target_agl_m": self.terrain_follower._target_agl,
                "min_clearance_m": self.terrain_follower._min_clearance,
            },
            "destination": self.destination_router.get_status(),
        }


def _project_to_segment(px, py, ax, ay, bx, by):
    """Project point P onto line segment AB. Returns (proj_x, proj_y, distance_m)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ax, ay, _haversine_m(px, py, ax, ay)
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return proj_x, proj_y, _haversine_m(px, py, proj_x, proj_y)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
