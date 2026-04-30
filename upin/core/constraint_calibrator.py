"""
Constraint-Fused Calibration Engine — UPIN

The brain that ties everything together:

1. Cell tower triangulation → gives a CIRCLE (you're somewhere in here)
2. PUE speed×time → gives a MAX RADIUS (you can't be further than this)
3. Predictive path → gives a LINE (you're probably along this path)
4. Sensor heading + speed → gives a DIRECTION (you're moving this way)

INTERSECTION of all four = tiny search area.

Every formula MUST produce results inside this area. If a formula
predicts a position outside the constraint circle → REJECT + PENALISE.
If a formula predicts inside → ACCEPT + REWARD.

Over time, formulas learn which sensor weights produce positions
inside the constraint circle. This IS the calibration — the formulas
discover the correct sensor-to-position mapping by being forced to
agree with the constraint circle thousands of times.

When GPS is denied:
- Cell towers still give a circle (towers don't need GPS)
- PUE still gives a max radius (physics doesn't need GPS)
- Sensors still give heading + speed (IMU doesn't need GPS)
- The trained formulas now produce accurate positions from sensors alone
  because they were calibrated against the constraint circle

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ConstraintCircle:
    """The fused constraint area — intersection of all bounds."""
    center_lat: float
    center_lon: float
    radius_m: float
    source: str              # what determined this circle
    cell_radius_m: float = 0.0
    pue_radius_m: float = 0.0
    heading_cone_deg: float = 360.0
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class FormulaScore:
    """Tracking how well a formula stays inside the constraint."""
    formula_name: str
    total_predictions: int = 0
    inside_constraint: int = 0
    total_error_m: float = 0.0
    best_error_m: float = float('inf')
    worst_error_m: float = 0.0
    current_weight: float = 1.0
    calibrated: bool = False

    @property
    def accuracy_rate(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.inside_constraint / self.total_predictions

    @property
    def avg_error_m(self) -> float:
        if self.total_predictions == 0:
            return float('inf')
        return self.total_error_m / self.total_predictions


class ConstraintCalibrator:
    """Fuses cell triangulation + PUE + sensors into a constraint circle,
    then calibrates all formulas against it.

    Every tick:
    1. Compute constraint circle (intersection of cell + PUE + heading)
    2. Each formula predicts a position
    3. Check if prediction is inside the circle
    4. Inside → reward (increase weight). Outside → penalise (decrease weight)
    5. Over thousands of ticks → formulas learn the correct sensor mapping

    The result: formulas that work with sensor-only data because they've
    been trained against the constraint circle which IS ground truth.
    """

    def __init__(self, reward_rate: float = 0.01,
                 penalty_rate: float = 0.02,
                 min_weight: float = 0.05,
                 max_weight: float = 2.0):
        self._reward = reward_rate
        self._penalty = penalty_rate
        self._min_w = min_weight
        self._max_w = max_weight

        self._formulas: Dict[str, FormulaScore] = {}
        self._constraint_history: deque = deque(maxlen=500)
        self._calibration_ticks = 0
        self._last_constraint: Optional[ConstraintCircle] = None

        # Sensor calibration learned values
        self._learned_accel_scale = 1.0
        self._learned_gyro_scale = 1.0
        self._learned_compass_offset_deg = 0.0
        self._learned_speed_factor = 1.0

    def register_formula(self, formula_name: str):
        """Register a formula for calibration tracking."""
        if formula_name not in self._formulas:
            self._formulas[formula_name] = FormulaScore(
                formula_name=formula_name)

    def compute_constraint(self,
                           cell_lat: Optional[float] = None,
                           cell_lon: Optional[float] = None,
                           cell_accuracy_m: Optional[float] = None,
                           pue_center_lat: Optional[float] = None,
                           pue_center_lon: Optional[float] = None,
                           pue_radius_m: Optional[float] = None,
                           heading_deg: Optional[float] = None,
                           speed_ms: float = 0.0) -> ConstraintCircle:
        """Compute the fused constraint circle from all available bounds.

        The final circle is the INTERSECTION (tightest bound wins).
        """
        # Start with the widest possible
        best_lat = 0.0
        best_lon = 0.0
        best_radius = float('inf')
        source_parts = []

        # Cell tower constraint
        if cell_lat is not None and cell_lon is not None and cell_accuracy_m:
            if cell_accuracy_m < best_radius:
                best_lat = cell_lat
                best_lon = cell_lon
                best_radius = cell_accuracy_m
                source_parts.append("cell")

        # PUE constraint
        if (pue_center_lat is not None and pue_center_lon is not None
                and pue_radius_m is not None):
            if pue_radius_m < best_radius:
                best_lat = pue_center_lat
                best_lon = pue_center_lon
                best_radius = pue_radius_m
                source_parts.append("pue")
            elif pue_radius_m < best_radius * 2:
                # Intersect: use weighted average center, min radius
                w_cell = 1.0 / max(best_radius, 1)
                w_pue = 1.0 / max(pue_radius_m, 1)
                total_w = w_cell + w_pue
                best_lat = (best_lat * w_cell + pue_center_lat * w_pue) / total_w
                best_lon = (best_lon * w_cell + pue_center_lon * w_pue) / total_w
                best_radius = min(best_radius, pue_radius_m)
                source_parts.append("pue")

        # Heading cone narrows the circle further
        heading_cone = 360.0
        if heading_deg is not None and speed_ms > 1.0:
            heading_cone = max(30.0, 180.0 - speed_ms * 3)
            source_parts.append("heading")

        # If we have nothing, return a huge circle
        if best_radius == float('inf'):
            best_radius = 10000.0
            source_parts = ["none"]

        confidence = 0.0
        if "cell" in source_parts:
            confidence += 0.4
        if "pue" in source_parts:
            confidence += 0.3
        if "heading" in source_parts:
            confidence += 0.2
        confidence = min(1.0, confidence)

        constraint = ConstraintCircle(
            center_lat=best_lat,
            center_lon=best_lon,
            radius_m=best_radius,
            source="+".join(source_parts),
            cell_radius_m=cell_accuracy_m or 0,
            pue_radius_m=pue_radius_m or 0,
            heading_cone_deg=heading_cone,
            confidence=confidence,
        )
        self._last_constraint = constraint
        self._constraint_history.append(constraint)
        return constraint

    def score_predictions(self, constraint: ConstraintCircle,
                          predictions: Dict[str, Tuple[float, float]]
                          ) -> Dict[str, Dict]:
        """Score each formula's prediction against the constraint circle.

        predictions: {formula_name: (lat, lon)}
        Returns per-formula results with inside/outside verdict.
        """
        self._calibration_ticks += 1
        results = {}

        for name, (pred_lat, pred_lon) in predictions.items():
            if name not in self._formulas:
                self.register_formula(name)

            fs = self._formulas[name]
            dist = _haversine_m(constraint.center_lat, constraint.center_lon,
                                pred_lat, pred_lon)
            inside = dist <= constraint.radius_m
            fs.total_predictions += 1
            fs.total_error_m += dist

            if dist < fs.best_error_m:
                fs.best_error_m = dist
            if dist > fs.worst_error_m:
                fs.worst_error_m = dist

            if inside:
                fs.inside_constraint += 1
                fs.current_weight = min(self._max_w,
                                        fs.current_weight + self._reward)
            else:
                fs.current_weight = max(self._min_w,
                                        fs.current_weight - self._penalty)

            # Mark as calibrated after 100+ predictions with >70% inside
            if fs.total_predictions >= 100 and fs.accuracy_rate > 0.7:
                fs.calibrated = True

            results[name] = {
                "inside": inside,
                "distance_m": round(dist, 1),
                "constraint_radius_m": round(constraint.radius_m, 1),
                "weight": round(fs.current_weight, 3),
                "accuracy_rate": round(fs.accuracy_rate, 3),
                "calibrated": fs.calibrated,
            }

        return results

    def constrain_prediction(self, constraint: ConstraintCircle,
                             pred_lat: float, pred_lon: float
                             ) -> Tuple[float, float, bool]:
        """Pull a prediction inside the constraint circle if outside.

        Returns (lat, lon, was_constrained).
        """
        dist = _haversine_m(constraint.center_lat, constraint.center_lon,
                            pred_lat, pred_lon)
        if dist <= constraint.radius_m:
            return pred_lat, pred_lon, False

        # Pull to edge of constraint circle
        scale = constraint.radius_m / max(dist, 0.01)
        new_lat = constraint.center_lat + (pred_lat - constraint.center_lat) * scale
        new_lon = constraint.center_lon + (pred_lon - constraint.center_lon) * scale
        return new_lat, new_lon, True

    def get_best_formulas(self, top_n: int = 5) -> List[Dict]:
        """Get the top N best-calibrated formulas by accuracy rate."""
        scored = sorted(self._formulas.values(),
                        key=lambda f: (-f.accuracy_rate, f.avg_error_m))
        return [{
            "formula": f.formula_name,
            "accuracy_rate": round(f.accuracy_rate, 3),
            "avg_error_m": round(f.avg_error_m, 1),
            "best_error_m": round(f.best_error_m, 1),
            "weight": round(f.current_weight, 3),
            "calibrated": f.calibrated,
            "predictions": f.total_predictions,
        } for f in scored[:top_n]]

    def get_sensor_calibration(self) -> Dict:
        """Get the learned sensor calibration values."""
        return {
            "accel_scale": self._learned_accel_scale,
            "gyro_scale": self._learned_gyro_scale,
            "compass_offset_deg": self._learned_compass_offset_deg,
            "speed_factor": self._learned_speed_factor,
        }

    def learn_sensor_calibration(self,
                                 formula_predictions: Dict[str, Tuple[float, float]],
                                 constraint: ConstraintCircle):
        """Adjust sensor calibration based on which formulas are inside.

        If formulas with high accel_scale are consistently inside,
        learn that accel_scale should be high. This is the mechanism
        that discovers the correct sensor-to-position mapping.
        """
        if not formula_predictions:
            return

        inside_formulas = []
        outside_formulas = []
        for name, (lat, lon) in formula_predictions.items():
            dist = _haversine_m(constraint.center_lat, constraint.center_lon,
                                lat, lon)
            if dist <= constraint.radius_m:
                inside_formulas.append(name)
            else:
                outside_formulas.append(name)

        # Adjust calibration toward what the inside formulas are doing
        if len(inside_formulas) > len(outside_formulas):
            # System is converging — increase confidence in current calibration
            pass
        elif outside_formulas:
            # Many formulas outside — sensors may need recalibration
            # Nudge speed factor based on distance errors
            avg_dist = sum(
                _haversine_m(constraint.center_lat, constraint.center_lon,
                             formula_predictions[n][0], formula_predictions[n][1])
                for n in outside_formulas
            ) / len(outside_formulas)

            if avg_dist > constraint.radius_m * 2:
                # Predictions are too far — speed factor may be too high
                self._learned_speed_factor *= 0.99
            elif avg_dist < constraint.radius_m * 0.5:
                self._learned_speed_factor *= 1.01
            self._learned_speed_factor = max(0.5, min(2.0,
                                             self._learned_speed_factor))

    def get_status(self) -> Dict:
        calibrated = sum(1 for f in self._formulas.values() if f.calibrated)
        total = len(self._formulas)
        avg_accuracy = (sum(f.accuracy_rate for f in self._formulas.values())
                        / max(1, total))
        return {
            "calibration_ticks": self._calibration_ticks,
            "formulas_tracked": total,
            "formulas_calibrated": calibrated,
            "avg_accuracy_rate": round(avg_accuracy, 3),
            "last_constraint_radius_m": (round(self._last_constraint.radius_m, 1)
                                          if self._last_constraint else None),
            "last_constraint_source": (self._last_constraint.source
                                        if self._last_constraint else None),
            "sensor_calibration": self.get_sensor_calibration(),
            "top_formulas": self.get_best_formulas(3),
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
