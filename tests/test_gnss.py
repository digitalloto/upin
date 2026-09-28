"""Tests for L0: GPS and NavIC with jamming, RAIM and spoof checks.

Everything is flown through the simulator's pseudoranges with the true
ranges stripped, as a receiver would see them. Where a test needs an
independent reference -- the thing a spoofed fix is checked against -- it
uses the true position plus noise of a stated sigma, standing in for dead
reckoning or the Arbiter, and says so.

Run: python tests/test_gnss.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.core.no_fabrication import NoFixReason, audit_layer
from upin.detection.jamming_map import JammingMap
from upin.geo.greatcircle import destination, distance_bearing
from upin.layers.satellite.gnss_receiver import Reception, solve
from upin.layers.satellite.layers import GPSLayer, NavICLayer
from upin.simulation.adapters import adapter_for
from upin.simulation.feeds import AgentFeed, WorldFeed
from upin.simulation.harness import Mode, NavigationHarness
from upin.simulation.world import SimulationWorld

PASSED = []
LAT, LON = 13.0827, 80.2707
DEG_M = 111_320.0


def ranges(w, c):
    return [{k: v for k, v in p.items() if k != "true_range_m"}
            for p in w.get_pseudoranges(c)]


def epoch(layer, w, c="GPS"):
    return layer.feed_gnss(ranges(w, c), w.get_gnss_quality(c), w.elapsed)


def advance(w, seconds=1.0):
    for _ in range(int(round(seconds / 0.1))):
        w.step(0.1)


def reference(layer, w, rng, sigma=5.0):
    """Stand-in for dead reckoning: truth plus noise of the stated sigma."""
    lat = w.true_lat + rng.normal(0, sigma) / DEG_M
    lon = w.true_lon + rng.normal(0, sigma) / (DEG_M * math.cos(math.radians(w.true_lat)))
    layer.set_reference(lat, lon, sigma, w.elapsed)


def trusted_receiver(w, layer=None, c="GPS"):
    layer = layer or GPSLayer()
    layer.initialize()
    for _ in range(layer.VALIDATION_EPOCHS):
        epoch(layer, w, c)
        advance(w)
    assert layer.trusted, layer.read().raw_data
    return layer


def err_m(w, reading):
    d, _ = distance_bearing(w.true_lat, w.true_lon,
                            reading.position.latitude, reading.position.longitude)
    return d


# -------------------------------------------------------------- contract

def test_contract_and_bare_read():
    for cls in (GPSLayer, NavICLayer):
        assert audit_layer(cls()).compliant
        r = cls().read()
        assert not r.is_valid and r.raw_data["no_fix_reason"] == NoFixReason.NO_INPUT
        assert "feed_gnss()" in r.raw_data["detail"]
    print("[ok] GPS and NavIC pass the audit; unfed, they name feed_gnss()")
    PASSED.append("contract")


def test_a_new_signal_must_earn_trust():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=1)
    L = GPSLayer(); L.initialize()
    reasons = []
    for _ in range(L.VALIDATION_EPOCHS):
        ep = epoch(L, w)
        reasons.append(ep.valid)
        advance(w)
    assert reasons == [False] * (L.VALIDATION_EPOCHS - 1) + [True], reasons
    print(f"[ok] first {L.VALIDATION_EPOCHS - 1} epochs decline 'validating'; "
          f"trusted on epoch {L.VALIDATION_EPOCHS}")
    PASSED.append("startup")


def test_first_fix_needs_no_starting_guess():
    """The old solver seeded from the world's true position. Bancroft needs none."""
    for lat, lon in ((28.6139, 77.2090), (-33.9, 151.2), (51.5, -0.1)):
        w = SimulationWorld.at_agl(lat, lon, 120.0, seed=2)
        sol, why = solve(ranges(w, "GPS"), "GPS")
        d, _ = distance_bearing(w.true_lat, w.true_lon, sol.lat, sol.lon)
        assert d < 3 * sol.radius95_m, (lat, lon, d)
    print("[ok] cold first fix from Delhi, Sydney and London with no seed at all")
    PASSED.append("no_seed")


