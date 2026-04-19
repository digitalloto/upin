"""
Position Uncertainty Envelope (PUE) + Smart Constraint Engine — UPIN

Ported from UPIN phone-demo v5. Physics-based constraint that limits
how far a platform COULD have travelled given known speed/time, then
SHRINKS the envelope using sensor evidence (ZUPT, cell tower bounds,
speed-decay inference).

PUE (grows with time): max radius = speed * time + 0.5 * accel_max * t^2
Smart Constraint (shrinks): final_radius = MIN(physics_max, speed_decay,
                                               zupt_frozen, cell_bound)

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple, List


@dataclass
class PUEState:
    """Current state of the Position Uncertainty Envelope."""
    center_lat: float
    center_lon: float
    radius_m: float
    last_gps_time: float
    last_known_speed_ms: float = 0.0
    physics_max_m: float = 0.0
    speed_decay_m: float = 0.0
    zupt_frozen: bool = False
    zupt_frozen_radius_m: float = 0.0
    cell_bound_m: float = 0.0
    constraint_winner: str = "physics_max"


class PositionUncertaintyEnvelope:
    """PUE — limits how far the platform could have moved since last GPS fix.

    Physics model:
        max_distance = v0 * t + 0.5 * a_max * t^2
    where v0 is last known speed and a_max is platform max acceleration.
    """

    def __init__(self, max_accel_ms2: float = 5.0, max_speed_ms: float = 50.0):
        self._max_accel = max_accel_ms2  # m/s^2 (typical vehicle)
        self._max_speed = max_speed_ms   # m/s absolute limit
        self._state: Optional[PUEState] = None

    def set_known_fix(self, lat: float, lon: float, speed_ms: float = 0.0):
        """Set a known-good position (from GPS) as PUE anchor."""
        self._state = PUEState(
            center_lat=lat,
            center_lon=lon,
            radius_m=0.0,
            last_gps_time=time.time(),
            last_known_speed_ms=speed_ms,
        )

    def get_max_radius(self, current_time: Optional[float] = None) -> float:
        """Physics-only max radius (grows with time since last fix)."""
        if self._state is None:
            return float('inf')
        now = current_time if current_time is not None else time.time()
        dt = now - self._state.last_gps_time
        v0 = min(self._state.last_known_speed_ms, self._max_speed)
        # Physics: max distance = v0 * t + 0.5 * a * t^2, capped at v_max * t
        physics = v0 * dt + 0.5 * self._max_accel * dt * dt
        capped = self._max_speed * dt
        return min(physics, capped)

    def is_position_feasible(self, lat: float, lon: float) -> bool:
        """Check if a candidate position is within the PUE envelope."""
        if self._state is None:
            return True
        dist = self._haversine_m(
            self._state.center_lat, self._state.center_lon, lat, lon,
        )
        return dist <= self.get_max_radius()

    def get_state(self) -> Optional[PUEState]:
        return self._state

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2) -> float:
        R = 6_371_000.0
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class SmartConstraintEngine:
    """Smart Constraint Engine — 4 layers that SHRINK the search radius.

    final_radius = MIN(
        physics_max,          # PUE upper bound
        speed_decay_estimate, # from accel energy
        zupt_frozen_radius,   # if stopped, freeze radius
        cell_tower_bound,     # independent cell triangulation
    )

    This is tighter than PUE alone because it uses sensor evidence
    (deceleration, stop detection, cell tower accuracy) to eliminate
    impossible positions.
    """

    def __init__(self, pue: PositionUncertaintyEnvelope):
        self.pue = pue
        self._accel_energy_history: List[float] = []
        self._stop_start_time: Optional[float] = None
        self._is_stopped = False
        self._frozen_radius_m: Optional[float] = None
        self._stop_detection_threshold = 0.3  # m/s^2 accel magnitude
        self._stop_duration_required_s = 3.0

    def update_sensors(self, accel_magnitude_ms2: float,
                       cell_accuracy_m: Optional[float] = None) -> dict:
        """Update constraint state from latest sensor readings.

        accel_magnitude_ms2: |accel| with gravity removed (low = still)
        cell_accuracy_m: accuracy from cell triangulation (optional)
        """
        now = time.time()
        self._accel_energy_history.append(accel_magnitude_ms2)
        if len(self._accel_energy_history) > 50:
            self._accel_energy_history = self._accel_energy_history[-50:]

        recent_energy = (sum(self._accel_energy_history[-15:])
                         / max(1, len(self._accel_energy_history[-15:])))

        was_stopped = self._is_stopped
        if recent_energy < self._stop_detection_threshold:
            if self._stop_start_time is None:
                self._stop_start_time = now
            elif (now - self._stop_start_time) >= self._stop_duration_required_s:
                if not self._is_stopped:
                    self._is_stopped = True
                    state = self.pue.get_state()
                    if state is not None:
                        self._frozen_radius_m = self.pue.get_max_radius()
        else:
            self._stop_start_time = None
            if self._is_stopped:
                self._is_stopped = False
                self._frozen_radius_m = None

        physics_max = self.pue.get_max_radius()
        speed_decay = self._estimate_speed_decay_radius(recent_energy)
        zupt_bound = (self._frozen_radius_m if self._is_stopped
                      and self._frozen_radius_m is not None else float('inf'))
        cell_bound = (cell_accuracy_m * 2.0) if cell_accuracy_m else float('inf')

        candidates = {
            "physics_max": physics_max,
            "speed_decay": speed_decay,
            "zupt_frozen": zupt_bound,
            "cell_bound": cell_bound,
        }
        winner = min(candidates, key=candidates.get)
        final_radius = candidates[winner]

        state = self.pue.get_state()
        if state is not None:
            state.physics_max_m = physics_max
            state.speed_decay_m = speed_decay
            state.zupt_frozen = self._is_stopped
            state.zupt_frozen_radius_m = (self._frozen_radius_m or 0.0)
            state.cell_bound_m = cell_bound if cell_bound != float('inf') else 0.0
            state.radius_m = final_radius
            state.constraint_winner = winner

        return {
            "final_radius_m": final_radius,
            "winner": winner,
            "physics_max_m": physics_max,
            "speed_decay_m": speed_decay,
            "zupt_frozen": self._is_stopped,
            "cell_bound_m": cell_bound if cell_bound != float('inf') else None,
            "accel_energy": recent_energy,
            "just_stopped": self._is_stopped and not was_stopped,
        }

    def _estimate_speed_decay_radius(self, recent_energy: float) -> float:
        """Estimate tighter radius based on inferred speed from accel energy.

        If accel energy is very low, platform must be slow/stopped,
        so radius grows slower than physics_max allows.
        """
        state = self.pue.get_state()
        if state is None:
            return float('inf')
        now = time.time()
        dt = now - state.last_gps_time
        v0 = state.last_known_speed_ms
        # Inferred current speed — if energy is low, speed has decayed
        energy_ratio = min(1.0, recent_energy / 2.0)
        inferred_v = v0 * energy_ratio
        # Conservative estimate: average of v0 and inferred_v
        avg_speed = (v0 + inferred_v) / 2.0
        return avg_speed * dt

    def is_stopped(self) -> bool:
        return self._is_stopped

    def get_frozen_radius(self) -> Optional[float]:
        return self._frozen_radius_m
