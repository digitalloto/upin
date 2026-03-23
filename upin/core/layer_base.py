"""
Base classes for all UPIN positioning and sensing layers.

Every one of the 60 navigation layers and 25 threat detection layers
inherits from these base classes. The architecture is designed so that
any new layer operating on any physical principle can be added without
modifying the fusion engine — fulfilling the extensibility claim.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

from upin.core.position import Position, ThreatAlert


class LayerGroup(Enum):
    """Groups as defined in the patent specification Section 6.2."""
    A_SATELLITE_CELESTIAL = "A"
    B_INERTIAL_TIMING = "B"
    C_MAGNETIC_QUANTUM = "C"
    D_RF_TERRESTRIAL = "D"
    E_OPTICAL_VISION = "E"
    F_ACOUSTIC = "F"
    G_GRAVITY = "G"
    H_CHEMICAL_SEISMIC_FLOW = "H"
    I_COSMIC_ATMOSPHERIC = "I"
    J_HUMAN_CROWD = "J"
    K_SYSTEMS_INTELLIGENCE = "K"


class LayerCapability(Enum):
    """What a layer can provide."""
    POSITION = auto()        # Lat/lon/alt
    VELOCITY = auto()        # Speed and direction
    HEADING = auto()         # Bearing/orientation
    ALTITUDE = auto()        # Height only
    TIMING = auto()          # Precise time reference
    THREAT_DETECT = auto()   # Threat information
    ENVIRONMENT = auto()     # Environmental data


@dataclass
class LayerStatus:
    """Runtime status of a layer."""
    is_active: bool = True
    is_healthy: bool = True
    is_trusted: bool = True
    last_update: float = 0.0
    update_rate_hz: float = 1.0
    error_count: int = 0
    consecutive_failures: int = 0
    spoofing_suspected: bool = False
    degraded_reason: Optional[str] = None


@dataclass
class LayerReading:
    """A single reading from a positioning layer.

    This is what each layer passes to the fusion engine every cycle.
    """
    layer_id: str
    position: Optional[Position] = None
    velocity: Optional[float] = None
    heading: Optional[float] = None
    raw_data: Optional[dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)
    self_confidence: float = 1.0  # Layer's own confidence in this reading
    is_valid: bool = True


class NavigationLayer(ABC):
    """Abstract base class for all 60 UPIN navigation/positioning layers.

    Each layer operates on a fundamentally different physical principle.
    The fusion engine treats every layer uniformly through this interface.

    Subclasses must implement:
        - read(): Produce a LayerReading from sensor data
        - initialize(): Set up the layer
        - get_accuracy_rating(): Return baseline accuracy for this layer

    The layer can operate in two modes:
        - LIVE: Connected to real hardware/signals
        - SIMULATED: Generating realistic simulated data for testing
    """

    def __init__(
        self,
        layer_id: str,
        layer_number: int,
        name: str,
        group: LayerGroup,
        capabilities: list[LayerCapability],
        is_novel: bool = False,
        is_underwater: bool = False,
        description: str = "",
        bio_inspiration: str = "",
    ):
        self.layer_id = layer_id
        self.layer_number = layer_number
        self.name = name
        self.group = group
        self.capabilities = capabilities
        self.is_novel = is_novel
        self.is_underwater = is_underwater
        self.description = description
        self.bio_inspiration = bio_inspiration
        self.status = LayerStatus()
        self._simulated = True  # Default to simulation mode
        self._weight = 1.0
        self._reliability_coefficient = 1.0
        self._accuracy_rating = self.get_accuracy_rating()

    @abstractmethod
    def read(self) -> LayerReading:
        """Produce a positioning/navigation reading.

        This is called by the fusion engine at each processing cycle.
        Must return a LayerReading even if the layer has no new data
        (set is_valid=False in that case).
        """
        ...

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the layer. Returns True if ready."""
        ...

    @abstractmethod
    def get_accuracy_rating(self) -> float:
        """Return baseline accuracy rating (0.0 to 1.0).

        1.0 = highest possible accuracy for this layer type.
        This is the intrinsic accuracy, not the current confidence.
        """
        ...

    def shutdown(self) -> None:
        """Gracefully shut down the layer."""
        self.status.is_active = False

    def health_check(self) -> bool:
        """Run self-diagnostic. Returns True if healthy."""
        return self.status.is_healthy and self.status.consecutive_failures < 5

    @property
    def weight(self) -> float:
        """Current dynamic weight assigned by the fusion engine."""
        return self._weight

    @weight.setter
    def weight(self, value: float) -> None:
        self._weight = max(0.0, min(1.0, value))

    @property
    def reliability_coefficient(self) -> float:
        """Platform-specific learned reliability for this layer."""
        return self._reliability_coefficient

    @reliability_coefficient.setter
    def reliability_coefficient(self, value: float) -> None:
        self._reliability_coefficient = max(0.0, min(1.0, value))

    @property
    def is_simulated(self) -> bool:
        return self._simulated

    def set_simulation_mode(self, simulated: bool) -> None:
        self._simulated = simulated

    def set_world(self, world) -> None:
        """Inject a SimulationWorld for physics-based simulation.

        When a world is set, the layer computes its own coordinates
        from raw sensor physics rather than using a fixed base position.
        """
        self._world = world

    @property
    def world(self):
        """The SimulationWorld, if set."""
        return getattr(self, '_world', None)

    def __repr__(self) -> str:
        mode = "SIM" if self._simulated else "LIVE"
        status = "OK" if self.status.is_healthy else "FAIL"
        return (f"<Layer {self.layer_number}: {self.name} "
                f"[{self.group.value}] [{mode}] [{status}]>")


