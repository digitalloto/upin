"""
Wind Learner -- measure the wind while GNSS still works, keep it when it stops.

The Map-Click Guided layer flies toward a point by pointing the nose so that
airspeed plus wind comes out along the line to the target. Without the wind
it points straight at the target and is blown off course, and in a
GPS-denied aircraft nothing tells it so. So the wind has to be learned
beforehand, while GNSS is healthy, and frozen at the moment GNSS is lost
(spec section 1.3).

THE CHICKEN AND THE EGG

Wind is ground velocity minus air velocity. Ground velocity comes from GNSS.
Air velocity is heading times airspeed -- and airspeed at a given tilt is
exactly what the Speed Learner is trying to learn, which it can only do if
it already knows the wind. Each learner needs the other's answer first.

The way out is the wind triangle. At steady state a multirotor's airspeed
depends only on its tilt, not on which way it points. Fly the same tilt on
several headings and every sample obeys

    v_north = w_north + s(tilt) * cos(heading)
    v_east  = w_east  + s(tilt) * sin(heading)

which is linear in the unknowns: the two wind components and one airspeed
per tilt. One weighted least-squares solve gives all of them at once, and
its covariance says how well each is determined.

WHERE IT REFUSES

On a single heading the wind triangle is degenerate: a headwind and a slower
airspeed produce identical ground velocity, and no amount of data separates
them. The learner checks for this -- heading diversity and the conditioning
of the solve -- and declines rather than returning the least-squares answer
to an unanswerable question. The honest message is "turn": a few seconds on
two or three headings makes the wind observable.

It also ignores samples taken while accelerating (the steady-state
assumption is false then), and once frozen it ignores everything until told
GNSS is back.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class FlightSample:
    """One observation of the aircraft in flight while GNSS is healthy."""
    t: float                 # seconds, any monotonic clock
    heading_deg: float       # where the nose points (compass), degrees true
    tilt_deg: float          # forward tilt, from the attitude estimate
    v_north: float           # GNSS ground velocity, m/s
    v_east: float
    v_sigma: float = 0.1     # GNSS velocity 1-sigma, m/s, per component


@dataclass
class WindEstimate:
    """The wind, with how well it is known and where it came from."""
    north_ms: float
    east_ms: float
    sigma_ms: float                  # 1-sigma per component
    samples: int
    span_s: float
    heading_diversity: float         # 0 = one heading, 1 = evenly spread
    airspeeds: Dict[float, float]    # tilt-bin centre (deg) -> airspeed (m/s)
    frozen: bool = False
    frozen_at: Optional[float] = None
    seconds_frozen: float = 0.0
    source: str = "learned"
    # Turbulence, measured rather than assumed: the wind triangle's residuals
    # are what the steady model could not explain, and in flight that is
    # mostly gusts. Their spread and correlation time let a dead-reckoning
    # layer budget for the drift gusts will cause once GNSS is gone.
    gust_sigma_ms: float = 0.0
    gust_tau_s: float = 0.0
    # How far to trust the gust measurement itself. A learning window holds
    # only so many independent looks at the turbulence -- about T / (2 tau) --
    # and a variance measured from few looks is noisy. This is the one-sided
    # 95% upper bound on the gust power, as a factor on the point estimate:
    # nu / chi2_0.05(nu). Short learning costs confidence, as it should.
    gust_looks: float = 0.0
    gust_power_upper_factor: float = 1.0

    @property
    def vector_ned(self) -> np.ndarray:
        return np.array([self.north_ms, self.east_ms, 0.0])

    @property
    def speed_ms(self) -> float:
        return math.hypot(self.north_ms, self.east_ms)

    @property
    def toward_deg(self) -> float:
        """Direction the wind blows toward, degrees true."""
        return math.degrees(math.atan2(self.east_ms, self.north_ms)) % 360.0


class WindLearner:
    """Learns wind from GNSS velocity, heading and tilt; freezes on GNSS loss."""

    MIN_SAMPLES = 20
    MIN_HEADING_DIVERSITY = 0.25
    """1 minus the mean resultant length of the heading unit vectors. Zero on
    a straight line, near one on a full circle. A quarter corresponds to
    headings spread over roughly ninety degrees -- enough that the wind
    triangle is well posed rather than merely solvable."""

    SETTLE_S = 12.0
    """Seconds after a commanded change before a sample counts as steady.

    After a turn or a tilt change the aircraft approaches its new airspeed
    with a time constant of v_terminal / (g tan(tilt)) -- about 4 s at 5
    degrees for a typical quadrotor. Three time constants gets within a few
    percent. An acceleration threshold cannot do this job: at low tilt the
    maximum acceleration is itself small, so the tail of the transient looks
    steady while the airspeed is still several percent short. That biased
    the learned table low at 5 degrees before this clock replaced it."""

    MAX_STEADY_ACCEL = 1.0
    """m/s^2. A coarse guard for gross disturbances only; settling is judged
    by SETTLE_S."""

    HEADING_CHANGE_DEG = 5.0
    """A heading change larger than this restarts the settle clock."""

    WIND_CHANGE_MS_PER_MIN = 0.15
    """How fast a frozen wind estimate is assumed to go stale.

    **An assumption, not a measurement.** Wind does change, and a frozen
    estimate that never widened would claim it does not. 0.15 m/s per minute
    is a mean-wind change of about 1.5 m/s over ten minutes, typical of the
    lower boundary layer. It was 0.5 until the guided layer showed what that
    costs: integrated over a flight it grows position error with the square
    of time, and made the stated circle ten times larger than the real error.
    Replace it with a figure from the operating area's own records."""

    def __init__(self, window_s: float = 180.0, tilt_bin_deg: float = 2.5,
                 wind_change_ms_per_min: Optional[float] = None):
        self.window_s = window_s
        self.tilt_bin_deg = tilt_bin_deg
        if wind_change_ms_per_min is not None:
            self.WIND_CHANGE_MS_PER_MIN = wind_change_ms_per_min
        self._samples: List[FlightSample] = []
        self._last_seen: Optional[FlightSample] = None
        self._frozen: Optional[WindEstimate] = None
        self._rejected_unsteady = 0
        self._settled_since: Optional[float] = None

    # -- feeding ----------------------------------------------------

    def add_sample(self, sample: FlightSample) -> bool:
        """Offer one sample. Returns True if it was kept."""
        if self._frozen is not None:
            return False
        prev, self._last_seen = self._last_seen, sample
        if prev is None:
            self._settled_since = sample.t
            return False          # need a predecessor to judge steadiness
        dt = sample.t - prev.t
        if dt <= 0:
            return False
        turned = abs((sample.heading_deg - prev.heading_deg + 180.0) % 360.0
                     - 180.0) > self.HEADING_CHANGE_DEG
        retilted = self._bin(sample.tilt_deg) != self._bin(prev.tilt_deg)
        if turned or retilted:
            self._settled_since = sample.t
        accel = math.hypot(sample.v_north - prev.v_north,
                           sample.v_east - prev.v_east) / dt
        settled = sample.t - (self._settled_since or sample.t) >= self.SETTLE_S
        if not settled or accel > self.MAX_STEADY_ACCEL:
            self._rejected_unsteady += 1
            return False
        self._samples.append(sample)
        self._expire(sample.t)
        return True

    def gnss_lost(self, now: float) -> Optional[WindEstimate]:
        """Freeze the last good estimate. Called at the moment GNSS goes.

        Returns the frozen estimate, or None if there was nothing good to
        freeze -- in which case the guided layer has no wind to use, and
        must say so rather than assume calm.
        """
        est = self._solve()
        if est is None:
            self._frozen = WindEstimate(0.0, 0.0, float("inf"), 0, 0.0, 0.0,
                                        {}, frozen=True, frozen_at=now,
                                        source="none")
            return None
        est.frozen = True
        est.frozen_at = now
        self._frozen = est
        return est

    def gnss_restored(self) -> None:
        """Resume learning. The caller has validated the returning GNSS."""
        self._frozen = None
        self._samples.clear()
        self._last_seen = None

    # -- reading ----------------------------------------------------

    def estimate(self, now: Optional[float] = None) -> Optional[WindEstimate]:
        """The current wind estimate, or None if it is not known."""
        if self._frozen is not None:
            if self._frozen.source == "none":
                return None
            t = 0.0 if now is None else max(0.0, now - self._frozen.frozen_at)
            grown = self.WIND_CHANGE_MS_PER_MIN * t / 60.0
            f = self._frozen
            return WindEstimate(
                f.north_ms, f.east_ms, math.hypot(f.sigma_ms, grown),
                f.samples, f.span_s, f.heading_diversity, dict(f.airspeeds),
                frozen=True, frozen_at=f.frozen_at, seconds_frozen=t,
                source=f.source, gust_sigma_ms=f.gust_sigma_ms,
                gust_tau_s=f.gust_tau_s, gust_looks=f.gust_looks,
                gust_power_upper_factor=f.gust_power_upper_factor)
        return self._solve()

    def why_not(self) -> str:
        """If estimate() is None, the reason in words."""
        if self._frozen is not None and self._frozen.source == "none":
            return ("GNSS was lost before the wind was learned; there is no "
                    "estimate to freeze")
        if len(self._samples) < self.MIN_SAMPLES:
            return (f"{len(self._samples)} steady samples, need "
                    f"{self.MIN_SAMPLES}")
        div = self._heading_diversity(self._samples)
        if div < self.MIN_HEADING_DIVERSITY:
            return (f"heading diversity {div:.2f}, need "
                    f"{self.MIN_HEADING_DIVERSITY}: on one heading a headwind "
                    f"and a lower airspeed are indistinguishable -- turn")
        if self._solve() is None:
            return "the wind-triangle solve is ill-conditioned"
        return ""

    def cross_check(self, fc_wind_ned: Optional[Sequence[float]],
                    fc_sigma_ms: float = 1.0,
                    now: Optional[float] = None) -> Dict:
        """Compare against the flight controller's own wind estimate.

        The spec's second source (1.3). A second opinion, not a replacement:
        UPIN does not know the error of the flight controller's estimate, so
        it is never used as the primary.
        """
        est = self.estimate(now)
        if fc_wind_ned is None or est is None:
            return {"checked": False,
                    "reason": "no flight-controller estimate" if fc_wind_ned is None
                    else self.why_not()}
        gap = math.hypot(est.north_ms - fc_wind_ned[0],
                         est.east_ms - fc_wind_ned[1])
        allowed = 3.0 * math.hypot(est.sigma_ms, fc_sigma_ms)
        return {"checked": True, "disagreement_ms": gap, "allowed_ms": allowed,
                "agree": gap <= allowed}

    @property
    def frozen(self) -> bool:
        return self._frozen is not None

    @property
    def samples(self) -> int:
        return len(self._samples)

    @property
    def steady_samples(self) -> List[FlightSample]:
        """The samples currently inside the window, for the Speed Learner."""
        return list(self._samples)

    @property
    def rejected_unsteady(self) -> int:
        return self._rejected_unsteady

    # -- the solve --------------------------------------------------

    def _bin(self, tilt_deg: float) -> float:
        return round(tilt_deg / self.tilt_bin_deg) * self.tilt_bin_deg

    def _expire(self, now: float) -> None:
        cutoff = now - self.window_s
        if self._samples and self._samples[0].t < cutoff:
            self._samples = [s for s in self._samples if s.t >= cutoff]

    MAX_CORRELATION_LAG_S = 60.0

    @staticmethod
    def _nominal_dt(samples) -> float:
        if len(samples) < 2:
            return 0.0
        return float(np.median(np.diff([x.t for x in samples])))

    @classmethod
    def _integrated_time(cls, resid: np.ndarray, samples) -> tuple:
        """Integrated autocorrelation time of the residuals, and their spread.

        tau_int = dt (1/2 + sum over lags of rho(k)), summed until the
        correlation dies out. For a first-order gust process it equals the
        correlation time; for white noise it is dt/2. It replaces an estimate
        from the lag-one correlation alone, which was fragile in two ways:
        at half-second sampling an 8-second gust has rho near 0.94, where a
        small error in rho is a large error in tau; and pairs were taken
        across the twelve-second gaps at every turn, whose near-zero
        correlation dragged the estimate down. That made the wind's stated
        sigma up to three times too small in gusty air.

        Correlation is computed only between samples that really are k
        intervals apart, inside unbroken runs. Worst axis is reported.
        """
        if len(samples) < 4:
            return 0.0, 0.0
        t = np.array([x.t for x in samples])
        dt = float(np.median(np.diff(t)))
        if dt <= 0:
            return 0.0, 0.0
        breaks = np.where(np.diff(t) > 1.5 * dt)[0] + 1
        runs = np.split(np.arange(len(samples)), breaks)
        max_k = max(1, int(cls.MAX_CORRELATION_LAG_S / dt))

        best_tau, best_sigma = 0.0, 0.0
        for comp in (resid[0::2], resid[1::2]):
            x = comp - comp.mean()
            c0 = float(x @ x) / len(x)
            if c0 <= 0:
                continue
            total = 0.0
            for k in range(1, max_k + 1):
                num, pairs = 0.0, 0
                for r in runs:
                    if len(r) > k:
                        seg = x[r]
                        num += float(seg[:-k] @ seg[k:])
                        pairs += len(seg) - k
                if pairs < 10:
                    break
                rho = num / pairs / c0
                if rho <= 0.05:
                    break
                total += rho
            tau = dt * (0.5 + total)
            if tau * c0 > best_tau * best_sigma ** 2:
                best_tau, best_sigma = tau, math.sqrt(c0)
        return best_tau, best_sigma

    @staticmethod
    def _heading_diversity(samples: Sequence[FlightSample]) -> float:
        h = np.radians([s.heading_deg for s in samples])
        return float(1.0 - math.hypot(np.mean(np.cos(h)), np.mean(np.sin(h))))

    def _solve(self) -> Optional[WindEstimate]:
        s = self._samples
        if len(s) < self.MIN_SAMPLES:
            return None
        diversity = self._heading_diversity(s)
        if diversity < self.MIN_HEADING_DIVERSITY:
            return None

        bins = sorted({self._bin(x.tilt_deg) for x in s})
        col = {b: 2 + i for i, b in enumerate(bins)}
        n, k = len(s), 2 + len(bins)
        A = np.zeros((2 * n, k))
        y = np.zeros(2 * n)
        w = np.zeros(2 * n)
        for i, x in enumerate(s):
            h = math.radians(x.heading_deg)
            c = col[self._bin(x.tilt_deg)]
            A[2 * i, 0] = 1.0
            A[2 * i, c] = math.cos(h)
            A[2 * i + 1, 1] = 1.0
            A[2 * i + 1, c] = math.sin(h)
            y[2 * i], y[2 * i + 1] = x.v_north, x.v_east
            w[2 * i] = w[2 * i + 1] = 1.0 / max(x.v_sigma, 1e-6) ** 2

        AtW = A.T * w
        N = AtW @ A
        if not np.isfinite(np.linalg.cond(N)) or np.linalg.cond(N) > 1e8:
            return None
        xhat = np.linalg.solve(N, AtW @ y)

        resid = y - A @ xhat
        dof = max(1, 2 * n - k)
        # A-posteriori variance factor: if the data scatter more than the
        # stated GNSS sigma (gusts, model error), the covariance says so.
        scale = max(1.0, float(resid @ (w * resid)) / dof)
        # Correlated errors. Gusts last seconds; samples arrive every half
        # second, so neighbouring residuals are nearly the same number and the
        # solve would otherwise count one gust thirty times. An AR(1) inflation
        # of (1 + rho) / (1 - rho), from the residuals' own lag-one
        # correlation, converts the sample count into the number of
        # independent looks the data actually contain. Without it the stated
        # sigma was about five times too small in a 1.5 m/s gust field.
        tau_int, gust_sigma = self._integrated_time(resid, s)
        dt_nom = self._nominal_dt(s)
        scale *= max(1.0, 2.0 * tau_int / dt_nom) if dt_nom > 0 else 1.0
        cov = np.linalg.inv(N) * scale
        sigma = math.sqrt(max(cov[0, 0], cov[1, 1]))

        airspeeds = {b: float(xhat[col[b]]) for b in bins}
        gust_tau = tau_int
        looks, upper = self._confidence_in_gusts(n, dt_nom, tau_int)
        if any(v <= 0 for v in airspeeds.values()):
            return None         # a negative airspeed is a failed solve, not wind

        return WindEstimate(
            north_ms=float(xhat[0]), east_ms=float(xhat[1]), sigma_ms=sigma,
            samples=n, span_s=s[-1].t - s[0].t, heading_diversity=diversity,
            airspeeds=airspeeds, gust_sigma_ms=gust_sigma, gust_tau_s=gust_tau,
            gust_looks=looks, gust_power_upper_factor=upper)

    @staticmethod
    def _confidence_in_gusts(n: int, dt: float, tau: float) -> tuple:
        """Independent looks at the turbulence, and the 95% upper factor."""
        if n < 2 or dt <= 0 or tau <= 0:
            return float(n), 1.0
        looks = max(1.0, n * dt / (2.0 * max(tau, dt / 2.0)))
        from scipy.stats import chi2
        return looks, max(1.0, looks / float(chi2.ppf(0.05, looks)))
