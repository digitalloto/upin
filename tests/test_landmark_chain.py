"""Tests for landmark chain navigation (Layer 4).
Run: python tests/test_landmark_chain.py
"""
import math
import sys
import time

sys.path.insert(0, ".")

import numpy as np

from upin.core.no_fabrication import NoFixReason, audit_layer
from upin.layers.inertial.command_dr import (
    AirframeModel, CommandDeadReckoningLayer,
)
from upin.layers.optical.landmark_chain import (
    ALLOWED_MAP_SOURCES, BearingObservation, Breadcrumb, ForeignMapSourceError,
    Landmark, LandmarkChain, LandmarkChainLayer, LandmarkMap, MapSource,
    cut_angle_deg, reset_dead_reckoning, resect, validate_map_source,
)
from upin.layers.registry import ALL_LAYER_CLASSES

PASSED = []

DEG_M = 111_320.0
LAT0, LON0 = 13.0827, 80.2707      # Chennai, the reference used across UPIN


def place(dn, de, lat=LAT0, lon=LON0):
    """Offset a coordinate by metres north and east."""
    return (lat + dn / DEG_M,
            lon + de / (DEG_M * math.cos(math.radians(lat))))


def standard_map():
    """Three charted landmarks around the origin, all Indian sources."""
    a_lat, a_lon = place(800, 0)
    b_lat, b_lon = place(-200, 900)
    c_lat, c_lon = place(-600, -700)
    return LandmarkMap([
        Landmark("tower_a", a_lat, a_lon, MapSource.SURVEY_OF_INDIA, 2.0,
                 name="Water tower", altitude_m=12.0, feature_type="tank"),
        Landmark("bridge_b", b_lat, b_lon, MapSource.BHUVAN, 3.0,
                 name="Rail bridge", altitude_m=10.0, feature_type="bridge"),
        Landmark("tank_c", c_lat, c_lon, MapSource.CARTOSAT, 2.5,
                 name="Storage tank", altitude_m=11.0, feature_type="tank"),
    ])


def bearings_from(lat, lon, lmap, sigma_deg=0.5, now=None, noise=None,
                  ids=None):
    """True bearings from a position to charted landmarks.

    Noise, when asked for, is injected here in the harness and never inside
    the layer — that is the contract, and it is why two reads of the same
    observations must agree bit for bit.
    """
    now = time.time() if now is None else now
    out = []
    for i, lm_id in enumerate(sorted(ids if ids is not None else
                                     ["tower_a", "bridge_b", "tank_c"])):
        lm = lmap.get(lm_id)
        dn = (lm.latitude - lat) * DEG_M
        de = (lm.longitude - lon) * DEG_M * math.cos(math.radians(lat))
        b = math.degrees(math.atan2(de, dn)) % 360.0
        if noise is not None:
            b += float(noise[i])
        out.append(BearingObservation(lm_id, b, sigma_deg, now))
    return out


def error_m(lat_a, lon_a, lat_b, lon_b):
    return math.hypot((lat_a - lat_b) * DEG_M,
                      (lon_a - lon_b) * DEG_M * math.cos(math.radians(lat_a)))


# ------------------------------------------------------------ provenance

def test_foreign_map_sources_are_refused():
    """A Google-derived landmark must not enter the solve at all."""
    for bad in ("google_maps", "Google", "mapbox", "here_maps", "bing"):
        try:
            Landmark("x", LAT0, LON0, bad, 1.0)
        except ForeignMapSourceError:
            continue
        raise AssertionError(f"{bad!r} was accepted as a map source")
    for empty in ("", "   "):
        try:
            Landmark("x", LAT0, LON0, empty, 1.0)
        except ForeignMapSourceError:
            continue
        raise AssertionError("a landmark with no stated provenance was accepted")
    print(f"[ok] provenance: 5 foreign sources and 2 blanks refused; "
          f"allowed set is {sorted(ALLOWED_MAP_SOURCES)}")
    PASSED.append("foreign")


