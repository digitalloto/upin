"""Tests for layer 151, known-position beacon ranging, with balloons.

SIMULATED beacons and balloons (upin/simulation/beacons.py). Tests the
message checks, the solve and the stated limits, not any radio.

Run: python tests/test_beacon_ranging.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.core.no_fabrication import NoFixReason, audit_layer  # noqa: E402
from upin.layers.rf.beacon_ranging import DEG_M, BeaconRangingLayer  # noqa: E402
from upin.simulation.beacons import BeaconSim, SimBeacon  # noqa: E402
from upin.simulation.environment import JammingField, JammingZone  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
SECRET = b"test-range-secret-2026"


def ll(n, e):
    return LAT0 + n / DEG_M, LON0 + e / (DEG_M * math.cos(math.radians(LAT0)))


def ne(lat, lon):
    return (lat - LAT0) * DEG_M, (lon - LON0) * DEG_M * math.cos(math.radians(LAT0))


def ground_field(sigma=2.0):
    return [SimBeacon("g1", *ll(1500, -1500), 30.0, sigma),
            SimBeacon("g2", *ll(1500, 1500), 45.0, sigma),
            SimBeacon("g3", *ll(-1500, 0), 20.0, sigma),
            SimBeacon("mast", *ll(-900, 1800), 120.0, sigma)]


def balloon_field():
    return [SimBeacon(f"b{i}", *ll(n, e), 50.0, 5.0, kind="balloon", launch_t=-1800.0 - 300 * i,
                      wind_ne_ms=(1.5, 4.0))
            for i, (n, e) in enumerate(((-20000, -15000), (-20000, 15000), (20000, 0), (0, -25000)))]


def epoch(layer, sim, lat, lon, alt, t, jam=None, tamper=None, use_alt=True):
    for m in sim.messages(t, tamper):
        layer.feed_message(m, t)
    for bid, r, s in sim.ranges(lat, lon, alt, t, jam):
        layer.feed_range(bid, r, s, t)
    if use_alt:
        layer.set_altitude(alt, 2.0, t)
    return layer.solve(t)


def test_contract_and_message_checks():
    layer = BeaconRangingLayer()
    assert audit_layer(layer).compliant
    assert layer.solve(0.0)["reason_code"] == NoFixReason.NO_CALIBRATION
    layer.set_secret(SECRET)
    sim = BeaconSim(ground_field(), SECRET, seed=1)
    for tamper, why in (("unsigned", "bad signature"), ("wrong_channel", "off the hop schedule")):
        for m in sim.messages(10.0, tamper):
            assert layer.feed_message(m, 10.0) == why
    good = sim.messages(11.0)
    assert all(layer.feed_message(m, 11.0) == "accepted" for m in good)
    assert layer.feed_message(good[0], 11.0) == "replayed (sequence not newer)"
    old = sim.messages(12.0)
    assert layer.feed_message(old[0], 30.0).endswith("s old")
    wrong_key = BeaconRangingLayer()
    wrong_key.set_secret(b"someone else's key")
    assert wrong_key.feed_message(sim.messages(13.0)[0], 13.0) == "bad signature"
    assert layer.rejected["bad signature"] == 4 and layer.rejected["off the hop schedule"] == 4
    print(f"[ok] contract; unsigned, off-schedule, replayed, stale and wrong-key messages "
          f"are refused and counted: {layer.rejected}")
    PASSED.append("messages")


def test_ground_beacons_fix():
    layer = BeaconRangingLayer()
    layer.set_secret(SECRET)
    sim = BeaconSim(ground_field(), SECRET, seed=2)
    errs, sig = [], []
    for k in range(60):
        n, e = 100.0 + 6.0 * k, -50.0
        v = epoch(layer, sim, *ll(n, e), 80.0, float(k))
        assert v["status"] == "ok", v
        en, ee = ne(v["lat"], v["lon"])
        errs.append((en - n, ee - e))
        sig.append((v["sigma_n_m"], v["sigma_e_m"]))
    errs, sig = np.array(errs), np.array(sig)
    rms = float(np.sqrt((errs ** 2).sum(1).mean()))
    cover = float(np.mean(np.abs(errs) <= 1.96 * sig))
    assert rms < 3 * sig.mean(), (rms, sig.mean())
    assert 0.85 <= cover <= 1.0, cover
    print(f"[ok] four ground beacons, 10 m ranging: fix error {rms:.1f} m rms, stated "
          f"sigma {sig.mean():.1f} m, 95% interval covers {cover:.0%}, HDOP {v['hdop']:.1f}")
    PASSED.append("ground")


def test_balloons_fix_and_gnss_jammer_ignored():
    layer = BeaconRangingLayer()
    layer.set_secret(SECRET)
    sim = BeaconSim(balloon_field(), SECRET, seed=3)
    gnss_jammer = JammingField([JammingZone(LAT0, LON0, 3000.0, ("GPS", "NavIC", "LEO"))])
    errs, sig, hdops, alts = [], [], [], []
    for k in range(300):
        n, e = 8.0 * k * math.cos(0.01 * k), 8.0 * k * math.sin(0.01 * k)
        v = epoch(layer, sim, *ll(n, e), 100.0, float(k), jam=gnss_jammer)
        assert v["status"] == "ok", (k, v)
        en, ee = ne(v["lat"], v["lon"])
        errs.append((en - n, ee - e))
        sig.append((v["sigma_n_m"], v["sigma_e_m"]))
        hdops.append(v["hdop"])
    errs, sig = np.array(errs), np.array(sig)
    rms = float(np.sqrt((errs ** 2).sum(1).mean()))
    cover = float(np.mean(np.abs(errs) <= 1.96 * sig))
    assert rms < 3 * sig.mean() and cover >= 0.85, (rms, sig.mean(), cover)
    assert gnss_jammer.inside_denial(LAT0, LON0, "GPS")
    p = sim.beacons[0].position(299.0)
    print(f"[ok] four balloons at {p[2] / 1000:.0f}-{sim.beacons[3].position(299.0)[2] / 1000:.0f} km, "
          f"drifting, inside a 3 km GNSS jammer: fix {rms:.0f} m rms, stated sigma "
          f"{sig.mean():.0f} m, coverage {cover:.0%}, HDOP {np.mean(hdops):.1f}")
    PASSED.append("balloons")


def test_beacon_band_jammer_and_too_few():
    layer = BeaconRangingLayer()
    layer.set_secret(SECRET)
    sim = BeaconSim(ground_field(), SECRET, seed=4)
    wideband = JammingField([JammingZone(LAT0, LON0, 3000.0, ("GPS", "NavIC", "LEO", "BEACON"))])
    assert epoch(layer, sim, LAT0, LON0, 80.0, 1.0)["status"] == "ok"
    v = epoch(layer, sim, LAT0, LON0, 80.0, 5.0, jam=wideband)
    assert v["status"] == "declined" and "fresh message and range" in v["reason"], v
    two = BeaconRangingLayer()
    two.set_secret(SECRET)
    v = epoch(two, BeaconSim(ground_field()[:2], SECRET), LAT0, LON0, 80.0, 1.0)
    assert v["reason_code"] == NoFixReason.INSUFFICIENT_INPUT and "needs 3" in v["reason"]
    three = BeaconRangingLayer()
    three.set_secret(SECRET)
    v = epoch(three, BeaconSim(ground_field()[:3], SECRET), LAT0, LON0, 80.0, 1.0, use_alt=False)
    assert "needs 4" in v["reason"] and "no altitude" in v["reason"]
    print("[ok] a beacon-band (wideband) jammer silences the beacons and the layer declines; "
          "two beacons decline; three without altitude decline")
    PASSED.append("jam")


def test_bad_beacon_position_widens_the_fix():
    """A beacon's own position sigma propagates. One bad beacon among good
    ones is down-weighted (the fix barely changes); when every beacon is
    uncertain the fix cannot be better than they are, and the sigma says so."""
    def fix_sigma(sigmas):
        layer = BeaconRangingLayer()
        layer.set_secret(SECRET)
        field = ground_field()
        for b, sg in zip(field, sigmas):
            b.sigma_m = sg
        v = epoch(layer, BeaconSim(field, SECRET, seed=5), *ll(200, 100), 80.0, 1.0)
        assert v["status"] == "ok", v
        return v["sigma_m"]
    good = fix_sigma([2.0, 2.0, 2.0, 2.0])
    one_bad = fix_sigma([500.0, 2.0, 2.0, 2.0])
    all_bad = fix_sigma([50.0, 50.0, 50.0, 50.0])
    assert one_bad >= good, (one_bad, good)
    assert all_bad > 3 * good, (all_bad, good)
    print(f"[ok] beacon position sigma propagates: good beacons {good:.1f} m; one knowing "
          f"itself to 500 m is down-weighted ({one_bad:.1f} m); all at 50 m give "
          f"{all_bad:.0f} m -- a fix is never better than the beacons know themselves")
    PASSED.append("widen")


def test_bunched_geometry_declines():
    layer = BeaconRangingLayer()
    layer.set_secret(SECRET)
    # four high beacons (balloons that drifted together) 30 m apart, 20 km up
    # and 20 km away: in view, but all in the same direction
    bunched = [SimBeacon(f"c{i}", *ll(15000 + 30 * i, 15000 + 20 * i), 20000.0, 5.0)
               for i in range(4)]
    v = epoch(layer, BeaconSim(bunched, SECRET), LAT0, LON0, 80.0, 1.0)
    assert v["reason_code"] == NoFixReason.POOR_GEOMETRY, v
    print(f"[ok] four beacons bunched together 20 km away: {v['reason']}")
    PASSED.append("geometry")


if __name__ == "__main__":
    tests = [test_contract_and_message_checks, test_ground_beacons_fix,
             test_balloons_fix_and_gnss_jammer_ignored, test_beacon_band_jammer_and_too_few,
             test_bad_beacon_position_widens_the_fix, test_bunched_geometry_declines]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} beacon-ranging tests passed")
