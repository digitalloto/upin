"""
Speed Learner -- how fast this airframe flies at a given tilt.

The Map-Click Guided layer decides what air velocity it needs, then has to
turn that into something a flight controller understands: a tilt. That
conversion is a property of one airframe carrying one payload -- a heavier
payload needs more thrust to hold altitude and drags differently -- so it is
learned in flight rather than assumed (spec section 1.4).

The learner keeps a table of tilt bins, each holding the airspeeds observed
at that tilt. Samples come from the Wind Learner, which is the only thing
that can separate airspeed from ground speed.

WHERE IT REFUSES

  it interpolates between learned tilts, never extrapolates past them. A
  table learned between 5 and 15 degrees says nothing about 22 degrees, and
  drag is quadratic, so a straight-line guess is wrong in the direction that
  matters: it overestimates speed at high tilt.

  a bin needs enough samples before it answers.

  a stored table is tied to its airframe and payload. Loading the table for
  a quadrotor with a 2 kg payload into one carrying 5 kg is refused, because
  the numbers would be confidently wrong.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _ar1_inflation(values: List[float]) -> float:
    """(1 + rho) / (1 - rho) from the lag-one autocorrelation, rho in [0, .99]."""
    if len(values) < 3:
        return 1.0
    x = [v - sum(values) / len(values) for v in values]
    denom = sum(v * v for v in x)
    if denom <= 0:
        return 1.0
    rho = sum(a * b for a, b in zip(x, x[1:])) / denom
    rho = min(max(rho, 0.0), 0.99)
    return (1.0 + rho) / (1.0 - rho)


class TableMismatchError(ValueError):
    """A stored speed table belongs to a different airframe or payload."""


@dataclass
class _Bin:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0          # Welford running sum of squared deviations
    n_eff: float = 0.0       # independent samples, after correlation

    def add(self, x: float, eff: float = 1.0) -> None:
        self.n += 1
        self.n_eff += eff
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)

    @property
    def std(self) -> float:
        """Scatter of individual samples -- mostly turbulence in flight."""
        return math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else float("inf")

    @property
    def standard_error(self) -> float:
        """How well the mean is known: scatter over root effective count."""
        if self.n < 2 or self.n_eff <= 0:
            return float("inf")
        return self.std / math.sqrt(self.n_eff)


class SpeedLearner:
    """Tilt -> steady airspeed, for one airframe with one payload."""

    MIN_PER_BIN = 5
    PAYLOAD_TOLERANCE_KG = 0.05

    def __init__(self, airframe_id: str, payload_kg: float = 0.0,
                 bin_deg: float = 2.5):
        if not airframe_id:
            raise ValueError("a speed table must name its airframe")
        self.airframe_id = airframe_id
        self.payload_kg = float(payload_kg)
        self.bin_deg = float(bin_deg)
        self._bins: Dict[float, _Bin] = {}

    # -- learning ---------------------------------------------------

    def add(self, tilt_deg: float, airspeed_ms: float, eff: float = 1.0) -> bool:
        if not (math.isfinite(tilt_deg) and math.isfinite(airspeed_ms)):
            return False
        if tilt_deg < 0 or airspeed_ms < 0:
            return False
        b = self._bin(tilt_deg)
        self._bins.setdefault(b, _Bin()).add(float(airspeed_ms), eff)
        return True

    def learn_from_samples(self, samples, wind_estimate) -> int:
        """Airspeed per sample: GNSS ground velocity with the wind taken out.

        Many samples per bin rather than one number per solve, so each bin's
        spread reflects the real scatter of the flight, not the solver's
        opinion of itself.
        """
        if wind_estimate is None:
            return 0
        wn, we = wind_estimate.north_ms, wind_estimate.east_ms
        # Airspeed along the nose, not the length of the air-velocity vector.
        # A multirotor pitched forward flies where it points, so a crosswise
        # gust is not airspeed -- but it lengthens the vector, and taking the
        # length biased every bin upward in gusty air.
        per_bin: Dict[float, List[Tuple[float, float]]] = {}
        for x in samples:
            h = math.radians(x.heading_deg)
            along = ((x.v_north - wn) * math.cos(h)
                     + (x.v_east - we) * math.sin(h))
            per_bin.setdefault(self._bin(x.tilt_deg), []).append((x.tilt_deg, along))
        added = 0
        for pairs in per_bin.values():
            # Consecutive samples in a gust are nearly the same number. Each
            # sample counts for 1 / inflation of an independent one, so a
            # thousand correlated samples do not pretend to be a thousand.
            eff = 1.0 / _ar1_inflation([v for _, v in pairs])
            for tilt, along in pairs:
                added += int(self.add(tilt, along, eff))
        return added

    def learn_from(self, wind_estimate) -> int:
        """Take the per-tilt airspeeds a wind-triangle solve produced."""
        added = 0
        for tilt, speed in (getattr(wind_estimate, "airspeeds", {}) or {}).items():
            added += int(self.add(tilt, speed))
        return added

    # -- reading ----------------------------------------------------

    def _bin(self, tilt_deg: float) -> float:
        return round(tilt_deg / self.bin_deg) * self.bin_deg

    def _usable(self) -> List[Tuple[float, _Bin]]:
        return sorted((t, b) for t, b in self._bins.items()
                      if b.n >= self.MIN_PER_BIN)

    @property
    def primed(self) -> bool:
        """Two usable bins -- the minimum that defines a slope."""
        return len(self._usable()) >= 2

    @property
    def learned_range(self) -> Optional[Tuple[float, float]]:
        u = self._usable()
        return (u[0][0], u[-1][0]) if u else None

    def lookup(self, tilt_deg: float) -> Optional[Tuple[float, float]]:
        """(airspeed, sigma) at this tilt, or None outside what was learned.

        Level flight is a known point for free: zero tilt is zero airspeed.

        Interpolation is in v^2 against tan(tilt), not v against tilt. At
        steady state, thrust's horizontal part balances drag, so
        g tan(tilt) = k v^2: v^2 is linear in tan(tilt). A straight line in v
        against tilt is badly wrong near zero, where sqrt(tan) is steep --
        30% slow at 2.5 degrees between the zero anchor and a 5 degree bin --
        and that is exactly where a guided layer flies its final approach.
        This is exact at every learned bin and exact between them for the
        quadratic drag the rest of the system already assumes.
        """
        u = self._usable()
        if not u:
            return None
        pts = [(0.0, 0.0, 0.0)] + [(t, b.mean, b.std) for t, b in u]
        if tilt_deg < 0 or tilt_deg > pts[-1][0]:
            return None
        x = math.tan(math.radians(tilt_deg))
        for (t0, v0, s0), (t1, v1, s1) in zip(pts, pts[1:]):
            if t0 <= tilt_deg <= t1:
                x0, x1 = math.tan(math.radians(t0)), math.tan(math.radians(t1))
                f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                v2 = v0 * v0 + f * (v1 * v1 - v0 * v0)
                s0 = 0.0 if t0 == 0.0 else s0
                return math.sqrt(max(v2, 0.0)), max(s0, s1)
        return None

    def tilt_for(self, airspeed_ms: float) -> Optional[float]:
        """The tilt that produces this airspeed, or None if it was never seen.

        This is the direction the guided layer uses. Asking for more speed
        than the table covers returns None, not the largest tilt: the caller
        must know the demand cannot be met.
        """
        u = self._usable()
        if not u or airspeed_ms < 0:
            return None
        pts = [(0.0, 0.0)] + [(t, b.mean) for t, b in u]
        target = airspeed_ms * airspeed_ms
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if v1 <= v0:
                return None      # non-monotone table: refuse rather than guess
            if v0 <= airspeed_ms <= v1:
                # the exact inverse of lookup(): linear in v^2 against tan
                x0, x1 = math.tan(math.radians(t0)), math.tan(math.radians(t1))
                f = (target - v0 * v0) / (v1 * v1 - v0 * v0)
                return math.degrees(math.atan(x0 + f * (x1 - x0)))
        return None

    def mean_sigma(self, tilt_deg: float) -> Optional[float]:
        """Standard error of the table's airspeed at this tilt.

        This, not the sample scatter, is the right number for a guidance
        layer's airspeed *bias*: scatter is turbulence, and turbulence is
        budgeted separately from the Wind Learner's gust measurement.
        Counting it here as well would count it twice.
        """
        u = self._usable()
        if not u or tilt_deg < 0 or tilt_deg > u[-1][0]:
            return None
        pts = [(0.0, 0.0)] + [(t, b.standard_error) for t, b in u]
        for (t0, s0), (t1, s1) in zip(pts, pts[1:]):
            if t0 <= tilt_deg <= t1:
                return max(s0, s1)
        return None

    DRAG_CONSISTENCY = 0.10
    """Largest spread between bins' implied drag coefficients, as a fraction
    of their mean, for the table to count as quadratic drag."""

    def drag_estimate(self) -> Optional[Tuple[float, float]]:
        """The quadratic drag coefficient the table implies, and its spread.

        At steady state g tan(tilt) = k v^2, so every learned bin implies a
        k. If they agree, the airframe's drag is quadratic and the common k
        lets a dead-reckoning layer integrate the real deceleration after a
        turn, instead of approximating it. If they do not agree, this returns
        None and the caller must not pretend otherwise.
        """
        g = 9.80665
        ks = [g * math.tan(math.radians(t)) / (b.mean * b.mean)
              for t, b in self._usable() if t > 0 and b.mean > 0]
        if len(ks) < 2:
            return None
        mean = sum(ks) / len(ks)
        spread = (max(ks) - min(ks)) / mean
        if spread > self.DRAG_CONSISTENCY:
            return None
        return mean, spread

    def table(self) -> Dict[float, Dict]:
        return {t: {"airspeed_ms": b.mean, "std_ms": b.std,
                    "standard_error_ms": b.standard_error, "n": b.n,
                    "n_effective": b.n_eff}
                for t, b in sorted(self._bins.items())}

    # -- persistence ------------------------------------------------

    def to_dict(self) -> Dict:
        return {"airframe_id": self.airframe_id, "payload_kg": self.payload_kg,
                "bin_deg": self.bin_deg,
                "bins": {str(t): {"n": b.n, "mean": b.mean, "m2": b.m2,
                                  "n_eff": b.n_eff}
                         for t, b in self._bins.items()}}

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)         # atomic: a crash never leaves half a table
        return path

    @classmethod
    def load(cls, path, airframe_id: str, payload_kg: float) -> "SpeedLearner":
        """Load a stored table, refusing one that belongs to another setup."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("airframe_id") != airframe_id:
            raise TableMismatchError(
                f"table is for airframe {data.get('airframe_id')!r}, "
                f"not {airframe_id!r}")
        if abs(float(data.get("payload_kg", -1)) - payload_kg) > cls.PAYLOAD_TOLERANCE_KG:
            raise TableMismatchError(
                f"table was learned with {data.get('payload_kg')} kg of payload, "
                f"not {payload_kg} kg -- a different payload flies differently")
        out = cls(airframe_id, payload_kg, data.get("bin_deg", 2.5))
        for t, b in data.get("bins", {}).items():
            out._bins[float(t)] = _Bin(int(b["n"]), float(b["mean"]),
                                       float(b["m2"]),
                                       float(b.get("n_eff", b["n"])))
        return out
