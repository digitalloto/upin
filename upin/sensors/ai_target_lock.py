"""
UPIN AI Target Lock Module.
Multi-sensor fusion lock-on, predictive tracking,
human authorisation gate, multi-target management.
NO autonomous engagement — human authorises every action.
"""
from __future__ import annotations
import time
import uuid
import math
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import numpy as np


class LockStatus(Enum):
    NO_LOCK    = "no_lock"
    ACQUIRING  = "acquiring"
    SOFT_LOCK  = "soft_lock"
    HARD_LOCK  = "hard_lock"
    LOCK_LOST  = "lock_lost"
    HUMAN_HOLD = "human_hold"


class SensorInput(Enum):
    VISUAL   = "visual"
    THERMAL  = "thermal"
    RADAR    = "radar"
    GPS      = "gps"
    ACOUSTIC = "acoustic"
    LASER    = "laser"


@dataclass
class TargetState:
    target_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    position_geo: tuple = (0.0, 0.0, 0.0)
    velocity_mps: float = 0.0
    heading_deg: float = 0.0
    lock_status: LockStatus = LockStatus.NO_LOCK
    lock_confidence: float = 0.0
    sensor_inputs: list = field(default_factory=list)
    predicted_position_5s: Optional[tuple] = None
    predicted_position_10s: Optional[tuple] = None
    first_acquired: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    priority_score: float = 0.0
    human_authorised: bool = False
    classification: str = "unknown"
    track_history: list = field(default_factory=list)

    def age_seconds(self) -> float:
        return time.time() - self.first_acquired

    def staleness_seconds(self) -> float:
        return time.time() - self.last_updated

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "position_geo": self.position_geo,
            "velocity_mps": round(self.velocity_mps, 2),
            "heading_deg": round(self.heading_deg, 1),
            "lock_status": self.lock_status.value,
            "lock_confidence": round(self.lock_confidence, 3),
            "sensor_count": len(self.sensor_inputs),
            "sensors": [s.value for s in self.sensor_inputs],
            "predicted_5s": self.predicted_position_5s,
            "predicted_10s": self.predicted_position_10s,
            "age_s": round(self.age_seconds(), 1),
            "stale_s": round(self.staleness_seconds(), 1),
            "priority": round(self.priority_score, 3),
            "human_authorised": self.human_authorised,
            "classification": self.classification,
        }


