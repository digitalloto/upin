"""
Multi-Radio Mesh Communications — UPIN

UPIN philosophy applied to comms: if one radio is jammed, another
physics layer takes over. The mesh maintains connectivity across
7 different radio technologies with automatic failover.

Priority chain (fastest fallback):
1. UWB  — 100m, precise ranging + data
2. WiFi Direct — 300m, high bandwidth
3. BLE 5 — 200m, low power
4. LoRa 900MHz — 15km, low bandwidth
5. 915MHz ISM — 2km, medium bandwidth
6. IR/Laser — 1km LOS, unjammable
7. Acoustic — 50m air / 5km underwater

If ALL radios are jammed → pre-programmed formation patterns
(like army ants — no comms needed, just follow rules).

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


class RadioType(Enum):
    UWB = "uwb"                 # 100m, 6.5 Mbps, ranging
    WIFI_DIRECT = "wifi_direct" # 300m, 250 Mbps
    BLE_5 = "ble_5"             # 200m, 2 Mbps
    LORA_900 = "lora_900"       # 15km, 50 kbps
    ISM_915 = "ism_915"         # 2km, 500 kbps
    IR_LASER = "ir_laser"       # 1km LOS, 10 Mbps, unjammable
    ACOUSTIC = "acoustic"       # 50m air / 5km water, 1 kbps


@dataclass
class RadioConfig:
    radio_type: RadioType
    range_m: float
    bandwidth_kbps: float
    power_draw_w: float
    jammable: bool
    requires_los: bool       # line of sight required?
    underwater: bool
    frequency_hopping: bool = False
    active: bool = True
    health: float = 1.0      # 0-1, degrades under jamming


RADIO_SPECS: Dict[RadioType, RadioConfig] = {
    RadioType.UWB: RadioConfig(
        RadioType.UWB, 100, 6500, 0.5, False, False, False),
    RadioType.WIFI_DIRECT: RadioConfig(
        RadioType.WIFI_DIRECT, 300, 250000, 2.0, True, False, False),
    RadioType.BLE_5: RadioConfig(
        RadioType.BLE_5, 200, 2000, 0.1, True, False, False),
    RadioType.LORA_900: RadioConfig(
        RadioType.LORA_900, 15000, 50, 0.5, False, False, False,
        frequency_hopping=True),
    RadioType.ISM_915: RadioConfig(
        RadioType.ISM_915, 2000, 500, 1.0, True, False, False),
    RadioType.IR_LASER: RadioConfig(
        RadioType.IR_LASER, 1000, 10000, 0.3, False, True, False),
    RadioType.ACOUSTIC: RadioConfig(
        RadioType.ACOUSTIC, 50, 1, 0.2, False, False, True),
}


@dataclass
class CommLink:
    """An active communication link between two nodes."""
    from_node: str
    to_node: str
    radio: RadioType
    signal_quality: float = 1.0  # 0-1
    latency_ms: float = 5.0
    established_at: float = field(default_factory=time.time)


class MultiRadioMesh:
    """Multi-radio mesh with automatic failover.

    Each drone has multiple radios. The mesh automatically selects
    the best available radio for each link. If one is jammed,
    it falls to the next in the priority chain.
    """

    PRIORITY_CHAIN = [
        RadioType.UWB, RadioType.WIFI_DIRECT, RadioType.BLE_5,
        RadioType.LORA_900, RadioType.ISM_915, RadioType.IR_LASER,
        RadioType.ACOUSTIC,
    ]

    def __init__(self):
        self._node_radios: Dict[str, Dict[RadioType, RadioConfig]] = {}
        self._active_links: Dict[Tuple[str, str], CommLink] = {}
        self._jammed_bands: set = set()
        self._comms_log: List[Dict] = []

    def register_node(self, node_id: str,
                      radios: Optional[List[RadioType]] = None):
        """Register a node's available radios."""
        if radios is None:
            radios = [RadioType.UWB, RadioType.BLE_5, RadioType.LORA_900]
        self._node_radios[node_id] = {}
        for r in radios:
            spec = RADIO_SPECS[r]
            self._node_radios[node_id][r] = RadioConfig(
                radio_type=spec.radio_type,
                range_m=spec.range_m,
                bandwidth_kbps=spec.bandwidth_kbps,
                power_draw_w=spec.power_draw_w,
                jammable=spec.jammable,
                requires_los=spec.requires_los,
                underwater=spec.underwater,
                frequency_hopping=spec.frequency_hopping,
            )

    def report_jamming(self, radio_type: RadioType):
        """Report that a radio band is being jammed."""
        self._jammed_bands.add(radio_type)
        # Degrade all jammable links on this band
        for key, link in self._active_links.items():
            if link.radio == radio_type:
                spec = RADIO_SPECS.get(radio_type)
                if spec and spec.jammable:
                    link.signal_quality = 0.0
        self._failover_all()

    def clear_jamming(self, radio_type: RadioType):
        self._jammed_bands.discard(radio_type)

    def establish_link(self, from_node: str, to_node: str,
                       distance_m: float,
                       has_los: bool = True,
                       underwater: bool = False) -> Optional[CommLink]:
        """Find the best radio for a link and establish it."""
        from_radios = self._node_radios.get(from_node, {})
        to_radios = self._node_radios.get(to_node, {})

        for radio_type in self.PRIORITY_CHAIN:
            if radio_type not in from_radios or radio_type not in to_radios:
                continue
            spec = RADIO_SPECS[radio_type]
            # Check constraints
            if distance_m > spec.range_m:
                continue
            if spec.requires_los and not has_los:
                continue
            if underwater and not spec.underwater:
                continue
            if spec.jammable and radio_type in self._jammed_bands:
                continue

            link = CommLink(
                from_node=from_node, to_node=to_node,
                radio=radio_type,
                signal_quality=max(0.1, 1.0 - distance_m / spec.range_m),
                latency_ms=5.0 + distance_m / 300_000 * 1000,
            )
            self._active_links[(from_node, to_node)] = link
            return link

        return None  # no radio can reach

    def _failover_all(self):
        """Re-establish links that lost their radio due to jamming."""
        for key, link in list(self._active_links.items()):
            if link.signal_quality <= 0:
                # Try next radio in priority chain
                new_link = self.establish_link(
                    link.from_node, link.to_node,
                    distance_m=100.0,  # estimate
                )
                if new_link:
                    self._comms_log.append({
                        "event": "FAILOVER",
                        "from": link.from_node, "to": link.to_node,
                        "old_radio": link.radio.value,
                        "new_radio": new_link.radio.value,
                        "time": time.time(),
                    })

    def get_mesh_status(self) -> Dict:
        active = sum(1 for l in self._active_links.values()
                     if l.signal_quality > 0)
        radios_used = set(l.radio for l in self._active_links.values()
                          if l.signal_quality > 0)
        return {
            "nodes": len(self._node_radios),
            "active_links": active,
            "total_links": len(self._active_links),
            "jammed_bands": [r.value for r in self._jammed_bands],
            "radios_in_use": [r.value for r in radios_used],
            "failovers": sum(1 for e in self._comms_log
                             if e.get("event") == "FAILOVER"),
        }
