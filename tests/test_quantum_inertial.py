"""Tests for the quantum inertial bridge (CP2). Run: python tests/test_quantum_inertial.py"""
import math
import sys
import time

sys.path.insert(0, ".")

from upin.core.layer_base import LayerReading
from upin.core.position import Position
from upin.core.strapdown_ins import IMUGrade, StrapdownINS
from upin.layers.registry import ALL_LAYER_CLASSES
from upin.quantum.inertial_bridge import QuantumInertialBridge
from upin.simulation.world import SimulationWorld

PASSED = []


def _q4_reading(drift_deg_hr) -> LayerReading:
    return LayerReading(
        layer_id="atomgyro_q04",
        position=Position(latitude=13.08, longitude=80.27, altitude=100,
                          accuracy_m=1.0, timestamp=time.time()),
        self_confidence=0.94, is_valid=True,
        raw_data={"bias_drift_deg_per_hr": drift_deg_hr, "squeezing_db": 9.6},
    )


def test_quantum_grade_exists_and_is_best():
    """The new grade must be the lowest-drift profile, and only additive."""
    assert "quantum" in IMUGrade.PROFILES
    drifts = {n: p["gyro_drift_deg_hr"] for n, p in IMUGrade.PROFILES.items()}
    assert drifts["quantum"] == min(drifts.values())
    # the five original grades must be untouched
    for name, expected in [("phone_mems", 10.0), ("consumer", 3.0),
                           ("tactical", 0.5), ("navigation", 0.01),
                           ("strategic", 0.001)]:
        assert drifts[name] == expected, f"{name} drift changed to {drifts[name]}"
    ratio = drifts["navigation"] / drifts["quantum"]
    assert ratio > 1000, f"only {ratio:.0f}x better than navigation grade"
    print(f"[ok] quantum grade added at {drifts['quantum']:.2e} deg/hr, "
          f"{ratio:.0f}x below navigation; five original grades unchanged")
    PASSED.append("grade_added")


def test_drift_maps_to_the_right_grade():
    b = QuantumInertialBridge()
    cases = [(12.0, "phone_mems"), (2.5, "consumer"), (0.4, "tactical"),
             (0.008, "navigation"), (0.0009, "strategic"), (2e-6, "quantum")]
    for drift, expected in cases:
        got = b.grade_for_drift(drift)
        assert got == expected, f"{drift} deg/hr -> {got}, expected {expected}"
    print("[ok] drift-to-grade mapping correct across all six grades")
    PASSED.append("grade_mapping")


def test_error_grows_quadratically_with_time():
    """A constant gyro bias gives error ~ v*b*t^2/2 — this is why bias dominates."""
    b = QuantumInertialBridge(cruise_speed_ms=30.0)
    budget = b.drift_budget("navigation")
    bias = math.radians(budget.gyro_drift_deg_hr) / 3600.0

    def err(t):
        return 0.5 * 30.0 * bias * t * t

    e1, e2 = err(1800.0), err(3600.0)
    assert abs(e2 / e1 - 4.0) < 1e-9, "doubling time must quadruple error"
    assert abs(budget.cross_track_error_after_1hr_m - e2) < 1e-6
    print(f"[ok] quadratic growth: 30 min {e1:.2f} m -> 60 min {e2:.2f} m (4.0x)")
    PASSED.append("quadratic")


def test_quantum_endurance_beats_navigation():
    b = QuantumInertialBridge(cruise_speed_ms=30.0)
    nav = b.drift_budget("navigation")
    qtm = b.drift_budget("quantum")

    assert qtm.cross_track_error_after_1hr_m < nav.cross_track_error_after_1hr_m
    assert qtm.seconds_to_100m_error > nav.seconds_to_100m_error

    # time-to-error scales as 1/sqrt(bias), so a 5000x bias cut is ~70x endurance
    gain = qtm.hours_to_1km_error / nav.hours_to_1km_error
    expected = math.sqrt(nav.gyro_drift_deg_hr / qtm.gyro_drift_deg_hr)
    assert abs(gain - expected) < 0.5, f"gain {gain:.1f} vs expected {expected:.1f}"
    assert gain > 50, f"only {gain:.1f}x endurance gain"
    print(f"[ok] endurance: navigation {nav.hours_to_1km_error:.1f} hr to 1 km, "
          f"quantum {qtm.hours_to_1km_error:.0f} hr ({gain:.1f}x)")
    PASSED.append("endurance")


