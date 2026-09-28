"""Tests for the Wind Learner and Speed Learner.

Flown, not synthesised: every learning test flies the simulated aircraft
through F1's wind with F2's autopilot, and samples it the way a real
receiver and compass would -- GNSS Doppler velocity, a noisy heading, the
attitude estimate's tilt. Noise is added here, in the test rig, which is
where the contract says it belongs.

Run: python tests/test_learners.py
"""
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np

from upin.control.autopilot import SimulatedAutopilot
from upin.core.speed_learner import SpeedLearner, TableMismatchError
from upin.core.wind_learner import FlightSample, WindLearner
from upin.layers.inertial.command_dr import AirframeModel
from upin.simulation.world import SimulationWorld

PASSED = []

LAT, LON = 13.0827, 80.2707
G = 9.80665
QUAD = AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True)


def theory_airspeed(tilt_deg):
    return math.sqrt(G * math.tan(math.radians(tilt_deg)) / QUAD.drag_coeff)


def rig(wind=(0.0, 0.0), gust=0.0, seed=1):
    w = SimulationWorld.at_agl(LAT, LON, 120.0, seed=seed)
    ap = SimulatedAutopilot(w, airframe=QUAD)
    w.set_wind(*wind, gust_sigma_ms=gust, seed=seed)
    return w, ap


def fly_legs(w, ap, learner, legs, dt=0.1, sample_every=5, noise_seed=0):
    """Fly (heading, tilt, seconds) legs, feeding the learner at 2 Hz."""
    rng = np.random.default_rng(noise_seed)
    alt = w.true_alt
    for heading, tilt, seconds in legs:
        ap.send_attitude(heading, tilt, alt)
        for i in range(int(round(seconds / dt))):
            ap.fly(dt)
            if i % sample_every:
                continue
            v = w.get_gnss_velocity()
            if v is None:
                learner.gnss_lost(w.elapsed)
                continue
            learner.add_sample(FlightSample(
                t=w.elapsed,
                heading_deg=(w.true_heading + rng.normal(0, 1.0)) % 360.0,
                tilt_deg=tilt + rng.normal(0, 0.2),
                v_north=v["north_ms"], v_east=v["east_ms"], v_sigma=0.1))


BOX = [(0, 10, 25), (90, 10, 25), (180, 10, 25), (270, 10, 25)]


# --------------------------------------------------------------- refusals

def test_declines_on_a_straight_line():
    """On one heading, a headwind and a slower airspeed look identical."""
    w, ap = rig(wind=(3.0, 1.0))
    L = WindLearner()
    fly_legs(w, ap, L, [(0, 10, 60)])
    assert L.samples >= L.MIN_SAMPLES, L.samples
    assert L.estimate() is None, "solved an unobservable wind triangle"
    assert "turn" in L.why_not(), L.why_not()
    print(f"[ok] straight line, {L.samples} samples: declines -- {L.why_not()[:70]}...")
    PASSED.append("straight")


def test_declines_with_too_few_samples():
    L = WindLearner()
    assert L.estimate() is None and "steady samples" in L.why_not()
    print(f"[ok] no data: {L.why_not()}")
    PASSED.append("few")


# ---------------------------------------------------------------- learning

def test_a_box_pattern_recovers_wind_and_airspeed():
    w, ap = rig(wind=(3.0, -2.5))
    L = WindLearner()
    fly_legs(w, ap, L, BOX)
    est = L.estimate()
    assert est is not None, L.why_not()
    werr = math.hypot(est.north_ms - 3.0, est.east_ms + 2.5)
    s = est.airspeeds[10.0]
    assert werr < 0.3, (est.north_ms, est.east_ms)
    assert abs(s - theory_airspeed(10)) < 0.2, s
    print(f"[ok] box in a (3.0, -2.5) wind: learned ({est.north_ms:.2f}, "
          f"{est.east_ms:.2f}) +/- {est.sigma_ms:.3f}, error {werr:.3f} m/s; "
          f"airspeed at 10 deg {s:.2f} (theory {theory_airspeed(10):.2f})")
    PASSED.append("box")


