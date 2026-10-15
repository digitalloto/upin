"""Tests for wind-and-tilt dead reckoning (upin/box/wind_dr.py).

SIMULATED flights (upin/learned/sim_flights.py): a multirotor with
quadratic drag in a steady wind with gusts. Learn the wind and the
tilt-to-airspeed curve on the trusted leg, freeze, dead reckon; measure
against the same flight; show the declines; show the stated limit (the
wind shifts after the freeze); run it through the box.

Run: python tests/test_wind_dr.py
"""
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.box.gnss_parser import encode_mon_rf, encode_nav_pvt  # noqa: E402
from upin.box.gateway import DEGRADED, TRUSTED  # noqa: E402
from upin.box.service import Box, BoxConfig  # noqa: E402
from upin.box.wind_dr import WindDeadReckoning, body_accel_ne  # noqa: E402
from upin.console.sources import Msg  # noqa: E402
from upin.core.speed_learner import SpeedLearner, TableMismatchError  # noqa: E402
from upin.core.wind_learner import FlightSample, WindLearner  # noqa: E402
from upin.layers.rf.beacon_ranging import DEG_M  # noqa: E402
from upin.learned.features import G, RATE_HZ, thrust_direction  # noqa: E402
from upin.learned.sim_flights import simulate_flight  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
R95 = 2.4477
STEP_S = 0.5


def windows(rec, step_s=STEP_S, window_s=1.0):
    """One-second means every half second: (t, tilt, direction, accel_ne,
    yaw_rate, true vn, true ve)."""
    n_win = int(window_s * RATE_HZ)
    stride = int(step_s * RATE_HZ)
    out = []
    for k in range(n_win, len(rec.t), stride):
        sl = slice(k - n_win, k)
        td = [thrust_direction(r, p, y) for r, p, y in zip(rec.roll[sl], rec.pitch[sl], rec.yaw[sl])]
        tilt = float(np.mean([x[0] for x in td]))
        d = math.degrees(math.atan2(np.mean([math.sin(math.radians(x[1])) for x in td]),
                                    np.mean([math.cos(math.radians(x[1])) for x in td]))) % 360
        acc = [body_accel_ne(a, r, p, y) for a, r, p, y in
               zip(rec.acc[sl], rec.roll[sl], rec.pitch[sl], rec.yaw[sl])]
        an, ae = float(np.mean([a[0] for a in acc])), float(np.mean([a[1] for a in acc]))
        dyaw = (rec.yaw[k - 1] - rec.yaw[k - n_win] + math.pi) % (2 * math.pi) - math.pi
        out.append((float(rec.t[k - 1]), tilt, d, (an, ae), math.degrees(dyaw / window_s),
                    float(rec.gnss_vn[sl].mean()), float(rec.gnss_ve[sl].mean())))
    return out


def learn(rec, until_s, speed: SpeedLearner, wind: WindLearner):
    """The trusted leg: the Wind Learner's steady samples go into the curve
    in batches once the wind they need is known (as the box does)."""
    pending = []
    for t, tilt, d, acc, rate, vn, ve in windows(rec):
        if t > until_s:
            break
        smp = FlightSample(t, d, tilt, vn, ve, 0.1)
        if wind.add_sample(smp):
            pending.append(smp)
        est = wind.estimate(t)
        if est is not None and len(pending) >= 10:
            speed.learn_from_samples(pending, est)
            pending.clear()
    return wind.estimate(until_s)


def dead_reckon(dr, rec, start_s, end_s, use_imu=True):
    errs, sigs, declines, vel = [], [], {}, []
    for t, tilt, d, acc, rate, vn, ve in windows(rec):
        if t < start_s or t > end_s:
            continue
        v = dr.estimate(t, tilt, d, acc if use_imu else None, rate)
        if v["status"] != "ok":
            declines[v["reason"].split(":")[0]] = declines.get(v["reason"].split(":")[0], 0) + 1
            continue
        errs.append(math.hypot(v["vn"] - vn, v["ve"] - ve))
        sigs.append(v["sigma_ms"])
        vel.append((t, v["vn"], v["ve"], vn, ve))
    return np.array(errs), np.array(sigs), declines, vel


