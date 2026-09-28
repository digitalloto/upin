"""Tests for the simulated environment the layered-navigation spec needs.

Wind, commandable dynamics, a jamming field and ground texture were added to
SimulationWorld so the spec's layers have something real to act on. These
tests check two things about each: that it behaves as the physics says, and
that it is off by default, so no legacy layer sees a different world.

Run: python tests/test_environment.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.layers.inertial.command_dr import (
    AirframeModel, MotorCommand, accel_from_command,
)
from upin.simulation.environment import (
    DENIAL_DROP_DB, TRACKING_THRESHOLD_DBHZ, WindField, ground_patch,
)
from upin.simulation.feeds import Observation, WorldFeed
from upin.simulation.world import SimulationWorld

PASSED = []

LAT, LON = 13.0827, 80.2707
DEG_M = 111_320.0

# A quadrotor: 2.3 g of thrust. Drag 0.08 /m is the test airframe used
# elsewhere in the repo, suited to the slow flight these tests do.
QUAD = AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True)


def offset(lat, lon, north_m, east_m):
    return (lat + north_m / DEG_M,
            lon + east_m / (DEG_M * math.cos(math.radians(lat))))


def hover_world(seed=1, heading=0.0):
    w = SimulationWorld.at_agl(LAT, LON, 120.0, heading_deg=heading,
                               velocity_ms=0.0, seed=seed)
    w.engage_dynamics(QUAD)
    return w


# ------------------------------------------------------------ off by default

def test_default_world_is_calm_and_unjammed():
    w = SimulationWorld()
    assert w.wind.is_calm
    assert len(w.jamming) == 0
    assert not w.dynamics_engaged
    np.random.seed(0)
    for _ in range(20):
        w.step(0.1)
    ground = math.hypot(w.true_vn, w.true_ve)
    assert abs(ground - w.true_velocity) < 1e-9, (
        "a calm world added something to the platform's velocity")
    print("[ok] default world: calm, unjammed, kinematic; ground speed == airspeed")
    PASSED.append("default")


def test_new_observations_leave_the_legacy_random_stream_alone():
    """Legacy layers draw from np.random. New observations must not."""
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=4)
    np.random.seed(99)
    before = np.random.get_state()[1].copy()
    w.get_gnss_velocity()
    w.get_ground_patch()
    w.get_rangefinder_agl()
    w.get_gnss_quality("GPS")
    after = np.random.get_state()[1]
    assert np.array_equal(before, after), "a new observation consumed a legacy draw"
    print("[ok] new observations use the world's own generator, "
          "not the legacy stream")
    PASSED.append("rng_isolation")


# -------------------------------------------------------------------- wind

def test_wind_displaces_the_ground_track():
    """Nose north at 20 m/s, wind blowing east at 5: the track bends east."""
    w = SimulationWorld(start_lat=LAT, start_lon=LON, start_heading=0.0,
                        start_velocity=20.0)
    w.set_wind(0.0, 5.0)
    np.random.seed(0)
    for _ in range(5):
        w.step(0.1)
    assert abs(w.true_ve - 5.0) < 0.5, f"east ground speed {w.true_ve:.2f}"
    assert abs(w.true_vn - 20.0) < 0.5, f"north ground speed {w.true_vn:.2f}"
    print(f"[ok] crosswind: ground velocity {w.true_vn:.2f} N, "
          f"{w.true_ve:.2f} E for a northbound nose")
    PASSED.append("wind_track")


def test_gusts_are_seeded_and_sized():
    def series(seed):
        wf = WindField(3.0, -2.0, gust_sigma_ms=1.5, gust_tau_s=5.0, seed=seed)
        out = []
        for _ in range(6000):
            wf.step(0.1)
            out.append(wf.vector_ned[:2].copy())
        return np.array(out)
    a, b, c = series(7), series(7), series(8)
    assert np.array_equal(a, b), "same seed, different gusts"
    assert not np.array_equal(a, c), "different seeds, same gusts"
    mean = a.mean(axis=0)
    std = (a - np.array([3.0, -2.0])).std(axis=0)
    assert np.allclose(mean, [3.0, -2.0], atol=0.4), mean
    assert np.all(np.abs(std - 1.5) < 0.4), std
    print(f"[ok] gusts: mean {mean.round(2)} (set 3,-2), std {std.round(2)} "
          f"(set 1.5), reproducible by seed")
    PASSED.append("gusts")


# ---------------------------------------------------------------- dynamics

def test_hover_holds_station_in_calm_air():
    w = hover_world()
    lat0, lon0, alt0 = w.true_lat, w.true_lon, w.true_alt
    for _ in range(50):
        w.step(0.1)
    drift = math.hypot((w.true_lat - lat0) * DEG_M,
                       (w.true_lon - lon0) * DEG_M * math.cos(math.radians(LAT)))
    assert drift < 0.01 and abs(w.true_alt - alt0) < 0.01, (drift, w.true_alt - alt0)
    print(f"[ok] level hover thrust in calm air: {drift*1000:.2f} mm drift over 5 s")
    PASSED.append("hover")


def test_pitching_forward_accelerates_along_the_heading():
    """Nose down, heading east: the platform accelerates east, not north."""
    w = hover_world(heading=90.0)
    pitch = -0.15
    # Enough thrust that the vertical component still balances gravity.
    throttle = QUAD.hover_throttle / math.cos(pitch)
    w.command_attitude(MotorCommand(0.0, throttle, 0.0, pitch,
                                    math.radians(90.0)))
    for _ in range(20):
        w.step(0.1)
    assert w.true_ve > 2.0, f"east speed {w.true_ve:.2f}"
    assert abs(w.true_vn) < 0.05, f"north speed {w.true_vn:.3f}"
    assert abs(w.true_vd) < 0.05, f"vertical speed {w.true_vd:.3f}"
    print(f"[ok] nose-down heading east: {w.true_ve:.2f} m/s east, "
          f"{w.true_vn:.3f} north, {w.true_vd:.3f} vertical")
    PASSED.append("pitch")


def test_world_obeys_the_same_equations_as_dead_reckoning():
    """Sim and Layer 2 share one model, so they agree by construction."""
    w = hover_world(heading=30.0)
    w.set_wind(2.0, -1.0)
    cmd = MotorCommand(0.0, 0.47, 0.05, -0.1, math.radians(30.0))
    w.command_attitude(cmd)
    worst = 0.0
    for _ in range(30):
        v_before = np.array([w.true_vn, w.true_ve, w.true_vd])
        w.step(0.1)
        expected = accel_from_command(cmd, QUAD, v_before, w.wind.vector_ned)
        worst = max(worst, float(np.max(np.abs(w._last_accel - expected))))
    assert worst < 1e-12, worst
    print(f"[ok] world acceleration == accel_from_command to {worst:.1e} m/s^2")
    PASSED.append("same_model")


def test_a_hovering_drone_is_carried_by_the_wind():
    """Level attitude in a wind: drag drags it until airspeed is zero."""
    w = hover_world()
    w.set_wind(3.0, -4.0)
    for _ in range(600):
        w.step(0.1)
    air = np.array([w.true_vn, w.true_ve]) - np.array([3.0, -4.0])
    assert np.linalg.norm(air) < 0.3, f"residual airspeed {air}"
    print(f"[ok] hovering in a 5 m/s wind: carried at "
          f"({w.true_vn:.2f}, {w.true_ve:.2f}), airspeed "
          f"{np.linalg.norm(air):.2f} m/s after 60 s")
    PASSED.append("carried")


def test_commanding_without_dynamics_is_refused():
    w = SimulationWorld()
    try:
        w.command_attitude(MotorCommand(0.0, 0.5, 0.0, 0.0, 0.0))
    except RuntimeError:
        print("[ok] commanding a world with no dynamics raises, not ignored")
        PASSED.append("refused")
        return
    raise AssertionError("an attitude command was silently ignored")


# ----------------------------------------------------------------- jamming

def test_inside_a_zone_every_satellite_is_lost():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=2)
    w.add_jamming_zone(LAT, LON, radius_m=2000.0)
    assert w.get_pseudoranges("GPS") == []
    assert w.get_pseudoranges("NavIC") == []
    q = w.get_gnss_quality("GPS")
    assert q["tracked"] == 0 and q["visible"] > 0, q
    assert q["noise_floor_rise_db"] > DENIAL_DROP_DB
    print(f"[ok] inside a 2 km zone: 0 of {q['visible']} GPS tracked, "
          f"noise floor up {q['noise_floor_rise_db']:.0f} dB")
    PASSED.append("denial")


def test_reception_recovers_with_distance():
    """The gradient the Escape Manager follows: fewer satellites near the
    jammer, more further away, never the reverse."""
    radius = 1000.0
    rows = []
    for k in (0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0):
        la, lo = offset(LAT, LON, 0.0, k * radius)
        w = SimulationWorld.at_agl(la, lo, 120.0, seed=2)
        w.add_jamming_zone(LAT, LON, radius_m=radius)
        q = w.get_gnss_quality("GPS")
        rows.append((k, q["tracked"], q["visible"], q["noise_floor_rise_db"]))
    tracked = [r[1] for r in rows]
    rise = [r[3] for r in rows]
    assert tracked == sorted(tracked), f"tracked not monotone: {tracked}"
    assert rise == sorted(rise, reverse=True), f"noise not monotone: {rise}"
    assert tracked[0] == 0 and tracked[-1] == rows[-1][2]
    print("[ok] reception vs distance: " + ", ".join(
        f"{k:g}r {t}/{v}" for k, t, v, _ in rows))
    PASSED.append("gradient")


def test_noise_grows_as_cn0_falls():
    far = SimulationWorld.at_agl(*offset(LAT, LON, 0, 20_000), 120.0, seed=2)
    near = SimulationWorld.at_agl(*offset(LAT, LON, 0, 1500), 120.0, seed=2)
    for w in (far, near):
        w.add_jamming_zone(LAT, LON, radius_m=1000.0)
    def err(w):
        np.random.seed(11)
        pr = [p for _ in range(40) for p in w.get_pseudoranges("GPS")]
        return float(np.std([p["pseudorange_m"] - p["true_range_m"] for p in pr]))
    e_far, e_near = err(far), err(near)
    assert e_near > 2.0 * e_far, (e_far, e_near)
    print(f"[ok] pseudorange noise {e_far:.1f} m far from the jammer, "
          f"{e_near:.1f} m at 1.5 radii")
    PASSED.append("noise")


def test_a_zone_only_jams_what_it_targets():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=2)
    w.add_jamming_zone(LAT, LON, radius_m=2000.0, constellations=("GPS",))
    assert w.get_pseudoranges("GPS") == []
    assert len(w.get_pseudoranges("NavIC")) >= 4
    print("[ok] a GPS-only jammer leaves NavIC tracking")
    PASSED.append("scoped")


def test_the_global_jamming_flag_now_does_something():
    """set_gps_jamming used to set a flag nothing read."""
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=2)
    assert len(w.get_pseudoranges("GPS")) > 0
    w.set_gps_jamming(True)
    assert w.get_pseudoranges("GPS") == []
    assert len(w.get_pseudoranges("NavIC")) > 0
    print("[ok] set_gps_jamming(True) now removes GPS and leaves NavIC")
    PASSED.append("global_flag")


def test_doppler_velocity_is_good_in_clear_sky_and_absent_under_denial():
    w = SimulationWorld.at_agl(LAT, LON, 120.0, heading_deg=45.0,
                               velocity_ms=15.0, seed=3)
    v = w.get_gnss_velocity()
    err = math.hypot(v["north_ms"] - w.true_vn, v["east_ms"] - w.true_ve)
    assert err < 0.3, err
    w.add_jamming_zone(LAT, LON, radius_m=2000.0)
    assert w.get_gnss_velocity() is None
    print(f"[ok] Doppler velocity {err:.3f} m/s error in clear sky, "
          f"None inside a zone")
    PASSED.append("doppler")


# -------------------------------------------------- ground, camera, height

def test_rangefinder_and_the_underground_default():
    good = SimulationWorld.at_agl(LAT, LON, 120.0, seed=5)
    agl = good.get_rangefinder_agl()
    assert agl is not None and abs(agl - 120.0) < 0.5, agl
    bad = SimulationWorld(start_lat=LAT, start_lon=LON, start_alt=120.0)
    assert bad.get_terrain_elevation() > bad.true_alt, "expected underground"
    assert bad.get_rangefinder_agl() is None
    assert bad.get_ground_patch() is None
    print(f"[ok] at_agl gives {agl:.2f} m; the legacy default is "
          f"{bad.get_terrain_elevation() - bad.true_alt:.0f} m underground and "
          f"the rangefinder says None, not a number")
    PASSED.append("agl")


def test_ground_patch_is_deterministic_and_textured():
    a, gsd = ground_patch(100.0, 200.0, 0.0, 120.0, 40.0, 64)
    b, _ = ground_patch(100.0, 200.0, 0.0, 120.0, 40.0, 64)
    assert np.array_equal(a, b)
    assert a.std() > 0.05, f"texture too flat to track: std {a.std():.3f}"
    print(f"[ok] ground patch: deterministic, texture std {a.std():.3f}, "
          f"{gsd:.2f} m/px at 120 m")
    PASSED.append("texture")


def test_moving_forward_slides_the_image_down():
    """What optical flow will measure: 3 pixels of motion is 3 rows."""
    a, gsd = ground_patch(0.0, 0.0, 0.0, 120.0, 40.0, 64)
    b, _ = ground_patch(0.0, 3 * gsd, 0.0, 120.0, 40.0, 64)
    assert np.allclose(b[3:], a[:-3], atol=1e-9), "image did not shift by 3 rows"
    c, _ = ground_patch(3 * gsd, 0.0, 90.0, 120.0, 40.0, 64)  # heading east
    d, _ = ground_patch(0.0, 0.0, 90.0, 120.0, 40.0, 64)
    assert np.allclose(c[3:], d[:-3], atol=1e-9), "heading rotation wrong"
    print("[ok] 3 px of forward motion slides the frame exactly 3 rows, "
          "at heading 0 and 90")
    PASSED.append("slide")


def test_imu_does_not_invent_an_attitude():
    k = SimulationWorld.at_agl(LAT, LON, 120.0, seed=6)
    imu = k.get_imu()
    assert imu["roll_rad"] is None and imu["attitude_modelled"] is False
    d = hover_world()
    d.command_attitude(MotorCommand(0.0, 0.5, 0.07, -0.03, 0.0))
    d.step(0.1)
    imu = d.get_imu()
    assert imu["roll_rad"] == 0.07 and imu["attitude_modelled"] is True
    print("[ok] kinematic world reports no attitude; with dynamics, the "
          "commanded one")
    PASSED.append("imu")


def test_the_world_feed_serves_every_new_observation():
    f = WorldFeed(SimulationWorld.at_agl(LAT, LON, 120.0, seed=8))
    for kind in (Observation.GNSS_QUALITY, Observation.GNSS_VELOCITY,
                 Observation.GROUND_IMAGE, Observation.RANGEFINDER_AGL,
                 Observation.IMU):
        assert f.observation(kind) is not None, kind
    pr = f.observation(Observation.PSEUDORANGES)
    assert len(pr["NavIC"]) >= 4, (
        f"NavIC returned {len(pr['NavIC'])} satellites -- the key casing bug")
    print(f"[ok] feed serves all new observations; NavIC has "
          f"{len(pr['NavIC'])} satellites (was 0 under the old key)")
    PASSED.append("feed")


if __name__ == "__main__":
    tests = [
        test_default_world_is_calm_and_unjammed,
        test_new_observations_leave_the_legacy_random_stream_alone,
        test_wind_displaces_the_ground_track,
        test_gusts_are_seeded_and_sized,
        test_hover_holds_station_in_calm_air,
        test_pitching_forward_accelerates_along_the_heading,
        test_world_obeys_the_same_equations_as_dead_reckoning,
        test_a_hovering_drone_is_carried_by_the_wind,
        test_commanding_without_dynamics_is_refused,
        test_inside_a_zone_every_satellite_is_lost,
        test_reception_recovers_with_distance,
        test_noise_grows_as_cn0_falls,
        test_a_zone_only_jams_what_it_targets,
        test_the_global_jamming_flag_now_does_something,
        test_doppler_velocity_is_good_in_clear_sky_and_absent_under_denial,
        test_rangefinder_and_the_underground_default,
        test_ground_patch_is_deterministic_and_textured,
        test_moving_forward_slides_the_image_down,
        test_imu_does_not_invent_an_attitude,
        test_the_world_feed_serves_every_new_observation,
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

    print(f"\n{len(PASSED)}/{len(tests)} environment tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all environment tests passed")
