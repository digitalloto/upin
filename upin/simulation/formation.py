"""
SIMULATED formation: drones on a shared path at fixed offsets, each with
its own receiver, exchanging layer 153's signed messages and measuring the
ranges between them.

What is simulated, and how:
- each drone's true position: the path at a time shifted by its along-track
  offset, displaced across-track; its true velocity is the path's;
- each receiver's error: a Gauss-Markov process (**assumption** 1.5 m,
  30 s, like the console's receiver), independent per drone;
- whether a receiver has a fix: a callable the caller supplies (the console
  uses its jammer model at the drone's own position);
- a SINGLE spoofer: every receiver with a fix reports the SAME fake position
  (plus its own noise) -- the physics of one transmitter; a TAILORED
  spoofer: each receiver reports its own true position plus a common
  offset -- the multi-transmitter case the layer cannot catch, kept here so
  the limit is tested, not just stated;
- ranges: true 3-D distances plus Gaussian noise with the beacon
  simulation's assumed ranging sigma.

Truth never leaks into a message: a message carries the reported position,
the ranges the measured ones. A drone without a fix carries its last fix
forward with its velocity, widening (**assumption** 2 m/s of sigma growth),
marked untrusted with source "upin", as a real box would broadcast its own
degraded estimate.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from upin.layers.rf.beacon_ranging import DEG_M, hop_channel
from upin.layers.rf.formation import PEER_PREFIX, SOURCE_GNSS, SOURCE_UPIN, sign_peer_message
from upin.simulation.beacons import RANGE_SIGMA_LORA_M

Truth = Callable[[float], Tuple[float, float, float, float]]     # t -> (n, e, vn, ve)
ToLL = Callable[[float, float], Tuple[float, float]]             # (n, e) -> (lat, lon)
HasFix = Callable[[str, float, float], bool]                     # (drone_id, lat, lon) -> bool


@dataclass
class SimDrone:
    drone_id: str
    along_m: float = 0.0        # negative: behind the lead along the path
    cross_m: float = 0.0        # positive: to the right of the path
    alt_offset_m: float = 0.0


@dataclass
class Report:
    drone_id: str
    true_n: float
    true_e: float
    true_lat: float
    true_lon: float
    alt_m: float
    vn: float
    ve: float
    has_fix: bool
    lat: Optional[float]        # what the receiver reports (None: no fix)
    lon: Optional[float]
    sigma_m: Optional[float]


class _GaussMarkov:
    def __init__(self, rng: random.Random, sigma: float, tau_s: float):
        self.rng, self.sigma, self.tau = rng, sigma, tau_s
        self.x = rng.gauss(0, sigma)

    def step(self, dt: float) -> float:
        a = math.exp(-dt / self.tau)
        self.x = a * self.x + math.sqrt(1 - a * a) * self.rng.gauss(0, self.sigma)
        return self.x


class SimFormation:
    GNSS_SIGMA_M, GNSS_TAU_S = 1.5, 30.0
    """**Assumption.** Receiver error size and persistence, as the console."""
    COAST_SIGMA_GROWTH_MS = 2.0
    """**Assumption.** How fast a drone without a fix widens the sigma of
    the position it carries forward."""

    def __init__(self, drones: List[SimDrone], secret: bytes, truth: Truth, to_ll: ToLL,
                 speed_ms: float, alt_m: float = 50.0, seed: int = 0,
                 gnss_sigma_m: float = GNSS_SIGMA_M, range_sigma_m: float = RANGE_SIGMA_LORA_M):
        self.drones = {d.drone_id: d for d in drones}
        self.secret = secret
        self.truth, self.to_ll = truth, to_ll
        self.speed_ms, self.alt_m = speed_ms, alt_m
        self.range_sigma_m = range_sigma_m
        self.rng = random.Random(seed)
        self.nprng = np.random.default_rng(seed)
        self.err = {d.drone_id: [_GaussMarkov(self.rng, gnss_sigma_m, self.GNSS_TAU_S) for _ in range(2)]
                    for d in drones}
        self._seq = {d.drone_id: 0 for d in drones}
        self._last_fix: Dict[str, Tuple[float, float, float, float]] = {}   # lat, lon, sigma, t
        self.reports: Dict[str, Report] = {}
        self.ranges: Dict[frozenset, Tuple[float, float]] = {}
        self.t = 0.0

    # -- truth ------------------------------------------------------------

    def true_state(self, drone_id: str, t: float) -> Tuple[float, float, float, float]:
        d = self.drones[drone_id]
        n, e, vn, ve = self.truth(t + d.along_m / self.speed_ms)
        sp = math.hypot(vn, ve)
        if sp > 1e-9 and d.cross_m:
            un, ue = vn / sp, ve / sp
            n += d.cross_m * (-ue)                    # right of track
            e += d.cross_m * un
        return n, e, vn, ve

    # -- one slot ---------------------------------------------------------

    def step(self, t: float, dt: float = 1.0, has_fix: Optional[HasFix] = None,
             spoof: Optional[Tuple[float, float]] = None,
             tailored: Optional[Tuple[float, float]] = None,
             offsets: Optional[Dict[str, Tuple[float, float]]] = None) -> Dict[str, Report]:
        """Advance every receiver. spoof: the one fake position a single
        spoofer gives every receiver. tailored: a (north, east) offset each
        receiver's own position is shifted by (the multi-transmitter case).
        offsets: per-drone receiver faults, (north, east) metres."""
        self.t = t
        reports = {}
        for did, d in self.drones.items():
            n, e, vn, ve = self.true_state(did, t)
            tlat, tlon = self.to_ll(n, e)
            alt = self.alt_m + d.alt_offset_m
            en, ee = (g.step(dt) for g in self.err[did])
            fix = True if has_fix is None else bool(has_fix(did, tlat, tlon))
            lat = lon = sig = None
            if fix:
                if spoof is not None:
                    base_n, base_e = spoof
                else:
                    base_n, base_e = n, e
                    if tailored is not None:
                        base_n, base_e = base_n + tailored[0], base_e + tailored[1]
                if offsets and did in offsets:
                    base_n, base_e = base_n + offsets[did][0], base_e + offsets[did][1]
                lat, lon = self.to_ll(base_n + en, base_e + ee)
                sig = self.GNSS_SIGMA_M
                self._last_fix[did] = (lat, lon, sig, t)
            reports[did] = Report(did, n, e, tlat, tlon, alt, vn, ve, fix, lat, lon, sig)
        self.reports = reports
        self.ranges = {}
        ids = sorted(reports)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                ra, rb = reports[a], reports[b]
                dn = rb.true_n - ra.true_n
                de = rb.true_e - ra.true_e
                du = rb.alt_m - ra.alt_m
                true_r = math.sqrt(dn * dn + de * de + du * du)
                self.ranges[frozenset((a, b))] = (true_r + float(self.nprng.normal(0, self.range_sigma_m)),
                                                  self.range_sigma_m)
        return reports

    def ranges_for(self, drone_id: str) -> List[Tuple[str, float, float]]:
        """(peer id, measured range, sigma) as drone_id's radio measured them."""
        out = []
        for key, (r, s) in self.ranges.items():
            if drone_id in key:
                other = next(iter(key - {drone_id}))
                out.append((PEER_PREFIX + other, r, s))
        return sorted(out)

    def message(self, drone_id: str, t: float) -> Optional[dict]:
        """The signed message drone_id broadcasts this slot, or None if it
        has never had a fix to report."""
        r = self.reports[drone_id]
        if r.has_fix:
            lat, lon, sig, trusted, source = r.lat, r.lon, r.sigma_m, True, SOURCE_GNSS
        elif drone_id in self._last_fix:
            lat0, lon0, sig0, t0 = self._last_fix[drone_id]
            # carried forward with the velocity, widening; a real box would
            # broadcast its own degraded estimate here
            lat = lat0 + r.vn * (t - t0) / DEG_M
            lon = lon0 + r.ve * (t - t0) / (DEG_M * math.cos(math.radians(lat0)))
            sig = math.hypot(sig0, self.COAST_SIGMA_GROWTH_MS * (t - t0))
            trusted, source = False, SOURCE_UPIN
        else:
            return None
        self._seq[drone_id] += 1
        m = {"id": PEER_PREFIX + drone_id, "t": t, "lat": lat, "lon": lon, "alt_m": r.alt_m,
             "sigma_m": sig, "seq": self._seq[drone_id], "channel": hop_channel(self.secret, t),
             "vn": r.vn, "ve": r.ve, "trusted": trusted, "source": source,
             "ranges": [[pid, rr, ss] for pid, rr, ss in self.ranges_for(drone_id)]}
        return sign_peer_message(m, self.secret)
