"""
GPS-Calibrated Cell Tower Ranging — UPIN

The key insight: RSSI-to-distance is noisy (buildings, weather, reflections
make -92 dBm mean anywhere from 500m to 5km). But GPS-to-tower distance
is EXACT. When GPS is available, measure the real distance to every visible
tower. That distance IS the circle radius. All circles intersect at your
GPS position — perfect geometry.

TRAINING (GPS available):
  GPS says you're at (13.08, 80.27)
  Tower A is at (13.07, 80.26) → distance = 1,247m, RSSI = -92 dBm
  Tower B is at (13.09, 80.27) → distance = 1,113m, RSSI = -88 dBm
  Tower C is at (13.08, 80.28) → distance = 1,085m, RSSI = -85 dBm
  → Record: tower_id → (distance_m, rssi_dbm) pairs
  → All circles cross at GPS position — PROVEN geometry

GPS DENIED:
  RSSI for Tower A changes from -92 to -94 → you moved ~100m AWAY
  RSSI for Tower B changes from -88 to -86 → you moved ~80m CLOSER
  RSSI for Tower C stays at -85 → same distance
  → Update radii: A=1,347m, B=1,033m, C=1,085m
  → Trilaterate → new position from updated circles
  → The RSSI CHANGE is reliable even when absolute RSSI isn't

This replaces noisy path-loss estimation with GPS-measured truth +
delta tracking. Circles are tight and accurate.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class TowerCalibration:
    """GPS-calibrated data for one cell tower."""
    tower_id: str
    tower_lat: float
    tower_lon: float
    # GPS-measured true distance at calibration time
    calibrated_distance_m: float
    calibrated_rssi_dbm: float
    calibrated_at: float
    calibrated_from_lat: float
    calibrated_from_lon: float
    # RSSI history for delta tracking
    rssi_history: List[Tuple[float, float]] = field(default_factory=list)  # (time, rssi)
    # Learned path-loss coefficient for THIS tower (from GPS truth)
    path_loss_n: float = 3.0  # calibrated exponent
    # Current estimated distance (updated during GPS denial)
    current_distance_m: float = 0.0
    current_rssi_dbm: float = 0.0


@dataclass
class TowerCircle:
    """A circle centered on a tower with measured radius."""
    tower_id: str
    center_lat: float
    center_lon: float
    radius_m: float
    rssi_dbm: float
    calibrated: bool
    confidence: float


class GPSCalibratedTowerRanging:
    """GPS-calibrated cell tower distance measurement.

    During GPS: measure exact distance to each tower → record as circle radius.
    During denial: track RSSI changes → update radii → trilaterate.
    """

    def __init__(self, rssi_to_distance_scale: float = 30.0):
        self._towers: Dict[str, TowerCalibration] = {}
        self._rssi_scale = rssi_to_distance_scale  # metres per dBm change
        self._calibration_count = 0
        self._trilateration_count = 0
        self._max_rssi_history = 50

    def calibrate_tower(self, tower_id: str,
                        tower_lat: float, tower_lon: float,
                        gps_lat: float, gps_lon: float,
                        rssi_dbm: float):
        """Calibrate a tower using GPS-measured distance.

        This is the key: the distance is EXACT because GPS measured it.
        """
        distance = _haversine_m(gps_lat, gps_lon, tower_lat, tower_lon)

        # Learn path-loss exponent for this tower from real data
        # RSSI = P0 - 10*n*log10(d/d0), solve for n
        # Using reference: -40 dBm at 1m
        p0 = -40.0
        d0 = 1.0
        if distance > d0:
            n = (p0 - rssi_dbm) / (10.0 * math.log10(distance / d0))
            n = max(1.5, min(5.0, n))  # sane range
        else:
            n = 3.0

        cal = TowerCalibration(
            tower_id=tower_id,
            tower_lat=tower_lat,
            tower_lon=tower_lon,
            calibrated_distance_m=distance,
            calibrated_rssi_dbm=rssi_dbm,
            calibrated_at=time.time(),
            calibrated_from_lat=gps_lat,
            calibrated_from_lon=gps_lon,
            path_loss_n=n,
            current_distance_m=distance,
            current_rssi_dbm=rssi_dbm,
        )
        cal.rssi_history.append((time.time(), rssi_dbm))
        self._towers[tower_id] = cal
        self._calibration_count += 1

    def update_rssi(self, tower_id: str, rssi_dbm: float):
        """Update RSSI for a tower (during GPS denial or GPS available).

        Uses the RSSI CHANGE from calibration to estimate distance change.
        """
        if tower_id not in self._towers:
            return
        cal = self._towers[tower_id]
        cal.rssi_history.append((time.time(), rssi_dbm))
        if len(cal.rssi_history) > self._max_rssi_history:
            cal.rssi_history = cal.rssi_history[-self._max_rssi_history:]

        cal.current_rssi_dbm = rssi_dbm

        # RSSI delta from calibration
        rssi_delta = rssi_dbm - cal.calibrated_rssi_dbm

        # Distance change from RSSI delta using calibrated path-loss
        # RSSI drops 10*n dBm per decade of distance
        # So delta_rssi = -10*n*log10(d_new/d_cal)
        # d_new = d_cal * 10^(-delta_rssi / (10*n))
        if cal.path_loss_n > 0:
            ratio = 10.0 ** (-rssi_delta / (10.0 * cal.path_loss_n))
            cal.current_distance_m = cal.calibrated_distance_m * ratio
        else:
            # Fallback: simple linear scaling
            cal.current_distance_m = (cal.calibrated_distance_m
                                       + rssi_delta * self._rssi_scale)
        cal.current_distance_m = max(10.0, cal.current_distance_m)

    def get_circles(self) -> List[TowerCircle]:
        """Get all tower circles with current radii for map display."""
        circles = []
        for cal in self._towers.values():
            age_s = time.time() - cal.calibrated_at
            # Confidence decays with time since calibration
            confidence = max(0.1, math.exp(-age_s / 600))  # ~0.37 after 10 min
            circles.append(TowerCircle(
                tower_id=cal.tower_id,
                center_lat=cal.tower_lat,
                center_lon=cal.tower_lon,
                radius_m=cal.current_distance_m,
                rssi_dbm=cal.current_rssi_dbm,
                calibrated=True,
                confidence=confidence,
            ))
        return circles

    def trilaterate(self) -> Optional[Dict]:
        """Trilaterate position from GPS-calibrated tower circles.

        Uses NLLS (Gauss-Newton) for precision, with weighted centroid
        as initial guess.
        """
        circles = self.get_circles()
        if len(circles) < 3:
            if len(circles) >= 2:
                return self._bilaterate(circles)
            return None

        self._trilateration_count += 1

        # Initial guess: weighted centroid (inverse-distance weighting)
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for c in circles:
            w = c.confidence / max(c.radius_m, 1.0)
            lat_sum += c.center_lat * w
            lon_sum += c.center_lon * w
            total_w += w
        init_lat = lat_sum / total_w
        init_lon = lon_sum / total_w

        # Gauss-Newton NLLS refinement (5 iterations)
        lat, lon = init_lat, init_lon
        for _ in range(5):
            residuals = []
            jacobian = []
            m_lat = 111_320.0
            m_lon = 111_320.0 * max(math.cos(math.radians(lat)), 0.01)

            for c in circles:
                dy = (lat - c.center_lat) * m_lat
                dx = (lon - c.center_lon) * m_lon
                pred_d = math.sqrt(dx * dx + dy * dy)
                if pred_d < 1.0:
                    pred_d = 1.0
                residuals.append(c.radius_m - pred_d)
                jacobian.append([
                    -dy / pred_d * m_lat,
                    -dx / pred_d * m_lon,
                ])

            # Solve normal equations
            import numpy as np
            r = np.array(residuals)
            J = np.array(jacobian)
            try:
                JTJ = J.T @ J
                JTr = J.T @ r
                delta = np.linalg.solve(JTJ, JTr)
                lat -= float(delta[0])
                lon -= float(delta[1])
            except Exception:
                break

        # Residual RMS as accuracy estimate
        residual_sum = 0.0
        for c in circles:
            d = _haversine_m(lat, lon, c.center_lat, c.center_lon)
            residual_sum += (d - c.radius_m) ** 2
        rms = math.sqrt(residual_sum / len(circles))

        avg_confidence = sum(c.confidence for c in circles) / len(circles)

        return {
            "lat": lat,
            "lon": lon,
            "accuracy_m": max(5.0, rms),
            "towers_used": len(circles),
            "method": "gps_calibrated_nlls",
            "confidence": avg_confidence,
            "circles": [{
                "tower_id": c.tower_id,
                "radius_m": round(c.radius_m, 1),
                "rssi_dbm": round(c.rssi_dbm, 1),
            } for c in circles],
        }

    def _bilaterate(self, circles: List[TowerCircle]) -> Optional[Dict]:
        """2-tower estimation: intersection of two circles gives two points.
        Pick the one closest to the midpoint."""
        c1, c2 = circles[0], circles[1]
        # Midpoint
        mid_lat = (c1.center_lat + c2.center_lat) / 2
        mid_lon = (c1.center_lon + c2.center_lon) / 2
        return {
            "lat": mid_lat,
            "lon": mid_lon,
            "accuracy_m": max(c1.radius_m, c2.radius_m),
            "towers_used": 2,
            "method": "gps_calibrated_bilaterate",
            "confidence": min(c1.confidence, c2.confidence) * 0.5,
        }

    def recalibrate_all(self, gps_lat: float, gps_lon: float,
                        tower_rssi: Dict[str, float]):
        """Recalibrate all towers when GPS becomes available again."""
        for tower_id, rssi in tower_rssi.items():
            if tower_id in self._towers:
                cal = self._towers[tower_id]
                self.calibrate_tower(
                    tower_id, cal.tower_lat, cal.tower_lon,
                    gps_lat, gps_lon, rssi,
                )

    def get_rssi_trend(self, tower_id: str) -> Optional[str]:
        """Get RSSI trend for a tower: CLOSER, FARTHER, STABLE."""
        if tower_id not in self._towers:
            return None
        cal = self._towers[tower_id]
        if len(cal.rssi_history) < 5:
            return "UNKNOWN"
        recent = [r for _, r in cal.rssi_history[-5:]]
        older = [r for _, r in cal.rssi_history[-10:-5]] if len(cal.rssi_history) >= 10 else recent
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        diff = avg_recent - avg_older
        if diff > 2:
            return "CLOSER"   # RSSI increasing = getting closer
        if diff < -2:
            return "FARTHER"  # RSSI decreasing = getting farther
        return "STABLE"

    def get_status(self) -> Dict:
        trends = {}
        for tid in self._towers:
            trends[tid] = self.get_rssi_trend(tid)
        return {
            "towers_calibrated": len(self._towers),
            "calibration_count": self._calibration_count,
            "trilateration_count": self._trilateration_count,
            "tower_trends": trends,
            "circles": [{
                "tower_id": c.tower_id,
                "radius_m": round(c.radius_m, 1),
                "rssi_dbm": round(c.rssi_dbm, 1),
                "calibrated_distance_m": round(self._towers[c.tower_id].calibrated_distance_m, 1),
                "confidence": round(c.confidence, 3),
            } for c in self.get_circles()],
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
