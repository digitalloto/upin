"""
Layer 150 -- LEO Doppler anchor (leodoppler_a21).

A satellite in low orbit passes overhead in about ten minutes. Its received
carrier slides from high to low as it approaches and recedes, and the shape
of that slide depends on where the receiver stands relative to the orbit.
With the orbit known (a published TLE) the Doppler curve of one pass gives a
position: the method of the Transit system before GPS, now done with a
cheap software radio on any satellite that still transmits a steady
carrier (Orbcomm's VHF downlinks are the usual choice; the NOAA 137 MHz
weather satellites were retired in 2025).

THE FIT
    unknowns   receiver latitude, longitude, the radio's frequency offset
               and its drift (a cheap oscillator is off by about a part per
               million and wanders)
    model      f(t) = f_c (1 - range_rate / c) + offset + drift (t - t_mid)
    solve      weighted Gauss-Newton from a prior position; sigma from the
               covariance, in metres
    altitude   from the barometer (the fit is poorly conditioned in height)

THE AMBIGUITY, stated
    A Doppler curve is the same for the mirror position across the
    satellite's ground track. The prior chooses the side. If the prior is
    too weak to choose, the layer declines rather than guess. Along-track
    position is also weaker than cross-track; the covariance says by how
    much. And a wrong satellite (or a wrong phase in the orbit) fits
    perfectly for a receiver shifted along the track: the residuals cannot
    tell, so a fix far from the prior is refused.

WHAT IT CANNOT DO
    One fix per pass, passes an hour or two apart. The receiver must be
    nearly still, or its motion over the pass must be supplied with a
    sigma. Accuracy is hundreds of metres to kilometres with a cheap
    oscillator and a single pass -- a coarse anchor on a band GNSS jammers
    do not touch, not navigation. A stale orbit (old TLE) shifts the fix;
    orbits older than MAX_TLE_AGE_DAYS decline. A spoofer could fake a
    Doppler curve. Nothing here has met a real radio.

Orbit propagation: TLEs through the MIT-licensed `sgp4` package (optional,
lazy import; declines without it), or an analytic circular orbit for tests
and simulation.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import (DataInput, Hardware, ReferenceData,
                                           SensorRequirement)

C = 299_792_458.0
MU = 3.986004418e14
OMEGA_E = 7.2921159e-5
A_WGS84, F_WGS84 = 6378137.0, 1 / 298.257223563
DEG_M = 111_320.0


# -- frames -------------------------------------------------------------------

def julian_date(t_unix: float) -> float:
    return t_unix / 86400.0 + 2440587.5


def gmst_rad(t_unix: float) -> float:
    d = julian_date(t_unix) - 2451545.0
    return math.radians((280.46061837 + 360.98564736629 * d) % 360.0)


def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> np.ndarray:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    e2 = F_WGS84 * (2 - F_WGS84)
    n = A_WGS84 / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return np.array([(n + alt_m) * math.cos(lat) * math.cos(lon),
                     (n + alt_m) * math.cos(lat) * math.sin(lon),
                     (n * (1 - e2) + alt_m) * math.sin(lat)])


def ecef_to_eci(r_ecef: np.ndarray, t_unix: float) -> Tuple[np.ndarray, np.ndarray]:
    """Position and velocity of a point fixed to the Earth, in the inertial
    frame (rotation by Greenwich sidereal time; the Earth's spin gives it a
    velocity)."""
    th = gmst_rad(t_unix)
    c, s = math.cos(th), math.sin(th)
    R = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    r = R @ r_ecef
    v = np.cross(np.array([0.0, 0.0, OMEGA_E]), r)
    return r, v


def sub_point_and_track(orbit, t_unix: float) -> Tuple[float, float, Tuple[float, float]]:
    """The satellite's ground point (lat, lon) and the horizontal direction
    of its track (east, north unit vector) at time t."""
    r_eci, v_eci = orbit.state_eci(t_unix)
    th = gmst_rad(t_unix)
    c, s = math.cos(th), math.sin(th)
    R = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])      # ECI -> ECEF
    r = R @ r_eci
    v = R @ (v_eci - np.cross(np.array([0.0, 0.0, OMEGA_E]), r_eci))
    lat = math.atan2(r[2], math.hypot(r[0], r[1]))
    lon = math.atan2(r[1], r[0])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)])
    d = np.array([float(np.dot(v, east)), float(np.dot(v, north))])
    d = d / max(np.linalg.norm(d), 1e-9)
    return math.degrees(lat), math.degrees(lon), (float(d[0]), float(d[1]))


def mirror_across_track(lat, lon, orbit, t_unix) -> Tuple[float, float]:
    """The point on the other side of the satellite's ground track that shows
    the same Doppler curve."""
    slat, slon, (de, dn) = sub_point_and_track(orbit, t_unix)
    coslat = math.cos(math.radians(slat))
    pe = (lon - slon) * DEG_M * coslat
    pn = (lat - slat) * DEG_M
    along = pe * de + pn * dn
    me, mn = 2 * along * de - pe, 2 * along * dn - pn
    return slat + mn / DEG_M, slon + me / (DEG_M * coslat)


def enu_elevation_deg(lat_deg, lon_deg, alt_m, r_sat_eci, t_unix) -> float:
    r_rx, _ = ecef_to_eci(geodetic_to_ecef(lat_deg, lon_deg, alt_m), t_unix)
    d = r_sat_eci - r_rx
    up = r_rx / np.linalg.norm(r_rx)          # spherical up is enough here
    return math.degrees(math.asin(float(np.dot(d, up) / np.linalg.norm(d))))


# -- orbits -------------------------------------------------------------------

class CircularOrbit:
    """An analytic circular orbit in the inertial frame. For tests and
    simulation: a self-consistent model, not a real satellite."""

    def __init__(self, altitude_m: float, inclination_deg: float, raan_deg: float,
                 phase_deg: float, epoch_unix: float, name: str = "simulated LEO"):
        self.a = A_WGS84 + altitude_m
        self.n = math.sqrt(MU / self.a ** 3)
        i, O = math.radians(inclination_deg), math.radians(raan_deg)
        self.P = np.array([math.cos(O), math.sin(O), 0.0])
        self.Q = np.array([-math.sin(O) * math.cos(i), math.cos(O) * math.cos(i), math.sin(i)])
        self.u0, self.t0 = math.radians(phase_deg), epoch_unix
        self.name = name
        self.age_days = 0.0

    def state_eci(self, t_unix: float) -> Tuple[np.ndarray, np.ndarray]:
        u = self.u0 + self.n * (t_unix - self.t0)
        r = self.a * (math.cos(u) * self.P + math.sin(u) * self.Q)
        v = self.a * self.n * (-math.sin(u) * self.P + math.cos(u) * self.Q)
        return r, v


class TleOrbit:
    """A real satellite from its two-line element set, through the sgp4
    package (MIT). Declines cleanly when the package is missing."""

    def __init__(self, line1: str, line2: str, name: str = "", now_unix: Optional[float] = None):
        try:
            from sgp4.api import Satrec, jday  # noqa: WPS433 -- lazy by design
        except ImportError as exc:
            raise RuntimeError("the sgp4 package is not installed (pip install -e '.[sdr]')") from exc
        self._jday = jday
        self.sat = Satrec.twoline2rv(line1, line2)
        self.name = name or line1[2:7].strip()
        epoch_jd = self.sat.jdsatepoch + self.sat.jdsatepochF
        self.age_days = (julian_date(now_unix) - epoch_jd) if now_unix is not None else 0.0

    def state_eci(self, t_unix: float) -> Tuple[np.ndarray, np.ndarray]:
        jd = julian_date(t_unix)
        err, r, v = self.sat.sgp4(math.floor(jd), jd - math.floor(jd))
        if err != 0:
            raise ValueError(f"sgp4 error {err}")
        return np.array(r) * 1000.0, np.array(v) * 1000.0     # TEME ~ ECI, km -> m


# -- the layer ----------------------------------------------------------------

@dataclass
class DopplerObservation:
    t_unix: float
    freq_hz: float
    sigma_hz: float


class LeoDopplerLayer(NavigationLayer):
    """A coarse, GNSS-free position from one satellite pass's Doppler curve."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("software-defined radio and antenna for the satellite's band",
                     why="records the carrier through the pass",
                     typical_part="RTL-SDR dongle with a VHF antenna (Orbcomm 137-138 MHz)"),
        ],
        inputs=[
            DataInput("orbit", feed_method="set_orbit", units="TLE through sgp4, or a model",
                      why="where the satellite is at each moment"),
            DataInput("Doppler observations", feed_method="feed_doppler",
                      units="unix s, Hz, 1-sigma Hz", why="the carrier frequency through the pass"),
            DataInput("prior position", feed_method="set_prior", units="degrees, 1-sigma m",
                      why="chooses the side of the ground track; the fit starts here"),
            DataInput("altitude", feed_method="set_altitude", units="m MSL, 1-sigma m"),
            DataInput("receiver motion (optional)", feed_method="set_motion",
                      units="m/s north/east, 1-sigma", why="a moving receiver must say so"),
        ],
        reference_data=[
            ReferenceData("two-line elements", why="the satellite's orbit",
                          source="public TLE sets, fetched before the mission"),
        ],
        preconditions=("a pass of at least MIN_PASS_S with MIN_POINTS observations",
                       "maximum elevation at least MIN_MAX_ELEV_DEG",
                       "orbit no older than MAX_TLE_AGE_DAYS"),
        notes="One coarse fix per pass on a band GNSS jammers do not touch. The "
              "mirror position across the track also fits; the prior decides.",
    )

    MIN_PASS_S = 120.0
    MIN_POINTS = 20
    MIN_MAX_ELEV_DEG = 15.0
    MAX_TLE_AGE_DAYS = 7.0
    """**Assumption.** Beyond this a TLE's along-track error reaches
    kilometres and the fix is no longer an anchor."""
    MAX_SPEED_MS = 1.0
    MAX_ITER = 25
    CHI2_LIMIT = 4.0
    """Weighted residual variance above this means the model does not fit
    the data (wrong satellite, wrong orbit, interference): decline."""
    MAX_PRIOR_SIGMAS = 5.0
    """A fix further than this many prior sigmas from the prior is refused.
    A wrong satellite phase fits a receiver shifted along the track
    perfectly -- the residuals cannot tell; only the prior can."""

    def __init__(self):
        super().__init__(
            layer_id="leodoppler_a21", layer_number=150,
            name="LEO Doppler Anchor (software radio)",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION],
            description="A coarse, GNSS-free position from the Doppler curve of one "
                        "low-orbit satellite pass on a cheap software radio.",
        )
        self._orbit = None
        self._carrier_hz: Optional[float] = None
        self._obs: List[DopplerObservation] = []
        self._prior: Optional[Tuple[float, float, float]] = None
        self._alt: Optional[Tuple[float, float]] = None
        self._motion: Optional[Tuple[float, float, float]] = None
        self.last: Optional[dict] = None

    # -- contract -------------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.2

    # -- inputs ---------------------------------------------------------------

    def set_orbit(self, orbit, carrier_hz: float) -> None:
        self._orbit, self._carrier_hz = orbit, carrier_hz
        self._obs = []

    def feed_doppler(self, t_unix: float, freq_hz: float, sigma_hz: float) -> None:
        if sigma_hz > 0 and math.isfinite(freq_hz):
            self._obs.append(DopplerObservation(t_unix, freq_hz, sigma_hz))

    def clear(self) -> None:
        self._obs = []

    def set_prior(self, lat: float, lon: float, sigma_m: float) -> None:
        self._prior = (lat, lon, sigma_m)

    def set_altitude(self, alt_msl_m: float, sigma_m: float) -> None:
        self._alt = (alt_msl_m, sigma_m)

    def set_motion(self, vn: float, ve: float, sigma_ms: float) -> None:
        self._motion = (vn, ve, sigma_ms)

    # -- the model --------------------------------------------------------------

    def _predict(self, lat, lon, alt, offset, drift, ts, t_mid) -> np.ndarray:
        out = np.empty(len(ts))
        vn, ve = (self._motion[0], self._motion[1]) if self._motion else (0.0, 0.0)
        for k, t in enumerate(ts):
            dt = t - t_mid
            la = lat + vn * dt / DEG_M
            lo = lon + ve * dt / (DEG_M * math.cos(math.radians(lat)))
            r_rx, v_rx = ecef_to_eci(geodetic_to_ecef(la, lo, alt), t)
            if self._motion:
                # add the receiver's own ground velocity (ENU -> ECI, approx.)
                th = gmst_rad(t)
                lam = math.radians(lo) + th
                east = np.array([-math.sin(lam), math.cos(lam), 0.0])
                phi = math.radians(la)
                north = np.array([-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam),
                                  math.cos(phi)])
                v_rx = v_rx + vn * north + ve * east
            r_s, v_s = self._orbit.state_eci(t)
            d = r_s - r_rx
            rate = float(np.dot(d, v_s - v_rx) / np.linalg.norm(d))
            out[k] = self._carrier_hz * (1.0 - rate / C) + offset + drift * dt
        return out

    def _fit(self, lat, lon, ts, f, w, t_mid):
        """Gauss-Newton on (lat, lon, offset, drift). Returns x, cov, chi2."""
        alt = self._alt[0]
        x = np.array([lat, lon, 0.0, 0.0])
        # start the offset where the data sits relative to the model
        x[2] = float(np.average(f - self._predict(lat, lon, alt, 0.0, 0.0, ts, t_mid), weights=w))
        for _ in range(self.MAX_ITER):
            pred = self._predict(x[0], x[1], alt, x[2], x[3], ts, t_mid)
            res = f - pred
            J = np.zeros((len(ts), 4))
            h = 1e-4
            for j in range(2):
                xp = x.copy()
                xp[j] += h
                J[:, j] = (self._predict(xp[0], xp[1], alt, xp[2], xp[3], ts, t_mid) - pred) / h
            J[:, 2] = 1.0
            J[:, 3] = ts - t_mid
            N = J.T @ (w[:, None] * J)
            try:
                cov = np.linalg.inv(N)
            except np.linalg.LinAlgError:
                return None, None, float("inf")
            dx = cov @ (J.T @ (w * res))
            x = x + dx
            if abs(dx[0]) < 1e-7 and abs(dx[1]) < 1e-7 and abs(dx[2]) < 1e-3:
                break
        pred = self._predict(x[0], x[1], alt, x[2], x[3], ts, t_mid)
        chi2 = float(np.sum(w * (f - pred) ** 2) / max(len(ts) - 4, 1))
        return x, cov, chi2

    def _declined(self, code, why, **extra) -> dict:
        self.last = {"status": "declined", "reason_code": code, "reason": why, **extra}
        return self.last

    def solve(self) -> dict:
        if self._orbit is None or self._carrier_hz is None:
            return self._declined(NoFixReason.NO_INPUT, "no orbit set (TLE through sgp4, or a model)")
        age = getattr(self._orbit, "age_days", 0.0)
        if age > self.MAX_TLE_AGE_DAYS:
            return self._declined(NoFixReason.STALE_INPUT,
                                  f"orbit elements {age:.1f} days old (limit {self.MAX_TLE_AGE_DAYS:.0f})")
        if len(self._obs) < self.MIN_POINTS:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT,
                                  f"{len(self._obs)} Doppler points (needs {self.MIN_POINTS})")
        if self._prior is None:
            return self._declined(NoFixReason.NO_ANCHOR, "no prior position to start from "
                                  "and to choose the side of the track")
        if self._alt is None:
            return self._declined(NoFixReason.NO_INPUT, "no altitude (barometer)")
        obs = sorted(self._obs, key=lambda o: o.t_unix)
        ts = np.array([o.t_unix for o in obs])
        if ts[-1] - ts[0] < self.MIN_PASS_S:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT,
                                  f"pass {ts[-1] - ts[0]:.0f} s long (needs {self.MIN_PASS_S:.0f})")
        f = np.array([o.freq_hz for o in obs])
        w = 1.0 / np.array([o.sigma_hz ** 2 for o in obs])
        t_mid = float(ts.mean())
        lat0, lon0, prior_sigma = self._prior
        alt = self._alt[0]
        max_elev = max(enu_elevation_deg(lat0, lon0, alt, self._orbit.state_eci(t)[0], t)
                       for t in ts[::max(1, len(ts) // 20)])
        if max_elev < self.MIN_MAX_ELEV_DEG:
            return self._declined(NoFixReason.POOR_GEOMETRY,
                                  f"pass peaks at {max_elev:.0f} deg elevation "
                                  f"(needs {self.MIN_MAX_ELEV_DEG:.0f})", max_elevation_deg=max_elev)
        x, cov, chi2 = self._fit(lat0, lon0, ts, f, w, t_mid)
        if x is None or not np.all(np.isfinite(x)):
            return self._declined(NoFixReason.DIVERGED, "fit did not converge")
        if chi2 > self.CHI2_LIMIT:
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"Doppler curve does not fit this orbit (residual variance "
                                  f"{chi2:.1f}x the stated noise): wrong satellite, stale orbit "
                                  f"or interference", chi2=chi2)
        sig_lat = math.sqrt(max(cov[0, 0], 0)) * DEG_M
        sig_lon = math.sqrt(max(cov[1, 1], 0)) * DEG_M * math.cos(math.radians(x[0]))
        from_prior = math.hypot((x[0] - lat0) * DEG_M,
                                (x[1] - lon0) * DEG_M * math.cos(math.radians(lat0)))
        if from_prior > self.MAX_PRIOR_SIGMAS * prior_sigma + 3 * max(sig_lat, sig_lon):
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"fix {from_prior / 1000:.0f} km from the prior (sigma "
                                  f"{prior_sigma / 1000:.1f} km): wrong satellite or orbit, "
                                  f"or a bad prior; the curve itself cannot tell",
                                  from_prior_m=from_prior)
        # the mirror solution across the ground track: start the fit from
        # the prior reflected through the fitted point and see where it goes
        mirror = None
        t_peak = ts[int(np.argmax([enu_elevation_deg(x[0], x[1], alt, self._orbit.state_eci(t)[0], t)
                                   for t in ts[::max(1, len(ts) // 40)]])) * max(1, len(ts) // 40)]
        mlat, mlon = mirror_across_track(x[0], x[1], self._orbit, float(t_peak))
        xm, covm, chi2m = self._fit(mlat, mlon, ts, f, w, t_mid)
        if xm is not None and np.all(np.isfinite(xm)) and chi2m < self.CHI2_LIMIT:
            dist = math.hypot((xm[0] - x[0]) * DEG_M,
                              (xm[1] - x[1]) * DEG_M * math.cos(math.radians(x[0])))
            if dist > 3 * max(sig_lat, sig_lon):
                mirror = {"lat": float(xm[0]), "lon": float(xm[1]), "distance_m": dist, "chi2": chi2m}
                d_prior_fix = math.hypot((x[0] - lat0) * DEG_M,
                                         (x[1] - lon0) * DEG_M * math.cos(math.radians(lat0)))
                d_prior_mirror = math.hypot((xm[0] - lat0) * DEG_M,
                                            (xm[1] - lon0) * DEG_M * math.cos(math.radians(lat0)))
                if abs(d_prior_mirror - d_prior_fix) < 2 * prior_sigma:
                    return self._declined(NoFixReason.FAILED_VALIDATION,
                                          f"ambiguous: the mirror position {dist / 1000:.1f} km "
                                          f"across the track fits as well, and the prior "
                                          f"(sigma {prior_sigma:.0f} m) cannot choose", mirror=mirror)
        self.last = {
            "status": "ok", "lat": float(x[0]), "lon": float(x[1]), "alt_m": alt,
            "sigma_lat_m": sig_lat, "sigma_lon_m": sig_lon, "sigma_m": max(sig_lat, sig_lon),
            "offset_hz": float(x[2]), "drift_hz_s": float(x[3]), "chi2": chi2,
            "n_points": len(obs), "pass_s": float(ts[-1] - ts[0]), "max_elevation_deg": max_elev,
            "orbit_age_days": age, "satellite": getattr(self._orbit, "name", "?"),
            "mirror": mirror, "t": float(ts[-1]),
        }
        return self.last

    def read(self) -> LayerReading:
        v = self.solve()
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=v["lat"], longitude=v["lon"], altitude=v["alt_m"],
                              accuracy_m=math.hypot(v["sigma_lat_m"], v["sigma_lon_m"]),
                              altitude_accuracy_m=self._alt[1]),
            self_confidence=1.0 / (1.0 + v["sigma_m"] / 100.0),
            raw_data={"fabricated": False, "independent": True, **v},
        )
