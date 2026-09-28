"""
Great-circle navigation on a sphere.

The spec (section 1.2) asks for "the standard great-circle formula" for the
bearing and distance to a clicked target. These are those formulae: the
haversine for distance, the forward azimuth for bearing, and the direct
problem for "where do I end up".

The sphere's radius is the one SimulationWorld moves its platform on, so
guidance and the simulated aircraft agree about geometry. A sphere is about
half a percent from the WGS-84 ellipsoid; for the few-kilometre legs guided
flight works on, that is well inside the error budget, and the ellipsoidal
solution arrives with the datum work in spec item 11.1.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import Tuple

R_EARTH = 6_371_000.0


def distance_bearing(lat1: float, lon1: float, lat2: float,
                     lon2: float) -> Tuple[float, float]:
    """Distance in metres and initial bearing in degrees true, 1 -> 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2.0 * R_EARTH * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return d, math.degrees(math.atan2(y, x)) % 360.0


def destination(lat: float, lon: float, bearing_deg: float,
                distance_m: float) -> Tuple[float, float]:
    """Where a great circle from (lat, lon) on this bearing ends up."""
    p1, l1 = math.radians(lat), math.radians(lon)
    b = math.radians(bearing_deg)
    d = distance_m / R_EARTH
    p2 = math.asin(math.sin(p1) * math.cos(d)
                   + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def offset_ne(lat: float, lon: float, north_m: float,
              east_m: float) -> Tuple[float, float]:
    """Move by a north/east displacement."""
    dist = math.hypot(north_m, east_m)
    if dist == 0.0:
        return lat, lon
    return destination(lat, lon, math.degrees(math.atan2(east_m, north_m)), dist)
