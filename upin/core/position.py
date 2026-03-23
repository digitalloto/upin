"""
Position and navigation output data types for UPIN.

All positioning layers produce Position estimates that flow into the
AI Fusion Engine. The engine outputs NavigationOutput which includes
the fused position plus confidence score and threat alerts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class PositionDomain(Enum):
    """Domain in which the position was determined."""
    TERRESTRIAL = auto()
    MARITIME = auto()
    AERIAL = auto()
    UNDERWATER = auto()
    SUBTERRANEAN = auto()
    SPACE = auto()


class ThreatLevel(Enum):
    """Threat assessment levels."""
    NONE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Position:
    """A position estimate from a single layer or the fusion engine.

    Attributes:
        latitude: Decimal degrees, WGS84 datum.
        longitude: Decimal degrees, WGS84 datum.
        altitude: Metres above mean sea level. None if 2D only.
        heading: Degrees true north (0-360). None if unavailable.
        velocity: Metres per second. None if unavailable.
        velocity_heading: Direction of travel in degrees true north.
        timestamp: Unix epoch seconds when this position was determined.
        accuracy_m: Estimated horizontal accuracy in metres (1-sigma).
        altitude_accuracy_m: Estimated vertical accuracy in metres.
        domain: The operational domain of this position fix.
    """
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    heading: Optional[float] = None
    velocity: Optional[float] = None
    velocity_heading: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    accuracy_m: float = 10.0
    altitude_accuracy_m: Optional[float] = None
    domain: PositionDomain = PositionDomain.TERRESTRIAL

    def distance_to(self, other: Position) -> float:
        """Haversine distance to another position in metres."""
        import math
        R = 6_371_000  # Earth radius in metres
        lat1, lat2 = math.radians(self.latitude), math.radians(other.latitude)
        dlat = math.radians(other.latitude - self.latitude)
        dlon = math.radians(other.longitude - self.longitude)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def as_array(self) -> tuple[float, float, float]:
        """Return (lat, lon, alt) tuple for numerical processing."""
        return (self.latitude, self.longitude, self.altitude or 0.0)


@dataclass
class ThreatAlert:
    """A threat detected by the threat detection subsystem."""
    threat_id: str
    threat_type: str
    level: ThreatLevel
    description: str
    source_layer: str
    timestamp: float = field(default_factory=time.time)
    bearing: Optional[float] = None
    range_m: Optional[float] = None
    confidence: float = 0.0


@dataclass
class LayerDiagnostic:
    """Health and status of a single positioning layer."""
    layer_id: str
    layer_name: str
    is_active: bool
    is_trusted: bool
    current_weight: float
    reliability_coefficient: float
    last_position: Optional[Position] = None
    failure_reason: Optional[str] = None
    spoofing_suspected: bool = False


@dataclass
class NavigationOutput:
    """Complete output from the UPIN Fusion Engine at each cycle.

    This is the primary output consumed by all mission modules and operators.
    Contains the fused position, confidence score, layer diagnostics, and
    any active threat alerts.
    """
    position: Position
    confidence_score: float  # 0.0 to 100.0
    num_active_layers: int
    num_agreeing_layers: int
    threat_level: ThreatLevel
    threat_alerts: list[ThreatAlert] = field(default_factory=list)
    layer_diagnostics: list[LayerDiagnostic] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    cycle_hz: float = 10.0
    spoofing_detected: bool = False
    jamming_detected: bool = False
    gps_trusted: bool = True
    navic_trusted: bool = True

    @property
    def trust_level(self) -> str:
        """Human-readable trust assessment."""
        if self.confidence_score >= 95:
            return "FULL TRUST"
        elif self.confidence_score >= 80:
            return "HIGH ACCURACY"
        elif self.confidence_score >= 60:
            return "VERIFY"
        elif self.confidence_score >= 40:
            return "SEEK CONFIRMATION"
        else:
            return "IMMEDIATE ALERT"

    @property
    def is_reliable(self) -> bool:
        return self.confidence_score >= 60.0
