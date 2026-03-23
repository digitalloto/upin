"""
MC7 — Target Coordination & Engagement Management.

Manages target designation, tracking, engagement zone deconfliction,
fire-control solutions, and battle damage assessment.  Supports POINT,
AREA, LINEAR, and MOVING target types with coordinate conversion between
WGS-84, MGRS (simplified), and UTM.

╔══════════════════════════════════════════════════════════════════════╗
║  CRITICAL: Every engagement action requires EXPLICIT HUMAN          ║
║  AUTHORIZATION.  No autonomous engagement is permitted.  AI         ║
║  prepares solutions — humans decide.                                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

from upin.core.layer_base import MissionModule
from upin.core.position import Position, NavigationOutput, ThreatLevel

_DEG_PER_M = 1.0 / 111_000.0


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
        math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return Position(latitude=math.degrees(lat2),
                    longitude=math.degrees(lon2),
                    altitude=origin.altitude)


# ── enums ───────────────────────────────────────────────────────────

class TargetDesignationType(Enum):
    POINT = auto()
    AREA = auto()
    LINEAR = auto()
    MOVING = auto()


class TargetPriority(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    OPPORTUNITY = 5


class EngagementStatus(Enum):
    UNASSIGNED = auto()
    DESIGNATED = auto()
    TRACKING = auto()
    AUTHORIZED = auto()
    ENGAGED = auto()
    BDA_PENDING = auto()
    BDA_COMPLETE = auto()
    CANCELLED = auto()


class CoordinateType(Enum):
    WGS84 = auto()
    MGRS = auto()
    UTM = auto()
    GEOREF = auto()


# ── data structures ─────────────────────────────────────────────────

@dataclass
class TargetCoordinate:
    target_id: str
    designation_type: TargetDesignationType
    position: Position
    position_error_m: float = 10.0
    elevation_m: float = 0.0
    coordinate_source: str = "SENSOR"   # SIGINT, HUMINT, IMINT, SENSOR
    time_of_fix: float = field(default_factory=time.time)
    is_moving: bool = False
    velocity_ms: Optional[float] = None
    heading_deg: Optional[float] = None
    description: str = ""
    priority: TargetPriority = TargetPriority.MEDIUM
    status: EngagementStatus = EngagementStatus.UNASSIGNED
    area_radius_m: float = 0.0         # for AREA targets
    linear_length_m: float = 0.0       # for LINEAR targets
    linear_bearing_deg: float = 0.0


@dataclass
class EngagementZone:
    zone_id: str
    center: Position
    radius_m: float
    altitude_floor_m: float = 0.0
    altitude_ceiling_m: float = 50000.0
    zone_type: str = "WEZ"             # KEZ, MEZ, SHORAD, HIMAD, WEZ
    is_friendly: bool = False
    active: bool = True


@dataclass
class FireControlSolution:
    """AI-computed fire-control solution.  REQUIRES HUMAN AUTHORIZATION."""
    solution_id: str
    target: TargetCoordinate
    release_point: Position
    ingress_heading_deg: float
    egress_heading_deg: float
    time_of_flight_s: float
    probability_of_hit: float          # 0-1
    weapon_type: str = "PGM"
    fuze_setting: str = "IMPACT"
    requires_human_auth: bool = True   # ALWAYS True
    authorized: bool = False
    auth_code: Optional[str] = None
    auth_time: Optional[float] = None
    engaged: bool = False


@dataclass
class BattleDamageAssessment:
    bda_id: str
    target_id: str
    assessment_time: float = field(default_factory=time.time)
    damage_level: str = "UNKNOWN"      # DESTROYED, SEVERE, MODERATE, LIGHT, NONE, UNKNOWN
    reattack_recommended: bool = False
    confidence: float = 0.5
    sensor_used: str = "EO/IR"
    imagery_available: bool = False
    notes: str = ""


@dataclass
class TargetList:
    list_id: str
    name: str
    targets: list[TargetCoordinate] = field(default_factory=list)
    priority_order: list[str] = field(default_factory=list)
    created_time: float = field(default_factory=time.time)
    updated_time: float = field(default_factory=time.time)
    classification: str = "SECRET"


# ── module ───────────────────────────────────────────────────────────

class TargetCoordinationModule(MissionModule):
    """MC7 — Target Coordination & Engagement Management.

    Manages the full target lifecycle: designation → tracking → solution →
    human authorization → engagement → BDA.

    ╔═══════════════════════════════════════════════════════╗
    ║  EVERY ENGAGEMENT REQUIRES EXPLICIT HUMAN AUTH.      ║
    ║  AI prepares; humans decide.                         ║
    ╚═══════════════════════════════════════════════════════╝
    """

    def __init__(self):
        super().__init__(
            module_id="MC7",
            name="Target Coordination",
            description="Target designation, tracking, fire control & BDA",
        )
        self._targets: dict[str, TargetCoordinate] = {}
        self._zones: dict[str, EngagementZone] = {}
        self._solutions: dict[str, FireControlSolution] = {}
        self._bda: dict[str, list[BattleDamageAssessment]] = {}
        self._target_lists: dict[str, TargetList] = {}

    def initialize(self) -> bool:
        self.is_active = True
        return True

    # ── target management ────────────────────────────────────────────

    def designate_target(self, position: Position,
                         designation_type: TargetDesignationType = TargetDesignationType.POINT,
                         priority: TargetPriority = TargetPriority.MEDIUM,
                         source: str = "SENSOR",
                         description: str = "") -> TargetCoordinate:
        tid = f"TGT-{int(time.time())}-{np.random.randint(1000, 9999)}"
        tgt = TargetCoordinate(
            target_id=tid,
            designation_type=designation_type,
            position=position,
            coordinate_source=source,
            description=description,
            priority=priority,
            status=EngagementStatus.DESIGNATED,
        )
        self._targets[tid] = tgt
        return tgt

    def update_target_position(self, target_id: str,
                               new_position: Position,
                               error_m: float = 10.0) -> Optional[TargetCoordinate]:
        tgt = self._targets.get(target_id)
        if tgt is None:
            return None
        tgt.position = new_position
        tgt.position_error_m = error_m
        tgt.time_of_fix = time.time()
        if tgt.status == EngagementStatus.DESIGNATED:
            tgt.status = EngagementStatus.TRACKING
        return tgt

    def predict_target_position(self, target_id: str,
                                time_ahead_s: float) -> Optional[Position]:
        """Dead-reckoning prediction for moving targets."""
        tgt = self._targets.get(target_id)
        if tgt is None or not tgt.is_moving:
            return tgt.position if tgt else None
        v = tgt.velocity_ms or 0.0
        hdg = tgt.heading_deg or 0.0
        dist = v * time_ahead_s
        return _destination(tgt.position, hdg, dist)

    def get_target(self, target_id: str) -> Optional[TargetCoordinate]:
        return self._targets.get(target_id)

    def remove_target(self, target_id: str) -> None:
        self._targets.pop(target_id, None)

    def get_all_targets(self, priority_filter: Optional[TargetPriority] = None,
                        ) -> list[TargetCoordinate]:
        targets = list(self._targets.values())
        if priority_filter is not None:
            targets = [t for t in targets if t.priority == priority_filter]
        targets.sort(key=lambda t: t.priority.value)
        return targets

    # ── target lists ─────────────────────────────────────────────────

    def create_target_list(self, name: str,
                           targets: list[TargetCoordinate],
                           classification: str = "SECRET") -> TargetList:
        lid = f"TL-{int(time.time())}"
        tl = TargetList(
            list_id=lid, name=name, targets=targets,
            priority_order=[t.target_id for t in sorted(targets, key=lambda t: t.priority.value)],
            classification=classification,
        )
        self._target_lists[lid] = tl
        return tl

    def prioritize_targets(self, target_ids: list[str],
                           method: str = "priority",
                           reference_pos: Optional[Position] = None,
                           ) -> list[str]:
        """Sort targets by method: priority, distance, threat, opportunity."""
        targets = [self._targets[tid] for tid in target_ids if tid in self._targets]
        if method == "distance" and reference_pos:
            targets.sort(key=lambda t: reference_pos.distance_to(t.position))
        elif method == "threat":
            # Highest priority + closest
            targets.sort(key=lambda t: t.priority.value)
        elif method == "opportunity":
            # Moving targets first, then priority
            targets.sort(key=lambda t: (0 if t.is_moving else 1, t.priority.value))
        else:
            targets.sort(key=lambda t: t.priority.value)
        return [t.target_id for t in targets]

    def get_joint_prioritized_target_list(self) -> TargetList:
        """Unified JPTL from all designated targets."""
        all_tgts = self.get_all_targets()
        return self.create_target_list("JPTL", all_tgts, "SECRET")

    # ── engagement zones ─────────────────────────────────────────────

    def add_engagement_zone(self, center: Position, radius_m: float,
                            zone_type: str = "WEZ",
                            altitude_floor: float = 0.0,
                            altitude_ceiling: float = 50000.0,
                            is_friendly: bool = False) -> EngagementZone:
        zid = f"EZ-{int(time.time())}-{np.random.randint(100, 999)}"
        zone = EngagementZone(
            zone_id=zid, center=center, radius_m=radius_m,
            altitude_floor_m=altitude_floor, altitude_ceiling_m=altitude_ceiling,
            zone_type=zone_type, is_friendly=is_friendly,
        )
        self._zones[zid] = zone
        return zone

    def check_engagement_zone(self, position: Position) -> list[EngagementZone]:
        """Return all zones that contain *position*."""
        result = []
        alt = position.altitude or 0.0
        for z in self._zones.values():
            if not z.active:
                continue
            dist = position.distance_to(z.center)
            if (dist <= z.radius_m and
                    z.altitude_floor_m <= alt <= z.altitude_ceiling_m):
                result.append(z)
        return result

    def get_safe_corridor(self, start: Position,
                          end: Position) -> list[Position]:
        """Route around hostile engagement zones between start and end."""
        hostile = [z for z in self._zones.values()
                   if z.active and not z.is_friendly]
        if not hostile:
            return [start, end]

        route = [start]
        current = start
        for z in hostile:
            mid_lat = (current.latitude + end.latitude) / 2
            mid_lon = (current.longitude + end.longitude) / 2
            mid = Position(latitude=mid_lat, longitude=mid_lon)
            if mid.distance_to(z.center) < z.radius_m * 1.2:
                # Route around
                brg = math.degrees(math.atan2(
                    end.longitude - current.longitude,
                    end.latitude - current.latitude,
                ))
                avoid = _destination(z.center, brg + 90, z.radius_m * 1.5)
                route.append(avoid)
        route.append(end)
        return route

    # ── fire control ─────────────────────────────────────────────────

    def compute_fire_control_solution(
        self, target_id: str, platform_pos: Position,
        weapon_type: str = "PGM",
    ) -> Optional[FireControlSolution]:
        """Compute fire-control solution.  DOES NOT AUTHORIZE — human must.

        Calculates optimal release point, ingress/egress headings,
        time of flight, and probability of hit.
        """
        tgt = self._targets.get(target_id)
        if tgt is None:
            return None

        # Ingress heading: direct bearing to target
        ingress = math.degrees(math.atan2(
            tgt.position.longitude - platform_pos.longitude,
            tgt.position.latitude - platform_pos.latitude,
        )) % 360

        # Egress: 90° offset from ingress for survivability
        egress = (ingress + 90) % 360

        # Release point: weapon-dependent standoff
        standoff_m = {"PGM": 5000, "JDAM": 8000, "MISSILE": 15000,
                       "ROCKET": 2000, "GUN": 800}.get(weapon_type, 3000)
        release = _destination(tgt.position, (ingress + 180) % 360, standoff_m)

        # Time of flight estimate
        weapon_speed = {"PGM": 250, "JDAM": 200, "MISSILE": 600,
                         "ROCKET": 150, "GUN": 900}.get(weapon_type, 200)
        tof = standoff_m / weapon_speed

        # P(hit) based on position error and weapon CEP
        cep_m = {"PGM": 3, "JDAM": 10, "MISSILE": 5,
                  "ROCKET": 30, "GUN": 15}.get(weapon_type, 15)
        combined_error = math.sqrt(tgt.position_error_m**2 + cep_m**2)
        p_hit = max(0.0, min(1.0, 1.0 - (combined_error / 50.0)))

        sid = f"FCS-{int(time.time())}-{np.random.randint(100, 999)}"
        solution = FireControlSolution(
            solution_id=sid,
            target=tgt,
            release_point=release,
            ingress_heading_deg=ingress,
            egress_heading_deg=egress,
            time_of_flight_s=tof,
            probability_of_hit=round(p_hit, 2),
            weapon_type=weapon_type,
            requires_human_auth=True,
        )
        self._solutions[sid] = solution
        tgt.status = EngagementStatus.TRACKING
        return solution

    def authorize_engagement(self, solution_id: str,
                             auth_code: str) -> bool:
        """HUMAN AUTHORIZATION of a fire-control solution.

        This is the ONLY mechanism to authorize engagement.
        Returns True if authorization accepted.
        """
        sol = self._solutions.get(solution_id)
        if sol is None:
            return False
        sol.authorized = True
        sol.auth_code = auth_code
        sol.auth_time = time.time()
        sol.target.status = EngagementStatus.AUTHORIZED
        return True

    def record_engagement(self, solution_id: str) -> bool:
        sol = self._solutions.get(solution_id)
        if sol is None or not sol.authorized:
            return False
        sol.engaged = True
        sol.target.status = EngagementStatus.BDA_PENDING
        return True

    # ── BDA ──────────────────────────────────────────────────────────

    def submit_bda(self, target_id: str, damage_level: str,
                   confidence: float = 0.5, sensor_used: str = "EO/IR",
                   notes: str = "") -> BattleDamageAssessment:
        bid = f"BDA-{int(time.time())}-{np.random.randint(100, 999)}"
        bda = BattleDamageAssessment(
            bda_id=bid, target_id=target_id, damage_level=damage_level,
            confidence=confidence, sensor_used=sensor_used, notes=notes,
            reattack_recommended=damage_level in ("LIGHT", "NONE", "UNKNOWN"),
        )
        self._bda.setdefault(target_id, []).append(bda)
        tgt = self._targets.get(target_id)
        if tgt:
            tgt.status = EngagementStatus.BDA_COMPLETE
        return bda

    def get_bda_history(self, target_id: str) -> list[BattleDamageAssessment]:
        return self._bda.get(target_id, [])

    def recommend_reattack(self, target_id: str) -> bool:
        history = self._bda.get(target_id, [])
        if not history:
            return False
        return history[-1].reattack_recommended

    # ── coordinate conversion (simplified) ───────────────────────────

    @staticmethod
    def position_to_mgrs(position: Position) -> str:
        """Simplified MGRS grid reference (100m precision)."""
        zone = int((position.longitude + 180) / 6) + 1
        band = chr(int((position.latitude + 80) / 8) + ord('C'))
        if band > 'X':
            band = 'X'
        easting = int(((position.longitude % 6) / 6) * 100000)
        northing = int(((position.latitude % 8) / 8) * 100000)
        return f"{zone:02d}{band} {easting:05d} {northing:05d}"

    @staticmethod
    def mgrs_to_position(mgrs_str: str) -> Position:
        """Simplified MGRS to WGS-84 (approximate)."""
        parts = mgrs_str.strip().split()
        zone_band = parts[0]
        zone = int(zone_band[:-1])
        band = zone_band[-1]
        easting = int(parts[1]) if len(parts) > 1 else 0
        northing = int(parts[2]) if len(parts) > 2 else 0
        lon = (zone - 1) * 6 - 180 + (easting / 100000) * 6
        lat_base = (ord(band) - ord('C')) * 8 - 80
        lat = lat_base + (northing / 100000) * 8
        return Position(latitude=lat, longitude=lon)

    @staticmethod
    def format_coordinates(position: Position,
                           coord_type: CoordinateType = CoordinateType.WGS84,
                           ) -> str:
        if coord_type == CoordinateType.WGS84:
            ns = "N" if position.latitude >= 0 else "S"
            ew = "E" if position.longitude >= 0 else "W"
            return (f"{abs(position.latitude):.6f}°{ns} "
                    f"{abs(position.longitude):.6f}°{ew}")
        if coord_type == CoordinateType.MGRS:
            return TargetCoordinationModule.position_to_mgrs(position)
        # UTM simplified
        zone = int((position.longitude + 180) / 6) + 1
        return f"UTM {zone} {position.latitude:.6f} {position.longitude:.6f}"

    # ── MC interface ─────────────────────────────────────────────────

    def execute(self, nav_output: NavigationOutput,
                mission_params: dict) -> dict:
        # Update tracking for moving targets
        for tgt in self._targets.values():
            if tgt.is_moving and tgt.status == EngagementStatus.TRACKING:
                predicted = self.predict_target_position(tgt.target_id, 1.0)
                if predicted:
                    tgt.position = predicted
                    tgt.time_of_fix = time.time()

        zones_at_platform = self.check_engagement_zone(nav_output.position)

        return {
            "module": "MC7",
            "targets_total": len(self._targets),
            "targets_by_status": {
                s.name: sum(1 for t in self._targets.values() if t.status == s)
                for s in EngagementStatus
                if any(t.status == s for t in self._targets.values())
            },
            "engagement_zones": len(self._zones),
            "platform_in_zones": [z.zone_id for z in zones_at_platform],
            "pending_solutions": sum(
                1 for s in self._solutions.values() if not s.authorized),
            "authorized_solutions": sum(
                1 for s in self._solutions.values() if s.authorized),
            "bda_count": sum(len(v) for v in self._bda.values()),
        }
