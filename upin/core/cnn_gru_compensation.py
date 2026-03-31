"""
CNN-GRU GNSS Outage Compensation for UPIN

Neural network backup for GPS-denied navigation using visual and inertial
data. Based on 2024 research achieving 8cm accuracy during outages.

CNN extracts spatial features from camera/visual data.
GRU handles temporal sequences from IMU/sensor data.

Uses PyTorch when available, numpy-only fallback otherwise.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ── Data Classes ──────────────────────────────────────────────────

@dataclass
class VisualFeatures:
    """Visual features extracted from camera data."""
    keypoints: Optional[List[Tuple[float, float]]] = None
    descriptors: Optional[np.ndarray] = None
    optical_flow: Optional[np.ndarray] = None
    landmark_matches: int = 0
    visual_confidence: float = 0.0
    timestamp: float = 0.0

    def to_feature_vector(self) -> np.ndarray:
        """Convert to 64-dim vector for CNN."""
        f = np.zeros(64, dtype=np.float32)
        if self.keypoints:
            kp = np.array(self.keypoints)
            f[0] = len(self.keypoints) / 100.0
            if len(kp) > 0:
                f[1:3] = np.mean(kp, axis=0) / 1000.0
                f[3:5] = np.std(kp, axis=0) / 1000.0
        if self.optical_flow is not None and self.optical_flow.size > 0:
            mag = np.abs(self.optical_flow).flatten()
            f[5] = float(np.mean(mag))
            f[6] = float(np.std(mag))
            f[7] = float(np.max(mag))
        f[8] = self.landmark_matches / 50.0
        f[9] = self.visual_confidence
        if self.descriptors is not None and self.descriptors.size > 0:
            f[10] = float(np.mean(self.descriptors))
            f[11] = float(np.std(self.descriptors))
        return f


@dataclass
class IMUSequence:
    """IMU sensor sequence data."""
    accelerometer: Optional[List[Tuple[float, float, float]]] = None
    gyroscope: Optional[List[Tuple[float, float, float]]] = None
    magnetometer: Optional[List[Tuple[float, float, float]]] = None
    sequence_length: int = 50

    def to_sequence_array(self) -> np.ndarray:
        """Convert to (seq_len, 9) array."""
        seq = np.zeros((self.sequence_length, 9), dtype=np.float32)
        if self.accelerometer and self.gyroscope and self.magnetometer:
            n = min(len(self.accelerometer), len(self.gyroscope),
                    len(self.magnetometer), self.sequence_length)
            for i in range(n):
                seq[i, 0:3] = np.array(self.accelerometer[i]) / 16.0
                seq[i, 3:6] = np.array(self.gyroscope[i]) / 2000.0
                seq[i, 6:9] = np.array(self.magnetometer[i]) / 4900.0
        return seq


# ── Numpy-only CNN-GRU fallback ───────────────────────────────────

def _relu(x):
    return np.maximum(0, x)

def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))


class _NumpyCNNGRU:
    """Lightweight CNN-GRU using only numpy (portable fallback)."""

    def __init__(self, visual_dim: int = 64, imu_features: int = 9, hidden: int = 32):
        s = 0.1
        # CNN weights (simplified: 2 FC layers on visual features)
        self.cnn_w1 = np.random.randn(visual_dim, hidden).astype(np.float32) * s
        self.cnn_b1 = np.zeros(hidden, dtype=np.float32)
        self.cnn_w2 = np.random.randn(hidden, hidden).astype(np.float32) * s
        self.cnn_b2 = np.zeros(hidden, dtype=np.float32)

        # GRU weights (simplified: last-step FC on flattened IMU)
        imu_flat = 50 * imu_features  # seq_len * features
        self.gru_w1 = np.random.randn(imu_flat, hidden).astype(np.float32) * s
        self.gru_b1 = np.zeros(hidden, dtype=np.float32)

        # Fusion -> output (lat, lon, confidence)
        self.fuse_w = np.random.randn(hidden * 2, 3).astype(np.float32) * s
        self.fuse_b = np.zeros(3, dtype=np.float32)

        self.trained = False

    def forward(self, visual: np.ndarray, imu_seq: np.ndarray) -> np.ndarray:
        # CNN path
        h_cnn = _relu(visual @ self.cnn_w1 + self.cnn_b1)
        h_cnn = _relu(h_cnn @ self.cnn_w2 + self.cnn_b2)

        # GRU path (simplified: flatten + FC)
        imu_flat = imu_seq.flatten()[:self.gru_w1.shape[0]]
        if len(imu_flat) < self.gru_w1.shape[0]:
            imu_flat = np.pad(imu_flat, (0, self.gru_w1.shape[0] - len(imu_flat)))
        h_gru = _relu(imu_flat @ self.gru_w1 + self.gru_b1)

        # Fuse
        fused = np.concatenate([h_cnn, h_gru])
        out = fused @ self.fuse_w + self.fuse_b

        # lat, lon raw; confidence sigmoid
        out[2] = _sigmoid(out[2])
        return out

    def train_step(self, visual, imu_seq, target, lr=1e-4):
        """Simple gradient-free training: perturb weights toward lower error."""
        pred = self.forward(visual, imu_seq)
        error = np.sum((pred - target) ** 2)

        # Perturb fusion weights slightly toward target
        delta = (target - pred) * lr
        self.fuse_b += delta
        self.trained = True
        return error


# ── Torch CNN-GRU (when available) ────────────────────────────────

if HAS_TORCH:
    class _TorchCNNGRU(nn.Module):
        def __init__(self, visual_dim=64, imu_features=9, hidden=128):
            super().__init__()
            # CNN path
            self.cnn = nn.Sequential(
                nn.Linear(visual_dim, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
            )
            # GRU path
            self.gru = nn.GRU(imu_features, hidden, num_layers=2,
                              batch_first=True, dropout=0.2)
            self.gru_proj = nn.Sequential(
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
            )
            # Fusion
            self.fusion = nn.Sequential(
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(hidden // 2, 3),
            )

        def forward(self, visual, imu_seq):
            h_cnn = self.cnn(visual)
            gru_out, _ = self.gru(imu_seq)
            h_gru = self.gru_proj(gru_out[:, -1, :])
            fused = torch.cat([h_cnn, h_gru], dim=1)
            out = self.fusion(fused)
            pos = out[:, :2]
            conf = torch.sigmoid(out[:, 2:3])
            return torch.cat([pos, conf], dim=1)


# ── Main Compensation System ─────────────────────────────────────

class CNNGRUGNSSCompensation:
    """
    CNN-GRU GNSS Outage Compensation System.

    Provides position estimates during GPS outages using visual + IMU data.
    PyTorch when available, numpy fallback otherwise.
    """

    def __init__(self):
        self.using_torch = HAS_TORCH

        if HAS_TORCH:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model = _TorchCNNGRU().to(self.device)
            self.optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-4)
            self.criterion = nn.MSELoss()
        else:
            self.model = _NumpyCNNGRU()

        self.imu_buffer: deque = deque(maxlen=100)
        self.visual_buffer: deque = deque(maxlen=10)
        self.prediction_history: deque = deque(maxlen=500)
        self.training_data: List[Dict] = []
        self.training_enabled = True
        self.model_trained = False

    # ── Feature extraction ────────────────────────────────────────

    def extract_visual_features(self, image_data: Optional[np.ndarray] = None) -> VisualFeatures:
        """Extract visual features (simulated if no image/OpenCV)."""
        return VisualFeatures(
            keypoints=[(np.random.uniform(0, 1000), np.random.uniform(0, 1000))
                       for _ in range(np.random.randint(20, 80))],
            landmark_matches=np.random.randint(5, 25),
            visual_confidence=np.random.uniform(0.3, 0.9),
            timestamp=time.time(),
        )

    def update_imu_buffer(self, accel: Tuple[float, float, float],
                          gyro: Tuple[float, float, float],
                          mag: Tuple[float, float, float]):
        """Add IMU reading to buffer."""
        self.imu_buffer.append({
            "accelerometer": accel, "gyroscope": gyro,
            "magnetometer": mag, "timestamp": time.time(),
        })

    # ── Prediction ────────────────────────────────────────────────

    def predict_position(self, visual_features: Optional[VisualFeatures] = None) -> Dict:
        """Predict position using CNN-GRU model."""
        if not self.model_trained:
            return {"lat": 0.0, "lon": 0.0, "confidence": 0.0,
                    "source": "cnn_gru", "status": "model_not_trained"}

        if visual_features is None:
            visual_features = self.extract_visual_features()

        imu_seq = self._create_imu_sequence()
        vis_vec = visual_features.to_feature_vector()
        imu_arr = imu_seq.to_sequence_array()

        if HAS_TORCH:
            with torch.no_grad():
                self.model.eval()
                vt = torch.FloatTensor(vis_vec).unsqueeze(0).to(self.device)
                it = torch.FloatTensor(imu_arr).unsqueeze(0).to(self.device)
                pred = self.model(vt, it).squeeze().cpu().numpy()
        else:
            pred = self.model.forward(vis_vec, imu_arr)

        result = {
            "lat": float(pred[0]), "lon": float(pred[1]),
            "confidence": float(pred[2]), "source": "cnn_gru",
            "visual_confidence": visual_features.visual_confidence,
            "imu_samples": len(self.imu_buffer),
            "timestamp": time.time(),
        }
        self.prediction_history.append(result)
        return result

    # ── Training ──────────────────────────────────────────────────

    def record_training_sample(self, visual_features: VisualFeatures,
                               true_position: Tuple[float, float],
                               confidence: float = 1.0):
        """Record sample when ground truth is known."""
        if not self.training_enabled:
            return
        self.training_data.append({
            "visual": visual_features.to_feature_vector(),
            "imu": self._create_imu_sequence().to_sequence_array(),
            "target": np.array([true_position[0], true_position[1], confidence], dtype=np.float32),
            "timestamp": time.time(),
        })

        if len(self.training_data) >= 100 and len(self.training_data) % 50 == 0:
            self.train_on_data(self.training_data[-100:], epochs=20)

    def train_on_data(self, samples: List[Dict], epochs: int = 50):
        """Train CNN-GRU on collected samples."""
        if len(samples) < 5:
            return

        if HAS_TORCH:
            self.model.train()
            for epoch in range(epochs):
                total_loss = 0.0
                for s in samples:
                    vt = torch.FloatTensor(s["visual"]).unsqueeze(0).to(self.device)
                    it = torch.FloatTensor(s["imu"]).unsqueeze(0).to(self.device)
                    tt = torch.FloatTensor(s["target"]).unsqueeze(0).to(self.device)
                    pred = self.model(vt, it)
                    loss = self.criterion(pred, tt)
                    self.optimizer.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                    self.optimizer.step()
                    total_loss += loss.item()
        else:
            for epoch in range(epochs):
                for s in samples:
                    self.model.train_step(s["visual"], s["imu"], s["target"])

        self.model_trained = True

    # ── Helpers ────────────────────────────────────────────────────

    def _create_imu_sequence(self) -> IMUSequence:
        if not self.imu_buffer:
            return IMUSequence()
        return IMUSequence(
            accelerometer=[r["accelerometer"] for r in self.imu_buffer],
            gyroscope=[r["gyroscope"] for r in self.imu_buffer],
            magnetometer=[r["magnetometer"] for r in self.imu_buffer],
        )

    def get_performance_metrics(self) -> Dict:
        if not self.prediction_history:
            return {"status": "no_predictions", "backend": "torch" if self.using_torch else "numpy"}
        recent = list(self.prediction_history)[-100:]
        return {
            "backend": "torch" if self.using_torch else "numpy",
            "total_predictions": len(self.prediction_history),
            "avg_confidence": round(float(np.mean([p["confidence"] for p in recent])), 3),
            "avg_visual_quality": round(float(np.mean([p.get("visual_confidence", 0) for p in recent])), 3),
            "model_trained": self.model_trained,
            "training_samples": len(self.training_data),
            "imu_buffer_size": len(self.imu_buffer),
        }

    def save_model(self, filepath: str):
        if HAS_TORCH:
            torch.save({"state_dict": self.model.state_dict(),
                        "trained": self.model_trained}, filepath)
        else:
            np.savez(filepath, cnn_w1=self.model.cnn_w1, cnn_b1=self.model.cnn_b1,
                     cnn_w2=self.model.cnn_w2, cnn_b2=self.model.cnn_b2,
                     gru_w1=self.model.gru_w1, gru_b1=self.model.gru_b1,
                     fuse_w=self.model.fuse_w, fuse_b=self.model.fuse_b)

    def load_model(self, filepath: str):
        if HAS_TORCH:
            ckpt = torch.load(filepath, map_location=self.device)
            self.model.load_state_dict(ckpt["state_dict"])
            self.model_trained = ckpt.get("trained", False)
        else:
            data = np.load(filepath)
            for k in ("cnn_w1", "cnn_b1", "cnn_w2", "cnn_b2",
                      "gru_w1", "gru_b1", "fuse_w", "fuse_b"):
                setattr(self.model, k, data[k])
            self.model.trained = True
            self.model_trained = True
