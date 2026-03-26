"""
False Position Broadcasting — UPIN Intelligence Module

When an adversary is spoofing your position, you know exactly where
you actually are. UPIN can optionally transmit a convincing false
position to adversary tracking systems — making them believe you are
somewhere you are not.

This is an active deception measure. It requires explicit human
authorisation before any transmission. It is never autonomous.
Full audit trail is maintained.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Optional


class DecoyStrategy(Enum):
    STATIONARY = auto()     # Appear stopped at a fixed false location
    RETREATING = auto()     # Appear to be moving away from objective
    DECOY_ROUTE = auto()    # Appear to follow a plausible but wrong route
    MIRROR = auto()         # Broadcast the spoofed position back — appear to believe it
    CUSTOM = auto()         # Operator-defined false position


@dataclass
class FalsePositionBroadcast:
    """A single false position transmission record."""
    true_lat: float
    true_lon: float
    false_lat: float
    false_lon: float
    strategy: DecoyStrategy
    offset_km: float
    timestamp: float
    human_authorised: bool
    authorised_by: str
    duration_seconds: float
    broadcast_count: int = 0
    audit_log: list[str] = field(default_factory=list)

    def deception_distance_km(self) -> float:
        """How far the false position is from the true position."""
        dlat = (self.false_lat - self.true_lat) * 111.0
        dlon = (self.false_lon - self.true_lon) * 111.0 * math.cos(
            math.radians(self.true_lat)
        )
        return math.sqrt(dlat**2 + dlon**2)


class FalsePositionBroadcaster:
    """
    Generates and logs false position transmissions.

    True position is always maintained internally through UPIN fusion.
    The false position is what gets transmitted to adversary systems.

    RULES:
    - human_authorised must be True before any broadcast
    - Never transmits in COVERT_ISR or GHOST_RECON mode
    - Every broadcast is logged with who authorised it
    - Stops immediately when authorisation is revoked
    """

    # Minimum offset — never broadcast true position as false position
    MIN_OFFSET_KM = 0.5

    def __init__(self):
        self._active: Optional[FalsePositionBroadcast] = None
        self._history: list[FalsePositionBroadcast] = []
        self._human_authorised: bool = False
        self._authorised_by: str = ""
        self._emissions_blocked: bool = False

    def authorise(self, authorised: bool, authorised_by: str = "") -> None:
        """Human operator authorises or revokes false position broadcasting."""
        self._human_authorised = authorised
        self._authorised_by = authorised_by if authorised else ""
        if not authorised and self._active:
            self._stop_active("authorisation_revoked")

    def block_emissions(self, blocked: bool) -> None:
        """Called by mission mode controller — blocks all transmission in silent modes."""
        self._emissions_blocked = blocked
        if blocked and self._active:
            self._stop_active("emissions_blocked_by_mission_mode")

    def start_broadcast(
        self,
        true_lat: float,
        true_lon: float,
        strategy: DecoyStrategy,
        duration_seconds: float = 300.0,
        custom_lat: Optional[float] = None,
        custom_lon: Optional[float] = None,
        offset_bearing_deg: float = 180.0,
        offset_km: float = 5.0,
    ) -> Optional[FalsePositionBroadcast]:
        """
        Begin broadcasting a false position.
        Returns None if not authorised or emissions are blocked.
        """
        if not self._human_authorised:
            return None
        if self._emissions_blocked:
            return None
        if offset_km < self.MIN_OFFSET_KM:
            offset_km = self.MIN_OFFSET_KM

        false_lat, false_lon = self._calculate_false_position(
            true_lat, true_lon, strategy,
            custom_lat, custom_lon,
            offset_bearing_deg, offset_km,
        )

        log_entry = (
            f"[{time.strftime('%H:%M:%S')}] FALSE POSITION BROADCAST STARTED — "
            f"true={true_lat:.6f}N {true_lon:.6f}E — "
            f"false={false_lat:.6f}N {false_lon:.6f}E — "
            f"strategy={strategy.name} — "
            f"auth={self._authorised_by} — duration={duration_seconds}s"
        )

        broadcast = FalsePositionBroadcast(
            true_lat=true_lat,
            true_lon=true_lon,
            false_lat=false_lat,
            false_lon=false_lon,
            strategy=strategy,
            offset_km=offset_km,
            timestamp=time.time(),
            human_authorised=True,
            authorised_by=self._authorised_by,
            duration_seconds=duration_seconds,
            broadcast_count=1,
            audit_log=[log_entry],
        )

        self._active = broadcast
        self._history.append(broadcast)
        return broadcast

    def get_current_false_position(self) -> Optional[tuple[float, float]]:
        """Returns current false lat/lon being broadcast, or None if inactive."""
        if self._active is None:
            return None
        elapsed = time.time() - self._active.timestamp
        if elapsed > self._active.duration_seconds:
            self._stop_active("duration_expired")
            return None
        self._active.broadcast_count += 1
        return (self._active.false_lat, self._active.false_lon)

    def stop_broadcast(self) -> None:
        """Manually stop the active broadcast."""
        if self._active:
            self._stop_active("manually_stopped")

    def is_active(self) -> bool:
        if self._active is None:
            return False
        elapsed = time.time() - self._active.timestamp
        if elapsed > self._active.duration_seconds:
            self._stop_active("duration_expired")
            return False
        return True

    def get_history(self) -> list[FalsePositionBroadcast]:
        return list(self._history)

    def _calculate_false_position(
        self,
        true_lat: float,
        true_lon: float,
        strategy: DecoyStrategy,
        custom_lat: Optional[float],
        custom_lon: Optional[float],
        bearing_deg: float,
        offset_km: float,
    ) -> tuple[float, float]:
        if strategy == DecoyStrategy.CUSTOM and custom_lat and custom_lon:
            return custom_lat, custom_lon

        if strategy == DecoyStrategy.MIRROR:
            # Broadcast exactly what the spoofer sent — appear to believe it
            # Offset slightly from true position in spoofer's direction
            bearing_deg = (bearing_deg + 180.0) % 360.0

        # Convert bearing + distance to lat/lon offset
        bearing_rad = math.radians(bearing_deg)
        delta_lat = (offset_km / 111.0) * math.cos(bearing_rad)
        delta_lon = (offset_km / 111.0) * math.sin(bearing_rad) / math.cos(
            math.radians(true_lat)
        )

        if strategy == DecoyStrategy.RETREATING:
            # Double the offset to make retreat convincing
            delta_lat *= 2.0
            delta_lon *= 2.0

        return true_lat + delta_lat, true_lon + delta_lon

    def _stop_active(self, reason: str) -> None:
        if self._active:
            stop_log = (
                f"[{time.strftime('%H:%M:%S')}] BROADCAST STOPPED — "
                f"reason={reason} — "
                f"total_broadcasts={self._active.broadcast_count}"
            )
            self._active.audit_log.append(stop_log)
        self._active = None