def test_stated_accuracy_is_honest():
    ratios = []
    for seed in range(6):
        w = SimulationWorld.at_agl(LAT, LON, 120.0, heading_deg=60.0,
                                   velocity_ms=15.0, seed=seed)
        np.random.seed(seed)
        for c, cls in (("GPS", GPSLayer), ("NavIC", NavICLayer)):
            L = cls(); L.initialize()
            for _ in range(60):
                epoch(L, w, c)
                r = L.read()
                if r.is_valid:
                    ratios.append(err_m(w, r) / r.raw_data["radius95_m"])
                advance(w)
    ratios = np.array(ratios)
    inside, med = float(np.mean(ratios <= 1)), float(np.median(ratios))
    assert inside >= 0.90, inside
    assert med >= 0.10, med
    print(f"[ok] {len(ratios)} GPS+NavIC fixes: truth inside the 95% radius "
          f"{inside:.1%}, median error/radius {med:.2f}")
    PASSED.append("honest")


# --------------------------------------------------------------- jamming

def test_flying_into_a_jammer():
    # 13 km out: at four jammer radii the noise floor is already up 6 dB,
    # so the approach has to start beyond eight radii to begin clear.
    w = SimulationWorld.at_agl(*destination(LAT, LON, 270.0, 13000.0), 120.0,
                               heading_deg=90.0, velocity_ms=80.0, seed=3)
    w.add_jamming_zone(LAT, LON, 1500.0)
    L = trusted_receiver(w)
    seen, first_jam_d, clear_r95, worst_r95 = [], None, None, 0.0
    for _ in range(170):
        ep = epoch(L, w)
        d = w.jamming.zones[0].distance_m(w.true_lat, w.true_lon)
        seen.append(ep.reception)
        if ep.solution is not None:
            if ep.reception == Reception.CLEAR and clear_r95 is None:
                clear_r95 = ep.solution.radius95_m
            worst_r95 = max(worst_r95, ep.solution.radius95_m)
        if ep.reception == Reception.JAMMED and first_jam_d is None:
            first_jam_d = d
            r = L.read()
            assert not r.is_valid and "noise floor" in r.raw_data["detail"]
        advance(w)
    order = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
    assert order[:3] == [Reception.CLEAR, Reception.DEGRADED, Reception.JAMMED], order
    # The zone's radius is where even the strongest satellite is lost; the
    # fix (four satellites) goes earlier, about 1.4 radii out, and that is
    # when the receiver should call it jammed -- not before, not after.
    assert first_jam_d is not None and 1500.0 <= first_jam_d <= 1.6 * 1500.0, first_jam_d
    assert worst_r95 > 2 * clear_r95, (clear_r95, worst_r95)
    print(f"[ok] inbound: clear -> degraded -> jammed at {first_jam_d:.0f} m from "
          f"a 1500 m jammer; stated 95% radius widened {clear_r95:.1f} -> "
          f"{worst_r95:.1f} m before the fix was lost")
    PASSED.append("jam_in")


def test_gps_only_jammer_leaves_navic():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=4)
    g, n = trusted_receiver(w), trusted_receiver(w, NavICLayer(), "NavIC")
    w.add_jamming_zone(LAT, LON, 3000.0, constellations=("GPS",))
    epoch(g, w)
    epoch(n, w, "NavIC")
    assert not g.read().is_valid and n.read().is_valid
    print("[ok] GPS-only jammer: GPS declines, NavIC keeps its fix")
    PASSED.append("navic")


def test_navic_outside_its_service_area():
    w = SimulationWorld.at_agl(51.5, -0.1, 120.0, seed=5)
    L = NavICLayer(); L.initialize()
    epoch(L, w, "NavIC")
    r = L.read()
    assert not r.is_valid and r.raw_data["no_fix_reason"] == NoFixReason.INSUFFICIENT_INPUT
    print(f"[ok] NavIC from London: {r.raw_data['detail']}")
    PASSED.append("navic_region")