def test_several_tilts_are_learned_in_one_solve():
    w, ap = rig(wind=(-2.0, 1.5))
    L = WindLearner()
    legs = [(h, t, 25) for t in (5, 10, 15) for h in (0, 120, 240)]
    fly_legs(w, ap, L, legs)
    est = L.estimate()
    assert est is not None, L.why_not()
    rows = []
    for tilt in (5.0, 10.0, 15.0):
        got = est.airspeeds[tilt]
        # 0.1 m/s, not 0.25: a looser bound once hid a 6% low bias at
        # 5 degrees caused by counting unsettled samples as steady.
        assert abs(got - theory_airspeed(tilt)) < 0.1, (tilt, got)
        rows.append(f"{tilt:g}deg {got:.2f}/{theory_airspeed(tilt):.2f}")
    print("[ok] three tilts, one solve (learned/theory m/s): " + ", ".join(rows))
    PASSED.append("tilts")


def test_unsteady_samples_are_rejected():
    w, ap = rig(wind=(2.0, 0.0))
    L = WindLearner()
    fly_legs(w, ap, L, BOX)
    assert L.rejected_unsteady > 0, "turn transients were used as steady flight"
    print(f"[ok] {L.rejected_unsteady} samples rejected during turns and "
          f"speed changes")
    PASSED.append("unsteady")


def test_stated_uncertainty_is_honest_in_gusts():
    """The sigma must describe the real error, not flatter it.

    A single run can land close by luck. Across eight seeded gusty flights,
    the error divided by the stated sigma should look like a unit normal: an
    RMS near one, and almost every case inside three sigma. Before the
    correlation inflation this RMS was about five.
    """
    ratios, errors, sigmas = [], [], []
    for seed in range(8):
        w, ap = rig(wind=(3.0, 2.0), gust=1.5, seed=100 + seed)
        L = WindLearner()
        fly_legs(w, ap, L, BOX * 2, noise_seed=seed)
        est = L.estimate()
        assert est is not None, L.why_not()
        for got, true in ((est.north_ms, 3.0), (est.east_ms, 2.0)):
            ratios.append((got - true) / est.sigma_ms)
        errors.append(math.hypot(est.north_ms - 3.0, est.east_ms - 2.0))
        sigmas.append(est.sigma_ms)
    ratios = np.array(ratios)
    rms = float(np.sqrt(np.mean(ratios ** 2)))
    inside = int(np.sum(np.abs(ratios) <= 3.0))
    assert 0.3 < rms < 2.0, f"normalised error RMS {rms:.2f}: sigma is not honest"
    assert inside >= len(ratios) - 1, f"only {inside}/{len(ratios)} within 3 sigma"
    print(f"[ok] 8 gusty flights: mean error {np.mean(errors):.2f} m/s, mean "
          f"stated sigma {np.mean(sigmas):.2f}; normalised RMS {rms:.2f}, "
          f"{inside}/{len(ratios)} components within 3 sigma")
    PASSED.append("honest_sigma")


def test_calm_air_is_not_penalised_by_the_correction():
    w, ap = rig(wind=(3.0, 2.0), gust=0.0, seed=3)
    L = WindLearner()
    fly_legs(w, ap, L, BOX * 2)
    est = L.estimate()
    assert est.sigma_ms < 0.1, est.sigma_ms
    print(f"[ok] calm air still gives a tight sigma: {est.sigma_ms:.3f} m/s")
    PASSED.append("calm_sigma")


def test_a_sample_right_after_a_turn_is_not_steady():
    """Small acceleration is not the same as settled."""
    L = WindLearner()
    kept = []
    for i in range(60):                      # 30 s on one heading at 2 Hz
        heading = 0.0 if i < 30 else 90.0    # turn at 15 s
        kept.append(L.add_sample(FlightSample(i * 0.5, heading, 10.0,
                                              4.6 if heading == 0 else 0.0,
                                              0.0 if heading == 0 else 4.6)))
    turn = 30
    settle_samples = int(L.SETTLE_S / 0.5)
    assert not any(kept[turn:turn + settle_samples]), (
        "kept samples inside the settle window after a turn")
    assert any(kept[turn + settle_samples:]), "never re-settled"
    print(f"[ok] after a turn, the next {L.SETTLE_S:g} s of samples are "
          f"rejected however small the acceleration")
    PASSED.append("settle")


def test_the_window_forgets_an_old_wind():
    w, ap = rig(wind=(4.0, 0.0))
    L = WindLearner(window_s=60.0)
    fly_legs(w, ap, L, BOX)
    w.set_wind(-3.0, 2.0)
    fly_legs(w, ap, L, BOX)
    est = L.estimate()
    err = math.hypot(est.north_ms + 3.0, est.east_ms - 2.0)
    assert err < 0.4, (est.north_ms, est.east_ms)
    print(f"[ok] wind shifted (4,0) -> (-3,2): after one window the learner "
          f"reads ({est.north_ms:.2f}, {est.east_ms:.2f})")
    PASSED.append("window")


