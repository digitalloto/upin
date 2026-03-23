"""
MC5 — Advanced Waypoint Navigation System.

Comprehensive waypoint and route management for mission planning and
execution.  Supports military waypoint types (IP, CP, RP, ingress/egress),
hold patterns (racetrack, orbit), approach procedures, time-on-target
constraints, and real-time route progress tracking.

Integrates with the UPIN fusion engine for continuous position updates and
automatic waypoint sequencing.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

from upin.core.layer_base import MissionModule
from upin.core.position import Position, NavigationOutput

_DEG_PER_M = 1.0 / 111_000.0


# ── enums ───────────────────────────────────────────────────────────

class WaypointType(Enum):
    """Military waypoint classifications."""
    FLYOVER = auto()
    FLYBY = auto()
    HOLD = auto()
    ORBIT = auto()
    LOITER = auto()
    INGRESS_POINT = auto()
    EGRESS_POINT = auto()
    INITIAL_POINT = auto()       # IP — last point before target run
    TARGET = auto()
    RALLY_POINT = auto()
    EMERGENCY = auto()
    LANDING = auto()
    TAKEOFF = auto()
    REFUEL = auto()
    HANDOFF = auto()
    CHECKPOINT = auto()
    TURN_POINT = auto()
    CONTACT_POINT = auto()
    RELEASE_POINT = auto()
    COMBAT_AIR_PATROL = auto()


class RouteType(Enum):
    """Route classification by profile."""
    DIRECT = auto()
    LOW_LEVEL = auto()
    NOE_NAP_OF_EARTH = auto()
    HIGH_ALTITUDE = auto()
    INGRESS = auto()
    EGRESS = auto()
    TRANSIT = auto()
    TACTICAL = auto()
    FERRY = auto()
    TRAINING = auto()


# ── data structures ─────────────────────────────────────────────────

@dataclass
class HoldPattern:
    """Racetrack / hippodrome hold pattern definition."""
    center: Position
    inbound_heading_deg: float = 0.0
    turn_direction: str = "right"          # "left" | "right"
    leg_length_nm: float = 4.0             # nautical miles
    altitude_m: float = 3000.0
    speed_ms: float = 80.0
    max_hold_time_s: float = 600.0         # 10 min default
    turn_radius_m: float = 0.0            # 0 → auto from speed

    def __post_init__(self):
        if self.turn_radius_m <= 0:
            # Standard-rate turn (3 deg/s) → radius = V / omega
            omega = math.radians(3.0)
            self.turn_radius_m = self.speed_ms / omega


@dataclass
class ApproachProcedure:
    """Instrument-style approach for landing."""
    initial_approach_fix: Position
    final_approach_fix: Position
    missed_approach_point: Position
    decision_altitude_m: float = 60.0      # 200 ft
    approach_heading_deg: float = 0.0
    glideslope_deg: float = 3.0
    missed_approach_altitude_m: float = 600.0


@dataclass
class NavigationWaypoint:
    """Enhanced mission waypoint."""
    wp_id: str
    name: str
    position: Position
    wp_type: WaypointType = WaypointType.FLYOVER
    sequence_number: int = 0
    speed_ms: float = 50.0
    altitude_agl_m: Optional[float] = None
    altitude_msl_m: Optional[float] = None
    heading_required: Optional[float] = None
    time_on_target: Optional[float] = None   # unix epoch
    earliest_arrival: Optional[float] = None
    latest_arrival: Optional[float] = None
    hold_pattern: Optional[HoldPattern] = None
    approach: Optional[ApproachProcedure] = None
    notes: str = ""
    is_mandatory: bool = False
    fuel_required_kg: float = 0.0
    threat_exposure: str = "LOW"
    terrain_mask_required: bool = False
    radius_m: float = 50.0                   # arrival threshold


@dataclass
class Route:
    """A complete route composed of NavigationWaypoints."""
    route_id: str
    name: str
    route_type: RouteType
    waypoints: list[NavigationWaypoint] = field(default_factory=list)
    total_distance_m: float = 0.0
    total_time_s: float = 0.0
    fuel_required_kg: float = 0.0
    max_threat_exposure: str = "LOW"
    terrain_following: bool = False
    altitude_band_min_m: float = 0.0
    altitude_band_max_m: float = 15000.0
    created_time: float = field(default_factory=time.time)
    is_active: bool = False


# ── helpers ──────────────────────────────────────────────────────────

def _bearing(a: Position, b: Position) -> float:
    """Initial bearing from *a* to *b* in degrees (0-360)."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlon = math.radians(b.longitude - a.longitude)
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2) -
         math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _destination(origin: Position, bearing_deg: float,
                 distance_m: float) -> Position:
    """Position at *distance_m* along *bearing_deg* from *origin*."""
    R = 6_371_000.0
    lat1 = math.radians(origin.latitude)
    lon1 = math.radians(origin.longitude)
    brng = math.radians(bearing_deg)
    d = distance_m / R

    lat2 = math.asin(math.sin(lat1) * math.cos(d) +
                      math.cos(lat1) * math.sin(d) * math.cos(brng))
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return Position(
        latitude=math.degrees(lat2),
        longitude=math.degrees(lon2),
        altitude=origin.altitude,
    )


