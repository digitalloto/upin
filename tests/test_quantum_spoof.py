"""Tests for the quantum spoof guard (CP3). Run: python tests/test_quantum_spoof.py"""
import sys
import time

sys.path.insert(0, ".")

from upin.core.layer_base import LayerReading
from upin.detection.anti_spoof import AntiSpoofDetector
from upin.layers.registry import ALL_LAYER_CLASSES
from upin.quantum.spoof_guard import (
    AUTHENTIC_FIDELITY, CLONER_CEILING, QuantumSpoofGuard,
)
from upin.simulation.world import SimulationWorld

PASSED = []


def q1(verdict, measured, expected, anchors=4) -> LayerReading:
    return LayerReading(
        layer_id="qrange_q01", self_confidence=0.8, is_valid=True,
        raw_data={"no_cloning_verdict": verdict,
                  "mean_bell_fidelity": measured,
                  "expected_channel_fidelity": expected,
                  "anchors_ranged": anchors},
    )


def test_veto_catches_a_spoofer_that_passes_every_classical_check():
    """The case classical detection cannot handle: a patient, consistent spoofer."""
    g = QuantumSpoofGuard()
    r = g.check(13.08, 80.27, q1_reading=q1("INTERCEPTED", 0.82, 0.97))
    assert r.classical_score == 0.0, "scenario requires all 5 classical checks clean"
    assert r.quantum_override == "VETO"
    assert r.is_spoofed and r.action == "REJECT_GPS"
    assert r.final_score == 100.0
    assert r.quantum.is_proof
    print(f"[ok] VETO: classical score {r.classical_score:.1f} (undetected) -> "
          f"rejected at {r.final_score:.0f} by no-cloning")
    PASSED.append("veto")


def test_clear_removes_a_classical_false_positive():
    """A proven-authentic channel makes a teleport flag a manoeuvre, not an attack."""
    g = QuantumSpoofGuard()
    g.check(13.08, 80.27)                    # establish position history
    r = g.check(19.09, 72.87, q1_reading=q1("AUTHENTIC", 0.96, 0.97))
    assert r.classical_score >= 40.0, "teleport should trip the classical check"
    assert r.quantum_override == "CLEAR"
    assert not r.is_spoofed and r.action == "ACCEPT_GPS"
    assert r.final_score < r.classical_score
    print(f"[ok] CLEAR: classical {r.classical_score:.1f} (would reject) -> "
          f"{r.final_score:.1f} accepted, channel proven authentic")
    PASSED.append("clear")


def test_falls_back_cleanly_with_no_quantum_hardware():
    """Without entangled ranging the guard must behave exactly like the classical detector."""
    g = QuantumSpoofGuard()
    g.check(13.08, 80.27)
    r = g.check(19.09, 72.87, q1_reading=None)
    assert r.quantum.verdict == "UNAVAILABLE"
    assert not r.quantum.available
    assert r.quantum_override is None
    assert r.final_score == r.classical_score, "must not alter the classical verdict"
    assert r.is_spoofed, "teleport should still be caught classically"

    bare = AntiSpoofDetector()
    bare.check(13.08, 80.27)
    same = bare.check(19.09, 72.87)
    assert abs(same["spoof_score"] - r.final_score) < 1e-9, \
        "guard must reproduce the classical score exactly"
    print(f"[ok] fallback: no quantum -> identical classical score "
          f"{r.final_score:.1f}, teleport still caught")
    PASSED.append("fallback")


def test_interception_needs_real_evidence_to_veto():
    """A veto requires enough anchors and a channel that should beat the ceiling."""
    g = QuantumSpoofGuard()

    too_few = g.check(13.08, 80.27, q1_reading=q1("INTERCEPTED", 0.82, 0.97, anchors=2))
    assert not too_few.quantum.is_proof, "2 anchors is not proof"
    assert too_few.quantum_override != "VETO"

    # A lossy channel that legitimately sits below the cloner ceiling is not
    # evidence of anything — this is the false positive fixed in the Q1 layer.
    lossy = g.check(13.08, 80.27, q1_reading=q1("INTERCEPTED", 0.78, 0.79, anchors=5))
    assert not lossy.quantum.is_proof, "a genuinely lossy link must not veto"
    assert lossy.quantum_override != "VETO"
    print("[ok] veto withheld for 2 anchors, and for a lossy link legitimately "
          "below the cloner ceiling")
    PASSED.append("veto_evidence")


def test_degraded_raises_the_score_without_vetoing():
    g = QuantumSpoofGuard()
    r = g.check(13.08, 80.27, q1_reading=q1("DEGRADED", 0.70, 0.95))
    assert r.quantum_override is None, "degraded is suspicion, not proof"
    assert r.final_score > r.classical_score, "but it must still raise the score"
    print(f"[ok] DEGRADED: score raised {r.classical_score:.1f} -> "
          f"{r.final_score:.1f}, no veto")
    PASSED.append("degraded")