# ------------------------------------------------------------------ freeze

def test_it_freezes_when_gnss_is_lost():
    w, ap = rig(wind=(3.0, -2.5))
    L = WindLearner()
    fly_legs(w, ap, L, BOX)
    live = L.estimate()
    w.add_jamming_zone(w.true_lat, w.true_lon, 3000.0)
    fly_legs(w, ap, L, [(45, 10, 10)])
    assert L.frozen, "GNSS went and the learner kept learning"
    f0 = L.estimate(now=L._frozen.frozen_at)
    f5 = L.estimate(now=L._frozen.frozen_at + 300.0)
    assert (f0.north_ms, f0.east_ms) == (live.north_ms, live.east_ms)
    expected = math.hypot(f0.sigma_ms, L.WIND_CHANGE_MS_PER_MIN * 5.0)
    assert abs(f5.sigma_ms - expected) < 1e-9, (f5.sigma_ms, expected)
    assert L.add_sample(FlightSample(w.elapsed + 1, 0, 10, 0, 0)) is False
    print(f"[ok] frozen at GNSS loss: wind held at ({f0.north_ms:.2f}, "
          f"{f0.east_ms:.2f}); sigma {f0.sigma_ms:.2f} -> {f5.sigma_ms:.2f} m/s "
          f"after 5 min (declared assumption)")
    PASSED.append("freeze")


def test_losing_gnss_before_learning_leaves_no_wind():
    w, ap = rig(wind=(3.0, 0.0))
    L = WindLearner()
    w.add_jamming_zone(w.true_lat, w.true_lon, 3000.0)
    fly_legs(w, ap, L, [(0, 10, 10)])
    assert L.estimate() is None, "invented a wind it never measured"
    assert "before the wind was learned" in L.why_not()
    print("[ok] GNSS lost before learning: no wind, not calm -- "
          f"{L.why_not()[:60]}...")
    PASSED.append("unlearned")


def test_restoring_gnss_resumes_learning_from_scratch():
    L = WindLearner()
    L.gnss_lost(0.0)
    L.gnss_restored()
    assert not L.frozen and L.samples == 0
    print("[ok] GNSS restored: unfrozen, window cleared")
    PASSED.append("restore")


def test_cross_check_against_the_flight_controller():
    w, ap = rig(wind=(3.0, -2.5))
    L = WindLearner()
    fly_legs(w, ap, L, BOX)
    near = L.cross_check([3.2, -2.3])
    far = L.cross_check([-2.0, 3.0])
    assert near["checked"] and near["agree"], near
    assert far["checked"] and not far["agree"], far
    assert L.cross_check(None)["checked"] is False
    print(f"[ok] cross-check: FC 0.3 m/s off agrees; FC "
          f"{far['disagreement_ms']:.1f} m/s off is flagged")
    PASSED.append("cross_check")


def test_same_samples_same_answer():
    samples = []
    rng = np.random.default_rng(5)
    for i, h in enumerate(np.repeat([0, 90, 180, 270], 40)):
        hr = math.radians(h)
        samples.append(FlightSample(i * 0.5, float(h), 10.0,
                                    2.0 + 4.6 * math.cos(hr) + rng.normal(0, 0.05),
                                    -1.0 + 4.6 * math.sin(hr) + rng.normal(0, 0.05)))
    def run():
        L = WindLearner()
        L._last_seen = samples[0]
        for s in samples[1:]:
            L.add_sample(s)
        e = L.estimate()
        return (e.north_ms, e.east_ms, e.sigma_ms, e.airspeeds[10.0])
    assert run() == run()
    print("[ok] identical samples give a bit-identical wind estimate")
    PASSED.append("deterministic")


# ------------------------------------------------------------ Speed Learner

def primed_table():
    w, ap = rig(wind=(-2.0, 1.5))
    L = WindLearner()
    legs = [(h, t, 25) for t in (5, 10, 15) for h in (0, 120, 240)]
    fly_legs(w, ap, L, legs)
    S = SpeedLearner("sim-quad", payload_kg=1.2)
    S.learn_from_samples(L.steady_samples, L.estimate())
    return S, L


