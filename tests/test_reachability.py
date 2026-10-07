"""Tests for the reachability guard: where the aircraft could physically be.

The honest flights are synthetic: random manoeuvres no harder than the
airframe's stated acceleration, ground speed capped at its airspeed, fixes
with Gaussian error at their stated sigma. They test the guard's geometry
and margins, not any real airframe.

Run: python tests/test_reachability.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.detection.reachability import DEG_M, G, Envelope, ReachabilityGuard

PASSED = []
LAT0, LON0 = 13.0827, 80.2707
ENV = Envelope(max_accel_ms2=6.0, max_airspeed_ms=20.0)
SIGMA = 2.5


def ll(n, e):
    return (LAT0 + n / DEG_M,
            LON0 + e / (DEG_M * math.cos(math.radians(LAT0))))


def honest_flight(seed, seconds=600, dt=0.1):
    """(t, n, e, vn, ve) once a second, flown within the envelope."""
    rng = np.random.default_rng(seed)
    p, v = np.zeros(2), np.zeros(2)
    a = np.zeros(2)
    out = []
    for k in range(int(seconds / dt) + 1):
        t = k * dt
        if k % 20 == 0:                       # new manoeuvre every 2 s
            ang = rng.uniform(0, 2 * math.pi)
            a = rng.uniform(0, ENV.max_accel_ms2) * np.array([math.cos(ang), math.sin(ang)])
        v = v + a * dt
        s = np.linalg.norm(v)
        if s > ENV.max_airspeed_ms:
            v *= ENV.max_airspeed_ms / s
        p = p + v * dt
        if k % 10 == 0:
            out.append((t, p[0], p[1], v[0], v[1]))
    return out


def test_honest_flights_never_impossible():
    worst = -float("inf")
    checks = 0
    for seed in range(20):
        rng = np.random.default_rng(1000 + seed)
        guard = ReachabilityGuard(ENV)
        for i, (t, n, e, vn, ve) in enumerate(honest_flight(seed)):
            fn, fe = n + rng.normal(0, SIGMA), e + rng.normal(0, SIGMA)
            if i % 30 == 15:                  # every 30 s, a 15 s GNSS gap
                continue
            if guard.anchored:
                v = guard.check(*ll(fn, fe), t, sigma_m=SIGMA)
                worst = max(worst, v.excess_m)
                checks += 1
                assert v.possible, (seed, t, v.reason)
            guard.anchor(*ll(fn, fe), t, (vn + rng.normal(0, 0.3),
                                         ve + rng.normal(0, 0.3)),
                         sigma_pos_m=SIGMA, sigma_vel_ms=0.3)
    print(f"[ok] {checks} honest fixes over 20 flights: none impossible "
          f"(closest {worst:.0f} m inside the boundary)")
    PASSED.append("honest")


def test_jump_is_impossible():
    guard = ReachabilityGuard(ENV)
    guard.anchor(*ll(0, 0), 0.0, (10.0, 0.0), sigma_pos_m=SIGMA, sigma_vel_ms=0.3)
    v = guard.check(*ll(10.0, 500.0), 1.0)
    assert not v.possible and v.excess_m > 400, v
    assert "physically impossible" in v.reason
    ok = guard.check(*ll(10.0, 1.0), 1.0)
    assert ok.possible
    print(f"[ok] a 500 m jump one second later is impossible ({v.excess_m:.0f} m "
          f"beyond the region); the honest position is not")
    PASSED.append("jump")


def test_slow_drag_stays_inside_stated_limit():
    """The guard does NOT catch a spoofer who drags slowly. Asserted, so the
    limit cannot be forgotten. L0's statistical gate catches it
    (tests/test_gnss.py)."""
    guard = ReachabilityGuard(ENV)
    inside = 0
    for k in range(120):
        t = float(k)
        n, e = 1.0 * t, 0.0                   # truth hovers; spoof drifts 1 m/s
        if guard.anchored:
            inside += guard.check(*ll(n, e), t).possible
        guard.anchor(*ll(n, e), t, (1.0, 0.0), sigma_pos_m=SIGMA)
    assert inside == 119
    print("[ok] a 1 m/s drag-off stays inside the region for all 120 s -- "
          "this guard cannot see it; L0's gate is the check for that")
    PASSED.append("drag")


def test_region_grows_and_unanchored_says_so():
    guard = ReachabilityGuard(ENV)
    v0 = guard.check(*ll(0, 0), 0.0)
    assert v0.possible and "no trusted anchor" in v0.reason
    guard.anchor(*ll(0, 0), 0.0)
    r = [guard.check(*ll(0, 0), t).radius_m for t in (1, 10, 60)]
    assert r[0] < r[1] < r[2]
    print(f"[ok] region radius {r[0]:.0f} / {r[1]:.0f} / {r[2]:.0f} m at "
          f"1 / 10 / 60 s; before any anchor the guard says it cannot bound")
    PASSED.append("grows")


def test_envelope_from_airframe():
    env = Envelope.from_airframe(2 * G, 20.0)
    assert abs(env.max_accel_ms2 - G * math.sqrt(3)) < 1e-9
    try:
        Envelope.from_airframe(0.9 * G, 20.0)
        raise AssertionError("accepted an airframe that cannot fly")
    except ValueError:
        pass
    print("[ok] thrust-to-mass 2 g gives sqrt(3) g horizontal; below 1 g refused")
    PASSED.append("airframe")


if __name__ == "__main__":
    tests = [test_honest_flights_never_impossible, test_jump_is_impossible,
             test_slow_drag_stays_inside_stated_limit,
             test_region_grows_and_unanchored_says_so, test_envelope_from_airframe]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} reachability tests passed")