class TargetLock:
    """
    Multi-sensor fusion target lock.
    More sensors confirming = higher confidence.
    Same principle as UPIN 60-layer fusion — consensus = truth.
    HARD RULE: No engagement without human_authorised = True.
    """

    HARD_LOCK_MIN_SENSORS    = 3
    HARD_LOCK_MIN_CONFIDENCE = 0.80
    SOFT_LOCK_MIN_CONFIDENCE = 0.50

    SENSOR_WEIGHTS = {
        SensorInput.VISUAL:   0.25,
        SensorInput.THERMAL:  0.25,
        SensorInput.RADAR:    0.20,
        SensorInput.GPS:      0.15,
        SensorInput.ACOUSTIC: 0.10,
        SensorInput.LASER:    0.05,
    }

    def __init__(self):
        self._current_target: Optional[TargetState] = None
        self._sensor_readings: dict = {}
        self._lock_history: list = []

    def acquire(self, position_geo: tuple,
                classification: str = "unknown") -> TargetState:
        self._current_target = TargetState(
            position_geo=position_geo,
            lock_status=LockStatus.ACQUIRING,
            classification=classification,
        )
        self._sensor_readings = {}
        return self._current_target

    def update_sensor(self, sensor: SensorInput,
                      position_geo: tuple,
                      confidence: float,
                      velocity_mps: float = 0.0) -> dict:
        if not self._current_target:
            return {"error": "No active acquisition"}

        self._sensor_readings[sensor] = {
            "position": position_geo,
            "confidence": confidence,
            "velocity_mps": velocity_mps,
            "timestamp": time.time(),
        }

        fused = self._fuse_sensor_positions()
        if fused:
            self._current_target.position_geo = fused["position"]
            self._current_target.velocity_mps = fused["velocity"]

        self._current_target.sensor_inputs = list(self._sensor_readings.keys())
        self._recalculate_confidence()
        self._update_predictions()
        self._current_target.last_updated = time.time()
        return self._current_target.to_dict()

    def get_lock_status(self) -> Optional[TargetState]:
        return self._current_target

    def drop_lock(self) -> dict:
        if self._current_target:
            self._lock_history.append({
                "target_id": self._current_target.target_id,
                "lock_duration_s": self._current_target.age_seconds(),
                "final_status": self._current_target.lock_status.value,
                "dropped_at": time.time(),
            })
            self._current_target = None
        return {"status": "lock_dropped"}

    def _fuse_sensor_positions(self) -> Optional[dict]:
        if not self._sensor_readings:
            return None

        total_w = fused_lat = fused_lon = fused_alt = fused_vel = 0.0

        for sensor, reading in self._sensor_readings.items():
            w = self.SENSOR_WEIGHTS.get(sensor, 0.1) * reading["confidence"]
            pos = reading["position"]
            fused_lat += pos[0] * w
            fused_lon += pos[1] * w
            fused_alt += (pos[2] if len(pos) > 2 else 0.0) * w
            fused_vel += reading["velocity_mps"] * w
            total_w += w

        if total_w == 0:
            return None

        return {
            "position": (fused_lat/total_w, fused_lon/total_w, fused_alt/total_w),
            "velocity": fused_vel / total_w,
        }

    def _recalculate_confidence(self):
        if not self._current_target:
            return

        n = len(self._sensor_readings)
        if n == 0:
            self._current_target.lock_confidence = 0.0
            self._current_target.lock_status = LockStatus.NO_LOCK
            return

        total_w = total_conf = 0.0
        for sensor, reading in self._sensor_readings.items():
            w = self.SENSOR_WEIGHTS.get(sensor, 0.1)
            total_conf += reading["confidence"] * w
            total_w += w

        raw = total_conf / total_w if total_w > 0 else 0.0
        final = min(1.0, raw + min(0.20, (n - 1) * 0.05))
        self._current_target.lock_confidence = final

        if final >= self.HARD_LOCK_MIN_CONFIDENCE and n >= self.HARD_LOCK_MIN_SENSORS:
            self._current_target.lock_status = LockStatus.HARD_LOCK
        elif final >= self.SOFT_LOCK_MIN_CONFIDENCE:
            self._current_target.lock_status = LockStatus.SOFT_LOCK
        else:
            self._current_target.lock_status = LockStatus.ACQUIRING

    def _update_predictions(self):
        if not self._current_target:
            return

        pos = self._current_target.position_geo
        vel = self._current_target.velocity_mps
        hdg = self._current_target.heading_deg
        deg = 1.0 / 111_000

        def predict(s):
            d = vel * s
            return (pos[0] + d * math.cos(math.radians(hdg)) * deg,
                    pos[1] + d * math.sin(math.radians(hdg)) * deg,
                    pos[2])

        self._current_target.predicted_position_5s  = predict(5.0)
        self._current_target.predicted_position_10s = predict(10.0)


class PredictiveTracker:
    """Predicts target position 5-15 seconds ahead using velocity history."""

    def __init__(self, history_seconds: float = 30.0):
        self.history_seconds = history_seconds
        self._history: list = []

    def add_observation(self, position_geo: tuple, timestamp: float = None):
        self._history.append({
            "position": position_geo,
            "timestamp": timestamp or time.time(),
        })
        cutoff = time.time() - self.history_seconds
        self._history = [h for h in self._history if h["timestamp"] >= cutoff]

    def predict(self, seconds_ahead: float = 5.0) -> dict:
        if len(self._history) < 2:
            return {"predicted_position": None, "confidence": 0.0,
                    "method": "insufficient_data"}

        recent = self._history[-min(5, len(self._history)):]
        dt = recent[-1]["timestamp"] - recent[0]["timestamp"]
        if dt <= 0:
            return {"predicted_position": None, "confidence": 0.0,
                    "method": "zero_dt"}

        dlat = recent[-1]["position"][0] - recent[0]["position"][0]
        dlon = recent[-1]["position"][1] - recent[0]["position"][1]
        last = recent[-1]["position"]

        pred = (last[0] + (dlat/dt) * seconds_ahead,
                last[1] + (dlon/dt) * seconds_ahead,
                last[2] if len(last) > 2 else 0.0)

        speed = math.sqrt((dlat/dt * 111_000)**2 + (dlon/dt * 111_000)**2)

        return {
            "predicted_position": pred,
            "confidence": round(max(0.1, 1.0 - seconds_ahead / 60.0), 3),
            "speed_mps": round(speed, 2),
            "seconds_ahead": seconds_ahead,
            "method": "linear_extrapolation",
        }