# ── module ───────────────────────────────────────────────────────────

class WaypointNavigationModule(MissionModule):
    """MC5 — Advanced Waypoint Navigation.

    Manages mission routes with enhanced waypoint types, hold patterns,
    approach procedures, and real-time progress tracking.
    """

    def __init__(self):
        super().__init__(
            module_id="MC5",
            name="Advanced Waypoint Navigation",
            description="Waypoint/route management with hold patterns & TOT",
        )
        self._routes: dict[str, Route] = {}
        self._active_route_id: Optional[str] = None
        self._current_wp_index: int = 0
        self._hold_entry_time: Optional[float] = None

    def initialize(self) -> bool:
        self.is_active = True
        return True

    # ── waypoint management ──────────────────────────────────────────

    def add_waypoint(self, wp: NavigationWaypoint,
                     route_id: Optional[str] = None) -> None:
        route = self._resolve_route(route_id)
        if route is None:
            return
        wp.sequence_number = len(route.waypoints)
        route.waypoints.append(wp)
        self._recalculate_route(route)

    def remove_waypoint(self, wp_id: str,
                        route_id: Optional[str] = None) -> None:
        route = self._resolve_route(route_id)
        if route is None:
            return
        route.waypoints = [w for w in route.waypoints if w.wp_id != wp_id]
        for i, w in enumerate(route.waypoints):
            w.sequence_number = i
        self._recalculate_route(route)

    def insert_waypoint(self, wp: NavigationWaypoint, after_wp_id: str,
                        route_id: Optional[str] = None) -> None:
        route = self._resolve_route(route_id)
        if route is None:
            return
        idx = next((i for i, w in enumerate(route.waypoints)
                     if w.wp_id == after_wp_id), None)
        if idx is not None:
            route.waypoints.insert(idx + 1, wp)
            for i, w in enumerate(route.waypoints):
                w.sequence_number = i
            self._recalculate_route(route)

    def reorder_waypoints(self, wp_ids: list[str],
                          route_id: Optional[str] = None) -> None:
        route = self._resolve_route(route_id)
        if route is None:
            return
        by_id = {w.wp_id: w for w in route.waypoints}
        reordered = [by_id[wid] for wid in wp_ids if wid in by_id]
        for i, w in enumerate(reordered):
            w.sequence_number = i
        route.waypoints = reordered
        self._recalculate_route(route)

    # ── route management ─────────────────────────────────────────────

    def create_route(self, name: str, route_type: RouteType,
                     waypoints: list[NavigationWaypoint]) -> Route:
        rid = f"RTE-{int(time.time())}-{np.random.randint(1000, 9999)}"
        for i, w in enumerate(waypoints):
            w.sequence_number = i
        route = Route(route_id=rid, name=name, route_type=route_type,
                      waypoints=waypoints)
        self._recalculate_route(route)
        self._routes[rid] = route
        return route

    def get_active_route(self) -> Optional[Route]:
        if self._active_route_id:
            return self._routes.get(self._active_route_id)
        return None

    def activate_route(self, route_id: str) -> bool:
        if route_id in self._routes:
            # Deactivate previous
            if self._active_route_id and self._active_route_id in self._routes:
                self._routes[self._active_route_id].is_active = False
            self._active_route_id = route_id
            self._routes[route_id].is_active = True
            self._current_wp_index = 0
            self._hold_entry_time = None
            return True
        return False

    # ── navigation queries ───────────────────────────────────────────

    def get_next_waypoint(self, current_pos: Position) -> Optional[NavigationWaypoint]:
        route = self.get_active_route()
        if route is None or self._current_wp_index >= len(route.waypoints):
            return None
        return route.waypoints[self._current_wp_index]

    def get_bearing_to_next(self, current_pos: Position) -> Optional[float]:
        wp = self.get_next_waypoint(current_pos)
        if wp is None:
            return None
        return _bearing(current_pos, wp.position)

    def get_distance_to_next(self, current_pos: Position) -> Optional[float]:
        wp = self.get_next_waypoint(current_pos)
        if wp is None:
            return None
        return current_pos.distance_to(wp.position)

    def get_eta_to_next(self, current_pos: Position,
                        speed_ms: float = 0.0) -> Optional[float]:
        wp = self.get_next_waypoint(current_pos)
        if wp is None:
            return None
        dist = current_pos.distance_to(wp.position)
        spd = speed_ms if speed_ms > 0 else wp.speed_ms
        return dist / max(spd, 0.1)

    def check_waypoint_arrival(self, current_pos: Position,
                               threshold_m: float = 50.0) -> bool:
        """Return True if arrived at current waypoint. Advances sequence."""
        wp = self.get_next_waypoint(current_pos)
        if wp is None:
            return False
        dist = current_pos.distance_to(wp.position)
        thresh = max(threshold_m, wp.radius_m)
        if dist <= thresh:
            # Handle hold pattern
            if wp.hold_pattern:
                if self._hold_entry_time is None:
                    self._hold_entry_time = time.time()
                elapsed = time.time() - self._hold_entry_time
                if elapsed < wp.hold_pattern.max_hold_time_s:
                    return False  # still holding
                self._hold_entry_time = None

            # Handle time-on-target (wait if early)
            if wp.earliest_arrival and time.time() < wp.earliest_arrival:
                return False

            self._current_wp_index += 1
            return True
        return False

    # ── hold pattern ─────────────────────────────────────────────────

    def calculate_hold_pattern_position(self, hold: HoldPattern,
                                        elapsed_s: float) -> Position:
        """Position along a racetrack hold pattern at *elapsed_s*."""
        r = hold.turn_radius_m
        leg_m = hold.leg_length_nm * 1852.0
        # Racetrack: straight leg → 180° turn → straight leg → 180° turn
        turn_circumference = math.pi * r
        turn_time = turn_circumference / hold.speed_ms
        leg_time = leg_m / hold.speed_ms
        cycle_time = 2 * (leg_time + turn_time)

        t = elapsed_s % cycle_time
        heading = hold.inbound_heading_deg
        sign = 1.0 if hold.turn_direction == "right" else -1.0

        if t < leg_time:
            # Inbound leg
            dist = hold.speed_ms * t
            return _destination(hold.center, heading, -leg_m / 2 + dist)

        t -= leg_time
        if t < turn_time:
            # First turn (outbound)
            angle = (t / turn_time) * 180.0 * sign
            turn_center = _destination(hold.center, heading, leg_m / 2)
            perp = heading + 90.0 * sign
            return _destination(
                _destination(turn_center, perp, r),
                perp + 180.0 + angle, r,
            )

        t -= turn_time
        if t < leg_time:
            # Outbound leg
            outbound_hdg = (heading + 180.0) % 360
            dist = hold.speed_ms * t
            return _destination(hold.center, outbound_hdg, -leg_m / 2 + dist)

        # Second turn (inbound)
        t -= leg_time
        angle = (t / turn_time) * 180.0 * sign
        turn_center = _destination(hold.center, heading, -leg_m / 2)
        perp = (heading + 180.0) % 360 + 90.0 * sign
        return _destination(
            _destination(turn_center, perp, r),
            perp + 180.0 + angle, r,
        )

    # ── approach / missed approach ───────────────────────────────────

    def generate_missed_approach(self,
                                 approach: ApproachProcedure,
                                 ) -> list[NavigationWaypoint]:
        """Waypoints for a missed-approach go-around."""
        wps: list[NavigationWaypoint] = []

        # Climb straight ahead from MAP
        climb_pos = _destination(
            approach.missed_approach_point,
            approach.approach_heading_deg, 2000.0,
        )
        wps.append(NavigationWaypoint(
            wp_id=f"MA-CLB-{int(time.time())}",
            name="Missed Approach Climb",
            position=Position(
                latitude=climb_pos.latitude,
                longitude=climb_pos.longitude,
                altitude=approach.missed_approach_altitude_m,
            ),
            wp_type=WaypointType.FLYOVER,
            speed_ms=60.0,
            is_mandatory=True,
        ))

        # Turn to hold at IAF
        wps.append(NavigationWaypoint(
            wp_id=f"MA-HOLD-{int(time.time())}",
            name="Missed Approach Hold",
            position=Position(
                latitude=approach.initial_approach_fix.latitude,
                longitude=approach.initial_approach_fix.longitude,
                altitude=approach.missed_approach_altitude_m,
            ),
            wp_type=WaypointType.HOLD,
            speed_ms=60.0,
            hold_pattern=HoldPattern(
                center=approach.initial_approach_fix,
                inbound_heading_deg=approach.approach_heading_deg,
                altitude_m=approach.missed_approach_altitude_m,
            ),
            is_mandatory=True,
        ))
        return wps

    # ── divert / emergency ───────────────────────────────────────────

    def create_divert_route(self, current_pos: Position,
                            divert_point: Position) -> Route:
        """Create emergency divert route to an alternate."""
        wps = [
            NavigationWaypoint(
                wp_id=f"DVT-NOW-{int(time.time())}",
                name="Current Position",
                position=current_pos,
                wp_type=WaypointType.FLYOVER,
                speed_ms=80.0,
            ),
            NavigationWaypoint(
                wp_id=f"DVT-DST-{int(time.time())}",
                name="Divert Destination",
                position=divert_point,
                wp_type=WaypointType.LANDING,
                speed_ms=60.0,
                is_mandatory=True,
            ),
        ]
        route = self.create_route("EMERGENCY DIVERT", RouteType.DIRECT, wps)
        self.activate_route(route.route_id)
        return route

    # ── route summary ────────────────────────────────────────────────

    def get_route_summary(self) -> dict:
        route = self.get_active_route()
        if route is None:
            return {"active_route": None}
        return {
            "route_id": route.route_id,
            "name": route.name,
            "type": route.route_type.name,
            "total_waypoints": len(route.waypoints),
            "current_wp_index": self._current_wp_index,
            "total_distance_m": round(route.total_distance_m, 1),
            "total_time_s": round(route.total_time_s, 1),
            "terrain_following": route.terrain_following,
            "max_threat": route.max_threat_exposure,
            "waypoints": [
                {
                    "id": w.wp_id,
                    "name": w.name,
                    "type": w.wp_type.name,
                    "lat": round(w.position.latitude, 6),
                    "lon": round(w.position.longitude, 6),
                    "alt": w.position.altitude,
                    "speed_ms": w.speed_ms,
                    "threat": w.threat_exposure,
                    "mandatory": w.is_mandatory,
                }
                for w in route.waypoints
            ],
        }

    # ── helpers ──────────────────────────────────────────────────────

    def _resolve_route(self, route_id: Optional[str]) -> Optional[Route]:
        if route_id:
            return self._routes.get(route_id)
        return self.get_active_route()

    def _recalculate_route(self, route: Route) -> None:
        total_dist = 0.0
        total_time = 0.0
        threat_levels = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        max_threat = "LOW"

        for i in range(1, len(route.waypoints)):
            prev = route.waypoints[i - 1]
            curr = route.waypoints[i]
            seg_dist = prev.position.distance_to(curr.position)
            total_dist += seg_dist
            total_time += seg_dist / max(curr.speed_ms, 0.1)
            if threat_levels.get(curr.threat_exposure, 0) > threat_levels.get(max_threat, 0):
                max_threat = curr.threat_exposure

        route.total_distance_m = total_dist
        route.total_time_s = total_time
        route.max_threat_exposure = max_threat

    # ── MC interface ─────────────────────────────────────────────────

    def execute(self, nav_output: NavigationOutput,
                mission_params: dict) -> dict:
        current = nav_output.position
        route = self.get_active_route()
        result: dict = {
            "module": "MC5",
            "active_route": route.route_id if route else None,
            "routes_loaded": len(self._routes),
        }

        if route is None:
            return result

        # Auto-advance waypoints
        self.check_waypoint_arrival(current)

        next_wp = self.get_next_waypoint(current)
        if next_wp:
            result["next_wp"] = next_wp.name
            result["next_wp_type"] = next_wp.wp_type.name
            result["distance_to_next_m"] = round(
                self.get_distance_to_next(current) or 0, 1)
            result["bearing_to_next_deg"] = round(
                self.get_bearing_to_next(current) or 0, 1)
            result["eta_s"] = round(
                self.get_eta_to_next(current) or 0, 1)
            result["wp_progress"] = (
                f"{self._current_wp_index}/{len(route.waypoints)}")

            # Hold pattern guidance
            if next_wp.hold_pattern and self._hold_entry_time:
                elapsed = time.time() - self._hold_entry_time
                hold_pos = self.calculate_hold_pattern_position(
                    next_wp.hold_pattern, elapsed)
                result["hold_guidance_lat"] = round(hold_pos.latitude, 6)
                result["hold_guidance_lon"] = round(hold_pos.longitude, 6)
                result["hold_elapsed_s"] = round(elapsed, 1)
        else:
            result["status"] = "ROUTE_COMPLETE"

        result["confidence"] = nav_output.confidence_score
        return result