def test_indian_sources_are_accepted_and_normalised():
    for src in ALLOWED_MAP_SOURCES:
        assert validate_map_source(src.upper()) == src
    lm = Landmark("t", LAT0, LON0, "  Survey_Of_India ", 2.0)
    assert lm.source == MapSource.SURVEY_OF_INDIA
    print(f"[ok] all {len(ALLOWED_MAP_SOURCES)} Indian sources accepted, "
          f"case and whitespace normalised")
    PASSED.append("indian")


def test_landmark_must_state_its_survey_accuracy():
    """A fix cannot be better than the chart, so the chart error is required."""
    for bad in (0.0, -1.0):
        try:
            Landmark("x", LAT0, LON0, MapSource.BHUVAN, bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted survey accuracy {bad}")
    print("[ok] a landmark without a stated survey accuracy is refused")
    PASSED.append("survey_acc")


# -------------------------------------------------------------- geometry

def test_cut_angle_folds_to_the_useful_range():
    """A 170 degree cut is as good as 10 degrees is bad."""
    assert abs(cut_angle_deg([0.0, 90.0]) - 90.0) < 1e-9
    assert abs(cut_angle_deg([0.0, 170.0]) - 10.0) < 1e-9
    assert abs(cut_angle_deg([10.0, 20.0]) - 10.0) < 1e-9
    assert abs(cut_angle_deg([0.0, 5.0, 88.0]) - 88.0) < 1e-9
    print("[ok] cut angle: 170 deg folds to 10 deg, best pair wins")
    PASSED.append("cut")


def test_resection_recovers_a_known_position():
    """Exact bearings to three charted points must return the exact position."""
    lmap = standard_map()
    true_lat, true_lon = place(120.0, -60.0)
    r = resect(bearings_from(true_lat, true_lon, lmap), lmap)
    assert r.converged, r.reason
    err = error_m(r.latitude, r.longitude, true_lat, true_lon)
    assert err < 0.05, f"recovered position off by {err:.3f} m"
    assert r.residual_rms_deg < 1e-3, r.residual_rms_deg
    print(f"[ok] resection: exact bearings recover position to {err*1000:.2f} mm "
          f"in {r.iterations} iteration(s)")
    PASSED.append("resect")


def test_reported_accuracy_matches_observed_scatter():
    """The covariance must describe the real error, not flatter it.

    Noise goes in at the harness. If the reported accuracy were a label
    rather than a measurement, the scatter of 200 noisy solves would not
    track it.
    """
    lmap = standard_map()
    true_lat, true_lon = place(120.0, -60.0)
    sigma = 0.5
    rng = np.random.default_rng(11)
    errors = []
    reported = None
    for _ in range(200):
        obs = bearings_from(true_lat, true_lon, lmap, sigma_deg=sigma,
                            noise=rng.normal(0, sigma, 3))
        r = resect(obs, lmap)
        assert r.converged
        errors.append(error_m(r.latitude, r.longitude, true_lat, true_lon))
        reported = r.accuracy_m
    observed = float(np.sqrt(np.mean(np.square(errors))))
    ratio = observed / reported
    assert 0.5 < ratio < 1.5, (
        f"observed scatter {observed:.2f} m vs reported {reported:.2f} m")
    print(f"[ok] honesty: reported {reported:.2f} m, observed RMS "
          f"{observed:.2f} m (ratio {ratio:.2f})")
    PASSED.append("honest_acc")


def test_accuracy_degrades_with_worse_bearings():
    """Four times the bearing error must give roughly four times the fix error."""
    lmap = standard_map()
    true_lat, true_lon = place(120.0, -60.0)
    fine = resect(bearings_from(true_lat, true_lon, lmap, sigma_deg=0.25), lmap)
    coarse = resect(bearings_from(true_lat, true_lon, lmap, sigma_deg=1.0), lmap)
    ratio = coarse.accuracy_m / fine.accuracy_m
    assert 3.0 < ratio < 4.5, f"ratio {ratio:.2f} should track the sigma ratio"
    print(f"[ok] 0.25 deg -> {fine.accuracy_m:.2f} m, 1.0 deg -> "
          f"{coarse.accuracy_m:.2f} m (x{ratio:.2f})")
    PASSED.append("sigma_scale")


def test_coarse_chart_widens_the_fix():
    """A landmark surveyed to 50 m cannot produce a 2 m fix."""
    lmap = standard_map()
    coarse = standard_map()
    for lm_id in ("tower_a", "bridge_b", "tank_c"):
        lm = coarse.get(lm_id)
        coarse.add(Landmark(lm_id, lm.latitude, lm.longitude, lm.source, 50.0,
                            altitude_m=lm.altitude_m))
    true_lat, true_lon = place(120.0, -60.0)
    obs = bearings_from(true_lat, true_lon, lmap, sigma_deg=0.1)
    good = resect(obs, lmap)
    bad = resect(obs, coarse)
    assert bad.accuracy_m > good.accuracy_m * 2, (
        f"{bad.accuracy_m:.2f} vs {good.accuracy_m:.2f}")
    print(f"[ok] chart error propagates: 2 m survey -> {good.accuracy_m:.2f} m, "
          f"50 m survey -> {bad.accuracy_m:.2f} m")
    PASSED.append("chart_err")


def test_bearing_plus_range_fixes_from_one_landmark():
    """One landmark is enough when you know both direction and distance."""
    lmap = standard_map()
    true_lat, true_lon = place(120.0, -60.0)
    obs = bearings_from(true_lat, true_lon, lmap, ids=["tower_a"])[0]
    lm = lmap.get("tower_a")
    obs.range_m = error_m(true_lat, true_lon, lm.latitude, lm.longitude)
    obs.range_sigma_m = 5.0
    r = resect([obs], lmap)
    assert r.converged, r.reason
    err = error_m(r.latitude, r.longitude, true_lat, true_lon)
    assert err < 0.5, f"off by {err:.3f} m"
    print(f"[ok] one bearing + one range fixes to {err:.3f} m "
          f"(acc {r.accuracy_m:.2f} m)")
    PASSED.append("range")


def test_single_bearing_is_not_a_fix():
    lmap = standard_map()
    true_lat, true_lon = place(120.0, -60.0)
    r = resect(bearings_from(true_lat, true_lon, lmap, ids=["tower_a"]), lmap)
    assert not r.converged
    assert r.reason == NoFixReason.INSUFFICIENT_INPUT
    print("[ok] one bearing alone returns no position, not a guess")
    PASSED.append("single")


# -------------------------------------------------- the layer's refusals

def test_declines_without_a_map():
    layer = LandmarkChainLayer()
    layer.initialize()
    r = layer.read()
    assert not r.is_valid and r.position is None
    assert r.raw_data["no_fix_reason"] == NoFixReason.NO_INPUT
    assert r.raw_data["allowed_map_sources"] == sorted(ALLOWED_MAP_SOURCES)
    print("[ok] no map -> no position, and the reading names the allowed sources")
    PASSED.append("no_map")


def test_declines_without_observations():
    layer = LandmarkChainLayer(standard_map())
    layer.initialize()
    r = layer.read()
    assert not r.is_valid and r.position is None
    assert r.raw_data["no_fix_reason"] == NoFixReason.NO_INPUT
    assert r.raw_data["landmarks_charted"] == 3
    print("[ok] map but no bearings -> no position, reason stated")
    PASSED.append("no_obs")


def test_declines_on_stale_observations():
    """A bearing is a statement about where you were when you took it."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    now = 1_000_000.0
    true_lat, true_lon = place(120.0, -60.0)
    layer.observe_many(bearings_from(true_lat, true_lon, lmap, now=now))
    fresh = layer.read(now=now)
    assert fresh.is_valid
    stale = layer.read(now=now + layer.MAX_OBSERVATION_AGE_S + 1.0)
    assert not stale.is_valid and stale.position is None
    assert stale.raw_data["no_fix_reason"] == NoFixReason.STALE_INPUT
    assert stale.raw_data["stale_dropped"] == 3
    print(f"[ok] bearings older than {layer.MAX_OBSERVATION_AGE_S} s are dropped, "
          f"3 stale -> no fix")
    PASSED.append("stale")


def test_declines_on_a_narrow_cut():
    """Two nearly parallel lines of position do not cross anywhere useful."""
    lmap = LandmarkMap([
        Landmark("far_a", *place(20_000, 0), source=MapSource.BHUVAN,
                 position_accuracy_m=2.0),
        Landmark("far_b", *place(20_000, 400), source=MapSource.BHUVAN,
                 position_accuracy_m=2.0),
    ])
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    layer.observe_many(bearings_from(LAT0, LON0, lmap,
                                     ids=["far_a", "far_b"]))
    r = layer.read()
    assert not r.is_valid and r.position is None
    assert r.raw_data["no_fix_reason"] == NoFixReason.POOR_GEOMETRY
    assert r.raw_data["cut_angle_deg"] < layer.MIN_CUT_ANGLE_DEG
    print(f"[ok] {r.raw_data['cut_angle_deg']:.2f} deg cut refused "
          f"(floor {layer.MIN_CUT_ANGLE_DEG} deg)")
    PASSED.append("narrow")


def test_unknown_landmarks_are_ignored_not_invented():
    """A detection matched to nothing on the chart contributes nothing."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    layer.observe(BearingObservation("not_on_the_chart", 42.0, 0.5, time.time()))
    r = layer.read()
    assert not r.is_valid
    assert r.raw_data["no_fix_reason"] == NoFixReason.INSUFFICIENT_INPUT
    assert r.raw_data["observations_usable"] == 0
    assert r.raw_data["observations_supplied"] == 1
    print("[ok] an uncharted detection is counted as unusable, not used")
    PASSED.append("unknown")


# ------------------------------------------------------------- the fix

def test_produces_a_fix_and_reports_its_geometry():
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    true_lat, true_lon = place(120.0, -60.0)
    layer.observe_many(bearings_from(true_lat, true_lon, lmap))
    r = layer.read()
    assert r.is_valid and r.position is not None
    err = error_m(r.position.latitude, r.position.longitude, true_lat, true_lon)
    assert err < 0.05, f"off by {err:.3f} m"
    assert r.raw_data["rf_independent"] is True
    assert r.raw_data["can_reset_dead_reckoning"] is True
    assert set(r.raw_data["map_sources"]) <= ALLOWED_MAP_SOURCES
    assert r.position.altitude is not None    # charted base elevations exist
    assert 0.0 < r.self_confidence < 1.0
    print(f"[ok] fix: {err*1000:.2f} mm error, {r.position.accuracy_m:.2f} m "
          f"accuracy, {r.raw_data['cut_angle_deg']:.1f} deg cut, "
          f"conf {r.self_confidence:.2f}")
    PASSED.append("fix")


def test_altitude_is_none_when_the_chart_has_none():
    """Bearings fix a horizontal position and say nothing about height."""
    lmap = LandmarkMap([
        Landmark("a", *place(800, 0), source=MapSource.BHUVAN,
                 position_accuracy_m=2.0),
        Landmark("b", *place(-200, 900), source=MapSource.BHUVAN,
                 position_accuracy_m=2.0),
    ])
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    layer.observe_many(bearings_from(LAT0, LON0, lmap, ids=["a", "b"]))
    r = layer.read()
    assert r.is_valid
    assert r.position.altitude is None, "altitude invented from nothing"
    print("[ok] no charted elevation -> altitude is None, not a filler value")
    PASSED.append("alt_none")


def test_confidence_tracks_geometry():
    """A wide cut with tight bearings must beat a narrow cut with loose ones."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    true_lat, true_lon = place(120.0, -60.0)
    layer.observe_many(bearings_from(true_lat, true_lon, lmap, sigma_deg=0.1))
    good = layer.read().self_confidence

    layer2 = LandmarkChainLayer(standard_map())
    layer2.initialize()
    layer2.observe_many(bearings_from(true_lat, true_lon, lmap, sigma_deg=2.0))
    loose = layer2.read().self_confidence

    assert good > loose, f"{good:.3f} should beat {loose:.3f}"
    print(f"[ok] confidence: tight bearings {good:.3f} > loose {loose:.3f}")
    PASSED.append("conf")


def test_layer_is_deterministic():
    """Same observations, same answer, bit for bit."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    now = 1_000_000.0
    true_lat, true_lon = place(120.0, -60.0)
    layer.observe_many(bearings_from(true_lat, true_lon, lmap, now=now))
    a = layer.read(now=now)
    b = layer.read(now=now)
    assert a.position.latitude == b.position.latitude
    assert a.position.longitude == b.position.longitude
    assert a.position.accuracy_m == b.position.accuracy_m
    assert a.self_confidence == b.self_confidence
    assert len(layer.chain) == 1, "the same bearings recorded two crumbs"
    print("[ok] two reads on identical bearings are bit-identical, "
          "chain grew once")
    PASSED.append("determinism")


def test_passes_the_contract_audit():
    result = audit_layer(LandmarkChainLayer())
    assert result.compliant, result.detail
    assert result.declares_contract and result.declines_without_input
    assert result.states_reason and result.deterministic
    print(f"[ok] contract audit: {result.detail}")
    PASSED.append("audit")


# ---------------------------------------------------------- the chain

def test_chain_records_only_spaced_out_fixes():
    """Sitting still must not fill the trail with the same place."""
    chain = LandmarkChain(min_spacing_m=25.0)
    base = Breadcrumb(LAT0, LON0, 10.0, 5.0, 0.0, ("a", "b"), 60.0)
    assert chain.record(base) is True
    near_lat, near_lon = place(5.0, 0.0)
    assert chain.record(Breadcrumb(near_lat, near_lon, 10.0, 5.0, 1.0,
                                   ("a", "b"), 60.0)) is False
    far_lat, far_lon = place(100.0, 0.0)
    assert chain.record(Breadcrumb(far_lat, far_lon, 10.0, 5.0, 2.0,
                                   ("a", "b"), 60.0)) is True
    assert len(chain) == 2
    assert abs(chain.length_m - 100.0) < 1.0
    print(f"[ok] chain: 5 m apart rejected, 100 m apart kept, "
          f"trail {chain.length_m:.1f} m")
    PASSED.append("chain_spacing")


def test_return_leg_walks_the_trail_backwards():
    """Home is back through places the aircraft demonstrably was."""
    chain = LandmarkChain(min_spacing_m=10.0)
    for i in range(4):
        lat, lon = place(i * 100.0, 0.0)
        chain.record(Breadcrumb(lat, lon, 10.0, 5.0, float(i), ("a", "b"), 60.0))
    # Standing at the far end, the first leg goes to the last crumb behind us.
    here_lat, here_lon = place(400.0, 0.0)
    leg = chain.next_leg(here_lat, here_lon)
    assert leg is not None
    assert abs(leg.distance_m - 100.0) < 1.0, leg.distance_m
    assert abs(leg.bearing_deg - 180.0) < 1.0, leg.bearing_deg
    assert leg.remaining_crumbs == 4
    # Having arrived there, the cursor steps back to the one before it.
    leg2 = chain.next_leg(*place(300.0, 0.0))
    assert abs(leg2.distance_m - 100.0) < 1.0
    assert leg2.remaining_crumbs == 3
    # Fly each remaining crumb in turn. The trail is walked, not jumped —
    # arriving at the start does not let the cursor skip what lies between.
    for north in (200.0, 100.0):
        leg_n = chain.next_leg(*place(north, 0.0))
        assert leg_n is not None
        assert abs(leg_n.distance_m - 100.0) < 1.0
    # Standing on the first crumb, there is nothing left to fly to.
    assert chain.next_leg(*place(0.0, 0.0)) is None
    print("[ok] return leg: 100 m due south per hop, cursor steps 4 -> 3 -> "
          "... -> done at the start")
    PASSED.append("return_leg")


def test_return_leg_declines_with_an_empty_trail():
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap, min_spacing_m=1e9)  # never records
    layer.initialize()
    true_lat, true_lon = place(120.0, -60.0)
    layer.observe_many(bearings_from(true_lat, true_lon, lmap))
    layer.read()
    layer.chain._crumbs.clear()
    out = layer.return_leg()
    assert out["available"] is False
    assert out["reason"] == NoFixReason.NO_ANCHOR
    print("[ok] no breadcrumbs -> no route home, and it says so")
    PASSED.append("empty_trail")


