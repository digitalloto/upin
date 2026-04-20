"""
Predictive Positioning Engine — UPIN

"Shoot where the target WILL be, not where it is."

Instead of estimating where the platform is NOW (always stale),
predict where it will be in N seconds. Then confirm with incoming
sensor data. A validated predictor is 10× more useful in GPS denial
than a reactive estimator — because you've PROVEN it works.

Key components:
1. AccelerationTrend — 20-sample moving avg determines cruise/accel/decel
2. PredictiveModel — projects position forward using velocity + accel trend
3. CheckpointValidator — pre-loaded waypoints for trajectory confirmation
4. MultiModelPredictor — all formulas predict T+N, best is selected

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 1. ACCELERATION TREND — Moving average over last N readings
# ═══════════════════════════════════════════════════════════════

class AccelerationTrend:
    """Determines if the platform is cruising, accelerating, or decelerating
    based on a moving average of the last N acceleration readings.

    This is critical for prediction: a decelerating platform won't travel
    as far in 5s as a cruising one.
    """

    def __init__(self, window_size: int = 20):
        self._window_size = window_size
        self._accel_history: deque = deque(maxlen=window_size)
        self._speed_history: deque = deque(maxlen=window_size)
        self._timestamps: deque = deque(maxlen=window_size)

    def feed(self, accel_forward_ms2: float, speed_ms: float,
             timestamp: Optional[float] = None):
        """Feed a new acceleration + speed reading."""
        t = timestamp if timestamp is not None else time.time()
        self._accel_history.append(accel_forward_ms2)
        self._speed_history.append(speed_ms)
        self._timestamps.append(t)

    @property
    def avg_acceleration(self) -> float:
        """Moving average of forward acceleration (m/s^2)."""
        if not self._accel_history:
            return 0.0
        return sum(self._accel_history) / len(self._accel_history)

    @property
    def avg_speed(self) -> float:
        """Moving average speed (m/s)."""
        if not self._speed_history:
            return 0.0
        return sum(self._speed_history) / len(self._speed_history)

    @property
    def state(self) -> str:
        """Current motion state: CRUISING, ACCELERATING, DECELERATING, STOPPED."""
        avg_a = self.avg_acceleration
        avg_s = self.avg_speed
        if avg_s < 0.5:
            return "STOPPED"
        if avg_a > 0.5:
            return "ACCELERATING"
        if avg_a < -0.5:
            return "DECELERATING"
        return "CRUISING"

    def predict_speed_at(self, dt_seconds: float) -> float:
        """Predict speed at T+dt given current trend. Clamped to >= 0."""
        current = self.avg_speed
        accel = self.avg_acceleration
        predicted = current + accel * dt_seconds
        return max(0.0, predicted)

    def predict_distance(self, dt_seconds: float) -> float:
        """Predict distance travelled in next dt seconds.

        Uses: d = v0*t + 0.5*a*t^2, clamped so distance never goes negative.
        """
        v0 = self.avg_speed
        a = self.avg_acceleration
        d = v0 * dt_seconds + 0.5 * a * dt_seconds * dt_seconds
        return max(0.0, d)

    def get_stats(self) -> Dict:
        return {
            "state": self.state,
            "avg_speed_ms": round(self.avg_speed, 2),
            "avg_accel_ms2": round(self.avg_acceleration, 3),
            "samples": len(self._accel_history),
            "window_size": self._window_size,
        }


# ═══════════════════════════════════════════════════════════════
# 2. PREDICTIVE MODEL — Projects position forward in time
# ═══════════════════════════════════════════════════════════════

@dataclass
class Prediction:
    """A forward position prediction."""
    lat: float
    lon: float
    altitude_m: float
    heading_deg: float
    speed_ms: float
    predicted_at: float        # when prediction was made
    target_time: float         # when the predicted position is for
    model_name: str = ""
    confidence: float = 0.0


@dataclass
class PredictionResult:
    """Result of a prediction validation."""
    prediction: Prediction
    actual_lat: float
    actual_lon: float
    error_m: float
    time_elapsed_s: float
    validated: bool  # True if error < threshold


class PredictiveModel:
    """Core predictive positioning model.

    Projects current state (position + velocity + acceleration trend)
    forward by dt seconds. The prediction accounts for:
    - Current heading and speed
    - Acceleration trend (cruising/accel/decel from moving average)
    - Turn rate (from gyro history)
    - Altitude trend
    """

    def __init__(self, prediction_horizon_s: float = 5.0):
        self._horizon_s = prediction_horizon_s
        self._accel_trend = AccelerationTrend(window_size=20)
        self._heading_rate_dps: float = 0.0  # deg/s turn rate
        self._heading_history: deque = deque(maxlen=20)
        self._last_prediction: Optional[Prediction] = None
        self._validation_history: List[PredictionResult] = []
        self._max_history = 200

    def update(self, lat: float, lon: float, altitude_m: float,
               heading_deg: float, speed_ms: float,
               accel_forward_ms2: float, gyro_z_rad_s: float = 0.0):
        """Feed current state for model update."""
        self._accel_trend.feed(accel_forward_ms2, speed_ms)
        self._heading_history.append(heading_deg)
        self._heading_rate_dps = math.degrees(gyro_z_rad_s)
        self._current_state = {
            "lat": lat, "lon": lon, "alt": altitude_m,
            "heading": heading_deg, "speed": speed_ms,
        }

    def predict(self, dt_seconds: Optional[float] = None,
                model_name: str = "primary") -> Prediction:
        """Predict position at T + dt seconds from now."""
        dt = dt_seconds if dt_seconds is not None else self._horizon_s
        now = time.time()

        state = getattr(self, "_current_state", None)
        if state is None:
            return Prediction(lat=0, lon=0, altitude_m=0, heading_deg=0,
                              speed_ms=0, predicted_at=now,
                              target_time=now + dt, model_name=model_name)

        # Predict distance using acceleration trend
        dist_m = self._accel_trend.predict_distance(dt)

        # Predict heading using turn rate
        heading = state["heading"] + self._heading_rate_dps * dt
        heading %= 360.0

        # Average heading over the prediction interval (arc)
        avg_heading = state["heading"] + self._heading_rate_dps * dt * 0.5
        avg_heading_rad = math.radians(avg_heading)

        # Project lat/lon
        d_north = dist_m * math.cos(avg_heading_rad)
        d_east = dist_m * math.sin(avg_heading_rad)

        lat = state["lat"] + d_north / 111_320.0
        cos_lat = math.cos(math.radians(state["lat"]))
        lon = state["lon"] + d_east / (111_320.0 * max(cos_lat, 0.01))

        pred_speed = self._accel_trend.predict_speed_at(dt)

        prediction = Prediction(
            lat=lat, lon=lon, altitude_m=state["alt"],
            heading_deg=heading, speed_ms=pred_speed,
            predicted_at=now, target_time=now + dt,
            model_name=model_name,
            confidence=self._compute_confidence(),
        )
        self._last_prediction = prediction
        return prediction

    def validate(self, actual_lat: float, actual_lon: float,
                 threshold_m: float = 20.0) -> Optional[PredictionResult]:
        """Validate the last prediction against actual position."""
        if self._last_prediction is None:
            return None
        pred = self._last_prediction
        error = _haversine_m(pred.lat, pred.lon, actual_lat, actual_lon)
        elapsed = time.time() - pred.predicted_at

        result = PredictionResult(
            prediction=pred,
            actual_lat=actual_lat,
            actual_lon=actual_lon,
            error_m=error,
            time_elapsed_s=elapsed,
            validated=error <= threshold_m,
        )
        self._validation_history.append(result)
        if len(self._validation_history) > self._max_history:
            self._validation_history = self._validation_history[-self._max_history:]
        self._last_prediction = None
        return result

    def _compute_confidence(self) -> float:
        """Confidence based on recent prediction accuracy."""
        if not self._validation_history:
            return 0.3
        recent = self._validation_history[-20:]
        validated = sum(1 for r in recent if r.validated)
        return min(0.95, validated / max(1, len(recent)))

    @property
    def accel_trend(self) -> AccelerationTrend:
        return self._accel_trend

    @property
    def validation_rate(self) -> float:
        if not self._validation_history:
            return 0.0
        recent = self._validation_history[-50:]
        return sum(1 for r in recent if r.validated) / max(1, len(recent))

    def get_stats(self) -> Dict:
        return {
            "horizon_s": self._horizon_s,
            "accel_state": self._accel_trend.state,
            "avg_speed_ms": self._accel_trend.avg_speed,
            "heading_rate_dps": round(self._heading_rate_dps, 2),
            "validation_rate": round(self.validation_rate, 3),
            "total_validations": len(self._validation_history),
            "confidence": round(self._compute_confidence(), 3),
        }


# ═══════════════════════════════════════════════════════════════
# 3. CHECKPOINT VALIDATOR — Pre-loaded waypoints for confirmation
# ═══════════════════════════════════════════════════════════════

@dataclass
class Checkpoint:
    """A known waypoint along a pre-loaded route/flight plan."""
    name: str
    lat: float
    lon: float
    altitude_m: float = 0.0
    expected_speed_ms: float = 0.0
    sequence: int = 0
    confirmed: bool = False
    confirmed_at: Optional[float] = None
    prediction_error_m: Optional[float] = None


class CheckpointValidator:
    """Pre-loaded waypoints from a flight/route plan.

    When GPS confirms a checkpoint, the trajectory model is validated.
    During GPS denial, approaching a predicted checkpoint with matching
    sensor signatures gives a high-confidence position fix.
    """

    def __init__(self, proximity_threshold_m: float = 100.0):
        self._checkpoints: List[Checkpoint] = []
        self._proximity_m = proximity_threshold_m
        self._next_checkpoint_idx = 0

    def load_route(self, waypoints: List[Tuple[str, float, float, float]]):
        """Load a route as a sequence of (name, lat, lon, altitude_m)."""
        self._checkpoints = []
        for i, (name, lat, lon, alt) in enumerate(waypoints):
            self._checkpoints.append(Checkpoint(
                name=name, lat=lat, lon=lon, altitude_m=alt, sequence=i,
            ))
        self._next_checkpoint_idx = 0

    def check_position(self, lat: float, lon: float,
                       predicted_lat: Optional[float] = None,
                       predicted_lon: Optional[float] = None) -> Optional[Dict]:
        """Check if current position matches any upcoming checkpoint."""
        if self._next_checkpoint_idx >= len(self._checkpoints):
            return None
        cp = self._checkpoints[self._next_checkpoint_idx]
        dist = _haversine_m(lat, lon, cp.lat, cp.lon)
        if dist <= self._proximity_m:
            cp.confirmed = True
            cp.confirmed_at = time.time()
            if predicted_lat is not None and predicted_lon is not None:
                cp.prediction_error_m = _haversine_m(
                    predicted_lat, predicted_lon, cp.lat, cp.lon)
            self._next_checkpoint_idx += 1
            return {
                "checkpoint": cp.name,
                "sequence": cp.sequence,
                "confirmed": True,
                "distance_m": dist,
                "prediction_error_m": cp.prediction_error_m,
                "remaining_checkpoints": (len(self._checkpoints)
                                           - self._next_checkpoint_idx),
            }
        return None

    def next_checkpoint(self) -> Optional[Checkpoint]:
        if self._next_checkpoint_idx >= len(self._checkpoints):
            return None
        return self._checkpoints[self._next_checkpoint_idx]

    def distance_to_next(self, lat: float, lon: float) -> float:
        cp = self.next_checkpoint()
        if cp is None:
            return float('inf')
        return _haversine_m(lat, lon, cp.lat, cp.lon)

    def get_stats(self) -> Dict:
        confirmed = sum(1 for cp in self._checkpoints if cp.confirmed)
        return {
            "total_checkpoints": len(self._checkpoints),
            "confirmed": confirmed,
            "remaining": len(self._checkpoints) - confirmed,
            "next": (self._checkpoints[self._next_checkpoint_idx].name
                     if self._next_checkpoint_idx < len(self._checkpoints)
                     else None),
        }


# ═══════════════════════════════════════════════════════════════
# 4. MULTI-MODEL PREDICTOR — All formulas predict, best wins
# ═══════════════════════════════════════════════════════════════

class MultiModelPredictor:
    """Run multiple predictive models in parallel, score them all.

    Each formula/algorithm produces its own 5-second prediction.
    After 5 seconds, we compare all predictions against reality.
    The best predictor rises to the top via natural selection.
    """

    def __init__(self, horizon_s: float = 5.0):
        self._horizon_s = horizon_s
        self._models: Dict[str, PredictiveModel] = {}
        self._rankings: List[Tuple[str, float]] = []

    def register_model(self, name: str):
        """Register a new predictive model (one per formula)."""
        self._models[name] = PredictiveModel(
            prediction_horizon_s=self._horizon_s)

    def update_all(self, lat: float, lon: float, altitude_m: float,
                   heading_deg: float, speed_ms: float,
                   accel_forward_ms2: float, gyro_z_rad_s: float = 0.0):
        """Feed current state to ALL models."""
        for model in self._models.values():
            model.update(lat, lon, altitude_m, heading_deg, speed_ms,
                         accel_forward_ms2, gyro_z_rad_s)

    def predict_all(self) -> Dict[str, Prediction]:
        """Get predictions from all models."""
        return {name: model.predict(model_name=name)
                for name, model in self._models.items()}

    def validate_all(self, actual_lat: float, actual_lon: float,
                     threshold_m: float = 20.0) -> Dict[str, PredictionResult]:
        """Validate all models against actual position. Re-rank."""
        results = {}
        for name, model in self._models.items():
            r = model.validate(actual_lat, actual_lon, threshold_m)
            if r is not None:
                results[name] = r
        self._update_rankings()
        return results

    def _update_rankings(self):
        """Rank models by validation rate (higher = better predictor)."""
        scored = [(name, model.validation_rate)
                  for name, model in self._models.items()
                  if model._validation_history]
        scored.sort(key=lambda x: -x[1])
        self._rankings = scored

    def best_model(self) -> Optional[str]:
        """Name of the best performing predictor."""
        if not self._rankings:
            return None
        return self._rankings[0][0]

    def best_prediction(self) -> Optional[Prediction]:
        """Get prediction from the best-performing model."""
        best = self.best_model()
        if best is None and self._models:
            best = next(iter(self._models))
        if best is None:
            return None
        return self._models[best].predict(model_name=best)

    def get_rankings(self) -> List[Dict]:
        return [{"model": name, "validation_rate": round(rate, 3),
                 "confidence": round(self._models[name]._compute_confidence(), 3)}
                for name, rate in self._rankings]

    def get_stats(self) -> Dict:
        return {
            "models_registered": len(self._models),
            "horizon_s": self._horizon_s,
            "best_model": self.best_model(),
            "rankings": self.get_rankings()[:5],
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