class EngagementAuthoriser:
    """
    Human authorisation gate. NO autonomous engagement ever.
    Every action requires explicit human sign-off. Full audit trail.
    """

    def __init__(self, operator_id: str = ""):
        self.operator_id = operator_id or "UNKNOWN_OPERATOR"
        self._auth_log: list = []
        self._pending: dict = {}

    def request_engagement_auth(self, target: TargetState,
                                 engagement_type: str = "observe") -> dict:
        req_id = str(uuid.uuid4())[:8]
        req = {
            "request_id": req_id,
            "target_id": target.target_id,
            "target_position": target.position_geo,
            "classification": target.classification,
            "lock_status": target.lock_status.value,
            "lock_confidence": target.lock_confidence,
            "engagement_type": engagement_type,
            "status": "PENDING_HUMAN_AUTHORISATION",
            "submitted_at": time.time(),
            "operator": self.operator_id,
        }
        self._pending[req_id] = req
        return req

    def authorise(self, request_id: str, officer: str, auth_code: str) -> dict:
        if request_id not in self._pending:
            return {"error": f"Request {request_id} not found"}
        req = self._pending.pop(request_id)
        req.update({"status": "AUTHORISED", "authorised_by": officer,
                    "auth_code": auth_code, "authorised_at": time.time()})
        self._auth_log.append(dict(req))
        return req

    def deny(self, request_id: str, reason: str = "") -> dict:
        if request_id not in self._pending:
            return {"error": f"Request {request_id} not found"}
        req = self._pending.pop(request_id)
        req.update({"status": "DENIED", "denial_reason": reason,
                    "denied_at": time.time()})
        self._auth_log.append(dict(req))
        return req

    def get_pending_count(self) -> int:
        return len(self._pending)

    def get_audit_log(self) -> list:
        return list(self._auth_log)


class MultiTargetManager:
    """Manages up to 20 simultaneous target tracks with priority ranking."""

    MAX_TARGETS = 20

    def __init__(self):
        self._targets: dict = {}
        self._trackers: dict = {}
        self._total_tracked = 0

    def add_target(self, position_geo: tuple,
                   classification: str = "unknown",
                   priority_score: float = 0.5) -> Optional[TargetState]:
        if len(self._targets) >= self.MAX_TARGETS:
            self._drop_lowest_priority()

        lock = TargetLock()
        state = lock.acquire(position_geo, classification)
        state.priority_score = priority_score
        self._targets[state.target_id] = state
        self._trackers[state.target_id] = PredictiveTracker()
        self._trackers[state.target_id].add_observation(position_geo)
        self._total_tracked += 1
        return state

    def update_target(self, target_id: str, position_geo: tuple,
                      sensor: SensorInput = SensorInput.VISUAL,
                      confidence: float = 0.7) -> Optional[dict]:
        if target_id not in self._targets:
            return None

        target = self._targets[target_id]
        tracker = self._trackers[target_id]
        tracker.add_observation(position_geo)

        target.position_geo = position_geo
        target.last_updated = time.time()
        if sensor not in target.sensor_inputs:
            target.sensor_inputs.append(sensor)

        target.predicted_position_5s  = tracker.predict(5.0).get("predicted_position")
        target.predicted_position_10s = tracker.predict(10.0).get("predicted_position")

        return target.to_dict()

    def remove_target(self, target_id: str) -> bool:
        if target_id in self._targets:
            del self._targets[target_id]
            del self._trackers[target_id]
            return True
        return False

    def get_priority_ranked(self) -> list:
        targets = sorted(self._targets.values(),
                         key=lambda t: t.priority_score, reverse=True)
        return [t.to_dict() for t in targets]

    def get_hard_locked(self) -> list:
        return [t.to_dict() for t in self._targets.values()
                if t.lock_status == LockStatus.HARD_LOCK]

    def purge_stale(self, max_stale_s: float = 60.0):
        stale = [tid for tid, t in self._targets.items()
                 if t.staleness_seconds() > max_stale_s]
        for tid in stale:
            self.remove_target(tid)

    def get_summary(self) -> dict:
        lock_counts = {s.value: 0 for s in LockStatus}
        for t in self._targets.values():
            lock_counts[t.lock_status.value] += 1
        return {
            "active_targets": len(self._targets),
            "max_targets": self.MAX_TARGETS,
            "total_ever_tracked": self._total_tracked,
            "lock_status_breakdown": lock_counts,
            "hard_locked": lock_counts.get(LockStatus.HARD_LOCK.value, 0),
            "human_authorised": sum(
                1 for t in self._targets.values() if t.human_authorised),
        }

    def _drop_lowest_priority(self):
        if not self._targets:
            return
        lowest = min(self._targets.values(), key=lambda t: t.priority_score)
        self.remove_target(lowest.target_id)