def test_clear_cannot_rescue_an_overwhelming_classical_score():
    """Authentic ranging discounts a flag; it does not erase strong evidence."""
    g = QuantumSpoofGuard()
    g.check(13.08, 80.27)
    r = g.check(19.09, 72.87,
                gps_signal_dbm=-45.0,        # signal spike as well as teleport
                imu_accel_magnitude=0.0,
                gps_speed_ms=80.0,
                q1_reading=q1("AUTHENTIC", 0.96, 0.97))
    assert r.classical_score > QuantumSpoofGuard.CLEAR_CEILING, \
        f"scenario needs a score above the clear ceiling, got {r.classical_score}"
    assert r.quantum_override is None, "CLEAR must not apply above the ceiling"
    assert r.final_score == r.classical_score, "score must stand undiscounted"
    assert r.is_spoofed, "multi-check evidence must survive a clean channel"
    print(f"[ok] CLEAR bounded: classical {r.classical_score:.1f} exceeds the "
          f"{QuantumSpoofGuard.CLEAR_CEILING:.0f} ceiling, stands undiscounted")
    PASSED.append("clear_bounded")


def test_clear_can_be_disabled():
    """Operators who want quantum evidence to only ever add suspicion can say so."""
    g = QuantumSpoofGuard(allow_clear=False)
    g.check(13.08, 80.27)
    r = g.check(19.09, 72.87, q1_reading=q1("AUTHENTIC", 0.96, 0.97))
    assert r.quantum_override is None
    assert r.final_score == r.classical_score
    assert r.is_spoofed
    print("[ok] allow_clear=False keeps the classical verdict untouched")
    PASSED.append("clear_disabled")


def test_reads_the_live_q1_layer():
    w = SimulationWorld()
    w.step(0.1)
    layer = ALL_LAYER_CLASSES["qrange_q01"]()
    layer.initialize()
    layer.set_world(w)
    reading = layer.read()

    v = QuantumSpoofGuard.read_q1(reading)
    assert v.available
    assert v.verdict in ("AUTHENTIC", "DEGRADED", "INTERCEPTED")
    assert v.anchors_ranged >= 3
    assert 0.0 <= v.confidence <= 1.0
    print(f"[ok] live Q1: verdict {v.verdict}, F={v.measured_fidelity:.3f} "
          f"vs expected {v.expected_fidelity:.3f}, {v.anchors_ranged} anchors")
    PASSED.append("live_q1")


def test_cloner_ceiling_is_the_documented_constant():
    assert abs(CLONER_CEILING - 5.0 / 6.0) < 1e-12
    assert 0.83 < CLONER_CEILING < 0.834
    assert AUTHENTIC_FIDELITY > CLONER_CEILING, \
        "the authentic floor must sit above the cloner ceiling to mean anything"
    print(f"[ok] cloner ceiling {CLONER_CEILING:.4f}, authentic floor "
          f"{AUTHENTIC_FIDELITY} sits above it")
    PASSED.append("constants")


def test_status_counts_overrides():
    g = QuantumSpoofGuard()
    g.check(13.08, 80.27, q1_reading=q1("INTERCEPTED", 0.80, 0.97))
    # Hold position: consecutive checks are microseconds apart in a test, so
    # any movement at all reads as an impossible speed to the teleport check.
    g.check(13.08, 80.27)
    g.check(19.09, 72.87, q1_reading=q1("AUTHENTIC", 0.96, 0.97))
    s = g.get_status()
    assert s["checks_run"] == 3
    assert s["quantum_vetoes"] == 1
    assert s["quantum_clears"] == 1
    assert s["classical_checks"] == 5 and s["quantum_checks"] == 1
    print(f"[ok] status: {s['checks_run']} checks, {s['quantum_vetoes']} veto, "
          f"{s['quantum_clears']} clear")
    PASSED.append("status")


if __name__ == "__main__":
    tests = [
        test_veto_catches_a_spoofer_that_passes_every_classical_check,
        test_clear_removes_a_classical_false_positive,
        test_falls_back_cleanly_with_no_quantum_hardware,
        test_interception_needs_real_evidence_to_veto,
        test_degraded_raises_the_score_without_vetoing,
        test_clear_cannot_rescue_an_overwhelming_classical_score,
        test_clear_can_be_disabled,
        test_reads_the_live_q1_layer,
        test_cloner_ceiling_is_the_documented_constant,
        test_status_counts_overrides,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:
            failed.append((t.__name__, repr(e)))
            print(f"[ERROR] {t.__name__}: {e!r}")

    print(f"\n{len(PASSED)}/{len(tests)} spoof-guard tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all spoof-guard tests passed")
