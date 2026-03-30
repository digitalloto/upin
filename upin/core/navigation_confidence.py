"""
Navigation Confidence Framework — UPIN

Calculates navigation confidence, degradation rates, and operational
recommendations. The navigation equivalent of HAIL - instead of
engagement decisions, handles navigation degradation decisions.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from enum import auto, Enum
from typing import Dict, List, Tuple


class NavigationRecommendation(Enum):
    CONTINUE = auto()      # Continue mission - high confidence
    MONITOR = auto()       # Monitor closely - medium confidence
    RETURN = auto()        # Return to base recommended - low confidence
    HOLD = auto()          # Hold position - critical degradation


class NavigationConfidence:
    """
    Navigation confidence calculator and mission advisor.

    Provides real-time assessment of navigation reliability and
    recommendations for operational decisions based on active sensors
    and time since GPS loss.
    """

    def __init__(self):
        # Agent reliability weights (when functioning normally)
        self.agent_weights = {
            "gps": 0.45,
            "cellular": 0.20,
            "wifi": 0.15,
            "imu": 0.10,
            "barometric": 0.05,
            "magnetometer": 0.03,
            "visual": 0.02,
        }

        # Drift rates (meters per minute) for different sensor combinations
        self.drift_rates = {
            "imu_only": 8.0,
            "imu_barometric": 6.0,
            "imu_cellular": 2.0,
            "imu_cellular_wifi": 0.8,
            "imu_cellular_wifi_visual": 0.3,
        }

    def calculate_confidence(
        self,
        active_agents: List[str],
        agent_weights: Dict[str, float],
        time_since_gps_loss: float = 0.0,
    ) -> Tuple[float, float, float]:
        """
        Calculate navigation confidence score.

        Returns:
            confidence_score: 0-100% navigation confidence
            degradation_rate: % confidence loss per minute
            estimated_operational_minutes: minutes until confidence drops below 60%
        """
        # Base confidence from active agents
        base_confidence = 0.0
        for agent in active_agents:
            if agent in self.agent_weights:
                base_confidence += self.agent_weights[agent]

        # Apply GPS loss degradation if applicable
        if "gps" not in active_agents and time_since_gps_loss > 0:
            drift_penalty = min(0.4, time_since_gps_loss / 30.0)
            base_confidence -= drift_penalty

        confidence_score = max(0.0, min(100.0, base_confidence * 100))

        degradation_rate = self._calculate_degradation_rate(
            active_agents, time_since_gps_loss
        )

        if degradation_rate > 0 and confidence_score > 60:
            minutes_to_60_percent = (confidence_score - 60) / degradation_rate
            estimated_operational_minutes = max(0, minutes_to_60_percent)
        elif confidence_score <= 60:
            estimated_operational_minutes = 0.0
        else:
            estimated_operational_minutes = float("inf")

        return confidence_score, degradation_rate, estimated_operational_minutes

    def _calculate_degradation_rate(
        self, active_agents: List[str], time_since_gps_loss: float
    ) -> float:
        if "gps" in active_agents:
            return 0.1
        if "cellular" in active_agents and "wifi" in active_agents:
            return 0.5
        elif "cellular" in active_agents or "wifi" in active_agents:
            return 1.0
        else:
            return 2.0

    def estimate_drift_window(
        self, active_agents: List[str]
    ) -> Tuple[float, NavigationRecommendation]:
        """
        Estimate time until position error becomes operationally significant (>50m).

        Returns:
            minutes_remaining: Minutes until 50m position error
            recommendation: CONTINUE/MONITOR/HOLD/RETURN
        """
        sensor_combo = self._classify_sensor_combination(active_agents)
        drift_rate = self.drift_rates.get(sensor_combo, 10.0)

        minutes_to_50m = 50.0 / drift_rate

        if minutes_to_50m > 45:
            recommendation = NavigationRecommendation.CONTINUE
        elif minutes_to_50m > 15:
            recommendation = NavigationRecommendation.MONITOR
        elif minutes_to_50m > 5:
            recommendation = NavigationRecommendation.RETURN
        else:
            recommendation = NavigationRecommendation.HOLD

        return minutes_to_50m, recommendation

    def _classify_sensor_combination(self, active_agents: List[str]) -> str:
        has_cellular = "cellular" in active_agents
        has_wifi = "wifi" in active_agents
        has_visual = "visual" in active_agents

        if has_cellular and has_wifi and has_visual:
            return "imu_cellular_wifi_visual"
        elif has_cellular and has_wifi:
            return "imu_cellular_wifi"
        elif has_cellular:
            return "imu_cellular"
        elif "barometric" in active_agents:
            return "imu_barometric"
        else:
            return "imu_only"

    def recommend_action(
        self,
        confidence: float,
        minutes_remaining: float,
        mission_priority: str = "NORMAL",
    ) -> Tuple[NavigationRecommendation, str, Dict]:
        """Recommend operational action based on navigation confidence."""
        if mission_priority == "CRITICAL":
            continue_threshold, monitor_threshold, return_threshold = 70, 50, 30
        elif mission_priority == "HIGH":
            continue_threshold, monitor_threshold, return_threshold = 75, 60, 40
        else:
            continue_threshold, monitor_threshold, return_threshold = 80, 60, 40

        if confidence >= continue_threshold and minutes_remaining >= 30:
            action = NavigationRecommendation.CONTINUE
            reason = f"High confidence ({confidence:.0f}%) with {minutes_remaining:.0f}min remaining"
        elif confidence >= monitor_threshold or minutes_remaining >= 15:
            action = NavigationRecommendation.MONITOR
            reason = f"Medium confidence ({confidence:.0f}%) - monitor navigation closely"
        elif confidence >= return_threshold or minutes_remaining >= 5:
            action = NavigationRecommendation.RETURN
            reason = f"Low confidence ({confidence:.0f}%) - return to base recommended"
        else:
            action = NavigationRecommendation.HOLD
            reason = f"Critical degradation ({confidence:.0f}%) - hold position immediately"

        metadata = {
            "confidence_score": confidence,
            "time_remaining_minutes": minutes_remaining,
            "mission_priority": mission_priority,
            "threshold_used": {
                "continue": continue_threshold,
                "monitor": monitor_threshold,
                "return": return_threshold,
            },
        }

        return action, reason, metadata

    def get_confidence_summary(
        self,
        active_agents: List[str],
        time_since_gps_loss: float = 0.0,
        mission_priority: str = "NORMAL",
    ) -> Dict:
        """Get comprehensive navigation confidence assessment."""
        confidence, degradation_rate, operational_minutes = self.calculate_confidence(
            active_agents, self.agent_weights, time_since_gps_loss
        )

        drift_minutes, drift_recommendation = self.estimate_drift_window(active_agents)

        action, reason, metadata = self.recommend_action(
            confidence, min(operational_minutes, drift_minutes), mission_priority
        )

        return {
            "confidence_score": round(confidence, 1),
            "degradation_rate_per_minute": round(degradation_rate, 2),
            "operational_minutes_remaining": round(operational_minutes, 1)
            if operational_minutes != float("inf")
            else "unlimited",
            "drift_window_minutes": round(drift_minutes, 1),
            "recommendation": action.name,
            "reason": reason,
            "active_agents": active_agents,
            "time_since_gps_loss_minutes": round(time_since_gps_loss, 1),
            "mission_priority": mission_priority,
            "sensor_classification": self._classify_sensor_combination(active_agents),
            "metadata": metadata,
        }
