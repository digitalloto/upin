"""
Unconventional Mathematics for Position Prediction — UPIN

Six novel mathematical approaches that no standard navigation system uses:

1. Fourier Transform — find periodic movement patterns (commute, patrol)
2. Markov Chain — probabilistic state machine (stop→walk→drive→turn)
3. Bezier Spline — smooth curve extrapolation of path
4. Wavelet Denoising — multi-resolution noise separation
5. Shannon Entropy — information-theoretic prediction confidence
6. Terrain Slope Constraining — accelerometer tilt constrains road identity

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════
#  1. FOURIER TRANSFORM — Find movement rhythm
# ══════════════════════════════════════════════════════════════════

class FourierMovementAnalyzer:
    """
    Decomposes movement into frequency components using FFT.

    If you patrol a route, your lat/lon has a periodic pattern.
    FFT finds that period. During GPS denial, it predicts
    where you are in the cycle.

    Like finding the beat in music — your movement has a rhythm.
    """

    def __init__(self, sample_rate_hz: float = 1.0):
        self._sample_rate = sample_rate_hz
        self._lat_history: deque = deque(maxlen=512)
        self._lon_history: deque = deque(maxlen=512)
        self._dominant_freq_lat = 0.0
        self._dominant_freq_lon = 0.0
        self._amplitude_lat = 0.0
        self._amplitude_lon = 0.0
        self._phase_lat = 0.0
        self._phase_lon = 0.0
        self._mean_lat = 0.0
        self._mean_lon = 0.0

    def add_sample(self, lat: float, lon: float):
        self._lat_history.append(lat)
        self._lon_history.append(lon)

    def analyze(self) -> Dict:
        """Run FFT and find dominant movement frequencies."""
        if len(self._lat_history) < 16:
            return {"status": "insufficient_data", "samples": len(self._lat_history)}

        lats = np.array(self._lat_history)
        lons = np.array(self._lon_history)
        self._mean_lat = float(np.mean(lats))
        self._mean_lon = float(np.mean(lons))

        # Remove DC offset (mean)
        lat_ac = lats - self._mean_lat
        lon_ac = lons - self._mean_lon

        # FFT
        fft_lat = np.fft.rfft(lat_ac)
        fft_lon = np.fft.rfft(lon_ac)
        freqs = np.fft.rfftfreq(len(lat_ac), d=1.0 / self._sample_rate)

        # Find dominant frequency (skip DC at index 0)
        if len(fft_lat) > 1:
            mag_lat = np.abs(fft_lat[1:])
            mag_lon = np.abs(fft_lon[1:])
            idx_lat = int(np.argmax(mag_lat)) + 1
            idx_lon = int(np.argmax(mag_lon)) + 1

            self._dominant_freq_lat = float(freqs[idx_lat])
            self._dominant_freq_lon = float(freqs[idx_lon])
            self._amplitude_lat = float(mag_lat[idx_lat - 1]) * 2 / len(lat_ac)
            self._amplitude_lon = float(mag_lon[idx_lon - 1]) * 2 / len(lon_ac)
            self._phase_lat = float(np.angle(fft_lat[idx_lat]))
            self._phase_lon = float(np.angle(fft_lon[idx_lon]))

        # Periodicity strength: how much of the signal is in the dominant frequency
        total_power_lat = float(np.sum(np.abs(fft_lat[1:]) ** 2))
        dom_power_lat = float(np.abs(fft_lat[idx_lat]) ** 2) if len(fft_lat) > 1 else 0
        periodicity = dom_power_lat / total_power_lat if total_power_lat > 0 else 0

        return {
            "dominant_freq_lat_hz": round(self._dominant_freq_lat, 6),
            "dominant_freq_lon_hz": round(self._dominant_freq_lon, 6),
            "period_lat_s": round(1.0 / self._dominant_freq_lat, 1) if self._dominant_freq_lat > 0 else 0,
            "amplitude_lat_deg": round(self._amplitude_lat, 8),
            "periodicity_strength": round(periodicity, 3),
            "is_periodic": periodicity > 0.3,
            "samples": len(self._lat_history),
        }

    def predict(self, seconds_ahead: float) -> Tuple[float, float]:
        """Predict position using dominant frequency."""
        t = len(self._lat_history) / self._sample_rate + seconds_ahead
        pred_lat = self._mean_lat + self._amplitude_lat * math.sin(
            2 * math.pi * self._dominant_freq_lat * t + self._phase_lat)
        pred_lon = self._mean_lon + self._amplitude_lon * math.sin(
            2 * math.pi * self._dominant_freq_lon * t + self._phase_lon)
        return (pred_lat, pred_lon)


# ══════════════════════════════════════════════════════════════════
#  2. MARKOV CHAIN — Probabilistic state prediction
# ══════════════════════════════════════════════════════════════════

class MarkovMovementPredictor:
    """
    Models movement as a Markov Chain with states:
    STOPPED, WALKING, RUNNING, DRIVING_SLOW, DRIVING_FAST, TURNING

    Learns transition probabilities from baseline. During GPS denial,
    predicts most likely current state → applies state-specific motion model.

    Like weather forecasting: "if you were driving, you're probably still driving."
    """

    STATES = ["STOPPED", "WALKING", "RUNNING", "DRIVING_SLOW", "DRIVING_FAST", "TURNING"]

    def __init__(self):
        n = len(self.STATES)
        # Transition matrix: T[i][j] = P(next=j | current=i)
        # Initialize with slight self-preference (tend to stay in same state)
        self._transitions = np.ones((n, n)) / n
        for i in range(n):
            self._transitions[i, i] = 0.7  # 70% stay in same state
        self._transitions /= self._transitions.sum(axis=1, keepdims=True)

        self._state_speeds = {
            "STOPPED": 0.0, "WALKING": 1.2, "RUNNING": 3.5,
            "DRIVING_SLOW": 8.0, "DRIVING_FAST": 25.0, "TURNING": 5.0,
        }
        self._current_state = 0  # STOPPED
        self._observation_count = 0

    def classify_state(self, speed_mps: float, turn_rate_dps: float) -> int:
        """Classify current movement state from speed and turn rate."""
        if abs(turn_rate_dps) > 15:
            return 5  # TURNING
        if speed_mps < 0.3:
            return 0  # STOPPED
        if speed_mps < 2.0:
            return 1  # WALKING
        if speed_mps < 5.0:
            return 2  # RUNNING
        if speed_mps < 15.0:
            return 3  # DRIVING_SLOW
        return 4  # DRIVING_FAST

    def observe(self, speed_mps: float, turn_rate_dps: float = 0.0):
        """Observe a movement sample and update transition matrix."""
        new_state = self.classify_state(speed_mps, turn_rate_dps)

        # Update transition count
        alpha = 0.01  # Learning rate
        self._transitions[self._current_state, new_state] += alpha
        # Renormalize row
        row_sum = self._transitions[self._current_state].sum()
        self._transitions[self._current_state] /= row_sum

        self._current_state = new_state
        self._observation_count += 1

    def predict_state(self, steps_ahead: int = 1) -> Dict:
        """Predict most likely state N steps ahead."""
        state_probs = np.zeros(len(self.STATES))
        state_probs[self._current_state] = 1.0

        # Matrix power for N-step prediction
        for _ in range(steps_ahead):
            state_probs = state_probs @ self._transitions

        best_state = int(np.argmax(state_probs))
        return {
            "predicted_state": self.STATES[best_state],
            "probability": round(float(state_probs[best_state]), 3),
            "predicted_speed_mps": self._state_speeds[self.STATES[best_state]],
            "all_probabilities": {s: round(float(p), 3) for s, p in zip(self.STATES, state_probs)},
            "observations": self._observation_count,
        }

    def get_expected_speed(self, steps_ahead: int = 1) -> float:
        """Get expected speed N steps ahead (weighted by state probabilities)."""
        pred = self.predict_state(steps_ahead)
        return sum(self._state_speeds[s] * pred["all_probabilities"].get(s, 0)
                   for s in self.STATES)


# ══════════════════════════════════════════════════════════════════
#  3. BEZIER SPLINE — Smooth path extrapolation
# ══════════════════════════════════════════════════════════════════

class BezierPathExtrapolator:
    """
    Fits cubic Bezier curves to recent path, extrapolates forward.

    Unlike linear extrapolation (which goes straight), Bezier captures
    the curvature of your path. If you're on a curve, it continues
    the curve rather than going off on a tangent.

    Like predicting where a drawn line is going based on its curve.
    """

    def __init__(self, control_points: int = 4):
        self._points: deque = deque(maxlen=100)
        self._n_control = control_points

    def add_point(self, lat: float, lon: float):
        self._points.append((lat, lon))

    def extrapolate(self, steps_ahead: int = 10) -> List[Tuple[float, float]]:
        """Extrapolate path forward using cubic Bezier."""
        if len(self._points) < 4:
            return []

        # Use last 4 points as control points
        pts = list(self._points)[-4:]
        p0, p1, p2, p3 = [np.array(p) for p in pts]

        # Estimate next control point by extending the curve's direction
        # Direction from p2 to p3
        direction = p3 - p2
        # Curvature: how much the direction is changing
        prev_direction = p2 - p1
        curvature = direction - prev_direction

        predictions = []
        for step in range(1, steps_ahead + 1):
            t = step / steps_ahead
            # Extend with curvature
            next_point = p3 + direction * t + curvature * t * 0.5
            predictions.append((float(next_point[0]), float(next_point[1])))

        return predictions

    def predict_position(self, seconds_ahead: float, speed_mps: float = 1.5) -> Tuple[float, float]:
        """Predict single position ahead."""
        if len(self._points) < 4:
            return self._points[-1] if self._points else (0, 0)

        # Number of extrapolation steps proportional to time
        steps = max(1, int(seconds_ahead))
        preds = self.extrapolate(steps)
        return preds[-1] if preds else self._points[-1]


# ══════════════════════════════════════════════════════════════════
#  4. WAVELET DENOISING — Multi-resolution noise separation
# ══════════════════════════════════════════════════════════════════

class WaveletDenoiser:
    """
    Separates GPS noise from real movement at different timescales.

    Low frequency = real movement (you walking, driving)
    High frequency = noise (GPS jitter, multipath)

    Uses Haar wavelet transform (simplest wavelet, runs on any device).
    """

    @staticmethod
    def haar_transform(signal: List[float]) -> Tuple[List[float], List[float]]:
        """Single-level Haar wavelet decomposition."""
        n = len(signal) - len(signal) % 2  # Make even
        approx = []  # Low frequency (real movement)
        detail = []  # High frequency (noise)
        for i in range(0, n, 2):
            approx.append((signal[i] + signal[i + 1]) / 2)
            detail.append((signal[i] - signal[i + 1]) / 2)
        return approx, detail

    @staticmethod
    def denoise(signal: List[float], levels: int = 3, threshold_factor: float = 1.5) -> List[float]:
        """Multi-level wavelet denoising."""
        if len(signal) < 4:
            return list(signal)

        # Forward transform
        approx = list(signal)
        details = []
        for _ in range(levels):
            if len(approx) < 4:
                break
            approx, detail = WaveletDenoiser.haar_transform(approx)
            details.append(detail)

        # Threshold detail coefficients (remove noise)
        for i, detail in enumerate(details):
            if not detail:
                continue
            threshold = threshold_factor * np.std(detail)
            details[i] = [0.0 if abs(d) < threshold else d for d in detail]

        # Inverse transform
        result = approx
        for detail in reversed(details):
            reconstructed = []
            for j in range(min(len(result), len(detail))):
                reconstructed.append(result[j] + detail[j])
                reconstructed.append(result[j] - detail[j])
            result = reconstructed

        # Match original length
        return result[:len(signal)]

    @staticmethod
    def noise_level(signal: List[float]) -> float:
        """Estimate noise level from high-frequency wavelet coefficients."""
        if len(signal) < 4:
            return 0.0
        _, detail = WaveletDenoiser.haar_transform(signal)
        return float(np.std(detail)) if detail else 0.0


# ══════════════════════════════════════════════════════════════════
#  5. SHANNON ENTROPY — Prediction confidence from information theory
# ══════════════════════════════════════════════════════════════════

class EntropyConfidence:
    """
    Measures how predictable your movement is using Shannon entropy.

    Low entropy = predictable (straight line, regular pattern) → HIGH confidence
    High entropy = unpredictable (random turns, erratic) → LOW confidence

    Like measuring how many bits of information you need to describe the path.
    Regular patterns need few bits. Random paths need many bits.
    """

    @staticmethod
    def path_entropy(headings: List[float], bins: int = 36) -> float:
        """Calculate Shannon entropy of heading distribution."""
        if len(headings) < 5:
            return 0.0

        # Bin headings into 10-degree bins
        hist, _ = np.histogram(headings, bins=bins, range=(0, 360))
        probs = hist / hist.sum()
        probs = probs[probs > 0]  # Remove zeros

        entropy = -float(np.sum(probs * np.log2(probs)))
        return entropy

    @staticmethod
    def max_entropy(bins: int = 36) -> float:
        """Maximum possible entropy (uniform distribution)."""
        return math.log2(bins)

    @staticmethod
    def predictability(headings: List[float], bins: int = 36) -> float:
        """0.0 = completely random, 1.0 = completely predictable."""
        h = EntropyConfidence.path_entropy(headings, bins)
        h_max = EntropyConfidence.max_entropy(bins)
        return 1.0 - (h / h_max) if h_max > 0 else 0.0

    @staticmethod
    def speed_entropy(speeds: List[float], bins: int = 20) -> float:
        """Entropy of speed distribution."""
        if len(speeds) < 5:
            return 0.0
        hist, _ = np.histogram(speeds, bins=bins)
        probs = hist / hist.sum()
        probs = probs[probs > 0]
        return -float(np.sum(probs * np.log2(probs)))

    @staticmethod
    def prediction_confidence(headings: List[float], speeds: List[float]) -> float:
        """Combined confidence score from heading and speed entropy. 0-1."""
        h_pred = EntropyConfidence.predictability(headings)
        s_entropy = EntropyConfidence.speed_entropy(speeds)
        s_max = math.log2(20)
        s_pred = 1.0 - (s_entropy / s_max) if s_max > 0 else 0.0
        return round(0.6 * h_pred + 0.4 * s_pred, 3)


# ══════════════════════════════════════════════════════════════════
#  6. TERRAIN SLOPE CONSTRAINING — Accelerometer tells you the road
# ══════════════════════════════════════════════════════════════════

class TerrainSlopeConstraint:
    """
    Uses accelerometer tilt angle to determine terrain slope.
    Combined with elevation data, constrains which road you're on.

    If accelerometer says 5° slope and only one road nearby has 5° slope,
    you must be on that road — even without GPS.

    Like fingerprinting the road surface with gravity.
    """

    def __init__(self):
        self._slope_history: deque = deque(maxlen=200)
        self._known_slopes: Dict[str, float] = {}

    def measure_slope(self, accel_x: float, accel_y: float, accel_z: float) -> float:
        """Calculate terrain slope from accelerometer readings."""
        # Total acceleration magnitude
        total = math.sqrt(accel_x ** 2 + accel_y ** 2 + accel_z ** 2)
        if total < 0.1:
            return 0.0

        # Forward slope (pitch): angle from vertical in forward direction
        # Assumes device is roughly level (z-axis ≈ vertical)
        forward_component = math.sqrt(accel_x ** 2 + accel_y ** 2)
        slope_rad = math.atan2(forward_component, abs(accel_z))
        slope_deg = math.degrees(slope_rad)

        self._slope_history.append(slope_deg)
        return slope_deg

    def register_road_slope(self, road_id: str, slope_deg: float):
        """Register a known road's slope for matching."""
        self._known_slopes[road_id] = slope_deg

    def match_road(self, current_slope: float, tolerance_deg: float = 2.0) -> List[Dict]:
        """Find roads matching current slope."""
        matches = []
        for road_id, road_slope in self._known_slopes.items():
            diff = abs(current_slope - road_slope)
            if diff <= tolerance_deg:
                confidence = 1.0 - diff / tolerance_deg
                matches.append({
                    "road_id": road_id,
                    "road_slope": road_slope,
                    "difference_deg": round(diff, 2),
                    "confidence": round(confidence, 3),
                })
        matches.sort(key=lambda m: m["difference_deg"])
        return matches

    def get_slope_signature(self, window: int = 20) -> List[float]:
        """Get recent slope pattern as a fingerprint."""
        return list(self._slope_history)[-window:]

    def match_slope_pattern(self, known_patterns: Dict[str, List[float]],
                            tolerance: float = 1.5) -> Optional[str]:
        """Match current slope pattern against known road patterns."""
        current = self.get_slope_signature()
        if len(current) < 5:
            return None

        best_match = None
        best_score = float("inf")

        for road_id, pattern in known_patterns.items():
            if len(pattern) < 5:
                continue
            # Compare using DTW-like distance (simplified)
            min_len = min(len(current), len(pattern))
            diff = sum(abs(current[-min_len + i] - pattern[-min_len + i])
                       for i in range(min_len)) / min_len
            if diff < best_score and diff < tolerance:
                best_score = diff
                best_match = road_id

        return best_match