# ------------------------------------------------------------------ RAIM

def test_raim_excludes_one_bad_satellite():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=6)
    L = trusted_receiver(w)
    pr = ranges(w, "GPS")
    pr[3]["pseudorange_m"] += 300.0
    L.feed_gnss(pr, w.get_gnss_quality("GPS"), w.elapsed)
    r = L.read()
    assert r.is_valid and r.raw_data["excluded_satellites"] == [pr[3]["sat_id"]]
    assert err_m(w, r) < r.raw_data["radius95_m"]
    pr[5]["pseudorange_m"] -= 400.0
    L.feed_gnss(pr, w.get_gnss_quality("GPS"), w.elapsed + 1)
    r2 = L.read()
    assert not r2.is_valid and "RAIM" in r2.raw_data["detail"]
    print(f"[ok] one 300 m fault: {pr[3]['sat_id']} excluded, fix intact; "
          f"two faults: {r2.raw_data['detail'][:48]}...")
    PASSED.append("raim")


# ------------------------------------------------------------- spoofing

def test_a_spoof_jump_is_rejected():
    rng = np.random.default_rng(7)
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=7)
    L = trusted_receiver(w)
    reference(L, w, rng)
    w.set_gps_spoofing(500.0 / DEG_M, 0.0)
    epoch(L, w)
    r = L.read()
    assert not r.is_valid and r.position is None
    assert r.raw_data["no_fix_reason"] == NoFixReason.FAILED_VALIDATION
    assert "spoof" in r.raw_data["detail"]
    assert "rejected_position" in r.raw_data
    print(f"[ok] 500 m spoof: rejected -- {r.raw_data['detail'][:70]}...")
    PASSED.append("jump")


def test_a_drag_off_spoof_is_caught_and_the_rate_reported():
    """A spoofer that walks the fix away at 1 m/s. The gate catches it once
    the lie exceeds the combined uncertainty -- this reports when."""
    rng = np.random.default_rng(8)
    w = SimulationWorld.at_agl(LAT, LON, 120.0, heading_deg=30.0,
                               velocity_ms=10.0, seed=8)
    L = trusted_receiver(w)
    t0, caught = w.elapsed, None
    for k in range(120):
        offset = 1.0 * k
        w.set_gps_spoofing(offset / DEG_M, 0.0)
        reference(L, w, rng, sigma=5.0)
        ep = epoch(L, w)
        if not ep.valid and ep.reason == NoFixReason.FAILED_VALIDATION:
            caught = (k, offset)
            break
        advance(w)
    assert caught is not None, "a 1 m/s drag-off was never detected"
    assert caught[1] < 40.0, caught
    print(f"[ok] 1 m/s drag-off against a 5 m reference: caught after "
          f"{caught[0]} s, at {caught[1]:.0f} m of offset")
    PASSED.append("dragoff")


def test_returning_through_a_spoofer_is_refused_until_it_agrees():
    rng = np.random.default_rng(9)
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=9)
    L = trusted_receiver(w)
    w.add_jamming_zone(LAT, LON, 3000.0)
    for _ in range(4):
        epoch(L, w)
        advance(w)
    assert not L.trusted
    w.jamming.clear()
    w.set_gps_spoofing(300.0 / DEG_M, 300.0 / DEG_M)
    for _ in range(8):
        reference(L, w, rng)
        ep = epoch(L, w)
        assert not ep.valid, "believed a spoofed return"
        advance(w)
    w.clear_gps_spoofing()
    valid_at = None
    for k in range(10):
        reference(L, w, rng)
        if epoch(L, w).valid:
            valid_at = k + 1
            break
        advance(w)
    assert valid_at == L.VALIDATION_EPOCHS, valid_at
    print(f"[ok] after an outage, 8 spoofed epochs refused; honest signal "
          f"trusted again after {valid_at} agreeing epochs")
    PASSED.append("return")


