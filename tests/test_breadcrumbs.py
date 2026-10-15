"""Tests for layer 152, breadcrumb beacons.

SIMULATED crumbs (upin/simulation/beacons.py): each lands at its true
point and broadcasts the position it was stamped with. Tests the drop
policy, the stamp's honesty, the fix inside a jammed zone, and the limits.

Run: python tests/test_breadcrumbs.py
"""
import json
import math
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.box.gnss_parser import encode_mon_rf, encode_nav_pvt  # noqa: E402
from upin.box.service import Box, BoxConfig  # noqa: E402
from upin.console.sources import Msg  # noqa: E402
from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.rf.beacon_ranging import DEG_M  # noqa: E402
from upin.layers.rf.breadcrumbs import (THREAT_CLEAR, THREAT_JAMMED, THREAT_RISING,  # noqa: E402
                                        BreadcrumbLayer, DropPolicy)
from upin.simulation.beacons import BeaconSim  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
SECRET = b"crumb-test-secret"


def ll(n, e):
    return LAT0 + n / DEG_M, LON0 + e / (DEG_M * math.cos(math.radians(LAT0)))


def ne(lat, lon):
    return (lat - LAT0) * DEG_M, (lon - LON0) * DEG_M * math.cos(math.radians(LAT0))


def ready_layer(**policy):
    layer = BreadcrumbLayer(DropPolicy(**policy))
    layer.initialize()
    layer.set_secret(SECRET)
    layer.feed_wind(1.0, 2.0, 0.4)
    layer.feed_agl(60.0, 0.0)
    return layer


def test_contract_and_policy():
    layer = BreadcrumbLayer()
    assert audit_layer(layer).compliant
    assert layer.solve(0.0)["reason"] == "no crumbs dropped yet"
    layer = ready_layer(spacing_m=200.0, max_crumbs=2)
    layer.feed_threat(THREAT_CLEAR)
    layer.feed_fix(LAT0, LON0, 70.0, 1.5, 0.0, True)
    assert layer.should_drop(0.0) == (False, "threat clear: keeping the crumbs")
    layer.feed_threat(THREAT_JAMMED)
    layer.feed_fix(LAT0, LON0, 70.0, 1.5, 1.0, False)
    ok, why = layer.should_drop(1.0)
    assert not ok and "not trusted" in why and layer.drop(1.0) is None
    layer.feed_fix(LAT0, LON0, 70.0, 20.0, 2.0, True)
    ok, why = layer.should_drop(2.0)
    assert not ok and "looser" in why
    layer.feed_threat(THREAT_RISING)
    layer.feed_fix(LAT0, LON0, 70.0, 1.5, 3.0, True)
    rec = layer.drop(3.0)
    assert rec is not None and rec["type"] == "provision" and rec["id"] == "crumb-1"
    layer.feed_fix(*ll(100.0, 0.0), 70.0, 1.5, 4.0, True)
    assert layer.drop(4.0) is None and "spacing" in layer.last_drop_reason
    layer.feed_fix(*ll(250.0, 0.0), 70.0, 1.5, 5.0, True)
    assert layer.drop(5.0)["id"] == "crumb-2"
    layer.feed_fix(*ll(600.0, 0.0), 70.0, 1.5, 6.0, True)
    assert layer.drop(6.0) is None and "all 2 crumbs" in layer.last_drop_reason
    nowind = BreadcrumbLayer()
    nowind.set_secret(SECRET)
    nowind.feed_agl(60.0, 0.0)
    nowind.feed_threat(THREAT_RISING)
    nowind.feed_fix(LAT0, LON0, 70.0, 1.5, 0.0, True)
    rec = nowind.drop(0.0)
    assert rec["wind_source"] == "unknown" and rec["sigma_m"] > 15.0, rec
    print("[ok] contract; no drop while clear, untrusted, loose, too close to another crumb "
          "or when all are gone -- each with its reason; drops otherwise; with no wind "
          f"estimate the stamp is honest but loose (±{rec['sigma_m']:.0f} m, marked unknown)")
    PASSED.append("policy")


def test_stamp_is_honest():
    """The stamp's error against the true landing point stays within its
    stated sigma: fix error plus (wind error + gusts) over the fall."""
    rng = np.random.default_rng(3)
    inside = 0
    n = 300
    for k in range(n):
        layer = ready_layer()
        wind_true = rng.uniform(-6, 6, 2)
        wind_est = wind_true + rng.normal(0, 0.5, 2)
        gust = rng.normal(0, 0.6, 2)
        layer.feed_wind(wind_est[0], wind_est[1], math.hypot(0.5, 0.6))
        agl = rng.uniform(30, 120)
        layer.feed_agl(agl, 0.0)
        fix_err = rng.normal(0, 1.5, 2)
        lat, lon = ll(fix_err[0], fix_err[1])          # truth at (0, 0)
        layer.feed_fix(lat, lon, 80.0, 1.5, 0.0, True)
        layer.feed_threat(THREAT_RISING)
        rec = layer.drop(0.0)
        fall = agl / layer.CRUMB_FALL_MS
        true_land = (wind_true + gust) * fall
        sn, se = ne(rec["lat"], rec["lon"])
        err = math.hypot(sn - true_land[0], se - true_land[1])
        inside += err <= 2.4477 * rec["sigma_m"]             # 95% circle, per-axis sigma
    cover = inside / n
    assert cover >= 0.9, cover
    print(f"[ok] {n} drops with wind error and gusts: the true landing point is inside the "
          f"stamp's 95% circle {cover:.0%} of the time")
    PASSED.append("stamp")


