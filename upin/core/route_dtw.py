"""
Route DTW Learning — UPIN

Ported from UPIN phone-demo v5. Records a route as a sequence of
sensor fingerprints with GPS truth. During GPS denial on a previously
travelled route, Dynamic Time Warping aligns the current sensor
stream against the stored route to estimate current position.

Dynamic Time Warping handles variations in speed — the platform can
drive the same route at different speeds and still match.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class RouteSample:
    """One sample along a learned route."""
    lat: float
    lon: float
    timestamp: float
    heading_deg: float
    mag_intensity_nt: float = 0.0
    baro_pressure_hpa: float = 0.0
    speed_ms: float = 0.0


@dataclass
class LearnedRoute:
    """A complete learned route."""
    route_id: str
    name: str
    samples: List[RouteSample] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def length_m(self) -> float:
        total = 0.0
        for i in range(1, len(self.samples)):
            total += _haversine_m(
                self.samples[i - 1].lat, self.samples[i - 1].lon,
                self.samples[i].lat, self.samples[i].lon,
            )
        return total


class RouteDTWLearning:
    """Record routes with GPS; match live sensors during GPS denial via DTW.

    DTW handles speed variation — same route driven at different speeds
    still aligns, because DTW allows non-uniform temporal mapping.
    """

    def __init__(self, sample_interval_m: float = 10.0):
        self._routes: Dict[str, LearnedRoute] = {}
        self._active_recording: Optional[LearnedRoute] = None
        self._sample_interval_m = sample_interval_m
        self._last_recorded_sample: Optional[RouteSample] = None

    def start_recording(self, route_id: str, name: str = ""):
        self._active_recording = LearnedRoute(
            route_id=route_id, name=name or route_id,
        )
        self._last_recorded_sample = None

    def stop_recording(self) -> Optional[LearnedRoute]:
        route = self._active_recording
        if route is not None and route.samples:
            self._routes[route.route_id] = route
        self._active_recording = None
        self._last_recorded_sample = None
        return route

    def record_sample(self, sample: RouteSample) -> bool:
        """Record a sample along the active route if far enough from last."""
        if self._active_recording is None:
            return False
        if self._last_recorded_sample is not None:
            d = _haversine_m(
                self._last_recorded_sample.lat, self._last_recorded_sample.lon,
                sample.lat, sample.lon,
            )
            if d < self._sample_interval_m:
                return False
        self._active_recording.samples.append(sample)
        self._last_recorded_sample = sample
        return True

    def match_live(self, live_stream: List[RouteSample],
                   route_id: Optional[str] = None) -> Optional[Dict]:
        """Match a live sensor stream against a learned route via DTW.

        If route_id is None, matches against all routes and picks best.
        Returns the estimated position (from the best-matching route sample).
        """
        if not live_stream:
            return None

        candidates = ([self._routes[route_id]] if route_id and route_id in self._routes
                      else list(self._routes.values()))
        if not candidates:
            return None

        best_route = None
        best_cost = float('inf')
        best_align = None
        for route in candidates:
            if not route.samples:
                continue
            cost, alignment = self._dtw(live_stream, route.samples)
            if cost < best_cost:
                best_cost = cost
                best_route = route
                best_align = alignment

        if best_route is None or best_align is None:
            return None

        # Alignment tail: last live sample → which route sample?
        last_live_idx = len(live_stream) - 1
        matched_route_idx = None
        for li, ri in reversed(best_align):
            if li == last_live_idx:
                matched_route_idx = ri
                break
        if matched_route_idx is None:
            matched_route_idx = best_align[-1][1]

        matched = best_route.samples[matched_route_idx]
        # Confidence: lower cost = higher confidence (normalized by stream length)
        normalized = best_cost / max(1, len(live_stream))
        confidence = 1.0 / (1.0 + normalized)

        return {
            "lat": matched.lat,
            "lon": matched.lon,
            "heading_deg": matched.heading_deg,
            "confidence": confidence,
            "route_id": best_route.route_id,
            "matched_route_index": matched_route_idx,
            "dtw_cost": best_cost,
            "live_length": len(live_stream),
            "route_length": len(best_route.samples),
        }

    def _dtw(self, seq_a: List[RouteSample],
             seq_b: List[RouteSample]) -> Tuple[float, List[Tuple[int, int]]]:
        """Dynamic Time Warping — returns (total_cost, alignment).

        Classic DP implementation; bounded window for efficiency.
        """
        n, m = len(seq_a), len(seq_b)
        INF = float('inf')
        # dp[i][j] = min cost to align seq_a[:i+1] with seq_b[:j+1]
        dp = [[INF] * m for _ in range(n)]
        backptr = [[(-1, -1)] * m for _ in range(n)]

        dp[0][0] = self._sample_distance(seq_a[0], seq_b[0])
        for j in range(1, m):
            dp[0][j] = dp[0][j - 1] + self._sample_distance(seq_a[0], seq_b[j])
            backptr[0][j] = (0, j - 1)
        for i in range(1, n):
            dp[i][0] = dp[i - 1][0] + self._sample_distance(seq_a[i], seq_b[0])
            backptr[i][0] = (i - 1, 0)
        for i in range(1, n):
            for j in range(1, m):
                cost = self._sample_distance(seq_a[i], seq_b[j])
                options = [
                    (dp[i - 1][j], (i - 1, j)),
                    (dp[i][j - 1], (i, j - 1)),
                    (dp[i - 1][j - 1], (i - 1, j - 1)),
                ]
                best = min(options, key=lambda o: o[0])
                dp[i][j] = cost + best[0]
                backptr[i][j] = best[1]

        # Recover alignment
        alignment = []
        i, j = n - 1, m - 1
        while i >= 0 and j >= 0:
            alignment.append((i, j))
            pi, pj = backptr[i][j]
            if pi < 0:
                break
            i, j = pi, pj
        alignment.reverse()
        return dp[n - 1][m - 1], alignment

    @staticmethod
    def _sample_distance(a: RouteSample, b: RouteSample) -> float:
        """Cross-sensor distance between two samples (lower = more similar)."""
        d_mag = abs(a.mag_intensity_nt - b.mag_intensity_nt) / 50.0
        d_baro = abs(a.baro_pressure_hpa - b.baro_pressure_hpa)
        dh = abs(a.heading_deg - b.heading_deg)
        if dh > 180:
            dh = 360 - dh
        d_head = dh / 30.0
        return d_mag + d_baro + d_head

    def get_routes(self) -> List[LearnedRoute]:
        return list(self._routes.values())

    def get_route(self, route_id: str) -> Optional[LearnedRoute]:
        return self._routes.get(route_id)


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
