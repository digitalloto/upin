"""
Layer 152 -- breadcrumb beacons (breadcrumb_d28).

The drone carries a few small beacons and DROPS them on the way in, while
its position is still trusted, as jamming begins to rise. Each crumb is
stamped with the position it will land at (the fix at release plus the
fall drift the wind will give it) and the sigma of that stamp. Inside the
jammed zone, and on the way back, the drone ranges to its own crumbs and
solves its position from them: the radio form of the landmark layer's
breadcrumbs, built on layer 151's ranging and checks.

THE ONE RULE THAT MATTERS

A crumb is never dropped while the fix is untrusted or too loose. A crumb
stamped with a guessed position would poison every later fix. The drop
policy refuses, and says why. Asserted in tests.

THE STAMP

    landing   = fix + wind x fall time        (fall time = height / CRUMB_FALL_MS)
    sigma     = fix sigma (+) wind sigma x fall time

The crumb then broadcasts that stamp, signed, like any beacon; the range
and the solve are layer 151's. A stamp is only as good as the fix at the
moment of release and the wind estimate for the fall; both sigmas travel
into every fix the crumb later gives.

LIMITS: ground-level radios reach a kilometre or three with line of sight,
terrain blocks them, the crumbs stay behind (recoverable), and the number
carried is small. Crumb radio firmware and the release mechanism are not
built; the provisioning line is a contract.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import DataInput, Hardware, SensorRequirement
from upin.layers.rf.beacon_ranging import DEG_M, BeaconRangingLayer

CRUMB_PREFIX = "crumb-"
THREAT_CLEAR, THREAT_RISING, THREAT_JAMMED = 0, 1, 2


@dataclass
class DropPolicy:
    spacing_m: float = 300.0
    max_crumbs: int = 6
    max_drop_sigma_m: float = 5.0
    """**Assumption.** A crumb stamped with a fix looser than this is not
    worth carrying; it would give fixes no better than coasting for a
    while. Set from the mission's accuracy need."""
    start_at: int = THREAT_RISING


@dataclass
class Crumb:
    crumb_id: str
    lat: float
    lon: float
    alt_m: Optional[float]
    sigma_m: float
    t: float
    fix_sigma_m: float
    drift_m: Tuple[float, float]
    fall_s: float


