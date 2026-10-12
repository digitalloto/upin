"""Tests for the optical-flow integrity check (the laser-dot attack).

Flights are SIMULATED. The tests check the logic and its stated limits, not
how a real flow sensor behaves; thresholds must be calibrated on the real
one.

Run: python tests/test_flow_integrity.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.box.service import BoxConfig  # noqa: E402
from upin.console.sources import SimSource  # noqa: E402
from upin.console.state import ConsoleState  # noqa: E402
from upin.detection.flow_integrity import OK, SUSPECT, FlowIntegrityCheck  # noqa: E402
from upin.learned.features import to_heading_frame  # noqa: E402
from upin.learned.sim_flights import simulate_flight  # noqa: E402

PASSED = []
REC = simulate_flight("flow", 7, 300, wind_ms=3)


def fly(drag_east=lambda t: 0.0, gnss=False, heading_sigma=2.0, predictor=None):
    """Feed the check a simulated flight: IMU and attitude at 50 Hz, flow at
    10 Hz with world-frame drag (dots sweeping east), optional GNSS."""
    rng = np.random.default_rng(1)
    c = FlowIntegrityCheck(heading_sigma_deg=heading_sigma)
    out = []
    for k in range(len(REC)):
        t = float(REC.t[k])
        c.feed_attitude(REC.roll[k], REC.pitch[k], REC.yaw[k], t)
        c.feed_imu(REC.acc[k], t)
        if k % 5 == 0:
            f, r = to_heading_frame(REC.gnss_vn[k], REC.gnss_ve[k] + drag_east(t), REC.yaw[k])
            c.feed_flow(f + rng.normal(0, 0.2), r + rng.normal(0, 0.2), t)
            if gnss:
                c.feed_gnss_velocity(REC.gnss_vn[k], REC.gnss_ve[k], 0.15, t)
            if predictor:
                c.feed_predictor(*predictor(k), t)
            out.append((t, c.check(t)))
    return out


def test_honest_flight_no_flags():
    for gnss in (False, True):
        flags = [t for t, v in fly(gnss=gnss) if v["verdict"] == SUSPECT]
        assert not flags, flags[:5]
    print("[ok] honest simulated flight (300 s, manoeuvring): no flags, with or without GNSS")
    PASSED.append("honest")


def test_fast_drag_caught_latched_released():
    out = fly(lambda t: 2.5 if 100 <= t < 160 else 0.0)
    first = next(t for t, v in out if v["verdict"] == SUSPECT)
    during = [v["verdict"] for t, v in out if 102 <= t < 160]
    after = [v["verdict"] for t, v in out if t >= 170]
    assert 100 <= first <= 101, first
    assert all(x == SUSPECT for x in during)
    assert all(x == OK for x in after)
    print(f"[ok] laser-dot sweep at 2.5 m/s: flagged at {first - 100:.1f} s, kept "
          f"(latched) for the whole minute with no GNSS, released when it stopped")
    PASSED.append("drag")


def test_dragged_drone_with_frozen_flow():
    c = FlowIntegrityCheck()
    for k in range(300):
        t = k * 0.02
        c.feed_attitude(0.0, 0.0, 0.0, t)
        ae = 2.0 if t >= 3.0 else 0.0                 # the drone accelerates east
        c.feed_imu((0.0, ae, -9.80665), t)
        if k % 5 == 0:
            c.feed_flow(0.0, 0.0, t)                  # flow held still
            v = c.check(t)
    assert v["verdict"] == SUSPECT
    print("[ok] the drone accelerates (IMU) while flow stays still: flagged")
    PASSED.append("frozen")


def test_slow_drag_limit_and_gnss_catches_it():
    slow = lambda t: 0.03 * (t - 100) if t >= 100 else 0.0  # noqa: E731
    imu_only = [v["verdict"] for t, v in fly(slow)]
    assert SUSPECT not in imu_only
    with_gnss = fly(slow, gnss=True)
    first = next(t for t, v in with_gnss if v["verdict"] == SUSPECT)
    print(f"[ok] slow drag (0.03 m/s^2): passes the IMU test -- the stated limit; "
          f"trusted GNSS catches it after {first - 100:.0f} s "
          f"({slow(first):.1f} m/s of drag)")
    PASSED.append("slow")


def test_predictor_disagreement():
    pred = lambda k: (REC.gnss_vn[k] + (3.0 if REC.t[k] > 150 else 0.0),  # noqa: E731
                      REC.gnss_ve[k], 0.3)
    out = fly(predictor=pred)
    assert any(v["verdict"] == SUSPECT for t, v in out if t > 151)
    assert not any(v["verdict"] == SUSPECT for t, v in out if t < 150)
    print("[ok] flow and the AI predictor disagree by 3 m/s: flagged")
    PASSED.append("predictor")


def test_coarse_reference_cannot_clear_latch_and_expiry():
    coarse = lambda k: (REC.gnss_vn[k], REC.gnss_ve[k], 3.0)  # noqa: E731  sigma 3 m/s
    out = fly(lambda t: 2.5 if t >= 100 else 0.0, predictor=coarse)
    limit = 100 + FlowIntegrityCheck.LATCH_MAX_S
    held = [v["verdict"] for t, v in out if 101 <= t < limit]
    assert all(x == SUSPECT for x in held)
    assert any("expired" in v["reason"] for t, v in out if limit <= t < limit + 1)
    assert all(v["verdict"] == OK for t, v in out if t > limit + 1)
    print("[ok] a reference too coarse to resolve the jump (predictor sigma 3 m/s) "
          "cannot clear it; the latch expires after 60 s and a steady attack is "
          "then re-admitted -- the stated limit")
    PASSED.append("latch")


def _sim(action, seed=4):
    st = ConsoleState("sim", "S", True, SimSource.controls)
    s = SimSource(st, 13.08, 80.27, seed=seed,
                  cfg=BoxConfig(max_accel_ms2=6, max_airspeed_ms=20, flow_check_action=action))
    rows, modes, flow_updates = [], [], []
    for k in range(260):
        if k == 200:
            s.control("flow_attack")
        if k == 240:
            s.control("flow_attack")
        s.step()
        g = st.get()
        c = [x for x in g["checks"] if x["check"] == "optical flow integrity"][0]
        rows.append(c)
        modes.append(g["mode"])
        flow_updates.append(sum(1 for d in s.box.gateway.kf.decisions if d.source == "optical_flow"))
    return rows, modes, flow_updates


def test_box_distrust_rejects_and_substitutes():
    rows, modes, upd = _sim("distrust")
    assert all(r["status"] == "PASS" for r in rows[20:200])
    attack = rows[202:239]
    assert all(r["status"] == "FAIL" and "substitute" in r["detail"] for r in attack)
    assert upd[238] == upd[202], "flow was fed during the attack"
    assert "DEGRADED" not in modes and "NO_FIX" not in modes[5:]
    print(f"[ok] box, distrust (default): attack flagged FAIL for its whole 40 s, "
          f"flow not fed ('{attack[0]['detail'].split('substitute: ')[1]}'), GNSS "
          f"stayed TRUSTED throughout")
    PASSED.append("box_distrust")


def test_box_warn_feeds_and_why_it_is_not_default():
    rows, modes, upd = _sim("warn")
    assert any(r["status"] == "WARN" for r in rows[200:240])
    assert upd[238] > upd[202], "warn mode should still feed flow"
    poisoned = modes[200:260].count("DEGRADED")
    print(f"[ok] box, warn: flagged WARN but flow still fed; the fooled flow "
          f"poisoned the estimate and good GNSS was distrusted for {poisoned} of 60 s "
          f"-- why distrust is the default")
    PASSED.append("box_warn")


def test_not_run_without_flow():
    c = FlowIntegrityCheck()
    assert c.check(1.0)["verdict"] == "NOT_RUN"
    print("[ok] no flow: NOT_RUN with the reason")
    PASSED.append("notrun")


if __name__ == "__main__":
    tests = [test_honest_flight_no_flags, test_fast_drag_caught_latched_released,
             test_dragged_drone_with_frozen_flow, test_slow_drag_limit_and_gnss_catches_it,
             test_predictor_disagreement, test_coarse_reference_cannot_clear_latch_and_expiry,
             test_box_distrust_rejects_and_substitutes,
             test_box_warn_feeds_and_why_it_is_not_default, test_not_run_without_flow]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} flow-integrity tests passed")