def test_speed_table_matches_physics():
    S, _ = primed_table()
    assert S.primed
    rows = []
    for tilt in (5.0, 10.0, 15.0):
        v, sd = S.lookup(tilt)
        assert abs(v - theory_airspeed(tilt)) < 0.15, (tilt, v)
        rows.append(f"{tilt:g}deg {v:.2f}+/-{sd:.2f}")
    print("[ok] speed table: " + ", ".join(rows))
    PASSED.append("table")


def test_it_interpolates_but_never_extrapolates():
    S, _ = primed_table()
    lo, hi = S.learned_range
    mid = S.lookup(7.5)
    assert mid is not None and S.lookup(5)[0] < mid[0] < S.lookup(10)[0]
    assert S.lookup(hi + 5.0) is None, "extrapolated past the learned range"
    assert S.tilt_for(theory_airspeed(25.0)) is None, (
        "offered a tilt for a speed it has never flown")
    print(f"[ok] learned {lo:g}-{hi:g} deg: interpolates at 7.5, refuses "
          f"{hi + 5:g} deg and any speed beyond the table")
    PASSED.append("no_extrapolation")


def test_tilt_for_inverts_lookup():
    S, _ = primed_table()
    for tilt in (4.0, 8.0, 12.5):
        v, _ = S.lookup(tilt)
        back = S.tilt_for(v)
        assert abs(back - tilt) < 1e-9, (tilt, back)
    print("[ok] tilt_for(lookup(t)) == t at 4, 8 and 12.5 deg")
    PASSED.append("inverse")


def test_not_primed_until_bins_fill():
    S = SpeedLearner("q", 0.0)
    for _ in range(4):
        S.add(10.0, 4.6)
    assert not S.primed and S.lookup(10.0) is None
    for _ in range(5):
        S.add(5.0, 3.3)
    S.add(10.0, 4.6)
    assert S.primed
    print("[ok] a bin answers only after 5 samples; the table needs 2 bins")
    PASSED.append("priming")


def test_table_persists_and_refuses_the_wrong_airframe():
    S, _ = primed_table()
    with tempfile.TemporaryDirectory() as d:
        path = S.save(Path(d) / "tables" / "sim-quad.json")
        back = SpeedLearner.load(path, "sim-quad", 1.2)
        assert back.table() == S.table()
        for kwargs in (dict(airframe_id="other-quad", payload_kg=1.2),
                       dict(airframe_id="sim-quad", payload_kg=3.0)):
            try:
                SpeedLearner.load(path, **kwargs)
            except TableMismatchError:
                continue
            raise AssertionError(f"loaded a table for {kwargs}")
    print("[ok] table survives a save/load; refused for another airframe "
          "or another payload")
    PASSED.append("persist")


def test_learned_model_predicts_a_new_heading():
    """The payoff: wind + table predict ground velocity on an unflown heading."""
    S, L = primed_table()
    est = L.estimate()
    w, ap = rig(wind=(-2.0, 1.5))
    ap.send_attitude(45.0, 10.0, w.true_alt)
    for _ in range(300):
        ap.fly(0.1)
    s, _ = S.lookup(10.0)
    h = math.radians(45.0)
    pred = (est.north_ms + s * math.cos(h), est.east_ms + s * math.sin(h))
    err = math.hypot(pred[0] - w.true_vn, pred[1] - w.true_ve)
    assert err < 0.3, err
    print(f"[ok] on heading 045 (never flown while learning): predicted "
          f"ground velocity off by {err:.3f} m/s")
    PASSED.append("predict")


if __name__ == "__main__":
    tests = [
        test_declines_on_a_straight_line,
        test_declines_with_too_few_samples,
        test_a_box_pattern_recovers_wind_and_airspeed,
        test_several_tilts_are_learned_in_one_solve,
        test_unsteady_samples_are_rejected,
        test_stated_uncertainty_is_honest_in_gusts,
        test_calm_air_is_not_penalised_by_the_correction,
        test_a_sample_right_after_a_turn_is_not_steady,
        test_the_window_forgets_an_old_wind,
        test_it_freezes_when_gnss_is_lost,
        test_losing_gnss_before_learning_leaves_no_wind,
        test_restoring_gnss_resumes_learning_from_scratch,
        test_cross_check_against_the_flight_controller,
        test_same_samples_same_answer,
        test_speed_table_matches_physics,
        test_it_interpolates_but_never_extrapolates,
        test_tilt_for_inverts_lookup,
        test_not_primed_until_bins_fill,
        test_table_persists_and_refuses_the_wrong_airframe,
        test_learned_model_predicts_a_new_heading,
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

    print(f"\n{len(PASSED)}/{len(tests)} learner tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all learner tests passed")
