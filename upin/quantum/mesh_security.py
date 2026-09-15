"""
Quantum mesh security — Q7's QKD laid over the multi-radio failover chain.

MultiRadioMesh already solves availability. Jam WiFi and it falls to LoRa;
jam LoRa and it falls to IR; jam everything and acoustic still carries. Seven
radios across four distinct physical mechanisms, so no single jammer wins.

It does not solve confidentiality. Whichever radio survives is still carrying
plaintext or classically-encrypted traffic, and classical encryption rests on
a computational assumption — that factoring is hard, or discrete logs are.
Both assumptions expire the day a cryptographically relevant quantum computer
runs Shor's algorithm, and harvest-now-decrypt-later collection means traffic
sent today is already exposed to that future.

This module keys the mesh from physics instead. Keys come from QKD, so an
eavesdropper must measure to learn anything, measurement disturbs the state,
and the disturbance shows up as a raised error rate before any key is used.

The design point worth stating: security is decoupled from which radio
survives. The QKD channel and the data channel need not be the same medium —
key over IR while data goes over LoRa, or key over UWB at close range and
spend that key later over acoustic once the swarm disperses. Key material is
a consumable the mesh carries, not a property of a link.

Composition, not modification. MultiRadioMesh is untouched.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from upin.quantum.qkd import QKDMeshNetwork, QuantumKey
from upin.swarm.multi_radio_mesh import MultiRadioMesh, RadioType

# Radios able to carry quantum states at all. QKD needs single photons or
# entangled pairs, so only the optical paths qualify — everything else can
# carry the resulting key material but cannot generate it.
QKD_CAPABLE_RADIOS = {RadioType.IR_LASER}

# Radios that cannot be jammed by RF means, so a key distributed over them
# survives an adversary who owns the entire radio spectrum.
RF_IMMUNE_RADIOS = {RadioType.IR_LASER, RadioType.ACOUSTIC}


@dataclass
class SecureLink:
    """A mesh link with its key material and the radios involved."""
    from_node: str
    to_node: str
    key_radio: Optional[RadioType]      # where the key was distributed
    data_radio: Optional[RadioType]     # where the traffic flows
    key: Optional[QuantumKey] = None
    established_at: float = field(default_factory=time.time)
    bytes_protected: int = 0

    @property
    def is_secure(self) -> bool:
        return self.key is not None and self.key.is_secure

    @property
    def remaining_bytes(self) -> int:
        return (self.key.remaining_bits // 8) if self.key else 0


class QuantumMeshSecurity:
    """QKD overlay for MultiRadioMesh.

    Keys are distributed over whichever QKD-capable radio is available, then
    spent protecting traffic over whichever radio currently survives jamming.
    """

    def __init__(self, mesh: Optional[MultiRadioMesh] = None,
                 protocol: str = "BB84"):
        self._mesh = mesh or MultiRadioMesh()
        self._qkd = QKDMeshNetwork(protocol=protocol)
        self._links: Dict[Tuple[str, str], SecureLink] = {}
        self._key_distributions = 0
        self._rekeys = 0
        self._exhausted = 0
        self._downgrades = 0

    # -- topology ---------------------------------------------------

    def register_node(self, node_id: str, lat: float, lon: float,
                      radios: Optional[List[RadioType]] = None):
        """Register a node with the underlying mesh.

        Nodes default to carrying an IR terminal alongside the usual radios,
        because without a QKD-capable path there is nothing to key from.
        """
        if radios is None:
            radios = [RadioType.UWB, RadioType.BLE_5, RadioType.LORA_900,
                      RadioType.IR_LASER]
        self._mesh.register_node(node_id, radios)
        if hasattr(self._mesh, "_nodes") and node_id in self._mesh._nodes:
            pass  # MultiRadioMesh tracks radios; positions live in QKD below
        self._qkd_positions = getattr(self, "_qkd_positions", {})
        self._qkd_positions[node_id] = (lat, lon)

    # -- key distribution -------------------------------------------

    def available_qkd_radio(self, node_a: str, node_b: str) -> Optional[RadioType]:
        """Which QKD-capable radio can currently carry a key between two nodes."""
        radios_a = self._mesh._node_radios.get(node_a, {})
        radios_b = self._mesh._node_radios.get(node_b, {})
        for r in self._mesh.PRIORITY_CHAIN:
            if r not in QKD_CAPABLE_RADIOS:
                continue
            if r in radios_a and r in radios_b and r not in self._mesh._jammed_bands:
                return r
        return None

    def distribute_key(self, node_a: str, node_b: str,
                       eavesdropper: bool = False,
                       has_los: bool = True) -> Dict:
        """Establish key material between two nodes over a QKD-capable radio."""
        key_radio = self.available_qkd_radio(node_a, node_b)

        if key_radio is None:
            self._downgrades += 1
            return {
                "keyed": False,
                "reason": "NO_QKD_CAPABLE_RADIO",
                "detail": ("QKD needs an optical path; none available between "
                           f"{node_a} and {node_b}"),
                "fallback": "classical_encryption",
            }
        if key_radio is RadioType.IR_LASER and not has_los:
            self._downgrades += 1
            return {
                "keyed": False,
                "reason": "NO_LINE_OF_SIGHT",
                "detail": "IR/laser QKD requires line of sight",
                "fallback": "classical_encryption",
            }

        key = self._qkd.establish(node_a, node_b, eavesdropper=eavesdropper)
        self._key_distributions += 1

        if not key.is_secure:
            return {
                "keyed": False,
                "reason": "EAVESDROPPER_DETECTED",
                "qber": round(key.qber, 4),
                "key_radio": key_radio.value,
                "detail": (f"QBER {key.qber:.3f} exceeds the security threshold; "
                           "key discarded before use"),
                "fallback": "abort_or_reroute",
            }

        link = SecureLink(from_node=node_a, to_node=node_b,
                          key_radio=key_radio, data_radio=None, key=key)
        self._links[tuple(sorted((node_a, node_b)))] = link
        return {
            "keyed": True,
            "key_radio": key_radio.value,
            "key_bits": key.length_bits,
            "qber": round(key.qber, 4),
            "protocol": key.protocol,
            "rf_immune_key_path": key_radio in RF_IMMUNE_RADIOS,
        }

    # -- protected traffic ------------------------------------------

    def send_secure(self, node_a: str, node_b: str, payload: bytes,
                    distance_m: float = 100.0,
                    has_los: bool = True) -> Dict:
        """Send payload over the best surviving radio, protected by QKD key.

        The key path and the data path are independent. A key distributed over
        IR at close range can protect traffic sent over LoRa fifteen
        kilometres later.
        """
        link = self._links.get(tuple(sorted((node_a, node_b))))
        if link is None or not link.is_secure:
            return {"sent": False, "reason": "NO_SECURE_KEY",
                    "remedy": "call distribute_key first"}

        data_link = self._mesh.establish_link(node_a, node_b,
                                              distance_m=distance_m,
                                              has_los=has_los)
        if data_link is None:
            return {"sent": False, "reason": "NO_RADIO_REACHES",
                    "detail": f"no radio spans {distance_m:.0f} m to {node_b}"}

        enc = self._qkd.encrypt(node_a, node_b, payload)
        if enc is None:
            return {"sent": False, "reason": "KEY_UNUSABLE"}
        if "error" in enc:
            self._exhausted += 1
            return {"sent": False, "reason": enc["error"],
                    "remaining_bits": enc.get("remaining_bits", 0),
                    "required_bits": enc.get("required_bits", 0),
                    "remedy": "redistribute key material"}

        link.data_radio = data_link.radio
        link.bytes_protected += len(payload)

        return {
            "sent": True,
            "bytes": len(payload),
            "key_radio": link.key_radio.value,
            "data_radio": data_link.radio.value,
            "paths_differ": link.key_radio is not data_link.radio,
            "signal_quality": round(data_link.signal_quality, 3),
            "remaining_key_bytes": link.remaining_bytes,
            "security": "information_theoretic",
            "quantum_computer_resistant": True,
        }

    def report_jamming(self, radio: RadioType) -> Dict:
        """Tell the mesh a band is jammed and report the security consequence."""
        self._mesh.report_jamming(radio)
        qkd_lost = radio in QKD_CAPABLE_RADIOS
        return {
            "jammed": radio.value,
            "qkd_capability_lost": qkd_lost,
            "consequence": (
                "No new keys can be distributed; existing key material still "
                "protects traffic until exhausted."
                if qkd_lost else
                "Key distribution unaffected; data reroutes to the next radio."),
            "rf_immune_paths_remaining": sorted(
                r.value for r in RF_IMMUNE_RADIOS
                if r not in self._mesh._jammed_bands),
        }

    def rekey_all(self) -> Dict:
        """Refresh every link that is running low on key material."""
        refreshed, failed = [], []
        for (a, b), link in list(self._links.items()):
            if link.remaining_bytes > 256:
                continue
            res = self.distribute_key(a, b)
            (refreshed if res["keyed"] else failed).append((a, b))
            if res["keyed"]:
                self._rekeys += 1
        return {"refreshed": len(refreshed), "failed": len(failed),
                "links_total": len(self._links)}

    def get_status(self) -> Dict:
        secure = [l for l in self._links.values() if l.is_secure]
        q = self._qkd.get_status()
        return {
            "links_total": len(self._links),
            "links_secure": len(secure),
            "key_distributions": self._key_distributions,
            "rekeys": self._rekeys,
            "key_exhaustions": self._exhausted,
            "classical_downgrades": self._downgrades,
            "total_key_bytes": sum(l.remaining_bytes for l in secure),
            "bytes_protected": sum(l.bytes_protected for l in self._links.values()),
            "protocol": q["protocol"],
            "mean_qber": round(q["mean_qber"], 5),
            "eavesdropper_alerts": q["eavesdropper_alerts"],
            "qkd_capable_radios": sorted(r.value for r in QKD_CAPABLE_RADIOS),
            "rf_immune_radios": sorted(r.value for r in RF_IMMUNE_RADIOS),
            "mesh": self._mesh.get_mesh_status(),
        }