def drift_m(vel, seconds):
    """Position drift of dead reckoning against truth over the first
    `seconds`, and the same for holding the last trusted velocity."""
    if not vel:
        return float("nan"), float("nan")
    t0 = vel[0][0]
    dr_n = dr_e = tr_n = tr_e = co_n = co_e = 0.0
    hold = (vel[0][3], vel[0][4])
    prev = t0
    for t, vn, ve, tn, te in vel:
        if t - t0 > seconds:
            break
        dt = t - prev
        dr_n += vn * dt; dr_e += ve * dt
        tr_n += tn * dt; tr_e += te * dt
        co_n += hold[0] * dt; co_e += hold[1] * dt
        prev = t
    return math.hypot(dr_n - tr_n, dr_e - tr_e), math.hypot(co_n - tr_n, co_e - tr_e)


def test_declines_and_pitot():
    wind = WindLearner()
    dr = WindDeadReckoning(wind, None)
    v = dr.estimate(0.0, 5.0, 90.0)
    assert v["status"] == "declined" and v["reason"].startswith("no wind estimate"), v
    rec = simulate_flight("f", 1, duration_s=240.0, wind_ms=3.0, wind_toward_deg=45.0)
    speed = SpeedLearner("sim-quad", 0.0)
    est = learn(rec, 240.0, speed, wind)
    assert est is not None and speed.primed, (wind.why_not(), speed.table())
    assert dr.estimate(240.0, 5.0, 90.0)["reason"].startswith("no airframe_id")
    dr = WindDeadReckoning(wind, speed)
    lo, hi = speed.learned_range
    v = dr.estimate(240.0, hi + 10.0, 90.0)
    assert v["status"] == "declined" and "outside the learned range" in v["reason"], v
    v = dr.estimate(240.0, None, None)
    assert v["reason"] == "attitude stale or absent"
    v = dr.estimate(240.0, 8.0, 90.0, None, 12.0)
    assert "turning" in v["reason"] and "no IMU" in v["reason"], v
    v = dr.estimate(240.0, 8.0, 90.0, (0.0, 0.0), 12.0)
    assert v["status"] == "ok" and v["imu_corrected"], v        # with the IMU a turn is fine
    # pitot: airspeed along the heading, plus the wind, no curve needed
    v = dr.estimate(240.0, None, None, airspeed=(12.0, 1.0), heading_deg=90.0)
    assert v["status"] == "ok" and v["air_source"] == "pitot"
    assert abs(v["ve"] - (12.0 + est.east_ms)) < 1e-9 and abs(v["vn"] - est.north_ms) < 1e-9
    assert v["sigma_ms"] >= 1.0
    assert dr.estimate(240.0, None, None, airspeed=(12.0, 1.0))["reason"] == "airspeed without a heading"
    wind.gnss_lost(240.0)
    later = dr.estimate(240.0 + 600.0, 8.0, 90.0, (0.0, 0.0))
    assert later["wind"]["frozen"] and later["wind"]["sigma_ms"] > est.sigma_ms, later["wind"]
    print(f"[ok] declines with reasons: no wind, no airframe, tilt past the learned range "
          f"({lo:.1f}-{hi:.1f} deg), stale attitude, turning without an IMU; the pitot path adds "
          f"airspeed along the heading to the wind; the frozen wind's sigma grows "
          f"({est.sigma_ms:.2f} -> {later['wind']['sigma_ms']:.2f} m/s after 10 min)")
    PASSED.append("declines")


