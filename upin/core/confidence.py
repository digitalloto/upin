"""
UPIN Confidence Scoring System.

Novel contribution per patent Section 6.3:
C = (Sum of W_i * R_i for agreeing layers) / (Sum of W_i * R_i for all active layers) * 100

The confidence score tells the operator HOW MUCH to trust the current
position output — something no prior art system provides.

Trust levels:
    95-100%  = 10+ layers agree    -> FULL TRUST
    80-94%   = 7-9 layers agree    -> HIGH ACCURACY
    60-79%   = 4-6 layers agree    -> VERIFY
    40-59%   = 2-3 layers agree    -> SEEK CONFIRMATION
    Below 40%= Attack/failure      -> IMMEDIATE ALERT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class LayerAgreement:
    """Result of checking whether a layer agrees with consensus."""
    layer_id: str
    agrees: bool
    deviation_m: float  # Distance from consensus position in metres
    weight: float
    reliability: float
    accuracy_rating: float


@dataclass
class ConfidenceResult:
    """Full confidence analysis output."""
    score: float  # 0.0 to 100.0
    num_agreeing: int
    num_active: int
    trust_level: str
    layer_agreements: list[LayerAgreement] = field(default_factory=list)
    outlier_layer_ids: list[str] = field(default_factory=list)
    spoofing_suspected: bool = False
    jamming_suspected: bool = False


class ConfidenceScorer:
    """Implements the UPIN confidence scoring algorithm.

    The scorer analyses agreement between all active layers, identifies
    outliers, and produces a confidence percentage that represents
    how much the operator should trust the current position.
    """

    def __init__(
        self,
        agreement_threshold_m: float = 50.0,
        min_layers_for_full_trust: int = 10,
        spoofing_detection_enabled: bool = True,
    ):
        self.agreement_threshold_m = agreement_threshold_m
        self.min_layers_for_full_trust = min_layers_for_full_trust
        self.spoofing_detection_enabled = spoofing_detection_enabled
        self._historical_scores: list[float] = []
        self._drift_baseline: Optional[float] = None

    def compute(
        self,
        layer_positions: list[dict],
        consensus_position: tuple[float, float, float],
    ) -> ConfidenceResult:
        """Compute confidence score from layer positions vs consensus.

        Args:
            layer_positions: List of dicts with keys:
                - layer_id: str
                - position: (lat, lon, alt) tuple
                - weight: float (W_i)
                - reliability: float (R_i)
                - accuracy_rating: float
            consensus_position: The fused (lat, lon, alt) from the EKF.

        Returns:
            ConfidenceResult with score and diagnostics.
        """
        if not layer_positions:
            return ConfidenceResult(
                score=0.0, num_agreeing=0, num_active=0,
                trust_level="IMMEDIATE ALERT",
            )

        agreements = []
        total_weighted = 0.0
        agreeing_weighted = 0.0
        outliers = []

        for lp in layer_positions:
            deviation = self._position_deviation_m(
                lp["position"], consensus_position
            )
            agrees = deviation <= self.agreement_threshold_m
            w_i = lp["weight"]
            r_i = lp["reliability"]
            wr = w_i * r_i

            total_weighted += wr
            if agrees:
                agreeing_weighted += wr
            else:
                outliers.append(lp["layer_id"])

            agreements.append(LayerAgreement(
                layer_id=lp["layer_id"],
                agrees=agrees,
                deviation_m=deviation,
                weight=w_i,
                reliability=r_i,
                accuracy_rating=lp.get("accuracy_rating", 1.0),
            ))

        # Core formula: C = (Sum W_i*R_i agreeing) / (Sum W_i*R_i all) * 100
        if total_weighted > 0:
            score = (agreeing_weighted / total_weighted) * 100.0
        else:
            score = 0.0

        num_agreeing = sum(1 for a in agreements if a.agrees)
        num_active = len(agreements)

        # Detect spoofing: if a high-weight layer (GPS) disagrees with
        # many other layers, that's a spoofing indicator
        spoofing = False
        jamming = False
        if self.spoofing_detection_enabled:
            spoofing, jamming = self._detect_anomalies(
                agreements, outliers, num_agreeing
            )

        trust_level = self._classify_trust(score, num_agreeing)

        # Track for drift detection
        self._historical_scores.append(score)
        if len(self._historical_scores) > 1000:
            self._historical_scores = self._historical_scores[-500:]

        return ConfidenceResult(
            score=round(score, 2),
            num_agreeing=num_agreeing,
            num_active=num_active,
            trust_level=trust_level,
            layer_agreements=agreements,
            outlier_layer_ids=outliers,
            spoofing_suspected=spoofing,
            jamming_suspected=jamming,
        )

    def _position_deviation_m(
        self,
        pos: tuple[float, float, float],
        consensus: tuple[float, float, float],
    ) -> float:
        """Calculate deviation between a position and consensus in metres."""
        # Haversine for horizontal, direct for vertical
        lat1, lon1, alt1 = np.radians(pos[0]), np.radians(pos[1]), pos[2]
        lat2, lon2, alt2 = (np.radians(consensus[0]),
                            np.radians(consensus[1]), consensus[2])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (np.sin(dlat / 2) ** 2 +
             np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2)
        horizontal = 6_371_000 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        vertical = abs(alt2 - alt1)
        return float(np.sqrt(horizontal ** 2 + vertical ** 2))

    def _detect_anomalies(
        self,
        agreements: list[LayerAgreement],
        outliers: list[str],
        num_agreeing: int,
    ) -> tuple[bool, bool]:
        """Detect spoofing and jamming from agreement patterns.

        Spoofing: A satellite layer disagrees with consensus of many
        other layers — the spoofed signal can't fool all physical principles.

        Jamming: Satellite layers report no signal / invalid readings
        while non-satellite layers continue to function.
        """
        spoofing = False
        jamming = False

        satellite_layer_prefixes = ("gps", "navic", "leo", "gnss")
        satellite_outliers = [
            o for o in outliers
            if any(o.lower().startswith(p) for p in satellite_layer_prefixes)
        ]

        # If satellite layers disagree but 5+ other layers agree, likely spoofing
        if satellite_outliers and num_agreeing >= 5:
            spoofing = True

        # Jamming: check for sudden confidence drop
        if len(self._historical_scores) >= 10:
            recent = self._historical_scores[-10:]
            older = self._historical_scores[-20:-10] if len(
                self._historical_scores) >= 20 else recent
            drop = np.mean(older) - np.mean(recent)
            if drop > 20:  # 20-point sudden drop
                jamming = True

        return spoofing, jamming

    def _classify_trust(self, score: float, num_agreeing: int) -> str:
        """Classify the trust level from score and layer count."""
        if score >= 95 and num_agreeing >= self.min_layers_for_full_trust:
            return "FULL TRUST"
        elif score >= 80:
            return "HIGH ACCURACY"
        elif score >= 60:
            return "VERIFY"
        elif score >= 40:
            return "SEEK CONFIRMATION"
        else:
            return "IMMEDIATE ALERT"

    def get_score_trend(self, window: int = 50) -> str:
        """Get trend of confidence scores over recent history."""
        if len(self._historical_scores) < window:
            return "INSUFFICIENT DATA"
        recent = self._historical_scores[-window:]
        half = window // 2
        first_half = np.mean(recent[:half])
        second_half = np.mean(recent[half:])
        diff = second_half - first_half
        if diff > 5:
            return "IMPROVING"
        elif diff < -5:
            return "DEGRADING"
        return "STABLE"