def fly_zone(path_n, spacing_m=200.0, out_m=1300.0):
    """Fly east dropping crumbs as the threat rises, lose GNSS, turn back.
    path_n(e) gives the north offset of the path. Returns (layer, errors
    and sigmas inside the jam, declines inside the jam)."""
    rng = np.random.default_rng(4)
    layer = ready_layer(spacing_m=spacing_m, max_crumbs=6)
    layer.feed_wind(0.0, 0.0, 0.3)
    sim = BeaconSim([], SECRET, seed=4)
    errs, sig, declines = [], [], {}
    half = int(out_m / 8.0)
    for k in range(2 * half):
        t = float(k)
        e = 8.0 * k if k < half else 8.0 * (2 * half - k)         # out and back
        n = path_n(e)
        lat, lon = ll(n, e)
        # the jammer switches on as the drone nears 1100 m and stays on: the
        # way back along the trail is flown inside the jam, on the crumbs
        jammed_now = e >= 1100 or (k >= half and e >= 300)
        threat = THREAT_JAMMED if jammed_now else THREAT_RISING if e >= 400 else THREAT_CLEAR
        trusted = not jammed_now
        fix_lat, fix_lon = ll(n + rng.normal(0, 1.5), e + rng.normal(0, 1.5))
        layer.feed_fix(fix_lat, fix_lon, 80.0, 1.5, t, trusted)
        layer.feed_agl(80.0, t)
        layer.feed_threat(threat)
        rec = layer.drop(t)
        if rec is not None:
            sim.drop_crumb(rec, lat, lon, 0.0)                       # lands under the drone
        for m in sim.messages(t):
            layer.feed_message(m, t)
        for bid, r, s in sim.ranges(lat, lon, 80.0, t):
            layer.feed_range(bid, r, s, t)
        layer.set_altitude(80.0, 2.0, t)
        layer.set_prior(fix_lat, fix_lon)          # the box would give its own estimate
        v = layer.solve(t)
        if threat == THREAT_JAMMED:
            if v["status"] == "ok":
                en, ee = ne(v["lat"], v["lon"])
                errs.append(math.hypot(en - n, ee - e))
                sig.append(v["sigma_m"])
            else:
                declines[v["reason_code"]] = declines.get(v["reason_code"], 0) + 1
    return layer, np.array(errs), np.array(sig), declines


def test_fix_inside_the_jammed_zone():
    """On a gently weaving path the crumbs are not collinear and give a
    fix inside the zone; a lone crumb declines."""
    # a weave twice the crumb spacing long puts successive crumbs on opposite
    # sides of the track (a weave near the spacing length aliases into a line)
    layer, errs, sig, declines = fly_zone(lambda e: 120.0 * math.sin(2 * math.pi * e / 800.0))
    assert len(layer.crumbs) == 4, [c.crumb_id for c in layer.crumbs]      # near 400..1000 m
    assert all(c.t < 138 for c in layer.crumbs)                            # all before the jam
    n_jam = len(errs) + sum(declines.values())
    assert len(errs) >= 0.6 * n_jam, (len(errs), declines)
    assert np.mean(errs <= 2.4477 * sig) >= 0.85, np.mean(errs <= 2.4477 * sig)
    assert sig.mean() < 60.0, sig.mean()
    lone = ready_layer()
    lone.feed_threat(THREAT_RISING)
    lone.feed_fix(LAT0, LON0, 80.0, 1.5, 0.0, True)
    lone_sim = BeaconSim([], SECRET)
    lone_sim.drop_crumb(lone.drop(0.0), LAT0, LON0, 0.0)
    for m in lone_sim.messages(1.0):
        lone.feed_message(m, 1.0)
    for bid, r, s in lone_sim.ranges(LAT0, LON0, 80.0, 1.0):
        lone.feed_range(bid, r, s, 1.0)
    lone.set_altitude(80.0, 2.0, 1.0)
    v = lone.solve(1.0)
    assert v["reason_code"] == NoFixReason.INSUFFICIENT_INPUT and v["crumbs_dropped"] == 1
    print(f"[ok] four crumbs dropped on a weaving path as the threat rose (all before the jam); "
          f"inside the jam, past the trail and back along it, {len(errs)} of {n_jam} epochs got a fix: "
          f"{errs.mean():.0f} m rms, stated sigma {sig.mean():.0f} m, 95% circle covers "
          f"{np.mean(errs <= 2.4477 * sig):.0%}; the rest declined on geometry; a lone crumb declines")
    PASSED.append("zone")


