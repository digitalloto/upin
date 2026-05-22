"""
Acoustic Mesh Communication — UPIN

50m in air, 5km underwater. Unjammable by RF. Uses sound waves.
Primary use: underwater swarm comms where all radio fails.
Also works in air for short-range indoor/cave operations.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class AcousticPacket:
    """One acoustic transmission."""
    from_node: str
    to_node: str
    payload: Dict
    frequency_hz: float
    distance_m: float
    propagation_time_ms: float
    snr_db: float = 20.0
    medium: str = "water"  # water or air
    timestamp: float = field(default_factory=time.time)


class AcousticMeshRadio:
    """Acoustic mesh communication — sound-based data and ranging.

    Underwater: 1500 m/s sound speed, 5km range, 1 kbps.
    In air: 343 m/s sound speed, 50m range, 0.5 kbps.

    Completely immune to RF/EM jamming — uses mechanical waves.
    Also provides ranging from time-of-flight (passive sonar principle).
    """

    def __init__(self, medium: str = "water",
                 frequency_hz: float = 25000.0):
        self._medium = medium
        self._freq = frequency_hz
        self._nodes: Dict[str, Tuple[float, float]] = {}
        self._packets: List[AcousticPacket] = []

        if medium == "water":
            self._sound_speed = 1500.0  # m/s in seawater
            self._max_range_m = 5000.0
            self._bandwidth_bps = 1000
            self._attenuation_db_km = 3.0
        else:  # air
            self._sound_speed = 343.0  # m/s in air
            self._max_range_m = 50.0
            self._bandwidth_bps = 500
            self._attenuation_db_km = 100.0

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)

    def send(self, from_id: str, to_id: str, payload: Dict) -> Optional[Dict]:
        """Send an acoustic packet. Returns reception info."""
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        p1, p2 = self._nodes[from_id], self._nodes[to_id]
        dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
        if dist > self._max_range_m:
            return None

        prop_time_ms = (dist / self._sound_speed) * 1000
        attenuation = self._attenuation_db_km * dist / 1000
        snr = max(0, 40 - attenuation)

        pkt = AcousticPacket(
            from_node=from_id, to_node=to_id, payload=payload,
            frequency_hz=self._freq, distance_m=dist,
            propagation_time_ms=prop_time_ms, snr_db=snr,
            medium=self._medium,
        )
        self._packets.append(pkt)

        return {
            "received": snr > 5,
            "distance_m": round(dist, 1),
            "propagation_ms": round(prop_time_ms, 1),
            "snr_db": round(snr, 1),
            "bandwidth_bps": self._bandwidth_bps,
        }

    def range_from_tof(self, propagation_time_s: float) -> float:
        """Compute range from time-of-flight measurement."""
        return propagation_time_s * self._sound_speed

    def ping(self, from_id: str, to_id: str) -> Optional[Dict]:
        """Acoustic ping — measure round-trip time for ranging."""
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        p1, p2 = self._nodes[from_id], self._nodes[to_id]
        true_dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
        if true_dist > self._max_range_m:
            return None

        rtt_s = 2 * true_dist / self._sound_speed
        import numpy as np
        measured_rtt = rtt_s + np.random.normal(0, 0.0001)
        measured_dist = measured_rtt / 2 * self._sound_speed

        return {
            "distance_m": round(measured_dist, 2),
            "rtt_ms": round(measured_rtt * 1000, 2),
            "accuracy_m": 0.15 if self._medium == "water" else 0.05,
        }

    def get_status(self) -> Dict:
        return {
            "medium": self._medium,
            "nodes": len(self._nodes),
            "packets": len(self._packets),
            "sound_speed_ms": self._sound_speed,
            "max_range_m": self._max_range_m,
            "bandwidth_bps": self._bandwidth_bps,
            "frequency_hz": self._freq,
            "rf_silent": True,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