def test_learn_then_hold():
    """Learn on the trusted leg, lose GNSS, dead reckon for two minutes:
    the error is inside the stated sigma and far below coasting."""
    rec = simulate_flight("f", 3, duration_s=420.0, wind_ms=3.0, wind_toward_deg=45.0)
    wind, speed = WindLearner(), SpeedLearner("sim-quad", 0.0)
    est = learn(rec, 300.0, speed, wind)
    assert est is not None, wind.why_not()
    tw = rec.meta["true_wind_ne"]
    wind_err = math.hypot(est.north_ms - tw[0], est.east_ms - tw[1])
    assert wind_err < 3.0 * est.sigma_ms + 0.3, (wind_err, est.sigma_ms)
    wind.gnss_lost(300.0)
    dr = WindDeadReckoning(wind, speed)
    errs, sigs, declines, vel = dead_reckon(dr, rec, 300.0, 420.0)
    assert len(errs) >= 0.8 * (len(errs) + sum(declines.values())), declines
    cover = float(np.mean(errs <= R95 * sigs))
    assert cover >= 0.85, (cover, errs.mean(), sigs.mean())
    assert np.sqrt(np.mean(errs ** 2)) < 1.5, np.sqrt(np.mean(errs ** 2))
    d60_dr, d60_hold = drift_m(vel, 60.0)
    assert d60_dr < 0.5 * d60_hold, (d60_dr, d60_hold)
    # without the IMU the turns' lean is read as airspeed: declines while
    # turning, and the steady-flight estimate is what is left
    e2, s2, dec2, _ = dead_reckon(dr, rec, 300.0, 420.0, use_imu=False)
    assert sum(dec2.values()) > 0 and "turning" in " ".join(dec2)
    print(f"[ok] 300 s trusted leg: wind learned to {wind_err:.2f} m/s (stated ±{est.sigma_ms:.2f}), "
          f"curve {speed.learned_range[0]:.1f}-{speed.learned_range[1]:.1f} deg; 120 s dead reckoning: "
          f"{np.sqrt(np.mean(errs ** 2)):.2f} m/s rms with stated ±{sigs.mean():.2f}, 95% circle covers "
          f"{cover:.0%}; drift after 60 s {d60_dr:.0f} m against {d60_hold:.0f} m holding the last "
          f"velocity; without an IMU {sum(dec2.values())} windows declined while turning")
    PASSED.append("hold")


def test_wind_shift_is_the_stated_limit():
    """The same flight flown in a wind 3 m/s stronger after the freeze: the
    frozen wind is wrong by that much, and so is the dead reckoning."""
    a = simulate_flight("f", 5, duration_s=420.0, wind_ms=3.0, wind_toward_deg=45.0)
    b = simulate_flight("f", 5, duration_s=420.0, wind_ms=6.0, wind_toward_deg=45.0)
    wind, speed = WindLearner(), SpeedLearner("sim-quad", 0.0)
    assert learn(a, 300.0, speed, wind) is not None, wind.why_not()
    wind.gnss_lost(300.0)
    dr = WindDeadReckoning(wind, speed)
    e_same, s_same, _, _ = dead_reckon(dr, a, 300.0, 420.0)
    e_shift, s_shift, _, _ = dead_reckon(dr, b, 300.0, 420.0)
    assert np.sqrt(np.mean(e_shift ** 2)) > 2.0 and np.mean(e_shift <= R95 * s_shift) < 0.5
    print(f"[ok] STATED LIMIT: wind shifted by 3 m/s after the freeze -> {np.sqrt(np.mean(e_shift ** 2)):.1f} m/s "
          f"rms error against a stated ±{s_shift.mean():.2f} (covers {np.mean(e_shift <= R95 * s_shift):.0%}); "
          f"the same flight in the learned wind: {np.sqrt(np.mean(e_same ** 2)):.2f} m/s")
    PASSED.append("limit")


