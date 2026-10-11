"""
A small neural network that predicts velocity and how sure it is.

Two hidden layers (tanh), about 4-5 thousand weights. Inputs are features of
the last second of IMU, attitude and throttle (upin/learned/features.py).
Outputs are two velocity components and the log-variance of each.

TRAINED TO STATE ITS OWN UNCERTAINTY

The loss is the Gaussian negative log-likelihood,
    0.5 * (log s^2 + (y - mu)^2 / s^2),
so the network is penalised both for being wrong and for claiming more
certainty than it has. After training, the stated sigma is checked on
flights it never trained on and scaled so the 95% interval covers 95% there
(sigma_scale). Without held-out flights the scale stays 1 and the model is
marked unvalidated.

Plain numpy: no PyTorch, so the same code trains and runs on the Pi or a
laptop. Deterministic for a given seed.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

LOGVAR_MIN, LOGVAR_MAX = -8.0, 6.0
Z95 = 1.959964


@dataclass
class TrainResult:
    epochs: int
    train_nll: List[float] = field(default_factory=list)
    val_nll: List[float] = field(default_factory=list)


class InertialNet:
    def __init__(self, n_in: int, hidden=(48, 32), n_out: int = 2, seed: int = 0):
        rng = np.random.default_rng(seed)
        sizes = [n_in, *hidden, 2 * n_out]
        self.W = [rng.normal(0, np.sqrt(1.0 / a), (a, b)) for a, b in zip(sizes, sizes[1:])]
        self.b = [np.zeros(b) for b in sizes[1:]]
        self.n_in, self.n_out, self.hidden = n_in, n_out, tuple(hidden)
        self.x_mean = np.zeros(n_in)
        self.x_std = np.ones(n_in)
        self.y_scale = np.ones(n_out)
        self.sigma_scale = 1.0
        self.meta: Dict = {}

    @property
    def n_weights(self) -> int:
        return int(sum(w.size for w in self.W) + sum(b.size for b in self.b))

    # -- forward / backward ----------------------------------------------

    def _forward(self, X):
        acts = [X]
        h = X
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            z = h @ W + b
            h = np.tanh(z) if i < len(self.W) - 1 else z
            acts.append(h)
        out = acts[-1]
        mu = out[:, :self.n_out]
        logvar = np.clip(out[:, self.n_out:], LOGVAR_MIN, LOGVAR_MAX)
        return mu, logvar, acts

    def _nll_grad(self, X, Y):
        mu, logvar, acts = self._forward(X)
        inv = np.exp(-logvar)
        err = mu - Y
        nll = 0.5 * (logvar + err * err * inv)
        n = X.shape[0]
        d_mu = err * inv / n
        d_lv = 0.5 * (1.0 - err * err * inv) / n
        raw_lv = acts[-1][:, self.n_out:]
        d_lv = d_lv * ((raw_lv > LOGVAR_MIN) & (raw_lv < LOGVAR_MAX))
        delta = np.concatenate([d_mu, d_lv], axis=1)
        gW, gb = [None] * len(self.W), [None] * len(self.b)
        for i in range(len(self.W) - 1, -1, -1):
            gW[i] = acts[i].T @ delta
            gb[i] = delta.sum(axis=0)
            if i > 0:
                delta = (delta @ self.W[i].T) * (1.0 - acts[i] ** 2)
        return float(nll.sum(axis=1).mean()), gW, gb

    # -- training ----------------------------------------------------------

    def fit(self, X, Y, X_val=None, Y_val=None, epochs=200, batch=128,
            lr=3e-3, seed=0, patience=25) -> TrainResult:
        """Adam on the NLL; early stopping on validation NLL if given."""
        rng = np.random.default_rng(seed)
        self.x_mean = X.mean(axis=0)
        self.x_std = X.std(axis=0) + 1e-6
        self.y_scale = Y.std(axis=0) + 1e-6
        Xn, Yn = self._nx(X), Y / self.y_scale
        Xv = self._nx(X_val) if X_val is not None and len(X_val) else None
        Yv = Y_val / self.y_scale if Xv is not None else None
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        t, best, best_params, wait = 0, np.inf, None, 0
        res = TrainResult(0)
        for ep in range(epochs):
            order = rng.permutation(len(Xn))
            for k in range(0, len(order), batch):
                idx = order[k:k + batch]
                _, gW, gb = self._nll_grad(Xn[idx], Yn[idx])
                t += 1
                for j, g in enumerate(gW + gb):
                    m[j] = 0.9 * m[j] + 0.1 * g
                    v[j] = 0.999 * v[j] + 0.001 * g * g
                    mh, vh = m[j] / (1 - 0.9 ** t), v[j] / (1 - 0.999 ** t)
                    params[j] -= lr * mh / (np.sqrt(vh) + 1e-8)
            res.train_nll.append(self._nll_grad(Xn, Yn)[0])
            res.epochs = ep + 1
            if Yv is not None:
                vn = self._nll_grad(Xv, Yv)[0]
                res.val_nll.append(vn)
                if vn < best - 1e-4:
                    best, wait = vn, 0
                    best_params = [p.copy() for p in params]
                else:
                    wait += 1
                    if wait >= patience:
                        break
        if best_params is not None:
            for p, bp in zip(params, best_params):
                p[...] = bp
        return res

    def calibrate(self, X_val, Y_val) -> Optional[float]:
        """Scale sigma so 95% of held-out errors fall inside +-1.96 sigma."""
        if X_val is None or len(X_val) < 20:
            self.sigma_scale = 1.0
            return None
        mu, sig = self.predict(X_val, calibrated=False)
        z = np.abs(Y_val - mu) / sig
        self.sigma_scale = float(max(np.quantile(z, 0.95) / Z95, 1e-3))
        return self.sigma_scale

    # -- inference -----------------------------------------------------------

    def _nx(self, X):
        return (X - self.x_mean) / self.x_std

    def predict(self, X, calibrated: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        mu, logvar, _ = self._forward(self._nx(np.atleast_2d(X)))
        sig = np.exp(0.5 * logvar) * self.y_scale
        if calibrated:
            sig = sig * self.sigma_scale
        return mu * self.y_scale, sig

    def nll(self, X, Y) -> float:
        mu, sig = self.predict(X)
        return float(np.mean(np.sum(np.log(sig) + 0.5 * ((Y - mu) / sig) ** 2, axis=1)))

    def coverage95(self, X, Y) -> float:
        """Fraction of components inside their stated 95% interval
        (per axis; 0.95 is the target)."""
        mu, sig = self.predict(X)
        return float(np.mean(np.abs(Y - mu) <= Z95 * sig))

    # -- persistence ---------------------------------------------------------

    def save(self, path: str) -> None:
        arrays = {f"W{i}": w for i, w in enumerate(self.W)}
        arrays.update({f"b{i}": b for i, b in enumerate(self.b)})
        np.savez(path, x_mean=self.x_mean, x_std=self.x_std, y_scale=self.y_scale,
                 sigma_scale=np.array(self.sigma_scale),
                 shape=np.array([self.n_in, self.n_out, *self.hidden]),
                 meta=np.array(json.dumps(self.meta)), **arrays)

    @classmethod
    def load(cls, path: str) -> "InertialNet":
        d = np.load(path, allow_pickle=False)
        n_in, n_out, *hidden = [int(x) for x in d["shape"]]
        net = cls(n_in, tuple(hidden), n_out)
        net.W = [d[f"W{i}"] for i in range(len(net.W))]
        net.b = [d[f"b{i}"] for i in range(len(net.b))]
        net.x_mean, net.x_std, net.y_scale = d["x_mean"], d["x_std"], d["y_scale"]
        net.sigma_scale = float(d["sigma_scale"])
        net.meta = json.loads(str(d["meta"]))
        return net
