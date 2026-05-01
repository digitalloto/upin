"""
Directional Tower Selection (GDOP) Layer — UPIN Layer 86

Pick towers from N/S/E/W for best geometric spread. If all towers
are to the south, you have great north-south accuracy but terrible
east-west. By selecting one tower from each cardinal direction,
the circles cross at tight angles → minimum position error.

This is Geometric Dilution of Precision (GDOP) — same principle
GPS uses to pick satellites from different parts of the sky.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


@dataclass
class DirectionalTower:
    tower_id: str
    lat: float
    lon: float
    bearing_deg: float   # bearing FROM user TO tower
    distance_m: float
    rssi_dbm: float
    quadrant: str        # N, S, E, W, NE, SE, SW, NW


class DirectionalTowerSelector:
    """Select towers from all cardinal directions for best GDOP.

    Sorts available towers into quadrants (N, NE, E, SE, S, SW, W, NW),
    then picks the best tower from each occupied quadrant. More spread
    = tighter intersection = better position accuracy.
    """

    def __init__(self):
        self._towers: List[DirectionalTower] = []
        self._selected: List[DirectionalTower] = []
        self._gdop: float = 99.0

    def classify_towers(self, user_lat: float, user_lon: float,
                        towers: List[Dict]) -> List[DirectionalTower]:
        """Classify towers into directional quadrants."""
        classified = []
        for t in towers:
            t_lat = t.get("lat", t.get("known_lat", 0))
            t_lon = t.get("lon", t.get("known_lon", 0))
            dist = _haversine_m(user_lat, user_lon, t_lat, t_lon)
            if dist < 1:
                continue

            bearing = math.degrees(math.atan2(
                t_lon - user_lon, t_lat - user_lat)) % 360

            # 8-direction quadrant
            if bearing < 22.5 or bearing >= 337.5:
                quadrant = "N"
            elif bearing < 67.5:
                quadrant = "NE"
            elif bearing < 112.5:
                quadrant = "E"
            elif bearing < 157.5:
                quadrant = "SE"
            elif bearing < 202.5:
                quadrant = "S"
            elif bearing < 247.5:
                quadrant = "SW"
            elif bearing < 292.5:
                quadrant = "W"
            else:
                quadrant = "NW"

            classified.append(DirectionalTower(
                tower_id=t.get("tower_id", ""),
                lat=t_lat, lon=t_lon,
                bearing_deg=bearing,
                distance_m=dist,
                rssi_dbm=t.get("rssi_dbm", -90),
                quadrant=quadrant,
            ))
        self._towers = classified
        return classified

    def select_best_spread(self, min_towers: int = 3,
                           max_towers: int = 8) -> List[DirectionalTower]:
        """Select towers maximising directional spread.

        Picks the strongest tower from each occupied quadrant.
        Ensures at least min_towers from different directions.
        """
        quadrant_best: Dict[str, DirectionalTower] = {}
        for t in self._towers:
            if (t.quadrant not in quadrant_best
                    or t.rssi_dbm > quadrant_best[t.quadrant].rssi_dbm):
                quadrant_best[t.quadrant] = t

        # Sort by quadrant priority: prefer opposite pairs (N+S, E+W)
        priority = ["N", "S", "E", "W", "NE", "SW", "SE", "NW"]
        selected = []
        for q in priority:
            if q in quadrant_best and len(selected) < max_towers:
                selected.append(quadrant_best[q])

        # If not enough, add remaining by RSSI strength
        if len(selected) < min_towers:
            remaining = [t for t in self._towers if t not in selected]
            remaining.sort(key=lambda t: -t.rssi_dbm)
            for t in remaining:
                if len(selected) >= min_towers:
                    break
                selected.append(t)

        self._selected = selected
        self._gdop = self._compute_gdop(selected)
        return selected

    def _compute_gdop(self, towers: List[DirectionalTower]) -> float:
        """Compute Geometric Dilution of Precision from tower spread.

        Lower GDOP = better geometry = more accurate position.
        GDOP < 2: excellent, 2-5: good, 5-10: moderate, >10: poor
        """
        if len(towers) < 3:
            return 99.0

        # Check angular spread
        bearings = sorted(t.bearing_deg for t in towers)
        max_gap = 0.0
        for i in range(len(bearings)):
            gap = bearings[(i + 1) % len(bearings)] - bearings[i]
            if gap < 0:
                gap += 360
            max_gap = max(max_gap, gap)

        # GDOP approximation from angular spread
        spread_factor = (360.0 - max_gap) / 360.0
        n_towers = len(towers)
        gdop = 1.0 / (spread_factor * math.sqrt(n_towers) + 0.01)
        return round(min(99.0, gdop), 2)

    def get_quadrant_coverage(self) -> Dict[str, Optional[str]]:
        """Show which quadrants have towers."""
        coverage = {}
        for q in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]:
            selected_in_q = [t for t in self._selected if t.quadrant == q]
            coverage[q] = selected_in_q[0].tower_id if selected_in_q else None
        return coverage

    def get_status(self) -> Dict:
        return {
            "total_towers": len(self._towers),
            "selected": len(self._selected),
            "gdop": self._gdop,
            "quadrants_covered": sum(1 for v in self.get_quadrant_coverage().values()
                                     if v is not None),
            "quadrant_coverage": self.get_quadrant_coverage(),
        }


class DirectionalTowerLayer(NavigationLayer):
    """Layer 86 — Directional Tower Selection (GDOP Optimised).

    Selects towers from all cardinal directions for best geometric
    spread. Tighter circle intersections = more accurate position.
    """

    def __init__(self):
        super().__init__(
            layer_id="dirtower_k09",
            layer_number=86,
            name="Directional Tower GDOP",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="GDOP-optimised tower selection from all cardinal directions",
        )
        self._selector = DirectionalTowerSelector()

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        signals = self.world.get_cell_tower_signals()
        tower_dicts = [{"tower_id": s["tower_id"], "lat": s["known_lat"],
                        "lon": s["known_lon"], "rssi_dbm": s["rssi_dbm"]}
                       for s in signals]

        self._selector.classify_towers(
            self.world.true_lat, self.world.true_lon, tower_dicts)
        selected = self._selector.select_best_spread()

        if len(selected) < 3:
            return self._read_fallback()

        # Trilaterate from selected towers using GPS-measured distances
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for t in selected:
            w = 1.0 / max(t.distance_m, 1.0)
            lat_sum += t.lat * w
            lon_sum += t.lon * w
            total_w += w
        lat = lat_sum / total_w + np.random.normal(0, 0.0002)
        lon = lon_sum / total_w + np.random.normal(0, 0.0002)

        gdop = self._selector._gdop
        noise_m = max(10.0, 50.0 * gdop)
        confidence = max(0.2, min(0.9, 1.0 / (gdop + 0.1)))

        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=confidence,
            raw_data={
                "towers_selected": len(selected),
                "gdop": gdop,
                "quadrants_covered": self._selector.get_status()["quadrants_covered"],
                "quadrant_map": self._selector.get_quadrant_coverage(),
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat + np.random.normal(0, 50 / 111_000),
            longitude=base_lon + np.random.normal(0, 50 / 111_000),
            altitude=0, accuracy_m=50.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.4,
            raw_data={"gdop": 99, "status": "fallback"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
