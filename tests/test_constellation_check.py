"""Tests for the cross-constellation check.

Synthetic fixes with Gaussian error at their stated sigma.

Run: python tests/test_constellation_check.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.detection.constellation_check import (CANNOT_RULE_OUT, DEG_M,
                                                ConstellationFix, cross_check)

PASSED = []
LAT0, LON0 = 13.0827, 80.2707


def fix(name, n, e, sigma):
    return ConstellationFix(name, LAT0 + n / DEG_M,
                            LON0 + e / (DEG_M * math.cos(math.radians(LAT0))),
                            sigma)


def test_honest_false_alarm_rate():
    rng = np.random.default_rng(7)
    trials, alarms = 5000, 0
    for _ in range(trials):
        fixes = [fix("gps", *rng.normal(0, 3, 2), 3),
                 fix("navic", *rng.normal(0, 4, 2), 4)]
        alarms += not cross_check(fixes).consistent
    rate = alarms / trials
    assert rate < 0.004, rate
    print(f"[ok] honest GPS + NavIC: {alarms}/{trials} false alarms "
          f"({rate:.4f}; designed 0.001)")
    PASSED.append("honest")


def test_gps_only_spoof_two_constellations():
    cc = cross_check([fix("gps", 300, 0, 3), fix("navic", 1, -2, 4)])
    assert cc.checked and not cc.consistent
    assert "gps" in cc.suspects and "cannot be told" in cc.reason
    print("[ok] GPS spoofed by 300 m: GPS and NavIC disagree; with two, the "
          "check says it cannot tell which is wrong")
    PASSED.append("two")


def test_gps_only_spoof_three_constellations():
    cc = cross_check([fix("gps", 300, 0, 3), fix("navic", 1, -2, 4),
                      fix("galileo", -2, 1, 3)])
    assert not cc.consistent and cc.suspects == ["gps"], cc
    print("[ok] with three constellations the spoofed one is named: gps")
    PASSED.append("three")


def test_consistent_spoof_of_all_passes_and_says_so():
    cc = cross_check([fix("gps", 300, 0, 3), fix("navic", 301, 1, 4),
                      fix("galileo", 299, -1, 3)])
    assert cc.checked and cc.consistent
    assert cc.caveat == CANNOT_RULE_OUT
    print("[ok] all constellations spoofed consistently: the check passes, "
          "and its result says it cannot rule that out")
    PASSED.append("all")


def test_single_constellation_cannot_check():
    cc = cross_check([fix("gps", 0, 0, 3)])
    assert not cc.checked and "nothing to cross-check" in cc.reason
    print("[ok] one constellation: reported as unchecked, not as consistent")
    PASSED.append("single")


if __name__ == "__main__":
    tests = [test_honest_false_alarm_rate, test_gps_only_spoof_two_constellations,
             test_gps_only_spoof_three_constellations,
             test_consistent_spoof_of_all_passes_and_says_so,
             test_single_constellation_cannot_check]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} constellation-check tests passed")
