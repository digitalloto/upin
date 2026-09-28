"""Tests for the flight-controller interface.

The rule under test above all: a command outside the limits is refused and
reported, never clamped and flown. Then that the simulated autopilot flies
what it is told with the physics it should have, and that the MAVLink path
fails loudly rather than pretending when it cannot reach a vehicle.

Run: python tests/test_autopilot.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.control.autopilot import (
    AutopilotLimits, AutopilotUnavailable, MAVLinkAutopilot,
    SimulatedAutopilot, climb_thrust, euler_to_quaternion,
)
from upin.layers.inertial.command_dr import AirframeModel
from upin.simulation.world import SimulationWorld

PASSED = []

LAT, LON = 13.0827, 80.2707
QUAD = AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True)
G = 9.80665


def pilot(seed=1, heading=0.0, limits=None):
    w = SimulationWorld.at_agl(LAT, LON, 120.0, heading_deg=heading,
                               velocity_ms=0.0, seed=seed)
    return SimulatedAutopilot(w, airframe=QUAD, limits=limits), w


def fly(ap, seconds, dt=0.1):
    for _ in range(int(round(seconds / dt))):
        ap.fly(dt)


def track_bearing(w):
    return math.degrees(math.atan2(w.true_ve, w.true_vn)) % 360.0


# ----------------------------------------------------------------- refusals

def test_excess_tilt_is_refused_not_clamped():
    ap, w = pilot()
    ok = ap.send_attitude(0.0, 10.0, w.true_alt)
    assert ok.accepted
    bad = ap.send_attitude(90.0, 40.0, w.true_alt)
    assert not bad.accepted and "exceeds" in bad.reason, bad.reason
    assert ap.setpoint.tilt_deg == 10.0 and ap.setpoint.heading_deg == 0.0, (
        "a refused command changed what the aircraft is flying")
    assert len(ap.refusals) == 1
    print(f"[ok] 40 deg refused ({bad.reason}); still flying the accepted 10 deg")
    PASSED.append("tilt_refused")


def test_non_finite_commands_are_refused():
    ap, w = pilot()
    for args in ((float("nan"), 5.0, w.true_alt),
                 (0.0, float("inf"), w.true_alt),
                 (0.0, 5.0, float("nan"))):
        r = ap.send_attitude(*args)
        assert not r.accepted and "finite" in r.reason, r.reason
    print("[ok] NaN and infinity refused in heading, tilt and altitude")
    PASSED.append("nonfinite")


def test_negative_tilt_is_refused():
    ap, w = pilot()
    r = ap.send_attitude(0.0, -5.0, w.true_alt)
    assert not r.accepted and "negative" in r.reason
    print("[ok] negative tilt refused: turn the nose, don't fly backward")
    PASSED.append("negative")


def test_altitude_step_guards_against_a_units_mistake():
    """AGL passed as MSL, or feet as metres, is caught before it flies."""
    ap, w = pilot()
    agl_as_msl = 120.0                     # height above ground, not sea level
    r = ap.send_attitude(0.0, 0.0, agl_as_msl)
    step = abs(w.true_alt - agl_as_msl)
    if step > ap.limits.max_alt_step_m:
        assert not r.accepted and "units" in r.reason, r.reason
    r2 = ap.send_attitude(0.0, 0.0, w.true_alt * 3.28084)   # metres -> feet
    assert not r2.accepted, "a feet-for-metres altitude was flown"
    print(f"[ok] a {step:.0f} m and a feet-for-metres altitude jump both "
          f"refused -- check units and datum")
    PASSED.append("alt_step")


def test_altitude_floor_and_ceiling():
    ap, w = pilot(limits=AutopilotLimits(min_alt_m=100.0, max_alt_m=400.0,
                                         max_alt_step_m=1e9))
    assert not ap.send_attitude(0.0, 0.0, 50.0).accepted
    assert not ap.send_attitude(0.0, 0.0, 500.0).accepted
    assert ap.send_attitude(0.0, 0.0, 300.0).accepted
    print("[ok] altitude floor and ceiling enforced")
    PASSED.append("alt_band")


# ------------------------------------------------------- the simulated loop

def test_it_holds_altitude_while_tilting():
    ap, w = pilot()
    target = w.true_alt
    ap.send_attitude(45.0, 12.0, target)
    fly(ap, 20.0)
    assert abs(w.true_alt - target) < 0.5, w.true_alt - target
    print(f"[ok] 12 deg forward tilt for 20 s: altitude held to "
          f"{abs(w.true_alt - target):.2f} m")
    PASSED.append("alt_hold")


def test_it_climbs_to_a_new_altitude_and_settles():
    ap, w = pilot()
    target = w.true_alt + 20.0
    ap.send_attitude(0.0, 0.0, target)
    fly(ap, 30.0)
    assert abs(w.true_alt - target) < 0.5 and abs(w.true_vd) < 0.2, (
        w.true_alt - target, w.true_vd)
    print(f"[ok] 20 m climb settled within {abs(w.true_alt - target):.2f} m")
    PASSED.append("climb")


def test_it_flies_the_commanded_heading_in_calm_air():
    ap, w = pilot()
    ap.send_attitude(70.0, 10.0, w.true_alt)
    fly(ap, 15.0)
    err = (track_bearing(w) - 70.0 + 180.0) % 360.0 - 180.0
    assert abs(err) < 1.0, err
    print(f"[ok] commanded 070, ground track {track_bearing(w):.1f} in calm air")
    PASSED.append("heading")


def test_steady_speed_is_set_by_tilt_against_drag():
    """G tan(tilt) = k v^2 at steady state -- what the Speed Learner will learn."""
    rows = []
    for tilt in (5.0, 10.0, 15.0):
        ap, w = pilot()
        ap.send_attitude(0.0, tilt, w.true_alt)
        fly(ap, 40.0)
        v = math.hypot(w.true_vn, w.true_ve)
        expect = math.sqrt(G * math.tan(math.radians(tilt)) / QUAD.drag_coeff)
        assert abs(v - expect) / expect < 0.03, (tilt, v, expect)
        rows.append(f"{tilt:g} deg -> {v:.2f} m/s (theory {expect:.2f})")
    print("[ok] steady airspeed matches sqrt(g tan(tilt) / k): " + "; ".join(rows))
    PASSED.append("speed")


def test_a_crosswind_carries_it_off_its_heading():
    """The problem L2 exists to solve: nose north, wind east, track bends."""
    ap, w = pilot()
    w.set_wind(0.0, 3.0)
    ap.send_attitude(0.0, 10.0, w.true_alt)
    fly(ap, 40.0)
    bearing = track_bearing(w)
    assert 20.0 < bearing < 60.0, bearing
    print(f"[ok] nose on 000 in a 3 m/s easterly: ground track "
          f"{bearing:.1f} deg -- the crab L2 must correct")
    PASSED.append("crab")


def test_telemetry_reports_no_position():
    ap, w = pilot()
    t = ap.telemetry()
    for key in ("latitude", "longitude", "lat", "lon", "position"):
        assert key not in t, f"telemetry leaked {key}"
    assert t["altitude_m"] == w.true_alt
    print("[ok] telemetry carries attitude and altitude, never position")
    PASSED.append("no_position")


def test_fc_wind_estimate_exists_only_with_gnss():
    ap, w = pilot()
    w.set_wind(2.0, -1.0)
    est = ap.telemetry()["wind_estimate_ned"]
    assert est is not None
    assert math.hypot(est[0] - 2.0, est[1] + 1.0) < 2.0
    w.add_jamming_zone(w.true_lat, w.true_lon, 3000.0)
    assert ap.telemetry()["wind_estimate_ned"] is None, (
        "the flight controller kept a wind estimate it cannot make without GNSS")
    print("[ok] flight-controller wind estimate: present with GNSS, None "
          "when denied")
    PASSED.append("fc_wind")


def test_saturation_is_reported_not_hidden():
    heavy = AirframeModel(thrust_to_mass=10.5, drag_coeff=0.08, calibrated=True)
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=2)
    ap = SimulatedAutopilot(w, airframe=heavy)
    ap.send_attitude(0.0, 20.0, w.true_alt + 10.0)
    ap.fly(0.1)
    assert ap.telemetry()["thrust_saturated"] is True
    print("[ok] an underpowered airframe reports thrust saturation")
    PASSED.append("saturation")


# ------------------------------------------------------------ MAVLink path

def test_mavlink_is_marked_untested_and_fails_loudly():
    assert MAVLinkAutopilot.UNTESTED is True
    assert SimulatedAutopilot.UNTESTED is False
    ap = MAVLinkAutopilot("udpin:127.0.0.1:14550")
    try:
        ap.connect(timeout_s=0.1)
    except AutopilotUnavailable as exc:
        assert "untested" in str(exc).lower() or "heartbeat" in str(exc).lower()
    else:
        raise AssertionError("connected to a flight controller that is not there")
    try:
        ap.send_attitude(0.0, 5.0, 100.0)
    except AutopilotUnavailable:
        pass
    else:
        raise AssertionError("an unconnected autopilot accepted a command")
    print("[ok] MAVLink: UNTESTED=True, and connect/send raise instead of pretending")
    PASSED.append("mavlink")


def test_quaternion_matches_known_rotations():
    q = euler_to_quaternion(0.0, 0.0, math.radians(90.0))
    assert np.allclose(q, [math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)])
    q = euler_to_quaternion(0.0, math.radians(-10.0), 0.0)
    assert np.allclose(q, [math.cos(math.radians(-5)), 0,
                           math.sin(math.radians(-5)), 0])
    rng = np.random.default_rng(0)
    for _ in range(200):
        q = euler_to_quaternion(*rng.uniform(-math.pi, math.pi, 3))
        assert abs(np.linalg.norm(q) - 1.0) < 1e-12
    print("[ok] quaternions: yaw 90 and pitch -10 exact, 200 random all unit norm")
    PASSED.append("quaternion")


def test_climb_thrust_is_centred_on_hold():
    assert climb_thrust(100.0, 100.0) == 0.5
    assert climb_thrust(200.0, 100.0) == 1.0
    assert climb_thrust(0.0, 100.0) == 0.0
    assert climb_thrust(100.0, None) == 0.5
    print("[ok] GUIDED_NOGPS thrust: 0.5 holds, saturates at 0 and 1")
    PASSED.append("climb_thrust")


if __name__ == "__main__":
    tests = [
        test_excess_tilt_is_refused_not_clamped,
        test_non_finite_commands_are_refused,
        test_negative_tilt_is_refused,
        test_altitude_step_guards_against_a_units_mistake,
        test_altitude_floor_and_ceiling,
        test_it_holds_altitude_while_tilting,
        test_it_climbs_to_a_new_altitude_and_settles,
        test_it_flies_the_commanded_heading_in_calm_air,
        test_steady_speed_is_set_by_tilt_against_drag,
        test_a_crosswind_carries_it_off_its_heading,
        test_telemetry_reports_no_position,
        test_fc_wind_estimate_exists_only_with_gnss,
        test_saturation_is_reported_not_hidden,
        test_mavlink_is_marked_untested_and_fails_loudly,
        test_quaternion_matches_known_rotations,
        test_climb_thrust_is_centred_on_hold,
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

    print(f"\n{len(PASSED)}/{len(tests)} autopilot tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all autopilot tests passed")