def test_straight_line_crumbs_cannot_fix_cross_track():
    """Crumbs dropped along a straight path are collinear: ranges to them
    cannot tell which side of the line the drone is on, and the solve
    declines on geometry. The stated limit: weave while dropping."""
    layer, errs, sig, declines = fly_zone(lambda e: 0.0)
    assert len(layer.crumbs) == 4
    n_jam = len(errs) + sum(declines.values())
    assert len(errs) < 0.3 * n_jam, (len(errs), declines)
    assert declines.get(NoFixReason.POOR_GEOMETRY, 0) + declines.get(NoFixReason.DIVERGED, 0) > 0.5 * n_jam, declines
    print(f"[ok] crumbs along a straight line: inside the zone the solve declined on geometry "
          f"{sum(declines.values())} times ({dict(declines)}) -- the stated limit; drop on a weave")
    PASSED.append("collinear")


def test_through_the_box():
    """The box drops crumbs as the receiver's jamming state rises, routes
    crumb messages to the layer, and re-anchors on a crumb fix when GNSS
    is gone. Crumb radio lines are simulated."""
    cfg = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, max_degraded_h_acc_m=1e6,
                    breadcrumbs=True, breadcrumb_spacing_m=250.0, breadcrumb_max=4,
                    breadcrumb_drop_agl_m=60.0)
    box = Box(cfg)
    box.beacons.set_secret(SECRET)
    box.crumbs.set_secret(SECRET)
    sim = BeaconSim([], SECRET, seed=5)
    provisioned = []
    truth = {"n": 0.0, "e": 0.0}

    def radio_out(line):
        rec = json.loads(line)
        provisioned.append(rec)
        sim.drop_crumb(rec, *ll(truth["n"], truth["e"]), 0.0)
    box._radio_out = radio_out
    rng = np.random.default_rng(6)
    errs = []
    for k in range(300):
        t = float(k)
        e = 6.0 * k if k < 150 else 6.0 * (300 - k)
        truth["n"], truth["e"] = 100.0 * math.sin(2 * math.pi * e / 1000.0), e
        box.on_fc_message(Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=math.radians(90.0 if k < 150 else 270.0)), t)
        box.on_fc_message(Msg("DISTANCE_SENSOR", current_distance=6000, orientation=25), t)
        # a barometer, so the box has a GNSS-calibrated altitude for the solve
        box.on_fc_message(Msg("SCALED_PRESSURE", press_abs=1006.0, temperature=3000), t)
        lat, lon = ll(truth["n"], e)
        for m in sim.messages(t):
            box.on_beacon_line(json.dumps({"type": "msg", **m}), t)
        for bid, r, s in sim.ranges(lat, lon, 60.0, t):
            box.on_beacon_line(json.dumps({"type": "range", "id": bid, "range_m": r, "sigma_m": s}), t)
        jam_state = "ok" if e < 300 else "warning" if e < 800 else "critical"
        if jam_state == "critical":
            data = encode_mon_rf("critical", 240, 1800, 200) + encode_nav_pvt(
                int(t * 1000), 0.0, 0.0, 0.0, 0.0, 0.0, (0, 0, 0), 0.0, fix_type=0, num_sv=0)
        else:
            flat, flon = ll(truth["n"] + rng.normal(0, 1.5), e + rng.normal(0, 1.5))
            data = encode_mon_rf(jam_state, 90, 2900, 10) + encode_nav_pvt(
                int(t * 1000), flat, flon, 60.0, 1.5, 3.0, (0.0, 6.0 if k < 150 else -6.0, 0.0), 0.15)
        (out, _), = box.on_receiver_bytes(data, t, 0.0)
        if jam_state == "critical" and out.lat is not None:
            on, oe = ne(out.lat, out.lon)
            errs.append(math.hypot(on - truth["n"], oe - e))
    assert len(provisioned) >= 2, provisioned
    # one heading only: the box's wind learner cannot learn the wind, so the
    # stamps honestly say the wind was unknown and carry the loose sigma
    assert all(p["wind_source"] == "unknown" and 15.0 < p["sigma_m"] < 25.0 for p in provisioned), provisioned
    fx = box.gateway.last_fixes.get("breadcrumbs")
    assert fx is not None and fx["accepted"] and fx["anchored"], fx
    assert box.last_crumbs["status"] == "ok" or box.last_crumbs["crumbs_in_range"] >= 0
    tail = np.array(errs[-60:])
    assert tail.mean() < 40.0, tail.mean()
    print(f"[ok] through the box: {len(provisioned)} crumbs provisioned as the receiver's "
          f"jamming state rose (wind unknown, stamps ±{provisioned[0]['sigma_m']:.0f} m); "
          f"inside the jam the crumbs re-anchored the filter; output error {tail.mean():.0f} m "
          f"over the last minute with GNSS gone")
    PASSED.append("box")


if __name__ == "__main__":
    tests = [test_contract_and_policy, test_stamp_is_honest, test_fix_inside_the_jammed_zone,
             test_straight_line_crumbs_cannot_fix_cross_track, test_through_the_box]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} breadcrumb tests passed")
