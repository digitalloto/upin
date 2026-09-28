"""
The GNSS receiver's own mathematics, with nothing borrowed from the answer.

Spec section 2 asks for GNSS and NavIC that notice when they are jammed,
notice when they are lied to, and check a returning signal before trusting
it. Everything here works from what a receiver actually has: satellite
positions from the ephemeris, pseudoranges, C/N0, and the noise floor its AGC
reports. The simulator's ground truth appears nowhere.

  first fix      Bancroft's closed-form solution (Bancroft 1985). The solver
                 this replaces seeded itself from the world's true position,
                 which a receiver switched on for the first time does not
                 have; Bancroft needs no starting guess at all.

  refinement     weighted Gauss-Newton on [x, y, z, clock], each satellite
                 weighted by the 1/sqrt(C/N0) code-tracking law, so the
                 covariance -- and the stated accuracy -- comes from the
                 geometry and the signal quality actually received.

  integrity      RAIM: the post-fit residuals, normalised by their sigmas,
                 are chi-squared with n - 4 degrees of freedom if every
                 satellite is honest. Above the threshold something is
                 wrong; with six or more satellites, exclude the worst and
                 try again (fault detection and exclusion).

  jamming        judged from the receiver's own observables -- satellites
                 tracked against satellites the almanac says are up, C/N0,
                 noise-floor rise -- not from a flag.

Coordinates use the same sphere the simulator places satellites on, so the
solve and the geometry agree; the WGS-84 ellipsoid arrives with the datum work
in spec 11.1.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

R_EARTH = 6_371_000.0
R95_PER_SIGMA = 2.4477

UERE_NOMINAL_M = {"GPS": 3.0, "NavIC": 2.0, "LEO": 1.0}
"""**Assumption.** Pseudorange error at the reference C/N0, per constellation.
Order-of-magnitude figures for single-frequency code ranging; the receiver
cannot know the true value. Replace with the receiver's datasheet figures."""

CN0_REFERENCE_DBHZ = 42.0
"""C/N0 at which a satellite's pseudorange sigma equals UERE_NOMINAL_M. Code
tracking jitter scales as 1/sqrt(C/N0), i.e. sigma grows 10^(dB/20)."""

RAIM_FALSE_ALARM = 1e-3


def lla_to_ecef(lat: float, lon: float, alt: float) -> np.ndarray:
    la, lo = math.radians(lat), math.radians(lon)
    r = R_EARTH + alt
    return np.array([r * math.cos(la) * math.cos(lo),
                     r * math.cos(la) * math.sin(lo), r * math.sin(la)])


def ecef_to_lla(x: float, y: float, z: float) -> Tuple[float, float, float]:
    r = math.sqrt(x * x + y * y + z * z)
    return (math.degrees(math.asin(z / r)), math.degrees(math.atan2(y, x)),
            r - R_EARTH)


def enu_rotation(lat: float, lon: float) -> np.ndarray:
    """Rows: east, north, up unit vectors in ECEF, at this point."""
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([
        [-math.sin(lo), math.cos(lo), 0.0],
        [-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)],
        [math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)],
    ])


def pseudorange_sigma(constellation: str, cn0_dbhz: Optional[float]) -> float:
    base = UERE_NOMINAL_M.get(constellation, 3.0)
    if cn0_dbhz is None:
        return base
    return base * 10.0 ** ((CN0_REFERENCE_DBHZ - cn0_dbhz) / 20.0)


# ---------------------------------------------------------------------------
# The solve
# ---------------------------------------------------------------------------

