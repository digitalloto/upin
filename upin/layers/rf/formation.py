"""
Layer 153 -- formation cross-check and cooperative fix (formation_d29).

Two or more drones fly together, each with the box and a ranging radio.
Every slot each drone broadcasts, signed, where its receiver says it is,
how sure it is, whether it trusts that fix and where the fix came from, and
the ranges it has measured to the others. The ranging radio measures the
REAL distance between the drones on a band GNSS attacks do not touch. The
layer compares what the receivers say the distances are with what the
radio measures.

WHY THIS CATCHES WHAT ONE DRONE CANNOT

A single spoofer -- one transmitter, or a record-and-replay unit -- sends
the same set of fake satellite signals to every receiver in range. The
extra path delay from the spoofer to a given receiver is common to all of
that receiver's satellites, so it goes into the receiver's clock bias, not
its position: every receiver solves to the SAME fake position. Three
drones 40-80 m apart then all report one place, the reported pairwise
distances collapse towards zero, and the measured ranges still show the
formation intact. Each drone's receiver, looked at alone, is healthy.

THE CHECK   for each pair (i, j) with a fresh message and a fresh range:

    z = (|reported_i - reported_j| - range_ij) / sqrt(s_i^2 + s_j^2 + s_r^2)

a pair fails at |z| > Z_MAX. All pairs failing with the reported distances
far shorter than the ranges is "common spoof suspected"; both pairs of one
drone failing while the rest pass makes that drone the odd one out; a
single failing pair is a warning, never a hard fail (one pair cannot say
which receiver is wrong).

THE COOPERATIVE FIX   when my own fix is not trusted and two peers still
hold trusted GNSS fixes: my two ranges and my barometric altitude put me
on two circles that cross at two points, mirror images across the line
between the peers. My own dead-reckoning prior picks the right one when
the two are far enough apart; otherwise the layer declines and says so.
Three or more trusted peers go through layer 151's weighted solver.

A peer is an anchor only if its message says its fix is TRUSTED and came
from its own GNSS -- never from this layer. Three drones all anchoring on
each other would drift together while agreeing perfectly.

LIMITS, STATED: a spoofer with several directional transmitters that
tailors a distinct, geometry-preserving lie to each drone passes the check
(tested, so the claim stays true). A wide-area jammer that takes every
receiver down leaves no anchor: the ranges keep the formation's relative
geometry honest but cannot place it. A drone on the line between its two
peers cannot be fixed by them. The radio firmware is not written; the
message and range line formats are the contract. Every threshold is an
assumption until the real radio's ranging sigma is measured.

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
from upin.layers.rf.beacon_ranging import (DEG_M, HOP_SLOT_S, SIG_BYTES, BeaconRangingLayer,
                                           hop_channel, sign_message)

PEER_PREFIX = "drone-"
SOURCE_GNSS, SOURCE_UPIN = "gnss", "upin"


# -- the message and its signature ---------------------------------------------

def _canonical(m: dict) -> bytes:
    """Every field is signed, the ranges in a fixed order: a peer's trust
    flag or source cannot be flipped in flight."""
    ranges = ";".join(f"{str(r[0])}:{float(r[1]):.2f}:{float(r[2]):.2f}"
                      for r in sorted(m.get("ranges", []), key=lambda r: str(r[0])))
    return (f"{m['id']}|{m['t']:.3f}|{m['lat']:.7f}|{m['lon']:.7f}|{m['alt_m']:.1f}|"
            f"{m['sigma_m']:.2f}|{int(m['seq'])}|{int(m['channel'])}|{m['vn']:.2f}|{m['ve']:.2f}|"
            f"{int(bool(m['trusted']))}|{m['source']}|{ranges}").encode()


def sign_peer_message(m: dict, secret: bytes) -> dict:
    m = dict(m)
    m["sig"] = hmac.new(secret, _canonical(m), hashlib.sha256).hexdigest()[:2 * SIG_BYTES]
    return m


def verify_peer_message(m: dict, secret: bytes) -> bool:
    try:
        expect = hmac.new(secret, _canonical(m), hashlib.sha256).hexdigest()[:2 * SIG_BYTES]
        return hmac.compare_digest(expect, str(m.get("sig", "")))
    except (KeyError, TypeError, ValueError):
        return False


@dataclass
class PeerState:
    peer_id: str
    lat: float
    lon: float
    alt_m: float
    sigma_m: float
    vn: float
    ve: float
    trusted: bool
    source: str
    seq: int
    t: float                                   # message time
    ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)   # its ranges to others
    range_m: Optional[float] = None            # my range to it
    range_sigma_m: Optional[float] = None
    range_t: Optional[float] = None

    def at(self, t: float, velocity_sigma_ms: float) -> Tuple[float, float, float, float]:
        """Reported position moved to time t with the reported velocity;
        sigma widened for the skew. Returns (lat, lon, alt, sigma)."""
        dt = t - self.t
        lat = self.lat + self.vn * dt / DEG_M
        lon = self.lon + self.ve * dt / (DEG_M * math.cos(math.radians(self.lat)))
        return lat, lon, self.alt_m, math.hypot(self.sigma_m, velocity_sigma_ms * abs(dt))


class FormationLayer(NavigationLayer):
    """Peers in formation confirm each other's fixes through measured
    ranges, and place a peer that lost its own."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("ranging radio on every drone",
                     why="carries the signed messages and measures the real distance "
                         "between the drones on a band GNSS attacks do not touch",
                     typical_part="2.4 GHz LoRa-class ranging module (SX1280 family) or UWB"),
            Hardware("two or more drones flying together, each with the box",
                     why="each broadcasts its own checked fix; two trusted peers can place a third"),
        ],
        inputs=[
            DataInput("shared secret", feed_method="set_secret", units="bytes",
                      why="hop schedule and message signatures"),
            DataInput("peer messages", feed_method="feed_message",
                      units="id, time, position, sigma, velocity, trusted, source, ranges, seq, "
                            "channel, signature"),
            DataInput("ranges to peers", feed_method="feed_range", units="m, 1-sigma m"),
            DataInput("own fix to check", feed_method="check",
                      units="degrees, m, 1-sigma m", why="compared with the formation"),
            DataInput("barometric altitude", feed_method="set_altitude",
                      units="m MSL, 1-sigma m", why="turns two slant ranges into a fix"),
            DataInput("own prior position", feed_method="set_prior",
                      units="degrees, 1-sigma m", why="picks between the two mirror solutions"),
        ],
        preconditions=("at least one peer with a fresh signed message and range for the check",
                       "two peers with TRUSTED own-GNSS fixes, plus altitude and a prior, for a fix",
                       "the drone off the line between its peers"),
        notes="A single spoofer gives every receiver the same position; the ranges show "
              "the formation intact. A tailored multi-transmitter spoof passes (stated). "
              "Peers whose fix came from this layer are never anchors.",
    )

    MAX_AGE_S = 5.0
    MAX_RANGE_AGE_S = 2.0
    CLOCK_TOLERANCE_SLOTS = 1
    Z_MAX = 3.0
    """**Assumption.** A pair whose reported distance differs from its
    measured range by more than this many combined sigmas is inconsistent.
    Set from the real radio's ranging sigma once measured."""
    VELOCITY_SIGMA_MS = 1.0
    """**Assumption.** How much a peer's reported velocity may be wrong,
    widening its position for the time between its message and my epoch."""
    COLLAPSE_RATIO = 0.5
    """**Assumption.** Reported distances under this fraction of the measured
    ranges, on every pair, read as "everyone reports the same place": the
    single-spoofer signature."""
    MIRROR_SIGMAS = 3.0
    """**Assumption.** The rejected mirror solution must be this many sigmas
    from the prior, and the chosen one within it, or the fix declines."""
    MAX_HDOP = BeaconRangingLayer.MAX_HDOP

    def __init__(self, drone_id: str = ""):
        super().__init__(
            layer_id="formation_d29", layer_number=153,
            name="Formation Cross-Check and Cooperative Fix (peers confirm each other)",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ALTITUDE,
                          LayerCapability.THREAT_DETECT],
            description="Drones in formation compare the distances their receivers "
                        "imply with the distances a ranging radio measures: a single "
                        "spoofer gives every receiver the same position and is caught; "
                        "two trusted peers place a third that lost GNSS.",
        )
        self.drone_id = drone_id
        self._secret: Optional[bytes] = None
        self._peers: Dict[str, PeerState] = {}
        self._alt: Optional[Tuple[float, float, float]] = None
        self._prior: Optional[Tuple[float, float, float]] = None
        self._seq = 0
        self.rejected: Dict[str, int] = {}
        self.last: Optional[dict] = None
        self.last_check: Optional[dict] = None
        self.suspects: List[str] = []

    @property
    def own_id(self) -> str:
        return PEER_PREFIX + self.drone_id if self.drone_id else ""

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

    def set_prior(self, lat: float, lon: float, sigma_m: float) -> None:
        """Where I think I am and how sure: the solver's start, and the
        judge between the two mirror solutions. Never a measurement."""
        self._prior = (lat, lon, sigma_m)

    def _reject(self, why: str) -> str:
        self.rejected[why] = self.rejected.get(why, 0) + 1
        return why

    def feed_message(self, m: dict, now: float) -> str:
        """A peer's message as received. Returns "accepted" or the reason it
        was not; rejected messages are counted and never used."""
        if self._secret is None:
            return self._reject("no shared secret set")
        try:
            pid = str(m["id"])
            t, lat, lon = float(m["t"]), float(m["lat"]), float(m["lon"])
            alt, sigma = float(m["alt_m"]), float(m["sigma_m"])
            seq, ch = int(m["seq"]), int(m["channel"])
            vn, ve = float(m["vn"]), float(m["ve"])
            trusted, source = bool(m["trusted"]), str(m["source"])
            ranges = {str(r[0]): (float(r[1]), float(r[2])) for r in m.get("ranges", [])}
        except (KeyError, TypeError, ValueError, IndexError):
            return self._reject("malformed message")
        if pid == self.own_id:
            return "own message ignored"
        if not verify_peer_message(m, self._secret):
            return self._reject("bad signature")
        expected = {hop_channel(self._secret, t + k * HOP_SLOT_S)
                    for k in range(-self.CLOCK_TOLERANCE_SLOTS, self.CLOCK_TOLERANCE_SLOTS + 1)}
        if ch not in expected:
            return self._reject("off the hop schedule")
        if abs(now - t) > self.MAX_AGE_S:
            return self._reject(f"message {abs(now - t):.0f} s old")
        prev = self._peers.get(pid)
        if prev is not None and seq <= prev.seq:
            return self._reject("replayed (sequence not newer)")
        if not (sigma > 0 and math.isfinite(sigma)):
            return self._reject("peer states no position sigma")
        if source not in (SOURCE_GNSS, SOURCE_UPIN):
            return self._reject("unknown fix source")
        rng_fields = (prev.range_m, prev.range_sigma_m, prev.range_t) if prev else (None, None, None)
        self._peers[pid] = PeerState(pid, lat, lon, alt, sigma, vn, ve, trusted, source, seq, t,
                                     ranges, *rng_fields)
        return "accepted"

    def feed_range(self, peer_id: str, range_m: float, sigma_m: float, t: float) -> str:
        p = self._peers.get(str(peer_id))
        if p is None:
            return self._reject("range from a peer with no accepted message")
        if not (range_m > 0 and sigma_m > 0):
            return self._reject("range without a stated sigma")
        p.range_m, p.range_sigma_m, p.range_t = range_m, sigma_m, t
        return "accepted"

    def own_message(self, lat: float, lon: float, alt_m: float, sigma_m: float,
                    vn: float, ve: float, trusted: bool, source: str, t: float) -> dict:
        """What I broadcast this slot, signed, with my fresh ranges to the
        peers folded in so every drone can see every pair."""
        if self._secret is None or not self.drone_id:
            raise ValueError("own_message needs a shared secret and a drone_id")
        if source not in (SOURCE_GNSS, SOURCE_UPIN):
            raise ValueError("source must be 'gnss' or 'upin'")
        self._seq += 1
        ranges = [[p.peer_id, p.range_m, p.range_sigma_m] for p in self._peers.values()
                  if p.range_t is not None and t - p.range_t <= self.MAX_RANGE_AGE_S]
        m = {"id": self.own_id, "t": t, "lat": lat, "lon": lon, "alt_m": alt_m,
             "sigma_m": sigma_m, "seq": self._seq, "channel": hop_channel(self._secret, t),
             "vn": vn, "ve": ve, "trusted": bool(trusted), "source": source,
             "ranges": sorted(ranges, key=lambda r: r[0])}
        return sign_peer_message(m, self._secret)

    # -- peers in view --------------------------------------------------------

    def fresh_peers(self, now: float) -> List[PeerState]:
        return [p for p in self._peers.values() if now - p.t <= self.MAX_AGE_S]

    def ranged_peers(self, now: float) -> List[PeerState]:
        return [p for p in self.fresh_peers(now)
                if p.range_t is not None and now - p.range_t <= self.MAX_RANGE_AGE_S]

    def peers_snapshot(self, now: float) -> List[dict]:
        """For display: what I last heard from each peer, as heard."""
        out = []
        for p in sorted(self._peers.values(), key=lambda p: p.peer_id):
            out.append({"id": p.peer_id, "lat": p.lat, "lon": p.lon, "alt_m": p.alt_m,
                        "sigma_m": p.sigma_m, "trusted": p.trusted, "source": p.source,
                        "age_s": now - p.t, "range_m": p.range_m,
                        "range_age_s": None if p.range_t is None else now - p.range_t,
                        "suspect": p.peer_id in self.suspects})
        return out

    # -- the check --------------------------------------------------------

    @staticmethod
    def _distance(lat1, lon1, alt1, lat2, lon2, alt2) -> float:
        dn = (lat2 - lat1) * DEG_M
        de = (lon2 - lon1) * DEG_M * math.cos(math.radians((lat1 + lat2) / 2))
        du = 0.0 if alt1 is None or alt2 is None else alt2 - alt1
        return math.sqrt(dn * dn + de * de + du * du)

    def check(self, lat: float, lon: float, alt_m: Optional[float], sigma_m: float,
              t: float) -> dict:
        """My reported GNSS fix against the formation. Verdict PASS, WARN,
        FAIL or NOT_RUN, with the pairs that decided it."""
        me = self.own_id or "me"
        peers = self.ranged_peers(t)
        if self._secret is None:
            return self._verdict("NOT_RUN", "no shared secret set", [])
        if not self._peers:
            return self._verdict("NOT_RUN", "no peer messages accepted", [])
        if not self.fresh_peers(t):
            return self._verdict("NOT_RUN", "peer messages stale", [])
        if not peers:
            return self._verdict("NOT_RUN", "no fresh range to any peer", [])
        pairs = []
        for p in peers:
            plat, plon, palt, psig = p.at(t, self.VELOCITY_SIGMA_MS)
            skew = abs(t - p.range_t)
            d = self._distance(lat, lon, alt_m, plat, plon, palt if alt_m is not None else None)
            s = math.sqrt(sigma_m ** 2 + psig ** 2 + p.range_sigma_m ** 2
                          + (self.VELOCITY_SIGMA_MS * skew) ** 2)
            z = (d - p.range_m) / s
            pairs.append({"a": me, "b": p.peer_id, "reported_m": d, "range_m": p.range_m,
                          "sigma_m": s, "z": z, "ok": abs(z) <= self.Z_MAX})
        fresh = {p.peer_id: p for p in self.fresh_peers(t)}
        done = set()
        for p in fresh.values():
            for other_id, (r, rs) in p.ranges.items():
                q = fresh.get(other_id)
                key = frozenset((p.peer_id, other_id))
                if q is None or other_id == me or key in done:
                    continue
                done.add(key)
                plat, plon, palt, psig = p.at(t, self.VELOCITY_SIGMA_MS)
                qlat, qlon, qalt, qsig = q.at(t, self.VELOCITY_SIGMA_MS)
                d = self._distance(plat, plon, palt, qlat, qlon, qalt)
                s = math.sqrt(psig ** 2 + qsig ** 2 + rs ** 2)
                z = (d - r) / s
                pairs.append({"a": p.peer_id, "b": other_id, "reported_m": d, "range_m": r,
                              "sigma_m": s, "z": z, "ok": abs(z) <= self.Z_MAX})
        failed = [x for x in pairs if not x["ok"]]
        max_z = max(abs(x["z"]) for x in pairs)
        if not failed:
            return self._verdict("PASS", f"{len(pairs)} pair(s) consistent, largest |z| {max_z:.1f}",
                                 pairs, max_z=max_z)
        # the single-spoofer signature first: every reported distance far
        # shorter than its measured range. Judged on all pairs together, so
        # one range reading made noisy enough to pass cannot hide it.
        ratio = (sum(x["reported_m"] for x in pairs) / max(sum(x["range_m"] for x in pairs), 1e-9))
        if (len(pairs) >= 2 and len(failed) >= 2 and ratio < self.COLLAPSE_RATIO
                and all(x["reported_m"] < self.COLLAPSE_RATIO * x["range_m"] for x in pairs)):
            return self._verdict("FAIL", "common spoof suspected: all receivers report the same "
                                 f"place (reported distances {ratio:.0%} of the measured ranges) "
                                 "while the ranges show the formation intact",
                                 pairs, max_z=max_z, pattern="common_spoof")
        if len(failed) == len(pairs) and len(pairs) >= 2:
            return self._verdict("FAIL", f"all {len(pairs)} pairs inconsistent with the measured "
                                 "ranges", pairs, max_z=max_z, pattern="all_pairs")
        if len(pairs) == 1:
            x = failed[0]
            return self._verdict("WARN", f"pair {x['a']}–{x['b']} inconsistent (reported "
                                 f"{x['reported_m']:.0f} m, ranged {x['range_m']:.0f} m): one of the "
                                 "two receivers is wrong, or both are spoofed; one pair cannot say",
                                 pairs, max_z=max_z, pattern="one_pair")
        # the odd one out: every failing pair contains one drone, every pair
        # of that drone fails, and some other pair passes
        ids = set()
        for x in pairs:
            ids.update((x["a"], x["b"]))
        for cand in sorted(ids):
            mine = [x for x in pairs if cand in (x["a"], x["b"])]
            if (all(not x["ok"] for x in mine) and all(cand in (x["a"], x["b"]) for x in failed)
                    and len(mine) >= 2 and len(mine) < len(pairs)):
                if cand == me:
                    return self._verdict("FAIL", "my receiver disagrees with the ranges to both "
                                         "peers while the peers agree with each other",
                                         pairs, max_z=max_z, pattern="odd_me", suspect=me)
                return self._verdict("PASS", f"peer {cand} disagrees with both ranges and is "
                                     "suspect; my fix is consistent with the others",
                                     pairs, max_z=max_z, pattern="odd_peer", suspect=cand)
        return self._verdict("WARN", f"{len(failed)} of {len(pairs)} pairs inconsistent, pattern "
                             "unclear", pairs, max_z=max_z, pattern="mixed")

    def _verdict(self, verdict: str, reason: str, pairs: List[dict], **extra) -> dict:
        suspect = extra.get("suspect")
        self.suspects = [suspect] if suspect and suspect != self.own_id else []
        self.last_check = {"verdict": verdict, "reason": reason, "pairs": pairs,
                           "n_peers": len(self._peers), "n_pairs": len(pairs), **extra}
        return self.last_check

    # -- the cooperative fix ---------------------------------------------

    def _declined(self, code, why, **extra) -> dict:
        self.last = {"status": "declined", "reason_code": code, "reason": why,
                     "rejected": dict(self.rejected), **extra}
        return self.last

    def anchors(self, now: float) -> List[PeerState]:
        """Peers I may place myself from: fresh, ranged, trusting their own
        GNSS fix, and not the odd one out."""
        return [p for p in self.ranged_peers(now)
                if p.trusted and p.source == SOURCE_GNSS and p.peer_id not in self.suspects]

    def solve(self, now: float) -> dict:
        if self._secret is None:
            return self._declined(NoFixReason.NO_CALIBRATION, "no shared secret set")
        if not self._peers:
            return self._declined(NoFixReason.NO_INPUT, "no peer messages accepted")
        anchors = self.anchors(now)
        ranged = self.ranged_peers(now)
        if len(anchors) < 2:
            why = (f"{len(anchors)} peer(s) with a trusted own-GNSS fix and a fresh range; "
                   f"needs two" if ranged else "no peer with a fresh message and range")
            if len(anchors) == 1:
                why += ": one peer can detect a spoof but cannot place me"
            if any(not p.trusted or p.source != SOURCE_GNSS for p in ranged):
                why += " (peers without their own trusted GNSS fix are never anchors)"
            return self._declined(NoFixReason.INSUFFICIENT_INPUT, why, n_anchors=len(anchors))
        if self._alt is None or now - self._alt[2] > self.MAX_AGE_S:
            return self._declined(NoFixReason.NO_INPUT, "no fresh own altitude: two slant ranges "
                                  "need it to become a horizontal fix", n_anchors=len(anchors))
        if len(anchors) >= 3:
            return self._solve_many(anchors, now)
        return self._solve_two(anchors, now)

    def _solve_two(self, anchors: List[PeerState], now: float) -> dict:
        a, b = anchors
        alt, alt_sigma, _ = self._alt
        alat, alon, aalt, asig = a.at(now, self.VELOCITY_SIGMA_MS)
        blat, blon, balt, bsig = b.at(now, self.VELOCITY_SIGMA_MS)
        coslat = math.cos(math.radians(alat))

        def enu(lat, lon):
            return np.array([(lon - alon) * DEG_M * coslat, (lat - alat) * DEG_M])

        A, B = enu(alat, alon), enu(blat, blon)
        # slant ranges to horizontal, with the altitude uncertainty folded in
        hr, hs = [], []
        for p, palt, psig in ((a, aalt, asig), (b, balt, bsig)):
            dz = palt - alt
            if p.range_m <= abs(dz):
                return self._declined(NoFixReason.FAILED_VALIDATION,
                                      f"range to {p.peer_id} ({p.range_m:.0f} m) is shorter than the "
                                      f"altitude difference ({abs(dz):.0f} m)", n_anchors=2)
            h = math.sqrt(p.range_m ** 2 - dz * dz)
            dz_sigma = math.hypot(alt_sigma, psig)
            hr.append(h)
            hs.append(math.sqrt(p.range_sigma_m ** 2 + psig ** 2 + (dz / h * dz_sigma) ** 2))
        d = float(np.linalg.norm(B - A))
        if d < 1.0:
            return self._declined(NoFixReason.POOR_GEOMETRY, "the two peers report the same place: "
                                  "no baseline to fix from", n_anchors=2)
        ex = (B - A) / d
        ey = np.array([-ex[1], ex[0]])
        x = (hr[0] ** 2 - hr[1] ** 2 + d * d) / (2 * d)
        y2 = hr[0] ** 2 - x * x
        tol = 3.0 * math.hypot(*hs)
        if y2 < 0:
            if hr[0] + hr[1] < d - tol or abs(hr[0] - hr[1]) > d + tol:
                return self._declined(NoFixReason.FAILED_VALIDATION,
                                      f"the two ranges ({hr[0]:.0f} m, {hr[1]:.0f} m) cannot both be "
                                      f"true with the peers {d:.0f} m apart", n_anchors=2)
            y2 = 0.0                                  # tangent within the noise
        y = math.sqrt(y2)
        cands = [A + x * ex + y * ey, A + x * ex - y * ey]
        mirror_m = 2.0 * y
        if self._prior is None:
            return self._declined(NoFixReason.NO_ANCHOR, "no prior position to choose between the "
                                  f"two mirror solutions ({mirror_m:.0f} m apart)", n_anchors=2,
                                  mirror_distance_m=mirror_m)
        P = enu(self._prior[0], self._prior[1])
        psig = self._prior[2]
        dists = [float(np.linalg.norm(c - P)) for c in cands]
        k = int(np.argmin(dists))
        c = cands[k]
        # geometry at the chosen point, then the covariance from the two ranges
        J = np.array([(c - A) / max(np.linalg.norm(c - A), 1e-6),
                      (c - B) / max(np.linalg.norm(c - B), 1e-6)])
        try:
            dop = np.linalg.inv(J.T @ J)
            tr = dop[0, 0] + dop[1, 1]
            hdop = math.sqrt(tr) if tr > 0 and math.isfinite(tr) else float("inf")
        except np.linalg.LinAlgError:
            hdop = float("inf")
        if not math.isfinite(hdop) or hdop > self.MAX_HDOP:
            return self._declined(NoFixReason.POOR_GEOMETRY,
                                  f"HDOP {hdop:.1f}: I am on or near the line between the two peers; "
                                  "two ranges cannot fix the cross-line position", n_anchors=2,
                                  hdop=hdop, mirror_distance_m=mirror_m)
        W = np.diag([1.0 / hs[0] ** 2, 1.0 / hs[1] ** 2])
        cov = np.linalg.inv(J.T @ W @ J)
        sig_e, sig_n = math.sqrt(cov[0, 0]), math.sqrt(cov[1, 1])
        fix_sigma = max(sig_n, sig_e)
        gate = self.MIRROR_SIGMAS * math.hypot(psig, fix_sigma)
        if dists[1 - k] <= gate:
            return self._declined(NoFixReason.POOR_GEOMETRY,
                                  f"mirror ambiguous: the two candidate positions are {mirror_m:.0f} m "
                                  f"apart and the prior is only ±{psig:.0f} m", n_anchors=2,
                                  hdop=hdop, mirror_distance_m=mirror_m)
        if dists[k] > gate:
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"neither candidate agrees with the prior (nearest {dists[k]:.0f} m "
                                  f"away, prior ±{psig:.0f} m)", n_anchors=2, hdop=hdop,
                                  mirror_distance_m=mirror_m)
        lat = alat + c[1] / DEG_M
        lon = alon + c[0] / (DEG_M * coslat)
        self.last = {
            "status": "ok", "t": now, "lat": lat, "lon": lon, "alt_m": alt,
            "sigma_n_m": sig_n, "sigma_e_m": sig_e, "sigma_m": fix_sigma, "sigma_alt_m": alt_sigma,
            "hdop": hdop, "n_anchors": 2, "anchors": [a.peer_id, b.peer_id],
            "mirror_distance_m": mirror_m, "prior_distance_m": dists[k], "rms_residual_m": 0.0,
            "method": "two ranges and altitude, closed form; mirror resolved by the prior",
            "rejected": dict(self.rejected),
        }
        return self.last

    def _solve_many(self, anchors: List[PeerState], now: float) -> dict:
        inner = BeaconRangingLayer()
        inner.initialize()
        inner.set_secret(self._secret)
        for p in anchors:
            lat, lon, alt, sig = p.at(now, self.VELOCITY_SIGMA_MS)
            m = sign_message({"id": p.peer_id, "t": now, "lat": lat, "lon": lon, "alt_m": alt,
                              "sigma_m": sig, "seq": p.seq, "channel": hop_channel(self._secret, now)},
                             self._secret)
            inner.feed_message(m, now)
            inner.feed_range(p.peer_id, p.range_m, p.range_sigma_m, p.range_t)
        inner.set_altitude(*self._alt)
        if self._prior is not None:
            inner.set_prior(self._prior[0], self._prior[1])
        v = dict(inner.solve(now))
        v["n_anchors"] = v.pop("n_beacons", len(anchors))
        v["anchors"] = v.pop("beacons", [p.peer_id for p in anchors])
        v.pop("beacon_sigmas_m", None)
        v["method"] = "weighted least squares over three or more peers (layer 151's solver)"
        v["rejected"] = dict(self.rejected)
        self.last = v
        return v

    def read(self) -> LayerReading:
        now = max([p.t for p in self._peers.values()] + [0.0])
        v = self.solve(now)
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=v["lat"], longitude=v["lon"], altitude=v["alt_m"],
                              accuracy_m=math.hypot(v["sigma_n_m"], v["sigma_e_m"]),
                              altitude_accuracy_m=v["sigma_alt_m"]),
            self_confidence=1.0 / (1.0 + v["sigma_m"]),
            raw_data={"fabricated": False, "independent": True, **v},
        )
