"""
Realistic GPS Physics Engine — UPIN

Proper pseudorange-based GPS positioning with:
- Satellite orbit simulation
- Pseudorange calculation with atmospheric errors (iono + tropo)
- Clock drift accumulation
- Iterative least-squares trilateration solver
- Confidence scoring based on error/noise/drift
- CSV logging for mobile analysis

Based on Navigation Engine V11.
Integrates with existing UPIN fusion as a high-fidelity GPS source.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import csv
import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

C = 299792458.0  # Speed of light (m/s)
EARTH_RADIUS = 6371000.0  # metres
GPS_ORBIT_RADIUS = 26600000.0  # metres (MEO orbit)


# ── Error Models ──────────────────────────────────────────────────

def atmospheric_error() -> float:
    """
    Simulate ionospheric + tropospheric delay error on GPS signal.
    Ionosphere: ~2m RMS (can be 10-50m during storms)
    Troposphere: ~1m RMS (humidity/pressure dependent)
    """
    ionospheric = np.random.randn() * 2.0   # metres
    tropospheric = np.random.randn() * 1.0  # metres
    return ionospheric + tropospheric


def clock_drift(prev_bias: float) -> float:
    """
    Simulate receiver clock drift.
    Crystal oscillators drift ~1e-9 s per second.
    """
    return prev_bias + np.random.randn() * 1e-9


def multipath_error(urban_density: float = 0.5) -> float:
    """
    Multipath error from signal reflections.
    Higher in urban environments (0.0=rural, 1.0=dense urban).
    """
    return np.random.randn() * (1.0 + urban_density * 4.0)


# ── Confidence Scoring ────────────────────────────────────────────

def confidence_score(error_m: float, noise_m: float, drift_s: float) -> float:
    """
    Calculate navigation confidence from error, noise, and drift.
    Returns 0-100 score.

    Formula: 0.4*(1/error) + 0.3*(1/noise) + 0.3*(1/drift)
    Scaled to 0-100 range.
    """
    error_m = max(error_m, 1e-6)
    noise_m = max(noise_m, 1e-6)
    drift_s = max(drift_s, 1e-6)
    raw = 0.4 * (1.0 / error_m) + 0.3 * (1.0 / noise_m) + 0.3 * (1.0 / drift_s)
    return min(raw * 10.0, 100.0)


# ── Satellite Generation ─────────────────────────────────────────

def generate_satellites(n: int = 8, radius: float = GPS_ORBIT_RADIUS) -> List[np.ndarray]:
    """
    Generate n satellite positions on a sphere of given radius.
    Returns list of (3,1) position vectors in ECEF-like coordinates.
    """
    sats = []
    for _ in range(n):
        v = np.random.randn(3, 1)
        v /= np.linalg.norm(v)
        sats.append(radius * v)
    return sats


# ── Pseudorange Simulation ────────────────────────────────────────

def simulate_pseudoranges(
    true_pos: np.ndarray,
    satellites: List[np.ndarray],
    clock_bias: float,
    urban_density: float = 0.3,
) -> np.ndarray:
    """
    Calculate pseudoranges from true position to each satellite.
    Includes atmospheric error, clock bias, and multipath.
    """
    pseudoranges = []
    for sat in satellites:
        geometric_range = float(np.linalg.norm(true_pos - sat))
        atm_err = atmospheric_error()
        mp_err = multipath_error(urban_density)
        pr = geometric_range + C * clock_bias + atm_err + mp_err
        pseudoranges.append(pr)
    return np.array(pseudoranges).reshape(-1, 1)


# ── Trilateration Solver ─────────────────────────────────────────

def solve_position_from_pseudoranges(
    satellites: List[np.ndarray],
    pseudoranges: np.ndarray,
    initial_guess: Optional[np.ndarray] = None,
    max_iterations: int = 10,
) -> Tuple[np.ndarray, float]:
    """
    Iterative least-squares position solver from pseudoranges.
    Solves for [x, y, z, clock_bias] simultaneously.

    Returns (state_4x1, residual_rms).
    """
    if initial_guess is None:
        x = np.zeros((4, 1))
    else:
        x = initial_guess.copy()

    for iteration in range(max_iterations):
        H_rows = []
        y_rows = []

        for i, sat in enumerate(satellites):
            dx = x[0:3] - sat
            r = float(np.linalg.norm(dx))
            if r < 1.0:
                continue

            # Jacobian row: partial derivatives of pseudorange w.r.t. state
            h = np.zeros((1, 4))
            h[0, 0:3] = dx.flatten() / r
            h[0, 3] = C
            H_rows.append(h)

            # Predicted pseudorange
            predicted = r + C * x[3, 0]
            residual = pseudoranges[i, 0] - predicted
            y_rows.append(residual)

        if len(H_rows) < 4:
            break  # Need at least 4 satellites

        H = np.vstack(H_rows)
        y = np.array(y_rows).reshape(-1, 1)

        try:
            delta = np.linalg.inv(H.T @ H) @ H.T @ y
        except np.linalg.LinAlgError:
            break

        x += delta

        if np.linalg.norm(delta) < 1e-3:
            break

    residual_rms = float(np.sqrt(np.mean(y ** 2))) if len(y_rows) > 0 else 999.0
    return x, residual_rms


# ── Navigation EKF ────────────────────────────────────────────────

@dataclass
class NavigationState:
    """Complete navigation state with error tracking."""
    position: np.ndarray = field(default_factory=lambda: np.zeros((3, 1)))
    velocity: np.ndarray = field(default_factory=lambda: np.zeros((3, 1)))
    clock_bias: float = 1e-6
    error_m: float = 0.0
    confidence: float = 0.0
    atmospheric_noise_m: float = 3.0
    step: int = 0


class RealisticNavigationEKF:
    """
    EKF with realistic GPS physics: pseudoranges, atmospheric errors,
    clock drift, and proper confidence scoring.
    """

    def __init__(self, num_satellites: int = 8):
        self.satellites = generate_satellites(num_satellites)
        self.state = NavigationState()
        self.true_position = np.zeros((3, 1))
        self.true_velocity = np.array([[5.0], [1.0], [0.0]])  # m/s
        self._log: List[Dict] = []
        self._alpha = 0.2  # EKF update gain

    def step(self) -> Dict:
        """Run one navigation step: predict + GPS update."""
        self.state.step += 1

        # True position update
        self.true_position = self.true_position + self.true_velocity

        # Clock drift
        self.state.clock_bias = clock_drift(self.state.clock_bias)

        # Generate pseudoranges from true position
        pseudoranges = simulate_pseudoranges(
            self.true_position, self.satellites, self.state.clock_bias
        )

        # Solve position from pseudoranges
        initial = np.vstack((self.state.position, [[self.state.clock_bias]]))
        solution, residual = solve_position_from_pseudoranges(
            self.satellites, pseudoranges, initial
        )
        gps_position = solution[0:3]

        # EKF predict
        self.state.position = self.state.position + self.state.velocity

        # EKF update (weighted blend of prediction and GPS)
        self.state.position = (1 - self._alpha) * self.state.position + self._alpha * gps_position

        # Calculate error
        self.state.error_m = float(np.linalg.norm(self.state.position - self.true_position))

        # Confidence scoring
        self.state.confidence = confidence_score(
            self.state.error_m,
            self.state.atmospheric_noise_m,
            abs(self.state.clock_bias),
        )

        # Log entry
        entry = {
            "step": self.state.step,
            "true_x": float(self.true_position[0, 0]),
            "true_y": float(self.true_position[1, 0]),
            "true_z": float(self.true_position[2, 0]),
            "est_x": float(self.state.position[0, 0]),
            "est_y": float(self.state.position[1, 0]),
            "est_z": float(self.state.position[2, 0]),
            "error_m": round(self.state.error_m, 3),
            "confidence": round(self.state.confidence, 2),
            "clock_bias_ns": round(self.state.clock_bias * 1e9, 3),
            "residual_rms": round(residual, 3),
        }
        self._log.append(entry)

        return entry

    def run(self, steps: int = 200) -> List[Dict]:
        """Run full navigation simulation."""
        for _ in range(steps):
            self.step()
        return self._log

    def save_csv(self, filepath: str = "nav_log.csv"):
        """Save navigation log as CSV for mobile analysis."""
        if not self._log:
            return
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._log[0].keys())
            writer.writeheader()
            writer.writerows(self._log)

    def get_summary(self) -> Dict:
        """Get navigation performance summary."""
        if not self._log:
            return {}
        errors = [e["error_m"] for e in self._log]
        confs = [e["confidence"] for e in self._log]
        return {
            "total_steps": len(self._log),
            "final_error_m": round(errors[-1], 2),
            "mean_error_m": round(float(np.mean(errors)), 2),
            "max_error_m": round(float(np.max(errors)), 2),
            "final_confidence": round(confs[-1], 2),
            "mean_confidence": round(float(np.mean(confs)), 2),
            "satellites": len(self.satellites),
            "clock_drift_ns": round(self.state.clock_bias * 1e9, 3),
        }

    def get_current_position_for_upin(self) -> Dict:
        """Get current position in UPIN-compatible format."""
        # Convert ECEF-like coords back to lat/lon (simplified)
        x, y, z = self.state.position.flatten()
        r = math.sqrt(x**2 + y**2 + z**2)

        if r < 1:
            return {"lat": 0.0, "lon": 0.0, "alt": 0.0, "confidence": 0.0}

        lat = math.degrees(math.asin(z / r))
        lon = math.degrees(math.atan2(y, x))

        return {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "alt": round(r - EARTH_RADIUS, 1),
            "accuracy_m": round(self.state.error_m, 1),
            "confidence": round(self.state.confidence / 100.0, 3),
            "clock_bias_ns": round(self.state.clock_bias * 1e9, 3),
            "source": "pseudorange_trilateration",
        }