def bancroft(sats: np.ndarray, rho: np.ndarray) -> Optional[np.ndarray]:
    """Closed-form [x, y, z, clock] from four or more pseudoranges.

    With the Lorentz inner product <a, b> = a1b1 + a2b2 + a3b3 - a4b4, each
    satellite gives <s_i - r, s_i - r> = 0 for s_i = (sat, rho) and
    r = (receiver, clock). That is linear in r apart from one scalar, which
    satisfies a quadratic. Of its two roots, the one near the Earth's surface
    is the receiver.
    """
    n = len(rho)
    if n < 4:
        return None
    B = np.column_stack([sats, rho])
    M = np.diag([1.0, 1.0, 1.0, -1.0])
    lorentz = lambda a, b: float(a @ M @ b)
    a = np.array([0.5 * lorentz(B[i], B[i]) for i in range(n)])
    e = np.ones(n)
    Bp = np.linalg.pinv(B)
    u, v = Bp @ a, Bp @ e
    A, Bq, C = lorentz(v, v), 2.0 * (lorentz(u, v) - 1.0), lorentz(u, u)
    candidates = []
    if abs(A) < 1e-18:
        if abs(Bq) > 1e-18:
            candidates.append(-C / Bq)
    else:
        disc = Bq * Bq - 4.0 * A * C
        if disc < 0:
            return None
        root = math.sqrt(disc)
        candidates += [(-Bq + root) / (2 * A), (-Bq - root) / (2 * A)]
    best = None
    for lam in candidates:
        r = M @ (u + lam * v)
        err = abs(np.linalg.norm(r[:3]) - R_EARTH)
        if best is None or err < best[0]:
            best = (err, r)
    return None if best is None else best[1]


@dataclass
class GNSSSolution:
    lat: float
    lon: float
    alt: float
    clock_m: float
    sigma_east_m: float
    sigma_north_m: float
    sigma_up_m: float
    hdop: float
    vdop: float
    pdop: float
    satellites: int
    raim_statistic: Optional[float]
    raim_threshold: Optional[float]
    raim_ok: Optional[bool]              # None when n == 4: nothing to test
    excluded: List[str] = field(default_factory=list)
    mean_cn0_dbhz: Optional[float] = None

    @property
    def drms_m(self) -> float:
        return math.hypot(self.sigma_east_m, self.sigma_north_m)

    @property
    def radius95_m(self) -> float:
        return R95_PER_SIGMA * math.sqrt(
            (self.sigma_east_m ** 2 + self.sigma_north_m ** 2) / 2.0)


def _solve_subset(sats: np.ndarray, rho: np.ndarray,
                  sig: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray, float, np.ndarray]]:
    x = bancroft(sats, rho)
    if x is None or not np.all(np.isfinite(x)):
        return None
    W = np.diag(1.0 / sig ** 2)
    H = None
    for _ in range(10):
        d = x[:3] - sats
        r = np.linalg.norm(d, axis=1)
        if np.any(r < 1.0):
            return None
        H = np.column_stack([d / r[:, None], np.ones(len(rho))])
        resid = rho - (r + x[3])
        N = H.T @ W @ H
        try:
            dx = np.linalg.solve(N, H.T @ W @ resid)
        except np.linalg.LinAlgError:
            return None
        x = x + dx
        if np.linalg.norm(dx[:3]) < 1e-4:
            break
    r = np.linalg.norm(x[:3] - sats, axis=1)
    resid = rho - (r + x[3])
    try:
        cov = np.linalg.inv(H.T @ W @ H)
        Q = np.linalg.inv(H.T @ H)
    except np.linalg.LinAlgError:
        return None
    stat = float(np.sum((resid / sig) ** 2))
    return x, cov, stat, Q


