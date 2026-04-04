"""
Financial Indicator Navigation — UPIN

Uses trading chart indicators (SMA, EMA, MACD, Bollinger, RSI, VWAP)
to predict position during GPS denial. Records baseline while GPS is
active, then extrapolates using learned patterns when GPS is cut.

Like a trader stacking indicators for confluence — UPIN only trusts
a position when multiple indicator strategies agree.

Longer baseline = better prediction. 200 samples beats 5 samples,
just like 200-candle MA beats 5-candle MA.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ── Indicator Functions ───────────────────────────────────────────

def sma(values: List[float], window: int) -> float:
    """Simple Moving Average."""
    if not values:
        return 0.0
    w = values[-window:]
    return sum(w) / len(w)


def ema(values: List[float], alpha: float) -> float:
    """Exponential Moving Average."""
    if not values:
        return 0.0
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1 - alpha) * result
    return result


def vwma(values: List[float], weights: List[float], window: int) -> float:
    """Volume/Confidence-Weighted Moving Average."""
    v = values[-window:]
    w = weights[-window:]
    if not v or not w:
        return 0.0
    tw = sum(w)
    if tw == 0:
        return sum(v) / len(v)
    return sum(vi * wi for vi, wi in zip(v, w)) / tw


def macd(values: List[float], fast_alpha: float = 0.2, slow_alpha: float = 0.05) -> float:
    """MACD — difference between fast and slow EMA."""
    if len(values) < 2:
        return 0.0
    return ema(values, fast_alpha) - ema(values, slow_alpha)


def bollinger_mean(values: List[float], window: int = 20) -> Tuple[float, float, float]:
    """Bollinger Bands — mean, upper, lower."""
    if not values:
        return (0.0, 0.0, 0.0)
    w = values[-window:]
    m = sum(w) / len(w)
    std = (sum((v - m) ** 2 for v in w) / len(w)) ** 0.5
    return (m, m + 2 * std, m - 2 * std)


def rsi(values: List[float], window: int = 14) -> float:
    """Relative Strength Index — 0-100 heading consistency."""
    if len(values) < 2:
        return 50.0
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    recent = deltas[-window:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / window if gains else 0.001
    avg_loss = sum(losses) / window if losses else 0.001
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


# ── Baseline Recorder ─────────────────────────────────────────────

@dataclass
class BaselineSample:
    """One GPS-confirmed baseline sample."""
    lat: float
    lon: float
    alt: float
    speed_mps: float
    heading_deg: float
    vel_lat: float     # degrees/second
    vel_lon: float
    accel_mps2: float
    confidence: float
    timestamp: float


class BaselineRecorder:
    """Records baseline while GPS is active. Like collecting candles on a chart."""

    def __init__(self, max_samples: int = 500):
        self.samples: deque[BaselineSample] = deque(maxlen=max_samples)
        self._prev_lat = 0.0
        self._prev_lon = 0.0
        self._prev_speed = 0.0
        self._prev_time = 0.0

    def record(self, lat: float, lon: float, alt: float,
               speed: float, heading: float, confidence: float):
        """Record one GPS-confirmed sample."""
        now = time.time()
        dt = now - self._prev_time if self._prev_time > 0 else 1.0
        dt = max(dt, 0.01)

        vel_lat = (lat - self._prev_lat) / dt if self._prev_lat != 0 else 0.0
        vel_lon = (lon - self._prev_lon) / dt if self._prev_lon != 0 else 0.0
        accel = (speed - self._prev_speed) / dt

        self.samples.append(BaselineSample(
            lat=lat, lon=lon, alt=alt, speed_mps=speed,
            heading_deg=heading, vel_lat=vel_lat, vel_lon=vel_lon,
            accel_mps2=accel, confidence=confidence, timestamp=now,
        ))

        self._prev_lat, self._prev_lon = lat, lon
        self._prev_speed = speed
        self._prev_time = now

    @property
    def count(self) -> int:
        return len(self.samples)

    def speeds(self) -> List[float]:
        return [s.speed_mps for s in self.samples]

    def headings(self) -> List[float]:
        return [s.heading_deg for s in self.samples]

    def vel_lats(self) -> List[float]:
        return [s.vel_lat for s in self.samples]

    def vel_lons(self) -> List[float]:
        return [s.vel_lon for s in self.samples]

    def accels(self) -> List[float]:
        return [s.accel_mps2 for s in self.samples]

    def confidences(self) -> List[float]:
        return [s.confidence for s in self.samples]

    def lats(self) -> List[float]:
        return [s.lat for s in self.samples]

    def lons(self) -> List[float]:
        return [s.lon for s in self.samples]

    def get_indicators(self) -> Dict:
        """Get all 6 baseline indicators like a trading dashboard."""
        return {
            "sma_speed": round(sma(self.speeds(), 20), 3),
            "ema_heading": round(ema(self.headings(), 0.15), 1),
            "vwma_lat": round(vwma(self.lats(), self.confidences(), 20), 6),
            "vwma_lon": round(vwma(self.lons(), self.confidences(), 20), 6),
            "velocity_sma_lat": round(sma(self.vel_lats(), 20), 9),
            "velocity_sma_lon": round(sma(self.vel_lons(), 20), 9),
            "accel_ema": round(ema(self.accels(), 0.15), 4),
            "samples": self.count,
        }


# ── Strategy Layers (like stacking trading indicators) ────────────

class PositionStrategy:
    """Base class for a prediction strategy using indicator combos."""

    def __init__(self, name: str):
        self.name = name
        self.errors: List[float] = []
        self.drift_per_second: List[float] = []
        self.weight = 1.0

    def predict(self, baseline: BaselineRecorder, last_known_lat: float,
                last_known_lon: float, blind_seconds: float) -> Tuple[float, float]:
        raise NotImplementedError

    def score(self, predicted_lat: float, predicted_lon: float,
              actual_lat: float, actual_lon: float, blind_seconds: float):
        """Score after GPS resurface."""
        dlat = (predicted_lat - actual_lat) * 111320
        dlon = (predicted_lon - actual_lon) * 111320 * math.cos(math.radians(actual_lat))
        error = math.sqrt(dlat ** 2 + dlon ** 2)
        self.errors.append(error)
        if blind_seconds > 0:
            self.drift_per_second.append(error / blind_seconds)

    def avg_error(self) -> float:
        return sum(self.errors) / len(self.errors) if self.errors else 999.0

    def avg_drift_rate(self) -> float:
        return sum(self.drift_per_second) / len(self.drift_per_second) if self.drift_per_second else 0.0

    def get_stats(self) -> Dict:
        return {
            "name": self.name,
            "weight": round(self.weight, 3),
            "avg_error_m": round(self.avg_error(), 2),
            "avg_drift_mps": round(self.avg_drift_rate(), 3),
            "drills": len(self.errors),
        }


class TrendStrategy(PositionStrategy):
    """Fast SMA(5) + EMA(0.25) — catches turns quickly. Like fast crossover."""

    def __init__(self):
        super().__init__("Trend")

    def predict(self, b: BaselineRecorder, lat: float, lon: float, t: float) -> Tuple[float, float]:
        speed = sma(b.speeds(), 5)
        heading = ema(b.headings(), 0.25)
        heading_rad = math.radians(heading)
        dist = speed * t
        return (lat + dist * math.cos(heading_rad) / 111320,
                lon + dist * math.sin(heading_rad) / (111320 * math.cos(math.radians(lat))))


class SmoothStrategy(PositionStrategy):
    """Slow SMA(30) + EMA(0.05) — filters noise, stable. Like 200-period MA."""

    def __init__(self):
        super().__init__("Smooth")

    def predict(self, b: BaselineRecorder, lat: float, lon: float, t: float) -> Tuple[float, float]:
        speed = sma(b.speeds(), 30)
        heading = ema(b.headings(), 0.05)
        heading_rad = math.radians(heading)
        dist = speed * t
        return (lat + dist * math.cos(heading_rad) / 111320,
                lon + dist * math.sin(heading_rad) / (111320 * math.cos(math.radians(lat))))


class MACDStrategy(PositionStrategy):
    """MACD velocity + RSI heading — predicts turns and acceleration."""

    def __init__(self):
        super().__init__("MACD")

    def predict(self, b: BaselineRecorder, lat: float, lon: float, t: float) -> Tuple[float, float]:
        vel_lat = sma(b.vel_lats(), 10) + macd(b.vel_lats()) * t
        vel_lon = sma(b.vel_lons(), 10) + macd(b.vel_lons()) * t
        # RSI for heading consistency — if RSI > 70, heading is steady; < 30, turning
        heading_rsi = rsi(b.headings(), 14)
        # If turning (RSI < 40), reduce prediction distance
        damping = 1.0 if heading_rsi > 60 else 0.5
        return (lat + vel_lat * t * damping, lon + vel_lon * t * damping)


class BollingerStrategy(PositionStrategy):
    """Bollinger mean reversion — assumes position reverts to average."""

    def __init__(self):
        super().__init__("Bollinger")

    def predict(self, b: BaselineRecorder, lat: float, lon: float, t: float) -> Tuple[float, float]:
        mean_lat, _, _ = bollinger_mean(b.lats(), 20)
        mean_lon, _, _ = bollinger_mean(b.lons(), 20)
        # Blend current position with historical mean (mean reversion)
        revert_strength = min(0.3, t / 60.0)  # Stronger reversion over time
        pred_lat = lat * (1 - revert_strength) + mean_lat * revert_strength
        pred_lon = lon * (1 - revert_strength) + mean_lon * revert_strength
        # Still apply velocity
        vel_lat = sma(b.vel_lats(), 20)
        vel_lon = sma(b.vel_lons(), 20)
        return (pred_lat + vel_lat * t * (1 - revert_strength),
                pred_lon + vel_lon * t * (1 - revert_strength))


class AdaptiveStrategy(PositionStrategy):
    """Auto-tunes alpha and window based on previous drill errors."""

    def __init__(self):
        super().__init__("Adaptive")
        self.sma_window = 15
        self.ema_alpha = 0.15

    def predict(self, b: BaselineRecorder, lat: float, lon: float, t: float) -> Tuple[float, float]:
        speed = sma(b.speeds(), self.sma_window)
        heading = ema(b.headings(), self.ema_alpha)
        heading_rad = math.radians(heading)
        dist = speed * t
        return (lat + dist * math.cos(heading_rad) / 111320,
                lon + dist * math.sin(heading_rad) / (111320 * math.cos(math.radians(lat))))

    def score(self, predicted_lat, predicted_lon, actual_lat, actual_lon, blind_seconds):
        super().score(predicted_lat, predicted_lon, actual_lat, actual_lon, blind_seconds)
        # Self-tune: if error is high, use longer window and lower alpha (smoother)
        if self.errors[-1] > 20:
            self.sma_window = min(50, self.sma_window + 2)
            self.ema_alpha = max(0.03, self.ema_alpha - 0.02)
        elif self.errors[-1] < 5:
            self.sma_window = max(5, self.sma_window - 1)
            self.ema_alpha = min(0.3, self.ema_alpha + 0.01)

    def get_stats(self) -> Dict:
        stats = super().get_stats()
        stats["sma_window"] = self.sma_window
        stats["ema_alpha"] = round(self.ema_alpha, 3)
        return stats


# ── Financial Indicator Navigation Engine ─────────────────────────

class FinancialIndicatorNav:
    """
    Main engine that combines baseline recording + 5 strategy layers.

    While GPS active: records baseline (like collecting candles)
    While GPS denied: predicts using strategies (like trading with indicators)
    After GPS resurface: scores strategies, adjusts weights (backtesting)

    Final position = 60% agent consensus + 40% MA/strategy prediction
    """

    def __init__(self):
        self.baseline = BaselineRecorder(max_samples=500)
        self.strategies = [
            TrendStrategy(),
            SmoothStrategy(),
            MACDStrategy(),
            BollingerStrategy(),
            AdaptiveStrategy(),
        ]
        self._last_known_lat = 0.0
        self._last_known_lon = 0.0
        self._blind_start = 0.0
        self._is_blind = False
        self._drill_count = 0

    # ── GPS Active Phase ──────────────────────────────────────────

    def record_gps_sample(self, lat: float, lon: float, alt: float = 0,
                          speed: float = 0, heading: float = 0, confidence: float = 0.9):
        """Record one GPS sample to baseline. Like adding a candle to the chart."""
        self.baseline.record(lat, lon, alt, speed, heading, confidence)
        self._last_known_lat = lat
        self._last_known_lon = lon
        self._is_blind = False

    # ── GPS Denied Phase ──────────────────────────────────────────

    def enter_blind_mode(self):
        """GPS lost — switch to indicator-based prediction."""
        self._is_blind = True
        self._blind_start = time.time()

    def predict_position(self, agent_lat: float = None, agent_lon: float = None,
                         agent_weight: float = 0.6) -> Dict:
        """
        Predict current position using strategies.

        agent_lat/lon: consensus from other UPIN agents (IMU, mag, etc.)
        agent_weight: how much to trust agents vs MA prediction (default 60/40)

        Returns full prediction with per-strategy breakdown.
        """
        if self.baseline.count < 5:
            return {"lat": self._last_known_lat, "lon": self._last_known_lon,
                    "confidence": 0.1, "source": "insufficient_baseline"}

        blind_seconds = time.time() - self._blind_start if self._is_blind else 0.0

        # Run all strategies
        strategy_predictions = {}
        for strat in self.strategies:
            try:
                pred_lat, pred_lon = strat.predict(
                    self.baseline, self._last_known_lat, self._last_known_lon, blind_seconds
                )
                strategy_predictions[strat.name] = {
                    "lat": pred_lat, "lon": pred_lon, "weight": strat.weight,
                }
            except Exception:
                pass

        if not strategy_predictions:
            return {"lat": self._last_known_lat, "lon": self._last_known_lon,
                    "confidence": 0.2, "source": "no_strategies"}

        # Weighted strategy consensus (like finding confluence)
        total_w = sum(p["weight"] for p in strategy_predictions.values())
        strat_lat = sum(p["lat"] * p["weight"] for p in strategy_predictions.values()) / total_w
        strat_lon = sum(p["lon"] * p["weight"] for p in strategy_predictions.values()) / total_w

        # Blend with agent consensus if available
        if agent_lat is not None and agent_lon is not None:
            final_lat = agent_lat * agent_weight + strat_lat * (1 - agent_weight)
            final_lon = agent_lon * agent_weight + strat_lon * (1 - agent_weight)
        else:
            final_lat, final_lon = strat_lat, strat_lon

        # Confidence degrades with blind time
        time_decay = max(0.1, 1.0 - blind_seconds / 120.0)
        sample_factor = min(1.0, self.baseline.count / 50.0)
        confidence = time_decay * sample_factor * 0.85

        return {
            "lat": final_lat,
            "lon": final_lon,
            "confidence": round(confidence, 3),
            "blind_seconds": round(blind_seconds, 1),
            "baseline_samples": self.baseline.count,
            "strategies_used": len(strategy_predictions),
            "strategy_predictions": strategy_predictions,
            "agent_weight": agent_weight,
            "source": "financial_indicators",
        }

    # ── GPS Resurface (Backtesting) ───────────────────────────────

    def resurface(self, actual_lat: float, actual_lon: float):
        """GPS is back — score all strategies like backtesting a trade."""
        if not self._is_blind:
            return

        blind_seconds = time.time() - self._blind_start
        self._drill_count += 1

        # Score each strategy
        for strat in self.strategies:
            try:
                pred_lat, pred_lon = strat.predict(
                    self.baseline, self._last_known_lat, self._last_known_lon, blind_seconds
                )
                strat.score(pred_lat, pred_lon, actual_lat, actual_lon, blind_seconds)
            except Exception:
                pass

        # Update weights — best strategy gets highest weight
        if any(s.errors for s in self.strategies):
            errors = [(s.avg_error(), s) for s in self.strategies if s.errors]
            errors.sort(key=lambda x: x[0])
            # Best gets weight 2.0, worst gets 0.5
            for rank, (err, strat) in enumerate(errors):
                strat.weight = max(0.5, 2.0 - rank * 0.3)

        self._is_blind = False
        self._last_known_lat = actual_lat
        self._last_known_lon = actual_lon

    # ── Dashboard ─────────────────────────────────────────────────

    def get_dashboard(self) -> Dict:
        """Get full indicator dashboard like a trading screen."""
        indicators = self.baseline.get_indicators()

        # Add trading-style derived indicators
        if self.baseline.count >= 5:
            indicators["speed_macd"] = round(macd(self.baseline.speeds()), 4)
            indicators["heading_rsi"] = round(rsi(self.baseline.headings()), 1)
            bb_lat = bollinger_mean(self.baseline.lats(), 20)
            indicators["bollinger_lat"] = {
                "mean": round(bb_lat[0], 6),
                "upper": round(bb_lat[1], 6),
                "lower": round(bb_lat[2], 6),
            }

        return {
            "indicators": indicators,
            "strategies": [s.get_stats() for s in self.strategies],
            "drill_count": self._drill_count,
            "is_blind": self._is_blind,
            "baseline_quality": "good" if self.baseline.count > 50 else
                                "fair" if self.baseline.count > 20 else "building",
        }
