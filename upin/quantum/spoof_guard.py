"""
Quantum spoof guard — Q1's no-cloning verdict joined to the classical checks.

UPIN's AntiSpoofDetector runs five checks: signal strength spike, teleport,
tower mismatch, IMU mismatch and precision anomaly. Every one of them is
*statistical*. They infer an attack from inconsistency, which means two
things follow inevitably:

  false negatives   a patient, well-resourced spoofer who walks the target
                    slowly and keeps every observable self-consistent passes
                    all five checks
  false positives   a genuine hard manoeuvre, a tunnel exit, or a real
                    multipath event can trip them

The quantum check is different in kind, not degree. The no-cloning theorem
forbids copying an unknown quantum state, and the optimal universal cloner
is capped at fidelity 5/6 = 0.8333. A spoofer who intercepts and retransmits
cannot exceed that ceiling no matter how much money or patience they have.
So this is not evidence of an attack — it is proof of one.

That asymmetry earns the quantum check two powers the classical five do not
have:

  VETO    an INTERCEPTED verdict rejects the fix outright, whatever the
          classical score says, because physics has settled the question

  CLEAR   an AUTHENTIC verdict at high fidelity can discount a classical
          flag, because a channel proven un-tampered makes a "teleport"
          far more likely to be a real manoeuvre than an attack

Composition, not modification. AntiSpoofDetector is untouched; this wraps it.
A platform with no entangled ranging never constructs this guard and the
five classical checks behave exactly as they do today.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from upin.core.layer_base import LayerReading
from upin.detection.anti_spoof import AntiSpoofDetector

# Optimal universal cloning machine fidelity limit for an unknown qubit.
CLONER_CEILING = 5.0 / 6.0

# Fidelity above which a channel is considered proven un-tampered.
AUTHENTIC_FIDELITY = 0.90


@dataclass
class QuantumVerdict:
    """The quantum channel's opinion on whether the fix is genuine."""
    available: bool
    verdict: str                     # AUTHENTIC | DEGRADED | INTERCEPTED | UNAVAILABLE
    measured_fidelity: float = 0.0
    expected_fidelity: float = 0.0
    anchors_ranged: int = 0
    confidence: float = 0.0
    is_proof: bool = False           # True only when physics settles it


@dataclass
class GuardResult:
    """Combined classical + quantum spoofing assessment."""
    is_spoofed: bool
    action: str
    classical_score: float
    final_score: float
    quantum: QuantumVerdict
    classical_alerts: List[Dict] = field(default_factory=list)
    quantum_override: Optional[str] = None   # VETO | CLEAR | None
    reasoning: str = ""


