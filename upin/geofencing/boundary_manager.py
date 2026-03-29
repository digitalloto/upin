"""
Geographic Boundary Manager — UPIN Geofencing

Enforces operational boundaries, no-fly zones, territorial limits,
and safety perimeters. Prevents UPIN from operating outside
authorized areas and triggers alerts for boundary violations.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.position import Position


class BoundaryType(Enum):
    NO_FLY_ZONE = auto()
    RESTRICTED_AREA = auto()
    TERRITORIAL_LIMIT = auto()
    OPERATIONAL_BOUNDARY = auto()
    SAFETY_PERIMETER = auto()
    MISSION_AREA = auto()


class ViolationType(Enum):
    ENTRY = auto()         # Entered restricted area
    EXIT = auto()          # Left authorized area
    APPROACH = auto()      # Approaching boundary
    LOITERING = auto()     # Staying near boundary too long


@dataclass
class GeographicBoundary:
    """One geographic boundary definition."""
    boundary_id: str
    name: str
    boundary_type: BoundaryType
    vertices: List[Tuple[float, float]]  # lat, lon pairs defining polygon
    altitude_min_m: Optional[float] = None
    altitude_max_m: Optional[float] = None
    active: bool = True
    warning_distance_m: float = 500.0    # Distance to trigger approach warning


@dataclass
class BoundaryViolation:
    """One boundary violation event."""
    violation_id: str
    timestamp: float
    boundary: GeographicBoundary
    violation_type: ViolationType
    position: Position
    distance_to_boundary_m: float
    severity: float  # 0.0-1.0


class BoundaryManager:
    """
    Manages geographic boundaries and detects violations.

    Enforces operational limits and safety zones for UPIN operations.
    """

    def __init__(self):
        self.boundaries: List[GeographicBoundary] = []
        self.violation_history: List[BoundaryViolation] = []
        self.current_violations: List[BoundaryViolation] = []

        # Load default boundaries
        self._load_default_boundaries()

    def add_boundary(self, boundary: GeographicBoundary) -> None:
        """Add a new geographic boundary."""
        self.boundaries.append(boundary)

    def check_position(self, position: Position) -> List[BoundaryViolation]:
        """Check position against all boundaries and return violations."""
        violations = []
        current_time = time.time()

        for boundary in self.boundaries:
            if not boundary.active:
                continue

            violation = self._check_boundary_violation(position, boundary, current_time)
            if violation:
                violations.append(violation)

        self.current_violations = violations
        self.violation_history.extend(violations)

        return violations

    def _check_boundary_violation(
        self,
        position: Position,
        boundary: GeographicBoundary,
        timestamp: float
    ) -> Optional[BoundaryViolation]:
        """Check if position violates a specific boundary."""

        inside = self._point_in_polygon(
            position.latitude, position.longitude, boundary.vertices
        )
        distance = self._distance_to_polygon(
            position.latitude, position.longitude, boundary.vertices
        )

        violation_type = None
        severity = 0.0

        if boundary.boundary_type in [BoundaryType.NO_FLY_ZONE, BoundaryType.RESTRICTED_AREA]:
            if inside:
                violation_type = ViolationType.ENTRY
                severity = 1.0
            elif distance < boundary.warning_distance_m:
                violation_type = ViolationType.APPROACH
                severity = 1.0 - (distance / boundary.warning_distance_m)

        elif boundary.boundary_type in [BoundaryType.OPERATIONAL_BOUNDARY, BoundaryType.MISSION_AREA]:
            if not inside:
                violation_type = ViolationType.EXIT
                severity = min(1.0, distance / boundary.warning_distance_m)

        if violation_type:
            return BoundaryViolation(
                violation_id=f"viol_{int(timestamp*1000)}_{boundary.boundary_id}",
                timestamp=timestamp,
                boundary=boundary,
                violation_type=violation_type,
                position=position,
                distance_to_boundary_m=distance,
                severity=severity
            )

        return None

    def _point_in_polygon(self, lat: float, lon: float, vertices: List[Tuple[float, float]]) -> bool:
        """Check if point is inside polygon using ray casting algorithm."""
        if len(vertices) < 3:
            return False

        inside = False
        j = len(vertices) - 1

        for i in range(len(vertices)):
            xi, yi = vertices[i]
            xj, yj = vertices[j]

            if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi) + xi):
                inside = not inside

            j = i

        return inside

    def _distance_to_polygon(self, lat: float, lon: float, vertices: List[Tuple[float, float]]) -> float:
        """Calculate minimum distance from point to polygon boundary."""
        if len(vertices) < 2:
            return float('inf')

        min_distance = float('inf')

        for i in range(len(vertices)):
            j = (i + 1) % len(vertices)
            lat1, lon1 = vertices[i]
            lat2, lon2 = vertices[j]

            dist = self._distance_point_to_line(lat, lon, lat1, lon1, lat2, lon2)
            min_distance = min(min_distance, dist)

        return min_distance

    def _distance_point_to_line(
        self,
        px: float, py: float,
        x1: float, y1: float,
        x2: float, y2: float
    ) -> float:
        """Calculate distance from point to line segment in meters."""

        px_m = px * 111320
        py_m = py * 111320 * math.cos(math.radians(px))
        x1_m = x1 * 111320
        y1_m = y1 * 111320 * math.cos(math.radians(x1))
        x2_m = x2 * 111320
        y2_m = y2 * 111320 * math.cos(math.radians(x2))

        dx = px_m - x1_m
        dy = py_m - y1_m

        line_dx = x2_m - x1_m
        line_dy = y2_m - y1_m
        line_length_sq = line_dx**2 + line_dy**2

        if line_length_sq == 0:
            return math.sqrt(dx**2 + dy**2)

        t = max(0, min(1, (dx * line_dx + dy * line_dy) / line_length_sq))

        closest_x = x1_m + t * line_dx
        closest_y = y1_m + t * line_dy

        return math.sqrt((px_m - closest_x)**2 + (py_m - closest_y)**2)

    def _load_default_boundaries(self) -> None:
        """Load default boundaries for operations."""

        mumbai_boundary = GeographicBoundary(
            boundary_id="mumbai_ops",
            name="Mumbai Operational Area",
            boundary_type=BoundaryType.OPERATIONAL_BOUNDARY,
            vertices=[
                (18.85, 72.75), (18.85, 72.95),
                (19.35, 72.95), (19.35, 72.75)
            ],
            warning_distance_m=1000.0
        )

        chennai_boundary = GeographicBoundary(
            boundary_id="chennai_ops",
            name="Chennai Operational Area",
            boundary_type=BoundaryType.OPERATIONAL_BOUNDARY,
            vertices=[
                (12.95, 80.15), (12.95, 80.35),
                (13.25, 80.35), (13.25, 80.15)
            ],
            warning_distance_m=1000.0
        )

        airport_nfz = GeographicBoundary(
            boundary_id="mumbai_airport_nfz",
            name="Mumbai Airport No-Fly Zone",
            boundary_type=BoundaryType.NO_FLY_ZONE,
            vertices=[
                (19.08, 72.86), (19.08, 72.88),
                (19.10, 72.88), (19.10, 72.86)
            ],
            altitude_max_m=500.0,
            warning_distance_m=2000.0
        )

        self.boundaries.extend([mumbai_boundary, chennai_boundary, airport_nfz])

    def get_boundary_status(self) -> dict:
        """Get status of all boundaries and recent violations."""
        recent_violations = [v for v in self.violation_history if time.time() - v.timestamp < 3600]

        return {
            'total_boundaries': len(self.boundaries),
            'active_boundaries': len([b for b in self.boundaries if b.active]),
            'current_violations': len(self.current_violations),
            'recent_violations_1h': len(recent_violations),
            'violation_types': {
                vtype.name: len([v for v in recent_violations if v.violation_type == vtype])
                for vtype in ViolationType
            }
        }