def test_return_leg_needs_a_current_fix():
    layer = LandmarkChainLayer(standard_map())
    layer.initialize()
    out = layer.return_leg()
    assert out["available"] is False
    assert out["reason"] == NoFixReason.NO_INPUT
    print("[ok] without a current fix there is no 'from', so no guidance")
    PASSED.append("leg_needs_fix")


def test_outbound_flight_builds_a_usable_trail():
    """Fly out taking fixes, then read the way home off the trail."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap, min_spacing_m=25.0)
    layer.initialize()
    now = 1_000_000.0
    for i in range(6):
        layer.clear_observations()
        lat, lon = place(i * 60.0, i * 20.0)
        layer.observe_many(bearings_from(lat, lon, lmap, now=now + i))
        r = layer.read(now=now + i)
        assert r.is_valid, r.raw_data
    assert len(layer.chain) == 6, len(layer.chain)
    home = layer.return_leg(now=now + 5)
    assert home["available"] is True
    assert home["remaining_crumbs"] >= 1
    assert set(home["target_landmarks"]) == {"bridge_b", "tank_c", "tower_a"}
    print(f"[ok] outbound: 6 fixes, {layer.chain.length_m:.0f} m trail, "
          f"way home bears {home['bearing_deg']:.1f} deg "
          f"for {home['distance_m']:.0f} m")
    PASSED.append("outbound")


# ------------------------------------------------------- cross-checking

def test_catches_a_satellite_claim_the_landmarks_contradict():
    """An attacker can forge a waveform but cannot move a water tower."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    now = 1_000_000.0
    true_lat, true_lon = place(120.0, -60.0)
    layer.observe_many(bearings_from(true_lat, true_lon, lmap, now=now))

    honest = layer.check_satellite_claim(*place(125.0, -55.0), now=now)
    assert honest["checked"] and honest["consistent"]
    assert honest["verdict"] == "CONSISTENT"

    spoofed = layer.check_satellite_claim(*place(1200.0, 900.0), now=now)
    assert spoofed["checked"] and not spoofed["consistent"]
    assert spoofed["verdict"] == "SATELLITE_SUSPECT"
    print(f"[ok] spoof check: 7 m claim CONSISTENT, "
          f"{spoofed['disagreement_m']:.0f} m claim SATELLITE_SUSPECT "
          f"(allowed {spoofed['allowed_m']:.0f} m)")
    PASSED.append("sat_check")