class QuantumSpoofGuard:
    """Wraps AntiSpoofDetector and adds the Q1 no-cloning check on top."""

    VETO_SCORE = 100.0          # an interception is conclusive
    CLEAR_DISCOUNT = 0.45       # how far a proven channel discounts a flag
    # Above this classical score, CLEAR no longer applies. A proven-clean
    # ranging channel explains one anomalous observable — a genuine manoeuvre
    # tripping the teleport check. It does not explain several independent
    # checks firing together, which is what a high score means. Beyond this
    # ceiling the classical evidence stands on its own.
    CLEAR_CEILING = 50.0

    def __init__(self, detector: Optional[AntiSpoofDetector] = None,
                 threshold: float = 40.0,
                 allow_clear: bool = True):
        self._detector = detector or AntiSpoofDetector(threshold=threshold)
        self._threshold = threshold
        self._allow_clear = allow_clear
        self._vetoes = 0
        self._clears = 0
        self._checks = 0
        self._last: Optional[GuardResult] = None

    # -- quantum evidence -------------------------------------------

    @staticmethod
    def read_q1(q1_reading: Optional[LayerReading]) -> QuantumVerdict:
        """Extract the no-cloning verdict from an entangled-ranging reading."""
        if q1_reading is None or not q1_reading.raw_data:
            return QuantumVerdict(available=False, verdict="UNAVAILABLE")
        d = q1_reading.raw_data
        verdict = d.get("no_cloning_verdict")
        if verdict is None:
            return QuantumVerdict(available=False, verdict="UNAVAILABLE")

        measured = float(d.get("mean_bell_fidelity", 0.0))
        expected = float(d.get("expected_channel_fidelity", 0.0))
        anchors = int(d.get("anchors_ranged", 0))

        # An interception verdict is only proof if enough anchors agreed and
        # the channel should have delivered better than the cloner ceiling.
        is_proof = (verdict == "INTERCEPTED"
                    and anchors >= 3
                    and expected > CLONER_CEILING + 0.02)

        if verdict == "INTERCEPTED":
            conf = min(1.0, max(0.0, (expected - measured) / 0.3))
        elif verdict == "AUTHENTIC":
            conf = min(1.0, measured / max(expected, 1e-9))
        else:
            conf = 0.5

        return QuantumVerdict(
            available=True, verdict=verdict,
            measured_fidelity=measured, expected_fidelity=expected,
            anchors_ranged=anchors, confidence=conf, is_proof=is_proof,
        )

    # -- combined check ---------------------------------------------

    def check(self, gps_lat: float, gps_lon: float,
              q1_reading: Optional[LayerReading] = None,
              **classical_kwargs) -> GuardResult:
        """Run the five classical checks, then apply the quantum verdict.

        classical_kwargs are passed straight through to AntiSpoofDetector.check
        (gps_accuracy_m, gps_signal_dbm, cell_lat, cell_lon,
        imu_accel_magnitude, gps_speed_ms, gps_heading_deg).
        """
        self._checks += 1
        classical = self._detector.check(gps_lat, gps_lon, **classical_kwargs)
        c_score = float(classical["spoof_score"])
        q = self.read_q1(q1_reading)

        final = c_score
        override: Optional[str] = None

        if q.available and q.verdict == "INTERCEPTED" and q.is_proof:
            # Physics has settled it. Nothing the classical checks say matters.
            final = self.VETO_SCORE
            override = "VETO"
            self._vetoes += 1
            reasoning = (
                f"Quantum VETO: measured Bell fidelity {q.measured_fidelity:.3f} "
                f"sits at or below the {CLONER_CEILING:.3f} optimal-cloner ceiling "
                f"while the channel should deliver {q.expected_fidelity:.3f} across "
                f"{q.anchors_ranged} anchors. Interception is not inferred, it is "
                f"forbidden by no-cloning. Fix rejected regardless of the "
                f"classical score of {c_score:.1f}.")

        elif (q.available and q.verdict == "AUTHENTIC"
              and q.measured_fidelity >= AUTHENTIC_FIDELITY
              and self._allow_clear and 0 < c_score <= self.CLEAR_CEILING):
            # A channel proven un-tampered makes a classical flag far more
            # likely to be a real manoeuvre than an attack.
            final = c_score * (1.0 - self.CLEAR_DISCOUNT)
            if final < self._threshold <= c_score:
                override = "CLEAR"
                self._clears += 1
                reasoning = (
                    f"Quantum CLEAR: Bell fidelity {q.measured_fidelity:.3f} across "
                    f"{q.anchors_ranged} anchors proves the ranging channel was not "
                    f"tampered with, so the classical score of {c_score:.1f} is "
                    f"discounted to {final:.1f} and treated as a genuine manoeuvre "
                    f"rather than an attack.")
            else:
                reasoning = (
                    f"Quantum channel authentic (F={q.measured_fidelity:.3f}); "
                    f"classical score {c_score:.1f} discounted to {final:.1f}.")

        elif q.available and q.verdict == "DEGRADED":
            final = c_score + 15.0
            reasoning = (
                f"Quantum channel degraded (F={q.measured_fidelity:.3f} against an "
                f"expected {q.expected_fidelity:.3f}). Not proof of interception, "
                f"but it raises the score from {c_score:.1f} to {final:.1f}.")

        elif (q.available and q.verdict == "AUTHENTIC"
              and c_score > self.CLEAR_CEILING):
            reasoning = (
                f"Quantum channel authentic (F={q.measured_fidelity:.3f}), but the "
                f"classical score of {c_score:.1f} exceeds the {self.CLEAR_CEILING:.0f} "
                f"clear ceiling. Several independent checks are firing together, "
                f"which clean ranging does not explain. Classical evidence stands.")

        elif not q.available:
            reasoning = (
                f"No entangled ranging available; falling back to the five "
                f"classical checks alone. Score {c_score:.1f}.")
        else:
            reasoning = (
                f"Quantum channel authentic, classical checks clean. "
                f"Score {c_score:.1f}.")

        final = max(0.0, min(100.0, final))
        spoofed = final >= self._threshold

        result = GuardResult(
            is_spoofed=spoofed,
            action="REJECT_GPS" if spoofed else "ACCEPT_GPS",
            classical_score=c_score,
            final_score=final,
            quantum=q,
            classical_alerts=classical.get("alerts", []),
            quantum_override=override,
            reasoning=reasoning,
        )
        self._last = result
        return result

    # -- reporting --------------------------------------------------

    def get_status(self) -> Dict:
        return {
            "checks_run": self._checks,
            "quantum_vetoes": self._vetoes,
            "quantum_clears": self._clears,
            "threshold": self._threshold,
            "cloner_ceiling": round(CLONER_CEILING, 4),
            "authentic_fidelity_floor": AUTHENTIC_FIDELITY,
            "clear_enabled": self._allow_clear,
            "classical_checks": 5,
            "quantum_checks": 1,
            "last_action": self._last.action if self._last else None,
            "last_override": self._last.quantum_override if self._last else None,
        }