def fly_box(cfg, rec, deny_from=300.0, deny_for=90.0, flow=False, capture=None):
    """Drive a Box with the flight record: attitude and IMU at 10 Hz, one
    receiver epoch a second, the position integrated from the true velocity."""
    box = Box(cfg)
    n, e = 0.0, 0.0
    truth, outs = {}, {}
    sub = int(RATE_HZ / 10)
    rng = np.random.default_rng(1)
    for k in range(0, len(rec.t), sub):
        t = float(rec.t[k])
        box.on_fc_message(Msg("ATTITUDE", roll=float(rec.roll[k]), pitch=float(rec.pitch[k]),
                              yaw=float(rec.yaw[k])), t)
        mg = G * 1e-3
        box.on_fc_message(Msg("RAW_IMU", xacc=rec.acc[k, 0] / mg, yacc=rec.acc[k, 1] / mg,
                              zacc=rec.acc[k, 2] / mg, xgyro=rec.gyro[k, 0] * 1000,
                              ygyro=rec.gyro[k, 1] * 1000, zgyro=rec.gyro[k, 2] * 1000), t)
        if flow:
            h = float(rec.yaw[k])
            fwd = rec.gnss_vn[k] * math.cos(h) + rec.gnss_ve[k] * math.sin(h)
            right = -rec.gnss_vn[k] * math.sin(h) + rec.gnss_ve[k] * math.cos(h)
            box.on_fc_message(Msg("OPTICAL_FLOW", flow_comp_m_x=fwd, flow_comp_m_y=right,
                                  quality=200, ground_distance=50.0), t)
        dt = sub / RATE_HZ
        n += rec.gnss_vn[k] * dt
        e += rec.gnss_ve[k] * dt
        if k % int(RATE_HZ / 2) == 0:            # receiver epochs at 2 Hz
            lat = LAT0 + n / DEG_M
            lon = LON0 + e / (DEG_M * math.cos(math.radians(LAT0)))
            denied = deny_from <= t < deny_from + deny_for
            if denied:
                data = encode_mon_rf("critical") + encode_nav_pvt(
                    int(t * 1000), 0, 0, 0, 0, 0, (0, 0, 0), 0, fix_type=0, num_sv=0)
            else:
                data = encode_mon_rf("ok") + encode_nav_pvt(
                    int(t * 1000), lat + rng.normal(0, 1.0) / DEG_M, lon + rng.normal(0, 1.0) / DEG_M,
                    50.0, 1.5, 3.0, (float(rec.gnss_vn[k]), float(rec.gnss_ve[k]), 0.0), 0.1)
            for out, sent in box.on_receiver_bytes(data, t, 1.7e9 + t):
                truth[t] = (n, e)
                outs[t] = out
                if capture is not None:
                    capture(t, box, out)
    return box, truth, outs


def error_at(truth, outs, t):
    o = outs[t]
    if o.lat is None:
        return None
    return math.hypot((o.lat - LAT0) * DEG_M - truth[t][0],
                      (o.lon - LON0) * DEG_M * math.cos(math.radians(LAT0)) - truth[t][1])


def test_through_the_box():
    rec = simulate_flight("f", 7, duration_s=400.0, wind_ms=3.0, wind_toward_deg=45.0)
    base = dict(max_accel_ms2=10.0, max_airspeed_ms=20.0, max_degraded_h_acc_m=1e6,
                airframe_id="sim-quad")
    fed = {"wind_dr": 0, "standby": 0, "declined": {}}

    def cap(t, box, out):
        w = box.last_wind_dr
        if w is None:
            return
        if w["status"] != "ok":
            fed["declined"][w["reason"][:40]] = fed["declined"].get(w["reason"][:40], 0) + 1
        elif w["fed"]:
            fed["wind_dr"] += 1
        else:
            fed["standby"] += 1

    with tempfile.TemporaryDirectory() as d:
        model = os.path.join(d, "speed.json")
        box, truth, outs = fly_box(BoxConfig(**base, wind_dr=True, speed_model=model), rec, capture=cap)
        assert box.speed_samples_learned > 20, box.speed_samples_learned
        t_end = max(t for t in outs if t < 390.0)
        assert outs[360.0].mode == DEGRADED and outs[t_end].mode == DEGRADED
        assert fed["wind_dr"] >= 120, fed
        err_dr = error_at(truth, outs, 360.0)
        assert box.save_models() == [model] and os.path.exists(model)
        box2, truth2, outs2 = fly_box(BoxConfig(**base), rec)
        err_coast = error_at(truth2, outs2, 360.0)
        assert err_dr is not None and err_dr < 0.5 * err_coast, (err_dr, err_coast)
        rec_dict = box.last_record["wind_dr"]
        assert rec_dict["air_source"] == "tilt curve" and rec_dict["wind"]["frozen"] is True
        # a loaded curve is ready from the first epoch; a wrong airframe is refused
        box3 = Box(BoxConfig(**base, wind_dr=True, speed_model=model))
        assert box3.speed.primed
        try:
            Box(BoxConfig(**dict(base, airframe_id="other-quad"), wind_dr=True, speed_model=model))
            raise AssertionError("a curve for another airframe was accepted")
        except TableMismatchError:
            pass
        # precedence: with a flow sensor feeding, wind DR stays in standby
        seen = {}
        fly_box(BoxConfig(**base, wind_dr=True), rec, flow=True,
                capture=lambda t, b, o: seen.__setitem__(t, dict(b.last_wind_dr or {})))
        w = seen[360.0]
        assert w["status"] == "ok" and not w["fed"] and "flow chip" in w["why_not_fed"], w
    print(f"[ok] through the box: curve learned from {box.speed_samples_learned} steady samples on the "
          f"trusted leg; 90 s denied -> wind DR fed {fed['wind_dr']} epochs; error after 60 s denied "
          f"{err_dr:.0f} m against {err_coast:.0f} m coasting; curve saved and reloaded, another "
          f"airframe's refused; with a flow chip feeding, wind DR stands by ('{w['why_not_fed']}')")
    PASSED.append("box")


