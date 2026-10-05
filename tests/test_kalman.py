"""Tests for HonestKalmanFusion -- the textbook idea, held to its promises.

The first test is the worked example from the explainer: prediction 100 m
(variance 4), GPS 106 m (variance 12), gain 1/4, estimate 101.5 m, variance 3.

The calibration test uses synthetic data whose stated noise is true by
construction, so it tests the filter itself. With real layers, the filter is
only as honest as what the layers claim -- that is measured separately by
tools/compare_fusion.py.

Run: python tests/test_kalman.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.core.layer_base import LayerReading
from upin.core.position import Position
from upin.fusion.honest_kalman import DEG_M, HonestKalmanAlgorithm, HonestKalmanFusion

PASSED = []
LAT0, LON0 = 13.0827, 80.2707


def ll(n, e):
    return (LAT0 + n / DEG_M,
            LON0 + e / (DEG_M * math.cos(math.radians(LAT0))))


def ne(lat, lon):
    return ((lat - LAT0) * DEG_M,
            (lon - LON0) * DEG_M * math.cos(math.radians(LAT0)))


def reading(src, n, e, drms, t, independent=None):
    lat, lon = ll(n, e)
    raw = {} if independent is None else {"independent": independent}
    return LayerReading(layer_id=src, is_valid=True, self_confidence=0.9,
                        position=Position(latitude=lat, longitude=lon,
                                          accuracy_m=drms, timestamp=t),
                        raw_data=raw)


def truth_path(seed, steps, q, dt=1.0):
    """Constant-velocity truth driven by white acceleration of PSD q --
    exactly the motion the filter's model assumes."""
    rng = np.random.default_rng(seed)
    x = np.array([0.0, 0.0, 5.0, 3.0])          # n, e, vn, ve
    out = []
    for _ in range(steps):
        a = rng.normal(0, math.sqrt(q / dt), 2)
        x[:2] += x[2:] * dt + 0.5 * a * dt * dt
        x[2:] += a * dt
        out.append(x.copy())
    return out, rng


# -------------------------------------------------------------- the idea

def test_the_worked_example():
    kf = HonestKalmanFusion()
    kf.ACCEL_PSD_H = 0.0
    kf.update_position(*ll(100.0, 0.0), 2.0, "model", t=0.0)        # var 4
    d = kf.update_position(*ll(106.0, 0.0), math.sqrt(12.0), "gps", t=0.0)
    e = kf.estimate()
    n, _ = ne(e.lat, e.lon)
    assert d.accepted
    assert abs(n - 101.5) < 1e-6 and abs(e.sigma_north_m ** 2 - 3.0) < 1e-9, (n, e.sigma_north_m ** 2)
    print(f"[ok] worked example: estimate {n:.3f} m, variance {e.sigma_north_m ** 2:.3f} "
          f"(video: 101.5 m, 3)")
    PASSED.append("example")


def test_headings_are_compared_the_short_way_round():
    kf = HonestKalmanFusion()
    kf.update_position(LAT0, LON0, 5.0, "gps", t=0.0)
    kf.update_heading(359.0, 2.0, "compass")
    kf.update_heading(1.0, 2.0, "compass")
    h = kf.estimate().heading_deg
    assert min(h, 360.0 - h) < 0.5, h
    print(f"[ok] heading 359 + measured 1 -> {h:.2f} deg (the live filter gives 180)")
    PASSED.append("heading")


# ------------------------------------------------------- independence

def test_a_duplicated_source_adds_no_certainty():
    once, twice = HonestKalmanFusion(), HonestKalmanFusion()
    for kf, n_copies in ((once, 1), (twice, 2)):
        kf.step([reading("gps_l1", 0, 0, 5.0, 0.0)], 0.0)
        kf.step([reading("gps_l1", 1, 0, 5.0, 1.0)] * n_copies, 1.0)
    a, b = once.estimate().sigma_north_m, twice.estimate().sigma_north_m
    assert a == b, (a, b)
    skipped = [d for d in twice.decisions if not d.accepted]
    assert skipped and "same source" in skipped[0].reason
    print(f"[ok] the same source twice: variance unchanged ({a:.3f} m), "
          f"second copy skipped with its reason")
    PASSED.append("duplicate")


def test_an_estimate_derived_from_ours_is_not_fused():
    kf = HonestKalmanFusion()
    kf.step([reading("gps_l1", 0, 0, 5.0, 0.0)], 0.0)
    before = kf.estimate().sigma_north_m
    kf.step([reading("mapclick_b13", 0, 0, 1.0, 0.0, independent=False)], 0.0)
    assert kf.estimate().sigma_north_m == before
    print("[ok] a reading marked independent=False is never fused")
    PASSED.append("independent")


# -------------------------------------------------------- the surprise

def test_an_implausible_surprise_is_rejected_and_recorded():
    kf = HonestKalmanFusion()
    for t in range(10):
        kf.step([reading("gps_l1", 5.0 * t, 0, 4.0, float(t))], float(t))
    d = kf.update_position(*ll(50.0, 300.0), 3.0, "rogue", t=10.0)
    assert not d.accepted and "implausible" in d.reason, d
    good = kf.update_position(*ll(50.5, 0.5), 3.0, "gps_l1", t=10.0)
    assert good.accepted
    n, e = ne(kf.estimate().lat, kf.estimate().lon)
    assert abs(e) < 3.0, e
    print(f"[ok] 300 m rogue fix rejected ({d.reason}); the honest fix after it accepted")
    PASSED.append("gate")


