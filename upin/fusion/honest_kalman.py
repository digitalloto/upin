"""
An honest Kalman filter -- the textbook idea, kept true end to end.

The idea fits in one example. A motion model predicts the aircraft is at
100 m with variance 4; a GPS fix says 106 m with variance 12. The difference,
6 m, is the innovation -- the surprise. The Kalman gain decides how much of
the surprise to believe: 4 / (4 + 12) = 1/4. So the estimate moves a quarter
of the way, to 101.5 m, and because precisions (1 / variance) add, the new
variance is 1 / (1/4 + 1/12) = 3 -- better than either source alone.

That works only while three things stay true, and this filter is built
around keeping them true rather than assuming them:

  1. THE VARIANCES MEAN SOMETHING. Every number in the covariance is in
     metres or metres per second, set from the measurements' own stated
     uncertainty, and the filter REPORTS that covariance as its accuracy.
     The live engine reports accuracy from a confidence lookup table
     (0.5 m at "95% confidence"); this one reports what it actually knows.

  2. THE ERRORS ARE INDEPENDENT. Precisions add only for independent errors.
     Fuse one GPS fix twice and the variance drops from 3 to 2.4: certainty
     out of nothing. So a reading marked independent=False (a layer that is
     propagating an estimate it was given) is never fused, and each source
     contributes at most one measurement per cycle.

  3. THE SURPRISE IS PLAUSIBLE. Each measurement's normalised innovation is
     tested against chi-squared before it is believed. A 300 m "fix" when
     the filter is sure to 5 m is rejected and recorded, not averaged in.

Angles are compared the short way round: 359 and 1 degrees are 2 apart, not
358. (The live filter reads them as 358 apart and swings to 180.)

The state is local north / east / up metres around the first fix, plus
velocity and heading: [n, e, u, vn, ve, vu, heading]. Flat-earth geometry
about the reference point -- fine across the tens of kilometres a sortie
covers, re-anchored with `rereference()` beyond that.

One assumption is not measured here and is labelled as such: how hard the
aircraft manoeuvres, which sets how fast the prediction's uncertainty grows
(ACCEL_PSD). Measure it on the airframe and replace it.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from upin.core.layer_base import LayerReading

DEG_M = 111_320.0
R95_PER_SIGMA = 2.4477
N, E, U, VN, VE, VU, HDG = range(7)
STATE_DIM = 7


def wrap_deg(a: float) -> float:
    """Fold an angle difference into (-180, 180]."""
    return (a + 180.0) % 360.0 - 180.0


@dataclass
class Decision:
    """What happened to one measurement, kept so nothing is silent."""
    source: str
    kind: str                 # position, velocity, altitude, heading
    accepted: bool
    reason: str = ""
    nis: Optional[float] = None
    threshold: Optional[float] = None


@dataclass
class Estimate:
    lat: float
    lon: float
    alt: Optional[float]
    sigma_north_m: float
    sigma_east_m: float
    sigma_up_m: Optional[float]
    velocity_ne: Tuple[float, float]
    sigma_velocity_ms: float
    heading_deg: Optional[float]
    t: float

    @property
    def drms_m(self) -> float:
        return math.hypot(self.sigma_north_m, self.sigma_east_m)

    @property
    def radius95_m(self) -> float:
        return R95_PER_SIGMA * math.sqrt(
            (self.sigma_north_m ** 2 + self.sigma_east_m ** 2) / 2.0)


class HonestKalmanFusion:
    """Position/velocity/heading Kalman filter that keeps its variances true."""

    ACCEL_PSD_H = 0.5
    """**Assumption.** Horizontal acceleration noise, m^2/s^3, of a
    constant-velocity model: how hard the aircraft is expected to manoeuvre
    between measurements. Sets how fast the prediction's uncertainty grows.
    Measure it on the airframe."""

    ACCEL_PSD_V = 0.2
    """**Assumption.** The same for the vertical axis."""

    HEADING_RATE_PSD = 4.0
    """**Assumption.** Heading random walk, deg^2/s."""

    MAX_SPEED_MS = 60.0
    """Speed the platform cannot exceed. Sets the initial velocity
    uncertainty: before any velocity is measured, the filter knows only that
    it is below this."""

    GATE_PROB = 0.999
    """An honest measurement fails the gate one time in a thousand."""

    def __init__(self, gate: bool = True, use_independence_rule: bool = True,
                 keep_history: bool = False):
        self.gate = gate
        self.use_independence_rule = use_independence_rule
        self.keep_history = keep_history
        self.x = np.zeros(STATE_DIM)
        self.P = np.eye(STATE_DIM)
        self._ref: Optional[Tuple[float, float]] = None
        self._t: Optional[float] = None
        self._initialised = False
        self._have_alt = False
        self._have_heading = False
        self.decisions: List[Decision] = []
        self.history: List[Dict] = []
        self._consecutive_rejects = 0

    # -- geometry -------------------------------------------------------

    def _to_ne(self, lat: float, lon: float) -> Tuple[float, float]:
        lat0, lon0 = self._ref
        return ((lat - lat0) * DEG_M,
                (lon - lon0) * DEG_M * math.cos(math.radians(lat0)))

    def _to_ll(self, n: float, e: float) -> Tuple[float, float]:
        lat0, lon0 = self._ref
        return (lat0 + n / DEG_M,
                lon0 + e / (DEG_M * math.cos(math.radians(lat0))))

    def rereference(self) -> None:
        """Move the local origin to the current estimate (long flights)."""
        if not self._initialised:
            return
        lat, lon = self._to_ll(self.x[N], self.x[E])
        self._ref = (lat, lon)
        self.x[N] = self.x[E] = 0.0

    # -- predict --------------------------------------------------------

    def predict(self, t: float) -> None:
        if not self._initialised or self._t is None:
            self._t = t
            return
        dt = t - self._t
        if dt <= 0:
            return
        self._t = t
        F = np.eye(STATE_DIM)
        F[N, VN] = F[E, VE] = F[U, VU] = dt
        Q = np.zeros((STATE_DIM, STATE_DIM))
        for p, v, q in ((N, VN, self.ACCEL_PSD_H), (E, VE, self.ACCEL_PSD_H),
                        (U, VU, self.ACCEL_PSD_V)):
            Q[p, p] = q * dt ** 3 / 3.0
            Q[p, v] = Q[v, p] = q * dt ** 2 / 2.0
            Q[v, v] = q * dt
        Q[HDG, HDG] = self.HEADING_RATE_PSD * dt
        x_prior, P_prior = self.x.copy(), self.P.copy()
        self.x = F @ self.x
        self.x[HDG] %= 360.0
        self.P = F @ self.P @ F.T + Q
        if self.keep_history:
            self.history.append({"t": t, "F": F, "x_prior": x_prior,
                                 "P_prior": P_prior, "x_pred": self.x.copy(),
                                 "P_pred": self.P.copy()})

    # -- the update that the video describes ---------------------------

    def _update(self, source: str, kind: str, z: np.ndarray, H: np.ndarray,
                R: np.ndarray, angle_rows: Sequence[int] = ()) -> Decision:
        y = z - H @ self.x
        for r in angle_rows:
            y[r] = wrap_deg(y[r])
        S = H @ self.P @ H.T + R
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            d = Decision(source, kind, False, "singular innovation covariance")
            self.decisions.append(d)
            return d
        nis = float(y @ S_inv @ y)
        threshold = None
        if self.gate:
            from scipy.stats import chi2
            threshold = float(chi2.ppf(self.GATE_PROB, len(z)))
            if nis > threshold:
                d = Decision(source, kind, False,
                             f"innovation implausible: NIS {nis:.1f} > {threshold:.1f}",
                             nis, threshold)
                self.decisions.append(d)
                return d
        K = self.P @ H.T @ S_inv
        self.x = self.x + K @ y
        self.x[HDG] %= 360.0
        I_KH = np.eye(STATE_DIM) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T        # Joseph form
        d = Decision(source, kind, True, "", nis, threshold)
        self.decisions.append(d)
        return d

    # -- measurements ---------------------------------------------------

    def update_position(self, lat: float, lon: float, sigma_h_m: float,
                        source: str = "position", t: Optional[float] = None,
                        alt: Optional[float] = None,
                        sigma_v_m: Optional[float] = None) -> Decision:
        """A position fix with its per-axis 1-sigma horizontal error."""
        if not (sigma_h_m > 0 and math.isfinite(sigma_h_m)):
            d = Decision(source, "position", False, "no stated uncertainty")
            self.decisions.append(d)
            return d
        if not self._initialised:
            return self._initialise(lat, lon, sigma_h_m, source, t, alt, sigma_v_m)
        if t is not None:
            self.predict(t)
        n, e = self._to_ne(lat, lon)
        H = np.zeros((2, STATE_DIM))
        H[0, N] = H[1, E] = 1.0
        d = self._update(source, "position", np.array([n, e]), H,
                         np.diag([sigma_h_m ** 2] * 2))
        if alt is not None and sigma_v_m and sigma_v_m > 0:
            self.update_altitude(alt, sigma_v_m, source)
        self._consecutive_rejects = 0 if d.accepted else self._consecutive_rejects + 1
        return d

    def update_velocity(self, vn: float, ve: float, sigma_ms: float,
                        source: str = "velocity") -> Decision:
        """Ground velocity -- GNSS Doppler, optical flow."""
        if not self._initialised:
            d = Decision(source, "velocity", False, "no position yet")
            self.decisions.append(d)
            return d
        H = np.zeros((2, STATE_DIM))
        H[0, VN] = H[1, VE] = 1.0
        return self._update(source, "velocity", np.array([vn, ve]), H,
                            np.diag([sigma_ms ** 2] * 2))

    def update_altitude(self, alt: float, sigma_m: float,
                        source: str = "altitude") -> Decision:
        if not self._initialised:
            d = Decision(source, "altitude", False, "no position yet")
            self.decisions.append(d)
            return d
        if not self._have_alt:
            self.x[U], self.P[U, U] = alt, sigma_m ** 2
            self._have_alt = True
            d = Decision(source, "altitude", True, "initialised altitude")
            self.decisions.append(d)
            return d
        H = np.zeros((1, STATE_DIM))
        H[0, U] = 1.0
        return self._update(source, "altitude", np.array([alt]), H,
                            np.array([[sigma_m ** 2]]))

    def update_heading(self, heading_deg: float, sigma_deg: float,
                       source: str = "heading") -> Decision:
        if not self._initialised:
            d = Decision(source, "heading", False, "no position yet")
            self.decisions.append(d)
            return d
        if not self._have_heading:
            self.x[HDG], self.P[HDG, HDG] = heading_deg % 360.0, sigma_deg ** 2
            self._have_heading = True
            d = Decision(source, "heading", True, "initialised heading")
            self.decisions.append(d)
            return d
        H = np.zeros((1, STATE_DIM))
        H[0, HDG] = 1.0
        return self._update(source, "heading", np.array([heading_deg % 360.0]), H,
                            np.array([[sigma_deg ** 2]]), angle_rows=[0])

    def _initialise(self, lat, lon, sigma_h, source, t, alt, sigma_v) -> Decision:
        self._ref = (lat, lon)
        self.x[:] = 0.0
        self.P = np.diag([sigma_h ** 2, sigma_h ** 2, 1e6,
                          self.MAX_SPEED_MS ** 2, self.MAX_SPEED_MS ** 2,
                          (self.MAX_SPEED_MS / 4) ** 2, 180.0 ** 2])
        self._initialised = True
        if t is not None:
            self._t = t
        if alt is not None and sigma_v and sigma_v > 0:
            self.x[U], self.P[U, U] = alt, sigma_v ** 2
            self._have_alt = True
        d = Decision(source, "position", True,
                     "initialised from this fix and its own variance")
        self.decisions.append(d)
        return d

    # -- layer readings ---------------------------------------------------

    def step(self, readings: Sequence[LayerReading], t: float) -> List[Decision]:
        """One cycle from layer readings, all sharing clock `t`.

        Readings that are invalid, carry no position, are marked
        independent=False, or repeat a source already used this cycle are
        recorded as skipped -- never fused.
        """
        self.predict(t)
        out: List[Decision] = []
        seen = set()
        for r in readings:
            src = getattr(r, "layer_id", "?")
            raw = r.raw_data or {}
            if not r.is_valid or r.position is None:
                continue
            if self.use_independence_rule and raw.get("independent") is False:
                out.append(self._skip(src, "propagates an estimate it was given "
                                           "(independent=False)"))
                continue
            if self.use_independence_rule and src in seen:
                out.append(self._skip(src, "second measurement from the same "
                                           "source this cycle"))
                continue
            seen.add(src)
            p = r.position
            # Layers state horizontal accuracy as DRMS; per-axis sigma is
            # DRMS / sqrt(2).
            sigma_h = (p.accuracy_m or 0.0) / math.sqrt(2.0)
            out.append(self.update_position(
                p.latitude, p.longitude, sigma_h, src, None,
                p.altitude if p.altitude_accuracy_m else None,
                p.altitude_accuracy_m))
        return out

    def _skip(self, src: str, why: str) -> Decision:
        d = Decision(src, "position", False, why)
        self.decisions.append(d)
        return d

    # -- output -----------------------------------------------------------

    def estimate(self) -> Optional[Estimate]:
        """The estimate and its own uncertainty, or None before any fix."""
        if not self._initialised:
            return None
        lat, lon = self._to_ll(self.x[N], self.x[E])
        return Estimate(
            lat=lat, lon=lon,
            alt=float(self.x[U]) if self._have_alt else None,
            sigma_north_m=math.sqrt(max(self.P[N, N], 0.0)),
            sigma_east_m=math.sqrt(max(self.P[E, E], 0.0)),
            sigma_up_m=math.sqrt(max(self.P[U, U], 0.0)) if self._have_alt else None,
            velocity_ne=(float(self.x[VN]), float(self.x[VE])),
            sigma_velocity_ms=math.sqrt(max(self.P[VN, VN], self.P[VE, VE], 0.0)),
            heading_deg=float(self.x[HDG]) if self._have_heading else None,
            t=self._t or 0.0,
        )

    @property
    def possibly_diverged(self) -> bool:
        """Every position for 5 cycles running rejected: the filter, not the
        sensors, may be wrong. Reported; never silently 'fixed'."""
        return self._consecutive_rejects >= 5

    # -- offline smoothing for replays ----------------------------------

    def smooth(self) -> List[Tuple[float, np.ndarray, np.ndarray]]:
        """Rauch-Tung-Striebel smoother over a recorded run.

        OFFLINE ONLY: it uses measurements from after each moment, so it is
        the best estimate of a logged flight, never something the aircraft
        had in the air. Needs keep_history=True; each history entry must be
        followed by the post-update state, recorded by `snapshot()`.
        """
        hist = [h for h in self.history if "x_post" in h]
        if not hist:
            return []
        xs = [h["x_post"].copy() for h in hist]
        Ps = [h["P_post"].copy() for h in hist]
        for k in range(len(hist) - 2, -1, -1):
            F = hist[k + 1]["F"]
            Pp = hist[k + 1]["P_pred"]
            C = Ps[k] @ F.T @ np.linalg.inv(Pp)
            xs[k] = xs[k] + C @ (xs[k + 1] - hist[k + 1]["x_pred"])
            Ps[k] = Ps[k] + C @ (Ps[k + 1] - Pp) @ C.T
        return [(h["t"], x, P) for h, x, P in zip(hist, xs, Ps)]

    def snapshot(self) -> None:
        """Record the post-update state for the smoother."""
        if self.keep_history and self.history:
            self.history[-1]["x_post"] = self.x.copy()
            self.history[-1]["P_post"] = self.P.copy()


# ---------------------------------------------------------------------------
# Beside the other algorithms
# ---------------------------------------------------------------------------

class HonestKalmanAlgorithm:
    """Same call shape as MultiFusionEngine's algorithms: fuse_readings().

    Kept separate rather than added to that module's enum, so nothing
    already built is touched. Readings must share one clock in their
    position timestamps.
    """

    NAME = "HONEST_KALMAN"

    def __init__(self):
        self.kf = HonestKalmanFusion()

    def get_algorithm_type(self) -> str:
        return self.NAME

    def fuse_readings(self, readings: Sequence[LayerReading]):
        from upin.core.position import Position
        from upin.fusion.multi_fusion_engine import FusionResult
        t0 = time.perf_counter()
        ts = [r.position.timestamp for r in readings
              if r.is_valid and r.position is not None]
        decisions = self.kf.step(readings, max(ts) if ts else 0.0)
        est = self.kf.estimate()
        if est is None:
            return None
        return FusionResult(
            algorithm=self.NAME,
            position=Position(latitude=est.lat, longitude=est.lon,
                              altitude=est.alt, accuracy_m=est.drms_m,
                              timestamp=est.t),
            confidence=1.0 / (1.0 + est.radius95_m / 20.0),
            processing_time_ms=(time.perf_counter() - t0) * 1000.0,
            layers_used=[d.source for d in decisions if d.accepted],
            reasoning="; ".join(f"{d.source}: {d.reason}" for d in decisions
                                if not d.accepted) or "all measurements accepted",
            quality_score=1.0 / (1.0 + est.radius95_m / 20.0),
        )