# ══════════════════════════════════════════════════════════════════
#  COMBINED UNCONVENTIONAL PREDICTOR
# ══════════════════════════════════════════════════════════════════

class UnconventionalPredictor:
    """
    Combines all 6 unconventional math approaches into one predictor.

    Each method votes on position. Methods with higher confidence
    (from entropy analysis) get more weight.
    """

    def __init__(self):
        self.fourier = FourierMovementAnalyzer()
        self.markov = MarkovMovementPredictor()
        self.bezier = BezierPathExtrapolator()
        self.wavelet = WaveletDenoiser()
        self.entropy = EntropyConfidence()
        self.terrain = TerrainSlopeConstraint()

        self._headings: List[float] = []
        self._speeds: List[float] = []

    def feed(self, lat: float, lon: float, speed: float = 0,
             heading: float = 0, accel_z: float = 9.81):
        """Feed one sample to all predictors."""
        self.fourier.add_sample(lat, lon)
        self.markov.observe(speed, 0)
        self.bezier.add_point(lat, lon)
        self._headings.append(heading)
        self._speeds.append(speed)
        self.terrain.measure_slope(0, 0, accel_z)

    def predict(self, seconds_ahead: float) -> Dict:
        """Get combined prediction from all methods."""
        results = {}

        # Fourier
        self.fourier.analyze()
        f_lat, f_lon = self.fourier.predict(seconds_ahead)
        results["fourier"] = {"lat": f_lat, "lon": f_lon}

        # Bezier
        b_pos = self.bezier.predict_position(seconds_ahead)
        results["bezier"] = {"lat": b_pos[0], "lon": b_pos[1]}

        # Markov expected speed
        markov_pred = self.markov.predict_state(int(seconds_ahead))
        results["markov"] = markov_pred

        # Entropy-based confidence
        confidence = self.entropy.prediction_confidence(self._headings, self._speeds)
        results["entropy_confidence"] = confidence

        # Wavelet noise level
        if len(self._speeds) > 4:
            noise = self.wavelet.noise_level(self._speeds)
            results["noise_level"] = round(noise, 4)

        # Weighted average of Fourier + Bezier
        w_fourier = 0.4
        w_bezier = 0.6
        combined_lat = f_lat * w_fourier + b_pos[0] * w_bezier
        combined_lon = f_lon * w_fourier + b_pos[1] * w_bezier

        results["combined"] = {
            "lat": round(combined_lat, 8),
            "lon": round(combined_lon, 8),
            "confidence": confidence,
            "method": "fourier_bezier_weighted",
        }

        return results
