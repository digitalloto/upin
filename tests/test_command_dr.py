"""Tests for command-based dead reckoning and the no-fabrication contract.
Run: python tests/test_command_dr.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.core.no_fabrication import NoFixReason, audit_layer, no_fix
from upin.layers.inertial.command_dr import (
    AirframeModel, CommandDeadReckoningLayer, ModelCalibrator, MotorCommand,
    WindEstimator, accel_from_command, propagate,
)
from upin.layers.registry import ALL_LAYER_CLASSES

PASSED = []

# The airframe we pretend to have flown. The calibrator has to find it.
TRUE = AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True)


def _flight(n_segments=12, pitch=(-0.20, 0.20), steps=20, seed=7):
    """Generate flight logs from the true airframe — commands + real displacement."""
    rng = np.random.default_rng(seed)
    cal = ModelCalibrator("test-quad")
    for _ in range(n_segments):
        cmds = [
            MotorCommand(
                timestamp=0.0,
                throttle=float(TRUE.hover_throttle + rng.uniform(-0.05, 0.08)),
                roll_rad=float(rng.uniform(-0.1, 0.1)),
                pitch_rad=float(rng.uniform(*pitch)),
                yaw_rad=float(rng.uniform(0, 2 * math.pi)),
                dt=0.1,
            )
            for _ in range(steps)
        ]
        disp, _ = propagate(cmds, TRUE, np.zeros(3), np.zeros(3))
        cal.add_segment(cmds, disp)
    return cal


# ---------------------------------------------------------------- physics

def test_hover_produces_no_acceleration():
    """At hover throttle and level attitude, thrust must exactly cancel gravity."""
    cmd = MotorCommand(0.0, throttle=TRUE.hover_throttle,
                       roll_rad=0.0, pitch_rad=0.0, yaw_rad=0.0, dt=0.1)
    a = accel_from_command(cmd, TRUE, np.zeros(3))
    assert abs(a[2]) < 1e-9, f"vertical accel {a[2]} should be zero at hover"
    assert abs(a[0]) < 1e-12 and abs(a[1]) < 1e-12, "level hover must not translate"
    print(f"[ok] hover: thrust cancels gravity to {abs(a[2]):.2e} m/s^2")
    PASSED.append("hover")


def test_pitch_moves_along_heading():
    """Nose-down pitch accelerates forward, and yaw rotates which way that is."""
    north = accel_from_command(
        MotorCommand(0.0, TRUE.hover_throttle, 0.0, -0.15, 0.0, 0.1),
        TRUE, np.zeros(3))
    assert north[0] > 0.5, f"nose-down at yaw 0 should push north, got {north[0]}"
    assert abs(north[1]) < 1e-9, "no east component when heading north"

    east = accel_from_command(
        MotorCommand(0.0, TRUE.hover_throttle, 0.0, -0.15, math.pi / 2, 0.1),
        TRUE, np.zeros(3))
    assert east[1] > 0.5, "same pitch at yaw 90 should push east"
    assert abs(east[0]) < 1e-9
    assert abs(abs(north[0]) - abs(east[1])) < 1e-9, "magnitude must be yaw-invariant"
    print(f"[ok] attitude: pitch -0.15 rad gives {north[0]:.3f} m/s^2, "
          f"rotated correctly by yaw")
    PASSED.append("attitude")


def test_drag_opposes_motion():
    fast = np.array([10.0, 0.0, 0.0])
    level = MotorCommand(0.0, TRUE.hover_throttle, 0.0, 0.0, 0.0, 0.1)
    a = accel_from_command(level, TRUE, fast)
    assert a[0] < 0, "drag must decelerate a northward drone"
    expected = -TRUE.drag_coeff * 10.0 * 10.0
    assert abs(a[0] - expected) < 1e-9, f"{a[0]} vs expected {expected}"
    print(f"[ok] drag: {a[0]:.3f} m/s^2 opposing 10 m/s, matches -k*v^2")
    PASSED.append("drag")


def test_propagation_is_deterministic():
    """Same commands, same model, bit-identical answer. No hidden randomness."""
    cmds = [MotorCommand(0.0, 0.5, 0.05, -0.1, 0.3, 0.1) for _ in range(50)]
    p1, v1 = propagate(cmds, TRUE, np.zeros(3), np.zeros(3))
    p2, v2 = propagate(cmds, TRUE, np.zeros(3), np.zeros(3))
    assert np.array_equal(p1, p2) and np.array_equal(v1, v2)
    print(f"[ok] propagation deterministic over 50 commands, "
          f"displacement {np.linalg.norm(p1):.3f} m")
    PASSED.append("determinism")


def test_uncalibrated_model_refuses_to_propagate():
    try:
        accel_from_command(MotorCommand(0.0, 0.5, 0, 0, 0, 0.1),
                           AirframeModel(), np.zeros(3))
    except ValueError as e:
        assert "calibrat" in str(e).lower()
        print("[ok] an uncalibrated model raises rather than guessing")
        PASSED.append("uncalibrated_raises")
        return
    raise AssertionError("should have refused to use an uncalibrated model")


# ------------------------------------------------------------ calibration

def test_calibration_recovers_the_true_airframe():
    fit = _flight().fit()
    assert fit.calibrated
    err = abs(fit.thrust_to_mass - TRUE.thrust_to_mass)
    assert err < 0.1, f"thrust-to-mass off by {err:.4f}"
    assert fit.calibration_rms_m < 1.0, f"fit rms {fit.calibration_rms_m}"
    print(f"[ok] calibration recovers thrust-to-mass to {err:.4f} "
          f"(rms {fit.calibration_rms_m:.4f} m over {fit.calibration_samples} segments)")
    PASSED.append("calibration")


def test_refuses_to_calibrate_on_too_little_data():
    """A model fitted to two segments reproduces those two segments and nothing else."""
    thin = _flight(n_segments=3).fit()
    assert not thin.calibrated, "3 segments must not produce a calibrated model"
    assert thin.calibration_samples == 3
    assert thin.thrust_to_mass == 0.0, "must not report a fitted value it does not have"
    print(f"[ok] 3 segments refused (need {ModelCalibrator.MIN_SEGMENTS}), "
          f"no value reported")
    PASSED.append("thin_data")


def test_drag_observability_is_reported_honestly():
    """Drag is invisible at hover speed. The fit must say so, not bluff."""
    slow = _flight(pitch=(-0.20, 0.20), steps=20).fit()
    fast = _flight(pitch=(-0.55, -0.35), steps=90).fit()

    assert slow.max_calibration_speed_ms < fast.max_calibration_speed_ms
    assert not slow.drag_observable, "1 m/s data cannot constrain drag"
    assert fast.drag_observable, f"{fast.max_calibration_speed_ms:.1f} m/s should"

    slow_err = abs(slow.drag_coeff - TRUE.drag_coeff)
    fast_err = abs(fast.drag_coeff - TRUE.drag_coeff)
    assert fast_err < slow_err / 4, "fast data must estimate drag far better"
    assert fast_err < 0.01, f"fast drag error {fast_err:.4f}"
    print(f"[ok] drag observability: {slow.max_calibration_speed_ms:.1f} m/s data "
          f"errs {slow_err:.4f} (flagged unobservable); "
          f"{fast.max_calibration_speed_ms:.1f} m/s errs {fast_err:.4f}")
    PASSED.append("drag_observability")


# --------------------------------------------------------------- contract

def test_declines_without_calibration():
    layer = CommandDeadReckoningLayer()
    layer.initialize()
    r = layer.read()
    assert not r.is_valid and r.position is None
    assert r.raw_data["no_fix_reason"] == NoFixReason.NO_CALIBRATION
    assert r.self_confidence == 0.0
    print("[ok] no calibration -> no position, reason stated")
    PASSED.append("no_calibration")


def test_declines_without_anchor():
    layer = CommandDeadReckoningLayer(model=_flight().fit())
    layer.initialize()
    r = layer.read()
    assert not r.is_valid
    assert r.raw_data["no_fix_reason"] == NoFixReason.NO_ANCHOR
    print("[ok] calibrated but unanchored -> no position, reason stated")
    PASSED.append("no_anchor")


def test_declines_without_commands():
    layer = CommandDeadReckoningLayer(model=_flight().fit())
    layer.initialize()
    layer.set_anchor(13.0827, 80.2707, 100.0)
    r = layer.read()
    assert not r.is_valid
    assert r.raw_data["no_fix_reason"] == NoFixReason.NO_INPUT
    print("[ok] anchored but no commands -> no position, reason stated")
    PASSED.append("no_commands")


def test_produces_a_fix_from_real_commands():
    fit = _flight().fit()
    layer = CommandDeadReckoningLayer(model=fit)
    layer.initialize()
    layer.set_anchor(13.0827, 80.2707, 100.0)
    for _ in range(30):
        layer.log_command(MotorCommand(0.0, fit.hover_throttle,
                                       0.0, -0.10, 0.0, 0.1))
    r = layer.read()
    assert r.is_valid and r.position is not None
    assert r.position.latitude > 13.0827, "nose-down at yaw 0 must move north"
    assert abs(r.position.longitude - 80.2707) < 1e-6, "no eastward drift expected"
    assert r.raw_data["fabricated"] is False
    assert r.raw_data["displacement_m"] > 0
    print(f"[ok] 30 commands -> lat {r.position.latitude:.6f}, "
          f"{r.raw_data['displacement_m']} m north, accuracy {r.position.accuracy_m:.2f} m")
    PASSED.append("real_fix")


def test_accuracy_degrades_with_time_since_anchor():
    """A bridge, not a solution — the layer must admit it is getting worse."""
    fit = _flight().fit()
    layer = CommandDeadReckoningLayer(model=fit)
    layer.initialize()
    layer.set_anchor(13.0827, 80.2707, 100.0)

    accuracies = []
    for _ in range(4):
        for _ in range(20):
            layer.log_command(MotorCommand(0.0, fit.hover_throttle,
                                           0.0, -0.05, 0.0, 0.1))
        accuracies.append(layer.read().position.accuracy_m)

    assert accuracies == sorted(accuracies), f"accuracy must widen: {accuracies}"
    assert accuracies[-1] > accuracies[0] * 2
    print(f"[ok] accuracy degrades {accuracies[0]:.2f} m -> {accuracies[-1]:.2f} m "
          f"over 8 s of dead reckoning")
    PASSED.append("degradation")


def test_anchor_reset_clears_drift():
    fit = _flight().fit()
    layer = CommandDeadReckoningLayer(model=fit)
    layer.initialize()
    layer.set_anchor(13.0827, 80.2707, 100.0)
    for _ in range(60):
        layer.log_command(MotorCommand(0.0, fit.hover_throttle, 0.0, -0.1, 0.0, 0.1))
    drifted = layer.read().position.accuracy_m

    layer.set_anchor(13.09, 80.28, 100.0)     # a landmark fix arrives
    layer.log_command(MotorCommand(0.0, fit.hover_throttle, 0.0, -0.1, 0.0, 0.1))
    reset = layer.read()
    assert reset.position.accuracy_m < drifted / 3
    assert abs(reset.position.latitude - 13.09) < 0.001
    print(f"[ok] landmark reset: accuracy {drifted:.2f} m -> "
          f"{reset.position.accuracy_m:.2f} m")
    PASSED.append("reset")


def test_layer_is_deterministic():
    fit = _flight().fit()
    layer = CommandDeadReckoningLayer(model=fit)
    layer.initialize()
    layer.set_anchor(13.0827, 80.2707, 100.0)
    for _ in range(20):
        layer.log_command(MotorCommand(0.0, fit.hover_throttle, 0.0, -0.1, 0.0, 0.1))
    a = layer.read()
    b = layer.read()
    assert a.position.latitude == b.position.latitude
    assert a.position.longitude == b.position.longitude
    assert a.position.accuracy_m == b.position.accuracy_m
    assert a.self_confidence == b.self_confidence
    print("[ok] two reads on identical state are bit-identical — no fabrication")
    PASSED.append("layer_determinism")


def test_passes_the_contract_audit():
    result = audit_layer(ALL_LAYER_CLASSES["cmddr_b12"]())
    assert result.declares_contract
    assert result.declines_without_input
    assert result.states_reason
    assert result.deterministic is not False
    assert result.compliant, result.detail
    print(f"[ok] contract audit: {result.detail}")
    PASSED.append("audit")


# ------------------------------------------------------------ cross-checks

def test_wind_estimated_from_disagreement():
    w = WindEstimator()
    # commands predicted 10 m north; the drone actually went 10 north + 5 east
    for _ in range(10):
        w.update([10.0, 0.0, 0.0], [10.0, 5.0, 0.0], elapsed_s=5.0)
    assert abs(w.speed_ms - 1.0) < 0.01, f"expected 1 m/s east, got {w.speed_ms}"
    assert abs(w.bearing_deg - 90.0) < 1.0, f"bearing {w.bearing_deg}"
    print(f"[ok] wind: {w.speed_ms:.2f} m/s toward {w.bearing_deg:.0f} deg "
          f"from {w.samples} samples")
    PASSED.append("wind")


def test_catches_a_satellite_claim_the_commands_contradict():
    """The spoofing check: an attacker can forge GPS but not the command log."""
    fit = _flight().fit()
    layer = CommandDeadReckoningLayer(model=fit)
    layer.initialize()
    layer.set_anchor(13.0827, 80.2707, 100.0)
    for _ in range(20):
        layer.log_command(MotorCommand(0.0, fit.hover_throttle, 0.0, -0.05, 0.0, 0.1))
    layer.read()

    honest = layer.check_satellite_claim([2.0, 0.0, 0.0], elapsed_s=2.0)
    assert honest["consistent"] and honest["verdict"] == "CONSISTENT"

    spoofed = layer.check_satellite_claim([900.0, 400.0, 0.0], elapsed_s=2.0)
    assert not spoofed["consistent"]
    assert spoofed["verdict"] == "SATELLITE_SUSPECT"
    assert spoofed["disagreement_m"] > spoofed["allowed_m"]
    print(f"[ok] spoof check: a claimed {spoofed['claimed_displacement_m']:.0f} m jump "
          f"against {spoofed['commanded_displacement_m']:.1f} m commanded -> SUSPECT")
    PASSED.append("spoof_check")


def test_satellite_check_refuses_without_calibration():
    layer = CommandDeadReckoningLayer()
    layer.initialize()
    res = layer.check_satellite_claim([10.0, 0.0, 0.0], elapsed_s=1.0)
    assert not res["checked"]
    assert res["reason"] == NoFixReason.NO_CALIBRATION
    print("[ok] spoof check declines without a calibrated model")
    PASSED.append("spoof_needs_model")


# ---------------------------------------------------------------- helpers

def test_no_fix_helper_shape():
    r = no_fix("test_layer", NoFixReason.POOR_GEOMETRY, "only two bearings")
    assert not r.is_valid and r.position is None
    assert r.self_confidence == 0.0
    assert r.raw_data["no_fix_reason"] == NoFixReason.POOR_GEOMETRY
    assert r.raw_data["fabricated"] is False
    assert r.raw_data["detail"] == "only two bearings"
    print("[ok] no_fix() produces an invalid, position-free, reasoned reading")
    PASSED.append("no_fix_helper")


if __name__ == "__main__":
    tests = [
        test_hover_produces_no_acceleration,
        test_pitch_moves_along_heading,
        test_drag_opposes_motion,
        test_propagation_is_deterministic,
        test_uncalibrated_model_refuses_to_propagate,
        test_calibration_recovers_the_true_airframe,
        test_refuses_to_calibrate_on_too_little_data,
        test_drag_observability_is_reported_honestly,
        test_declines_without_calibration,
        test_declines_without_anchor,
        test_declines_without_commands,
        test_produces_a_fix_from_real_commands,
        test_accuracy_degrades_with_time_since_anchor,
        test_anchor_reset_clears_drift,
        test_layer_is_deterministic,
        test_passes_the_contract_audit,
        test_wind_estimated_from_disagreement,
        test_catches_a_satellite_claim_the_commands_contradict,
        test_satellite_check_refuses_without_calibration,
        test_no_fix_helper_shape,
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

    print(f"\n{len(PASSED)}/{len(tests)} command-DR tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all command-DR tests passed")
