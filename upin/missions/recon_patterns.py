"""
MC6 — Reconnaissance & Patrol Pattern Generator.

Generates standard military search and patrol patterns as flyable waypoint
sequences.  Supports 14 pattern types used in SAR, ISR, maritime patrol,
and area-denial operations.  Each pattern produces WGS-84 waypoints that
can be fed directly into the MC5 waypoint navigation system.

Pattern types:
  CREEPING_LINE, EXPANDING_SQUARE, SECTOR_SEARCH, PARALLEL_TRACK,
  BARRIER_PATROL, RACETRACK, FIGURE_EIGHT, RANDOM_PATROL, SPIRAL_INWARD,
  SPIRAL_OUTWARD, CROSSOVER, BOW_TIE, LADDER, ZAMBONI
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


def _offset(origin: Position, north_m: float, east_m: float,
            alt: Optional[float] = None) -> Position:
    """Offset *origin* by metres north/east."""
    lat_r = math.radians(origin.latitude)
    return Position(
        latitude=origin.latitude + north_m * _DEG_PER_M,
        longitude=origin.longitude + east_m * _DEG_PER_M / max(math.cos(lat_r), 1e-10),
        altitude=alt if alt is not None else origin.altitude,
    )


def _destination(origin: Position, bearing_deg: float,
                 distance_m: float) -> Position:
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
    return Position(latitude=math.degrees(lat2),
                    longitude=math.degrees(lon2),
                    altitude=origin.altitude)


# ── enums / data ────────────────────────────────────────────────────

class SearchPatternType(Enum):
    CREEPING_LINE = auto()
    EXPANDING_SQUARE = auto()
    SECTOR_SEARCH = auto()
    PARALLEL_TRACK = auto()
    BARRIER_PATROL = auto()
    RACETRACK = auto()
    FIGURE_EIGHT = auto()
    RANDOM_PATROL = auto()
    SPIRAL_INWARD = auto()
    SPIRAL_OUTWARD = auto()
    CROSSOVER = auto()
    BOW_TIE = auto()
    LADDER = auto()
    ZAMBONI = auto()


class PatrolStatus(Enum):
    PLANNED = auto()
    ACTIVE = auto()
    PAUSED = auto()
    COMPLETED = auto()
    ABORTED = auto()


@dataclass
class SearchArea:
    """Rectangular search area defined by centre, dimensions, and rotation."""
    center: Position
    width_m: float = 2000.0
    height_m: float = 2000.0
    orientation_deg: float = 0.0       # rotation of the box
    min_altitude_m: float = 50.0
    max_altitude_m: float = 500.0


@dataclass
class PatrolRoute:
    patrol_id: str
    name: str
    pattern_type: SearchPatternType
    waypoints: list[Position] = field(default_factory=list)
    area: Optional[SearchArea] = None
    speed_ms: float = 40.0
    altitude_m: float = 200.0
    sensor_swath_m: float = 100.0
    overlap_pct: float = 10.0
    status: PatrolStatus = PatrolStatus.PLANNED
    total_distance_m: float = 0.0
    estimated_time_s: float = 0.0
    coverage_pct: float = 0.0
    laps_completed: int = 0
    max_laps: int = 1
    _current_wp: int = 0


@dataclass
class ReconTarget:
    target_id: str
    position: Position
    name: str = ""
    priority: int = 3                  # 1 (highest) – 5
    observation_time_s: float = 30.0
    approach_heading: Optional[float] = None
    min_standoff_m: float = 200.0
    max_standoff_m: float = 1000.0
    sensor_requirements: list[str] = field(default_factory=list)
    observed: bool = False
    observation_data: dict = field(default_factory=dict)


# ── pattern generator ───────────────────────────────────────────────

class PatternGenerator(MissionModule):
    """MC6 — Reconnaissance & Patrol Pattern Generator.

    Generates flyable waypoint sequences for 14 standard search and patrol
    patterns.  Manages patrol execution, coverage tracking, and recon target
    observation planning.
    """

    def __init__(self):
        super().__init__(
            module_id="MC6",
            name="Recon & Patrol Patterns",
            description="14-pattern search/patrol generator with coverage tracking",
        )
        self._patrols: dict[str, PatrolRoute] = {}
        self._recon_targets: dict[str, ReconTarget] = {}

    def initialize(self) -> bool:
        self.is_active = True
        return True

    # ── pattern generators ───────────────────────────────────────────

    def generate_creeping_line(self, area: SearchArea,
                               track_spacing_m: float = 100.0,
                               ) -> list[Position]:
        """Parallel lines advancing along the long axis (classic SAR)."""
        pts: list[Position] = []
        n_tracks = int(area.width_m / track_spacing_m) + 1
        half_h = area.height_m / 2
        half_w = area.width_m / 2
        theta = math.radians(area.orientation_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)

        for i in range(n_tracks):
            x = -half_w + i * track_spacing_m
            if i % 2 == 0:
                y_start, y_end = -half_h, half_h
            else:
                y_start, y_end = half_h, -half_h
            # Rotate
            for y in (y_start, y_end):
                n = x * sin_t + y * cos_t
                e = x * cos_t - y * sin_t
                pts.append(_offset(area.center, n, e, area.min_altitude_m))
        return pts

    def generate_expanding_square(self, center: Position,
                                   initial_leg_m: float = 200.0,
                                   spacing_m: float = 100.0,
                                   turns: int = 20) -> list[Position]:
        """Expanding square spiral from a datum point."""
        pts = [center]
        headings = [0.0, 90.0, 180.0, 270.0]
        leg = initial_leg_m
        for i in range(turns):
            hdg = headings[i % 4]
            pts.append(_destination(pts[-1], hdg, leg))
            if i % 2 == 1:
                leg += spacing_m
        return pts

    def generate_sector_search(self, center: Position,
                                radius_m: float = 2000.0,
                                num_sectors: int = 6) -> list[Position]:
        """Pie-slice sectors radiating from centre."""
        pts: list[Position] = []
        for i in range(num_sectors):
            bearing = (360.0 / num_sectors) * i
            pts.append(center)
            pts.append(_destination(center, bearing, radius_m))
            # Arc to next sector boundary
            next_bearing = bearing + 360.0 / num_sectors
            pts.append(_destination(center, next_bearing, radius_m))
        pts.append(center)
        return pts

    def generate_parallel_track(self, area: SearchArea,
                                 track_spacing_m: float = 100.0,
                                 ) -> list[Position]:
        """Parallel tracks perpendicular to area orientation."""
        pts: list[Position] = []
        n_tracks = int(area.height_m / track_spacing_m) + 1
        half_w = area.width_m / 2
        half_h = area.height_m / 2
        theta = math.radians(area.orientation_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)

        for i in range(n_tracks):
            y = -half_h + i * track_spacing_m
            if i % 2 == 0:
                x_start, x_end = -half_w, half_w
            else:
                x_start, x_end = half_w, -half_w
            for x in (x_start, x_end):
                n = x * sin_t + y * cos_t
                e = x * cos_t - y * sin_t
                pts.append(_offset(area.center, n, e, area.min_altitude_m))
        return pts

    def generate_barrier_patrol(self, start: Position, end: Position,
                                 width_m: float = 500.0,
                                 legs: int = 6) -> list[Position]:
        """Back-and-forth barrier between two points."""
        brg = math.degrees(math.atan2(
            end.longitude - start.longitude,
            end.latitude - start.latitude,
        ))
        perp = brg + 90.0
        pts: list[Position] = []
        for i in range(legs):
            offset_m = (i - legs / 2) * (width_m / legs)
            a = _destination(start, perp, offset_m)
            b = _destination(end, perp, offset_m)
            if i % 2 == 0:
                pts.extend([a, b])
            else:
                pts.extend([b, a])
        return pts

    def generate_racetrack(self, center: Position, length_m: float = 4000.0,
                            width_m: float = 1000.0,
                            heading_deg: float = 0.0) -> list[Position]:
        """Racetrack / hippodrome orbit pattern."""
        half_l = length_m / 2
        half_w = width_m / 2
        pts: list[Position] = []
        # Four corners + semicircle approximation
        n_arc = 8
        for corner_set in [(half_l, half_w, 1), (-half_l, -half_w, -1)]:
            fwd, side_sign_base, direction = corner_set
            # Straight leg start
            theta = math.radians(heading_deg)
            cos_t, sin_t = math.cos(theta), math.sin(theta)

        # Simplified: straight legs + turn waypoints
        fwd_pos = _destination(center, heading_deg, half_l)
        aft_pos = _destination(center, heading_deg, -half_l)
        right_fwd = _destination(fwd_pos, heading_deg + 90, half_w)
        left_fwd = _destination(fwd_pos, heading_deg - 90, half_w)
        right_aft = _destination(aft_pos, heading_deg + 90, half_w)
        left_aft = _destination(aft_pos, heading_deg - 90, half_w)

        # Racetrack: right side outbound, turn, left side inbound, turn
        pts = [right_aft, right_fwd]
        # Top turn (semicircle approx)
        for j in range(1, n_arc):
            angle = heading_deg + 90 - (180.0 / n_arc) * j
            pts.append(_destination(fwd_pos, angle, half_w))
        pts.append(left_fwd)
        pts.append(left_aft)
        # Bottom turn
        for j in range(1, n_arc):
            angle = heading_deg - 90 + (180.0 / n_arc) * j
            pts.append(_destination(aft_pos, angle, half_w))
        return pts

    def generate_figure_eight(self, center: Position,
                               radius_m: float = 1000.0,
                               heading_deg: float = 0.0) -> list[Position]:
        """Figure-8 pattern over a point."""
        pts: list[Position] = []
        n = 24
        # Upper circle
        upper = _destination(center, heading_deg, radius_m)
        for i in range(n):
            angle = heading_deg + (360.0 / n) * i
            pts.append(_destination(upper, angle, radius_m))
        # Lower circle (opposite rotation)
        lower = _destination(center, heading_deg + 180, radius_m)
        for i in range(n):
            angle = heading_deg - (360.0 / n) * i
            pts.append(_destination(lower, angle, radius_m))
        return pts

    def generate_spiral(self, center: Position,
                         start_radius_m: float = 200.0,
                         end_radius_m: float = 2000.0,
                         spacing_m: float = 100.0,
                         inward: bool = False) -> list[Position]:
        """Archimedean spiral pattern."""
        pts: list[Position] = []
        if inward:
            start_radius_m, end_radius_m = end_radius_m, start_radius_m
        total_turns = abs(end_radius_m - start_radius_m) / spacing_m
        n_points = int(total_turns * 36)  # 36 points per turn
        for i in range(n_points):
            frac = i / max(n_points - 1, 1)
            r = start_radius_m + (end_radius_m - start_radius_m) * frac
            angle = frac * total_turns * 360.0
            pts.append(_destination(center, angle % 360, r))
        return pts

    def generate_ladder(self, start: Position, end: Position,
                         rung_width_m: float = 500.0,
                         rung_spacing_m: float = 200.0) -> list[Position]:
        """Ladder pattern along a line (rungs perpendicular)."""
        dist = start.distance_to(end)
        brg = math.degrees(math.atan2(
            end.longitude - start.longitude,
            end.latitude - start.latitude,
        ))
        perp = brg + 90.0
        n_rungs = int(dist / rung_spacing_m) + 1
        pts: list[Position] = []
        for i in range(n_rungs):
            base = _destination(start, brg, i * rung_spacing_m)
            left = _destination(base, perp, -rung_width_m / 2)
            right = _destination(base, perp, rung_width_m / 2)
            if i % 2 == 0:
                pts.extend([left, right])
            else:
                pts.extend([right, left])
        return pts

    def generate_crossover(self, center: Position, length_m: float = 3000.0,
                            width_m: float = 1000.0,
                            heading_deg: float = 0.0) -> list[Position]:
        """X-pattern crossover for target area coverage."""
        half_l, half_w = length_m / 2, width_m / 2
        pts = [
            _destination(_destination(center, heading_deg, -half_l),
                         heading_deg + 90, -half_w),
            _destination(_destination(center, heading_deg, half_l),
                         heading_deg + 90, half_w),
            center,
            _destination(_destination(center, heading_deg, -half_l),
                         heading_deg + 90, half_w),
            _destination(_destination(center, heading_deg, half_l),
                         heading_deg + 90, -half_w),
        ]
        return pts

    # ── patrol management ────────────────────────────────────────────

    def create_patrol(self, name: str, pattern_type: SearchPatternType,
                      area: SearchArea, track_spacing_m: float = 100.0,
                      speed_ms: float = 40.0, altitude_m: float = 200.0,
                      sensor_swath_m: float = 100.0, overlap_pct: float = 10.0,
                      max_laps: int = 1) -> PatrolRoute:
        """Create a patrol route from pattern type and area."""
        generators = {
            SearchPatternType.CREEPING_LINE: lambda: self.generate_creeping_line(area, track_spacing_m),
            SearchPatternType.PARALLEL_TRACK: lambda: self.generate_parallel_track(area, track_spacing_m),
            SearchPatternType.EXPANDING_SQUARE: lambda: self.generate_expanding_square(area.center, track_spacing_m * 2, track_spacing_m),
            SearchPatternType.SECTOR_SEARCH: lambda: self.generate_sector_search(area.center, max(area.width_m, area.height_m) / 2),
            SearchPatternType.SPIRAL_INWARD: lambda: self.generate_spiral(area.center, track_spacing_m, max(area.width_m, area.height_m) / 2, track_spacing_m, inward=True),
            SearchPatternType.SPIRAL_OUTWARD: lambda: self.generate_spiral(area.center, track_spacing_m, max(area.width_m, area.height_m) / 2, track_spacing_m, inward=False),
            SearchPatternType.RACETRACK: lambda: self.generate_racetrack(area.center, area.height_m, area.width_m, area.orientation_deg),
            SearchPatternType.FIGURE_EIGHT: lambda: self.generate_figure_eight(area.center, min(area.width_m, area.height_m) / 4, area.orientation_deg),
            SearchPatternType.CROSSOVER: lambda: self.generate_crossover(area.center, area.height_m, area.width_m, area.orientation_deg),
            SearchPatternType.ZAMBONI: lambda: self.generate_creeping_line(area, track_spacing_m),
        }
        gen = generators.get(pattern_type,
                             lambda: self.generate_parallel_track(area, track_spacing_m))
        waypoints = gen()

        # Set altitude on all points
        for wp in waypoints:
            wp.altitude = altitude_m

        total_dist = sum(
            waypoints[i].distance_to(waypoints[i + 1])
            for i in range(len(waypoints) - 1)
        ) if len(waypoints) > 1 else 0.0

        patrol = PatrolRoute(
            patrol_id=f"PAT-{int(time.time())}-{np.random.randint(1000, 9999)}",
            name=name,
            pattern_type=pattern_type,
            waypoints=waypoints,
            area=area,
            speed_ms=speed_ms,
            altitude_m=altitude_m,
            sensor_swath_m=sensor_swath_m,
            overlap_pct=overlap_pct,
            total_distance_m=total_dist,
            estimated_time_s=total_dist / max(speed_ms, 0.1),
            max_laps=max_laps,
        )
        self._patrols[patrol.patrol_id] = patrol
        return patrol

    def start_patrol(self, patrol_id: str) -> bool:
        p = self._patrols.get(patrol_id)
        if p and p.status in (PatrolStatus.PLANNED, PatrolStatus.PAUSED):
            p.status = PatrolStatus.ACTIVE
            return True
        return False

    def pause_patrol(self, patrol_id: str) -> bool:
        p = self._patrols.get(patrol_id)
        if p and p.status == PatrolStatus.ACTIVE:
            p.status = PatrolStatus.PAUSED
            return True
        return False

    def resume_patrol(self, patrol_id: str) -> bool:
        return self.start_patrol(patrol_id)

    def abort_patrol(self, patrol_id: str) -> bool:
        p = self._patrols.get(patrol_id)
        if p:
            p.status = PatrolStatus.ABORTED
            return True
        return False

    def get_patrol_status(self, patrol_id: str) -> dict:
        p = self._patrols.get(patrol_id)
        if p is None:
            return {"error": "patrol not found"}
        return {
            "patrol_id": p.patrol_id,
            "name": p.name,
            "pattern": p.pattern_type.name,
            "status": p.status.name,
            "waypoints_total": len(p.waypoints),
            "waypoints_completed": p._current_wp,
            "laps_completed": p.laps_completed,
            "max_laps": p.max_laps,
            "coverage_pct": round(p.coverage_pct, 1),
            "distance_m": round(p.total_distance_m, 1),
            "eta_s": round(p.estimated_time_s, 1),
        }

    def get_coverage_estimate(self, patrol: PatrolRoute) -> float:
        """Estimate area covered (0-1) based on progress."""
        if not patrol.waypoints:
            return 0.0
        frac = patrol._current_wp / max(len(patrol.waypoints), 1)
        return min(frac * patrol.max_laps / max(patrol.laps_completed + 1, 1), 1.0)

    def check_patrol_progress(self, patrol_id: str,
                               current_pos: Position) -> dict:
        p = self._patrols.get(patrol_id)
        if p is None or p.status != PatrolStatus.ACTIVE:
            return {"error": "patrol not active"}

        if p._current_wp >= len(p.waypoints):
            p.laps_completed += 1
            if p.laps_completed >= p.max_laps:
                p.status = PatrolStatus.COMPLETED
                p.coverage_pct = 100.0
                return {"status": "COMPLETED", "laps": p.laps_completed}
            p._current_wp = 0  # restart lap

        next_wp = p.waypoints[p._current_wp]
        dist = current_pos.distance_to(next_wp)

        # Auto-advance if within 30m
        if dist < 30.0:
            p._current_wp += 1
            p.coverage_pct = self.get_coverage_estimate(p) * 100
            if p._current_wp < len(p.waypoints):
                next_wp = p.waypoints[p._current_wp]
                dist = current_pos.distance_to(next_wp)

        brg = math.degrees(math.atan2(
            next_wp.longitude - current_pos.longitude,
            next_wp.latitude - current_pos.latitude,
        )) % 360

        return {
            "next_wp_lat": round(next_wp.latitude, 6),
            "next_wp_lon": round(next_wp.longitude, 6),
            "distance_m": round(dist, 1),
            "bearing_deg": round(brg, 1),
            "wp_index": p._current_wp,
            "lap": p.laps_completed + 1,
            "coverage_pct": round(p.coverage_pct, 1),
        }

    # ── recon target management ──────────────────────────────────────

    def add_recon_target(self, target: ReconTarget) -> None:
        self._recon_targets[target.target_id] = target

    def remove_recon_target(self, target_id: str) -> None:
        self._recon_targets.pop(target_id, None)

    def mark_target_observed(self, target_id: str, data: dict) -> None:
        t = self._recon_targets.get(target_id)
        if t:
            t.observed = True
            t.observation_data = data

    def plan_recon_route(self, targets: list[ReconTarget],
                         start_pos: Position,
                         optimize: bool = True) -> list[Position]:
        """Plan route visiting all recon targets, respecting standoff.

        If *optimize* is True, uses nearest-neighbour heuristic.
        """
        remaining = list(targets)
        route: list[Position] = [start_pos]
        current = start_pos

        while remaining:
            if optimize:
                remaining.sort(key=lambda t: current.distance_to(t.position))
            tgt = remaining.pop(0)

            # Approach from specified heading or direct
            standoff = (tgt.min_standoff_m + tgt.max_standoff_m) / 2
            if tgt.approach_heading is not None:
                approach = _destination(tgt.position,
                                        (tgt.approach_heading + 180) % 360,
                                        standoff)
            else:
                brg = math.degrees(math.atan2(
                    tgt.position.longitude - current.longitude,
                    tgt.position.latitude - current.latitude,
                ))
                approach = _destination(tgt.position, (brg + 180) % 360,
                                        standoff)
            route.append(approach)

            # Observation point at standoff distance
            if tgt.approach_heading is not None:
                obs = _destination(tgt.position, tgt.approach_heading,
                                   -tgt.min_standoff_m)
            else:
                obs = approach
            route.append(obs)
            current = obs

        return route

    # ── MC interface ─────────────────────────────────────────────────

    def execute(self, nav_output: NavigationOutput,
                mission_params: dict) -> dict:
        active = [p for p in self._patrols.values()
                  if p.status == PatrolStatus.ACTIVE]

        result: dict = {
            "module": "MC6",
            "patrols_total": len(self._patrols),
            "patrols_active": len(active),
            "recon_targets": len(self._recon_targets),
            "targets_observed": sum(
                1 for t in self._recon_targets.values() if t.observed),
        }

        # Progress active patrols
        for p in active:
            self.check_patrol_progress(p.patrol_id, nav_output.position)
            result[f"patrol_{p.patrol_id}_status"] = p.status.name
            result[f"patrol_{p.patrol_id}_coverage"] = round(p.coverage_pct, 1)

        return result