def solve(pseudoranges: Sequence[Dict], constellation: str,
          fde: bool = True) -> Tuple[Optional[GNSSSolution], str]:
    """Position from pseudoranges, with RAIM and exclusion. (solution, why)."""
    obs = [p for p in pseudoranges
           if p.get("pseudorange_m") is not None and p.get("sat_ecef") is not None]
    n = len(obs)
    if n < 4:
        return None, f"{n} satellites tracked, 4 needed"

    sats = np.array([p["sat_ecef"] for p in obs], dtype=float)
    rho = np.array([p["pseudorange_m"] for p in obs], dtype=float)
    cn0 = [p.get("cn0_dbhz") for p in obs]
    sig = np.array([pseudorange_sigma(constellation, c) for c in cn0])
    ids = [str(p.get("sat_id", i)) for i, p in enumerate(obs)]

    from scipy.stats import chi2

    def attempt(mask):
        out = _solve_subset(sats[mask], rho[mask], sig[mask])
        if out is None:
            return None
        dof = int(mask.sum()) - 4
        thr = float(chi2.ppf(1.0 - RAIM_FALSE_ALARM, dof)) if dof > 0 else None
        return out, dof, thr

    full = np.ones(n, dtype=bool)
    got = attempt(full)
    if got is None:
        return None, "solution did not converge"
    (x, cov, stat, Q), dof, thr = got
    excluded: List[str] = []

    if thr is not None and stat > thr:
        if not (fde and n >= 6):
            return None, (f"RAIM fault: residual statistic {stat:.1f} > "
                          f"{thr:.1f} and too few satellites to exclude one")
        best = None
        for i in range(n):
            m = full.copy()
            m[i] = False
            g = attempt(m)
            if g is None:
                continue
            (xi, ci, si, Qi), di, ti = g
            if ti is not None and si <= ti and (best is None or si < best[0]):
                best = (si, i, g)
        if best is None:
            return None, (f"RAIM fault not isolable: statistic {stat:.1f} > "
                          f"{thr:.1f} with every single exclusion")
        _, i, ((x, cov, stat, Q), dof, thr) = best
        excluded = [ids[i]]
        keep = full.copy()
        keep[i] = False
        cn0 = [c for c, k in zip(cn0, keep) if k]

    lat, lon, alt = ecef_to_lla(*x[:3])
    R = enu_rotation(lat, lon)
    cov_enu = R @ cov[:3, :3] @ R.T
    Q_enu = R @ Q[:3, :3] @ R.T
    finite_cn0 = [c for c in cn0 if c is not None]
    return GNSSSolution(
        lat=lat, lon=lon, alt=alt, clock_m=float(x[3]),
        sigma_east_m=math.sqrt(max(cov_enu[0, 0], 0.0)),
        sigma_north_m=math.sqrt(max(cov_enu[1, 1], 0.0)),
        sigma_up_m=math.sqrt(max(cov_enu[2, 2], 0.0)),
        hdop=math.sqrt(max(Q_enu[0, 0] + Q_enu[1, 1], 0.0)),
        vdop=math.sqrt(max(Q_enu[2, 2], 0.0)),
        pdop=math.sqrt(max(np.trace(Q_enu), 0.0)),
        satellites=dof + 4, raim_statistic=stat if thr is not None else None,
        raim_threshold=thr, raim_ok=(stat <= thr) if thr is not None else None,
        excluded=excluded,
        mean_cn0_dbhz=float(np.mean(finite_cn0)) if finite_cn0 else None,
    ), ""


# ---------------------------------------------------------------------------
# Jamming, judged from the receiver's own observables
# ---------------------------------------------------------------------------

class Reception:
    CLEAR = "clear"
    DEGRADED = "degraded"
    JAMMED = "jammed"


JAM_NOISE_RISE_DB = 10.0
"""Noise-floor rise at which a receiver that has lost lock is called jammed
rather than merely obstructed. An obstruction removes satellites without
raising the noise floor; a jammer raises it."""

DEGRADED_NOISE_RISE_DB = 3.0


def judge_reception(quality: Optional[Dict]) -> Tuple[str, str]:
    """(state, reason) from visible, tracked and noise-floor rise."""
    if not quality:
        return Reception.DEGRADED, "no receiver quality report"
    visible = quality.get("visible", 0)
    tracked = quality.get("tracked", 0)
    rise = float(quality.get("noise_floor_rise_db") or 0.0)
    if tracked < 4 and visible >= 4 and rise >= JAM_NOISE_RISE_DB:
        return Reception.JAMMED, (f"{tracked} of {visible} satellites tracked, "
                                  f"noise floor up {rise:.0f} dB")
    if rise >= DEGRADED_NOISE_RISE_DB or (visible and tracked < 0.75 * visible):
        return Reception.DEGRADED, (f"{tracked} of {visible} tracked, noise floor "
                                    f"up {rise:.1f} dB")
    return Reception.CLEAR, ""


def consistency(fix_lat: float, fix_lon: float, fix_sigma_e: float,
                fix_sigma_n: float, ref_lat: float, ref_lon: float,
                ref_sigma: float) -> Tuple[float, float]:
    """(statistic, distance_m): chi-squared, 2 dof, fix against a reference."""
    dn = (fix_lat - ref_lat) * math.pi / 180.0 * R_EARTH
    de = ((fix_lon - ref_lon) * math.pi / 180.0 * R_EARTH
          * math.cos(math.radians((fix_lat + ref_lat) / 2.0)))
    stat = (dn * dn / (fix_sigma_n ** 2 + ref_sigma ** 2)
            + de * de / (fix_sigma_e ** 2 + ref_sigma ** 2))
    return stat, math.hypot(dn, de)
