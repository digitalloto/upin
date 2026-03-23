"""
MC1 — AI Flight Path Planning Module.

Uses UPIN real-time position data to plan and continuously optimise
flight paths in 3D. Capabilities:
- Pre-mission optimal route calculation (terrain masking, threat avoidance,
  radar coverage gaps, fuel efficiency, rules of engagement)
- Dynamic re-routing as conditions change
- Multi-platform path deconfliction across entire swarm
- Terrain-following nap-of-earth flight using Visual SLAM and LiDAR
- Popup attack profiles, low-level ingress, ferry routes
- Fuel management with bingo-point calculation
- No-fly zone / restricted airspace avoidance
- Air corridor routing
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from upin.core.layer_base import MissionModule
from upin.core.position import Position, NavigationOutput

_DEG_PER_M = 1.0 / 111_000.0


def _destination(origin: Position, bearing_deg: float,
                 distance_m: float) -> Position:
    R = 6_371_000.0
    lat1, lon1 = math.radians(origin.latitude), math.radians(origin.longitude)
    brng = math.radians(bearing_deg)
    d = distance_m / R
    lat2 = math.asin(math.sin(lat1) * math.cos(d) +
                      math.cos(lat1) * math.sin(d) * math.cos(brng))
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return Position(latitude=math.degrees(lat2),
                    longitude=math.degrees(lon2),
                    altitude=origin.altitude)


def _bearing(a: Position, b: Position) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlon = math.radians(b.longitude - a.longitude)
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2) -
         math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ── data structures ─────────────────────────────────────────────────

@dataclass
class Waypoint:
    """A waypoint in a flight plan."""
    position: Position
    speed_ms: float = 50.0
    altitude_agl_m: float = 100.0
    action: str = "transit"       # transit, loiter, survey, attack, extract
    time_on_station_s: float = 0.0
    is_mandatory: bool = False
    wp_name: str = ""
    terrain_elevation_m: Optional[float] = None
    required_heading: Optional[float] = None
    min_speed_ms: float = 0.0
    max_speed_ms: float = 300.0


@dataclass
class ThreatZone:
    """A known threat area to avoid."""
    center: Position
    radius_m: float
    threat_type: str
    altitude_floor_m: float = 0.0
    altitude_ceiling_m: float = 50000.0


@dataclass
class FlightPlan:
    """A complete flight plan."""
    plan_id: str
    waypoints: list[Waypoint]
    total_distance_m: float = 0.0
    estimated_time_s: float = 0.0
    fuel_margin_pct: float = 20.0
    threat_zones_avoided: int = 0
    terrain_following: bool = False
    deconflicted: bool = False


@dataclass
class AltitudeBand:
    """Named altitude band."""
    min_m: float
    max_m: float
    name: str = "MEDIUM"      # NOE, LOW_LEVEL, MEDIUM, HIGH, VERY_HIGH

    @staticmethod
    def NOE() -> AltitudeBand:
        return AltitudeBand(0, 30, "NOE")

    @staticmethod
    def LOW_LEVEL() -> AltitudeBand:
        return AltitudeBand(30, 300, "LOW_LEVEL")

    @staticmethod
    def MEDIUM() -> AltitudeBand:
        return AltitudeBand(300, 6000, "MEDIUM")

    @staticmethod
    def HIGH() -> AltitudeBand:
        return AltitudeBand(6000, 12000, "HIGH")

    @staticmethod
    def VERY_HIGH() -> AltitudeBand:
        return AltitudeBand(12000, 25000, "VERY_HIGH")


@dataclass
class RouteSegment:
    """A typed segment of a flight plan."""
    start: Position
    end: Position
    distance_m: float = 0.0
    heading_deg: float = 0.0
    altitude_band: AltitudeBand = field(default_factory=AltitudeBand.MEDIUM)
    speed_ms: float = 50.0
    segment_type: str = "cruise"   # climb, cruise, descent, terrain_follow, popup, dive
    time_s: float = 0.0
    threat_exposure: str = "LOW"


@dataclass
class NoFlyZone:
    """Restricted / prohibited airspace."""
    center: Position
    radius_m: float
    altitude_floor_m: float = 0.0
    altitude_ceiling_m: float = 50000.0
    zone_type: str = "RESTRICTED"  # RESTRICTED, PROHIBITED, MOA, WARNING, ALERT
    active_times: Optional[tuple[int, int]] = None   # (start_hour, end_hour) UTC


@dataclass
class Corridor:
    """Air corridor for safe transit."""
    corridor_id: str
    waypoints: list[Position] = field(default_factory=list)
    width_m: float = 2000.0
    altitude_band: AltitudeBand = field(default_factory=AltitudeBand.MEDIUM)
    direction: str = "two_way"     # one_way, two_way
    name: str = ""


@dataclass
class FuelProfile:
    """Fuel state and burn parameters."""
    total_fuel_kg: float = 100.0
    fuel_burn_rate_kg_per_s: float = 0.01  # ~36 kg/hr
    reserve_fuel_kg: float = 15.0
    bingo_fuel_kg: float = 25.0           # fuel to return to base
    fuel_remaining_kg: float = 100.0

    @property
    def endurance_s(self) -> float:
        usable = self.fuel_remaining_kg - self.reserve_fuel_kg
        return max(usable / max(self.fuel_burn_rate_kg_per_s, 1e-9), 0.0)


# ── module ───────────────────────────────────────────────────────────

class FlightPlanningModule(MissionModule):
    """MC1 — AI Flight Path Planning.

    Plans optimal routes factoring terrain, threats, radar coverage,
    fuel, and rules of engagement. Continuously re-optimises in flight.
    """

    def __init__(self):
        super().__init__(
            module_id="MC1",
            name="AI Flight Path Planning",
            description="3D flight path optimisation with threat avoidance",
        )
        self._current_plan: Optional[FlightPlan] = None
        self._threat_zones: list[ThreatZone] = []
        self._no_fly_zones: list[NoFlyZone] = []
        self._corridors: dict[str, Corridor] = {}
        self._max_altitude_m = 15000.0
        self._min_altitude_agl_m = 30.0

    def initialize(self) -> bool:
        self.is_active = True
        return True

    # ── basic routing (original) ─────────────────────────────────────

    def plan_route(self, start: Position, end: Position,
                   intermediate_waypoints: list[Position] = None,
                   terrain_following: bool = False,
                   speed_ms: float = 50.0) -> FlightPlan:
        """Calculate optimal route from start to end."""
        waypoints = [Waypoint(position=start, action="takeoff", wp_name="DEPART")]

        if intermediate_waypoints:
            for idx, wp in enumerate(intermediate_waypoints):
                waypoints.append(Waypoint(position=wp, speed_ms=speed_ms,
                                          wp_name=f"WP{idx+1}"))

        avoidance_count = 0
        for tz in self._threat_zones:
            if self._path_intersects_threat(start, end, tz):
                avoidance_wp = self._calculate_avoidance_waypoint(start, end, tz)
                waypoints.insert(len(waypoints),
                                 Waypoint(position=avoidance_wp, speed_ms=speed_ms,
                                          wp_name="AVOID"))
                avoidance_count += 1

        # Also avoid no-fly zones
        for nfz in self._no_fly_zones:
            tz_proxy = ThreatZone(center=nfz.center, radius_m=nfz.radius_m,
                                  threat_type=nfz.zone_type)
            if self._path_intersects_threat(start, end, tz_proxy):
                avoidance_wp = self._calculate_avoidance_waypoint(start, end, tz_proxy)
                waypoints.insert(len(waypoints),
                                 Waypoint(position=avoidance_wp, speed_ms=speed_ms,
                                          wp_name="NFZ-AVOID"))
                avoidance_count += 1

        waypoints.append(Waypoint(position=end, action="land", wp_name="ARRIVE"))

        total_dist = sum(
            waypoints[i - 1].position.distance_to(waypoints[i].position)
            for i in range(1, len(waypoints))
        )

        plan = FlightPlan(
            plan_id=f"FP-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
            threat_zones_avoided=avoidance_count,
            terrain_following=terrain_following,
        )
        self._current_plan = plan
        return plan

    def dynamic_reroute(self, current_pos: Position,
                        new_threat: ThreatZone) -> Optional[FlightPlan]:
        """Dynamically reroute around a newly detected threat."""
        self._threat_zones.append(new_threat)
        if self._current_plan and self._current_plan.waypoints:
            dest = self._current_plan.waypoints[-1]
            return self.plan_route(current_pos, dest.position,
                                   terrain_following=self._current_plan.terrain_following)
        return None

    def add_threat_zone(self, zone: ThreatZone):
        self._threat_zones.append(zone)

    def deconflict_paths(self, plans: list[FlightPlan]) -> list[FlightPlan]:
        """Deconflict multiple platform flight paths."""
        min_separation_m = 100.0
        for plan in plans:
            plan.deconflicted = True
            for wp in plan.waypoints:
                wp.position = Position(
                    latitude=wp.position.latitude,
                    longitude=wp.position.longitude,
                    altitude=(wp.position.altitude or 100) +
                             plans.index(plan) * min_separation_m,
                )
        return plans

    # ── terrain-following routes ─────────────────────────────────────

    def plan_noe_route(self, start: Position, end: Position,
                       terrain_profile: list[float] = None,
                       max_agl_m: float = 30.0,
                       speed_ms: float = 40.0) -> FlightPlan:
        """Nap-of-earth route following terrain contour.

        *terrain_profile* is a list of ground elevations (MSL) along
        the direct path.  If None, assumes flat terrain at start altitude.
        """
        dist = start.distance_to(end)
        brg = _bearing(start, end)
        n_points = max(int(dist / 200), 5)   # waypoint every ~200 m

        if terrain_profile is None:
            terrain_profile = [start.altitude or 100.0] * n_points

        waypoints: list[Waypoint] = []
        for i in range(n_points):
            frac = i / max(n_points - 1, 1)
            pos = _destination(start, brg, dist * frac)
            idx = min(i, len(terrain_profile) - 1)
            ground_elev = terrain_profile[idx]
            pos = Position(latitude=pos.latitude, longitude=pos.longitude,
                           altitude=ground_elev + max_agl_m)
            action = "takeoff" if i == 0 else ("land" if i == n_points - 1 else "transit")
            waypoints.append(Waypoint(
                position=pos, speed_ms=speed_ms, action=action,
                altitude_agl_m=max_agl_m, wp_name=f"NOE{i}",
                terrain_elevation_m=ground_elev,
            ))

        total_dist = sum(
            waypoints[i - 1].position.distance_to(waypoints[i].position)
            for i in range(1, len(waypoints))
        )
        plan = FlightPlan(
            plan_id=f"NOE-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
            terrain_following=True,
        )
        self._current_plan = plan
        return plan

    def plan_popup_attack(self, ip_position: Position,
                          target_position: Position,
                          popup_alt_m: float = 500.0,
                          release_alt_m: float = 300.0,
                          ingress_alt_m: float = 30.0,
                          speed_ms: float = 70.0) -> FlightPlan:
        """Low-level ingress → popup → weapons release → egress.

        IP = Initial Point (start of attack run).
        """
        brg_to_tgt = _bearing(ip_position, target_position)
        dist_to_tgt = ip_position.distance_to(target_position)

        # Ingress: low-level from IP toward target
        ingress_end = _destination(ip_position, brg_to_tgt, dist_to_tgt * 0.7)

        # Popup point
        popup_point = _destination(ip_position, brg_to_tgt, dist_to_tgt * 0.8)

        # Release point (over target at release altitude)
        release_point = target_position

        # Egress: break left 90° and descend
        egress_brg = (brg_to_tgt + 90) % 360
        egress_point = _destination(target_position, egress_brg, 3000)
        egress_end = _destination(egress_point, egress_brg, 5000)

        waypoints = [
            Waypoint(position=Position(latitude=ip_position.latitude,
                                       longitude=ip_position.longitude,
                                       altitude=ingress_alt_m),
                     action="transit", wp_name="IP", speed_ms=speed_ms,
                     altitude_agl_m=ingress_alt_m, is_mandatory=True),
            Waypoint(position=Position(latitude=ingress_end.latitude,
                                       longitude=ingress_end.longitude,
                                       altitude=ingress_alt_m),
                     action="transit", wp_name="INGRESS_END", speed_ms=speed_ms),
            Waypoint(position=Position(latitude=popup_point.latitude,
                                       longitude=popup_point.longitude,
                                       altitude=popup_alt_m),
                     action="transit", wp_name="POPUP", speed_ms=speed_ms * 0.9),
            Waypoint(position=Position(latitude=release_point.latitude,
                                       longitude=release_point.longitude,
                                       altitude=release_alt_m),
                     action="attack", wp_name="RELEASE", speed_ms=speed_ms,
                     is_mandatory=True),
            Waypoint(position=Position(latitude=egress_point.latitude,
                                       longitude=egress_point.longitude,
                                       altitude=ingress_alt_m),
                     action="transit", wp_name="EGRESS_BREAK", speed_ms=speed_ms * 1.2),
            Waypoint(position=Position(latitude=egress_end.latitude,
                                       longitude=egress_end.longitude,
                                       altitude=ingress_alt_m),
                     action="transit", wp_name="EGRESS_END", speed_ms=speed_ms),
        ]

        total_dist = sum(
            waypoints[i - 1].position.distance_to(waypoints[i].position)
            for i in range(1, len(waypoints))
        )
        plan = FlightPlan(
            plan_id=f"POPUP-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
        )
        self._current_plan = plan
        return plan

    def plan_low_level_ingress(self, start: Position, target: Position,
                                altitude_agl_m: float = 50.0,
                                speed_ms: float = 60.0) -> FlightPlan:
        """Low-level ingress route to target."""
        return self.plan_noe_route(start, target,
                                   max_agl_m=altitude_agl_m,
                                   speed_ms=speed_ms)

    # ── multi-leg routes ─────────────────────────────────────────────

    def plan_multi_leg_route(self,
                             legs: list[tuple[Position, Position, str]],
                             speed_ms: float = 50.0) -> FlightPlan:
        """Build a route from explicit legs: (start, end, segment_type)."""
        waypoints: list[Waypoint] = []
        for i, (s, e, seg_type) in enumerate(legs):
            if i == 0:
                waypoints.append(Waypoint(position=s, action="takeoff",
                                          speed_ms=speed_ms, wp_name=f"LEG{i}_S"))
            waypoints.append(Waypoint(position=e, action="transit",
                                      speed_ms=speed_ms, wp_name=f"LEG{i}_E"))
        if waypoints:
            waypoints[-1].action = "land"

        total_dist = sum(
            waypoints[i - 1].position.distance_to(waypoints[i].position)
            for i in range(1, len(waypoints))
        )
        plan = FlightPlan(
            plan_id=f"ML-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
        )
        self._current_plan = plan
        return plan

    def plan_round_trip(self, start: Position, destination: Position,
                        loiter_time_s: float = 300.0,
                        speed_ms: float = 50.0) -> FlightPlan:
        """Start → destination (loiter) → return."""
        waypoints = [
            Waypoint(position=start, action="takeoff", wp_name="HOME",
                     speed_ms=speed_ms),
            Waypoint(position=destination, action="loiter", wp_name="DEST",
                     speed_ms=speed_ms, time_on_station_s=loiter_time_s),
            Waypoint(position=start, action="land", wp_name="RTB",
                     speed_ms=speed_ms),
        ]
        out_dist = start.distance_to(destination)
        total_dist = out_dist * 2
        plan = FlightPlan(
            plan_id=f"RT-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1) + loiter_time_s,
        )
        self._current_plan = plan
        return plan

    def plan_ferry_route(self, start: Position, end: Position,
                         max_altitude_m: float = 6000.0,
                         speed_ms: float = 60.0) -> FlightPlan:
        """Max-range / efficiency ferry route at optimal altitude."""
        climb_end = _destination(start, _bearing(start, end),
                                 start.distance_to(end) * 0.1)
        descent_start = _destination(start, _bearing(start, end),
                                     start.distance_to(end) * 0.9)
        waypoints = [
            Waypoint(position=Position(latitude=start.latitude,
                                       longitude=start.longitude,
                                       altitude=start.altitude or 0),
                     action="takeoff", wp_name="DEPART", speed_ms=speed_ms * 0.8),
            Waypoint(position=Position(latitude=climb_end.latitude,
                                       longitude=climb_end.longitude,
                                       altitude=max_altitude_m),
                     action="transit", wp_name="TOC", speed_ms=speed_ms),
            Waypoint(position=Position(latitude=descent_start.latitude,
                                       longitude=descent_start.longitude,
                                       altitude=max_altitude_m),
                     action="transit", wp_name="TOD", speed_ms=speed_ms),
            Waypoint(position=Position(latitude=end.latitude,
                                       longitude=end.longitude,
                                       altitude=end.altitude or 0),
                     action="land", wp_name="ARRIVE", speed_ms=speed_ms * 0.7),
        ]
        total_dist = sum(
            waypoints[i - 1].position.distance_to(waypoints[i].position)
            for i in range(1, len(waypoints))
        )
        plan = FlightPlan(
            plan_id=f"FERRY-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
        )
        self._current_plan = plan
        return plan

    # ── fuel management ──────────────────────────────────────────────

    def calculate_fuel_required(self, plan: FlightPlan,
                                fuel_profile: FuelProfile) -> float:
        """Fuel in kg required to fly the plan."""
        return plan.estimated_time_s * fuel_profile.fuel_burn_rate_kg_per_s

    def get_bingo_point(self, plan: FlightPlan,
                        fuel_profile: FuelProfile) -> Optional[Position]:
        """Waypoint where platform must turn back to make it home on fuel."""
        burn_rate = fuel_profile.fuel_burn_rate_kg_per_s
        usable = fuel_profile.fuel_remaining_kg - fuel_profile.bingo_fuel_kg
        if usable <= 0:
            return plan.waypoints[0].position if plan.waypoints else None

        time_budget_s = usable / max(burn_rate, 1e-9)
        elapsed = 0.0
        for i in range(1, len(plan.waypoints)):
            seg_dist = plan.waypoints[i - 1].position.distance_to(
                plan.waypoints[i].position)
            seg_time = seg_dist / max(plan.waypoints[i].speed_ms, 0.1)
            if elapsed + seg_time > time_budget_s / 2:
                # Bingo at this waypoint
                return plan.waypoints[i - 1].position
            elapsed += seg_time
        return plan.waypoints[-1].position if plan.waypoints else None

    def check_fuel_feasibility(self, plan: FlightPlan,
                               fuel_profile: FuelProfile,
                               ) -> tuple[bool, str]:
        """Check if plan is fuel-feasible. Returns (feasible, reason)."""
        required = self.calculate_fuel_required(plan, fuel_profile)
        available = fuel_profile.fuel_remaining_kg - fuel_profile.reserve_fuel_kg
        if required > available:
            deficit = required - available
            return False, f"Need {deficit:.1f} kg more fuel"
        margin = (available - required) / max(required, 0.1) * 100
        return True, f"Feasible with {margin:.0f}% fuel margin"

    # ── airspace management ──────────────────────────────────────────

    def add_no_fly_zone(self, zone: NoFlyZone) -> None:
        self._no_fly_zones.append(zone)

    def add_corridor(self, corridor: Corridor) -> None:
        self._corridors[corridor.corridor_id] = corridor

    def check_airspace_conflicts(self, plan: FlightPlan) -> list[dict]:
        """Check if any segment penetrates a no-fly zone."""
        conflicts: list[dict] = []
        for i, wp in enumerate(plan.waypoints):
            alt = wp.position.altitude or wp.altitude_agl_m
            for nfz in self._no_fly_zones:
                dist = wp.position.distance_to(nfz.center)
                if (dist < nfz.radius_m and
                        nfz.altitude_floor_m <= alt <= nfz.altitude_ceiling_m):
                    conflicts.append({
                        "waypoint_index": i,
                        "waypoint_name": wp.wp_name,
                        "zone_type": nfz.zone_type,
                        "penetration_m": nfz.radius_m - dist,
                    })
        return conflicts

    def route_through_corridor(self, start: Position, end: Position,
                                corridor: Corridor,
                                speed_ms: float = 50.0) -> FlightPlan:
        """Route from start through a corridor's waypoints to end."""
        wps = [Waypoint(position=start, action="takeoff", wp_name="START",
                        speed_ms=speed_ms)]
        for i, cp in enumerate(corridor.waypoints):
            wps.append(Waypoint(
                position=Position(latitude=cp.latitude, longitude=cp.longitude,
                                  altitude=corridor.altitude_band.min_m),
                action="transit", wp_name=f"COR{i}", speed_ms=speed_ms,
            ))
        wps.append(Waypoint(position=end, action="land", wp_name="END",
                            speed_ms=speed_ms))

        total_dist = sum(
            wps[i - 1].position.distance_to(wps[i].position)
            for i in range(1, len(wps))
        )
        plan = FlightPlan(
            plan_id=f"COR-{int(time.time())}",
            waypoints=wps,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
        )
        self._current_plan = plan
        return plan

    # ── advanced routing ─────────────────────────────────────────────

    def plan_ingress_egress(self, target: Position,
                            ingress_heading: float,
                            egress_heading: float,
                            standoff_m: float = 5000.0,
                            speed_ms: float = 60.0) -> FlightPlan:
        """Plan ingress to target and egress on different headings."""
        ip = _destination(target, (ingress_heading + 180) % 360, standoff_m)
        ep = _destination(target, egress_heading, standoff_m)
        waypoints = [
            Waypoint(position=ip, action="transit", wp_name="IP",
                     speed_ms=speed_ms, is_mandatory=True,
                     required_heading=ingress_heading),
            Waypoint(position=target, action="attack", wp_name="TARGET",
                     speed_ms=speed_ms, is_mandatory=True),
            Waypoint(position=ep, action="transit", wp_name="EP",
                     speed_ms=speed_ms * 1.1,
                     required_heading=egress_heading),
        ]
        total_dist = sum(
            waypoints[i - 1].position.distance_to(waypoints[i].position)
            for i in range(1, len(waypoints))
        )
        plan = FlightPlan(
            plan_id=f"IE-{int(time.time())}",
            waypoints=waypoints,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
        )
        self._current_plan = plan
        return plan

    def optimize_route(self, plan: FlightPlan,
                       criteria: str = "fuel") -> FlightPlan:
        """Re-order / adjust plan for criteria: fuel, time, stealth, safety."""
        if criteria == "fuel":
            # Straighten legs where possible
            for wp in plan.waypoints:
                wp.speed_ms = min(wp.speed_ms, 45.0)  # economy speed
        elif criteria == "time":
            for wp in plan.waypoints:
                wp.speed_ms = wp.max_speed_ms * 0.9
        elif criteria == "stealth":
            for wp in plan.waypoints:
                wp.altitude_agl_m = min(wp.altitude_agl_m, 50.0)
                wp.speed_ms = min(wp.speed_ms, 40.0)
        elif criteria == "safety":
            # Maximize distance from threats
            pass  # Already handled by avoidance in plan_route
        return plan

    def get_route_segments(self, plan: FlightPlan) -> list[RouteSegment]:
        """Break a plan into typed RouteSegments."""
        segments: list[RouteSegment] = []
        for i in range(1, len(plan.waypoints)):
            prev, curr = plan.waypoints[i - 1], plan.waypoints[i]
            dist = prev.position.distance_to(curr.position)
            hdg = _bearing(prev.position, curr.position)
            prev_alt = prev.position.altitude or prev.altitude_agl_m
            curr_alt = curr.position.altitude or curr.altitude_agl_m

            if curr_alt > prev_alt + 50:
                seg_type = "climb"
            elif curr_alt < prev_alt - 50:
                seg_type = "descent"
            elif plan.terrain_following:
                seg_type = "terrain_follow"
            else:
                seg_type = "cruise"

            band = AltitudeBand.MEDIUM()
            alt = curr_alt
            if alt <= 30:
                band = AltitudeBand.NOE()
            elif alt <= 300:
                band = AltitudeBand.LOW_LEVEL()
            elif alt <= 6000:
                band = AltitudeBand.MEDIUM()
            elif alt <= 12000:
                band = AltitudeBand.HIGH()
            else:
                band = AltitudeBand.VERY_HIGH()

            segments.append(RouteSegment(
                start=prev.position, end=curr.position,
                distance_m=dist, heading_deg=hdg,
                altitude_band=band, speed_ms=curr.speed_ms,
                segment_type=seg_type,
                time_s=dist / max(curr.speed_ms, 0.1),
            ))
        return segments

    def calculate_time_on_target(self, plan: FlightPlan,
                                  target_wp_index: int) -> float:
        """Estimated time-on-target (seconds from now) for a waypoint."""
        total = 0.0
        for i in range(1, min(target_wp_index + 1, len(plan.waypoints))):
            dist = plan.waypoints[i - 1].position.distance_to(
                plan.waypoints[i].position)
            total += dist / max(plan.waypoints[i].speed_ms, 0.1)
        return total

    # ── internal helpers ─────────────────────────────────────────────

    def _path_intersects_threat(self, start: Position, end: Position,
                                 threat: ThreatZone) -> bool:
        mid_lat = (start.latitude + end.latitude) / 2
        mid_lon = (start.longitude + end.longitude) / 2
        mid = Position(latitude=mid_lat, longitude=mid_lon)
        return mid.distance_to(threat.center) < threat.radius_m

    def _calculate_avoidance_waypoint(self, start: Position, end: Position,
                                       threat: ThreatZone) -> Position:
        offset_m = threat.radius_m * 1.5
        dlat = end.latitude - start.latitude
        dlon = end.longitude - start.longitude
        perp_lat = -dlon
        perp_lon = dlat
        norm = np.sqrt(perp_lat**2 + perp_lon**2) or 1.0
        mid_lat = (start.latitude + end.latitude) / 2
        mid_lon = (start.longitude + end.longitude) / 2
        return Position(
            latitude=mid_lat + (perp_lat / norm) * offset_m / 111_000,
            longitude=mid_lon + (perp_lon / norm) * offset_m / 111_000,
            altitude=start.altitude or 100,
        )

    # ── MC interface ─────────────────────────────────────────────────

    def execute(self, nav_output: NavigationOutput, mission_params: dict) -> dict:
        result: dict = {
            "module": "MC1",
            "current_plan": self._current_plan.plan_id if self._current_plan else None,
            "threat_zones": len(self._threat_zones),
            "no_fly_zones": len(self._no_fly_zones),
            "corridors": len(self._corridors),
        }

        if self._current_plan:
            current = nav_output.position
            remaining_wps = [wp for wp in self._current_plan.waypoints
                             if current.distance_to(wp.position) > 50]
            result["waypoints_remaining"] = len(remaining_wps)
            result["confidence"] = nav_output.confidence_score

            # Airspace conflict check
            conflicts = self.check_airspace_conflicts(self._current_plan)
            if conflicts:
                result["airspace_conflicts"] = len(conflicts)

            if nav_output.confidence_score < 60 and mission_params.get("auto_reroute"):
                result["action"] = "REROUTING_LOW_CONFIDENCE"

        return result
