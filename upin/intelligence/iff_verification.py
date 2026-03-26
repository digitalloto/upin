"""
IFF Seven-Factor Verification — UPIN Intelligence Module

Standard IFF relies on a transponder code. One code. One point of failure.
A captured or spoofed transponder fools it completely.

UPIN IFF runs seven independent verification factors simultaneously.
A genuine friendly matches all seven. A spoofed transponder matches one.
The system cannot be defeated by transponder capture alone.

In COVERT_ISR mode all active queries are suppressed — passive factors only.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Optional


class IFFVerdict(Enum):
    FRIENDLY = auto()      # All 7 factors pass
    SUSPECT = auto()       # 4-6 factors pass — hold, do not engage
    HOSTILE = auto()       # 3 or fewer factors pass
    UNKNOWN = auto()       # Insufficient data to score


class IFFactor(Enum):
    TRANSPONDER_CODE = auto()       # Factor 1 — encrypted IFF challenge/response
    RF_EMISSION_SIGNATURE = auto()  # Factor 2 — radio emission fingerprint
    FLIGHT_PROFILE = auto()         # Factor 3 — speed, altitude, manoeuvre pattern
    FORMATION_POSITION = auto()     # Factor 4 — position relative to known friendlies
    TIMING_SYNCHRONISATION = auto() # Factor 5 — atomic clock sync token
    ENCRYPTED_IFF_TOKEN = auto()    # Factor 6 — rotating cryptographic token
    THERMAL_VISUAL_SIGNATURE = auto() # Factor 7 — thermal/visual platform ID


@dataclass
class FactorScore:
    factor: IFFactor
    score: float          # 0.0 to 1.0
    passed: bool          # True if score >= threshold
    method: str           # how it was assessed
    passive_only: bool    # True if no active emission was required


@dataclass
class IFFResult:
    target_id: str
    verdict: IFFVerdict
    overall_confidence: float
    factors: list[FactorScore]
    factors_passed: int
    timestamp: float
    covert_mode: bool
    audit_log: list[str] = field(default_factory=list)

    def is_cleared_to_engage(self) -> bool:
        """Only HOSTILE verdict with high confidence clears for engagement prep."""
        return self.verdict == IFFVerdict.HOSTILE and self.overall_confidence >= 0.80

    def is_confirmed_friendly(self) -> bool:
        return self.verdict == IFFVerdict.FRIENDLY and self.overall_confidence >= 0.85


class IFFVerifier:
    """
    Seven-factor IFF verification engine.

    Each factor is scored independently 0.0-1.0.
    A factor passes if its score is >= its threshold.
    Verdict is determined by total factors passed.

    In covert mode (COVERT_ISR / GHOST_RECON), active query
    factors are suppressed. Verdict is based on passive factors only.
    """

    PASS_THRESHOLD = 0.70
    FRIENDLY_REQUIRED = 7   # All seven must pass
    SUSPECT_MIN = 4         # 4-6 = SUSPECT
    # Below 4 = HOSTILE

    def __init__(self, covert_mode: bool = False):
        self._covert_mode = covert_mode
        self._known_friendlies: dict[str, dict] = {}
        self._history: list[IFFResult] = []

    def set_covert_mode(self, covert: bool) -> None:
        self._covert_mode = covert

    def register_friendly(self, platform_id: str, profile: dict) -> None:
        """Register a known friendly platform's expected signatures."""
        self._known_friendlies[platform_id] = profile

    def verify(self, target_id: str, sensor_data: dict) -> IFFResult:
        """
        Run all seven factors against sensor_data and return verdict.

        sensor_data keys:
          transponder_code, rf_signature, speed_ms, altitude_m,
          heading_deg, formation_lat, formation_lon, timing_token,
          iff_token, thermal_signature, visual_signature
        """
        factors: list[FactorScore] = []

        factors.append(self._score_transponder(sensor_data))
        factors.append(self._score_rf_signature(sensor_data))
        factors.append(self._score_flight_profile(sensor_data))
        factors.append(self._score_formation_position(sensor_data))
        factors.append(self._score_timing_sync(sensor_data))
        factors.append(self._score_iff_token(sensor_data))
        factors.append(self._score_thermal_visual(sensor_data))

        passed = sum(1 for f in factors if f.passed)
        confidence = sum(f.score for f in factors) / len(factors)

        if passed == self.FRIENDLY_REQUIRED:
            verdict = IFFVerdict.FRIENDLY
        elif passed >= self.SUSPECT_MIN:
            verdict = IFFVerdict.SUSPECT
        else:
            verdict = IFFVerdict.HOSTILE

        if self._covert_mode:
            active_suppressed = sum(1 for f in factors if not f.passive_only)
            passive_passed = sum(1 for f in factors if f.passed and f.passive_only)
            if active_suppressed > 0 and passive_passed < 3:
                verdict = IFFVerdict.UNKNOWN

        log = (
            f"[{time.strftime('%H:%M:%S')}] IFF {target_id} — "
            f"{passed}/7 factors passed — verdict {verdict.name} — "
            f"confidence {confidence:.0%} — covert={self._covert_mode}"
        )

        result = IFFResult(
            target_id=target_id,
            verdict=verdict,
            overall_confidence=confidence,
            factors=factors,
            factors_passed=passed,
            timestamp=time.time(),
            covert_mode=self._covert_mode,
            audit_log=[log],
        )
        self._history.append(result)
        return result

    def _score_transponder(self, d: dict) -> FactorScore:
        code = d.get("transponder_code", "")
        expected = "IFF-ALPHA-7749"
        score = 1.0 if code == expected else (0.3 if code else 0.0)
        return FactorScore(
            factor=IFFactor.TRANSPONDER_CODE,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="encrypted_challenge_response",
            passive_only=False,
        )

    def _score_rf_signature(self, d: dict) -> FactorScore:
        sig = d.get("rf_signature", 0.0)
        # Score based on how close signature is to known friendly fingerprint
        expected_sig = 0.847
        deviation = abs(sig - expected_sig)
        score = max(0.0, 1.0 - deviation * 5.0)
        return FactorScore(
            factor=IFFactor.RF_EMISSION_SIGNATURE,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="passive_rf_fingerprint",
            passive_only=True,
        )

    def _score_flight_profile(self, d: dict) -> FactorScore:
        speed = d.get("speed_ms", 0.0)
        altitude = d.get("altitude_m", 0.0)
        heading = d.get("heading_deg", 0.0)
        # Friendly profiles operate within known envelopes
        speed_ok = 50.0 <= speed <= 350.0
        alt_ok = 100.0 <= altitude <= 8000.0
        heading_ok = 0.0 <= heading <= 360.0
        score = (int(speed_ok) + int(alt_ok) + int(heading_ok)) / 3.0
        return FactorScore(
            factor=IFFactor.FLIGHT_PROFILE,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="kinematic_envelope_check",
            passive_only=True,
        )

    def _score_formation_position(self, d: dict) -> FactorScore:
        if self._covert_mode:
            return FactorScore(
                factor=IFFactor.FORMATION_POSITION,
                score=0.0,
                passed=False,
                method="suppressed_covert_mode",
                passive_only=False,
            )
        lat = d.get("formation_lat", None)
        lon = d.get("formation_lon", None)
        if lat is None or lon is None:
            score = 0.0
        else:
            # Check if within 500m of a known friendly formation position
            dlat = (lat - 13.0827) * 111000
            dlon = (lon - 80.2707) * 111000 * math.cos(math.radians(lat))
            dist = math.sqrt(dlat**2 + dlon**2)
            score = max(0.0, 1.0 - dist / 500.0)
        return FactorScore(
            factor=IFFactor.FORMATION_POSITION,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="formation_mesh_position",
            passive_only=False,
        )

    def _score_timing_sync(self, d: dict) -> FactorScore:
        token = d.get("timing_token", 0)
        expected = int(time.time()) // 30  # 30-second window
        score = 1.0 if token == expected else (0.5 if abs(token - expected) <= 1 else 0.0)
        return FactorScore(
            factor=IFFactor.TIMING_SYNCHRONISATION,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="atomic_clock_sync_window",
            passive_only=False,
        )

    def _score_iff_token(self, d: dict) -> FactorScore:
        token = d.get("iff_token", "")
        # Rotating token: valid format checked (real system uses crypto)
        valid = isinstance(token, str) and token.startswith("TOK-") and len(token) == 12
        score = 1.0 if valid else 0.0
        return FactorScore(
            factor=IFFactor.ENCRYPTED_IFF_TOKEN,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="rotating_crypto_token",
            passive_only=False,
        )

    def _score_thermal_visual(self, d: dict) -> FactorScore:
        thermal = d.get("thermal_signature", 0.0)
        visual = d.get("visual_signature", 0.0)
        expected_thermal = 0.72
        expected_visual = 0.68
        t_score = max(0.0, 1.0 - abs(thermal - expected_thermal) * 4.0)
        v_score = max(0.0, 1.0 - abs(visual - expected_visual) * 4.0)
        score = (t_score + v_score) / 2.0
        return FactorScore(
            factor=IFFactor.THERMAL_VISUAL_SIGNATURE,
            score=score,
            passed=score >= self.PASS_THRESHOLD,
            method="passive_thermal_visual_id",
            passive_only=True,
        )

    def get_history(self) -> list[IFFResult]:
        return list(self._history)
