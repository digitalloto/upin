"""
Do the constellations agree with each other?

GPS, NavIC, Galileo, GLONASS and BeiDou are separate systems: different
satellites, often different frequencies. A spoofer that fakes only one of
them -- the cheap and common case -- makes that constellation's fix disagree
with the others. Solving each constellation separately and comparing the
answers catches it, and with three or more constellations it says which one
is lying.

WHAT IT CANNOT DO

It cannot prove that spoofing is impossible. Commercial multi-constellation
signal simulators can fake every constellation at once, consistently; then
all the fixes agree with each other and with the lie. Agreement raises the
cost of an attack; it is not a guarantee, and every result says so. The
checks a spoofer finds much harder to fake are physical: the reachability
region, consistency with motion sensors and dead reckoning, landmarks and
terrain, and received-power anomalies.

It is cheap enough to run every epoch, so it does.

Each input must be an independent solution -- one constellation's
satellites only. A receiver's single blended fix cannot be split after the
fact; per-constellation fixes come from raw measurements solved separately
(the L0 layers do this) or from separate receivers.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence

DEG_M = 111_320.0
GATE_CHI2_2DOF = 13.816      # p = 0.999: an honest pair fails once in a thousand

CANNOT_RULE_OUT = ("agreement between constellations does not rule out a "
                   "spoofer faking all of them consistently")


@dataclass(frozen=True)
class ConstellationFix:
    constellation: str
    lat: float
    lon: float
    sigma_m: float               # per-axis 1-sigma, horizontal


@dataclass
class CrossCheck:
    checked: bool
    consistent: bool
    suspects: List[str] = field(default_factory=list)
    pairs: Dict[str, float] = field(default_factory=dict)
    reason: str = ""
    caveat: str = CANNOT_RULE_OUT


def _statistic(a: ConstellationFix, b: ConstellationFix) -> float:
    dn = (a.lat - b.lat) * DEG_M
    de = (a.lon - b.lon) * DEG_M * math.cos(math.radians((a.lat + b.lat) / 2))
    return (dn * dn + de * de) / (a.sigma_m ** 2 + b.sigma_m ** 2)


def cross_check(fixes: Sequence[ConstellationFix]) -> CrossCheck:
    fixes = [f for f in fixes if f.sigma_m > 0 and math.isfinite(f.sigma_m)]
    names = [f.constellation for f in fixes]
    if len(set(names)) < 2:
        return CrossCheck(False, True, reason=(
            "only one constellation has a fix: nothing to cross-check against"))
    pairs: Dict[str, float] = {}
    failed: Dict[str, int] = {n: 0 for n in names}
    for a, b in combinations(fixes, 2):
        s = _statistic(a, b)
        pairs[f"{a.constellation}/{b.constellation}"] = s
        if s > GATE_CHI2_2DOF:
            failed[a.constellation] += 1
            failed[b.constellation] += 1
    if not any(failed.values()):
        return CrossCheck(True, True, [], pairs,
                          f"{len(fixes)} constellations agree")
    if len(fixes) == 2:
        return CrossCheck(True, False, sorted(names), pairs,
                          "the two constellations disagree; with only two, "
                          "which one is wrong cannot be told from GNSS alone")
    others = len(fixes) - 1
    suspects = sorted(n for n, k in failed.items() if k == others)
    if suspects:
        return CrossCheck(True, False, suspects, pairs,
                          f"{', '.join(suspects)} disagrees with every other "
                          f"constellation")
    return CrossCheck(True, False, sorted(n for n, k in failed.items() if k),
                      pairs, "constellations disagree with no single odd one out")
