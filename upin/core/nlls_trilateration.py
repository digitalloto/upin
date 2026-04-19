"""
Non-linear Least Squares Cell Tower Trilateration — UPIN

Ported from UPIN phone-demo v5. Upgrades weighted-centroid trilateration
to full Gauss-Newton non-linear least squares. Given N towers with known
positions and measured distances, iteratively refines (lat, lon) to
minimize squared residuals. Typically converges in 3-5 iterations.

Inputs: list of (tower_lat, tower_lon, measured_distance_m).
Output: best-fit (lat, lon) + accuracy estimate from residual RMS.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np


class NLLSTrilateration:
    """Gauss-Newton NLLS for multi-tower position estimation."""

    def __init__(self, max_iterations: int = 5,
                 convergence_threshold_m: float = 0.5):
        self._max_iters = max_iterations
        self._threshold_m = convergence_threshold_m

    def solve(self, observations: List[Tuple[float, float, float]],
              initial_guess: Optional[Tuple[float, float]] = None
              ) -> Optional[dict]:
        """observations: list of (tower_lat, tower_lon, measured_distance_m).

        Returns dict with keys: lat, lon, accuracy_m, iterations, residual_rms_m.
        """
        if len(observations) < 3:
            return None

        if initial_guess is None:
            lat = sum(o[0] for o in observations) / len(observations)
            lon = sum(o[1] for o in observations) / len(observations)
        else:
            lat, lon = initial_guess

        meters_per_deg_lat = 111_320.0

        residual_rms = 0.0
        iterations = 0
        for iteration in range(self._max_iters):
            meters_per_deg_lon = 111_320.0 * max(
                math.cos(math.radians(lat)), 0.01)
            residuals = []
            jacobian = []
            for tower_lat, tower_lon, meas_d in observations:
                dy = (lat - tower_lat) * meters_per_deg_lat
                dx = (lon - tower_lon) * meters_per_deg_lon
                pred_d = math.sqrt(dx * dx + dy * dy)
                if pred_d < 1e-3:
                    pred_d = 1e-3
                residuals.append(meas_d - pred_d)
                # Partial derivatives
                dpred_dlat = -dy / pred_d * meters_per_deg_lat
                dpred_dlon = -dx / pred_d * meters_per_deg_lon
                jacobian.append([dpred_dlat, dpred_dlon])

            r = np.array(residuals)
            J = np.array(jacobian)
            # Solve (J^T J) Δ = J^T r
            try:
                JT_J = J.T @ J
                JT_r = J.T @ r
                delta = np.linalg.solve(JT_J, JT_r)
            except np.linalg.LinAlgError:
                break

            # r = measured - predicted, J = ∂r/∂x = -∂pred/∂x
            # Gauss-Newton step: x_new = x_old - (JᵀJ)⁻¹ Jᵀr
            lat -= float(delta[0])
            lon -= float(delta[1])
            step_m = math.sqrt(
                (delta[0] * meters_per_deg_lat) ** 2
                + (delta[1] * meters_per_deg_lon) ** 2
            )
            residual_rms = float(np.sqrt(np.mean(r * r)))
            iterations = iteration + 1
            if step_m < self._threshold_m:
                break

        return {
            "lat": lat,
            "lon": lon,
            "accuracy_m": max(5.0, residual_rms),
            "residual_rms_m": residual_rms,
            "iterations": iterations,
            "towers_used": len(observations),
        }
