"""
IR/Laser Mesh Communication — UPIN

1km LOS range, 10 Mbps, UNJAMMABLE by RF jammers.
Primary use: stealth communication when RF silence is required.
Requires line-of-sight — blocked by obstacles, rain, fog.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LaserLink:
    """One IR/laser communication link."""
    from_node: str
    to_node: str
    distance_m: float
    bandwidth_mbps: float
    beam_divergence_mrad: float = 1.0
    wavelength_nm: int = 1550  # eye-safe
    has_los: bool = True
    weather_attenuation_db: float = 0.0
    timestamp: float = field(default_factory=time.time)


class IRLaserMeshRadio:
    """IR/laser free-space optical communication.

    Completely immune to RF jamming — uses photons, not radio waves.
    Perfect for GHOST_RECON and COVERT_ISR missions where RF
    silence is mandatory.

    Limitations:
    - Requires line-of-sight (no obstacles)
    - Degraded by rain, fog, dust (atmospheric attenuation)
    - Needs precise pointing (narrow beam)
    """

    def __init__(self, wavelength_nm: int = 1550,
                 tx_power_mw: float = 100.0):
        self._wavelength = wavelength_nm
        self._tx_power = tx_power_mw
        self._nodes: Dict[str, Tuple[float, float]] = {}
        self._links: Dict[Tuple[str, str], LaserLink] = {}
        self._max_range_m = 1000.0
        self._weather_factor = 1.0  # 1.0 = clear, 0.1 = heavy fog

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)

    def set_weather(self, visibility_m: float):
        """Set weather conditions — affects range and bandwidth."""
        if visibility_m > 5000:
            self._weather_factor = 1.0
        elif visibility_m > 1000:
            self._weather_factor = 0.7
        elif visibility_m > 200:
            self._weather_factor = 0.3
        else:
            self._weather_factor = 0.05  # heavy fog/rain

    def establish_link(self, from_id: str, to_id: str,
                       has_los: bool = True) -> Optional[LaserLink]:
        """Establish an IR/laser link. Requires LOS."""
        if not has_los:
            return None
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        p1, p2 = self._nodes[from_id], self._nodes[to_id]
        dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
        effective_range = self._max_range_m * self._weather_factor
        if dist > effective_range:
            return None

        attenuation_db = dist * 0.002 / self._weather_factor
        bw = 10.0 * self._weather_factor * max(0.1, 1 - dist / effective_range)

        link = LaserLink(
            from_node=from_id, to_node=to_id, distance_m=dist,
            bandwidth_mbps=bw, wavelength_nm=self._wavelength,
            has_los=True, weather_attenuation_db=attenuation_db,
        )
        self._links[(from_id, to_id)] = link
        return link

    def is_rf_silent(self) -> bool:
        """IR/laser produces zero RF emissions — always RF silent."""
        return True

    def get_status(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "active_links": len(self._links),
            "wavelength_nm": self._wavelength,
            "weather_factor": self._weather_factor,
            "rf_silent": True,
            "max_range_m": self._max_range_m * self._weather_factor,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
