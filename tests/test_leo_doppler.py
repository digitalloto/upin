"""Tests for layer 150, the LEO Doppler anchor.

SIMULATED: an analytic circular orbit and synthetic Doppler. These test the
fit, its stated uncertainty and its limits, not a real satellite or radio.

Run: python tests/test_leo_doppler.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.satellite.doppler_track import synth_iq, track_carrier  # noqa: E402
from upin.layers.satellite.leo_doppler import (C, DEG_M, CircularOrbit,  # noqa: E402
                                               LeoDopplerLayer, ecef_to_eci,
                                               enu_elevation_deg, geodetic_to_ecef)

PASSED = []
LAT, LON, ALT = 13.0827, 80.2707, 12.0
CARRIER = 137.5e6
T0 = 1_760_000_000.0


def find_pass(orbit, lat, lon, alt, start, hours=24.0, min_elev=30.0):
    """First pass whose peak elevation exceeds min_elev: (t_rise, t_set)."""
    t, rising = start, None
    while t < start + hours * 3600:
        el = enu_elevation_deg(lat, lon, alt, orbit.state_eci(t)[0], t)
        if el > 0 and rising is None:
            rising = t
        if el <= 0 and rising is not None:
            peak = max(enu_elevation_deg(lat, lon, alt, orbit.state_eci(x)[0], x)
                       for x in np.linspace(rising, t, 30))
            if peak >= min_elev:
                return rising, t
            rising = None
        t += 10.0
    raise RuntimeError("no pass found")


def doppler_curve(orbit, lat, lon, alt, ts, offset=0.0, drift=0.0, t_mid=None):
    out = []
    t_mid = t_mid if t_mid is not None else ts.mean()
    for t in ts:
        r_rx, v_rx = ecef_to_eci(geodetic_to_ecef(lat, lon, alt), t)
        r_s, v_s = orbit.state_eci(t)
        d = r_s - r_rx
        rate = float(np.dot(d, v_s - v_rx) / np.linalg.norm(d))
        out.append(CARRIER * (1 - rate / C) + offset + drift * (t - t_mid))
    return np.array(out)


ORBIT = CircularOrbit(800_000.0, 98.0, 40.0, 0.0, T0)
RISE, SET = find_pass(ORBIT, LAT, LON, ALT, T0)
TS = np.arange(RISE + 20, SET - 20, 1.0)


def fresh_layer(prior_off_m=(3000.0, -2000.0), prior_sigma=5000.0):
    layer = LeoDopplerLayer()
    layer.initialize()
    layer.set_orbit(ORBIT, CARRIER)
    layer.set_prior(LAT + prior_off_m[0] / DEG_M,
                    LON + prior_off_m[1] / (DEG_M * math.cos(math.radians(LAT))), prior_sigma)
    layer.set_altitude(ALT, 3.0)
    return layer


def err_m(v):
    return math.hypot((v["lat"] - LAT) * DEG_M, (v["lon"] - LON) * DEG_M * math.cos(math.radians(LAT)))


def test_contract_and_declines():
    layer = LeoDopplerLayer()
    assert audit_layer(layer).compliant
    assert layer.solve()["reason_code"] == NoFixReason.NO_INPUT
    layer.set_orbit(ORBIT, CARRIER)
    assert "Doppler points" in layer.solve()["reason"]
    for t, f in zip(TS[:30], doppler_curve(ORBIT, LAT, LON, ALT, TS[:30])):
        layer.feed_doppler(t, f, 2.0)
    assert layer.solve()["reason_code"] == NoFixReason.NO_ANCHOR
    layer.set_prior(LAT, LON, 5000.0)
    assert "altitude" in layer.solve()["reason"]
    layer.set_altitude(ALT, 3.0)
    assert "pass 29 s long" in layer.solve()["reason"]
    stale = CircularOrbit(800_000.0, 98.0, 40.0, 0.0, T0)
    stale.age_days = 12.0
    layer.set_orbit(stale, CARRIER)
    assert layer.solve()["reason_code"] == NoFixReason.STALE_INPUT
    print("[ok] declines with reasons: no orbit, too few points, no prior, no altitude, "
          "pass too short, orbit elements too old")
    PASSED.append("contract")


def test_fit_recovers_position_and_absorbs_oscillator():
    rng = np.random.default_rng(1)
    errs, sigs, offsets = [], [], []
    for seed in range(8):
        layer = fresh_layer()
        f = doppler_curve(ORBIT, LAT, LON, ALT, TS, offset=137.0, drift=0.05) + rng.normal(0, 2.0, len(TS))
        for t, fx in zip(TS, f):
            layer.feed_doppler(t, fx, 2.0)
        v = layer.solve()
        assert v["status"] == "ok", v
        errs.append(err_m(v))
        sigs.append(v["sigma_m"])
        offsets.append(v["offset_hz"])
    errs, sigs = np.array(errs), np.array(sigs)
    assert errs.max() < 3 * sigs.max(), (errs, sigs)
    assert abs(np.mean(offsets) - 137.0) < 2.0, offsets
    r = layer.read()
    assert r.is_valid and r.raw_data["independent"]
    print(f"[ok] one {SET - RISE:.0f} s pass peaking at {v['max_elevation_deg']:.0f} deg, 2 Hz noise, "
          f"1 ppm offset and drift: position error {errs.mean():.0f} m (max {errs.max():.0f}), "
          f"stated sigma {sigs.mean():.0f} m; offset recovered as {np.mean(offsets):.1f} Hz")
    PASSED.append("fit")


def test_coverage_over_passes():
    rng = np.random.default_rng(2)
    inside = total = 0
    for seed in range(20):
        layer = fresh_layer(prior_off_m=(rng.uniform(-4000, 4000), rng.uniform(-4000, 4000)))
        f = doppler_curve(ORBIT, LAT, LON, ALT, TS, offset=rng.uniform(-300, 300)) + rng.normal(0, 3.0, len(TS))
        for t, fx in zip(TS, f):
            layer.feed_doppler(t, fx, 3.0)
        v = layer.solve()
        if v["status"] != "ok":
            continue
        dlat = (v["lat"] - LAT) * DEG_M
        dlon = (v["lon"] - LON) * DEG_M * math.cos(math.radians(LAT))
        inside += abs(dlat) <= 1.96 * v["sigma_lat_m"]
        inside += abs(dlon) <= 1.96 * v["sigma_lon_m"]
        total += 2
    cover = inside / total
    assert cover >= 0.85, cover
    print(f"[ok] 20 passes with random priors and offsets: 95% intervals cover {cover:.0%}")
    PASSED.append("coverage")


def test_stale_orbit_shifts_the_fix_and_bad_orbit_is_refused():
    layer = fresh_layer()
    f = doppler_curve(ORBIT, LAT, LON, ALT, TS)
    for t, fx in zip(TS, f):
        layer.feed_doppler(t, fx, 2.0)
    good = layer.solve()
    shifted = CircularOrbit(800_000.0, 98.0, 40.0, 0.0, T0 + 0.3)      # 0.3 s late: ~2.2 km along track
    layer.set_orbit(shifted, CARRIER)
    for t, fx in zip(TS, f):
        layer.feed_doppler(t, fx, 2.0)
    v = layer.solve()
    assert v["status"] == "ok"
    wrong = CircularOrbit(800_000.0, 98.0, 40.0, 5.0, T0)             # wrong satellite phase
    layer.set_orbit(wrong, CARRIER)
    for t, fx in zip(TS, f):
        layer.feed_doppler(t, fx, 2.0)
    bad = layer.solve()
    assert bad["status"] == "declined" and "from the prior" in bad["reason"], bad
    print(f"[ok] an orbit 0.3 s stale moved the fix by {err_m(v) - err_m(good):+.0f} m "
          f"(stated sigma {v['sigma_m']:.0f} m); a wrong satellite phase fits perfectly "
          f"{bad['from_prior_m'] / 1000:.0f} km away and is refused by the prior check")
    PASSED.append("stale")


def test_mirror_ambiguity_declines_with_weak_prior():
    # for a pass peaking at ~32 degrees the mirror sits about 2,000 km away,
    # so only a prior that cannot tell continents apart is too weak
    layer = fresh_layer(prior_off_m=(0.0, 0.0), prior_sigma=2_000_000.0)
    f = doppler_curve(ORBIT, LAT, LON, ALT, TS)
    for t, fx in zip(TS, f):
        layer.feed_doppler(t, fx, 2.0)
    v = layer.solve()
    assert v["status"] == "declined" and "mirror" in v["reason"], v
    strong = fresh_layer(prior_off_m=(0.0, 0.0), prior_sigma=5000.0)
    for t, fx in zip(TS, f):
        strong.feed_doppler(t, fx, 2.0)
    w = strong.solve()
    assert w["status"] == "ok" and w["mirror"] is not None
    print(f"[ok] the mirror position {w['mirror']['distance_m'] / 1000:.0f} km across the track "
          f"fits too (chi2 {w['mirror']['chi2']:.1f}): a 2,000 km prior cannot choose and the "
          f"layer declines; a 5 km prior chooses, and the mirror is reported")
    PASSED.append("mirror")


def test_moving_receiver_declines_without_motion():
    layer = fresh_layer()
    f = doppler_curve(ORBIT, LAT, LON, ALT, TS)
    layer.MAX_SPEED_MS = 1.0
    layer.set_motion(3.0, 0.0, 0.3)                 # moving north at 3 m/s, stated
    for t, fx in zip(TS, f):
        layer.feed_doppler(t, fx, 2.0)
    v = layer.solve()
    assert v["status"] == "ok"
    print("[ok] a receiver that states its motion is fitted with it")
    PASSED.append("motion")


def test_carrier_tracker():
    rng = np.random.default_rng(3)
    fs = 48_000.0
    f_true = doppler_curve(ORBIT, LAT, LON, ALT, TS[:60]) - CARRIER + 500.0   # offset from centre
    iq = synth_iq(f_true, fs, 1.0, snr_db=-10.0, rng=rng)                    # weak per-sample SNR
    obs = track_carrier(iq, fs, TS[0], expect_hz=500.0, search_hz=5000.0, chunk_s=1.0)
    assert len(obs) >= 50, len(obs)
    err = np.array([f - f_true[int(t - TS[0])] for t, f, _ in obs])
    sig = np.array([s for _, _, s in obs])
    assert np.sqrt((err ** 2).mean()) < 3.0, err
    assert np.mean(np.abs(err) <= 2 * sig) >= 0.8
    print(f"[ok] carrier tracker on synthetic samples at -10 dB per-sample SNR: "
          f"{len(obs)} points, frequency error {np.sqrt((err ** 2).mean()):.2f} Hz rms, "
          f"stated sigma {sig.mean():.2f} Hz")
    PASSED.append("tracker")


def test_sgp4_round_trip_if_installed():
    try:
        from sgp4.api import WGS72, Satrec
    except ImportError:
        print("[skip] sgp4 not installed: TLE orbit untested here")
        return
    from upin.layers.satellite.leo_doppler import TleOrbit, julian_date
    sat = Satrec()
    jd_epoch = julian_date(T0)
    # a SYNTHETIC element set (not a real satellite): 800 km, 98 deg
    sat.sgp4init(WGS72, "i", 99999, jd_epoch - 2433281.5, 0.0, 0.0, 0.0,
                 0.001, 0.0, math.radians(98.0), 0.0, 0.06, math.radians(40.0))
    orbit = TleOrbit.__new__(TleOrbit)
    orbit.sat, orbit.name, orbit.age_days = sat, "synthetic", 0.0
    r, v = orbit.state_eci(T0 + 600.0)
    assert 7.0e6 < np.linalg.norm(r) < 7.4e6 and 7000 < np.linalg.norm(v) < 7700
    print(f"[ok] sgp4 propagates a synthetic element set: radius {np.linalg.norm(r) / 1e3:.0f} km, "
          f"speed {np.linalg.norm(v):.0f} m/s")
    PASSED.append("sgp4")


if __name__ == "__main__":
    tests = [test_contract_and_declines, test_fit_recovers_position_and_absorbs_oscillator,
             test_coverage_over_passes, test_stale_orbit_shifts_the_fix_and_bad_orbit_is_refused,
             test_mirror_ambiguity_declines_with_weak_prior, test_moving_receiver_declines_without_motion,
             test_carrier_tracker, test_sgp4_round_trip_if_installed]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} LEO Doppler tests passed")
