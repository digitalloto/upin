"""
Continuous Background Learning — UPIN

Every layer secretly predicts ahead while GPS is active, then checks
against reality. Wrong predictions trigger auto-tuning. By the time
GPS is jammed, every layer has already been training on YOUR device.

Components:
1. Background Validator — 30s predict-then-check cycle for all layers
2. Sensor Auto-Calibrator — learns your phone's specific biases
3. Fish School Grid Search — 6 schools with different parameters compete
4. User Profile — saves learned parameters across sessions
5. Continuous Tuning — every GPS tick is a learning opportunity

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════
#  1. BACKGROUND VALIDATOR — predict-then-check every 30s
# ══════════════════════════════════════════════════════════════════

@dataclass
class ValidationResult:
    """One validation cycle result."""
    cycle: int
    timestamp: float
    predictions: Dict[str, Tuple[float, float]]  # agent_name -> (pred_lat, pred_lon)
    actual: Tuple[float, float]
    errors: Dict[str, float]                      # agent_name -> error_m
    best_agent: str
    best_error_m: float
    tuning_applied: Dict[str, Dict]


class BackgroundValidator:
    """
    Every 30 seconds, each algorithm predicts "where will we be in 30s?"
    Then compares against actual GPS. Wrong predictions trigger auto-tuning.

    Like paper-trading before going live — test strategies with no risk.
    """

    def __init__(self, interval_s: float = 30.0):
        self.interval_s = interval_s
        self._pending_predictions: Dict[str, Tuple[float, float]] = {}
        self._prediction_time = 0.0
        self._validation_results: deque = deque(maxlen=200)
        self._cycle_count = 0
        self._agent_scores: Dict[str, List[float]] = {}
        self._last_position: Tuple[float, float] = (0, 0)

    def start_prediction_cycle(self, current_lat: float, current_lon: float,
                                agent_predictions: Dict[str, Tuple[float, float]]):
        """
        Start a new prediction cycle. Each agent predicts where we'll be
        in interval_s seconds.

        agent_predictions: {"kalman": (pred_lat, pred_lon), "particle": (...), ...}
        """
        self._pending_predictions = dict(agent_predictions)
        self._prediction_time = time.time()
        self._last_position = (current_lat, current_lon)

    def check_predictions(self, actual_lat: float, actual_lon: float) -> Optional[ValidationResult]:
        """
        After interval_s, compare predictions to actual GPS position.
        Returns validation result with per-agent errors and tuning suggestions.
        """
        if not self._pending_predictions:
            return None

        elapsed = time.time() - self._prediction_time
        if elapsed < self.interval_s * 0.8:
            return None  # Not enough time passed

        self._cycle_count += 1
        errors = {}
        tuning = {}

        for agent_name, (pred_lat, pred_lon) in self._pending_predictions.items():
            dlat = (pred_lat - actual_lat) * 111320
            dlon = (pred_lon - actual_lon) * 111320 * math.cos(math.radians(actual_lat))
            error_m = math.sqrt(dlat ** 2 + dlon ** 2)
            errors[agent_name] = round(error_m, 2)

            # Track per-agent performance
            if agent_name not in self._agent_scores:
                self._agent_scores[agent_name] = []
            self._agent_scores[agent_name].append(error_m)

            # Generate tuning suggestion based on error pattern
            scores = self._agent_scores[agent_name]
            if len(scores) >= 3:
                recent_avg = np.mean(scores[-3:])
                if recent_avg > 20:
                    tuning[agent_name] = {
                        "action": "increase_smoothing",
                        "reason": f"avg error {recent_avg:.1f}m over 3 cycles",
                        "suggested_alpha_change": -0.05,
                    }
                elif recent_avg < 5:
                    tuning[agent_name] = {
                        "action": "decrease_smoothing",
                        "reason": f"very accurate ({recent_avg:.1f}m), can be more responsive",
                        "suggested_alpha_change": +0.02,
                    }

        best_agent = min(errors, key=errors.get) if errors else "none"
        best_error = errors.get(best_agent, 999)

        result = ValidationResult(
            cycle=self._cycle_count,
            timestamp=time.time(),
            predictions=dict(self._pending_predictions),
            actual=(actual_lat, actual_lon),
            errors=errors,
            best_agent=best_agent,
            best_error_m=round(best_error, 2),
            tuning_applied=tuning,
        )

        self._validation_results.append(result)
        self._pending_predictions = {}

        return result

    def get_agent_rankings(self) -> List[Dict]:
        """Get agents ranked by average prediction error."""
        rankings = []
        for agent, scores in self._agent_scores.items():
            rankings.append({
                "agent": agent,
                "avg_error_m": round(float(np.mean(scores)), 2),
                "best_error_m": round(float(min(scores)), 2),
                "worst_error_m": round(float(max(scores)), 2),
                "cycles": len(scores),
            })
        rankings.sort(key=lambda r: r["avg_error_m"])
        return rankings

    def get_stats(self) -> Dict:
        return {
            "cycles_completed": self._cycle_count,
            "agents_tracked": len(self._agent_scores),
            "rankings": self.get_agent_rankings(),
        }


# ══════════════════════════════════════════════════════════════════
#  2. SENSOR AUTO-CALIBRATOR — learns YOUR phone's biases
# ══════════════════════════════════════════════════════════════════

class SensorAutoCalibrator:
    """
    Learns your specific phone's sensor biases by comparing sensor data
    to GPS ground truth over time.

    - Accelerometer bias: what it reads when stationary
    - Gyro drift: how much it drifts per second
    - Compass offset: difference between compass and GPS heading
    - Step length: your personal step length from GPS distance / step count

    These corrections are applied to all agents automatically.
    """

    def __init__(self):
        self.accel_bias = np.array([0.0, 0.0, 0.0])
        self.gyro_drift = np.array([0.0, 0.0, 0.0])
        self.compass_offset_deg = 0.0
        self.step_length_m = 0.73  # Default human average
        self.calibration_quality = 0.0

        self._static_accel_samples: List[np.ndarray] = []
        self._static_gyro_samples: List[np.ndarray] = []
        self._heading_pairs: List[Tuple[float, float]] = []  # (compass, gps_heading)
        self._step_distances: List[Tuple[int, float]] = []  # (steps, gps_distance_m)
        self._calibrated = False

    def feed_static_sample(self, accel: Tuple[float, float, float],
                           gyro: Tuple[float, float, float]):
        """Feed sensor data while device is stationary (for bias detection)."""
        self._static_accel_samples.append(np.array(accel))
        self._static_gyro_samples.append(np.array(gyro))

        if len(self._static_accel_samples) >= 20:
            self._calculate_biases()

    def feed_heading_pair(self, compass_heading: float, gps_heading: float):
        """Feed compass heading paired with GPS-derived heading."""
        self._heading_pairs.append((compass_heading, gps_heading))

        if len(self._heading_pairs) >= 10:
            offsets = [(gps - compass) % 360 for compass, gps in self._heading_pairs[-20:]]
            # Handle wrap-around (e.g., 350 vs 10 should give offset of 20, not 340)
            offsets_adj = []
            for o in offsets:
                if o > 180:
                    o -= 360
                offsets_adj.append(o)
            self.compass_offset_deg = float(np.mean(offsets_adj))

    def feed_step_distance(self, steps: int, gps_distance_m: float):
        """Feed step count paired with GPS-measured distance."""
        if steps > 0 and gps_distance_m > 1:
            self._step_distances.append((steps, gps_distance_m))
            if len(self._step_distances) >= 5:
                total_steps = sum(s for s, _ in self._step_distances[-10:])
                total_dist = sum(d for _, d in self._step_distances[-10:])
                if total_steps > 0:
                    self.step_length_m = total_dist / total_steps

    def _calculate_biases(self):
        """Calculate sensor biases from static samples."""
        accel_arr = np.array(self._static_accel_samples[-50:])
        gyro_arr = np.array(self._static_gyro_samples[-50:])

        # Accelerometer bias: mean reading minus gravity on z-axis
        self.accel_bias = np.mean(accel_arr, axis=0)
        self.accel_bias[2] -= 9.81  # Remove expected gravity

        # Gyro drift: mean reading (should be zero when stationary)
        self.gyro_drift = np.mean(gyro_arr, axis=0)

        self._calibrated = True
        self.calibration_quality = min(1.0, len(self._static_accel_samples) / 100.0)

    def correct_accel(self, raw: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Apply bias correction to accelerometer reading."""
        corrected = np.array(raw) - self.accel_bias
        return tuple(corrected)

    def correct_gyro(self, raw: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Apply drift correction to gyroscope reading."""
        corrected = np.array(raw) - self.gyro_drift
        return tuple(corrected)

    def correct_heading(self, compass_heading: float) -> float:
        """Apply offset correction to compass heading."""
        return (compass_heading + self.compass_offset_deg) % 360

    def get_calibration(self) -> Dict:
        return {
            "accel_bias": self.accel_bias.tolist(),
            "gyro_drift": self.gyro_drift.tolist(),
            "compass_offset_deg": round(self.compass_offset_deg, 2),
            "step_length_m": round(self.step_length_m, 3),
            "quality": round(self.calibration_quality, 2),
            "calibrated": self._calibrated,
            "accel_samples": len(self._static_accel_samples),
            "heading_pairs": len(self._heading_pairs),
            "step_samples": len(self._step_distances),
        }


# ══════════════════════════════════════════════════════════════════
#  3. FISH SCHOOL GRID SEARCH — 6 schools, different parameters
# ══════════════════════════════════════════════════════════════════

@dataclass
class FishSchoolConfig:
    name: str
    sma_window: int
    ema_alpha: float
    description: str
    error_history: List[float] = field(default_factory=list)
    weight: float = 1.0


class FishSchoolGridSearch:
    """
    6 fish schools, each running the same formula with different parameters.
    Like a parameter grid search — find the best settings for YOUR movement.

    Alpha: very fast/reactive
    Bravo: fast
    Charlie: balanced
    Delta: smooth
    Echo: very smooth
    Foxtrot: mutates toward the winner after each drill
    """

    def __init__(self):
        self.schools = [
            FishSchoolConfig("Alpha", 5, 0.30, "Very fast/reactive"),
            FishSchoolConfig("Bravo", 10, 0.20, "Fast"),
            FishSchoolConfig("Charlie", 20, 0.12, "Balanced"),
            FishSchoolConfig("Delta", 30, 0.06, "Smooth"),
            FishSchoolConfig("Echo", 40, 0.03, "Very smooth"),
            FishSchoolConfig("Foxtrot", 15, 0.15, "Adaptive — mutates toward winner"),
        ]
        self._winner_name = "Charlie"

    def predict_all(self, speeds: List[float], headings: List[float],
                    last_lat: float, last_lon: float,
                    blind_seconds: float) -> Dict[str, Tuple[float, float]]:
        """Run all 6 schools and return their predictions."""
        from upin.core.financial_indicator_nav import sma, ema

        predictions = {}
        for school in self.schools:
            try:
                speed = sma(speeds, school.sma_window) if len(speeds) >= school.sma_window else (
                    sum(speeds) / len(speeds) if speeds else 0)
                heading = ema(headings, school.ema_alpha) if headings else 0

                heading_rad = math.radians(heading)
                dist = speed * blind_seconds

                pred_lat = last_lat + dist * math.cos(heading_rad) / 111320
                pred_lon = last_lon + dist * math.sin(heading_rad) / (
                    111320 * math.cos(math.radians(last_lat)))

                predictions[school.name] = (pred_lat, pred_lon)
            except Exception:
                predictions[school.name] = (last_lat, last_lon)

        return predictions

    def score_all(self, predictions: Dict[str, Tuple[float, float]],
                  actual_lat: float, actual_lon: float):
        """Score all schools after GPS resurface."""
        for school in self.schools:
            pred = predictions.get(school.name)
            if pred:
                dlat = (pred[0] - actual_lat) * 111320
                dlon = (pred[1] - actual_lon) * 111320 * math.cos(math.radians(actual_lat))
                error = math.sqrt(dlat ** 2 + dlon ** 2)
                school.error_history.append(error)

        # Find winner
        scored = [(np.mean(s.error_history[-5:]) if s.error_history else 999, s)
                  for s in self.schools]
        scored.sort(key=lambda x: x[0])
        self._winner_name = scored[0][1].name

        # Update weights — best gets 2.0, worst gets 0.5
        for rank, (_, school) in enumerate(scored):
            school.weight = max(0.5, 2.0 - rank * 0.25)

        # Foxtrot mutates toward winner
        winner = scored[0][1]
        foxtrot = next(s for s in self.schools if s.name == "Foxtrot")
        foxtrot.sma_window = int(foxtrot.sma_window * 0.7 + winner.sma_window * 0.3)
        foxtrot.ema_alpha = foxtrot.ema_alpha * 0.7 + winner.ema_alpha * 0.3

    def get_best_prediction(self, predictions: Dict[str, Tuple[float, float]]) -> Tuple[float, float]:
        """Get weighted consensus from all schools."""
        total_w = 0.0
        w_lat = 0.0
        w_lon = 0.0
        for school in self.schools:
            pred = predictions.get(school.name)
            if pred:
                w_lat += pred[0] * school.weight
                w_lon += pred[1] * school.weight
                total_w += school.weight
        if total_w == 0:
            return (0, 0)
        return (w_lat / total_w, w_lon / total_w)

    def get_stats(self) -> List[Dict]:
        return [{
            "name": s.name,
            "sma_window": s.sma_window,
            "ema_alpha": round(s.ema_alpha, 3),
            "weight": round(s.weight, 2),
            "avg_error_m": round(float(np.mean(s.error_history[-5:])), 1) if s.error_history else None,
            "drills": len(s.error_history),
            "description": s.description,
            "is_winner": s.name == self._winner_name,
        } for s in self.schools]


# ══════════════════════════════════════════════════════════════════
#  4. USER PROFILE — saves learned parameters across sessions
# ══════════════════════════════════════════════════════════════════

class UserProfile:
    """
    Saves all learned parameters to disk so the system remembers
    your device's characteristics across sessions.
    """

    def __init__(self, profile_path: str = "upin_user_profile.json"):
        self.path = profile_path
        self.data: Dict[str, Any] = {
            "device_id": "",
            "sessions": 0,
            "accel_bias": [0, 0, 0],
            "gyro_drift": [0, 0, 0],
            "compass_offset": 0,
            "step_length": 0.73,
            "best_strategy": "Balanced",
            "fish_school_params": {},
            "agent_rankings": [],
            "total_training_minutes": 0,
            "last_session": 0,
        }
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    saved = json.load(f)
                self.data.update(saved)
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        self.data["last_session"] = time.time()
        self.data["sessions"] += 1
        try:
            with open(self.path, "w") as f:
                json.dump(self.data, f, indent=2)
        except IOError:
            pass

    def update_from_calibrator(self, cal: SensorAutoCalibrator):
        self.data["accel_bias"] = cal.accel_bias.tolist()
        self.data["gyro_drift"] = cal.gyro_drift.tolist()
        self.data["compass_offset"] = cal.compass_offset_deg
        self.data["step_length"] = cal.step_length_m

    def update_from_validator(self, val: BackgroundValidator):
        self.data["agent_rankings"] = val.get_agent_rankings()

    def update_from_fish_schools(self, fish: FishSchoolGridSearch):
        self.data["fish_school_params"] = {
            s.name: {"window": s.sma_window, "alpha": s.ema_alpha, "weight": s.weight}
            for s in fish.schools
        }

    def apply_to_calibrator(self, cal: SensorAutoCalibrator):
        cal.accel_bias = np.array(self.data.get("accel_bias", [0, 0, 0]))
        cal.gyro_drift = np.array(self.data.get("gyro_drift", [0, 0, 0]))
        cal.compass_offset_deg = self.data.get("compass_offset", 0)
        cal.step_length_m = self.data.get("step_length", 0.73)
        if any(cal.accel_bias != 0):
            cal._calibrated = True


# ══════════════════════════════════════════════════════════════════
#  5. CONTINUOUS LEARNING ENGINE — ties everything together
# ══════════════════════════════════════════════════════════════════

class ContinuousLearningEngine:
    """
    Master engine that runs background validation, sensor calibration,
    fish school grid search, and user profile management.

    Every GPS tick is a learning opportunity.
    The longer you use it, the better it gets.
    """

    def __init__(self, profile_path: str = "upin_user_profile.json"):
        self.validator = BackgroundValidator(interval_s=30.0)
        self.calibrator = SensorAutoCalibrator()
        self.fish_schools = FishSchoolGridSearch()
        self.profile = UserProfile(profile_path)

        # Apply saved profile
        self.profile.apply_to_calibrator(self.calibrator)

        self._tick_count = 0
        self._gps_ticks = 0
        self._blind_ticks = 0
        self._start_time = time.time()

    def gps_tick(self, lat: float, lon: float, speed: float, heading: float,
                 accel: Tuple[float, float, float] = (0, 0, 9.81),
                 gyro: Tuple[float, float, float] = (0, 0, 0),
                 compass: float = 0.0,
                 agent_predictions: Optional[Dict[str, Tuple[float, float]]] = None):
        """
        Called every GPS update. This is where all learning happens.

        Every single tick:
        - Feeds calibrator with sensor data
        - Checks pending predictions against reality
        - Starts new prediction cycle
        - Updates user profile periodically
        """
        self._tick_count += 1
        self._gps_ticks += 1

        # 1. Feed calibrator
        if speed < 0.3:  # Stationary — good for bias calibration
            self.calibrator.feed_static_sample(accel, gyro)
        self.calibrator.feed_heading_pair(compass, heading)

        # 2. Check pending predictions
        validation = self.validator.check_predictions(lat, lon)

        # 3. Start new prediction cycle (if agents provided predictions)
        if agent_predictions:
            self.validator.start_prediction_cycle(lat, lon, agent_predictions)

        # 4. Save profile every 60 ticks
        if self._tick_count % 60 == 0:
            self.profile.update_from_calibrator(self.calibrator)
            self.profile.update_from_validator(self.validator)
            self.profile.update_from_fish_schools(self.fish_schools)
            self.profile.data["total_training_minutes"] = round(
                (time.time() - self._start_time) / 60, 1)
            self.profile.save()

        return validation

    def get_corrected_sensors(self, accel: Tuple, gyro: Tuple,
                               compass: float) -> Dict:
        """Get bias-corrected sensor readings."""
        return {
            "accel": self.calibrator.correct_accel(accel),
            "gyro": self.calibrator.correct_gyro(gyro),
            "heading": self.calibrator.correct_heading(compass),
        }

    def get_dashboard(self) -> Dict:
        return {
            "tick_count": self._tick_count,
            "gps_ticks": self._gps_ticks,
            "training_minutes": round((time.time() - self._start_time) / 60, 1),
            "calibration": self.calibrator.get_calibration(),
            "validation": self.validator.get_stats(),
            "fish_schools": self.fish_schools.get_stats(),
            "profile_sessions": self.profile.data.get("sessions", 0),
        }
