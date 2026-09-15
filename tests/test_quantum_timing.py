"""Tests for the quantum timing prior (CP1). Run: python tests/test_quantum_timing.py"""
import sys
import time

sys.path.insert(0, ".")

from upin.core.layer_base import LayerReading
from upin.core.position import Position
from upin.layers.registry import ALL_LAYER_CLASSES
from upin.quantum.timing_bridge import (
    C_LIGHT, FREE_RUNNING_SYNC_NS, QuantumTimingPrior, TDOA_LAYERS,
)
from upin.simulation.world import SimulationWorld

PASSED = []


def _reading(layer_id: str, accuracy_m: float) -> LayerReading:
    return LayerReading(
        layer_id=layer_id,
        position=Position(latitude=13.08, longitude=80.27, altitude=100,
                          accuracy_m=accuracy_m, timestamp=time.time()),
        self_confidence=0.7, is_valid=True, raw_data={},
    )


def test_range_floor_scales_with_propagation_speed():
    """1 ns of sync error is 30 cm of RF range but only 1.5 um of acoustic."""
    p = QuantumTimingPrior(holdover_drift_ns_per_s=0.0)
    p.set_classical(1.0)
    rf = p.range_floor_m("eloran_l41")
    ac = p.range_floor_m("acoustic_l10")
    assert abs(rf - 0.2998) < 1e-3, f"RF floor {rf}"
    assert abs(ac - 1.5e-6) < 1e-9, f"acoustic floor {ac}"
    assert rf / ac > 1e5, "RF must be far more clock-sensitive than acoustic"
    assert p.range_floor_m("magano_l6") is None, "non-TDOA layer must be untouched"
    print(f"[ok] range floor at 1 ns: RF {rf:.4f} m, acoustic {ac:.3e} m "
          f"({rf/ac:.1e}x more sensitive)")
    PASSED.append("floor_scaling")


def test_quantum_sync_tightens_a_clock_limited_layer():
    p = QuantumTimingPrior(holdover_drift_ns_per_s=0.0)

    # Free-running: 50 ns -> ~15 m RF floor
    r = p.apply(_reading("eloran_l41", accuracy_m=2.0))
    assert r.raw_data["timing_limited_by"] == "clock_sync"
    free_acc = r.position.accuracy_m
    assert abs(free_acc - FREE_RUNNING_SYNC_NS * 1e-9 * C_LIGHT) < 1e-6

    # Quantum sync at 2 ns -> ~0.6 m floor
    p.set_classical(2.0, source="quantum")
    r2 = p.apply(_reading("eloran_l41", accuracy_m=2.0))
    assert r2.position.accuracy_m < free_acc
    assert r2.raw_data["timing_limited_by"] == "layer_physics", \
        "at 2 ns the layer's own 2 m claim should become the binding limit"
    print(f"[ok] clock-limited layer: {free_acc:.2f} m free-running -> "
          f"{r2.position.accuracy_m:.2f} m at 2 ns sync")
    PASSED.append("tightening")


def test_never_fakes_an_improvement():
    """A layer already worse than the timing floor keeps its own claim."""
    p = QuantumTimingPrior(holdover_drift_ns_per_s=0.0)
    p.set_classical(0.001, source="quantum")     # essentially perfect sync
    r = p.apply(_reading("otdoa_d22", accuracy_m=50.0))
    assert r.position.accuracy_m == 50.0, "must not invent accuracy"
    assert r.raw_data["timing_limited_by"] == "layer_physics"
    print("[ok] perfect sync does not improve a layer limited by its own physics")
    PASSED.append("no_faking")


def test_holdover_degrades_sync():
    """Sync quality decays after the last pulse — holdover is not free."""
    p = QuantumTimingPrior(holdover_drift_ns_per_s=10.0)
    p.set_classical(1.0, source="quantum")
    fresh = p.range_floor_m("eloran_l41")
    time.sleep(0.25)
    stale = p.range_floor_m("eloran_l41")
    assert stale > fresh, "floor must widen as the sync ages"
    print(f"[ok] holdover: floor {fresh:.3f} m -> {stale:.3f} m after 0.25 s "
          f"at 10 ns/s drift")
    PASSED.append("holdover")


