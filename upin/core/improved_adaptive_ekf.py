"""
Improved Adaptive Extended Kalman Filter (IAEKF) for UPIN

Dynamically adapts noise covariance matrices based on environmental
conditions and sensor reliability. Based on 2024 research showing
significant noise reduction and improved state estimation accuracy.

Uses PyTorch when available, numpy-only fallback otherwise.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


class FilterState(Enum):
    INITIALIZATION = "initialization"
    STABLE = "stable"
    ADAPTATION = "adaptation"
    DEGRADED = "degraded"
    RECOVERY = "recovery"


@dataclass
class SensorHealthMetrics:
    sensor_id: str
    availability: bool = True
    signal_strength: float = 1.0
    noise_level: float = 0.1
    drift_rate: float = 0.0
    reliability_score: float = 1.0


@dataclass
class IAEKFEnvironment:
    temperature: float = 20.0
    humidity: float = 50.0
    magnetic_declination: float = 0.0
    atmospheric_pressure: float = 1013.25
    urban_density: str = "medium"
    weather_condition: str = "clear"
    electromagnetic_noise: float = 0.1
    multipath_severity: float = 0.2


# ── Numpy-only adaptive noise estimator ───────────────────────────

def _relu(x):
    return np.maximum(0, x)

def _softplus(x):
    return np.log1p(np.exp(np.clip(x, -20, 20)))

def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))


class _NumpyNoiseNet:
    """Lightweight adaptive noise estimator (numpy only)."""

    def __init__(self, input_dim=20, hidden=32):
        s = 0.1
        self.w1 = np.random.randn(input_dim, hidden).astype(np.float32) * s
        self.b1 = np.zeros(hidden, dtype=np.float32)
        self.w2 = np.random.randn(hidden, hidden).astype(np.float32) * s
        self.b2 = np.zeros(hidden, dtype=np.float32)
        # Measurement noise head (3 values)
        self.wm = np.random.randn(hidden, 3).astype(np.float32) * s
        self.bm = np.ones(3, dtype=np.float32)
        # Process noise head (9 values)
        self.wp = np.random.randn(hidden, 9).astype(np.float32) * s
        self.bp = np.ones(9, dtype=np.float32) * 0.01
        # Adaptation gains (3 values)
        self.wa = np.random.randn(hidden, 3).astype(np.float32) * s
        self.ba = np.zeros(3, dtype=np.float32)

    def forward(self, x):
        h = _relu(x @ self.w1 + self.b1)
        h = _relu(h @ self.w2 + self.b2)
        m = _softplus(h @ self.wm + self.bm)
        p = _softplus(h @ self.wp + self.bp)
        a = _sigmoid(h @ self.wa + self.ba)
        return m, p, a


# ── Torch adaptive noise network ─────────────────────────────────

if HAS_TORCH:
    class _TorchNoiseNet(nn.Module):
        def __init__(self, input_dim=20, hidden=64):
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(input_dim, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
            )
            self.meas = nn.Sequential(nn.Linear(hidden // 2, 3), nn.Softplus())
            self.proc = nn.Sequential(nn.Linear(hidden // 2, 9), nn.Softplus())
            self.gain = nn.Sequential(nn.Linear(hidden // 2, 3), nn.Sigmoid())

        def forward(self, x):
            h = self.shared(x)
            return self.meas(h), self.proc(h), self.gain(h)


# ── IAEKF ─────────────────────────────────────────────────────────

class ImprovedAdaptiveEKF:
    """
    Improved Adaptive Extended Kalman Filter with neural-network-based
    noise adaptation and environmental awareness.

    State vector: [lat, lon, alt, v_lat, v_lon, v_alt, a_lat, a_lon, a_alt]
    """

    STATE_DIM = 9
    MEAS_DIM = 3

    def __init__(self, initial_position: Tuple[float, float] = (0.0, 0.0)):
        self.using_torch = HAS_TORCH

        # State
        self.state = np.zeros(self.STATE_DIM, dtype=np.float64)
        self.state[0] = initial_position[0]
        self.state[1] = initial_position[1]

        # Covariance
        self.P = np.eye(self.STATE_DIM) * 100.0

        # Base noise matrices
        self.Q_base = np.eye(self.STATE_DIM) * 0.01
        self.R_base = np.eye(self.MEAS_DIM) * 1.0
        self.Q = self.Q_base.copy()
        self.R = self.R_base.copy()

        # Measurement matrix (direct position observation)
        self.H = np.zeros((self.MEAS_DIM, self.STATE_DIM))
        self.H[0, 0] = self.H[1, 1] = self.H[2, 2] = 1.0

        self.dt = 1.0

        # Neural noise network
        if HAS_TORCH:
            self.device = torch.device("cpu")
            self.noise_net = _TorchNoiseNet().to(self.device)
        else:
            self.noise_net = _NumpyNoiseNet()

        # Tracking
        self.filter_state = FilterState.INITIALIZATION
        self.adaptation_enabled = True
        self.network_trained = False
        self.innovation_history: deque = deque(maxlen=50)
        self.adaptation_history: deque = deque(maxlen=100)
        self.sensor_health: Dict[str, SensorHealthMetrics] = {}
        self.environment = IAEKFEnvironment()

        # Thresholds
        self.innovation_threshold = 3.0
        self.adaptation_rate = 0.1

    # ── State transition ──────────────────────────────────────────

    def _F(self, dt: float) -> np.ndarray:
        F = np.eye(self.STATE_DIM)
        F[0, 3] = dt;  F[1, 4] = dt;  F[2, 5] = dt
        F[0, 6] = 0.5*dt*dt; F[1, 7] = 0.5*dt*dt; F[2, 8] = 0.5*dt*dt
        F[3, 6] = dt;  F[4, 7] = dt;  F[5, 8] = dt
        return F

    # ── Predict ───────────────────────────────────────────────────

    def predict(self, dt: float = 1.0, control: Optional[np.ndarray] = None) -> Dict:
        self.dt = dt
        F = self._F(dt)
        self.state = F @ self.state
        if control is not None:
            self.state += control
        self.P = F @ self.P @ F.T + self.Q
        self._update_filter_state()
        return {"state": self.state.copy(), "filter_state": self.filter_state.value}

    # ── Update ────────────────────────────────────────────────────

    def update(self, measurement: np.ndarray, R_override: Optional[np.ndarray] = None) -> Dict:
        R = R_override if R_override is not None else self.R

        # Innovation
        innov = measurement - self.H @ self.state
        S = self.H @ self.P @ self.H.T + R

        # Kalman gain
        try:
            K = self.P @ self.H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            K = self.P @ self.H.T @ np.linalg.pinv(S)

        # State update
        self.state = self.state + K @ innov

        # Covariance update (Joseph form)
        I_KH = np.eye(self.STATE_DIM) - K @ self.H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T

        # Adapt
        if self.adaptation_enabled:
            self._adapt(innov, S)

        innov_mag = float(np.linalg.norm(innov))
        self.innovation_history.append({"magnitude": innov_mag, "timestamp": time.time()})

        conf = self._confidence(innov, S)

        return {
            "state": self.state.copy(),
            "innovation": innov,
            "confidence": conf,
            "filter_state": self.filter_state.value,
        }

    # ── Adaptation ────────────────────────────────────────────────

    def _adapt(self, innov: np.ndarray, S: np.ndarray):
        try:
            norm = float(innov.T @ np.linalg.inv(S) @ innov)
        except np.linalg.LinAlgError:
            norm = float(np.linalg.norm(innov))

        if norm > self.innovation_threshold:
            self.R *= (1.0 + self.adaptation_rate)
            self.filter_state = FilterState.ADAPTATION
        else:
            self.R *= (1.0 - self.adaptation_rate * 0.1)

        self.R = np.clip(self.R, self.R_base * 0.1, self.R_base * 10.0)

        if len(self.innovation_history) > 5:
            recent = [h["magnitude"] for h in list(self.innovation_history)[-5:]]
            avg = np.mean(recent)
            if avg > 2.0:
                self.Q *= (1.0 + self.adaptation_rate * 0.5)
            elif avg < 0.5:
                self.Q *= (1.0 - self.adaptation_rate * 0.1)

        self.Q = np.clip(self.Q, self.Q_base * 0.01, self.Q_base * 100.0)

        self.adaptation_history.append({
            "R_diag": np.diag(self.R).tolist(),
            "Q_diag": np.diag(self.Q)[:3].tolist(),
            "innov_norm": norm,
            "timestamp": time.time(),
        })

    def neural_adaptation(self) -> Dict:
        """Use neural network for advanced noise adaptation."""
        if not self.network_trained:
            return {"status": "not_trained"}

        cond = self._condition_vector()

        if HAS_TORCH:
            with torch.no_grad():
                ct = torch.FloatTensor(cond).unsqueeze(0).to(self.device)
                m, p, g = self.noise_net(ct)
                m = m.squeeze().cpu().numpy()
                p = p.squeeze().cpu().numpy()
                g = g.squeeze().cpu().numpy()
        else:
            m, p, g = self.noise_net.forward(cond)

        self.R = np.diag(m[:3])
        self.Q = np.diag(p[:self.STATE_DIM])

        return {"R_diag": m[:3].tolist(), "Q_diag": p[:3].tolist(),
                "gains": g.tolist(), "status": "adapted"}

    def _condition_vector(self) -> np.ndarray:
        c = np.zeros(20, dtype=np.float32)
        env = self.environment
        c[0] = env.temperature / 50.0
        c[1] = env.humidity / 100.0
        c[2] = np.sin(np.radians(env.magnetic_declination))
        c[3] = env.atmospheric_pressure / 1100.0
        density_map = {"rural": 0.2, "suburban": 0.5, "medium": 0.5, "urban": 0.8, "dense_urban": 1.0}
        weather_map = {"clear": 1.0, "cloudy": 0.8, "rain": 0.6, "storm": 0.3, "fog": 0.4}
        c[4] = density_map.get(env.urban_density, 0.5)
        c[5] = weather_map.get(env.weather_condition, 0.7)
        c[6] = env.electromagnetic_noise
        c[7] = env.multipath_severity

        sensors = list(self.sensor_health.values())
        if sensors:
            c[8] = np.mean([s.signal_strength for s in sensors])
            c[9] = np.mean([s.noise_level for s in sensors])
            c[10] = np.mean([s.reliability_score for s in sensors])

        if self.innovation_history:
            recent = [h["magnitude"] for h in list(self.innovation_history)[-10:]]
            c[13] = np.mean(recent)
            c[14] = np.std(recent)

        return c

    # ── State management ──────────────────────────────────────────

    def _update_filter_state(self):
        if len(self.innovation_history) < 10:
            self.filter_state = FilterState.INITIALIZATION
            return
        recent = [h["magnitude"] for h in list(self.innovation_history)[-10:]]
        avg, std = np.mean(recent), np.std(recent)
        if avg < 1.0 and std < 0.5:
            self.filter_state = FilterState.STABLE
        elif avg > 3.0 or std > 2.0:
            self.filter_state = FilterState.DEGRADED
        elif self.filter_state == FilterState.DEGRADED and avg < 2.0:
            self.filter_state = FilterState.RECOVERY
        else:
            self.filter_state = FilterState.ADAPTATION

    def _confidence(self, innov, S) -> float:
        try:
            d = float(np.sqrt(innov.T @ np.linalg.inv(S) @ innov))
        except np.linalg.LinAlgError:
            d = float(np.linalg.norm(innov))
        conf = np.exp(-d / 3.0)
        if self.filter_state == FilterState.STABLE:
            conf = min(1.0, conf * 1.2)
        elif self.filter_state == FilterState.DEGRADED:
            conf *= 0.7
        return float(np.clip(conf, 0.0, 1.0))

    # ── Public API ────────────────────────────────────────────────

    def get_current_position(self) -> Dict:
        pos = self.state[:3]
        unc = np.sqrt(np.diag(self.P[:3, :3]))
        return {
            "lat": float(pos[0]), "lon": float(pos[1]), "alt": float(pos[2]),
            "uncertainty_lat": float(unc[0]), "uncertainty_lon": float(unc[1]),
            "filter_state": self.filter_state.value,
        }

    def update_environment(self, env: IAEKFEnvironment):
        self.environment = env

    def update_sensor_health(self, sensor_id: str, metrics: SensorHealthMetrics):
        self.sensor_health[sensor_id] = metrics

    def get_performance_metrics(self) -> Dict:
        m: Dict = {
            "backend": "torch" if self.using_torch else "numpy",
            "filter_state": self.filter_state.value,
            "adaptation_enabled": self.adaptation_enabled,
            "network_trained": self.network_trained,
            "total_updates": len(self.innovation_history),
        }
        if self.innovation_history:
            recent = [h["magnitude"] for h in list(self.innovation_history)[-20:]]
            m["avg_innovation"] = round(float(np.mean(recent)), 4)
            m["std_innovation"] = round(float(np.std(recent)), 4)
        return m
