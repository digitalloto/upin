"""Tests for layer 148, camera optical flow with weighted RANSAC.

SIMULATED frames from the simulator's ground texture, with a sweeping grid
of laser dots painted on for the attack. Tests the method and its stated
limits, not a real camera.

Run: python tests/test_camera_flow.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.optical.camera_flow import CameraFlowLayer  # noqa: E402
from upin.simulation.attacks import camera_frame  # noqa: E402

PASSED = []
PX, FOV, AGL, DT = 256, 40.0, 50.0, 0.2
DOTS = {"speed_ne": (0.0, 3.0), "spacing_m": 4.0, "dot_m": 0.5}


def naive_flow():
    """The flow the reel's attack works on: plain matching, plain average."""
    layer = CameraFlowLayer()
    layer.SAD_CAP = None
    layer.USE_RANSAC = False
    return layer


def flight(seconds, seed=1, turn_after=None, yaw_rate=0.0, speed=8.0):
    """Frames at 5 Hz along a path; returns (t, frame, truth fwd/right, heading, gyro)."""
    rng = np.random.default_rng(seed)
    n = e = 0.0
    course = math.radians(90.0)
    out = []
    k = 0
    for t in np.arange(0.0, seconds, DT):
        rate = yaw_rate if (turn_after is None or t >= turn_after) else 0.0
        course += rate * DT
        vn, ve = speed * math.cos(course), speed * math.sin(course)
        n, e = n + vn * DT, e + ve * DT
        hdg = math.degrees(course) % 360.0
        img, _ = camera_frame(e, n, hdg, AGL, FOV, PX, t, pixel_noise=0.02, rng=rng)
        out.append((float(t), img, (speed, 0.0), hdg, (0.0, 0.0, rate), (n, e)))
        k += 1
    return out


def run(layer, frames, dots=None, rng=None):
    results = []
    for t, img, truth, hdg, gyro, (n, e) in frames:
        if dots is not None:
            img, _ = camera_frame(e, n, hdg, AGL, FOV, PX, t, dots=dots, pixel_noise=0.02, rng=rng)
        layer.feed_gyro(*gyro, t)
        layer.feed_height(AGL, 0.5, t)
        layer.feed_attitude(0.0, 0.0, hdg, t)
        layer.feed_frame(img, t, FOV)
        v = layer.solve()
        results.append((t, v, truth))
    return results


def test_contract_and_declines():
    layer = CameraFlowLayer()
    layer.initialize()
    assert audit_layer(layer).compliant
    assert layer.solve()["reason_code"] == NoFixReason.NO_INPUT
    frames = flight(2.0)
    layer.feed_frame(frames[0][1], 0.0, FOV)
    assert "two camera frames" in layer.solve()["reason"]
    layer.feed_frame(frames[1][1], 0.2, FOV)
    assert "height" in layer.solve()["reason"]
    layer.feed_height(AGL, 0.5, 0.2)
    assert "gyro" in layer.solve()["reason"]
    layer.feed_gyro(0, 0, 0, 0.2)
    assert layer.solve()["status"] == "ok"
    layer.feed_frame(frames[5][1], 1.0, FOV)
    assert "apart" in layer.solve()["reason"]
    flat = CameraFlowLayer()
    flat.feed_frame(np.full((PX, PX), 0.5), 0.0, FOV)
    flat.feed_frame(np.full((PX, PX), 0.5), 0.2, FOV)
    flat.feed_height(AGL, 0.5, 0.2)
    flat.feed_gyro(0, 0, 0, 0.2)
    assert "texture" in flat.solve()["reason"]
    print("[ok] declines with reasons: no frames, one frame, no height, no gyro, frames "
          "too far apart, no texture")
    PASSED.append("contract")


def test_honest_flight():
    layer = CameraFlowLayer()
    res = run(layer, flight(30.0, turn_after=10.0, yaw_rate=math.radians(8.0)))
    ok = [(v, truth) for _, v, truth in res if v["status"] == "ok"]
    assert len(ok) >= 0.95 * (len(res) - 1), (len(ok), len(res))
    err = np.array([[v["forward_ms"] - tf, v["right_ms"] - tr] for v, (tf, tr) in ok])
    sig = np.array([v["sigma_ms"] for v, _ in ok])
    rms = float(np.sqrt((err ** 2).mean()))
    cover = float(np.mean(np.abs(err) <= 1.96 * sig[:, None]))
    assert rms < 0.35, rms
    assert cover >= 0.85, cover
    # the simulator's ground is smoother and noisier than real ground, so some
    # honest patches mismatch and trust settles below 1; it must still rise
    assert layer.trust.mean() > 0.6, layer.trust.mean()
    print(f"[ok] honest 30 s flight with a turn: velocity error {rms:.2f} m/s rms, 95% "
          f"interval covers {cover:.0%}; mean trust rose from 0.5 to {layer.trust.mean():.2f}")
    PASSED.append("honest")


