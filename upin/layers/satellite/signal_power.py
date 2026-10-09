"""
Layer 146 -- GNSS signal-power spoof check (cn0spoof_a20). Support function:
it never reports a position. It says whether the pattern of satellite
signal strengths looks like a real sky or like one transmitter.

WHY IT WORKS

A receiver finds each satellite by correlating a known code against noise.
How strongly each correlation stands out (C/N0, in dB-Hz) depends on that
satellite's distance, its elevation and the antenna's gain pattern. Real
satellites therefore arrive at different strengths, stronger when high in
the sky. A spoofer usually transmits every fake satellite from one antenna,
which leaves fingerprints:

  1 too uniform      every satellite about equally strong
  2 no elevation     low satellites as strong as high ones
  3 too strong       stronger than open sky ever gives
  4 rising together  all satellites jump up at once (a takeover)
  5 AGC vs C/N0      the receiver's automatic gain control drops because
                     extra power is arriving, while C/N0 rises: spoofing.
                     AGC drops while C/N0 falls: jamming, reported as such.
  6 own profile      stronger than this antenna normally sees at each
                     elevation, once that has been learned on trusted fixes

The inputs are what a u-blox receiver already reports: per-satellite C/N0
and elevation (UBX NAV-SAT) and AGC (UBX MON-RF).

WHAT IT CANNOT CATCH -- stated, and asserted in tests/test_signal_power.py

- A spoofer that shapes each fake satellite's power by elevation, at
  realistic levels, passes every test here.
- A baseline learned while already spoofed from power-on learns the spoof.
  That is why the generic tests 1-5 keep running after learning.
- Every threshold below is an ASSUMPTION until calibrated on the receiver and
  antenna actually flown. Real skies differ: trees, the airframe, the
  antenna's pattern. The box therefore treats this check as a warning by
  default (power_check_action = "warn").

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.sensor_requirements import DataInput, Hardware, SensorRequirement

CLEAR, SUSPECT, JAMMING, NOT_RUN = "CLEAR", "SUSPECT_SPOOFING", "JAMMING", "NOT_RUN"

BANDS = ((0, 15), (15, 30), (30, 45), (45, 60), (60, 91))


@dataclass(frozen=True)
class SatPower:
    constellation: str
    cn0_dbhz: float
    elevation_deg: float


def _slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0


def _band(elev: float) -> int:
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= elev < hi:
            return i
    return len(BANDS) - 1


class SignalPowerCheckLayer(NavigationLayer):
    """Does the satellite signal-strength pattern look like a real sky?"""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("GNSS receiver reporting per-satellite C/N0 and elevation",
                     why="the signal strengths this layer judges",
                     typical_part="u-blox receiver with UBX NAV-SAT (M8 or later)"),
        ],
        inputs=[
            DataInput("per-satellite C/N0 and elevation", feed_method="feed_nav_sat",
                      units="dB-Hz, degrees", why="tests 1-4 and 6"),
            DataInput("RF front-end AGC (optional)", feed_method="feed_rf",
                      units="AGC count", why="test 5; skipped without it"),
            DataInput("whether this epoch's fix was trusted", feed_method="learn",
                      units="bool", why="learns this antenna's own profile only "
                      "from trusted epochs"),
        ],
        preconditions=(
            "at least 6 satellites tracked with known elevation",
            "elevations spanning at least 30 degrees for tests 1 and 2",
        ),
        notes="Support function: never a position. Thresholds are assumptions "
              "until calibrated on the flown receiver and antenna.",
    )

    MIN_SATS = 6
    MIN_ELEV_SPAN_DEG = 30.0
    MIN_SPREAD_DB = 1.5
    """**Assumption.** Below this standard deviation of C/N0 across
    satellites, the sky is suspiciously uniform. One transmitter gives about
    1 dB (measurement jitter only); a sky spanning 30 degrees of elevation
    gives more. Set between the two. It was 2.5 at first: the synthetic sky
    model dipped under that 1% of the time. Calibrate on the real antenna."""
    MIN_SLOPE_DB_PER_DEG = 0.03
    """**Assumption.** Below this C/N0-vs-elevation slope, low satellites are
    as strong as high ones. Real antennas give clearly positive slopes."""
    MAX_PLAUSIBLE_DBHZ = 51.0
    """**Assumption.** Median C/N0 above this is stronger than open sky
    gives a typical patch antenna on L1."""
    JUMP_DB = 6.0
    """**Assumption.** A median rise this large between consecutive epochs,
    with most satellites rising, is a takeover signature."""
    AGC_DROP_FRACTION = 0.15
    """**Assumption.** AGC this far below its learned level means extra
    power is arriving at the antenna."""
    PROFILE_OFFSET_DB = 5.0
    """**Assumption.** Satellites this much stronger than this antenna's
    learned profile, across bands, is suspicious."""
    LEARN_EPOCHS = 60
    STALE_S = 3.0

    def __init__(self):
        super().__init__(
            layer_id="cn0spoof_a20", layer_number=146,
            name="GNSS Signal-Power Spoof Check",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[],
            description="Judges whether satellite signal strengths look like a "
                        "real sky or one transmitter. Never a position.",
        )
        self._sats: List[SatPower] = []
        self._sats_t: Optional[float] = None
        self._prev_cn0: Dict[str, float] = {}
        self._prev_t: Optional[float] = None
        self._agc: Optional[float] = None
        self._band_sum = [0.0] * len(BANDS)
        self._band_n = [0] * len(BANDS)
        self._agc_learn: List[float] = []
        self._learned_epochs = 0
        self.last_verdict: Optional[dict] = None

    # -- contract -----------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.0          # produces no position

    # -- inputs -------------------------------------------------------------

    def feed_nav_sat(self, sats: Sequence, t: float) -> None:
        """UBX NAV-SAT satellites (SatInfo from upin.box.gnss_parser), or any
        objects with constellation, sv_id, cn0_dbhz and elevation_deg."""
        tracked = [s for s in sats
                   if s.cn0_dbhz > 0 and 0 <= s.elevation_deg <= 90]
        self._prev_cn0 = {k: v for k, v in self._cur_cn0().items()}
        self._prev_t = self._sats_t
        self._sats = [SatPower(s.constellation, float(s.cn0_dbhz), float(s.elevation_deg))
                      for s in tracked]
        self._ids = [f"{s.constellation}{getattr(s, 'sv_id', i)}" for i, s in enumerate(tracked)]
        self._sats_t = t

    def _cur_cn0(self) -> Dict[str, float]:
        return {i: s.cn0_dbhz for i, s in zip(getattr(self, "_ids", []), self._sats)}

    def feed_rf(self, blocks: Sequence, t: float) -> None:
        """UBX MON-RF blocks; the first block's AGC count is used."""
        self._agc = float(blocks[0].agc_count) if blocks else None

    def learn(self, trusted: bool) -> None:
        """Add the current epoch to this antenna's profile -- only if the fix
        was trusted and this layer itself saw nothing suspicious."""
        v = self.last_verdict
        if not trusted or not self._sats or v is None or v["verdict"] != CLEAR:
            return
        for s in self._sats:
            b = _band(s.elevation_deg)
            self._band_sum[b] += s.cn0_dbhz
            self._band_n[b] += 1
        if self._agc is not None:
            self._agc_learn.append(self._agc)
        self._learned_epochs += 1

    @property
    def profile_learned(self) -> bool:
        return (self._learned_epochs >= self.LEARN_EPOCHS
                and sum(1 for n in self._band_n if n >= 20) >= 3)

    def profile(self) -> List[Optional[float]]:
        """Learned mean C/N0 per elevation band (None where unlearned)."""
        return [self._band_sum[i] / n if n >= 20 else None
                for i, n in enumerate(self._band_n)]

    # -- the judgement --------------------------------------------------------

    def check(self, t: float) -> dict:
        tests: List[dict] = []

        def test(name, fired, value, threshold, unit, kind="spoofing"):
            tests.append({"test": name, "fired": bool(fired), "value": value,
                          "threshold": threshold, "unit": unit, "kind": kind})

        def done(verdict, reason):
            self.last_verdict = {
                "verdict": verdict, "reason": reason, "tests": tests,
                "satellites": [[s.constellation, s.cn0_dbhz, s.elevation_deg]
                               for s in self._sats],
                "profile_learned": self.profile_learned,
                "profile": [[lo, hi, m] for (lo, hi), m in zip(BANDS, self.profile())],
                "agc": self._agc, "t": t,
            }
            self.status.spoofing_suspected = verdict == SUSPECT
            return self.last_verdict

        if self._sats_t is None:
            return done(NOT_RUN, "no per-satellite signal data (UBX NAV-SAT) received")
        if t - self._sats_t > self.STALE_S:
            return done(NOT_RUN, f"signal data {t - self._sats_t:.0f} s old")

        sats = self._sats
        cn0 = [s.cn0_dbhz for s in sats]
        median = statistics.median(cn0) if cn0 else None

        # 5: AGC first -- it is the only test that also works when jamming
        # has knocked satellites out.
        agc_base = statistics.fmean(self._agc_learn) if len(self._agc_learn) >= 20 else None
        agc_drop = (agc_base is not None and self._agc is not None
                    and self._agc < agc_base * (1 - self.AGC_DROP_FRACTION))
        prof = self.profile()
        base_median = None
        if self.profile_learned:
            known = [m for m in prof if m is not None]
            base_median = statistics.median(known) if known else None

        if len(sats) < self.MIN_SATS:
            if agc_drop:
                test("AGC drop with satellites lost", True, self._agc,
                     round(agc_base * (1 - self.AGC_DROP_FRACTION)), "AGC count", "jamming")
                return done(JAMMING, f"AGC fell to {self._agc:.0f} (learned "
                            f"{agc_base:.0f}) and only {len(sats)} satellites tracked")
            return done(NOT_RUN, f"only {len(sats)} satellites tracked "
                        f"(needs {self.MIN_SATS})")

        elevs = [s.elevation_deg for s in sats]
        span = max(elevs) - min(elevs)
        if span >= self.MIN_ELEV_SPAN_DEG:
            spread = statistics.pstdev(cn0)
            test("too uniform", spread < self.MIN_SPREAD_DB, round(spread, 2),
                 self.MIN_SPREAD_DB, "dB spread")
            slope = _slope(elevs, cn0)
            test("no elevation dependence", slope < self.MIN_SLOPE_DB_PER_DEG,
                 round(slope, 3), self.MIN_SLOPE_DB_PER_DEG, "dB/deg")
        test("too strong", median > self.MAX_PLAUSIBLE_DBHZ, median,
             self.MAX_PLAUSIBLE_DBHZ, "dB-Hz median")

        prev, cur = self._prev_cn0, self._cur_cn0()
        common = [k for k in cur if k in prev]
        if (self._prev_t is not None and self._sats_t - self._prev_t <= 2.5
                and len(common) >= self.MIN_SATS):
            rises = [cur[k] - prev[k] for k in common]
            med_rise = statistics.median(rises)
            most = sum(1 for r in rises if r > self.JUMP_DB / 2) >= 0.7 * len(rises)
            test("all rising together", med_rise > self.JUMP_DB and most,
                 med_rise, self.JUMP_DB, "dB median rise")

        if agc_drop:
            falling = base_median is not None and median < base_median - 3.0
            test("AGC drop", True, self._agc,
                 round(agc_base * (1 - self.AGC_DROP_FRACTION)), "AGC count",
                 "jamming" if falling else "spoofing")

        if self.profile_learned:
            offsets = [s.cn0_dbhz - prof[_band(s.elevation_deg)] for s in sats
                       if prof[_band(s.elevation_deg)] is not None]
            if len(offsets) >= self.MIN_SATS:
                off = statistics.median(offsets)
                test("stronger than this antenna's profile", off > self.PROFILE_OFFSET_DB,
                     round(off, 2), self.PROFILE_OFFSET_DB, "dB above profile")

        spoof = [x["test"] for x in tests if x["fired"] and x["kind"] == "spoofing"]
        jam = [x["test"] for x in tests if x["fired"] and x["kind"] == "jamming"]
        note = "" if self.profile_learned else "; this antenna's profile not learned yet"
        if spoof:
            return done(SUSPECT, f"looks like one transmitter: {', '.join(spoof)}{note}")
        if jam:
            return done(JAMMING, f"looks like jamming: {', '.join(jam)}{note}")
        return done(CLEAR, f"{len(sats)} satellites look like a real sky{note}")

    def read(self) -> LayerReading:
        if self._sats_t is None:
            return no_fix(self.layer_id, NoFixReason.NO_INPUT,
                          self.REQUIRES.describe_missing([]),
                          feed_via=self.REQUIRES.feed_methods)
        v = self.check(self._sats_t)
        return LayerReading(layer_id=self.layer_id, position=None, is_valid=False,
                            self_confidence=0.0,
                            raw_data={"support_function": True, "fabricated": False,
                                      **v})
