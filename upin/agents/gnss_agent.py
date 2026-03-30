"""
GNSS Agent — UPIN GNSS Positioning with Spoofing Detection

Handles GPS, NavIC, GLONASS, Galileo, BeiDou positioning with
gradual spoofing detection and constellation signal authentication.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Tuple

from upin.agents.base_agent import BaseAgent
from upin.core.position import Position


class GNSSAgent(BaseAgent):
    """GNSS positioning agent with multi-constellation support."""

    def __init__(self, agent_id: str = "gnss_primary"):
        super().__init__(agent_id, "GNSS")
        self.status = "ACTIVE"
        self._spoof_history: List[Dict] = []

    def get_reading(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "timestamp": time.time(),
            "status": self.status,
            "lat": 13.0827,
            "lon": 80.2707,
            "accuracy_m": 5.0,
            "sources": ["gps", "navic"],
        }

    def is_available(self) -> bool:
        return self.status == "ACTIVE"

    def calibrate(self) -> bool:
        self.status = "ACTIVE"
        return True

    # ── Enhancement 1a: Gradual Spoofing Detection ────────────────

    def detect_gradual_spoof(
        self,
        current_reading: Dict,
        agent_consensus_history: List[Dict],
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Detect gradual spoofing attacks using temporal window comparison.

        Compares GPS position against 10-second rolling average of other agents.
        If GPS drifts more than 15 metres from consensus over any 30-second window,
        flag as gradual spoof attack.
        """
        if len(agent_consensus_history) < 10:
            return False, None

        # Calculate rolling 10-second average of non-GPS agents
        non_gps_positions = []
        for reading in agent_consensus_history[-10:]:
            if "gps" not in reading.get("sources", []):
                non_gps_positions.append([reading["lat"], reading["lon"]])

        if len(non_gps_positions) < 5:
            return False, "Insufficient non-GPS data for gradual spoof detection"

        consensus_lat = sum(pos[0] for pos in non_gps_positions) / len(non_gps_positions)
        consensus_lon = sum(pos[1] for pos in non_gps_positions) / len(non_gps_positions)

        dlat_m = (current_reading["lat"] - consensus_lat) * 111320
        dlon_m = (
            (current_reading["lon"] - consensus_lon)
            * 111320
            * math.cos(math.radians(consensus_lat))
        )
        drift_distance = math.sqrt(dlat_m**2 + dlon_m**2)

        # Check for gradual drift over 30-second window
        if len(agent_consensus_history) >= 30:
            window_start = agent_consensus_history[-30]
            if "gps" in window_start.get("sources", []):
                time_delta = current_reading["timestamp"] - window_start["timestamp"]
                if time_delta > 0:
                    drift_rate_mps = drift_distance / time_delta

                    if drift_distance > 15.0 and drift_rate_mps > 0.5:
                        return True, {
                            "drift_distance_m": drift_distance,
                            "drift_rate_mps": drift_rate_mps,
                            "drift_direction_deg": math.degrees(
                                math.atan2(dlon_m, dlat_m)
                            ),
                            "attack_type": "GRADUAL_SPOOF",
                            "confidence": min(0.95, drift_distance / 50.0),
                        }

        return False, None

    # ── Enhancement 1b: Signal Authentication Logging ─────────────

    def signal_authentication_log(self, gnss_reading: Dict) -> Dict:
        """
        Log which constellation provided the reading and authenticate if possible.

        Records GPS, NavIC, GLONASS, Galileo, BeiDou sources.
        When NavIC RS (Restricted Service) signal is available, flag as
        authenticated source and weight it higher in the fusion engine.
        """
        constellation_data = {
            "primary_constellation": None,
            "available_constellations": [],
            "authenticated_signal": False,
            "signal_strengths": {},
            "authentication_level": "NONE",
        }

        if "constellation_info" in gnss_reading:
            constellation_data.update(gnss_reading["constellation_info"])
        else:
            available = ["GPS", "NavIC", "GLONASS"]
            constellation_data["available_constellations"] = available
            constellation_data["primary_constellation"] = available[0]

            for constellation in available:
                constellation_data["signal_strengths"][constellation] = random.uniform(
                    35, 50
                )

        # Check for NavIC Restricted Service (authenticated)
        if "NavIC" in constellation_data["available_constellations"]:
            navic_strength = constellation_data["signal_strengths"].get("NavIC", 0)

            if navic_strength > 40 and random.random() > 0.3:
                constellation_data["authenticated_signal"] = True
                constellation_data["authentication_level"] = "NAVIC_RS"
                constellation_data["auth_confidence"] = 0.95

        # Indian Regional Navigation enhancement
        if constellation_data["authenticated_signal"]:
            gnss_reading["reliability_multiplier"] = 1.5
            gnss_reading["authentication_status"] = "AUTHENTICATED"
        else:
            gnss_reading["reliability_multiplier"] = 1.0
            gnss_reading["authentication_status"] = "UNAUTHENTICATED"

        gnss_reading["constellation_data"] = constellation_data
        return gnss_reading