def test_airspeed_sensor_in_the_box():
    """A fixed wing's pitot: used only when the config says a real sensor
    is fitted; otherwise VFR_HUD.airspeed is parsed but never used."""
    wind = None
    for fitted in (False, True):
        cfg = BoxConfig(max_accel_ms2=10.0, max_airspeed_ms=30.0, max_degraded_h_acc_m=1e6,
                        wind_dr=True, airspeed_sensor=fitted)
        box = Box(cfg)
        vn, ve = 12.0 + 2.1, 2.1                    # 12 m/s north through a 3 m/s NE wind
        n = e = 0.0
        rng = np.random.default_rng(2)
        for k in range(120):
            t = float(k)
            for j in range(10):
                tt = t + j / 10.0
                box.on_fc_message(Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=0.0), tt)
                box.on_fc_message(Msg("VFR_HUD", airspeed=12.0 + rng.normal(0, 0.3), groundspeed=0.0,
                                      heading=0, throttle=50, alt=50.0, climb=0.0), tt)
            n += vn; e += ve
            denied = k >= 80
            data = encode_mon_rf("critical" if denied else "ok") + (
                encode_nav_pvt(int(t * 1000), 0, 0, 0, 0, 0, (0, 0, 0), 0, fix_type=0, num_sv=0) if denied
                else encode_nav_pvt(int(t * 1000), LAT0 + n / DEG_M,
                                    LON0 + e / (DEG_M * math.cos(math.radians(LAT0))), 50.0, 1.5, 3.0,
                                    (vn + rng.normal(0, 0.1), ve + rng.normal(0, 0.1), 0.0), 0.1))
            box.on_receiver_bytes(data, t, 1.7e9 + t)
        assert box.fc.state.airspeed is not None and abs(box.fc.state.airspeed.ms - 12.0) < 1.5
        w = box.last_wind_dr
        if fitted:
            # on one heading the wind triangle is degenerate: the Wind Learner
            # must say so, and the pitot path cannot run without a wind
            assert w["status"] == "declined" and "no wind estimate" in w["reason"], w
            wind = w["reason"]
        else:
            assert w["status"] == "declined", w
    print(f"[ok] VFR_HUD airspeed parsed ({box.fc.state.airspeed.ms:.1f} m/s) but on a single heading "
          f"there is no wind to add, and the box says so: '{wind[:90]}...'; without airspeed_sensor "
          f"= true it is never used")
    PASSED.append("pitot")


if __name__ == "__main__":
    tests = [test_declines_and_pitot, test_learn_then_hold, test_wind_shift_is_the_stated_limit,
             test_through_the_box, test_airspeed_sensor_in_the_box]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} wind-DR tests passed")