def test_satellite_check_declines_without_a_fix():
    layer = LandmarkChainLayer(standard_map())
    layer.initialize()
    out = layer.check_satellite_claim(LAT0, LON0)
    assert out["checked"] is False
    assert out["reason"] == NoFixReason.NO_INPUT
    print("[ok] with nothing to check against, the check declines")
    PASSED.append("sat_declines")


def test_landmark_fix_re_anchors_dead_reckoning():
    """Layer 4 is what stops Layer 2 drifting — and only with a real fix."""
    lmap = standard_map()
    layer = LandmarkChainLayer(lmap)
    layer.initialize()
    now = 1_000_000.0
    true_lat, true_lon = place(120.0, -60.0)

    dr = CommandDeadReckoningLayer(
        AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True,
                      calibration_samples=12, calibration_rms_m=0.02,
                      max_calibration_speed_ms=8.0, drag_observable=True))
    dr.initialize()

    # No fix yet: the dead-reckoning layer must not be re-anchored to nothing.
    assert reset_dead_reckoning(dr, layer.read(now=now)) is False
    assert dr.read().raw_data["no_fix_reason"] == NoFixReason.NO_ANCHOR

    layer.observe_many(bearings_from(true_lat, true_lon, lmap, now=now))
    assert reset_dead_reckoning(dr, layer.read(now=now)) is True
    anchored = dr.read()
    assert anchored.raw_data["no_fix_reason"] == NoFixReason.NO_INPUT, \
        "anchored but commandless should want commands, not an anchor"
    print("[ok] a valid landmark fix re-anchors dead reckoning; "
          "an invalid one is refused")
    PASSED.append("reanchor")