class BreadcrumbLayer(NavigationLayer):
    """Position from beacons the drone itself dropped while it still knew
    where it was."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("breadcrumb units", why="small signed ranging beacons the drone carries",
                     typical_part="2.4 GHz ranging module + microcontroller + coin cell + streamer"),
            Hardware("release mechanism", why="drops one crumb on command",
                     typical_part="a servo-driven dispenser"),
            Hardware("ranging radio on the box", why="ranges to the crumbs",
                     typical_part="the same module as layer 151"),
        ],
        inputs=[
            DataInput("current fix and whether it is trusted", feed_method="feed_fix",
                      units="degrees, m, 1-sigma m, bool", why="the stamp, and the rule"),
            DataInput("wind estimate", feed_method="feed_wind", units="m/s, 1-sigma",
                      why="the fall drift"),
            DataInput("height above ground", feed_method="feed_agl", units="m",
                      why="the fall time"),
            DataInput("threat level", feed_method="feed_threat", units="0 clear / 1 rising / 2 jammed",
                      why="when to start dropping"),
            DataInput("shared secret", feed_method="set_secret", units="bytes"),
            DataInput("crumb messages and ranges", feed_method="feed_message",
                      units="as layer 151"),
            DataInput("barometric altitude (optional)", feed_method="set_altitude",
                      units="m MSL, 1-sigma m"),
        ],
        preconditions=("crumbs dropped while the fix was trusted and tight",
                       "three or more crumbs in radio range (plus altitude), or four"),
        notes="Never drops on an untrusted or loose fix. Stamp sigma = fix sigma "
              "and wind sigma over the fall. Ground-level range, line of sight.",
    )

    CRUMB_FALL_MS = 15.0
    """**Assumption.** Terminal velocity of a ~40 g crumb with a streamer.
    Measure by dropping one."""
    UNKNOWN_WIND_SIGMA_MS = 5.0
    """**Assumption.** With no wind estimate yet, the stamp assumes calm air
    with this sigma -- a moderate day. The stamp is honest but loose; the
    record says the wind was unknown."""
    FIX_STALE_S = 2.0

    def __init__(self, policy: Optional[DropPolicy] = None):
        super().__init__(
            layer_id="breadcrumb_d28", layer_number=152,
            name="Breadcrumb Beacons (self-dropped, position-stamped)",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ALTITUDE],
            description="Ranges to small beacons the drone dropped on the way in, "
                        "each stamped with its landing position while the fix was "
                        "still trusted; a position inside the jammed zone.",
        )
        self.policy = policy or DropPolicy()
        self.inner = BeaconRangingLayer()
        self.inner.initialize()
        self._fix: Optional[Tuple[float, float, Optional[float], float, float, bool]] = None
        self._wind: Tuple[float, float, float] = (0.0, 0.0, float("inf"))
        self._agl: Optional[Tuple[float, float]] = None
        self._threat = THREAT_CLEAR
        self.crumbs: List[Crumb] = []
        self.last_drop_reason = "no drop considered yet"
        self.last: Optional[dict] = None

    # -- contract -------------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    # -- inputs ---------------------------------------------------------------

    def set_secret(self, secret: bytes) -> None:
        self.inner.set_secret(secret)

    def feed_fix(self, lat: float, lon: float, alt_m: Optional[float], sigma_m: float,
                 t: float, trusted: bool) -> None:
        self._fix = (lat, lon, alt_m, sigma_m, t, trusted)

    def feed_wind(self, north_ms: float, east_ms: float, sigma_ms: float) -> None:
        self._wind = (north_ms, east_ms, sigma_ms)

    def feed_agl(self, agl_m: float, t: float) -> None:
        self._agl = (agl_m, t)

    def feed_threat(self, level: int) -> None:
        self._threat = int(level)

    def feed_message(self, m: dict, now: float) -> str:
        if not str(m.get("id", "")).startswith(CRUMB_PREFIX):
            return "not a crumb"
        return self.inner.feed_message(m, now)

    def feed_range(self, beacon_id: str, range_m: float, sigma_m: float, t: float) -> str:
        if not str(beacon_id).startswith(CRUMB_PREFIX):
            return "not a crumb"
        return self.inner.feed_range(beacon_id, range_m, sigma_m, t)

    def set_altitude(self, alt_msl_m: float, sigma_m: float, t: float) -> None:
        self.inner.set_altitude(alt_msl_m, sigma_m, t)

    def set_prior(self, lat: float, lon: float) -> None:
        self.inner.set_prior(lat, lon)

    # -- dropping -------------------------------------------------------------

    def should_drop(self, t: float) -> Tuple[bool, str]:
        p = self.policy
        if len(self.crumbs) >= p.max_crumbs:
            return False, f"all {p.max_crumbs} crumbs dropped"
        if self._threat < p.start_at:
            return False, "threat clear: keeping the crumbs"
        if self._fix is None or t - self._fix[4] > self.FIX_STALE_S:
            return False, "no fresh fix"
        lat, lon, _, sigma, _, trusted = self._fix
        if not trusted:
            return False, "fix not trusted: a crumb stamped with a guess would poison later fixes"
        if sigma > p.max_drop_sigma_m:
            return False, f"fix sigma {sigma:.1f} m looser than {p.max_drop_sigma_m:.0f} m"
        if self._agl is None or t - self._agl[1] > 5.0:
            return False, "no height above ground for the fall time"
        if self.crumbs:
            # against the NEAREST crumb, not the last: on the way back the
            # drone passes its own crumbs and must not double them up
            d = min(math.hypot((lat - c.lat) * DEG_M,
                               (lon - c.lon) * DEG_M * math.cos(math.radians(lat)))
                    for c in self.crumbs)
            if d < p.spacing_m:
                return False, f"nearest crumb {d:.0f} m away (spacing {p.spacing_m:.0f} m)"
        return True, "drop"

    def drop(self, t: float) -> Optional[dict]:
        """Stamp and record a crumb; returns the provisioning record for the
        crumb's radio, or None (see last_drop_reason)."""
        ok, why = self.should_drop(t)
        self.last_drop_reason = why
        if not ok:
            return None
        lat, lon, alt, sigma, _, _ = self._fix
        agl = self._agl[0]
        fall = max(agl, 0.0) / self.CRUMB_FALL_MS
        wn, we, ws = self._wind
        wind_source = "estimate"
        if not math.isfinite(ws):
            wn, we, ws, wind_source = 0.0, 0.0, self.UNKNOWN_WIND_SIGMA_MS, "unknown"
        drift = (wn * fall, we * fall)
        stamp_lat = lat + drift[0] / DEG_M
        stamp_lon = lon + drift[1] / (DEG_M * math.cos(math.radians(lat)))
        stamp_sigma = math.hypot(sigma, ws * fall)
        ground_alt = None if alt is None else alt - agl
        crumb = Crumb(f"{CRUMB_PREFIX}{len(self.crumbs) + 1}", stamp_lat, stamp_lon,
                      ground_alt, stamp_sigma, t, sigma, drift, fall)
        self.crumbs.append(crumb)
        return {"type": "provision", "id": crumb.crumb_id, "lat": crumb.lat, "lon": crumb.lon,
                "alt_m": crumb.alt_m if crumb.alt_m is not None else 0.0,
                "sigma_m": crumb.sigma_m, "t": t, "wind_source": wind_source,
                "fall_s": fall}

    # -- the fix --------------------------------------------------------------

    def solve(self, now: float) -> dict:
        if not self.crumbs:
            self.last = {"status": "declined", "reason_code": NoFixReason.NO_INPUT,
                         "reason": "no crumbs dropped yet", "crumbs_dropped": 0,
                         "last_drop_reason": self.last_drop_reason}
            return self.last
        v = dict(self.inner.solve(now))
        v["crumbs_dropped"] = len(self.crumbs)
        v["crumbs_in_range"] = len(self.inner.usable(now))
        v["last_drop_reason"] = self.last_drop_reason
        self.last = v
        return v

    def read(self) -> LayerReading:
        now = max([c.t for c in self.crumbs] + [0.0])
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
