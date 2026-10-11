"""Tests for the AI motion predictor (layer 147) and its flight-by-flight
learning.

All flights here are SIMULATED (upin/learned/sim_flights.py). They test the
pipeline, the learning loop and the honesty guards. They do not say how
well the predictor will do on a real drone; that comes only from real
flight logs, scored flight by flight in the library's LEARNED_IO.md.

Run: python tests/test_learned_io.py
"""
import math
import sys
import tempfile

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.fusion.honest_kalman import HonestKalmanFusion  # noqa: E402
from upin.layers.inertial.learned_io import LearnedInertialOdometryLayer  # noqa: E402
from upin.learned.features import RATE_HZ, windows  # noqa: E402
from upin.learned.flight_library import (FlightLibrary, evaluate,  # noqa: E402
                                         record_from_messages)
from upin.learned.sim_flights import simulate_flight  # noqa: E402

PASSED = []
_LIB = {}


def library():
    """A library of six simulated flights in light wind (1-3 m/s), shared by
    the tests that need a trained model."""
    if "lib" not in _LIB:
        d = tempfile.mkdtemp()
        lib = FlightLibrary(d)
        reports = [lib.learn_from_flight(simulate_flight(f"s{i}", 50 + i, 240,
                                                         wind_ms=1 + (i % 3),
                                                         wind_toward_deg=50 * i),
                                         epochs=150)
                   for i in range(6)]
        _LIB.update(lib=lib, dir=d, reports=reports)
    return _LIB["lib"], _LIB["reports"]


def feed_layer(layer, rec, end_index):
    n = int(RATE_HZ)
    for k in range(end_index - int(1.2 * n), end_index + 1):
        t = float(rec.t[k])
        layer.feed_imu(rec.acc[k], rec.gyro[k], t)
        layer.feed_attitude(rec.roll[k], rec.pitch[k], rec.yaw[k], t)
        layer.feed_throttle(rec.throttle[k], t)
    return float(rec.t[end_index])


def test_contract_and_declines():
    layer = LearnedInertialOdometryLayer()
    assert audit_layer(layer).compliant
    assert layer.read().raw_data["no_fix_reason"] == NoFixReason.NO_CALIBRATION
    lib, _ = library()
    model = lib.live_model()
    layer = LearnedInertialOdometryLayer(model)
    assert layer.predict(10.0)["reason_code"] == NoFixReason.NO_INPUT
    other = LearnedInertialOdometryLayer(model, airframe_id="a-different-quad")
    assert other.predict(10.0)["reason_code"] == NoFixReason.FAILED_VALIDATION
    rec = simulate_flight("x", 999, 30)
    t = feed_layer(layer, rec, 1000)
    assert layer.predict(t)["reason_code"] == NoFixReason.INSUFFICIENT_INPUT   # no wind
    print("[ok] declines: no model, no IMU, wrong airframe, no wind -- each with its reason")
    PASSED.append("contract")


def test_learns_and_states_honest_uncertainty():
    lib, reports = library()
    model = lib.live_model()
    rec = simulate_flight("held-out", 777, 240, wind_ms=2.0, wind_toward_deg=200)
    w = rec.meta["true_wind_ne"]
    X, Y, _ = windows(rec, tuple(w))
    mu, sig = model.predict(X)
    rms_model = float(np.sqrt(((mu - Y) ** 2).mean()))
    rms_zero = float(np.sqrt((Y ** 2).mean()))
    cov = model.coverage95(X, Y)
    assert rms_model < 0.4 * rms_zero, (rms_model, rms_zero)
    assert 0.85 <= cov <= 0.995, cov
    print(f"[ok] SIMULATED held-out flight: air-velocity error {rms_model:.2f} m/s rms "
          f"vs {rms_zero:.2f} predicting zero; 95% interval covers {cov:.0%}")
    PASSED.append("learns")


def test_each_flight_tested_before_learning_and_split():
    lib, reports = library()
    assert "before_learning" not in reports[0]
    assert all("before_learning" in r for r in reports[1:])
    roles = [r["role"] for r in reports]
    assert roles == ["train", "train", "validation", "train", "train", "validation"], roles
    for m in lib.m["models"]:
        assert not set(m["trained_on"]) & set(m["validated_on"])
    report = (lib.root / "LEARNED_IO.md").read_text()
    assert "before" in report and "SIMULATED" in report
    print("[ok] every flight after the first is scored before it is learned from; "
          "validation flights are never trained on; the learning record says SIMULATED")
    PASSED.append("loop")


