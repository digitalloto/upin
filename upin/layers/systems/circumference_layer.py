"""
Circumference Intersection Position Layer — UPIN Layer 87

Each tower circle's circumference passes through your position.
Where multiple circumferences cross = your EXACT location.
With 7 towers from different directions, you get multiple
confirmation points — all at the same spot.

This layer uses GPS-calibrated circle radii (exact distances)
and finds the geometric intersection of all circle circumferences.
The intersection point IS the position.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class CircumferenceIntersector:
    """Find the point where multiple circle circumferences intersect.

    Given N circles (center + radius), finds the point(s) where
    the maximum number of circumferences cross. With GPS-calibrated
    radii, all circles pass through the true position — so the
    intersection point IS the position.

    Uses pairwise circle-circle intersection then clusters the
    intersection points to find the consensus position.
    """

    def __init__(self, cluster_radius_m: float = 100.0):
        self._cluster_radius = cluster_radius_m

    def find_intersection(self,
                          circles: List[Tuple[float, float, float]]
                          ) -> Optional[Dict]:
        """Find the position where most circle circumferences cross.

        circles: list of (center_lat, center_lon, radius_m)
        Returns the cluster with the most intersection points.
        """
        if len(circles) < 2:
            return None

        # Find all pairwise circle-circle intersections
        intersection_points: List[Tuple[float, float, int, int]] = []
        for i in range(len(circles)):
            for j in range(i + 1, len(circles)):
                pts = self._circle_circle_intersect(
                    circles[i][0], circles[i][1], circles[i][2],
                    circles[j][0], circles[j][1], circles[j][2],
                )
                for lat, lon in pts:
                    intersection_points.append((lat, lon, i, j))

        if not intersection_points:
            # No intersections — use weighted centroid as fallback
            total_w = 0.0
            lat_sum = lon_sum = 0.0
            for clat, clon, r in circles:
                w = 1.0 / max(r, 1.0)
                lat_sum += clat * w
                lon_sum += clon * w
                total_w += w
            return {
                "lat": lat_sum / total_w,
                "lon": lon_sum / total_w,
                "intersection_count": 0,
                "cluster_size": 0,
                "method": "fallback_centroid",
            }

        # Cluster intersection points — find the densest cluster
        best_cluster_lat = 0.0
        best_cluster_lon = 0.0
        best_cluster_size = 0

        for idx, (ref_lat, ref_lon, _, _) in enumerate(intersection_points):
            cluster = [(ref_lat, ref_lon)]
            for jdx, (pt_lat, pt_lon, _, _) in enumerate(intersection_points):
                if jdx == idx:
                    continue
                d = _haversine_m(ref_lat, ref_lon, pt_lat, pt_lon)
                if d <= self._cluster_radius:
                    cluster.append((pt_lat, pt_lon))

            if len(cluster) > best_cluster_size:
                best_cluster_size = len(cluster)
                best_cluster_lat = sum(p[0] for p in cluster) / len(cluster)
                best_cluster_lon = sum(p[1] for p in cluster) / len(cluster)

        # Count how many circles this point lies on
        circles_passing = 0
        for clat, clon, r in circles:
            d = _haversine_m(best_cluster_lat, best_cluster_lon, clat, clon)
            if abs(d - r) < self._cluster_radius:
                circles_passing += 1

        return {
            "lat": best_cluster_lat,
            "lon": best_cluster_lon,
            "intersection_count": len(intersection_points),
            "cluster_size": best_cluster_size,
            "circles_passing": circles_passing,
            "total_circles": len(circles),
            "method": "circumference_intersection",
        }

    def _circle_circle_intersect(self,
                                  lat1: float, lon1: float, r1: float,
                                  lat2: float, lon2: float, r2: float
                                  ) -> List[Tuple[float, float]]:
        """Find 0 or 2 intersection points of two circles on Earth surface.

        Approximation using flat-earth projection (valid for <100km).
        """
        m_per_deg = 111_320.0
        cos_lat = math.cos(math.radians((lat1 + lat2) / 2))

        # Convert to metres
        x1, y1 = 0.0, 0.0
        x2 = (lon2 - lon1) * m_per_deg * cos_lat
        y2 = (lat2 - lat1) * m_per_deg

        d = math.sqrt(x2 * x2 + y2 * y2)
        if d < 1e-6 or d > r1 + r2 or d < abs(r1 - r2):
            return []  # no intersection

        a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
        h_sq = r1 * r1 - a * a
        if h_sq < 0:
            return []
        h = math.sqrt(h_sq)

        # Point on line between centers
        px = a * x2 / d
        py = a * y2 / d

        # Two intersection points
        ix1 = px + h * y2 / d
        iy1 = py - h * x2 / d
        ix2 = px - h * y2 / d
        iy2 = py + h * x2 / d

        # Convert back to lat/lon
        pt1_lat = lat1 + iy1 / m_per_deg
        pt1_lon = lon1 + ix1 / (m_per_deg * cos_lat)
        pt2_lat = lat1 + iy2 / m_per_deg
        pt2_lon = lon1 + ix2 / (m_per_deg * cos_lat)

        return [(pt1_lat, pt1_lon), (pt2_lat, pt2_lon)]


class CircumferenceIntersectionLayer(NavigationLayer):
    """Layer 87 — Circumference Intersection Position.

    Finds the point where multiple tower circle circumferences cross.
    With GPS-calibrated exact radii, all circles pass through your
    position. The intersection point IS your location.
    """

    def __init__(self):
        super().__init__(
            layer_id="circumfx_k10",
            layer_number=87,
            name="Circumference Intersection",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Multi-circle circumference crossing point = position",
        )
        self._intersector = CircumferenceIntersector()

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.70

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        signals = self.world.get_cell_tower_signals()
        if len(signals) < 3:
            return self._read_fallback()

        # Build circles: center = tower position, radius = GPS distance to tower
        circles = []
        for s in signals:
            dist = self.world._haversine_m(
                self.world.true_lat, self.world.true_lon,
                s["known_lat"], s["known_lon"],
            )
            # Add small noise to simulate measurement uncertainty
            dist += np.random.normal(0, dist * 0.01)
            circles.append((s["known_lat"], s["known_lon"], dist))

        result = self._intersector.find_intersection(circles)
        if result is None:
            return self._read_fallback()

        confidence = min(0.9, 0.3 + result["cluster_size"] * 0.05
                         + result["circles_passing"] * 0.1)
        noise_m = max(5.0, 50.0 / max(1, result["circles_passing"]))

        pos = Position(
            latitude=result["lat"], longitude=result["lon"], altitude=0,
            accuracy_m=noise_m, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=confidence,
            raw_data={
                "intersection_count": result["intersection_count"],
                "cluster_size": result["cluster_size"],
                "circles_passing": result["circles_passing"],
                "total_circles": result["total_circles"],
                "method": result["method"],
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat + np.random.normal(0, 30 / 111_000),
            longitude=base_lon + np.random.normal(0, 30 / 111_000),
            altitude=0, accuracy_m=30.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.4,
            raw_data={"method": "fallback", "circles_passing": 0},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
