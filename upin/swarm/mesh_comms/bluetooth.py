"""
Bluetooth 5 Mesh Communication — UPIN

200m range, 2 Mbps, low power (0.01W). Primary use: short-range
data exchange, sensor relay, indoor mesh. Jammable but ubiquitous.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class BLEAdvertisement:
    """One BLE advertisement packet."""
    from_node: str
    rssi_dbm: float
    payload: Dict
    timestamp: float = field(default_factory=time.time)


class BluetoothMeshRadio:
    """Bluetooth 5 mesh for low-power data relay.

    Supports:
    - RSSI-based ranging (3-5m accuracy)
    - Angle of Arrival (sub-metre with BLE 5.1)
    - Mesh relay (multi-hop message forwarding)
    - Sensor data broadcast (low bandwidth, low power)
    """

    def __init__(self, tx_power_dbm: int = 0):
        self._tx_power = tx_power_dbm
        self._nodes: Dict[str, Tuple[float, float]] = {}
        self._advertisements: List[BLEAdvertisement] = []
        self._max_range_m = 200.0
        self._path_loss_n = 2.5

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)

    def advertise(self, from_id: str, payload: Dict) -> List[Dict]:
        """Broadcast an advertisement — all nodes in range receive it."""
        if from_id not in self._nodes:
            return []
        from_pos = self._nodes[from_id]
        received_by = []
        for to_id, to_pos in self._nodes.items():
            if to_id == from_id:
                continue
            dist = _haversine_m(from_pos[0], from_pos[1], to_pos[0], to_pos[1])
            if dist > self._max_range_m:
                continue
            rssi = self._tx_power - 40 - 10 * self._path_loss_n * math.log10(max(dist, 1))
            adv = BLEAdvertisement(from_node=from_id, rssi_dbm=rssi, payload=payload)
            self._advertisements.append(adv)
            received_by.append({
                "node": to_id, "rssi_dbm": round(rssi, 1),
                "distance_m": round(dist, 1),
            })
        return received_by

    def estimate_distance(self, rssi_dbm: float) -> float:
        """Estimate distance from RSSI using path-loss model."""
        return 10 ** ((self._tx_power - 40 - rssi_dbm) / (10 * self._path_loss_n))

    def get_status(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "advertisements": len(self._advertisements),
            "tx_power_dbm": self._tx_power,
            "max_range_m": self._max_range_m,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