def test_no_silent_regression():
    lib, _ = library()
    live_before = lib.m["live"]
    r = lib.learn_from_flight(simulate_flight("s-bad", 4242, 240, wind_ms=2.0), epochs=1)
    assert r["model"] is not None and not r["model"]["promoted"], r["model"]
    assert lib.m["live"] == live_before and "live kept" in r["model"]["reason"]
    print(f"[ok] a deliberately undertrained version (1 epoch) is refused: "
          f"{r['model']['reason']}")
    PASSED.append("regression")


def test_library_refuses_mixing():
    lib, _ = library()
    real = simulate_flight("pretend-real", 1, 60)
    real.source = "ardupilot log: x.bin"
    for rec, words in ((real, "refusing to mix"),
                       (simulate_flight("s0", 2, 60), "already"),
                       (simulate_flight("q", 3, 60, airframe=__import__(
                           "upin.layers.inertial.command_dr", fromlist=["AirframeModel"]
                       ).AirframeModel(thrust_to_mass=20, drag_coeff=0.1, calibrated=True,
                                       airframe_id="other")), "airframe")):
        try:
            lib.learn_from_flight(rec)
            raise AssertionError(f"accepted: {words}")
        except ValueError as e:
            assert words in str(e), e
    print("[ok] library refuses simulated+real mixing, duplicate flights and a "
          "second airframe")
    PASSED.append("mixing")


def test_weather_flag():
    lib, _ = library()
    model = lib.live_model()
    rec = simulate_flight("w", 31, 30, wind_ms=2.0)
    layer = LearnedInertialOdometryLayer(model, airframe_id="sim-quad")
    t = feed_layer(layer, rec, 1200)
    layer.set_wind(1.0, 1.0, 0.2, 0.3)
    inside = layer.predict(t)
    layer.set_wind(3.2, 2.0, 0.2, 0.3)          # 3.8 m/s; trained winds reach ~1.9
    outside = layer.predict(t)
    layer.set_wind(25.0, 0.0, 0.2, 0.3)
    far = layer.predict(t)
    assert inside["status"] == "ok" and not inside["flags"]
    assert outside["status"] == "ok" and any("wind" in f for f in outside["flags"])
    assert outside["sigma_air_ms"] > inside["sigma_air_ms"]
    assert far["status"] == "declined" and "far outside" in far["reason"]
    env = model.meta["envelope"]["wind_speed_ms"]
    print(f"[ok] weather: trained in {env[0]:.1f}-{env[1]:.1f} m/s wind -> 1.4 m/s "
          f"inside; 3.8 m/s flagged ('{outside['flags'][0]}'), uncertainty widened "
          f"x{outside['widened_by']:.0f}; 25 m/s declined ('{far['reason']}')")
    PASSED.append("weather")


def test_input_range_guard_and_gate():
    lib, _ = library()
    layer = LearnedInertialOdometryLayer(lib.live_model())
    rec = simulate_flight("g", 32, 30)
    rec.gyro[:, 2] = 3.0                             # 3 rad/s spin: never trained on
    t = feed_layer(layer, rec, 1200)
    layer.set_wind(1.0, 0.0, 0.2)
    p = layer.predict(t)
    assert p["status"] == "declined" or p["flags"], p
    kf = HonestKalmanFusion()
    for k in range(20):
        kf.update_position(13.0, 80.0, 2.0, t=float(k))
        kf.update_velocity(0.0, 0.0, 0.2)
    d = kf.update_velocity(15.0, -12.0, 0.3, source="learned_io")
    assert not d.accepted
    print("[ok] inputs far outside training are flagged or declined; a wildly "
          "wrong velocity is rejected by the Kalman gate, not trusted")
    PASSED.append("guard")


def test_extractor_from_log_messages():
    rec = simulate_flight("log", 5, 40)
    msgs = {"IMU": [], "ATT": [], "GPS": [], "CTUN": [], "BARO": []}
    for k in range(len(rec)):
        us = int(rec.t[k] * 1e6) + 5_000_000
        msgs["IMU"].append({"TimeUS": us, "I": 0, "AccX": rec.acc[k, 0], "AccY": rec.acc[k, 1],
                            "AccZ": rec.acc[k, 2], "GyrX": rec.gyro[k, 0],
                            "GyrY": rec.gyro[k, 1], "GyrZ": rec.gyro[k, 2]})
        if k % 2 == 0:
            msgs["ATT"].append({"TimeUS": us, "Roll": math.degrees(rec.roll[k]),
                                "Pitch": math.degrees(rec.pitch[k]),
                                "Yaw": math.degrees(rec.yaw[k])})
            msgs["CTUN"].append({"TimeUS": us, "ThO": rec.throttle[k]})
        if k % 10 == 0:
            spd = math.hypot(rec.gnss_vn[k], rec.gnss_ve[k])
            msgs["GPS"].append({"TimeUS": us, "I": 0, "Status": 3 if k < 1500 else 1,
                                "NSats": 14, "HDop": 0.8, "Spd": spd,
                                "GCrs": math.degrees(math.atan2(rec.gnss_ve[k], rec.gnss_vn[k])) % 360})
            msgs["BARO"].append({"TimeUS": us, "I": 0, "Press": 100500.0, "Temp": 31.0})
    out = record_from_messages(msgs, "log", "sim-quad", "ardupilot log: synthetic fixture")
    k = 500
    assert abs(out.acc[k, 0] - rec.acc[k, 0]) < 0.2 and abs(out.roll[k] - rec.roll[k]) < 0.05
    assert out.gnss_ok[:1400].all() and not out.gnss_ok[1600:].any()
    assert abs(out.pressure_hpa.mean() - 1005.0) < 1e-6
    print("[ok] log extraction (synthetic dataflash-shaped fixture): resampled to "
          "50 Hz, GNSS marked bad without a 3-D fix. Real .bin parsing UNTESTED")
    PASSED.append("extract")


