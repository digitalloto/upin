"""
LoRa 900MHz Mesh Communication — UPIN

15km range, 50 kbps, frequency hopping spread spectrum.
Primary use: long-range position sharing across mountains/valleys.
Hard to jam. Solar-powered beacons on mountain tops.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LoRaPacket:
    """One LoRa transmission."""
    from_node: str
    to_node: str  # "broadcast" for all
    payload: Dict
    rssi_dbm: float = -90.0
    snr_db: float = 10.0
    spreading_factor: int = 7  # SF7-SF12
    frequency_mhz: float = 915.0
    timestamp: float = field(default_factory=time.time)
    hop_count: int = 0


class LoRaMeshRadio:
    """LoRa 900MHz mesh for long-range low-bandwidth communication.

    Key properties:
    - 15km+ range (mountain-top to valley)
    - Low bandwidth (50 kbps at SF7, 0.3 kbps at SF12)
    - Frequency hopping makes jamming very difficult
    - Solar-powered beacons can run indefinitely
    - Higher spreading factor = longer range but slower

    Adaptive SF: auto-select spreading factor based on distance.
    Close nodes use SF7 (fast). Far nodes use SF12 (slow but reliable).
    """

    def __init__(self, frequency_mhz: float = 915.0, tx_power_dbm: float = 20.0):
        self._freq = frequency_mhz
        self._tx_power = tx_power_dbm
        self._nodes: Dict[str, Tuple[float, float]] = {}
        self._packets: List[LoRaPacket] = []
        self._max_range_m = 15_000.0

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)

    def select_spreading_factor(self, distance_m: float) -> int:
        """Auto-select SF based on distance. Longer = higher SF."""
        if distance_m < 2000:
            return 7
        elif distance_m < 5000:
            return 8
        elif distance_m < 8000:
            return 9
        elif distance_m < 11000:
            return 10
        elif distance_m < 13000:
            return 11
        return 12

    def get_data_rate_bps(self, sf: int) -> float:
        """Data rate for a given spreading factor."""
        rates = {7: 50000, 8: 25000, 9: 12500, 10: 6250,
                 11: 3125, 12: 1562}
        return rates.get(sf, 1562)

    def send(self, from_id: str, payload: Dict,
             to_id: str = "broadcast") -> List[Dict]:
        """Send a LoRa packet. Returns list of nodes that received it."""
        if from_id not in self._nodes:
            return []
        from_pos = self._nodes[from_id]
        received = []

        targets = ([(to_id, self._nodes[to_id])] if to_id != "broadcast"
                   else [(nid, pos) for nid, pos in self._nodes.items()
                         if nid != from_id])

        for nid, pos in targets:
            dist = _haversine_m(from_pos[0], from_pos[1], pos[0], pos[1])
            if dist > self._max_range_m:
                continue

            sf = self.select_spreading_factor(dist)
            # Path loss model for sub-GHz
            path_loss = 44.9 + 6.55 * math.log10(max(dist, 1))
            rssi = self._tx_power - path_loss
            snr = rssi + 120  # rough SNR estimate

            pkt = LoRaPacket(
                from_node=from_id, to_node=nid, payload=payload,
                rssi_dbm=rssi, snr_db=snr, spreading_factor=sf,
                frequency_mhz=self._freq,
            )
            self._packets.append(pkt)
            received.append({
                "node": nid, "distance_m": round(dist, 0),
                "rssi_dbm": round(rssi, 1), "sf": sf,
                "data_rate_bps": self.get_data_rate_bps(sf),
            })
        return received

    def send_position(self, from_id: str, lat: float, lon: float,
                      alt: float = 0.0) -> List[Dict]:
        """Broadcast position over LoRa — minimal packet for max range."""
        return self.send(from_id, {
            "type": "position", "lat": lat, "lon": lon, "alt": alt,
        })

    def get_status(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "packets_sent": len(self._packets),
            "frequency_mhz": self._freq,
            "tx_power_dbm": self._tx_power,
            "max_range_m": self._max_range_m,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
