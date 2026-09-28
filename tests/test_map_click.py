"""Tests for L2, the Map-Click Guided Layer.

Every flight here is flown, not scripted: the aircraft learns the wind and
its speed table while GNSS works, a jammer then takes GNSS away, and L2
steers to a clicked point on heading, tilt and time alone. Ground truth is
used only to score it.

The test that matters most is the calibration one. A guided layer that
arrives is useful; one whose stated circle actually contains the aircraft is
trustworthy. Earlier versions of this layer arrived fine while stating a
circle ten times too big, and later one that contained the truth only 72% of
the time. Both were caught here.

Run: python tests/test_map_click.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.control.autopilot import SimulatedAutopilot
from upin.core.no_fabrication import NoFixReason, audit_layer
from upin.core.speed_learner import SpeedLearner
from upin.core.wind_learner import FlightSample, WindEstimate, WindLearner
from upin.geo.greatcircle import destination, distance_bearing
from upin.layers.guidance.map_click import GuidanceState, MapClickGuidedLayer
from upin.layers.inertial.command_dr import AirframeModel
from upin.layers.registry import ALL_LAYER_CLASSES
from upin.simulation.world import SimulationWorld

PASSED = []

LAT, LON = 13.0827, 80.2707
QUAD = AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True)


def learn(seed=1, wind=(3.0, -2.0), gust=0.0, stale=None):
    """Fly the learning pattern with GNSS, then lose it. Returns the rig."""
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=seed)
    ap = SimulatedAutopilot(w, airframe=QUAD)
    w.set_wind(*wind, gust_sigma_ms=gust, seed=seed)
    rng = np.random.default_rng(seed)
    wl = WindLearner(wind_change_ms_per_min=stale)
    alt = w.true_alt
    for tilt in (5, 10, 15):
        for hdg in (0, 120, 240):
            ap.send_attitude(hdg, tilt, alt)
            for i in range(250):
                ap.fly(0.1)
                if i % 5 == 0:
                    v = w.get_gnss_velocity()
                    wl.add_sample(FlightSample(
                        w.elapsed, (w.true_heading + rng.normal(0, 1.0)) % 360.0,
                        tilt + rng.normal(0, 0.2), v["north_ms"], v["east_ms"], 0.1))
    sl = SpeedLearner("sim-quad", 0.0)
    sl.learn_from_samples(wl.steady_samples, wl.estimate())
    return w, ap, wl, sl, rng


def deny_gnss(w, wl):
    w.add_jamming_zone(w.true_lat, w.true_lon, 20_000.0, name="test jammer")
    wl.gnss_lost(w.elapsed)


def last_fix(w, rng, sigma=3.0):
    lat = w.true_lat + rng.normal(0, sigma) / 111_320.0
    lon = w.true_lon + rng.normal(0, sigma) / (111_320.0 * math.cos(math.radians(w.true_lat)))
    return lat, lon, sigma


def guided(w, ap, wl, sl, rng, **kw):
    L = MapClickGuidedLayer(ap, wl, sl, **kw)
    L.initialize()
    lat, lon, sigma = last_fix(w, rng)
    L.set_fix(lat, lon, w.true_alt, sigma, w.elapsed, "gnss_last",
              velocity_ne=(w.true_vn, w.true_ve))
    return L


def fly_to(w, ap, L, bearing, dist_m, max_s=300.0, record=None):
    tlat, tlon = destination(w.true_lat, w.true_lon, bearing, dist_m)
    L.set_target(tlat, tlon)
    st = None
    for _ in range(int(max_s / 0.1)):
        st = L.step(w.elapsed)
        ap.fly(0.1)
        if record is not None:
            r = L.read()
            err, _ = distance_bearing(w.true_lat, w.true_lon,
                                      r.position.latitude, r.position.longitude)
            record.append((err, r.raw_data["radius95_m"]))
        if st.state is GuidanceState.ARRIVED:
            break
    return st, (tlat, tlon)


def estimate_error(w, L):
    r = L.read()
    err, _ = distance_bearing(w.true_lat, w.true_lon,
                              r.position.latitude, r.position.longitude)
    return err, r.raw_data["radius95_m"]


# ------------------------------------------------------------- the contract

def test_passes_the_no_fabrication_audit():
    res = audit_layer(MapClickGuidedLayer())
    assert res.compliant, res.detail
    r = MapClickGuidedLayer().read()
    assert not r.is_valid and r.raw_data["no_fix_reason"] == NoFixReason.NO_ANCHOR
    assert "flight controller" in r.raw_data["detail"]
    print(f"[ok] contract audit: {res.detail}; bare read names what is missing")
    PASSED.append("audit")


def test_no_fix_means_no_command():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=1)
    ap = SimulatedAutopilot(w, airframe=QUAD)
    before = ap.setpoint
    L = MapClickGuidedLayer(ap)
    L.initialize()
    L.set_target(*destination(LAT, LON, 90.0, 300.0))
    st = L.step(w.elapsed)
    assert st.state is GuidanceState.NO_FIX
    assert ap.setpoint == before, "commanded the aircraft with no fix"
    print("[ok] no fix: state NO_FIX and not one command sent")
    PASSED.append("no_fix")


def test_refuses_to_fly_as_if_calm_when_the_wind_was_never_learned():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=2)
    ap = SimulatedAutopilot(w, airframe=QUAD)
    wl = WindLearner()
    wl.gnss_lost(w.elapsed)                 # GNSS gone before any learning
    sl = SpeedLearner("sim-quad")
    for t, v in ((5.0, 3.27), (10.0, 4.65)):
        for _ in range(6):
            sl.add(t, v)
    before = ap.setpoint
    L = MapClickGuidedLayer(ap, wl, sl)
    L.initialize()
    L.set_fix(w.true_lat, w.true_lon, w.true_alt, 3.0, w.elapsed)
    L.set_target(*destination(LAT, LON, 90.0, 300.0))
    st = L.step(w.elapsed + 0.1)
    assert st.state is GuidanceState.NO_WIND, st
    assert "refusing to fly as if calm" in st.reason
    assert ap.setpoint == before
    print(f"[ok] wind never learned: {st.reason[:78]}...")
    PASSED.append("no_wind")


def test_refuses_without_a_speed_table():
    w, ap, wl, _, rng = learn(seed=3)
    deny_gnss(w, wl)
    L = guided(w, ap, wl, SpeedLearner("empty"), rng)
    L.set_target(*destination(w.true_lat, w.true_lon, 45.0, 300.0))
    st = L.step(w.elapsed + 0.1)
    assert st.state is GuidanceState.NO_SPEED_TABLE, st
    print(f"[ok] no speed table: {st.reason}")
    PASSED.append("no_table")


# ------------------------------------------------------------------ flying

def test_flies_to_a_clicked_point_without_gnss():
    w, ap, wl, sl, rng = learn(seed=4)
    deny_gnss(w, wl)
    assert w.get_gnss_velocity() is None, "GNSS still available"
    L = guided(w, ap, wl, sl, rng)
    t0 = w.elapsed
    st, (tlat, tlon) = fly_to(w, ap, L, 60.0, 500.0)
    assert st.state is GuidanceState.ARRIVED, st
    err, radius = estimate_error(w, L)
    miss, _ = distance_bearing(w.true_lat, w.true_lon, tlat, tlon)
    assert err <= radius, (err, radius)
    assert miss <= radius + L.arrive_m, (miss, radius)
    print(f"[ok] 500 m, GNSS denied, 3.6 m/s wind: arrived in "
          f"{w.elapsed - t0:.0f} s; true miss {miss:.1f} m, estimate error "
          f"{err:.1f} m inside a {radius:.1f} m circle")
    PASSED.append("arrives")


def test_it_crabs_into_the_wind():
    """The nose points upwind of the target; the track still hits it."""
    w, ap, wl, sl, rng = learn(seed=5, wind=(0.0, 3.0))   # wind blowing east
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng)
    tlat, tlon = destination(w.true_lat, w.true_lon, 0.0, 600.0)  # due north
    L.set_target(tlat, tlon)
    for _ in range(400):                      # 40 s: settle into the crab
        L.step(w.elapsed)
        ap.fly(0.1)
    track = math.degrees(math.atan2(w.true_ve, w.true_vn)) % 360.0
    nose = ap.setpoint.heading_deg
    track_err = (track + 180.0) % 360.0 - 180.0
    crab = (nose + 180.0) % 360.0 - 180.0
    assert abs(track_err) < 3.0, f"ground track {track:.1f}, wanted 000"
    assert crab < -15.0, f"nose {nose:.1f}: not crabbed into an easterly"
    print(f"[ok] target due north, wind from the west: ground track "
          f"{track_err:+.1f} deg, nose {crab:+.1f} deg -- crabbing")
    PASSED.append("crab")


def test_ignoring_the_wind_misses_by_the_predicted_drift():
    """Tell L2 the air is calm: it misses by wind speed times flight time."""
    w, ap, wl, sl, rng = learn(seed=6, wind=(3.0, -2.0))
    deny_gnss(w, wl)

    class CalmLie:
        def estimate(self, now=None):
            return WindEstimate(0.0, 0.0, 0.01, 50, 200.0, 1.0, {})
        def why_not(self):
            return ""

    L = MapClickGuidedLayer(ap, CalmLie(), sl)
    L.initialize()
    L.set_fix(w.true_lat, w.true_lon, w.true_alt, 1.0, w.elapsed,
              velocity_ne=(w.true_vn - 3.0, w.true_ve + 2.0))
    t0 = w.elapsed
    st, (tlat, tlon) = fly_to(w, ap, L, 140.0, 400.0)
    t = w.elapsed - t0
    err, _ = estimate_error(w, L)
    predicted = math.hypot(3.0, -2.0) * t
    assert abs(err - predicted) / predicted < 0.10, (err, predicted)
    print(f"[ok] wind withheld: estimate {err:.0f} m out after {t:.0f} s; "
          f"|wind| x t predicts {predicted:.0f} m")
    PASSED.append("drift")


def test_the_circle_grows_until_a_fix_shrinks_it():
    w, ap, wl, sl, rng = learn(seed=7, gust=0.3)
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng)
    L.set_target(*destination(w.true_lat, w.true_lon, 200.0, 2000.0))
    radii = []
    for _ in range(600):
        L.step(w.elapsed)
        ap.fly(0.1)
        radii.append(L.radius95_m())
    assert all(b >= a - 1e-9 for a, b in zip(radii, radii[1:])), "circle shrank on its own"
    L.operator_fix(w.true_lat, w.true_lon, 5.0, w.elapsed)
    after = L.radius95_m()
    r = L.read()
    assert after < radii[-1] / 3.0, (radii[-1], after)
    assert r.raw_data["derived_from"] == "fix from operator"
    assert r.raw_data["seconds_since_fix"] == 0.0
    print(f"[ok] circle grew {radii[0]:.1f} -> {radii[-1]:.1f} m in 60 s; "
          f"an operator 'I am here' took it to {after:.1f} m")
    PASSED.append("circle")


def test_the_stated_circle_is_honest():
    """Across seeded gusty flights the 95% circle should hold the truth
    about 95% of the time -- not 72%, and not 100% with a circle ten times
    too big."""
    records, arrived = [], 0
    for seed in range(6):
        w, ap, wl, sl, rng = learn(seed=100 + seed, gust=0.5)
        deny_gnss(w, wl)
        L = guided(w, ap, wl, sl, rng)
        rec = []
        st, _ = fly_to(w, ap, L, float(rng.uniform(0, 360)), 500.0, record=rec)
        arrived += st.state is GuidanceState.ARRIVED
        records.extend(rec)
    ratio = np.array([e / r for e, r in records])
    inside = float(np.mean(ratio <= 1.0))
    median = float(np.median(ratio))
    assert inside >= 0.90, f"truth inside the 95% circle only {inside:.1%} of the time"
    assert median >= 0.10, f"median error/radius {median:.2f}: circle uselessly large"
    print(f"[ok] 6 gusty flights: truth inside the 95% circle {inside:.1%} of "
          f"the time, median error/radius {median:.2f}; {arrived}/6 arrived")
    PASSED.append("honest")


# ----------------------------------------------------- handing over, limits

def test_exceeding_the_limit_calls_the_escape_hook_once():
    w, ap, wl, sl, rng = learn(seed=8, gust=0.3)
    deny_gnss(w, wl)
    calls = []

    def escape(layer, status):
        calls.append(status.state)
        return True                          # the escape manager takes over

    L = guided(w, ap, wl, sl, rng, max_radius_m=20.0,
               on_uncertainty_exceeded=escape)
    L.set_target(*destination(w.true_lat, w.true_lon, 90.0, 3000.0))
    taken_at = None
    for i in range(1200):
        st = L.step(w.elapsed)
        if calls and taken_at is None:
            taken_at = ap.setpoint
        ap.fly(0.1)
    assert calls == [GuidanceState.UNCERTAINTY_EXCEEDED], calls
    assert ap.setpoint == taken_at, "L2 kept commanding after handing over"
    print("[ok] radius limit: escape hook called exactly once, and L2 stopped "
          "commanding once it took over")
    PASSED.append("hook")


def test_with_no_escape_manager_it_holds_station_not_drifts():
    """Level attitude in wind means drifting at wind speed. It must not."""
    w, ap, wl, sl, rng = learn(seed=9, wind=(3.0, -2.0))
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng, max_radius_m=15.0)
    L.set_target(*destination(w.true_lat, w.true_lon, 90.0, 3000.0))
    for _ in range(1500):
        st = L.step(w.elapsed)
        ap.fly(0.1)
    assert st.state is GuidanceState.UNCERTAINTY_EXCEEDED
    ground = math.hypot(w.true_vn, w.true_ve)
    assert ground < 0.5, f"drifting at {ground:.2f} m/s"
    print(f"[ok] limit exceeded with nobody to hand to: holds station into the "
          f"wind at {ground:.2f} m/s ground speed (level hold would drift at 3.6)")
    PASSED.append("station_keep")


def test_a_wind_it_cannot_beat_is_reported_not_flown():
    w, ap, wl, sl, rng = learn(seed=10, wind=(0.0, 7.0))   # 7 m/s > 5.7 max
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng)
    L.set_target(*destination(w.true_lat, w.true_lon, 270.0, 500.0))  # upwind
    before = ap.setpoint
    st = L.step(w.elapsed + 0.1)
    assert st.state is GuidanceState.CANNOT_HOLD_TRACK, st
    assert ap.setpoint == before, "sent a command it knew could not work"
    print(f"[ok] 7 m/s headwind vs 5.7 m/s best airspeed: {st.reason}")
    PASSED.append("too_strong")


def test_it_never_asks_for_more_than_it_learned():
    w, ap, wl, sl, rng = learn(seed=11, gust=0.3)
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng)
    _, hi = sl.learned_range
    tilts = []
    # Upwind: the wind (3, -2) blows toward 326, so 146 is straight into it
    # and the aircraft has to reach for the top of its table. A downwind leg
    # would pass this test at two degrees of tilt without testing anything.
    tlat, tlon = destination(w.true_lat, w.true_lon, 146.0, 400.0)
    L.set_target(tlat, tlon)
    for _ in range(2000):
        st = L.step(w.elapsed)
        if st.tilt_cmd_deg is not None:
            tilts.append(st.tilt_cmd_deg)
        ap.fly(0.1)
        if st.state is GuidanceState.ARRIVED:
            break
    assert ap.refusals == [], ap.refusals
    assert max(tilts) <= hi + 1e-9, (max(tilts), hi)
    assert max(tilts) > 0.8 * hi, f"only reached {max(tilts):.1f} deg: not a test of the ceiling"
    print(f"[ok] {len(tilts)} commands, none refused, none beyond the "
          f"{hi:g} deg the table has seen (max {max(tilts):.2f})")
    PASSED.append("limits")


# ------------------------------------------------------------- the reading

def test_the_reading_says_it_is_not_independent():
    w, ap, wl, sl, rng = learn(seed=12)
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng)
    L.set_target(*destination(w.true_lat, w.true_lon, 0.0, 300.0))
    for _ in range(100):
        L.step(w.elapsed)
        ap.fly(0.1)
    r = L.read()
    assert r.raw_data["independent"] is False
    budget = r.raw_data["error_budget_m"]
    for key in ("fix", "wind", "airspeed", "gusts_measured",
                "compass_assumed", "transient_assumed"):
        assert key in budget, key
    a, b = L.read(), L.read()
    assert (a.position.latitude, a.position.accuracy_m) == \
           (b.position.latitude, b.position.accuracy_m)
    print(f"[ok] independent=False; budget separates measured from assumed: "
          f"{ {k: round(v, 1) for k, v in budget.items()} }")
    PASSED.append("reading")


def test_nudge_moves_the_target_relative_to_the_nose():
    w, ap, wl, sl, rng = learn(seed=13)
    deny_gnss(w, wl)
    L = guided(w, ap, wl, sl, rng)
    L.set_target(*destination(w.true_lat, w.true_lon, 0.0, 400.0))
    for _ in range(50):
        L.step(w.elapsed)
        ap.fly(0.1)
    old = L._target
    heading = ap.telemetry()["heading_deg"]
    L.nudge(forward_m=100.0)
    moved, brg = distance_bearing(old[0], old[1], L._target[0], L._target[1])
    assert abs(moved - 100.0) < 0.5 and abs(((brg - heading) + 180) % 360 - 180) < 0.5
    print(f"[ok] nudge forward 100 m moved the target {moved:.2f} m along the nose")
    PASSED.append("nudge")


def test_registered():
    assert "mapclick_b13" in ALL_LAYER_CLASSES
    layer = ALL_LAYER_CLASSES["mapclick_b13"]()
    assert layer.layer_number == 145 and layer.group.value == "B"
    print("[ok] registered as mapclick_b13, layer 145, group B")
    PASSED.append("registered")


if __name__ == "__main__":
    tests = [
        test_passes_the_no_fabrication_audit,
        test_no_fix_means_no_command,
        test_refuses_to_fly_as_if_calm_when_the_wind_was_never_learned,
        test_refuses_without_a_speed_table,
        test_flies_to_a_clicked_point_without_gnss,
        test_it_crabs_into_the_wind,
        test_ignoring_the_wind_misses_by_the_predicted_drift,
        test_the_circle_grows_until_a_fix_shrinks_it,
        test_the_stated_circle_is_honest,
        test_exceeding_the_limit_calls_the_escape_hook_once,
        test_with_no_escape_manager_it_holds_station_not_drifts,
        test_a_wind_it_cannot_beat_is_reported_not_flown,
        test_it_never_asks_for_more_than_it_learned,
        test_the_reading_says_it_is_not_independent,
        test_nudge_moves_the_target_relative_to_the_nose,
        test_registered,
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

    print(f"\n{len(PASSED)}/{len(tests)} map-click tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all map-click tests passed")
