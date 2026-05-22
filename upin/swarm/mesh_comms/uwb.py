"""
UWB (Ultra-Wideband) Mesh Communication — UPIN

100m range, 10cm ranging accuracy, 6.5 Mbps bandwidth.
Primary use: precise peer-to-peer ranging for mesh positioning.
Hard to jam (spread across 500MHz+ bandwidth).

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class UWBRanging:
    """One UWB range measurement between two nodes."""
    from_node: str
    to_node: str
    distance_m: float
    timestamp: float
    signal_quality: float = 1.0  # 0-1
    los: bool = True  # line-of-sight


class UWBMeshRadio:
    """UWB mesh radio — precise ranging + data transfer.

    Two-Way Ranging (TWR): node A sends pulse → node B replies →
    round-trip time ÷ 2 × speed_of_light = distance.
    Accuracy: 10cm typical, 1cm in ideal conditions.
    """

    def __init__(self, channel: int = 5, prf_mhz: float = 64.0):
        self._channel = channel
        self._prf = prf_mhz
        self._nodes: Dict[str, Tuple[float, float]] = {}  # id → (lat, lon)
        self._ranges: List[UWBRanging] = []
        self._max_range_m = 100.0
        self._accuracy_m = 0.10

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)

    def perform_ranging(self, from_id: str, to_id: str) -> Optional[UWBRanging]:
        """Perform TWR between two nodes. Returns range measurement."""
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        p1 = self._nodes[from_id]
        p2 = self._nodes[to_id]
        true_dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
        if true_dist > self._max_range_m:
            return None
        import numpy as np
        measured = true_dist + np.random.normal(0, self._accuracy_m)
        quality = max(0.1, 1.0 - true_dist / self._max_range_m)
        ranging = UWBRanging(
            from_node=from_id, to_node=to_id,
            distance_m=max(0, measured), timestamp=time.time(),
            signal_quality=quality, los=true_dist < 50,
        )
        self._ranges.append(ranging)
        return ranging

    def range_all_pairs(self) -> List[UWBRanging]:
        """Range every pair of nodes within range."""
        results = []
        nodes = list(self._nodes.keys())
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                r = self.perform_ranging(nodes[i], nodes[j])
                if r:
                    results.append(r)
        return results

    def get_status(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "ranges_measured": len(self._ranges),
            "channel": self._channel,
            "accuracy_m": self._accuracy_m,
            "max_range_m": self._max_range_m,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
