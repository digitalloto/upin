"""
UPIN Layer Code Generator — Developer Tool

Auto-generates a complete NavigationLayer subclass from a definition.
Useful for quickly adding new layers to the 67+ layer system.

Usage:
    from upin.utils.layer_generator import generate_layer
    code = generate_layer("snake_thermal", 73, "F", "Infrared pit organ thermal nav",
                          "Pit viper infrared sensing", accuracy=0.55)
    print(code)  # Ready-to-paste Python class

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from typing import List, Optional


_GROUP_MAP = {
    "A": "A_SATELLITE_CELESTIAL",
    "B": "B_INERTIAL_TIMING",
    "C": "C_MAGNETIC_QUANTUM",
    "D": "D_RF_TERRESTRIAL",
    "E": "E_OPTICAL_VISION",
    "F": "F_ACOUSTIC",
    "G": "G_GRAVITY",
    "H": "H_CHEMICAL_SEISMIC_FLOW",
    "I": "I_COSMIC_ATMOSPHERIC",
    "J": "J_HUMAN_CROWD",
    "K": "K_SYSTEMS_INTELLIGENCE",
}

_CAPABILITY_MAP = {
    "position": "POSITION",
    "heading": "HEADING",
    "velocity": "VELOCITY",
    "altitude": "ALTITUDE",
    "timing": "TIMING",
    "threat": "THREAT_DETECT",
    "environment": "ENVIRONMENT",
}


def generate_layer(
    layer_id_short: str,
    layer_number: int,
    group_letter: str,
    name: str,
    bio_inspiration: str = "",
    description: str = "",
    accuracy: float = 0.5,
    capabilities: Optional[List[str]] = None,
    is_novel: bool = True,
    is_underwater: bool = False,
    noise_m: float = 20.0,
) -> str:
    """
    Generate a complete NavigationLayer subclass.

    Args:
        layer_id_short: e.g. "snake_f04"
        layer_number: e.g. 73
        group_letter: "A" through "K"
        name: Human-readable name
        bio_inspiration: Animal/concept inspiration
        description: One-line description
        accuracy: 0.0-1.0 accuracy rating
        capabilities: ["position", "heading", ...] defaults to ["position"]
        is_novel: True if novel to UPIN
        is_underwater: True if works underwater
        noise_m: Simulated position noise in metres

    Returns:
        Complete Python class code as a string.
    """
    caps = capabilities or ["position"]
    cap_list = ", ".join(f"LayerCapability.{_CAPABILITY_MAP.get(c, 'POSITION')}" for c in caps)
    group_enum = _GROUP_MAP.get(group_letter.upper(), "K_SYSTEMS_INTELLIGENCE")
    class_name = "".join(w.capitalize() for w in name.split()) + "Layer"

    code = f'''class {class_name}(NavigationLayer):
    """{name} — {bio_inspiration or 'custom layer'}.

    {description or name}
    """

    def __init__(self):
        super().__init__(
            layer_id="{layer_id_short}",
            layer_number={layer_number},
            name="{name}",
            group=LayerGroup.{group_enum},
            capabilities=[{cap_list}],
            is_novel={is_novel},
            is_underwater={is_underwater},
            bio_inspiration="{bio_inspiration}",
            description="{description or name}",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return {accuracy}

    def read(self) -> LayerReading:
        noise_m = {noise_m}

        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
        elif self._simulated:
            true_lat = getattr(self, "_sim_lat", 13.0827)
            true_lon = getattr(self, "_sim_lon", 80.2707)
        else:
            raise NotImplementedError("Live hardware not connected")

        lat = true_lat + np.random.normal(0, noise_m / 111_000)
        lon = true_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence={accuracy},
            raw_data={{"bio_inspiration": "{bio_inspiration}"}},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
'''
    return code


def generate_layer_file(layers: list) -> str:
    """Generate a complete Python file with multiple layers.

    Args:
        layers: list of dicts, each passed to generate_layer().

    Returns:
        Complete Python file content.
    """
    header = '''"""Auto-generated UPIN layers."""

from __future__ import annotations
import time
import numpy as np
from upin.core.layer_base import NavigationLayer, LayerGroup, LayerCapability, LayerReading
from upin.core.position import Position

'''
    body = "\n\n".join(generate_layer(**ldef) for ldef in layers)
    return header + body
