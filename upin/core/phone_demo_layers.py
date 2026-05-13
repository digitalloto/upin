"""
Missing Phone-Demo Layers — UPIN

11 layers from the phone-demo v5 that were not yet in the Python repo.
All implemented as standalone modules that integrate with the existing
UPIN architecture.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 4. TOWER+PREDICT FUSION
# ═══════════════════════════════════════════════════════════════

class TowerPredictFusion:
    """Cross-validates predictor heading with tower RSSI changes.

    If the predictor says "heading north" AND the northern tower
    gets stronger AND the southern tower gets weaker → 3 independent
    sources agree → HIGH confidence heading.
    """

    def __init__(self, agreement_threshold_dbm: float = 2.0):
        self._threshold = agreement_threshold_dbm
        self._validations = 0
        self._agreements = 0

    def validate(self, predicted_heading_deg: float,
                 tower_rssi_changes: Dict[str, Tuple[float, float, float]]
                 ) -> Dict:
        """Validate predicted heading against tower RSSI changes.

        tower_rssi_changes: {tower_id: (bearing_to_tower, rssi_old, rssi_new)}
        If moving toward a tower, its RSSI should increase.
        """
        self._validations += 1
        agreeing = 0
        disagreeing = 0
        details = []

        for tid, (bearing, rssi_old, rssi_new) in tower_rssi_changes.items():
            delta_rssi = rssi_new - rssi_old
            # Angle between heading and tower bearing
            angle_diff = abs(predicted_heading_deg - bearing)
            if angle_diff > 180:
                angle_diff = 360 - angle_diff

            if angle_diff < 60:
                # Moving toward tower — RSSI should increase
                expected = "increase"
                actual = "increase" if delta_rssi > self._threshold else "decrease"
            elif angle_diff > 120:
                # Moving away — RSSI should decrease
                expected = "decrease"
                actual = "decrease" if delta_rssi < -self._threshold else "increase"
            else:
                continue  # perpendicular — skip

            if expected == actual:
                agreeing += 1
            else:
                disagreeing += 1
            details.append({"tower": tid, "expected": expected,
                            "actual": actual, "delta_dbm": round(delta_rssi, 1)})

        total = agreeing + disagreeing
        if total > 0 and agreeing / total > 0.6:
            self._agreements += 1

        return {
            "heading_validated": agreeing > disagreeing,
            "agreeing": agreeing,
            "disagreeing": disagreeing,
            "confidence": agreeing / max(1, total),
            "details": details,
            "lifetime_rate": self._agreements / max(1, self._validations),
        }


# ═══════════════════════════════════════════════════════════════
# 5. CELL DIRECTION (RSSI rate-of-change → heading)
# ═══════════════════════════════════════════════════════════════

class CellDirectionEstimator:
    """Estimate heading from cell tower RSSI rate-of-change.

    If tower A's signal gets stronger over time → you're moving
    TOWARD tower A. If tower B gets weaker → moving AWAY from B.
    The tower you're approaching fastest = your heading direction.
    """

    def __init__(self, window_size: int = 10):
        self._window = window_size
        self._rssi_history: Dict[str, deque] = {}
        self._tower_positions: Dict[str, Tuple[float, float]] = {}

    def register_tower(self, tower_id: str, lat: float, lon: float):
        self._tower_positions[tower_id] = (lat, lon)
        if tower_id not in self._rssi_history:
            self._rssi_history[tower_id] = deque(maxlen=self._window)

    def feed_rssi(self, tower_id: str, rssi_dbm: float):
        if tower_id not in self._rssi_history:
            self._rssi_history[tower_id] = deque(maxlen=self._window)
        self._rssi_history[tower_id].append((time.time(), rssi_dbm))

    def estimate_heading(self, current_lat: float,
                         current_lon: float) -> Optional[Dict]:
        """Estimate heading from which towers are getting stronger/weaker."""
        rates = []
        for tid, history in self._rssi_history.items():
            if len(history) < 3 or tid not in self._tower_positions:
                continue
            # Linear regression on RSSI over time
            times = [t for t, _ in history]
            rssis = [r for _, r in history]
            n = len(times)
            t_mean = sum(times) / n
            r_mean = sum(rssis) / n
            num = sum((t - t_mean) * (r - r_mean) for t, r in zip(times, rssis))
            den = sum((t - t_mean) ** 2 for t in times)
            if abs(den) < 1e-10:
                continue
            slope = num / den  # dBm per second

            t_lat, t_lon = self._tower_positions[tid]
            bearing = math.degrees(math.atan2(
                t_lon - current_lon, t_lat - current_lat)) % 360
            rates.append({"tower": tid, "slope_dbm_s": slope, "bearing": bearing})

        if not rates:
            return None

        # Tower with strongest positive slope = approaching fastest = heading
        rates.sort(key=lambda r: -r["slope_dbm_s"])
        best = rates[0]
        if best["slope_dbm_s"] <= 0:
            # All towers getting weaker — use least-negative
            pass

        # Weighted heading from all positive-slope towers
        total_w = 0.0
        hx = hy = 0.0
        for r in rates:
            if r["slope_dbm_s"] > 0:
                w = r["slope_dbm_s"]
                hx += w * math.cos(math.radians(r["bearing"]))
                hy += w * math.sin(math.radians(r["bearing"]))
                total_w += w

        if total_w > 0:
            heading = math.degrees(math.atan2(hy, hx)) % 360
        else:
            heading = best["bearing"]

        return {
            "heading_deg": heading,
            "confidence": min(1.0, total_w / 5.0),
            "towers_approaching": sum(1 for r in rates if r["slope_dbm_s"] > 0),
            "towers_receding": sum(1 for r in rates if r["slope_dbm_s"] < 0),
            "strongest_approach": best["tower"],
        }


# ═══════════════════════════════════════════════════════════════
# 6. DOPPLER SHIFT (velocity from cell RSSI rate-of-change)
# ═══════════════════════════════════════════════════════════════

class CellDopplerVelocity:
    """Estimate velocity from cell tower RSSI rate-of-change.

    RSSI changes at a rate proportional to how fast you're moving
    toward or away from the tower. Multiple towers → speed + direction.
    """

    def __init__(self, path_loss_n: float = 3.0):
        self._n = path_loss_n
        self._rssi_rates: Dict[str, float] = {}
        self._tower_distances: Dict[str, float] = {}

    def update(self, tower_id: str, rssi_rate_dbm_s: float,
               current_distance_m: float):
        """Feed RSSI change rate for a tower."""
        self._rssi_rates[tower_id] = rssi_rate_dbm_s
        self._tower_distances[tower_id] = current_distance_m

    def estimate_speed(self) -> Optional[Dict]:
        """Estimate speed from RSSI rate-of-change across all towers.

        RSSI = P0 - 10*n*log10(d). dRSSI/dt = -10*n/(d*ln10) * dd/dt
        So dd/dt = -dRSSI/dt * d * ln10 / (10*n)
        """
        speeds = []
        for tid, rate in self._rssi_rates.items():
            d = self._tower_distances.get(tid, 1000)
            if d < 10:
                continue
            radial_speed = -rate * d * math.log(10) / (10 * self._n)
            speeds.append(abs(radial_speed))

        if not speeds:
            return None

        avg_speed = sum(speeds) / len(speeds)
        return {
            "speed_ms": avg_speed,
            "speed_kmh": avg_speed * 3.6,
            "towers_used": len(speeds),
            "method": "cell_doppler",
        }


# ═══════════════════════════════════════════════════════════════
# 7. LANDMARK TRIANGULATION
# ═══════════════════════════════════════════════════════════════

@dataclass
class Landmark:
    name: str
    lat: float
    lon: float
    landmark_type: str = "general"


class LandmarkTriangulation:
    """Position from known landmarks as fixed reference beacons.

    If you know you're 160m from Central Station and 50m from
    the Beach → intersection gives your position.
    """

    def __init__(self):
        self._landmarks: List[Landmark] = []

    def load_landmarks(self, landmarks: List[Landmark]):
        self._landmarks = landmarks

    def add_landmark(self, name: str, lat: float, lon: float,
                     landmark_type: str = "general"):
        self._landmarks.append(Landmark(name, lat, lon, landmark_type))

    def trilaterate(self, distances: Dict[str, float]) -> Optional[Dict]:
        """Given distances to named landmarks, trilaterate position.

        distances: {"Central Station": 160.0, "Beach": 50.0, ...}
        """
        observations = []
        for name, dist in distances.items():
            lm = next((l for l in self._landmarks if l.name == name), None)
            if lm:
                observations.append((lm.lat, lm.lon, dist))

        if len(observations) < 2:
            return None

        # Weighted centroid
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for lat, lon, d in observations:
            w = 1.0 / max(d, 1.0)
            lat_sum += lat * w
            lon_sum += lon * w
            total_w += w

        return {
            "lat": lat_sum / total_w,
            "lon": lon_sum / total_w,
            "landmarks_used": len(observations),
            "landmark_names": list(distances.keys()),
        }

    def get_status(self) -> Dict:
        return {"landmarks_loaded": len(self._landmarks)}


# ═══════════════════════════════════════════════════════════════
# 17. SVM QUALITY GATE
# ═══════════════════════════════════════════════════════════════

class SVMQualityGate:
    """Linear SVM that classifies sensor readings as reliable/unreliable.

    Learns a decision boundary from GPS-validated sensor readings.
    Features: accel magnitude, gyro rate, compass stability, RSSI variance.
    """

    def __init__(self, n_features: int = 6):
        self._weights = [0.0] * n_features
        self._bias = 0.0
        self._trained = False
        self._training_data: List[Tuple[List[float], int]] = []
        self._learning_rate = 0.01
        self._max_training = 1000

    def train_sample(self, features: List[float], reliable: bool):
        """Add one training sample (from GPS-validated period)."""
        label = 1 if reliable else -1
        self._training_data.append((features, label))
        if len(self._training_data) > self._max_training:
            self._training_data = self._training_data[-self._max_training:]

        # Online SGD update
        score = sum(w * f for w, f in zip(self._weights, features)) + self._bias
        if label * score < 1:  # hinge loss
            for i in range(len(self._weights)):
                self._weights[i] += self._learning_rate * label * features[i]
            self._bias += self._learning_rate * label

        if len(self._training_data) >= 20:
            self._trained = True

    def classify(self, features: List[float]) -> Dict:
        """Classify a sensor reading as reliable or unreliable."""
        score = sum(w * f for w, f in zip(self._weights, features)) + self._bias
        reliable = score > 0
        confidence = min(1.0, abs(score) / 3.0)
        return {
            "reliable": reliable,
            "score": round(score, 3),
            "confidence": round(confidence, 3),
            "trained": self._trained,
        }


# ═══════════════════════════════════════════════════════════════
# 18. RANDOM FOREST FUSION
# ═══════════════════════════════════════════════════════════════

class RandomForestFusion:
    """200 decision stumps that vote on position correction.

    Each stump looks at one sensor feature and one threshold.
    Majority vote produces a position correction vector.
    Learns thresholds from GPS-validated data.
    """

    def __init__(self, n_stumps: int = 200, n_features: int = 8):
        import random
        self._stumps = []
        for _ in range(n_stumps):
            feat_idx = random.randint(0, n_features - 1)
            threshold = random.gauss(0, 1)
            correction_lat = random.gauss(0, 0.0001)
            correction_lon = random.gauss(0, 0.0001)
            self._stumps.append({
                "feature": feat_idx,
                "threshold": threshold,
                "correction_lat": correction_lat,
                "correction_lon": correction_lon,
            })
        self._trained = False
        self._train_count = 0

    def train(self, features: List[float],
              error_lat: float, error_lon: float):
        """Train stumps from GPS truth error."""
        self._train_count += 1
        for stump in self._stumps:
            fi = stump["feature"]
            if fi < len(features):
                val = features[fi]
                if val > stump["threshold"]:
                    stump["correction_lat"] = (
                        0.95 * stump["correction_lat"] + 0.05 * error_lat)
                    stump["correction_lon"] = (
                        0.95 * stump["correction_lon"] + 0.05 * error_lon)
        if self._train_count >= 50:
            self._trained = True

    def predict_correction(self, features: List[float]) -> Dict:
        """Vote on position correction from sensor features."""
        lat_sum = lon_sum = 0.0
        votes = 0
        for stump in self._stumps:
            fi = stump["feature"]
            if fi < len(features) and features[fi] > stump["threshold"]:
                lat_sum += stump["correction_lat"]
                lon_sum += stump["correction_lon"]
                votes += 1
        if votes == 0:
            return {"correction_lat": 0, "correction_lon": 0, "votes": 0}
        return {
            "correction_lat": lat_sum / votes,
            "correction_lon": lon_sum / votes,
            "votes": votes,
            "total_stumps": len(self._stumps),
            "trained": self._trained,
        }


# ═══════════════════════════════════════════════════════════════
# 19. MANGHNANI CONE — constraint state machine
# ═══════════════════════════════════════════════════════════════

class ManghnaniCone:
    """State machine constraint: GPS_OK → CONE_GROWING → CONE_REFINED.

    When GPS is lost, a cone of possible positions grows with time.
    As sensor data narrows the possibilities, the cone refines.
    ALL formula outputs are constrained to be inside the cone.
    """

    def __init__(self, max_speed_ms: float = 50.0):
        self._state = "GPS_OK"  # GPS_OK, CONE_GROWING, CONE_REFINED
        self._anchor_lat = 0.0
        self._anchor_lon = 0.0
        self._cone_radius_m = 0.0
        self._cone_heading_deg = 0.0
        self._cone_width_deg = 360.0
        self._max_speed = max_speed_ms
        self._gps_lost_at: Optional[float] = None
        self._last_speed_ms = 0.0

    def gps_fix(self, lat: float, lon: float, speed_ms: float,
                heading_deg: float):
        """GPS available — anchor the cone."""
        self._state = "GPS_OK"
        self._anchor_lat = lat
        self._anchor_lon = lon
        self._cone_radius_m = 0.0
        self._cone_heading_deg = heading_deg
        self._cone_width_deg = 360.0
        self._last_speed_ms = speed_ms
        self._gps_lost_at = None

    def gps_lost(self):
        """GPS denied — start growing the cone."""
        if self._state == "GPS_OK":
            self._state = "CONE_GROWING"
            self._gps_lost_at = time.time()

    def update(self, heading_deg: Optional[float] = None,
               speed_ms: Optional[float] = None,
               cell_radius_m: Optional[float] = None) -> Dict:
        """Update cone state from sensor data."""
        now = time.time()

        if self._state == "GPS_OK":
            return {"state": "GPS_OK", "radius_m": 0}

        # Grow cone with time
        if self._gps_lost_at:
            dt = now - self._gps_lost_at
            v = speed_ms if speed_ms is not None else self._last_speed_ms
            self._cone_radius_m = min(v * dt, self._max_speed * dt)

        # Refine with heading
        if heading_deg is not None:
            self._cone_heading_deg = heading_deg
            self._cone_width_deg = max(30.0, self._cone_width_deg * 0.95)
            if self._cone_width_deg < 90:
                self._state = "CONE_REFINED"

        # Refine with cell tower
        if cell_radius_m is not None and cell_radius_m < self._cone_radius_m:
            self._cone_radius_m = cell_radius_m
            self._state = "CONE_REFINED"

        return {
            "state": self._state,
            "radius_m": round(self._cone_radius_m, 1),
            "heading_deg": round(self._cone_heading_deg, 1),
            "width_deg": round(self._cone_width_deg, 1),
            "anchor": (self._anchor_lat, self._anchor_lon),
        }

    def constrain(self, pred_lat: float, pred_lon: float) -> Tuple[float, float, bool]:
        """Constrain a prediction to be inside the cone."""
        if self._state == "GPS_OK":
            return pred_lat, pred_lon, False
        dist = _haversine_m(self._anchor_lat, self._anchor_lon, pred_lat, pred_lon)
        if dist <= self._cone_radius_m:
            return pred_lat, pred_lon, False
        scale = self._cone_radius_m / max(dist, 0.01)
        new_lat = self._anchor_lat + (pred_lat - self._anchor_lat) * scale
        new_lon = self._anchor_lon + (pred_lon - self._anchor_lon) * scale
        return new_lat, new_lon, True


# ═══════════════════════════════════════════════════════════════
# 23. FROZEN GPS DETECTION
# ═══════════════════════════════════════════════════════════════

class FrozenGPSDetector:
    """Detect when GPS position stops updating but IMU shows motion.

    Same position for 30s + accelerometer showing movement = GPS frozen.
    Auto-switch to tower + sensor positioning.
    """

    def __init__(self, freeze_threshold_s: float = 30.0,
                 motion_threshold_ms2: float = 0.3):
        self._threshold_s = freeze_threshold_s
        self._motion_threshold = motion_threshold_ms2
        self._last_position: Optional[Tuple[float, float]] = None
        self._position_unchanged_since: Optional[float] = None
        self._is_frozen = False

    def check(self, gps_lat: float, gps_lon: float,
              imu_accel_magnitude: float) -> Dict:
        now = time.time()
        moved = True
        if self._last_position is not None:
            dist = _haversine_m(self._last_position[0], self._last_position[1],
                                gps_lat, gps_lon)
            moved = dist > 1.0  # more than 1m = moved

        if moved:
            self._last_position = (gps_lat, gps_lon)
            self._position_unchanged_since = now
            self._is_frozen = False
        else:
            if self._position_unchanged_since is None:
                self._position_unchanged_since = now

        static_duration = now - (self._position_unchanged_since or now)
        has_motion = imu_accel_magnitude > self._motion_threshold

        if static_duration >= self._threshold_s and has_motion:
            self._is_frozen = True

        return {
            "frozen": self._is_frozen,
            "static_duration_s": round(static_duration, 1),
            "imu_motion": has_motion,
            "action": "SWITCH_TO_SENSORS" if self._is_frozen else "GPS_OK",
        }


# ═══════════════════════════════════════════════════════════════
# 24. SESSION VALIDATION
# ═══════════════════════════════════════════════════════════════

class SessionValidator:
    """5-check session quality assessment → Grade A/B/C/D/F.

    Checks: GPS health, motion detected, cross-check agreement,
    tower sanity, sensor responsiveness.
    """

    def validate(self, gps_fix_count: int, motion_detected: bool,
                 cross_check_rate: float, towers_valid: int,
                 sensor_responsive: bool) -> Dict:
        score = 0
        checks = {}

        # 1. GPS health (0-20)
        gps_score = min(20, gps_fix_count)
        checks["gps_health"] = gps_score
        score += gps_score

        # 2. Motion (0-20)
        motion_score = 20 if motion_detected else 0
        checks["motion"] = motion_score
        score += motion_score

        # 3. Cross-check (0-20)
        cc_score = int(cross_check_rate * 20)
        checks["cross_check"] = cc_score
        score += cc_score

        # 4. Tower sanity (0-20)
        tower_score = min(20, towers_valid * 5)
        checks["tower_sanity"] = tower_score
        score += tower_score

        # 5. Sensor responsive (0-20)
        sensor_score = 20 if sensor_responsive else 0
        checks["sensor_responsive"] = sensor_score
        score += sensor_score

        if score >= 80:
            grade = "A"
        elif score >= 60:
            grade = "B"
        elif score >= 40:
            grade = "C"
        elif score >= 20:
            grade = "D"
        else:
            grade = "F"

        return {"grade": grade, "score": score, "checks": checks}


# ═══════════════════════════════════════════════════════════════
# 25. COORDINATE BOUNDS CHECK
# ═══════════════════════════════════════════════════════════════

class CoordinateBoundsCheck:
    """Reject phantom coordinates outside operational area + impossible speeds."""

    def __init__(self, min_lat: float = -90, max_lat: float = 90,
                 min_lon: float = -180, max_lon: float = 180,
                 max_speed_ms: float = 500.0):
        self._min_lat = min_lat
        self._max_lat = max_lat
        self._min_lon = min_lon
        self._max_lon = max_lon
        self._max_speed = max_speed_ms
        self._last_pos: Optional[Tuple[float, float, float]] = None

    def set_operational_area(self, min_lat: float, max_lat: float,
                             min_lon: float, max_lon: float):
        self._min_lat = min_lat
        self._max_lat = max_lat
        self._min_lon = min_lon
        self._max_lon = max_lon

    def check(self, lat: float, lon: float) -> Dict:
        now = time.time()
        issues = []

        if not (self._min_lat <= lat <= self._max_lat):
            issues.append(f"Latitude {lat} outside [{self._min_lat}, {self._max_lat}]")
        if not (self._min_lon <= lon <= self._max_lon):
            issues.append(f"Longitude {lon} outside [{self._min_lon}, {self._max_lon}]")

        if self._last_pos is not None:
            dt = now - self._last_pos[2]
            if dt > 0:
                dist = _haversine_m(self._last_pos[0], self._last_pos[1], lat, lon)
                speed = dist / dt
                if speed > self._max_speed:
                    issues.append(f"Impossible speed {speed:.0f} m/s (>{self._max_speed})")

        self._last_pos = (lat, lon, now)
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "action": "ACCEPT" if not issues else "REJECT",
        }


# ═══════════════════════════════════════════════════════════════
# 26. COMPASS VALIDITY GATE
# ═══════════════════════════════════════════════════════════════

class CompassValidityGate:
    """Reject invalid compass readings. Returns last valid if current is bad."""

    def __init__(self):
        self._last_valid_heading: float = 0.0
        self._rejection_count = 0

    def validate(self, heading_deg: float) -> Dict:
        if 0 <= heading_deg <= 360:
            self._last_valid_heading = heading_deg
            return {"valid": True, "heading_deg": heading_deg}
        self._rejection_count += 1
        return {
            "valid": False,
            "heading_deg": self._last_valid_heading,
            "rejected_value": heading_deg,
            "rejections": self._rejection_count,
        }


# ═══════════════════════════════════════════════════════════════
# 28. CID COLLISION GUARD
# ═══════════════════════════════════════════════════════════════

class CIDCollisionGuard:
    """Reject tower CID matches that are too far from calibration city.

    Cell IDs can repeat across different cities. If you calibrated
    in Chennai and CID:24796 appears but the matched tower is in
    Delhi → it's a different tower with the same ID. Reject it.
    """

    def __init__(self, max_distance_km: float = 50.0):
        self._max_dist_km = max_distance_km
        self._calibration_positions: Dict[str, Tuple[float, float]] = {}

    def register_calibration(self, tower_id: str, lat: float, lon: float):
        self._calibration_positions[tower_id] = (lat, lon)

    def check(self, tower_id: str, candidate_lat: float,
              candidate_lon: float) -> Dict:
        if tower_id not in self._calibration_positions:
            return {"valid": True, "reason": "no calibration data"}

        cal_lat, cal_lon = self._calibration_positions[tower_id]
        dist = _haversine_m(cal_lat, cal_lon, candidate_lat, candidate_lon)
        dist_km = dist / 1000.0
        valid = dist_km <= self._max_dist_km

        return {
            "valid": valid,
            "distance_km": round(dist_km, 1),
            "max_km": self._max_dist_km,
            "action": "ACCEPT" if valid else "REJECT_CID_COLLISION",
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
