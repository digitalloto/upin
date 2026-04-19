"""
10-metre Training Constraint — UPIN

Ported from UPIN phone-demo v5. During GPS-available recording, every
formula's predicted position is pulled toward the GPS truth if the error
exceeds a tight threshold (default 10 m). This forces formulas to converge
faster: they cannot drift more than 10 m from truth during training, so
their parameters must adapt quickly.

Think of it as a training "leash" — the formulas are free to predict
anywhere within 10 m, but outside that they get yanked back. Evolution
within this tight space produces much tighter winners.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple


class TrainingConstraint:
    """Leash formulas to within N metres of GPS during training."""

    def __init__(self, leash_radius_m: float = 10.0):
        self._leash_m = leash_radius_m
        self._applied_count = 0
        self._total_count = 0

    def apply(self, truth_lat: float, truth_lon: float,
              predicted_lat: float, predicted_lon: float
              ) -> Tuple[float, float, bool]:
        """Pull prediction toward truth if outside leash. Returns new (lat, lon, was_pulled)."""
        self._total_count += 1
        dist = _haversine_m(truth_lat, truth_lon, predicted_lat, predicted_lon)
        if dist <= self._leash_m:
            return predicted_lat, predicted_lon, False
        # Pull to leash perimeter
        scale = self._leash_m / dist
        new_lat = truth_lat + (predicted_lat - truth_lat) * scale
        new_lon = truth_lon + (predicted_lon - truth_lon) * scale
        self._applied_count += 1
        return new_lat, new_lon, True

    def get_stats(self) -> dict:
        ratio = (self._applied_count / self._total_count
                 if self._total_count else 0.0)
        return {
            "leash_radius_m": self._leash_m,
            "applied_count": self._applied_count,
            "total_count": self._total_count,
            "pull_ratio": round(ratio, 3),
        }

    def set_leash(self, radius_m: float):
        self._leash_m = radius_m


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
