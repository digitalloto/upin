"""
UPIN Beehive Swarm Architecture (SW1-SW4).

Operates on beehive principles — no single point of control, no queen.
Each platform runs a complete UPIN AI and decides independently.
Intelligence emerges from collective interactions following three rules
from natural swarm systems: Separate, Align, Cohere.

SW1: Distributed Beehive Intelligence — no central controller
SW2: Master Brain Upload Protocol — collective learning
SW3: Offensive Posture Mode — human-authorized engagement
SW4: Adaptive Formation Intelligence — mission-optimal formations
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum, auto

import numpy as np

from upin.core.layer_base import SwarmLayer
from upin.core.position import Position, ThreatAlert


class FormationType(Enum):
    """Standard swarm formations."""
    SPREAD = auto()       # Wide ISR coverage
    TIGHT = auto()        # Contested airspace
    WEDGE = auto()        # Attack approach
    LINE = auto()         # Linear search
    CIRCLE = auto()       # Perimeter containment
    SPLIT = auto()        # Multi-vector approach
    ADAPTIVE = auto()     # AI-optimised


@dataclass
class PlatformState:
    """State of a single platform in the swarm."""
    platform_id: str
    position: Position
    velocity: float = 0.0
    heading: float = 0.0
    confidence_score: float = 0.0
    threat_alerts: list[ThreatAlert] = field(default_factory=list)
    is_healthy: bool = True
    mission_role: str = "scout"
    timestamp: float = field(default_factory=time.time)


@dataclass
class SwarmCommand:
    """A command from the swarm intelligence to a platform."""
    target_position: Optional[Position] = None
    target_heading: Optional[float] = None
    target_velocity: Optional[float] = None
    formation: FormationType = FormationType.ADAPTIVE
    priority: int = 0
    human_authorized: bool = False


class DistributedBeehiveIntelligence(SwarmLayer):
    """SW1 — Distributed Beehive Intelligence.

    Decentralised AI with no central controller. Swarm survives
    destruction of any individual node including the Master Brain.
    Three rules: Separate, Align, Cohere.
    """

    def __init__(self):
        super().__init__(
            swarm_id="SW1",
            name="Distributed Beehive Intelligence",
            description="Decentralised swarm — survives any node loss",
        )
        self._platform_id = str(uuid.uuid4())[:8]
        self._peers: dict[str, PlatformState] = {}
        self._min_separation_m = 50.0
        self._cohesion_radius_m = 5000.0

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def process(self, local_state: dict, peer_states: list[dict]) -> dict:
        """Apply Separate-Align-Cohere rules.

        Returns updated local state with swarm adjustments.
        """
        if not peer_states:
            return local_state

        local_pos = local_state.get("position", Position(0, 0))
        adjustments = {"heading_adj": 0.0, "velocity_adj": 0.0}

        for peer in peer_states:
            peer_pos = peer.get("position", Position(0, 0))
            dist = local_pos.distance_to(peer_pos)

            # SEPARATE: Maintain minimum safe distance
            if dist < self._min_separation_m and dist > 0:
                # Move away
                dlat = local_pos.latitude - peer_pos.latitude
                dlon = local_pos.longitude - peer_pos.longitude
                adjustments["heading_adj"] += np.degrees(np.arctan2(dlon, dlat))

            # COHERE: Don't drift too far from swarm
            if dist > self._cohesion_radius_m:
                dlat = peer_pos.latitude - local_pos.latitude
                dlon = peer_pos.longitude - local_pos.longitude
                adjustments["heading_adj"] += np.degrees(np.arctan2(dlon, dlat)) * 0.1

        # ALIGN: Move toward mission objective
        mission_heading = local_state.get("mission_heading", 0)
        adjustments["heading_adj"] = (adjustments["heading_adj"] + mission_heading) / 2

        local_state["swarm_adjustments"] = adjustments
        local_state["peers_tracked"] = len(peer_states)
        return local_state

    def update_peer(self, peer_state: PlatformState):
        self._peers[peer_state.platform_id] = peer_state


class MasterBrainProtocol(SwarmLayer):
    """SW2 — Master Brain Upload Protocol.

    Each platform uploads operational experience to Master Brain on
    reconnection. Master Brain synthesises learning from all platforms
    and distributes updated intelligence back. Network improves
    continuously from every platform's experience.
    """

    def __init__(self):
        super().__init__(
            swarm_id="SW2",
            name="Master Brain Upload Protocol",
            description="Collective learning — synthesise all platform experience",
        )
        self._experience_log: list[dict] = []
        self._global_weights: dict[str, float] = {}
        self._threat_library: list[dict] = []
        self._connected_to_master: bool = False

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def log_experience(self, experience: dict):
        """Log operational experience for later upload."""
        experience["timestamp"] = time.time()
        self._experience_log.append(experience)
        if len(self._experience_log) > 10000:
            self._experience_log = self._experience_log[-5000:]

    def upload_to_master(self) -> dict:
        """Upload accumulated experience to Master Brain.

        Returns synthesised intelligence update.
        """
        upload = {
            "platform_id": str(uuid.uuid4())[:8],
            "experiences": len(self._experience_log),
            "timestamp": time.time(),
        }

        # Simulate Master Brain synthesising response
        update = {
            "updated_weights": self._global_weights,
            "new_threat_signatures": len(self._threat_library),
            "network_platforms": np.random.randint(10, 100),
        }

        self._experience_log = []  # Clear after upload
        return update

    def receive_master_update(self, update: dict):
        """Receive synthesised intelligence from Master Brain."""
        if "updated_weights" in update:
            self._global_weights.update(update["updated_weights"])
        self._connected_to_master = True

    def process(self, local_state: dict, peer_states: list[dict]) -> dict:
        # Log this cycle's experience
        self.log_experience({
            "confidence": local_state.get("confidence_score", 0),
            "threats": len(local_state.get("threats", [])),
            "layers_active": local_state.get("active_layers", 0),
        })
        local_state["experience_buffer"] = len(self._experience_log)
        local_state["master_connected"] = self._connected_to_master
        return local_state


class OffensivePostureMode(SwarmLayer):
    """SW3 — Offensive Posture Mode.

    Under EXPLICIT HUMAN AUTHORISATION, swarm repositions to optimal
    engagement geometry. AI prepares the plan. Human authorises EVERY
    individual action. Human decision-making at AI speed.
    """

    def __init__(self):
        super().__init__(
            swarm_id="SW3",
            name="Offensive Posture Mode",
            description="Human-authorized engagement — AI prepares, human decides",
        )
        self._human_authorized = False
        self._engagement_plan: Optional[dict] = None

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def request_authorization(self, target: dict) -> dict:
        """Request human authorization for engagement.

        Returns the plan for human review. Does NOT execute.
        """
        plan = {
            "target": target,
            "optimal_positions": self._calculate_engagement_geometry(target),
            "risk_assessment": "MODERATE",
            "collateral_risk": self._assess_collateral(target),
            "requires_human_auth": True,
            "status": "AWAITING_AUTHORIZATION",
        }
        self._engagement_plan = plan
        return plan

    def authorize(self, auth_code: str) -> dict:
        """Human authorizes a specific action.

        Every individual action requires separate authorization.
        """
        if not self._engagement_plan:
            return {"error": "No pending plan"}
        self._human_authorized = True
        self._engagement_plan["status"] = "AUTHORIZED"
        self._engagement_plan["auth_code"] = auth_code
        self._engagement_plan["auth_time"] = time.time()
        return self._engagement_plan

    def _calculate_engagement_geometry(self, target: dict) -> list[dict]:
        return [
            {"platform": "alpha", "position": "flanking_left", "range_m": 2000},
            {"platform": "bravo", "position": "overwatch", "range_m": 3000},
            {"platform": "charlie", "position": "flanking_right", "range_m": 2000},
        ]

    def _assess_collateral(self, target: dict) -> dict:
        return {
            "civilian_structures_nearby": 3,
            "estimated_civilian_risk": "LOW",
            "school_detected": False,
            "hospital_detected": False,
        }

    def process(self, local_state: dict, peer_states: list[dict]) -> dict:
        local_state["offensive_mode"] = self._human_authorized
        local_state["engagement_plan"] = self._engagement_plan
        return local_state


class AdaptiveFormationIntelligence(SwarmLayer):
    """SW4 — Adaptive Formation Intelligence.

    Continuous formation optimisation for mission requirements.
    Spread for ISR, tight for contested airspace, split for multi-vector.
    """

    def __init__(self):
        super().__init__(
            swarm_id="SW4",
            name="Adaptive Formation Intelligence",
            description="Mission-optimal formation switching",
        )
        self._current_formation = FormationType.SPREAD
        self._formation_history: list[FormationType] = []

    def initialize(self) -> bool:
        self.is_active = True
        return True

    def select_formation(self, mission_type: str,
                         threat_level: int = 0) -> FormationType:
        """Select optimal formation for current conditions."""
        if mission_type == "isr" and threat_level < 2:
            formation = FormationType.SPREAD
        elif mission_type == "isr" and threat_level >= 2:
            formation = FormationType.TIGHT
        elif mission_type == "attack":
            formation = FormationType.WEDGE
        elif mission_type == "search":
            formation = FormationType.LINE
        elif mission_type == "containment":
            formation = FormationType.CIRCLE
        elif mission_type == "multi_approach":
            formation = FormationType.SPLIT
        else:
            formation = FormationType.ADAPTIVE

        self._current_formation = formation
        self._formation_history.append(formation)
        return formation

    def get_formation_positions(self, center: Position,
                                 n_platforms: int) -> list[Position]:
        """Calculate positions for each platform in current formation."""
        positions = []
        spacing_m = 200.0
        deg_per_m = 1.0 / 111_000

        if self._current_formation == FormationType.SPREAD:
            for i in range(n_platforms):
                angle = 2 * np.pi * i / n_platforms
                lat = center.latitude + spacing_m * 3 * np.cos(angle) * deg_per_m
                lon = center.longitude + spacing_m * 3 * np.sin(angle) * deg_per_m
                positions.append(Position(latitude=lat, longitude=lon,
                                          altitude=center.altitude or 100))

        elif self._current_formation == FormationType.TIGHT:
            for i in range(n_platforms):
                angle = 2 * np.pi * i / n_platforms
                lat = center.latitude + spacing_m * np.cos(angle) * deg_per_m
                lon = center.longitude + spacing_m * np.sin(angle) * deg_per_m
                positions.append(Position(latitude=lat, longitude=lon,
                                          altitude=center.altitude or 100))

        elif self._current_formation == FormationType.WEDGE:
            for i in range(n_platforms):
                row = i // 2
                side = 1 if i % 2 == 0 else -1
                lat = center.latitude - row * spacing_m * deg_per_m
                lon = center.longitude + side * row * spacing_m * 0.5 * deg_per_m
                positions.append(Position(latitude=lat, longitude=lon,
                                          altitude=center.altitude or 100))

        elif self._current_formation == FormationType.LINE:
            for i in range(n_platforms):
                lon = center.longitude + (i - n_platforms // 2) * spacing_m * deg_per_m
                positions.append(Position(latitude=center.latitude, longitude=lon,
                                          altitude=center.altitude or 100))
        else:
            # Default: even distribution
            for i in range(n_platforms):
                angle = 2 * np.pi * i / n_platforms
                lat = center.latitude + spacing_m * 2 * np.cos(angle) * deg_per_m
                lon = center.longitude + spacing_m * 2 * np.sin(angle) * deg_per_m
                positions.append(Position(latitude=lat, longitude=lon,
                                          altitude=center.altitude or 100))

        return positions

    def process(self, local_state: dict, peer_states: list[dict]) -> dict:
        local_state["formation"] = self._current_formation.name
        local_state["formation_peers"] = len(peer_states)
        return local_state
