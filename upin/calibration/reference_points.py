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

        # ── Global reference points ──────────────────────────────────────

        # North America
        north_america_points = [
            ReferencePoint(
                name="Statue of Liberty",
                lat=40.689247,
                lon=-74.044502,
                elevation_m=93.0,
                accuracy_m=0.3,
                reference_type=ReferenceType.MONUMENT,
                description="Liberty Island, New York Harbor",
                survey_date="2020",
                authority="NOAA NGS"
            ),
            ReferencePoint(
                name="Golden Gate Bridge North Tower",
                lat=37.828900,
                lon=-122.478600,
                elevation_m=227.4,
                accuracy_m=0.2,
                reference_type=ReferenceType.BRIDGE_CENTER,
                description="Cable-stayed bridge main tower, San Francisco",
                survey_date="2019",
                authority="Caltrans"
            ),
            ReferencePoint(
                name="Washington Monument",
                lat=38.889484,
                lon=-77.035278,
                elevation_m=169.3,
                accuracy_m=0.3,
                reference_type=ReferenceType.MONUMENT,
                description="National Mall obelisk, Washington DC",
                survey_date="2021",
                authority="NOAA NGS"
            ),
            ReferencePoint(
                name="Willis Tower Chicago",
                lat=41.878876,
                lon=-87.635915,
                elevation_m=527.0,
                accuracy_m=0.5,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Sears Tower, downtown Chicago",
                survey_date="2018",
                authority="NOAA NGS"
            ),
            ReferencePoint(
                name="CN Tower Toronto",
                lat=43.642566,
                lon=-79.387057,
                elevation_m=553.3,
                accuracy_m=0.4,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Communications tower, Toronto",
                survey_date="2019",
                authority="NRCan"
            ),
            ReferencePoint(
                name="LAX Airport DGPS",
                lat=33.942536,
                lon=-118.408075,
                elevation_m=38.1,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="Los Angeles International Airport reference",
                survey_date="2021",
                authority="FAA"
            ),
        ]

        # Europe
        europe_points = [
            ReferencePoint(
                name="Eiffel Tower Base",
                lat=48.858370,
                lon=2.294481,
                elevation_m=330.6,
                accuracy_m=0.2,
                reference_type=ReferenceType.MONUMENT,
                description="Iron lattice tower, Champ de Mars, Paris",
                survey_date="2020",
                authority="IGN France"
            ),
            ReferencePoint(
                name="Tower Bridge London",
                lat=51.505456,
                lon=-0.075356,
                elevation_m=65.0,
                accuracy_m=0.3,
                reference_type=ReferenceType.BRIDGE_CENTER,
                description="Bascule bridge over Thames, London",
                survey_date="2019",
                authority="Ordnance Survey"
            ),
            ReferencePoint(
                name="Brandenburg Gate Berlin",
                lat=52.516275,
                lon=13.377704,
                elevation_m=36.0,
                accuracy_m=0.4,
                reference_type=ReferenceType.MONUMENT,
                description="Neoclassical triumphal arch, Berlin",
                survey_date="2020",
                authority="BKG Germany"
            ),
            ReferencePoint(
                name="Colosseum Rome",
                lat=41.890210,
                lon=12.492231,
                elevation_m=48.5,
                accuracy_m=0.5,
                reference_type=ReferenceType.MONUMENT,
                description="Flavian Amphitheatre, Rome",
                survey_date="2018",
                authority="IGM Italy"
            ),
            ReferencePoint(
                name="Sagrada Familia Barcelona",
                lat=41.403629,
                lon=2.174356,
                elevation_m=172.0,
                accuracy_m=0.6,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Gaudi basilica, Barcelona",
                survey_date="2019",
                authority="IGN Spain"
            ),
            ReferencePoint(
                name="Heathrow Airport DGPS",
                lat=51.470020,
                lon=-0.454296,
                elevation_m=25.3,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="London Heathrow precision approach reference",
                survey_date="2021",
                authority="UK CAA"
            ),
        ]

        # Middle East
        middle_east_points = [
            ReferencePoint(
                name="Burj Khalifa Base",
                lat=25.197197,
                lon=55.274376,
                elevation_m=828.0,
                accuracy_m=0.2,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Tallest building in the world, Dubai",
                survey_date="2020",
                authority="Dubai Municipality"
            ),
            ReferencePoint(
                name="Strait of Hormuz Marker",
                lat=26.550000,
                lon=56.250000,
                elevation_m=0.0,
                accuracy_m=1.0,
                reference_type=ReferenceType.PORT_FACILITY,
                description="Maritime navigation marker, Strait of Hormuz",
                survey_date="2019",
                authority="UKHO"
            ),
            ReferencePoint(
                name="Jeddah Islamic Port DGPS",
                lat=21.485811,
                lon=39.186239,
                elevation_m=4.5,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="Port precision reference, Red Sea",
                survey_date="2020",
                authority="Saudi Ports Authority"
            ),
        ]

        # Asia-Pacific (non-India)
        asia_pacific_points = [
            ReferencePoint(
                name="Tokyo Skytree",
                lat=35.710063,
                lon=139.810700,
                elevation_m=634.0,
                accuracy_m=0.3,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Broadcasting tower, Sumida, Tokyo",
                survey_date="2020",
                authority="GSI Japan"
            ),
            ReferencePoint(
                name="Sydney Opera House",
                lat=-33.856784,
                lon=151.215297,
                elevation_m=67.0,
                accuracy_m=0.4,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Bennelong Point, Sydney Harbour",
                survey_date="2019",
                authority="Geoscience Australia"
            ),
            ReferencePoint(
                name="Petronas Towers Kuala Lumpur",
                lat=3.157764,
                lon=101.711861,
                elevation_m=451.9,
                accuracy_m=0.5,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Twin towers, KLCC, Kuala Lumpur",
                survey_date="2018",
                authority="JUPEM Malaysia"
            ),
            ReferencePoint(
                name="Marina Bay Sands Singapore",
                lat=1.283871,
                lon=103.860862,
                elevation_m=200.0,
                accuracy_m=0.3,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Integrated resort, Marina Bay",
                survey_date="2020",
                authority="SLA Singapore"
            ),
            ReferencePoint(
                name="Great Wall Badaling",
                lat=40.359907,
                lon=116.019993,
                elevation_m=755.0,
                accuracy_m=2.0,
                reference_type=ReferenceType.MONUMENT,
                description="Badaling section, Great Wall of China",
                survey_date="2019",
                authority="NASG China"
            ),
            ReferencePoint(
                name="Changi Airport DGPS",
                lat=1.350189,
                lon=103.994433,
                elevation_m=7.1,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="Singapore Changi precision approach reference",
                survey_date="2021",
                authority="CAAS Singapore"
            ),
        ]

        # Africa
        africa_points = [
            ReferencePoint(
                name="Great Pyramid of Giza",
                lat=29.979235,
                lon=31.134202,
                elevation_m=146.6,
                accuracy_m=0.3,
                reference_type=ReferenceType.MONUMENT,
                description="Pyramid of Khufu, Giza Plateau, Egypt",
                survey_date="2017",
                authority="Egyptian Survey Authority"
            ),
            ReferencePoint(
                name="Table Mountain Upper Cable",
                lat=-33.957500,
                lon=18.403056,
                elevation_m=1085.0,
                accuracy_m=1.0,
                reference_type=ReferenceType.LANDMARK_BUILDING,
                description="Upper cable station, Cape Town",
                survey_date="2018",
                authority="Chief Directorate National Geo-Spatial"
            ),
            ReferencePoint(
                name="Suez Canal Port Said DGPS",
                lat=31.265833,
                lon=32.301944,
                elevation_m=2.0,
                accuracy_m=0.1,
                reference_type=ReferenceType.DIFFERENTIAL_GPS,
                description="Canal entrance precision reference",
                survey_date="2020",
                authority="Suez Canal Authority"
            ),
        ]

        # South America
        south_america_points = [
            ReferencePoint(
                name="Christ the Redeemer",
                lat=-22.951916,
                lon=-43.210487,
                elevation_m=709.0,
                accuracy_m=0.5,
                reference_type=ReferenceType.MONUMENT,
                description="Statue atop Corcovado mountain, Rio de Janeiro",
                survey_date="2019",
                authority="IBGE Brazil"
            ),
            ReferencePoint(
                name="Panama Canal Miraflores Locks",
                lat=9.015367,
                lon=-79.590000,
                elevation_m=26.0,
                accuracy_m=0.3,
                reference_type=ReferenceType.PORT_FACILITY,
                description="Pacific-side locks, Panama Canal",
                survey_date="2020",
                authority="Panama Canal Authority"
            ),
        ]

        for point in (north_america_points + europe_points + middle_east_points +
                      asia_pacific_points + africa_points + south_america_points):
            self.add_point(point)

    def get_city_points(self, city: str) -> List[ReferencePoint]:
        """Get all reference points for a specific city."""
        city_bounds = {
            # India
            "mumbai": (18.9, 19.3, 72.7, 73.0),
            "chennai": (12.9, 13.2, 80.1, 80.3),
            "delhi": (28.4, 28.8, 77.0, 77.4),
            # North America
            "new york": (40.5, 40.9, -74.3, -73.7),
            "san francisco": (37.7, 37.9, -122.6, -122.3),
            "washington dc": (38.8, 39.0, -77.2, -76.9),
            "chicago": (41.7, 42.0, -87.8, -87.5),
            "toronto": (43.5, 43.8, -79.6, -79.2),
            "los angeles": (33.7, 34.2, -118.6, -118.1),
            # Europe
            "paris": (48.8, 48.9, 2.2, 2.5),
            "london": (51.4, 51.6, -0.5, 0.1),
            "berlin": (52.4, 52.6, 13.2, 13.6),
            "rome": (41.8, 42.0, 12.4, 12.6),
            "barcelona": (41.3, 41.5, 2.0, 2.3),
            # Middle East
            "dubai": (25.0, 25.4, 55.1, 55.5),
            "jeddah": (21.3, 21.7, 39.0, 39.4),
            # Asia-Pacific
            "tokyo": (35.5, 35.9, 139.5, 140.0),
            "sydney": (-34.0, -33.7, 151.0, 151.4),
            "kuala lumpur": (3.0, 3.3, 101.5, 101.9),
            "singapore": (1.2, 1.5, 103.6, 104.1),
            "beijing": (39.7, 40.5, 116.0, 116.8),
            # Africa
            "cairo": (29.9, 30.2, 31.0, 31.4),
            "cape town": (-34.1, -33.8, 18.3, 18.7),
            # South America
            "rio de janeiro": (-23.1, -22.7, -43.5, -43.0),
            "panama city": (8.9, 9.2, -79.7, -79.4),
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
