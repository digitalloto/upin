"""
Entanglement distribution across a UPIN swarm.

This is the module that separates a quantum navigation SYSTEM from a platform
that merely carries quantum sensors. Everyone building "quantum navigation"
today is building better individual boxes — atom interferometers, NV
magnetometers, optical clocks. Each box is quantum inside and classical
outside: it produces a number, and that number is fused classically.

UPIN entangles the boxes with each other.

Three consequences follow, and all three are navigation capabilities:

  1. Precision.   N entangled sensors estimate a shared field or rotation
                  sqrt(N) times better than N independent ones.

  2. Unspoofable ranging.  The no-cloning theorem forbids copying an unknown
                  quantum state. An adversary cannot manufacture a convincing
                  entangled range measurement, and any attempt to intercept
                  one raises the error rate in a way the receiver detects.

  3. Distributed clocks.  Entangled clock networks synchronise below the
                  standard quantum limit, which directly tightens every
                  time-of-arrival position fix the swarm computes.

Entanglement is a consumable. It is generated, distributed, consumed by
measurement, and lost to decoherence. This module tracks that budget the way
a fuel system tracks fuel, because in practice it is the binding constraint.

References (verify before external citation):
  Briegel et al., PRL 81, 5932 (1998)          — quantum repeaters
  Komar et al., Nature Physics 10, 582 (2014)  — quantum clock network
  Gottesman, Jennewein, Croke, PRL 109, 070503 (2012) — quantum telescope
  Wootters & Zurek, Nature 299, 802 (1982)     — no-cloning theorem

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

C_LIGHT = 299_792_458.0


@dataclass
class EntangledPair:
    """One distributed Bell pair shared between two nodes."""
    pair_id: str
    node_a: str
    node_b: str
    created_at: float
    fidelity: float = 0.99              # F = <Φ+|ρ|Φ+>
    consumed: bool = False
    separation_m: float = 0.0

    def current_fidelity(self, t2_s: float, now: Optional[float] = None) -> float:
        """Fidelity decays toward the classical floor of 0.25."""
        now = now if now is not None else time.time()
        age = max(0.0, now - self.created_at)
        decay = math.exp(-age / t2_s) if t2_s > 0 else 0.0
        return 0.25 + (self.fidelity - 0.25) * decay

    def is_usable(self, t2_s: float, threshold: float = 0.5,
                  now: Optional[float] = None) -> bool:
        """Below F = 0.5 a Bell pair carries no distillable entanglement."""
        return (not self.consumed) and self.current_fidelity(t2_s, now) > threshold


class EntanglementDistributor:
    """Generates and books out Bell pairs across the swarm.

    Distribution over free space is lossy: transmission falls as exp(-L/L_att)
    plus geometric beam spread, so pair rate falls sharply with separation.
    Entanglement swapping through a relay node extends reach at the cost of
    fidelity, which is exactly the quantum-repeater trade.
    """

    def __init__(self, source_rate_hz: float = 1e6,
                 t2_coherence_s: float = 1.0,
                 attenuation_length_m: float = 20_000.0,
                 detector_efficiency: float = 0.8):
        self._source_rate = source_rate_hz
        self._t2 = t2_coherence_s
        self._l_att = attenuation_length_m
        self._eta_det = detector_efficiency
        self._pairs: Dict[str, EntangledPair] = {}
        self._nodes: Dict[str, Tuple[float, float, float]] = {}
        self._counter = 0
        self._generated = 0
        self._consumed = 0
        self._expired = 0

    def register_node(self, node_id: str, lat: float, lon: float, alt: float = 0.0):
        self._nodes[node_id] = (lat, lon, alt)

    def channel_transmission(self, separation_m: float) -> float:
        """Combined absorption and geometric loss for a free-space link."""
        absorption = math.exp(-separation_m / self._l_att)
        geometric = 1.0 / (1.0 + (separation_m / 5_000.0) ** 2)
        return absorption * geometric * self._eta_det

    def pair_rate(self, node_a: str, node_b: str) -> float:
        """Usable entangled pairs per second between two nodes."""
        if node_a not in self._nodes or node_b not in self._nodes:
            return 0.0
        sep = self._separation(node_a, node_b)
        return self._source_rate * self.channel_transmission(sep) ** 2

    def distribute(self, node_a: str, node_b: str,
                   count: int = 1) -> List[EntangledPair]:
        """Attempt to establish `count` Bell pairs between two nodes."""
        if node_a not in self._nodes or node_b not in self._nodes:
            return []
        sep = self._separation(node_a, node_b)
        eta = self.channel_transmission(sep)
        # Fidelity degrades with channel loss
        fidelity = 0.25 + 0.74 * eta
        made: List[EntangledPair] = []
        for _ in range(max(0, count)):
            if np.random.random() > eta:
                continue                       # pair lost in the channel
            self._counter += 1
            p = EntangledPair(
                pair_id=f"EPR-{self._counter:08d}",
                node_a=node_a, node_b=node_b,
                created_at=time.time(),
                fidelity=fidelity,
                separation_m=sep,
            )
            self._pairs[p.pair_id] = p
            made.append(p)
            self._generated += 1
        return made

    def swap(self, pair_ac: str, pair_cb: str, relay: str) -> Optional[EntangledPair]:
        """Entanglement swapping A-C + C-B -> A-B via a Bell measurement at C.

        Fidelities multiply, which is why long chains need purification.
        """
        pa, pb = self._pairs.get(pair_ac), self._pairs.get(pair_cb)
        if pa is None or pb is None or pa.consumed or pb.consumed:
            return None
        ends = ({pa.node_a, pa.node_b} | {pb.node_a, pb.node_b}) - {relay}
        if len(ends) != 2:
            return None
        a, b = sorted(ends)
        fa = pa.current_fidelity(self._t2)
        fb = pb.current_fidelity(self._t2)
        pa.consumed = pb.consumed = True
        self._consumed += 2
        self._counter += 1
        swapped = EntangledPair(
            pair_id=f"EPR-{self._counter:08d}",
            node_a=a, node_b=b, created_at=time.time(),
            fidelity=max(0.25, fa * fb),
            separation_m=pa.separation_m + pb.separation_m,
        )
        self._pairs[swapped.pair_id] = swapped
        return swapped

    def purify(self, pair_ids: List[str]) -> Optional[EntangledPair]:
        """Sacrifice several noisy pairs for one better pair (BBPSSW).

        Two pairs of fidelity F yield one of roughly
        F' = (F² + ((1-F)/3)²) / (F² + 2F(1-F)/3 + 5((1-F)/3)²),
        which exceeds F whenever F > 0.5.
        """
        usable = [self._pairs[i] for i in pair_ids
                  if i in self._pairs and self._pairs[i].is_usable(self._t2)]
        if len(usable) < 2:
            return None
        f = usable[0].current_fidelity(self._t2)
        for nxt in usable[1:]:
            g = nxt.current_fidelity(self._t2)
            num = f * g + ((1 - f) / 3) * ((1 - g) / 3)
            den = f * g + f * (1 - g) / 3 + g * (1 - f) / 3 + 5 * ((1 - f) / 3) * ((1 - g) / 3)
            f = num / den if den > 0 else f
        for p in usable[1:]:
            p.consumed = True
            self._consumed += 1
        best = usable[0]
        best.fidelity = min(0.999, f)
        best.created_at = time.time()
        return best

    def consume(self, pair_id: str) -> Optional[float]:
        """Use a pair for a measurement. Returns the fidelity at use time."""
        p = self._pairs.get(pair_id)
        if p is None or p.consumed:
            return None
        f = p.current_fidelity(self._t2)
        p.consumed = True
        self._consumed += 1
        return f

    def prune(self):
        """Drop pairs that have decohered past usefulness."""
        now = time.time()
        dead = [i for i, p in self._pairs.items()
                if not p.consumed and not p.is_usable(self._t2, now=now)]
        for i in dead:
            del self._pairs[i]
            self._expired += 1

    def available(self, node_a: Optional[str] = None,
                  node_b: Optional[str] = None) -> List[EntangledPair]:
        now = time.time()
        out = []
        for p in self._pairs.values():
            if not p.is_usable(self._t2, now=now):
                continue
            if node_a and node_b:
                if {p.node_a, p.node_b} != {node_a, node_b}:
                    continue
            elif node_a and node_a not in (p.node_a, p.node_b):
                continue
            out.append(p)
        return out

    def _separation(self, a: str, b: str) -> float:
        pa, pb = self._nodes[a], self._nodes[b]
        return _haversine_3d(pa, pb)

    def get_status(self) -> Dict:
        live = self.available()
        fids = [p.current_fidelity(self._t2) for p in live]
        return {
            "nodes": len(self._nodes),
            "pairs_live": len(live),
            "pairs_generated": self._generated,
            "pairs_consumed": self._consumed,
            "pairs_expired": self._expired,
            "mean_fidelity": float(np.mean(fids)) if fids else 0.0,
            "t2_coherence_s": self._t2,
            "source_rate_hz": self._source_rate,
        }


class GHZNetwork:
    """Multi-node GHZ states — the resource behind Heisenberg-limited sensing.

    (|00...0> + |11...1>)/sqrt(2) shared across k nodes. Every node measuring
    the same field contributes phase coherently, so the ensemble estimates
    that field k times better than one node — until dephasing, which is also
    k times faster, takes it back.
    """

    def __init__(self, distributor: EntanglementDistributor):
        self._dist = distributor
        self._states: Dict[str, Dict] = {}
        self._counter = 0

    def create(self, node_ids: List[str], purify_rounds: int = 2,
               pairs_per_link: int = 16) -> Optional[Dict]:
        """Build a GHZ state over the given nodes from a star of Bell pairs.

        GHZ fidelity is the product of the link fidelities, so it collapses
        exponentially in the number of nodes: eleven links at F = 0.84 give
        0.84^11 = 0.15, which wipes out the Heisenberg gain entirely.

        Purification is therefore not optional, it is what makes distributed
        GHZ sensing work at all. Several noisy pairs per link are consumed to
        distil one good pair, raising each link toward F = 0.95+ before the
        star is stitched together.
        """
        if len(node_ids) < 2:
            return None
        hub, leaves = node_ids[0], node_ids[1:]
        fids = []
        for leaf in leaves:
            pairs = self._dist.distribute(hub, leaf, count=pairs_per_link)
            if not pairs:
                return None
            best = max(pairs, key=lambda p: p.fidelity)
            others = [p for p in pairs if p.pair_id != best.pair_id]

            # Distil: each round spends pairs to raise fidelity
            f = best.fidelity
            for _ in range(purify_rounds):
                if not others:
                    break
                partner = others.pop()
                g = partner.fidelity
                partner.consumed = True
                num = f * g + ((1 - f) / 3) * ((1 - g) / 3)
                den = (f * g + f * (1 - g) / 3 + g * (1 - f) / 3
                       + 5 * ((1 - f) / 3) * ((1 - g) / 3))
                if den > 0:
                    f = min(0.999, num / den)
            best.fidelity = f
            fids.append(f)
            for p in others:
                p.consumed = True

        fidelity = float(np.prod(fids))
        self._counter += 1
        gid = f"GHZ-{self._counter:06d}"
        st = {
            "ghz_id": gid,
            "nodes": list(node_ids),
            "size": len(node_ids),
            "fidelity": fidelity,
            "created_at": time.time(),
            # an N-body GHZ state dephases N times faster
            "effective_t2_s": self._dist._t2 / len(node_ids),
            "consumed": False,
        }
        self._states[gid] = st
        return st

    def measure(self, ghz_id: str, true_phase_rad: float) -> Optional[Dict]:
        """Consume a GHZ state to estimate a phase at the Heisenberg limit."""
        st = self._states.get(ghz_id)
        if st is None or st["consumed"]:
            return None
        st["consumed"] = True
        n = st["size"]
        age = time.time() - st["created_at"]
        contrast = st["fidelity"] * math.exp(-age / max(st["effective_t2_s"], 1e-9))
        contrast = max(contrast, 1e-6)

        sigma = 1.0 / (n * contrast)
        estimate = true_phase_rad + np.random.normal(0.0, sigma)
        sql = 1.0 / math.sqrt(n)
        return {
            "ghz_id": ghz_id,
            "size": n,
            "phase_estimate_rad": float(estimate),
            "uncertainty_rad": sigma,
            "sql_uncertainty_rad": sql,
            "advantage_over_sql": sql / sigma if sigma > 0 else 0.0,
            "beats_sql": sigma < sql,
            "contrast": contrast,
        }

    def get_status(self) -> Dict:
        live = [s for s in self._states.values() if not s["consumed"]]
        return {
            "states_created": self._counter,
            "states_live": len(live),
            "largest_live": max((s["size"] for s in live), default=0),
        }


def no_cloning_verification(measured_fidelity: float,
                            expected_fidelity: float,
                            tolerance: float = 0.05) -> Dict:
    """Detect interception of an entangled ranging signal.

    An adversary who measures and retransmits cannot reproduce the original
    state — the no-cloning theorem forbids it. The optimal universal cloner
    is capped at F = 5/6 ≈ 0.833, so a measured fidelity that sits at or below
    that ceiling while the link should be delivering better is the signature
    of an intercept-resend attack.
    """
    clone_ceiling = 5.0 / 6.0
    shortfall = expected_fidelity - measured_fidelity
    intercepted = (measured_fidelity <= clone_ceiling + tolerance
                   and expected_fidelity > clone_ceiling + tolerance)
    return {
        "measured_fidelity": measured_fidelity,
        "expected_fidelity": expected_fidelity,
        "optimal_cloner_limit": clone_ceiling,
        "fidelity_shortfall": shortfall,
        "interception_detected": intercepted or shortfall > 0.15,
        "confidence": min(1.0, max(0.0, shortfall / 0.3)),
        "verdict": "INTERCEPTED" if intercepted else (
            "DEGRADED" if shortfall > 0.15 else "AUTHENTIC"),
    }


def _haversine_3d(a: Tuple[float, float, float],
                  b: Tuple[float, float, float]) -> float:
    R = 6_371_000.0
    lat1, lon1, alt1 = a
    lat2, lon2, alt2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    ground = R * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))
    return math.sqrt(ground ** 2 + (alt2 - alt1) ** 2)
