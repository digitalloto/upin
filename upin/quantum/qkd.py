"""
Quantum key distribution for the UPIN mesh.

Classical swarm encryption rests on a computational assumption: that
factoring is hard, or that discrete logarithms are hard. Both assumptions
expire the day a cryptographically relevant quantum computer exists, and
both are vulnerable today to harvest-now-decrypt-later collection.

QKD rests on physics instead. An eavesdropper must measure to learn anything,
measurement disturbs the state, and the disturbance shows up as a raised error
rate. The swarm does not detect interception by clever analysis — it detects
it because quantum mechanics leaves a mark.

Two protocols are implemented:
  BB84  (Bennett & Brassard 1984) — prepare-and-measure, four states
  E91   (Ekert 1991)              — entanglement-based, security certified
                                    by violation of the CHSH inequality

Security thresholds used here:
  BB84 intercept-resend attack gives QBER = 25%
  One-way postprocessing tolerates QBER < 11%
  CHSH S > 2 rules out local hidden variables; Tsirelson bound is 2*sqrt(2)

References (verify before external citation):
  Bennett & Brassard, Proc. IEEE ICCSSP, 175 (1984)
  Ekert, PRL 67, 661 (1991)
  Shor & Preskill, PRL 85, 441 (2000)   — BB84 security proof
  Clauser, Horne, Shimony, Holt, PRL 23, 880 (1969)

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.quantum.metrology import binary_entropy

QBER_SECURITY_THRESHOLD = 0.11
QBER_INTERCEPT_RESEND = 0.25
TSIRELSON_BOUND = 2.0 * math.sqrt(2.0)


@dataclass
class QuantumKey:
    """A distilled symmetric key with its security provenance."""
    key_id: str
    node_a: str
    node_b: str
    key_bytes: bytes
    length_bits: int
    qber: float
    protocol: str
    created_at: float = field(default_factory=time.time)
    eavesdropper_detected: bool = False
    chsh_value: Optional[float] = None
    consumed_bits: int = 0

    @property
    def remaining_bits(self) -> int:
        return max(0, self.length_bits - self.consumed_bits)

    @property
    def is_secure(self) -> bool:
        return (not self.eavesdropper_detected) and self.qber < QBER_SECURITY_THRESHOLD


class BB84:
    """Prepare-and-measure QKD.

    Alice picks a random bit and a random basis; Bob picks a random basis.
    They keep only the rounds where the bases matched — the sifted key — then
    sacrifice a sample of it to estimate the error rate. An eavesdropper who
    measures in the wrong basis half the time and resends drives the QBER to
    25%, far above the 11% at which a secret key can still be distilled.
    """

    def __init__(self, channel_error_rate: float = 0.02,
                 detector_efficiency: float = 0.9):
        self._channel_error = channel_error_rate
        self._eta = detector_efficiency
        self._sessions = 0

    def exchange(self, node_a: str, node_b: str, raw_bits: int = 4096,
                 eavesdropper: bool = False) -> QuantumKey:
        rng = np.random.default_rng()
        a_bits = rng.integers(0, 2, raw_bits)
        a_basis = rng.integers(0, 2, raw_bits)
        b_basis = rng.integers(0, 2, raw_bits)

        detected = rng.random(raw_bits) < self._eta
        matching = (a_basis == b_basis) & detected
        n_sift = int(matching.sum())
        if n_sift < 64:
            return self._empty_key(node_a, node_b, "BB84")

        sifted_a = a_bits[matching]
        errors = rng.random(n_sift) < self._channel_error
        if eavesdropper:
            # Eve measures in a random basis; wrong half the time, and then
            # randomises Bob's outcome — 25% net error on sifted bits.
            wrong_basis = rng.random(n_sift) < 0.5
            errors = errors | (wrong_basis & (rng.random(n_sift) < 0.5))
        sifted_b = sifted_a ^ errors.astype(int)

        # Sacrifice a quarter of the sifted key to estimate QBER
        n_test = max(32, n_sift // 4)
        idx = rng.permutation(n_sift)
        test, keep = idx[:n_test], idx[n_test:]
        qber = float((sifted_a[test] != sifted_b[test]).mean())

        eve = qber > QBER_SECURITY_THRESHOLD
        # Privacy amplification: shrink by the information Eve could hold
        leak = binary_entropy(qber)
        final_bits = 0 if eve else max(0, int(len(keep) * (1.0 - 2.0 * leak)))

        key_bytes = b""
        if final_bits >= 128:
            raw = "".join(str(int(b)) for b in sifted_a[keep][:final_bits])
            key_bytes = hashlib.shake_256(raw.encode()).digest(final_bits // 8)

        self._sessions += 1
        return QuantumKey(
            key_id=f"QK-{self._sessions:06d}",
            node_a=node_a, node_b=node_b,
            key_bytes=key_bytes,
            length_bits=len(key_bytes) * 8,
            qber=qber, protocol="BB84",
            eavesdropper_detected=eve,
        )

    def _empty_key(self, a: str, b: str, proto: str) -> QuantumKey:
        self._sessions += 1
        return QuantumKey(key_id=f"QK-{self._sessions:06d}", node_a=a, node_b=b,
                          key_bytes=b"", length_bits=0, qber=1.0,
                          protocol=proto, eavesdropper_detected=True)


class E91:
    """Entanglement-based QKD with a Bell-inequality security certificate.

    The pair source need not be trusted. If the measured CHSH parameter
    exceeds 2, no local hidden-variable model — and therefore no eavesdropper
    holding a classical copy — can explain the correlations.
    """

    def __init__(self, pair_fidelity: float = 0.97):
        self._fidelity = pair_fidelity
        self._sessions = 0

    def chsh(self, fidelity: float) -> float:
        """Werner state of fidelity F gives S = 2*sqrt(2)*(4F-1)/3."""
        visibility = max(0.0, (4.0 * fidelity - 1.0) / 3.0)
        return TSIRELSON_BOUND * visibility

    def exchange(self, node_a: str, node_b: str, pairs: int = 4096,
                 eavesdropper: bool = False) -> QuantumKey:
        fidelity = self._fidelity * (0.72 if eavesdropper else 1.0)
        s = self.chsh(fidelity)
        qber = max(0.0, (1.0 - fidelity) * 0.75 + (0.18 if eavesdropper else 0.0))

        bell_violated = s > 2.0
        eve = (not bell_violated) or qber > QBER_SECURITY_THRESHOLD

        usable = pairs // 2                      # half spent on the CHSH test
        leak = binary_entropy(qber)
        final_bits = 0 if eve else max(0, int(usable * (1.0 - 2.0 * leak)))

        key_bytes = b""
        if final_bits >= 128:
            seed = f"{node_a}|{node_b}|{secrets.token_hex(16)}"
            key_bytes = hashlib.shake_256(seed.encode()).digest(final_bits // 8)

        self._sessions += 1
        return QuantumKey(
            key_id=f"QE-{self._sessions:06d}",
            node_a=node_a, node_b=node_b,
            key_bytes=key_bytes, length_bits=len(key_bytes) * 8,
            qber=qber, protocol="E91",
            eavesdropper_detected=eve, chsh_value=s,
        )


class QKDMeshNetwork:
    """Key management for the swarm.

    Keys are a consumable. One-time-pad usage burns key material bit for bit,
    so the network tracks reserves per link and refreshes them before they run
    dry. Where a direct link is impossible, a trusted-node chain relays the
    key — the standard compromise until end-to-end repeaters exist.
    """

    def __init__(self, protocol: str = "BB84"):
        self._bb84 = BB84()
        self._e91 = E91()
        self._protocol = protocol
        self._keys: Dict[Tuple[str, str], QuantumKey] = {}
        self._alerts: List[Dict] = []

    def establish(self, node_a: str, node_b: str,
                  eavesdropper: bool = False) -> QuantumKey:
        key = (self._e91 if self._protocol == "E91" else self._bb84).exchange(
            node_a, node_b, eavesdropper=eavesdropper)
        if key.eavesdropper_detected:
            self._alerts.append({
                "time": time.time(), "link": (node_a, node_b),
                "qber": key.qber, "protocol": key.protocol,
                "action": "KEY_REJECTED_EAVESDROPPER_DETECTED",
            })
        else:
            self._keys[tuple(sorted((node_a, node_b)))] = key
        return key

    def encrypt(self, node_a: str, node_b: str, plaintext: bytes) -> Optional[Dict]:
        """One-time pad. Information-theoretically secure while key remains."""
        k = self._keys.get(tuple(sorted((node_a, node_b))))
        if k is None or not k.is_secure:
            return None
        need = len(plaintext) * 8
        if k.remaining_bits < need:
            return {"error": "KEY_EXHAUSTED", "remaining_bits": k.remaining_bits,
                    "required_bits": need}
        off = k.consumed_bits // 8
        pad = k.key_bytes[off:off + len(plaintext)]
        if len(pad) < len(plaintext):
            return {"error": "KEY_EXHAUSTED", "remaining_bits": k.remaining_bits,
                    "required_bits": need}
        k.consumed_bits += need
        return {
            "ciphertext": bytes(a ^ b for a, b in zip(plaintext, pad)),
            "key_id": k.key_id,
            "remaining_bits": k.remaining_bits,
            "security": "information_theoretic",
        }

    def relay_key(self, path: List[str]) -> Optional[Dict]:
        """Trusted-node key relay along a multi-hop path."""
        if len(path) < 3:
            return None
        hops = []
        for a, b in zip(path, path[1:]):
            k = self.establish(a, b)
            if not k.is_secure:
                return {"error": "HOP_INSECURE", "failed_link": (a, b),
                        "qber": k.qber}
            hops.append(k.key_id)
        return {
            "path": path, "hops": len(hops), "hop_key_ids": hops,
            "end_to_end": (path[0], path[-1]),
            "trust_model": "trusted_relay_nodes",
        }

    def get_status(self) -> Dict:
        secure = [k for k in self._keys.values() if k.is_secure]
        return {
            "protocol": self._protocol,
            "links_keyed": len(self._keys),
            "links_secure": len(secure),
            "total_key_bits": sum(k.remaining_bits for k in secure),
            "mean_qber": float(np.mean([k.qber for k in secure])) if secure else 0.0,
            "eavesdropper_alerts": len(self._alerts),
            "recent_alerts": self._alerts[-5:],
        }