def test_a_return_with_nothing_to_check_it_against_is_refused():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=10)
    L = trusted_receiver(w)
    w.add_jamming_zone(LAT, LON, 3000.0)
    for _ in range(4):
        epoch(L, w)
        advance(w)
    w.jamming.clear()
    for _ in range(10):
        epoch(L, w)
        advance(w)
    r = L.read()
    assert not r.is_valid and "no independent reference" in r.raw_data["detail"]
    print(f"[ok] return with no reference: {r.raw_data['detail']}")
    PASSED.append("no_ref")


# --------------------------------------------------------- jamming map

def test_the_jamming_map_points_away_from_the_jammer():
    """Two legs at right angles give 2-D coverage; one straight leg does not."""
    rng = np.random.default_rng(11)
    jam = (LAT, LON)
    start = destination(LAT, LON, 180.0, 3500.0)
    w = SimulationWorld.at_agl(*start, 120.0, heading_deg=90.0,
                               velocity_ms=30.0, seed=11)
    w.add_jamming_zone(*jam, 1500.0)
    L = GPSLayer(); L.initialize()
    L.jamming_map = JammingMap(cell_m=100.0)

    def leg(seconds):
        for _ in range(seconds):
            reference(L, w, rng, sigma=20.0)
            epoch(L, w)
            advance(w)

    leg(60)                                    # eastbound, south of the jammer
    line_only = L.jamming_map.gradient(w.true_lat, w.true_lon, radius_m=2500.0)
    w.true_heading, w.true_vn, w.true_ve = 0.0, 30.0, 0.0   # turn north
    leg(50)
    probe = (w.true_lat, w.true_lon)
    g = L.jamming_map.gradient(*probe, radius_m=2500.0)
    assert line_only is None, "claimed a 2-D gradient from one straight line"
    assert g is not None
    _, outward = distance_bearing(*jam, *probe)
    diff = abs((g.toward_clear_deg - outward + 180.0) % 360.0 - 180.0)
    assert diff < 35.0, (g.toward_clear_deg, outward)
    print(f"[ok] one straight leg: no gradient claimed; after an L-shaped "
          f"survey ({len(L.jamming_map)} cells) clear air lies toward "
          f"{g.toward_clear_deg:.0f} deg, jammer-outward is {outward:.0f}")
    PASSED.append("map")


# ------------------------------------------------------------- harness

def test_harness_feeds_it_and_real_mode_does_not():
    seen = []

    class Spy(GPSLayer):
        def feed_gnss(self, pr, quality=None, t=None):
            seen.extend(k for p in pr for k in p)
            return super().feed_gnss(pr, quality, t)

    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=12)
    spy = Spy()
    spy.initialize()
    assert adapter_for("gps_l1") is not None
    adapter_for("gps_l1").drive(spy, WorldFeed(w), 0.1, np.random.default_rng(0))
    assert seen and "true_range_m" not in seen, set(seen)
    h = NavigationHarness([GPSLayer()], Mode.REAL, world=w, agent_feed=AgentFeed(agents=[]))
    h.tick(0.1)
    r = h.layer("gps_l1").read()
    assert not r.is_valid
    print("[ok] adapter strips true ranges; real mode with no receiver declines")
    PASSED.append("harness")


if __name__ == "__main__":
    tests = [
        test_contract_and_bare_read,
        test_a_new_signal_must_earn_trust,
        test_first_fix_needs_no_starting_guess,
        test_stated_accuracy_is_honest,
        test_flying_into_a_jammer,
        test_gps_only_jammer_leaves_navic,
        test_navic_outside_its_service_area,
        test_raim_excludes_one_bad_satellite,
        test_a_spoof_jump_is_rejected,
        test_a_drag_off_spoof_is_caught_and_the_rate_reported,
        test_returning_through_a_spoofer_is_refused_until_it_agrees,
        test_a_return_with_nothing_to_check_it_against_is_refused,
        test_the_jamming_map_points_away_from_the_jammer,
        test_harness_feeds_it_and_real_mode_does_not,
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
    print(f"\n{len(PASSED)}/{len(tests)} gnss tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all gnss tests passed")
