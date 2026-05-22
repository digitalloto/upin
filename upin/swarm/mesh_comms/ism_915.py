"""
915MHz ISM Band Mesh Communication — UPIN

2km range, 500 kbps. Main mesh backbone for medium-range swarm comms.
Better bandwidth than LoRa, better range than WiFi. The workhorse
radio for most swarm operations.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ISMLink:
    """An active ISM band link."""
    from_node: str
    to_node: str
    rssi_dbm: float
    bandwidth_kbps: float
    distance_m: float
    timestamp: float = field(default_factory=time.time)


class ISM915MeshRadio:
    """915MHz ISM band mesh — medium range, medium bandwidth backbone.

    Sits between LoRa (long range, low bandwidth) and WiFi (short
    range, high bandwidth). Good balance for most swarm operations:
    position updates, sensor summaries, command relay.
    """

    def __init__(self, tx_power_dbm: float = 27.0, channel_bw_khz: float = 500):
        self._tx_power = tx_power_dbm
        self._channel_bw = channel_bw_khz
        self._nodes: Dict[str, Tuple[float, float]] = {}
        self._links: Dict[Tuple[str, str], ISMLink] = {}
        self._max_range_m = 2000.0
        self._max_bandwidth_kbps = 500.0

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)

    def establish_link(self, from_id: str, to_id: str) -> Optional[ISMLink]:
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        p1, p2 = self._nodes[from_id], self._nodes[to_id]
        dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
        if dist > self._max_range_m:
            return None
        path_loss = 32.4 + 20 * math.log10(max(dist, 1)) + 20 * math.log10(915)
        rssi = self._tx_power - path_loss
        bw = self._max_bandwidth_kbps * max(0.1, 1 - dist / self._max_range_m)
        link = ISMLink(from_node=from_id, to_node=to_id, rssi_dbm=rssi,
                       bandwidth_kbps=bw, distance_m=dist)
        self._links[(from_id, to_id)] = link
        return link

    def broadcast(self, from_id: str, payload: Dict) -> List[Dict]:
        """Broadcast to all nodes in range."""
        if from_id not in self._nodes:
            return []
        results = []
        for nid in self._nodes:
            if nid == from_id:
                continue
            link = self.establish_link(from_id, nid)
            if link:
                results.append({
                    "node": nid, "rssi_dbm": round(link.rssi_dbm, 1),
                    "bandwidth_kbps": round(link.bandwidth_kbps, 0),
                    "distance_m": round(link.distance_m, 0),
                })
        return results

    def get_status(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "active_links": len(self._links),
            "tx_power_dbm": self._tx_power,
            "max_range_m": self._max_range_m,
            "max_bandwidth_kbps": self._max_bandwidth_kbps,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
