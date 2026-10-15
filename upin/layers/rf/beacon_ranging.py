"""
Layer 151 -- known-position beacon ranging (beaconrng_d27).

Beacons that know where they are, on a band GNSS jammers do not touch,
hopping frequency on a shared secret schedule, each message signed. The
drone measures its range to every beacon it can hear and solves its
position. The beacon can sit on a tripod, a mast, a tethered balloon or a
free weather balloon: the layer does not care, as long as the beacon
broadcasts its own position and how well it knows it. (The user's balloon
idea, made honest: see docs/BEACONS.md.)

WHAT A BEACON SENDS, every slot
    id, time, lat, lon, alt, position sigma, sequence number, channel, signature

WHAT THE DRONE CHECKS BEFORE A MESSAGE COUNTS
    signature       HMAC-SHA256 over the fields with the shared secret
    channel         the message was on the channel the secret schedule says
                    for that time slot (a jammer must cover the whole band)
    sequence        newer than the last one from that beacon (no replay)
    age             not older than MAX_AGE_S
A message failing any of these is counted and ignored, never used.

THE SOLVE
    Weighted least squares on the ranges, in a local east-north-up frame,
    Gauss-Newton from the beacons' centroid. Each range's weight folds in
    the beacon's own position sigma: a beacon that knows itself to 500 m
    cannot give a 10 m fix, and the maths says so. Three beacons plus a
    barometric altitude, or four beacons, make a fix. DOP is reported and a
    poor geometry declines.

WHAT IT CANNOT DO -- stated
    A jammer on the beacon band (barrage) stops it; so does losing line of
    sight. It is only as good as the beacons' own positions. Ranging
    precision is the radio's: tens of metres for LoRa-class two-way
    ranging, centimetres for UWB at short range. The legal band and power
    are the operator's responsibility (docs/BEACONS.md).

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import DataInput, Hardware, SensorRequirement

DEG_M = 111_320.0
HOP_SLOT_S = 1.0
N_CHANNELS = 32
SIG_BYTES = 8


# -- the message and its checks ----------------------------------------------

def hop_channel(secret: bytes, t: float, n_channels: int = N_CHANNELS) -> int:
    """The channel the schedule puts time t on: a keyed hash of the slot."""
    slot = int(math.floor(t / HOP_SLOT_S))
    digest = hmac.new(secret, f"hop:{slot}".encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:4], "big") % n_channels


def _canonical(m: dict) -> bytes:
    return (f"{m['id']}|{m['t']:.3f}|{m['lat']:.7f}|{m['lon']:.7f}|{m['alt_m']:.1f}|"
            f"{m['sigma_m']:.2f}|{int(m['seq'])}|{int(m['channel'])}").encode()


def sign_message(m: dict, secret: bytes) -> dict:
    m = dict(m)
    m["sig"] = hmac.new(secret, _canonical(m), hashlib.sha256).hexdigest()[:2 * SIG_BYTES]
    return m


def verify_signature(m: dict, secret: bytes) -> bool:
    try:
        expect = hmac.new(secret, _canonical(m), hashlib.sha256).hexdigest()[:2 * SIG_BYTES]
        return hmac.compare_digest(expect, str(m.get("sig", "")))
    except (KeyError, TypeError, ValueError):
        return False


@dataclass
class BeaconState:
    beacon_id: str
    lat: float
    lon: float
    alt_m: float
    sigma_m: float
    seq: int
    t: float                       # message time
    range_m: Optional[float] = None
    range_sigma_m: Optional[float] = None
    range_t: Optional[float] = None


@dataclass
class Solution:
    lat: float
    lon: float
    alt_m: Optional[float]
    sigma_n_m: float
    sigma_e_m: float
    sigma_u_m: Optional[float]
    hdop: float
    n_beacons: int
    rms_residual_m: float
    beacons: List[str] = field(default_factory=list)


class BeaconRangingLayer(NavigationLayer):
    """Position from ranges to beacons that broadcast their own positions."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("ranging radio on the beacon band",
                     why="hears the beacons and measures the range to each",
                     typical_part="2.4 GHz LoRa-class ranging module (SX1280 family) "
                                  "or UWB for short range"),
            Hardware("three or more beacons that know their own positions",
                     why="tripod, mast, tethered or free balloon; each carries its "
                         "own GNSS or is tracked from surveyed ground sites",
                     typical_part="same radio module, a position source, a battery"),
        ],
        inputs=[
            DataInput("shared secret", feed_method="set_secret", units="bytes",
                      why="hop schedule and message signatures"),
            DataInput("beacon messages", feed_method="feed_message",
                      units="id, time, position, sigma, seq, channel, signature"),
            DataInput("ranges", feed_method="feed_range", units="m, 1-sigma m"),
            DataInput("barometric altitude (optional)", feed_method="set_altitude",
                      units="m MSL, 1-sigma m", why="lets three beacons make a fix"),
        ],
        preconditions=("three beacons with fresh signed messages and ranges, or four "
                       "without altitude", "geometry with HDOP below MAX_HDOP"),
        notes="Carrier-agnostic: whatever holds the beacon up. A beacon's own "
              "position sigma propagates into the fix. Band and power limits are "
              "the operator's responsibility.",
    )

    MAX_AGE_S = 5.0
    MAX_RANGE_AGE_S = 2.0
    MAX_HDOP = 6.0
    """**Assumption.** Geometry worse than this gives a fix too elongated to
    be useful; declines instead."""
    CLOCK_TOLERANCE_SLOTS = 1
    MAX_ITER = 60
    STEP_TOL_M = 0.01

    def __init__(self):
        super().__init__(
            layer_id="beaconrng_d27", layer_number=151,
            name="Known-Position Beacon Ranging (balloons, masts, tripods)",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ALTITUDE],
            description="Position from ranges to signed, frequency-hopping beacons "
                        "that broadcast their own positions -- on tripods, masts or "
                        "balloons -- on a band GNSS jammers do not touch.",
        )
        self._secret: Optional[bytes] = None
        self._beacons: Dict[str, BeaconState] = {}
        self._alt: Optional[Tuple[float, float, float]] = None
        self.rejected: Dict[str, int] = {}
        self.last: Optional[dict] = None
        self._last_solution_ne: Optional[np.ndarray] = None
        self._prior: Optional[Tuple[float, float]] = None

    # -- contract ---------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    # -- inputs -----------------------------------------------------------

    def set_secret(self, secret: bytes) -> None:
        self._secret = bytes(secret)

    def set_altitude(self, alt_msl_m: float, sigma_m: float, t: float) -> None:
        self._alt = (alt_msl_m, sigma_m, t)

    def set_prior(self, lat: float, lon: float) -> None:
        """Where the solver starts (the filter's own estimate). Only the
        start: the ranges decide the fix."""
        self._prior = (lat, lon)

    def _reject(self, why: str) -> str:
        self.rejected[why] = self.rejected.get(why, 0) + 1
        return why

    def feed_message(self, m: dict, now: float) -> str:
        """A beacon message as received. Returns "accepted" or the reason it
        was not; rejected messages are counted and never used."""
        if self._secret is None:
            return self._reject("no shared secret set")
        try:
            bid = str(m["id"])
            t, lat, lon = float(m["t"]), float(m["lat"]), float(m["lon"])
            alt, sigma, seq, ch = float(m["alt_m"]), float(m["sigma_m"]), int(m["seq"]), int(m["channel"])
        except (KeyError, TypeError, ValueError):
            return self._reject("malformed message")
        if not verify_signature(m, self._secret):
            return self._reject("bad signature")
        expected = {hop_channel(self._secret, t + k * HOP_SLOT_S)
                    for k in range(-self.CLOCK_TOLERANCE_SLOTS, self.CLOCK_TOLERANCE_SLOTS + 1)}
        if ch not in expected:
            return self._reject("off the hop schedule")
        if abs(now - t) > self.MAX_AGE_S:
            return self._reject(f"message {abs(now - t):.0f} s old")
        prev = self._beacons.get(bid)
        if prev is not None and seq <= prev.seq:
            return self._reject("replayed (sequence not newer)")
        if not (sigma > 0 and math.isfinite(sigma)):
            return self._reject("beacon states no position sigma")
        rng_fields = (prev.range_m, prev.range_sigma_m, prev.range_t) if prev else (None, None, None)
        self._beacons[bid] = BeaconState(bid, lat, lon, alt, sigma, seq, t, *rng_fields)
        return "accepted"

    def feed_range(self, beacon_id: str, range_m: float, sigma_m: float, t: float) -> str:
        b = self._beacons.get(str(beacon_id))
        if b is None:
            return self._reject("range from a beacon with no accepted message")
        if not (range_m > 0 and sigma_m > 0):
            return self._reject("range without a stated sigma")
        b.range_m, b.range_sigma_m, b.range_t = range_m, sigma_m, t
        return "accepted"

    # -- the solve --------------------------------------------------------

    def _declined(self, code, why, **extra) -> dict:
        self.last = {"status": "declined", "reason_code": code, "reason": why,
                     "rejected": dict(self.rejected), **extra}
        return self.last

    def usable(self, now: float) -> List[BeaconState]:
        return [b for b in self._beacons.values()
                if now - b.t <= self.MAX_AGE_S and b.range_t is not None
                and now - b.range_t <= self.MAX_RANGE_AGE_S]

    def solve(self, now: float) -> dict:
        if self._secret is None:
            return self._declined(NoFixReason.NO_CALIBRATION, "no shared secret set")
        if not self._beacons:
            return self._declined(NoFixReason.NO_INPUT, "no beacon messages accepted",
                                  rejected=dict(self.rejected))
        bs = self.usable(now)
        have_alt = self._alt is not None and now - self._alt[2] <= self.MAX_AGE_S
        need = 3 if have_alt else 4
        if len(bs) < need:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT,
                                  f"{len(bs)} beacon(s) with fresh message and range; "
                                  f"needs {need}" + ("" if have_alt else " (no altitude input)"))
        lat0 = float(np.mean([b.lat for b in bs]))
        lon0 = float(np.mean([b.lon for b in bs]))
        coslat = math.cos(math.radians(lat0))

        def to_enu(lat, lon, alt):
            return np.array([(lon - lon0) * DEG_M * coslat, (lat - lat0) * DEG_M, alt])

        P = np.array([to_enu(b.lat, b.lon, b.alt_m) for b in bs])
        r = np.array([b.range_m for b in bs])
        w = 1.0 / np.array([b.range_sigma_m ** 2 + b.sigma_m ** 2 for b in bs])
        x = np.zeros(3)
        x[2] = self._alt[0] if have_alt else float(P[:, 2].mean() - 100.0)
        if self._prior is not None:
            x[:2] = to_enu(self._prior[0], self._prior[1], 0.0)[:2]
        elif self._last_solution_ne is not None:
            x[:2] = self._last_solution_ne

        def hdop_at(x):
            diff = x - P
            Hg = diff / np.maximum(np.linalg.norm(diff, axis=1), 1e-6)[:, None]
            if have_alt:
                Hg = np.vstack([Hg, [0.0, 0.0, 1.0]])
            try:
                d = np.linalg.inv(Hg.T @ Hg)
                v = d[0, 0] + d[1, 1]
                return math.sqrt(v) if v > 0 and math.isfinite(v) else float("inf")
            except np.linalg.LinAlgError:
                return float("inf")

        # geometry first: a bunched or collinear set cannot fix a horizontal
        # position wherever the solver starts, so say so before iterating
        hdop0 = hdop_at(x)
        if hdop0 > 3 * self.MAX_HDOP:
            return self._declined(NoFixReason.POOR_GEOMETRY,
                                  f"HDOP {hdop0:.0f} at the starting point: beacons too bunched "
                                  f"or collinear to fix horizontally", hdop=hdop0)

        def system(x):
            diff = x - P
            dist = np.linalg.norm(diff, axis=1)
            H = diff / np.maximum(dist, 1e-6)[:, None]
            res = r - dist
            if have_alt:
                H = np.vstack([H, [0.0, 0.0, 1.0]])
                res = np.append(res, self._alt[0] - x[2])
                ww = np.append(w, 1.0 / self._alt[1] ** 2)
            else:
                ww = w
            return H, res, ww, float(np.sum(ww * res * res))

        # Levenberg-Marquardt: a damped step that cannot overshoot, so a
        # one-sided geometry (all beacons behind the drone) still converges
        lam = 1e-3
        H, res, ww, cost = system(x)
        converged = False
        for _ in range(self.MAX_ITER):
            N = H.T @ (ww[:, None] * H)
            g = H.T @ (ww * res)
            try:
                dx = np.linalg.solve(N + lam * np.diag(np.diag(N) + 1e-9), g)
            except np.linalg.LinAlgError:
                return self._declined(NoFixReason.POOR_GEOMETRY, "singular geometry")
            x_new = x + dx
            H_new, res_new, ww_new, cost_new = system(x_new)
            if np.linalg.norm(dx) < self.STEP_TOL_M:
                if cost_new < cost:
                    x, H, res, ww, cost = x_new, H_new, res_new, ww_new, cost_new
                converged = True                    # at the minimum, accepted or not
                break
            if cost_new < cost:
                gain = (cost - cost_new) / max(cost, 1e-12)
                x, H, res, ww, cost = x_new, H_new, res_new, ww_new, cost_new
                lam = max(lam / 3.0, 1e-9)
                if gain < 1e-8:                    # creeping along a flat valley
                    converged = True
                    break
            else:
                lam = min(lam * 5.0, 1e6)
        if not converged:
            return self._declined(NoFixReason.DIVERGED, "solver did not converge")
        N = H.T @ (ww[:, None] * H)
        try:
            cov = np.linalg.inv(N)
        except np.linalg.LinAlgError:
            return self._declined(NoFixReason.POOR_GEOMETRY, "singular geometry")
        # DOP in the usual sense: geometry only, with unit-weight ranges
        try:
            Hg = H[:len(bs)]
            dop = np.linalg.inv(Hg.T @ Hg) if not have_alt else np.linalg.inv(
                np.vstack([Hg, [0, 0, 1]]).T @ np.vstack([Hg, [0, 0, 1]]))
            v = dop[0, 0] + dop[1, 1]
            hdop = math.sqrt(v) if v > 0 and math.isfinite(v) else float("inf")
        except np.linalg.LinAlgError:
            hdop = float("inf")
        if hdop > self.MAX_HDOP:
            return self._declined(NoFixReason.POOR_GEOMETRY,
                                  f"HDOP {hdop:.1f} above {self.MAX_HDOP}: beacons too "
                                  f"bunched to fix horizontally", hdop=hdop)
        dist = np.linalg.norm(x - P, axis=1)
        rms = float(np.sqrt(np.mean((r - dist) ** 2)))
        sig_e, sig_n = math.sqrt(cov[0, 0]), math.sqrt(cov[1, 1])
        sig_u = math.sqrt(cov[2, 2])
        self._last_solution_ne = x[:2].copy()
        lat = lat0 + x[1] / DEG_M
        lon = lon0 + x[0] / (DEG_M * coslat)
        self.last = {
            "status": "ok", "t": now, "lat": lat, "lon": lon, "alt_m": float(x[2]),
            "sigma_n_m": sig_n, "sigma_e_m": sig_e, "sigma_m": max(sig_n, sig_e),
            "sigma_alt_m": sig_u, "hdop": hdop, "n_beacons": len(bs),
            "beacons": [b.beacon_id for b in bs], "rms_residual_m": rms,
            "beacon_sigmas_m": [b.sigma_m for b in bs], "rejected": dict(self.rejected),
        }
        return self.last

    def read(self) -> LayerReading:
        now = max([b.t for b in self._beacons.values()] + [0.0])
        v = self.solve(now)
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=v["lat"], longitude=v["lon"], altitude=v["alt_m"],
                              accuracy_m=math.hypot(v["sigma_n_m"], v["sigma_e_m"]),  # DRMS
                              altitude_accuracy_m=v["sigma_alt_m"]),
            self_confidence=1.0 / (1.0 + v["sigma_m"]),
            raw_data={"fabricated": False, "independent": True, **v},
        )