def test_pure_rotation_gives_no_velocity():
    rate = math.radians(20.0)
    with_gyro = CameraFlowLayer()
    frames = flight(4.0, yaw_rate=rate, speed=0.0)
    res = run(with_gyro, frames)
    v = [math.hypot(v["forward_ms"], v["right_ms"]) for _, v, _ in res if v["status"] == "ok"]
    without = CameraFlowLayer()
    res2 = run(without, [(t, img, tr, hdg, (0.0, 0.0, 0.0), ne) for t, img, tr, hdg, g, ne in frames])
    v2 = [math.hypot(v["forward_ms"], v["right_ms"]) for _, v, _ in res2 if v["status"] == "ok"]
    assert v and np.mean(v) < 0.4, np.mean(v)
    assert v2 and np.mean(v) < 0.15 * np.mean(v2), (np.mean(v), np.mean(v2))
    print(f"[ok] turning in place at 20 deg/s: {np.mean(v):.2f} m/s with gyro compensation, "
          f"{np.mean(v2):.2f} m/s without it")
    PASSED.append("rotation")


def test_laser_dots_are_thrown_out():
    """Dots 4 m apart: some patches track dots, most track the ground. A
    naive tracker (plain matching, plain average) is dragged; ours is not."""
    frames = flight(20.0, seed=3)
    ours, naive = CameraFlowLayer(), naive_flow()
    run(ours, frames[:50])                                   # 10 s honest: trust is earned
    run(naive, frames[:50])
    r1 = run(ours, frames[50:], dots=DOTS, rng=np.random.default_rng(7))
    r2 = run(naive, frames[50:], dots=DOTS, rng=np.random.default_rng(7))
    e1 = [math.hypot(v["forward_ms"] - 8.0, v["right_ms"]) for _, v, _ in r1 if v["status"] == "ok"]
    e2 = [math.hypot(v["forward_ms"] - 8.0, v["right_ms"]) for _, v, _ in r2 if v["status"] == "ok"]
    assert len(e1) >= 0.8 * len(r1), (len(e1), len(r1))
    assert np.median(e2) > 1.0, np.median(e2)
    assert np.median(e1) < 0.5, np.median(e1)
    print(f"[ok] laser dots 4 m apart sweeping at 3 m/s: a naive tracker is dragged "
          f"{np.median(e2):.1f} m/s off; robust matching + weighted RANSAC stays within "
          f"{np.median(e1):.2f} m/s (medians over {len(e1)} frames)")
    PASSED.append("dots")


def test_dots_in_every_patch_is_a_stated_limit():
    """When the moving pattern is in every patch, everything in the image
    moves together and no image method can tell the floor from the pattern.
    The flow follows it. Asserted so the limit is never forgotten; the
    IMU-based flow integrity check is the remaining defence."""
    dense = {"speed_ne": (0.0, 3.0), "spacing_m": 2.0, "dot_m": 1.0}
    frames = flight(16.0, seed=4)
    ours = CameraFlowLayer()
    run(ours, frames[:30])
    r = run(ours, frames[30:], dots=dense, rng=np.random.default_rng(8))
    e = [math.hypot(v["forward_ms"] - 8.0, v["right_ms"]) for _, v, _ in r if v["status"] == "ok"]
    assert np.median(e) > 1.0, np.median(e)
    print(f"[ok] dots in every patch: the flow follows them ({np.median(e):.1f} m/s off) -- "
          f"the stated limit; only a non-image check (IMU) can catch this")
    PASSED.append("limit")


if __name__ == "__main__":
    tests = [test_contract_and_declines, test_honest_flight, test_pure_rotation_gives_no_velocity,
             test_laser_dots_are_thrown_out, test_dots_in_every_patch_is_a_stated_limit]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} camera-flow tests passed")
