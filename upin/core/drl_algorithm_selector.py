"""
Deep Reinforcement Learning Algorithm Selector for UPIN

Sits above Multi-Layer Fish Schooling and learns which schools to trust
in different environmental conditions using PPO (Proximal Policy Optimization).

Uses PyTorch when available, falls back to numpy-only implementation.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Try torch, fall back to numpy ─────────────────────────────────
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Categorical

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ── Environment State ─────────────────────────────────────────────

@dataclass
class EnvironmentState:
    """Current environment state for DRL decision making."""

    gps_available: bool = True
    cellular_signal_strength: float = 1.0
    wifi_networks_count: int = 0
    jamming_detected: bool = False
    spoofing_detected: bool = False
    movement_speed: float = 0.0
    time_since_last_confirmation: float = 0.0
    weather_condition: str = "clear"
    urban_density: str = "medium"

    def to_vector(self) -> np.ndarray:
        weather_map = {"clear": 1.0, "cloudy": 0.8, "rain": 0.6, "storm": 0.3, "fog": 0.4}
        density_map = {"rural": 0.2, "suburban": 0.5, "urban": 0.8, "dense_urban": 1.0, "medium": 0.5}
        return np.array([
            float(self.gps_available),
            self.cellular_signal_strength,
            min(self.wifi_networks_count / 10.0, 1.0),
            float(self.jamming_detected),
            float(self.spoofing_detected),
            min(self.movement_speed / 100.0, 1.0),
            min(self.time_since_last_confirmation / 3600.0, 1.0),
            weather_map.get(self.weather_condition, 0.7),
            density_map.get(self.urban_density, 0.5),
        ], dtype=np.float32)


# ── Numpy-only PPO (portable, no torch needed) ───────────────────

def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0, x)


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


class _NumpyPPO:
    """Lightweight PPO implementation using only numpy."""

    def __init__(self, state_dim: int, action_dim: int, hidden: int = 64):
        self.state_dim = state_dim
        self.action_dim = action_dim
        scale = 0.1

        # Shared
        self.w1 = np.random.randn(state_dim, hidden).astype(np.float32) * scale
        self.b1 = np.zeros(hidden, dtype=np.float32)
        self.w2 = np.random.randn(hidden, hidden).astype(np.float32) * scale
        self.b2 = np.zeros(hidden, dtype=np.float32)

        # Actor head
        self.wa = np.random.randn(hidden, action_dim).astype(np.float32) * scale
        self.ba = np.zeros(action_dim, dtype=np.float32)

        # Critic head
        self.wv = np.random.randn(hidden, 1).astype(np.float32) * scale
        self.bv = np.zeros(1, dtype=np.float32)

    def forward(self, state: np.ndarray) -> Tuple[np.ndarray, float]:
        h = _relu(state @ self.w1 + self.b1)
        h = _relu(h @ self.w2 + self.b2)
        probs = _softmax(h @ self.wa + self.ba)
        value = float((h @ self.wv + self.bv)[0])
        return probs, value

    def update(self, states, actions, rewards, lr: float = 3e-4):
        """Simple policy gradient update (simplified PPO for numpy)."""
        if len(states) == 0:
            return

        states = np.array(states)
        actions = np.array(actions, dtype=int)
        rewards = np.array(rewards, dtype=np.float32)

        # Normalize rewards
        if rewards.std() > 0:
            rewards = (rewards - rewards.mean()) / (rewards.std() + 1e-8)

        for i in range(len(states)):
            probs, _ = self.forward(states[i])
            grad_log = np.zeros(self.action_dim)
            grad_log[actions[i]] = 1.0 / max(probs[actions[i]], 1e-8)

            # Shared layers forward for gradient
            h1 = _relu(states[i] @ self.w1 + self.b1)
            h2 = _relu(h1 @ self.w2 + self.b2)

            # Simple gradient step on actor weights
            self.wa += lr * rewards[i] * np.outer(h2, grad_log) * 0.1
            self.ba += lr * rewards[i] * grad_log * 0.1


# ── Torch PPO (when available) ────────────────────────────────────

if HAS_TORCH:
    class _TorchPPO(nn.Module):
        def __init__(self, state_dim: int, action_dim: int, hidden: int = 128):
            super().__init__()
            self.shared = nn.Sequential(
                nn.Linear(state_dim, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden // 2), nn.ReLU(),
            )
            self.actor = nn.Sequential(
                nn.Linear(hidden // 2, hidden // 4), nn.ReLU(),
                nn.Linear(hidden // 4, action_dim), nn.Softmax(dim=-1),
            )
            self.critic = nn.Sequential(
                nn.Linear(hidden // 2, hidden // 4), nn.ReLU(),
                nn.Linear(hidden // 4, 1),
            )

        def forward(self, x):
            h = self.shared(x)
            return self.actor(h), self.critic(h)


# ── DRL Algorithm Selector ────────────────────────────────────────

class DRLAlgorithmSelector:
    """
    Deep Reinforcement Learning Algorithm Selector using PPO.

    Learns which fish schools to trust in different environmental conditions.
    Uses PyTorch when available, numpy-only fallback otherwise.
    """

    STATE_DIM = 9

    def __init__(self, num_fish_schools: int = 60):
        self.num_fish_schools = num_fish_schools
        self.using_torch = HAS_TORCH

        # PPO hyperparams
        self.gamma = 0.99
        self.epsilon = 0.2
        self.epochs = 10
        self.batch_size = 64
        self.lr = 3e-4

        # Build network
        if HAS_TORCH:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.network = _TorchPPO(self.STATE_DIM, num_fish_schools).to(self.device)
            self.optimizer = optim.Adam(self.network.parameters(), lr=self.lr)
        else:
            self.network = _NumpyPPO(self.STATE_DIM, num_fish_schools)

        # Experience buffer
        self.memory: deque = deque(maxlen=2048)
        self.selection_history: deque = deque(maxlen=1000)
        self.total_rewards: List[float] = []
        self.training_enabled = True

    # ── Selection ─────────────────────────────────────────────────

    def select_best_schools(
        self,
        environment_state: EnvironmentState,
        fish_school_results: List[Dict],
        top_k: int = 10,
    ) -> List[Dict]:
        """Select best fish schools for current environment via DRL."""
        state = environment_state.to_vector()

        # Get action probabilities
        if HAS_TORCH:
            with torch.no_grad():
                st = torch.FloatTensor(state).unsqueeze(0).to(self.device)
                probs, _ = self.network(st)
                action_probs = probs.squeeze().cpu().numpy()
        else:
            action_probs, _ = self.network.forward(state)

        # Score schools: 70% DRL + 30% inherent confidence
        scored = []
        for i, sr in enumerate(fish_school_results):
            p = action_probs[i] if i < len(action_probs) else 0.0
            combined = p * 0.7 + sr.get("confidence", 0.0) * 0.3
            scored.append((combined, sr))

        scored.sort(reverse=True, key=lambda x: x[0])
        selected = [s for _, s in scored[:top_k]]

        self.selection_history.append({
            "timestamp": time.time(),
            "state": state.tolist(),
            "action_probs": action_probs[:10].tolist(),
            "selected": [s.get("school_id", "?") for s in selected],
        })

        return selected

    # ── Learning ──────────────────────────────────────────────────

    def learn_from_confirmation(
        self,
        environment_state: EnvironmentState,
        selected_schools: List[Dict],
        true_position: Tuple[float, float],
        prediction_position: Tuple[float, float],
    ):
        """Learn from GPS/landmark confirmed position."""
        if not self.training_enabled:
            return

        error_m = float(np.linalg.norm(
            (np.array(true_position) - np.array(prediction_position)) * 111320
        ))

        # Reward: exp(-error/10) + confidence bonus
        reward = math.exp(-error_m / 10.0)
        avg_conf = np.mean([s.get("confidence", 0) for s in selected_schools])
        if error_m < 5.0 and avg_conf > 0.8:
            reward += 0.2
        elif error_m < 10.0 and avg_conf > 0.9:
            reward += 0.1

        state = environment_state.to_vector()

        # Determine action index from selected school
        action = 0
        if selected_schools:
            sid = selected_schools[0].get("school_id", "")
            parts = sid.split("_")
            if len(parts) >= 3:
                try:
                    action = int(parts[1]) * 10 + int(parts[2])
                except ValueError:
                    pass

        self.memory.append({"state": state, "action": action, "reward": reward})

        if len(self.memory) >= self.batch_size * 4:
            self._train()

    def _train(self):
        """Train the policy network."""
        states = [e["state"] for e in self.memory]
        actions = [e["action"] for e in self.memory]
        rewards = [e["reward"] for e in self.memory]

        if HAS_TORCH:
            self._train_torch(states, actions, rewards)
        else:
            self.network.update(states, actions, rewards, lr=self.lr)

        avg_r = float(np.mean(rewards))
        self.total_rewards.append(avg_r)
        self.memory.clear()

    def _train_torch(self, states, actions, rewards):
        """Full PPO training with PyTorch."""
        s = torch.FloatTensor(np.array(states)).to(self.device)
        a = torch.LongTensor(actions).to(self.device)
        r = torch.FloatTensor(rewards).to(self.device)

        # Normalise rewards
        if r.std() > 0:
            r = (r - r.mean()) / (r.std() + 1e-8)

        with torch.no_grad():
            old_probs, old_values = self.network(s)
            old_log_probs = torch.log(old_probs.gather(1, a.unsqueeze(1)).squeeze() + 1e-8)
            advantages = r - old_values.squeeze()

        for _ in range(self.epochs):
            probs, values = self.network(s)
            new_log_probs = torch.log(probs.gather(1, a.unsqueeze(1)).squeeze() + 1e-8)

            ratio = torch.exp(new_log_probs - old_log_probs)
            s1 = ratio * advantages
            s2 = torch.clamp(ratio, 1 - self.epsilon, 1 + self.epsilon) * advantages

            policy_loss = -torch.min(s1, s2).mean()
            value_loss = nn.MSELoss()(values.squeeze(), r)
            entropy = Categorical(probs).entropy().mean()

            loss = policy_loss + 0.5 * value_loss - 0.01 * entropy

            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 0.5)
            self.optimizer.step()

    # ── Stats ─────────────────────────────────────────────────────

    def get_selection_statistics(self) -> Dict:
        if not self.selection_history:
            return {"total_selections": 0}

        counts: Dict[str, int] = {}
        for sel in self.selection_history:
            for sid in sel["selected"]:
                counts[sid] = counts.get(sid, 0) + 1

        total = sum(counts.values()) or 1
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "backend": "torch" if self.using_torch else "numpy",
            "total_selections": len(self.selection_history),
            "unique_schools": len(counts),
            "top_schools": [(k, round(v / total, 3)) for k, v in top],
            "avg_reward": round(np.mean(self.total_rewards), 4) if self.total_rewards else 0.0,
            "training_episodes": len(self.total_rewards),
        }

    def save_model(self, filepath: str):
        if HAS_TORCH:
            torch.save({
                "state_dict": self.network.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "rewards": self.total_rewards,
            }, filepath)
        else:
            np.savez(filepath,
                      w1=self.network.w1, b1=self.network.b1,
                      w2=self.network.w2, b2=self.network.b2,
                      wa=self.network.wa, ba=self.network.ba,
                      wv=self.network.wv, bv=self.network.bv)

    def load_model(self, filepath: str):
        if HAS_TORCH:
            ckpt = torch.load(filepath, map_location=self.device)
            self.network.load_state_dict(ckpt["state_dict"])
            self.optimizer.load_state_dict(ckpt["optimizer"])
            self.total_rewards = ckpt.get("rewards", [])
        else:
            data = np.load(filepath)
            for k in ("w1", "b1", "w2", "b2", "wa", "ba", "wv", "bv"):
                setattr(self.network, k, data[k])