def test_confidence_moves_in_the_right_direction():
    p = QuantumTimingPrior(holdover_drift_ns_per_s=0.0)

    # Free-running and clock-limited: confidence should drop
    r = p.apply(_reading("eloran_l41", accuracy_m=1.0))
    assert r.self_confidence < 0.7, "clock-limited free-running must cost confidence"

    # Quantum-synced and physics-limited: confidence should rise
    p.set_classical(0.01, source="quantum")
    r2 = p.apply(_reading("eloran_l41", accuracy_m=100.0))
    assert r2.self_confidence > 0.7, "quantum sync should earn a small uplift"
    print(f"[ok] confidence: 0.70 -> {r.self_confidence:.3f} when clock-limited, "
          f"-> {r2.self_confidence:.3f} when quantum-synced")
    PASSED.append("confidence")


def test_end_to_end_q3_drives_the_prior():
    w = SimulationWorld()
    w.step(0.1)
    p = QuantumTimingPrior()

    before = p.get_status()["rf_range_floor_m"]

    q3 = ALL_LAYER_CLASSES["qclocknet_q03"]()
    q3.initialize()
    q3.set_world(w)
    res = p.update_from_q3(q3.read())

    assert res["accepted"], res
    assert res["source"] == "quantum"
    assert res["improvement_over_free_running"] > 2.0

    after = p.get_status()["rf_range_floor_m"]
    assert after < before, f"floor {before} -> {after}"
    print(f"[ok] Q3 -> prior: sync {res['sync_ns']:.3f} ns, RF floor "
          f"{before:.2f} m -> {after:.2f} m ({res['improvement_over_free_running']:.1f}x)")
    PASSED.append("end_to_end")


def test_rejects_a_reading_without_timing_data():
    p = QuantumTimingPrior()
    res = p.update_from_q3(_reading("qclocknet_q03", 10.0))
    assert not res["accepted"], "must reject a reading with no sync field"
    print("[ok] a reading with no sync_uncertainty_ns is rejected, not guessed")
    PASSED.append("rejects_bad")


def test_covers_the_real_tdoa_layers():
    """Every layer the prior claims to cover must exist in the registry."""
    missing = [lid for lid in TDOA_LAYERS if lid not in ALL_LAYER_CLASSES]
    assert not missing, f"prior references layers not in registry: {missing}"

    p = QuantumTimingPrior()
    covered = p.affected_layers(available=ALL_LAYER_CLASSES.keys())
    for key in ("acoustic_l10", "eloran_l41", "otdoa_d22", "univbeacon_k11"):
        assert key in covered, f"{key} should be covered"
    print(f"[ok] {len(covered)} real TDOA layers covered, none dangling")
    PASSED.append("coverage")


def test_apply_all_batches():
    w = SimulationWorld()
    w.step(0.1)
    p = QuantumTimingPrior()
    p.set_classical(1.5, source="quantum")

    readings = []
    for lid in ("eloran_l41", "otdoa_d22", "acoustic_l10", "magano_l6"):
        L = ALL_LAYER_CLASSES[lid]()
        L.initialize()
        L.set_world(w)
        readings.append(L.read())

    out = p.apply_all(readings)
    assert len(out) == 4
    tdoa_tagged = sum(1 for r in out if "timing_floor_m" in (r.raw_data or {}))
    assert tdoa_tagged == 3, "only the three TDOA layers should be tagged"
    assert "timing_floor_m" not in (out[-1].raw_data or {}), \
        "magano_l6 is not a TDOA layer and must pass through untouched"
    print(f"[ok] batch apply: 3 of 4 readings tagged, magnetic layer untouched")
    PASSED.append("batch")


if __name__ == "__main__":
    tests = [
        test_range_floor_scales_with_propagation_speed,
        test_quantum_sync_tightens_a_clock_limited_layer,
        test_never_fakes_an_improvement,
        test_holdover_degrades_sync,
        test_confidence_moves_in_the_right_direction,
        test_end_to_end_q3_drives_the_prior,
        test_rejects_a_reading_without_timing_data,
        test_covers_the_real_tdoa_layers,
        test_apply_all_batches,
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

    print(f"\n{len(PASSED)}/{len(tests)} timing-prior tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all timing-prior tests passed")