# ------------------------------------------------------------- honesty

def test_the_stated_circle_is_honest_when_the_inputs_are():
    q, sigma = 0.5, 4.0
    ratios = []
    for seed in range(20):
        path, rng = truth_path(seed, 120, q)
        kf = HonestKalmanFusion()
        kf.ACCEL_PSD_H = q
        for t, x in enumerate(path):
            z = x[:2] + rng.normal(0, sigma, 2)
            kf.update_position(*ll(*z), sigma, "gps", t=float(t))
            if t >= 10:
                e = kf.estimate()
                n, ee = ne(e.lat, e.lon)
                ratios.append(math.hypot(n - x[0], ee - x[1]) / e.radius95_m)
    r = np.array(ratios)
    inside, med = float(np.mean(r <= 1.0)), float(np.median(r))
    assert 0.92 <= inside <= 0.98, inside
    assert 0.40 <= med <= 0.56, med
    print(f"[ok] 20 runs, true noise: truth inside the 95% circle {inside:.1%}, "
          f"median error/radius {med:.2f} (theory 0.48)")
    PASSED.append("honest")


def test_velocity_measurements_slow_the_drift_once_positions_stop():
    """Doppler velocity removes the drift that comes from not knowing the
    starting velocity. It cannot remove drift from manoeuvres flown after
    positions stop -- no measurement made beforehand can. So the truth here
    is near-steady cruise (q_truth 0.002), where the first kind dominates;
    the filter still assumes the more agile q = 0.05."""
    q, sigma = 0.05, 4.0
    with_v, without_v = [], []
    for seed in range(20):
        path, rng = truth_path(seed, 90, 0.002)
        for use_v, sink in ((True, with_v), (False, without_v)):
            r2 = np.random.default_rng(seed + 1000)
            kf = HonestKalmanFusion()
            kf.ACCEL_PSD_H = q
            for t, x in enumerate(path):
                if t < 60:
                    kf.update_position(*ll(*(x[:2] + r2.normal(0, sigma, 2))),
                                       sigma, "gps", t=float(t))
                    if use_v:
                        kf.update_velocity(*(x[2:] + r2.normal(0, 0.05, 2)), 0.05, "doppler")
                else:
                    kf.predict(float(t))
            e = kf.estimate()
            n, ee = ne(e.lat, e.lon)
            sink.append(math.hypot(n - path[-1][0], ee - path[-1][1]))
    a, b = float(np.mean(with_v)), float(np.mean(without_v))
    assert a < 0.7 * b, (a, b)
    print(f"[ok] 30 s after positions stop: drift {a:.1f} m with Doppler velocity, "
          f"{b:.1f} m without (mean of 20)")
    PASSED.append("velocity")


def test_nothing_before_the_first_fix():
    kf = HonestKalmanFusion()
    assert kf.estimate() is None
    assert not kf.update_velocity(1, 1, 0.1).accepted
    print("[ok] no estimate, and no velocity accepted, before the first position")
    PASSED.append("no_fix")


def test_offline_smoother_beats_the_live_filter_on_a_replay():
    q, sigma = 0.5, 4.0
    f_err, s_err = [], []
    path, rng = truth_path(3, 100, q)
    kf = HonestKalmanFusion(keep_history=True)
    kf.ACCEL_PSD_H = q
    live = []
    for t, x in enumerate(path):
        kf.predict(float(t))
        kf.update_position(*ll(*(x[:2] + rng.normal(0, sigma, 2))), sigma, "gps")
        kf.snapshot()
        live.append(kf.x[:2].copy())
    smoothed = kf.smooth()
    hist_t = [int(round(t)) for t, _, _ in smoothed]
    for (t, xs, _), ti in zip(smoothed, hist_t):
        f_err.append(np.linalg.norm(live[ti][:2] - path[ti][:2]))
        s_err.append(np.linalg.norm(xs[:2] - path[ti][:2]))
    a, b = float(np.sqrt(np.mean(np.square(f_err)))), float(np.sqrt(np.mean(np.square(s_err))))
    assert b < a, (a, b)
    print(f"[ok] offline replay: smoothed RMS {b:.2f} m vs live {a:.2f} m "
          f"(offline only -- uses future measurements)")
    PASSED.append("smoother")


def test_sits_beside_the_other_algorithms():
    algo = HonestKalmanAlgorithm()
    res = algo.fuse_readings([reading("gps_l1", 0, 0, 5.0, 0.0)])
    assert res is not None and res.position.accuracy_m > 0
    assert algo.get_algorithm_type() == "HONEST_KALMAN"
    print("[ok] fuse_readings() interface works alongside MultiFusionEngine's algorithms")
    PASSED.append("interface")


if __name__ == "__main__":
    tests = [
        test_the_worked_example,
        test_headings_are_compared_the_short_way_round,
        test_a_duplicated_source_adds_no_certainty,
        test_an_estimate_derived_from_ours_is_not_fused,
        test_an_implausible_surprise_is_rejected_and_recorded,
        test_the_stated_circle_is_honest_when_the_inputs_are,
        test_velocity_measurements_slow_the_drift_once_positions_stop,
        test_nothing_before_the_first_fix,
        test_offline_smoother_beats_the_live_filter_on_a_replay,
        test_sits_beside_the_other_algorithms,
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
    print(f"\n{len(PASSED)}/{len(tests)} kalman tests passed")
    if failed:
        sys.exit(1)
    print("all kalman tests passed")