def test_reads_live_q4_layer():
    w = SimulationWorld()
    w.step(0.1)
    q4 = ALL_LAYER_CLASSES["atomgyro_q04"]()
    q4.initialize()
    q4.set_world(w)

    b = QuantumInertialBridge()
    res = b.read_q4(q4.read())
    assert res["accepted"], res
    assert res["grade"] == "quantum"
    assert res["beats_navigation_grade"]
    assert res["orders_of_magnitude_vs_navigation"] > 3.0
    print(f"[ok] live Q4: {res['measured_drift_deg_hr']:.3e} deg/hr, "
          f"{res['orders_of_magnitude_vs_navigation']:.1f} orders below nav grade")
    PASSED.append("live_q4")


def test_rejects_bad_readings():
    b = QuantumInertialBridge()
    missing = LayerReading(layer_id="atomgyro_q04", self_confidence=0.9,
                           is_valid=True, raw_data={})
    assert not b.read_q4(missing)["accepted"]
    assert not b.read_q4(_q4_reading("not-a-number"))["accepted"]
    assert not b.read_q4(_q4_reading(-1.0))["accepted"]
    assert not b.read_q4(_q4_reading(float("nan")))["accepted"]
    print("[ok] missing, unparseable, negative and NaN drift values all rejected")
    PASSED.append("rejects_bad")


def test_configures_a_fresh_ins():
    b = QuantumInertialBridge()
    b.read_q4(_q4_reading(2e-6))
    ins = b.configure_ins(lat=13.0827, lon=80.2707, alt=120.0)
    assert isinstance(ins, StrapdownINS)
    assert ins._grade_name == "quantum"
    assert ins._grade["gyro_drift_deg_hr"] == IMUGrade.PROFILES["quantum"]["gyro_drift_deg_hr"]
    assert not ins._auto_detect, "explicit grade must disable auto-detection"
    print(f"[ok] fresh INS built at grade '{ins._grade_name}'")
    PASSED.append("fresh_ins")


def test_reconfigures_an_existing_ins_without_breaking_it():
    """Re-pointing the profile must not disturb the propagation state."""
    ins = StrapdownINS(initial_lat=13.08, initial_lon=80.27,
                       initial_alt=100.0, hardware_grade="phone_mems")
    assert ins._grade_name == "phone_mems"
    lat_before = ins.state.latitude_rad
    lon_before = ins.state.longitude_rad

    b = QuantumInertialBridge()
    b.read_q4(_q4_reading(2e-6))
    same = b.configure_ins(ins=ins)

    assert same is ins, "must reconfigure in place, not replace"
    assert ins._grade_name == "quantum"
    assert ins.state.latitude_rad == lat_before, "position state must survive"
    assert ins.state.longitude_rad == lon_before
    print("[ok] existing INS upgraded phone_mems -> quantum, state preserved")
    PASSED.append("reconfigure")


def test_compare_grades_table():
    b = QuantumInertialBridge(cruise_speed_ms=30.0)
    c = b.compare_grades()
    assert len(c["grades"]) == 6
    # endurance must improve monotonically as drift falls
    ordered = sorted(c["grades"].items(), key=lambda kv: -kv[1]["gyro_drift_deg_hr"])
    hours = [r["hours_to_1km"] for _, r in ordered]
    assert hours == sorted(hours), f"endurance not monotonic: {hours}"
    assert c["quantum_vs_navigation_endurance_x"] > 50
    print(f"[ok] grade table monotonic: "
          f"{hours[0]:.2f} hr (phone) -> {hours[-1]:.0f} hr (quantum)")
    PASSED.append("table")


def test_speed_changes_the_budget():
    """Faster platforms hit a given error sooner — the budget must reflect that."""
    b = QuantumInertialBridge()
    slow = b.drift_budget("tactical", speed_ms=10.0)
    fast = b.drift_budget("tactical", speed_ms=100.0)
    assert fast.seconds_to_100m_error < slow.seconds_to_100m_error
    ratio = slow.seconds_to_100m_error / fast.seconds_to_100m_error
    assert abs(ratio - math.sqrt(10.0)) < 0.1, f"ratio {ratio}"
    print(f"[ok] speed scaling: 10x faster shortens time-to-100m by "
          f"{ratio:.2f}x (sqrt(10)={math.sqrt(10):.2f})")
    PASSED.append("speed")


if __name__ == "__main__":
    tests = [
        test_quantum_grade_exists_and_is_best,
        test_drift_maps_to_the_right_grade,
        test_error_grows_quadratically_with_time,
        test_quantum_endurance_beats_navigation,
        test_reads_live_q4_layer,
        test_rejects_bad_readings,
        test_configures_a_fresh_ins,
        test_reconfigures_an_existing_ins_without_breaking_it,
        test_compare_grades_table,
        test_speed_changes_the_budget,
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

    print(f"\n{len(PASSED)}/{len(tests)} inertial-bridge tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all inertial-bridge tests passed")