class ThreatLayer(ABC):
    """Abstract base class for all 25 UPIN threat detection layers.

    Threat layers come in two types:
        - Hardware (T1-T8): Repurpose navigation sensor hardware for threat detection
        - Software (ST1-ST17): Pure AI analysis on existing compute, zero hardware cost
    """

    def __init__(
        self,
        threat_id: str,
        name: str,
        is_hardware: bool,
        description: str = "",
    ):
        self.threat_id = threat_id
        self.name = name
        self.is_hardware = is_hardware
        self.description = description
        self.is_active = True
        self._last_scan_time = 0.0

    @abstractmethod
    def scan(self, layer_readings: list[LayerReading],
             nav_output: Optional[Any] = None) -> list[ThreatAlert]:
        """Scan for threats using available data.

        Args:
            layer_readings: Current readings from all navigation layers.
            nav_output: Previous NavigationOutput for trend analysis.

        Returns:
            List of detected threats (empty if none).
        """
        ...

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the threat layer."""
        ...

    def __repr__(self) -> str:
        kind = "HW" if self.is_hardware else "SW"
        return f"<Threat {self.threat_id}: {self.name} [{kind}]>"


class SwarmLayer(ABC):
    """Abstract base class for swarm architecture layers SW1-SW4."""

    def __init__(self, swarm_id: str, name: str, description: str = ""):
        self.swarm_id = swarm_id
        self.name = name
        self.description = description
        self.is_active = True

    @abstractmethod
    def process(self, local_state: dict, peer_states: list[dict]) -> dict:
        """Process swarm intelligence for this cycle.

        Args:
            local_state: This platform's current state.
            peer_states: States received from peer platforms.

        Returns:
            Updated local state with swarm intelligence applied.
        """
        ...

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the swarm layer."""
        ...


class MissionModule(ABC):
    """Abstract base class for mission capability modules MC1-MC4."""

    def __init__(self, module_id: str, name: str, description: str = ""):
        self.module_id = module_id
        self.name = name
        self.description = description
        self.is_active = False

    @abstractmethod
    def execute(self, nav_output: Any, mission_params: dict) -> dict:
        """Execute the mission module with current navigation data.

        Args:
            nav_output: Current NavigationOutput from fusion engine.
            mission_params: Mission-specific parameters.

        Returns:
            Module-specific output dictionary.
        """
        ...

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the mission module."""
        ...
