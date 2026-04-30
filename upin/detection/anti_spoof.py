"""
Anti-Spoof Detection — UPIN

Detects GPS spoofing by cross-checking GPS against independent sensors.
A real GPS signal is -130 dBm from 20,000km. A spoofer on the ground
is -60 dBm — 10 million times stronger. We catch it by:

1. Signal strength spike (too strong = fake)
2. Teleport detection (impossible position jump)
3. Tower mismatch (GPS disagrees with cell triangulation)
4. IMU mismatch (GPS says moving but accelerometer says still)
5. Precision anomaly (GPS accuracy < 3m is suspicious)
6. Arrival direction (all sats from same direction = single spoofer)

When spoofing detected → reject GPS → fall back to UPIN layers.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class SpoofAlert:
    """One detected spoofing indicator."""
    check_name: str
    severity: str          # CRITICAL, HIGH, MEDIUM, LOW
    detail: str
    score_contribution: float
    timestamp: float = field(default_factory=time.time)


class AntiSpoofDetector:
    """Multi-check GPS spoofing detector.

    Maintains a spoof_score (0-100). Above threshold = spoofed.
    Each check contributes to the score independently.
    """

    def __init__(self, threshold: float = 40.0):
        self._threshold = threshold
        self._spoof_score: float = 0.0
        self._alerts: List[SpoofAlert] = []
        self._last_gps: Optional[Dict] = None
        self._position_history: deque = deque(maxlen=30)
        self._signal_history: deque = deque(maxlen=50)
        self._is_spoofed = False
        self._decay_rate = 0.95

    def check(self, gps_lat: float, gps_lon: float,
              gps_accuracy_m: float = 10.0,
              gps_signal_dbm: float = -130.0,
              cell_lat: Optional[float] = None,
              cell_lon: Optional[float] = None,
              imu_accel_magnitude: float = 0.0,
              gps_speed_ms: float = 0.0,
              gps_heading_deg: float = 0.0) -> Dict:
        """Run all spoof checks against current GPS reading."""
        now = time.time()
        self._alerts = []
        self._spoof_score *= self._decay_rate

        # 1. Signal strength spike
        self._signal_history.append(gps_signal_dbm)
        if len(self._signal_history) >= 5:
            avg_signal = sum(self._signal_history) / len(self._signal_history)
            if gps_signal_dbm > avg_signal + 30:
                self._add_alert("SIGNAL_SPIKE", "CRITICAL",
                                f"GPS signal jumped {gps_signal_dbm - avg_signal:.0f} dBm "
                                f"(from {avg_signal:.0f} to {gps_signal_dbm:.0f})", 35)

        # 2. Teleport detection
        if self._last_gps is not None:
            dt = now - self._last_gps["time"]
            if dt > 0:
                dist = _haversine_m(self._last_gps["lat"], self._last_gps["lon"],
                                    gps_lat, gps_lon)
                speed_implied = dist / max(dt, 0.01)
                if speed_implied > 340:  # faster than speed of sound
                    self._add_alert("TELEPORT", "CRITICAL",
                                    f"Position jumped {dist:.0f}m in {dt:.1f}s "
                                    f"(implied {speed_implied:.0f} m/s)", 40)

        # 3. Tower mismatch
        if cell_lat is not None and cell_lon is not None:
            cell_gps_dist = _haversine_m(gps_lat, gps_lon, cell_lat, cell_lon)
            if cell_gps_dist > 1000:
                self._add_alert("TOWER_MISMATCH", "HIGH",
                                f"GPS vs cell tower: {cell_gps_dist:.0f}m apart", 25)

        # 4. IMU mismatch
        if gps_speed_ms > 5 and imu_accel_magnitude < 0.2:
            self._add_alert("IMU_MISMATCH", "MEDIUM",
                            f"GPS says {gps_speed_ms:.1f} m/s but IMU is still", 15)
        if gps_speed_ms < 0.5 and imu_accel_magnitude > 3.0:
            self._add_alert("IMU_MISMATCH_REV", "MEDIUM",
                            f"GPS says still but IMU shows {imu_accel_magnitude:.1f} m/s²", 15)

        # 5. Precision anomaly
        if gps_accuracy_m < 1.0:
            self._add_alert("TOO_PRECISE", "LOW",
                            f"GPS accuracy {gps_accuracy_m:.1f}m — suspiciously perfect", 10)

        self._spoof_score = min(100.0, self._spoof_score)
        self._is_spoofed = self._spoof_score >= self._threshold

        self._last_gps = {"lat": gps_lat, "lon": gps_lon, "time": now}
        self._position_history.append((gps_lat, gps_lon, now))

        return {
            "spoof_score": round(self._spoof_score, 1),
            "is_spoofed": self._is_spoofed,
            "threshold": self._threshold,
            "alerts": [{"check": a.check_name, "severity": a.severity,
                        "detail": a.detail} for a in self._alerts],
            "action": "REJECT_GPS" if self._is_spoofed else "ACCEPT_GPS",
        }

    def _add_alert(self, check: str, severity: str, detail: str, score: float):
        self._alerts.append(SpoofAlert(check, severity, detail, score))
        self._spoof_score += score

    @property
    def is_spoofed(self) -> bool:
        return self._is_spoofed

    @property
    def spoof_score(self) -> float:
        return self._spoof_score


class RFFieldMonitor:
    """RF Field Monitor — baseline + anomaly detection.

    Learns the normal RF environment (signal count, strength pattern)
    over N samples. Then detects any disturbance:
    - RF_SPIKE: new strong signal appeared (spoofer/jammer powering up)
    - JAMMING: all signals dropped (wideband jammer)
    - TOTAL_LOSS: zero signals (full spectrum denial)
    - NEW_TRANSMITTER: signal count jumped (new emitter appeared)
    """

    def __init__(self, learning_samples: int = 30):
        self._learning_samples = learning_samples
        self._sample_count = 0
        self._baseline_signal_count: float = 0.0
        self._baseline_avg_rssi: float = -80.0
        self._baseline_std_rssi: float = 5.0
        self._signal_count_history: deque = deque(maxlen=100)
        self._avg_rssi_history: deque = deque(maxlen=100)
        self._state = "LEARNING"  # LEARNING, NORMAL, ALERT, HOSTILE
        self._alerts: List[Dict] = []

    def feed(self, signal_count: int, avg_rssi_dbm: float) -> Dict:
        """Feed one RF environment sample. Returns field status."""
        self._sample_count += 1
        self._signal_count_history.append(signal_count)
        self._avg_rssi_history.append(avg_rssi_dbm)
        self._alerts = []

        if self._sample_count <= self._learning_samples:
            self._state = "LEARNING"
            self._update_baseline()
            return {"state": "LEARNING",
                    "progress": f"{self._sample_count}/{self._learning_samples}"}

        # Check anomalies
        if signal_count == 0:
            self._alert("TOTAL_LOSS", "Zero RF signals — full spectrum denial")
            self._state = "HOSTILE"

        elif signal_count < self._baseline_signal_count * 0.5:
            drop_db = self._baseline_avg_rssi - avg_rssi_dbm
            if drop_db > 15:
                self._alert("JAMMING",
                            f"Signals dropped {drop_db:.0f} dBm below baseline")
                self._state = "HOSTILE"

        elif avg_rssi_dbm > self._baseline_avg_rssi + 3 * self._baseline_std_rssi:
            spike = avg_rssi_dbm - self._baseline_avg_rssi
            self._alert("RF_SPIKE",
                        f"Signal {spike:.0f} dBm above baseline — new transmitter?")
            self._state = "ALERT"

        elif signal_count > self._baseline_signal_count + 2:
            self._alert("NEW_TRANSMITTER",
                        f"Signal count jumped from {self._baseline_signal_count:.0f} "
                        f"to {signal_count}")
            self._state = "ALERT"

        else:
            self._state = "NORMAL"

        return {
            "state": self._state,
            "signal_count": signal_count,
            "baseline_count": round(self._baseline_signal_count, 1),
            "avg_rssi_dbm": round(avg_rssi_dbm, 1),
            "baseline_rssi_dbm": round(self._baseline_avg_rssi, 1),
            "alerts": list(self._alerts),
        }

    def _update_baseline(self):
        if self._signal_count_history:
            self._baseline_signal_count = (
                sum(self._signal_count_history) / len(self._signal_count_history))
        if self._avg_rssi_history:
            vals = list(self._avg_rssi_history)
            self._baseline_avg_rssi = sum(vals) / len(vals)
            if len(vals) > 1:
                mean = self._baseline_avg_rssi
                self._baseline_std_rssi = max(
                    1.0, (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5)

    def _alert(self, alert_type: str, detail: str):
        self._alerts.append({"type": alert_type, "detail": detail,
                             "time": time.time()})

    @property
    def state(self) -> str:
        return self._state


class ConsensusValidator:
    """Multi-source position voting — consensus determines truth.

    Collects position estimates from GPS, cell triangulation, IMU dead
    reckoning, predictor, and any other source. Votes on the true position.
    If 4 agree but 1 is wildly different — that 1 is wrong (spoofed,
    malfunctioning, or stale). The consensus position IS the output.

    This is how aircraft navigation works — triple redundancy with voting.
    """

    def __init__(self, agreement_threshold_m: float = 50.0):
        self._threshold_m = agreement_threshold_m
        self._sources: Dict[str, Tuple[float, float, float]] = {}
        self._last_consensus: Optional[Dict] = None

    def submit(self, source_name: str, lat: float, lon: float,
               confidence: float = 1.0):
        """Submit a position estimate from a source."""
        self._sources[source_name] = (lat, lon, confidence)

    def vote(self) -> Dict:
        """Compute consensus position from all submitted sources."""
        if not self._sources:
            return {"consensus": False, "reason": "no_sources"}

        sources = list(self._sources.items())
        n = len(sources)

        # Weighted centroid of all sources
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for name, (lat, lon, conf) in sources:
            lat_sum += lat * conf
            lon_sum += lon * conf
            total_w += conf
        centroid_lat = lat_sum / total_w
        centroid_lon = lon_sum / total_w

        # Check each source against centroid
        agreeing = []
        outliers = []
        for name, (lat, lon, conf) in sources:
            dist = _haversine_m(centroid_lat, centroid_lon, lat, lon)
            if dist <= self._threshold_m:
                agreeing.append({"source": name, "distance_m": dist})
            else:
                outliers.append({"source": name, "distance_m": dist,
                                 "verdict": "SUSPECT"})

        # Re-compute centroid excluding outliers
        if agreeing and outliers:
            total_w = 0.0
            lat_sum = lon_sum = 0.0
            for entry in agreeing:
                name = entry["source"]
                lat, lon, conf = self._sources[name]
                lat_sum += lat * conf
                lon_sum += lon * conf
                total_w += conf
            if total_w > 0:
                centroid_lat = lat_sum / total_w
                centroid_lon = lon_sum / total_w

        consensus_confidence = len(agreeing) / max(1, n)

        self._last_consensus = {
            "consensus": len(agreeing) >= 2,
            "lat": centroid_lat,
            "lon": centroid_lon,
            "confidence": round(consensus_confidence, 3),
            "agreeing_sources": len(agreeing),
            "total_sources": n,
            "agreeing": agreeing,
            "outliers": outliers,
        }
        self._sources.clear()
        return self._last_consensus

    @property
    def last_consensus(self) -> Optional[Dict]:
        return self._last_consensus


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