def test_box_uses_the_predictor_when_gnss_goes():
    """End to end through the real box: a simulated flight's FC messages and
    receiver epochs; GNSS denied for the last 60 s. With a model loaded the
    learned velocity feeds the filter, and the estimate drifts less than
    coasting. SIMULATED -- shows the path works, not real accuracy."""
    from upin.box.gnss_parser import encode_nav_pvt
    from upin.box.service import Box, BoxConfig
    from upin.console.sources import Msg
    from upin.detection.reachability import DEG_M

    lib, _ = library()
    model_path = str(lib.root / "models" / f"v{lib.m['live']}.npz")
    rec = simulate_flight("box", 88, 300, wind_ms=2.0, wind_toward_deg=120)
    dt = 1.0 / RATE_HZ
    pn, pe = np.cumsum(rec.gnss_vn) * dt, np.cumsum(rec.gnss_ve) * dt
    lat0, lon0 = 13.0, 80.0
    ll = lambda n, e: (lat0 + n / DEG_M, lon0 + e / (DEG_M * math.cos(math.radians(lat0))))  # noqa: E731
    errors = {}
    for with_model in (False, True):
        cfg = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, airframe_id="sim-quad",
                        learned_io_model=model_path if with_model else "",
                        max_degraded_h_acc_m=1e6)
        box = Box(cfg)
        for k in range(len(rec)):
            t = float(rec.t[k])
            box.on_fc_message(Msg("ATTITUDE", roll=rec.roll[k], pitch=rec.pitch[k],
                                  yaw=rec.yaw[k]), t)
            a, g = rec.acc[k] / 9.80665e-3, rec.gyro[k] * 1000.0
            box.on_fc_message(Msg("RAW_IMU", xacc=a[0], yacc=a[1], zacc=a[2],
                                  xgyro=g[0], ygyro=g[1], zgyro=g[2]), t)
            pwm = 1000 + 1000 * rec.throttle[k]
            box.on_fc_message(Msg("SERVO_OUTPUT_RAW", servo1_raw=pwm, servo2_raw=pwm,
                                  servo3_raw=pwm, servo4_raw=pwm), t)
            if k % int(RATE_HZ) == 0 and k > 0:
                box.deny_gnss = t > 240
                lat, lon = ll(pn[k], pe[k])
                box.on_receiver_bytes(encode_nav_pvt(int(t * 1000), lat, lon, 50, 1.5, 3,
                                                     (rec.gnss_vn[k], rec.gnss_ve[k], 0), 0.15),
                                      t, 0.0)
        out = box.gateway.log[-1]
        tl, tn = ll(pn[-1], pe[-1])
        errors[with_model] = math.hypot((out.lat - tl) * DEG_M,
                                        (out.lon - tn) * DEG_M * math.cos(math.radians(lat0)))
        if with_model:
            used = [d for d in box.gateway.kf.decisions if d.source == "learned_io"]
            assert used and box.learned.last and box.learned.last["status"] == "ok"
    assert errors[True] < errors[False], errors
    print(f"[ok] through the real box (SIMULATED): after 60 s without GNSS, error "
          f"{errors[True]:.1f} m with the AI predictor vs {errors[False]:.1f} m coasting")
    PASSED.append("box")


if __name__ == "__main__":
    tests = [test_contract_and_declines, test_learns_and_states_honest_uncertainty,
             test_each_flight_tested_before_learning_and_split, test_no_silent_regression,
             test_library_refuses_mixing, test_weather_flag, test_input_range_guard_and_gate,
             test_extractor_from_log_messages, test_box_uses_the_predictor_when_gnss_goes]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} AI motion predictor tests passed")
