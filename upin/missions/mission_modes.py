"""
Mission Mode Controller — UPIN

A human commander selects the operational mode before launch.
The mode defines what UPIN is permitted to do — what it can emit,
what it can engage, and what requires human authorisation.

No mode allows autonomous lethal action. HAIL (Human Authorised
Intelligent Lethal) protocol is enforced at all times.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Optional


class MissionMode(Enum):
    GHOST_RECON = auto()    # Silent observation. No engagement. No emissions.
    SENTINEL = auto()       # Detect and hold. Human authorises all responses.
    GUARDIAN = auto()       # Detect, prepare, request authorisation.
    HUNTER = auto()         # Pre-authorised engagement within defined parameters.
    COVERT_ISR = auto()     # Entirely passive. Zero emissions. Intelligence only.
    RESCUE_SUPPORT = auto() # Navigation and detection only. All engagement disabled.


@dataclass
class ModePermissions:
    """What is permitted in this mission mode."""
    mode: MissionMode
    engagement_enabled: bool       # Can any engagement action be prepared?
    lethal_capable: bool           # Can lethal engagement be requested?
    active_emission_allowed: bool  # Can UPIN transmit any signal?
    autonomous_action: bool        # Always False — HAIL protocol enforced
    human_auth_required: bool      # Must human approve before any action?
    jammer_location_transmit: bool # Can jammer coordinates be transmitted?
    description: str


# Permissions table — defines every mode's operational envelope
MODE_PERMISSIONS: dict[MissionMode, ModePermissions] = {
    MissionMode.GHOST_RECON: ModePermissions(
        mode=MissionMode.GHOST_RECON,
        engagement_enabled=False,
        lethal_capable=False,
        active_emission_allowed=False,
        autonomous_action=False,
        human_auth_required=True,
        jammer_location_transmit=False,
        description="Silent observation only. No transmissions. No engagement of any kind.",
    ),
    MissionMode.SENTINEL: ModePermissions(
        mode=MissionMode.SENTINEL,
        engagement_enabled=False,
        lethal_capable=False,
        active_emission_allowed=True,
        autonomous_action=False,
        human_auth_required=True,
        jammer_location_transmit=True,
        description="Detect and report. Human authorises every response. No autonomous action.",
    ),
    MissionMode.GUARDIAN: ModePermissions(
        mode=MissionMode.GUARDIAN,
        engagement_enabled=True,
        lethal_capable=False,
        active_emission_allowed=True,
        autonomous_action=False,
        human_auth_required=True,
        jammer_location_transmit=True,
        description="Detect, prepare engagement solution, request human authorisation.",
    ),
    MissionMode.HUNTER: ModePermissions(
        mode=MissionMode.HUNTER,
        engagement_enabled=True,
        lethal_capable=True,
        active_emission_allowed=True,
        autonomous_action=False,
        human_auth_required=True,
        jammer_location_transmit=True,
        description="Pre-authorised engagement within defined parameters. HAIL still required.",
    ),
    MissionMode.COVERT_ISR: ModePermissions(
        mode=MissionMode.COVERT_ISR,
        engagement_enabled=False,
        lethal_capable=False,
        active_emission_allowed=False,
        autonomous_action=False,
        human_auth_required=True,
        jammer_location_transmit=False,
        description="Entirely passive. Zero emissions. Intelligence gathering only.",
    ),
    MissionMode.RESCUE_SUPPORT: ModePermissions(
        mode=MissionMode.RESCUE_SUPPORT,
        engagement_enabled=False,
        lethal_capable=False,
        active_emission_allowed=True,
        autonomous_action=False,
        human_auth_required=True,
        jammer_location_transmit=False,
        description="Navigation and detection only. All engagement permanently disabled.",
    ),
}


@dataclass
class ModeTransition:
    """A record of one mode change."""
    from_mode: Optional[MissionMode]
    to_mode: MissionMode
    timestamp: float
    authorised_by: str
    reason: str


class MissionModeController:
    """
    Controls the current operational mode of a UPIN unit.
    All mode changes are logged. Permissions are enforced before
    any action is taken.
    """

    def __init__(self, initial_mode: MissionMode = MissionMode.GHOST_RECON):
        self._current_mode: MissionMode = initial_mode
        self._history: list[ModeTransition] = []
        self._log_transition(None, initial_mode, "system", "Initialised")

    @property
    def current_mode(self) -> MissionMode:
        return self._current_mode

    @property
    def permissions(self) -> ModePermissions:
        return MODE_PERMISSIONS[self._current_mode]

    def set_mode(self, mode: MissionMode, authorised_by: str, reason: str) -> ModePermissions:
        """Switch to a new mission mode. Returns the new permissions."""
        previous = self._current_mode
        self._current_mode = mode
        self._log_transition(previous, mode, authorised_by, reason)
        return self.permissions

    def can(self, action: str) -> bool:
        """
        Check if an action is permitted in the current mode.
        Actions: 'engage', 'lethal', 'emit', 'transmit_jammer', 'autonomous'
        """
        p = self.permissions
        checks = {
            "engage": p.engagement_enabled,
            "lethal": p.lethal_capable,
            "emit": p.active_emission_allowed,
            "transmit_jammer": p.jammer_location_transmit,
            "autonomous": False,  # Always blocked — HAIL protocol
        }
        return checks.get(action, False)

    def require_auth(self) -> bool:
        """Returns True if human authorisation is required before any action."""
        return self.permissions.human_auth_required

    def get_history(self) -> list[ModeTransition]:
        return list(self._history)

    def status_report(self) -> str:
        p = self.permissions
        lines = [
            f"MODE: {self._current_mode.name}",
            f"  {p.description}",
            f"  Engagement: {'YES' if p.engagement_enabled else 'NO'}",
            f"  Lethal capable: {'YES' if p.lethal_capable else 'NO'}",
            f"  Active emissions: {'YES' if p.active_emission_allowed else 'NO'}",
            f"  Jammer tx: {'YES' if p.jammer_location_transmit else 'NO'}",
            f"  Autonomous action: NEVER (HAIL enforced)",
            f"  Human auth required: YES",
        ]
        return "\n".join(lines)

    def _log_transition(
        self,
        from_mode: Optional[MissionMode],
        to_mode: MissionMode,
        authorised_by: str,
        reason: str,
    ) -> None:
        self._history.append(ModeTransition(
            from_mode=from_mode,
            to_mode=to_mode,
            timestamp=time.time(),
            authorised_by=authorised_by,
            reason=reason,
        ))
