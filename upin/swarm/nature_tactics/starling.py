"""
Starling Murmuration — UPIN Swarm

Two strategies from starling flocks:

1. THREE-RULE FLOCKING — each bird follows separation, alignment,
   cohesion. Simple rules → complex emergent evasion patterns.
   No leader, no central command — pure mesh coordination.

2. PREDATOR EVASION — the flock flows around a hawk like water
   around a rock. Applied to drones: if a missile locks onto the
   swarm, the mesh parts and re-forms behind it. The missile
   passes through empty space.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Boid:
    """One drone in the murmuration."""
    drone_id: str
    lat: float = 0.0
    lon: float = 0.0
    alt: float = 100.0
    vx: float = 0.0  # velocity east (m/s)
    vy: float = 0.0  # velocity north (m/s)
    speed_ms: float = 15.0


class StarlingMurmuration:
    """Three-rule flocking + predator evasion.

    Rules applied every tick:
    1. SEPARATION: steer away from nearby drones (avoid collision)
    2. ALIGNMENT: match heading with neighbors
    3. COHESION: steer toward center of nearby group

    These 3 simple rules produce complex emergent swarm behavior
    without any central controller.
    """

    def __init__(self, separation_m: float = 20.0,
                 alignment_radius_m: float = 100.0,
                 cohesion_radius_m: float = 200.0,
                 max_speed_ms: float = 25.0):
        self._separation = separation_m
        self._alignment_r = alignment_radius_m
        self._cohesion_r = cohesion_radius_m
        self._max_speed = max_speed_ms
        self._boids: Dict[str, Boid] = {}
        self._predator: Optional[Tuple[float, float]] = None

        # Rule weights
        self._w_sep = 2.0
        self._w_ali = 1.0
        self._w_coh = 1.0
        self._w_pred = 5.0  # predator avoidance is strongest

    def add_boid(self, drone_id: str, lat: float, lon: float,
                 heading_deg: float = 0.0, speed_ms: float = 15.0):
        vx = speed_ms * math.sin(math.radians(heading_deg))
        vy = speed_ms * math.cos(math.radians(heading_deg))
        self._boids[drone_id] = Boid(
            drone_id=drone_id, lat=lat, lon=lon,
            vx=vx, vy=vy, speed_ms=speed_ms,
        )

    def set_predator(self, lat: float, lon: float):
        """Set a threat (missile/hawk) position for evasion."""
        self._predator = (lat, lon)

    def clear_predator(self):
        self._predator = None

    def tick(self, dt: float = 0.1) -> Dict[str, Dict]:
        """Apply all 3 rules + predator evasion. Returns new positions."""
        boid_list = list(self._boids.values())
        updates = {}

        for boid in boid_list:
            sep_x, sep_y = 0.0, 0.0  # separation
            ali_x, ali_y = 0.0, 0.0  # alignment
            coh_x, coh_y = 0.0, 0.0  # cohesion
            sep_n = ali_n = coh_n = 0

            for other in boid_list:
                if other.drone_id == boid.drone_id:
                    continue
                dx = (other.lon - boid.lon) * 111_320 * math.cos(math.radians(boid.lat))
                dy = (other.lat - boid.lat) * 111_320
                dist = math.sqrt(dx * dx + dy * dy)

                # Rule 1: Separation
                if 0 < dist < self._separation:
                    sep_x -= dx / max(dist, 0.1)
                    sep_y -= dy / max(dist, 0.1)
                    sep_n += 1

                # Rule 2: Alignment
                if dist < self._alignment_r:
                    ali_x += other.vx
                    ali_y += other.vy
                    ali_n += 1

                # Rule 3: Cohesion
                if dist < self._cohesion_r:
                    coh_x += dx
                    coh_y += dy
                    coh_n += 1

            # Normalize
            if sep_n > 0:
                sep_x /= sep_n
                sep_y /= sep_n
            if ali_n > 0:
                ali_x = ali_x / ali_n - boid.vx
                ali_y = ali_y / ali_n - boid.vy
            if coh_n > 0:
                coh_x /= coh_n
                coh_y /= coh_n

            # Predator evasion
            pred_x, pred_y = 0.0, 0.0
            if self._predator:
                px = (self._predator[1] - boid.lon) * 111_320 * math.cos(math.radians(boid.lat))
                py = (self._predator[0] - boid.lat) * 111_320
                pd = math.sqrt(px * px + py * py)
                if pd < 500:  # evade if predator within 500m
                    pred_x = -px / max(pd, 0.1)
                    pred_y = -py / max(pd, 0.1)

            # Combine forces
            boid.vx += (self._w_sep * sep_x + self._w_ali * ali_x
                        + self._w_coh * coh_x + self._w_pred * pred_x) * dt
            boid.vy += (self._w_sep * sep_y + self._w_ali * ali_y
                        + self._w_coh * coh_y + self._w_pred * pred_y) * dt

            # Limit speed
            speed = math.sqrt(boid.vx ** 2 + boid.vy ** 2)
            if speed > self._max_speed:
                boid.vx = boid.vx / speed * self._max_speed
                boid.vy = boid.vy / speed * self._max_speed

            # Update position
            boid.lat += boid.vy * dt / 111_320
            cos_lat = math.cos(math.radians(boid.lat))
            boid.lon += boid.vx * dt / (111_320 * max(cos_lat, 0.01))

            heading = math.degrees(math.atan2(boid.vx, boid.vy)) % 360
            updates[boid.drone_id] = {
                "lat": boid.lat, "lon": boid.lon,
                "heading_deg": heading,
                "speed_ms": math.sqrt(boid.vx ** 2 + boid.vy ** 2),
            }

        return updates

    def get_centroid(self) -> Tuple[float, float]:
        if not self._boids:
            return (0, 0)
        lat = sum(b.lat for b in self._boids.values()) / len(self._boids)
        lon = sum(b.lon for b in self._boids.values()) / len(self._boids)
        return (lat, lon)

    def get_status(self) -> Dict:
        return {
            "boids": len(self._boids),
            "centroid": self.get_centroid(),
            "predator_active": self._predator is not None,
            "rules": {"separation_m": self._separation,
                       "alignment_m": self._alignment_r,
                       "cohesion_m": self._cohesion_r},
        }
