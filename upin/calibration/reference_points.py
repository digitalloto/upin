"""
Reference Points Database — UPIN Calibration Module

Provides precisely surveyed landmark coordinates for sensor calibration.
When UPIN passes a known reference point, it can compare its sensor
readings to ground truth and update drift compensation parameters.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import auto, Enum
from typing import Dict, List, Optional, Tuple


class ReferenceType(Enum):
    SURVEY_MONUMENT = auto()      # Government survey markers
    LANDMARK_BUILDING = auto()    # Major buildings with known coordinates
    BRIDGE_CENTER = auto()        # Bridge centers
    MONUMENT = auto()             # Historical monuments
    AIRPORT_REFERENCE = auto()    # Airport reference points
    PORT_FACILITY = auto()        # Port infrastructure
    CELL_TOWER = auto()           # Cell towers with known positions
    DIFFERENTIAL_GPS = auto()     # RTK/DGPS base stations


@dataclass
class ReferencePoint:
    """One precisely surveyed reference point for calibration."""
    name: str
    lat: float                    # WGS84 latitude in decimal degrees
    lon: float                    # WGS84 longitude in decimal degrees
    elevation_m: float            # Height above mean sea level
    accuracy_m: float             # Survey accuracy in metres
    reference_type: ReferenceType
    description: str
    survey_date: str              # When coordinates were established
    authority: str                # Who surveyed it (Survey of India, etc.)

    def distance_to(self, lat: float, lon: float) -> float:
        """Calculate distance in metres to another lat/lon."""
        dlat = (lat - self.lat) * 111320  # metres per degree latitude
        dlon = (lon - self.lon) * 111320 * math.cos(math.radians(self.lat))
        return math.sqrt(dlat**2 + dlon**2)

    def is_nearby(self, lat: float, lon: float, threshold_m: float = 100.0) -> bool:
        """Check if a position is within threshold metres of this reference."""
        return self.distance_to(lat, lon) <= threshold_m


class ReferencePointDatabase:
    """Database of precisely surveyed reference points."""

    def __init__(self):
        self._points: Dict[str, ReferencePoint] = {}
        self._load_default_points()

    def add_point(self, point: ReferencePoint) -> None:
        """Add a reference point to the database."""
        self._points[point.name] = point

    def get_point(self, name: str) -> Optional[ReferencePoint]:
        """Get a reference point by name."""
        return self._points.get(name)

    def find_nearby(self, lat: float, lon: float, max_distance_m: float = 500.0) -> List[ReferencePoint]:
        """Find all reference points within max_distance_m of the given position."""
        nearby = []
        for point in self._points.values():
            if point.distance_to(lat, lon) <= max_distance_m:
                nearby.append(point)

        # Sort by distance
        nearby.sort(key=lambda p: p.distance_to(lat, lon))
        return nearby

    def get_best_reference(self, lat: float, lon: float, max_distance_m: float = 200.0) -> Optional[ReferencePoint]:
        """Get the most accurate reference point within max_distance_m."""
        candidates = self.find_nearby(lat, lon, max_distance_m)
        if not candidates:
            return None

        # Return the most accurate (smallest accuracy_m value)
        return min(candidates, key=lambda p: p.accuracy_m)

    def list_all_points(self) -> List[ReferencePoint]:
        """Get all reference points."""
        return list(self._points.values())

    def _load_default_points(self) -> None:
        """Load default reference points for Mumbai and Chennai."""

        # Mumbai reference points
        mumbai_points = [
            ReferencePoint(
                name="Gateway of India",
                lat=18.921984,
                lon=72.834656,
                elevation_m=8.2,
                accuracy_m=0.5,
                reference_type=ReferenceType.MONUMENT,
                description="Historic monument, Apollo Bunder",
                survey_date="2019",
                authority="Survey of India"
            ),
            ReferencePoint(
                name="Chhatrapati Shivaji Terminus",
                lat=18.940186,
                lon=72.834819,
                elevation_m=11.3,
                accuracy_m=1.0,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="UNESCO World Heritage railway station",
                survey_date="2018",
                authority="Indian Railways Survey"
            ),
            ReferencePoint(
                name="Marine Drive Curve",
                lat=18.943912,
                lon=72.823472,
                elevation_m=5.8,
                accuracy_m=2.0,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Queens Necklace central curve point",
                survey_date="2020",
                authority="BMC Engineering"
            ),
            ReferencePoint(
                name="Bandra-Worli Sea Link Tower 1",
                lat=19.017656,
                lon=72.811178,
                elevation_m=126.5,
                accuracy_m=0.3,
                reference_type=ReferenceType.BRIDGE_CENTER,
                description="Cable-stayed bridge main tower",
                survey_date="2009",
                authority="MSRDC"
            ),
            ReferencePoint(
                name="Mumbai Airport DGPS Station",
                lat=19.088686,
                lon=72.867985,
                elevation_m=39.1,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="Precision approach reference",
                survey_date="2021",
                authority="AAI"
            ),
        ]

        # Chennai reference points
        chennai_points = [
            ReferencePoint(
                name="Fort St. George",
                lat=13.079729,
                lon=80.288406,
                elevation_m=6.4,
                accuracy_m=0.8,
                reference_type=ReferenceType.MONUMENT,
                description="Historic fort and museum",
                survey_date="2017",
                authority="Survey of India"
            ),
            ReferencePoint(
                name="Chennai Central Railway Station",
                lat=13.081725,
                lon=80.275284,
                elevation_m=7.2,
                accuracy_m=1.2,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Main railway terminus",
                survey_date="2019",
                authority="Southern Railway"
            ),
            ReferencePoint(
                name="Marina Beach Lighthouse",
                lat=13.049167,
                lon=80.282750,
                elevation_m=46.3,
                accuracy_m=0.5,
                reference_type=ReferenceType.MONUMENT,
                description="Historic lighthouse on Marina Beach",
                survey_date="2018",
                authority="Port of Chennai"
            ),
            ReferencePoint(
                name="Kapaleeshwarar Temple",
                lat=13.033889,
                lon=80.269722,
                elevation_m=8.7,
                accuracy_m=1.5,
                reference_type=ReferenceType.MONUMENT,
                description="Ancient Shiva temple in Mylapore",
                survey_date="2016",
                authority="HR&CE Department"
            ),
            ReferencePoint(
                name="Chennai Airport DGPS",
                lat=12.990014,
                lon=80.169286,
                elevation_m=16.2,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="Airport precision approach reference",
                survey_date="2020",
                authority="AAI"
            ),
        ]

        # Delhi reference points (for demos)
        delhi_points = [
            ReferencePoint(
                name="India Gate",
                lat=28.612912,
                lon=77.229546,
                elevation_m=218.5,
                accuracy_m=0.4,
                reference_type=ReferenceType.MONUMENT,
                description="War memorial arch",
                survey_date="2020",
                authority="Survey of India"
            ),
            ReferencePoint(
                name="Red Fort Main Gate",
                lat=28.656159,
                lon=77.241025,
                elevation_m=215.2,
                accuracy_m=0.6,
                reference_type=ReferenceType.MONUMENT,
                description="UNESCO World Heritage Mughal fort",
                survey_date="2019",
                authority="ASI"
            ),
        ]

        # Add all points
        for point in mumbai_points + chennai_points + delhi_points:
            self.add_point(point)

    def get_city_points(self, city: str) -> List[ReferencePoint]:
        """Get all reference points for a specific city."""
        city_bounds = {
            "mumbai": (18.9, 19.3, 72.7, 73.0),      # lat_min, lat_max, lon_min, lon_max
            "chennai": (12.9, 13.2, 80.1, 80.3),
            "delhi": (28.4, 28.8, 77.0, 77.4),
        }

        if city.lower() not in city_bounds:
            return []

        lat_min, lat_max, lon_min, lon_max = city_bounds[city.lower()]

        city_points = []
        for point in self._points.values():
            if lat_min <= point.lat <= lat_max and lon_min <= point.lon <= lon_max:
                city_points.append(point)

        return city_points


# Global instance
reference_db = ReferencePointDatabase()