def test_map_query_is_deterministic():
    lmap = standard_map()
    near = lmap.within(LAT0, LON0, 1000.0)
    again = lmap.within(LAT0, LON0, 1000.0)
    assert [l.landmark_id for l in near] == [l.landmark_id for l in again]
    assert near[0].landmark_id == "tower_a", "nearest should be 800 m tower"
    assert len(lmap.within(LAT0, LON0, 100.0)) == 0
    print(f"[ok] map query: {len(near)} within 1 km, nearest "
          f"{near[0].landmark_id}, stable ordering")
    PASSED.append("map_query")


def test_registered_in_the_layer_registry():
    assert "lmkchain_e23" in ALL_LAYER_CLASSES
    layer = ALL_LAYER_CLASSES["lmkchain_e23"]()
    assert layer.layer_number == 144
    assert layer.group.value == "E"
    assert len(ALL_LAYER_CLASSES) == 139
    print(f"[ok] registered as lmkchain_e23, layer 144, group E; "
          f"registry now {len(ALL_LAYER_CLASSES)} layers")
    PASSED.append("registry")


if __name__ == "__main__":
    tests = [
        test_foreign_map_sources_are_refused,
        test_indian_sources_are_accepted_and_normalised,
        test_landmark_must_state_its_survey_accuracy,
        test_cut_angle_folds_to_the_useful_range,
        test_resection_recovers_a_known_position,
        test_reported_accuracy_matches_observed_scatter,
        test_accuracy_degrades_with_worse_bearings,
        test_coarse_chart_widens_the_fix,
        test_bearing_plus_range_fixes_from_one_landmark,
        test_single_bearing_is_not_a_fix,
        test_declines_without_a_map,
        test_declines_without_observations,
        test_declines_on_stale_observations,
        test_declines_on_a_narrow_cut,
        test_unknown_landmarks_are_ignored_not_invented,
        test_produces_a_fix_and_reports_its_geometry,
        test_altitude_is_none_when_the_chart_has_none,
        test_confidence_tracks_geometry,
        test_layer_is_deterministic,
        test_passes_the_contract_audit,
        test_chain_records_only_spaced_out_fixes,
        test_return_leg_walks_the_trail_backwards,
        test_return_leg_declines_with_an_empty_trail,
        test_return_leg_needs_a_current_fix,
        test_outbound_flight_builds_a_usable_trail,
        test_catches_a_satellite_claim_the_landmarks_contradict,
        test_satellite_check_declines_without_a_fix,
        test_landmark_fix_re_anchors_dead_reckoning,
        test_map_query_is_deterministic,
        test_registered_in_the_layer_registry,
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

    print(f"\n{len(PASSED)}/{len(tests)} landmark-chain tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all landmark-chain tests passed")
