"""
WiFi Direct Mesh Communication — UPIN

300m range, 250 Mbps, high bandwidth. Primary use: video relay,
bulk sensor data, real-time camera feeds between drones.
Jammable but high throughput for data-intensive operations.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class WiFiDirectLink:
    """A WiFi Direct peer-to-peer connection."""
    from_node: str
    to_node: str
    bandwidth_mbps: float
    rssi_dbm: float
    latency_ms: float
    established_at: float = field(default_factory=time.time)
    bytes_transferred: int = 0


class WiFiDirectMeshRadio:
    """WiFi Direct for high-bandwidth mesh data transfer.

    Supports:
    - Peer-to-peer video streaming (camera feeds between drones)
    - Bulk sensor data relay (LiDAR point clouds, hyperspectral)
    - Group Owner negotiation (one node acts as AP)
    - RTT ranging (Wi-Fi Fine Time Measurement, sub-metre)
    """

    def __init__(self, channel: int = 36, bandwidth_mhz: int = 80):
        self._channel = channel
        self._bandwidth_mhz = bandwidth_mhz
        self._nodes: Dict[str, Tuple[float, float]] = {}
        self._links: Dict[Tuple[str, str], WiFiDirectLink] = {}
        self._max_range_m = 300.0
        self._group_owner: Optional[str] = None

    def register_node(self, node_id: str, lat: float, lon: float):
        self._nodes[node_id] = (lat, lon)
        if self._group_owner is None:
            self._group_owner = node_id

    def establish_link(self, from_id: str, to_id: str) -> Optional[WiFiDirectLink]:
        """Establish a WiFi Direct link between two nodes."""
        if from_id not in self._nodes or to_id not in self._nodes:
            return None
        p1 = self._nodes[from_id]
        p2 = self._nodes[to_id]
        dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
        if dist > self._max_range_m:
            return None

        rssi = -30 - 20 * math.log10(max(dist, 1))
        bw = max(1.0, 250.0 * (1 - dist / self._max_range_m))
        latency = 1.0 + dist / 3e8 * 1000

        link = WiFiDirectLink(
            from_node=from_id, to_node=to_id,
            bandwidth_mbps=bw, rssi_dbm=rssi, latency_ms=latency,
        )
        self._links[(from_id, to_id)] = link
        return link

    def send_data(self, from_id: str, to_id: str, size_bytes: int) -> Optional[Dict]:
        """Send data over an established link."""
        key = (from_id, to_id)
        if key not in self._links:
            link = self.establish_link(from_id, to_id)
            if not link:
                return None
        link = self._links[key]
        transfer_time_ms = size_bytes / (link.bandwidth_mbps * 125_000) * 1000
        link.bytes_transferred += size_bytes
        return {
            "from": from_id, "to": to_id,
            "size_bytes": size_bytes,
            "transfer_time_ms": round(transfer_time_ms, 1),
            "bandwidth_mbps": round(link.bandwidth_mbps, 1),
        }

    def stream_video(self, from_id: str, to_id: str,
                     resolution: str = "1080p") -> Optional[Dict]:
        """Start a video stream (camera relay between drones)."""
        bitrates = {"480p": 2, "720p": 5, "1080p": 10, "4k": 25}
        bitrate_mbps = bitrates.get(resolution, 10)
        key = (from_id, to_id)
        if key not in self._links:
            link = self.establish_link(from_id, to_id)
            if not link:
                return None
        link = self._links[key]
        can_stream = link.bandwidth_mbps >= bitrate_mbps
        return {
            "streaming": can_stream,
            "resolution": resolution,
            "bitrate_mbps": bitrate_mbps,
            "available_bw_mbps": round(link.bandwidth_mbps, 1),
            "latency_ms": round(link.latency_ms, 1),
        }

    def get_status(self) -> Dict:
        total_bytes = sum(l.bytes_transferred for l in self._links.values())
        return {
            "nodes": len(self._nodes),
            "active_links": len(self._links),
            "group_owner": self._group_owner,
            "total_bytes_transferred": total_bytes,
            "channel": self._channel,
            "max_range_m": self._max_range_m,
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1; dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
