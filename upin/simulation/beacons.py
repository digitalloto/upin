"""
Simulated beacons: on the ground, on masts, or carried by weather balloons.
SIMULATION ONLY. Labelled models, not measurements.

A balloon beacon is launched from a point, climbs at ASCENT_MS, drifts with
a wind that strengthens with altitude (a simple labelled profile), and
bursts at BURST_ALT_M. It carries its own position source (a GNSS receiver
above the jammer, or ground tracking) with a stated sigma. All beacons send
signed, hopping messages every slot; the drone's radio measures a two-way
range with a stated sigma to every beacon above the elevation mask that is
not jammed on the beacon band.

Jamming: the world's JammingField governs. A zone that lists "BEACON" among
its constellations is a wideband or beacon-band jammer; a GNSS-only zone
leaves the beacons untouched. That is the whole point of a separate band.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from upin.layers.rf.beacon_ranging import DEG_M, hop_channel, sign_message
from upin.simulation.environment import JammingField

ASCENT_MS = 5.0
"""Typical latex weather-balloon ascent rate (about 1,000 ft/min)."""
BURST_ALT_M = 30_000.0
WIND_GRADIENT_PER_M = 1.0 / 8000.0
"""**Model.** Wind grows linearly with altitude: doubled by 8 km. Real
profiles vary; this is for exercising the layer, not forecasting."""
ELEVATION_MASK_DEG = 10.0
"""Beacons well above the drone (balloons) must be this high above the
horizon; low ones are hidden by terrain and the airframe."""
MAX_GROUND_RANGE_M = 5000.0
"""**Assumption.** Line-of-sight range to a ground or mast beacon from a
low-flying drone over flat ground. Measure on the real radio."""
LINK_MARGIN_DB = 20.0
"""**Assumption.** A jammer that knocks the beacon link's C/N0 down by more
than this breaks the ranging."""
RANGE_SIGMA_LORA_M = 10.0
"""**Assumption.** Two-way ranging precision of a LoRa-class 2.4 GHz module.
Measure on the real radio; UWB would be about 0.3 m at short range."""


@dataclass
class SimBeacon:
    beacon_id: str
    lat: float
    lon: float
    alt_m: float
    sigma_m: float                 # how well it knows its own position
    kind: str = "ground"           # ground | balloon | crumb | tethered
    launch_t: float = 0.0
    wind_ne_ms: Tuple[float, float] = (0.0, 0.0)
    # A crumb broadcasts the position it was STAMPED with, which differs
    # from where it really landed by the stamp's error. Truth is used for
    # the ranges; the stamp for the messages. Never mixed.
    stamped: Optional[Tuple[float, float, float]] = None
    # tethered aerostat: anchor at (lat, lon, alt_m), leaning downwind
    tether_m: float = 0.0
    aerostat_diameter_m: float = 3.0
    aerostat_net_lift_n: float = 60.0
    wind_sigma_ms: float = 0.0     # how well the wind at the aerostat is known

    def stated_sigma_m(self) -> float:
        """The position sigma the beacon broadcasts: its own, plus (for an
        aerostat) how much the wind's uncertainty moves it."""
        if self.kind != "tethered":
            return self.sigma_m
        from upin.simulation.balloon_physics import blowdown_sigma_m
        wind = math.hypot(*self.wind_ne_ms)
        return math.hypot(self.sigma_m, blowdown_sigma_m(
            self.tether_m, self.aerostat_diameter_m, self.aerostat_net_lift_n, wind,
            self.wind_sigma_ms))

    def position(self, t: float) -> Optional[Tuple[float, float, float]]:
        if self.kind == "tethered":
            from upin.simulation.balloon_physics import aerostat_blowdown
            wind = math.hypot(*self.wind_ne_ms)
            off, alt, _ = aerostat_blowdown(self.tether_m, self.aerostat_diameter_m,
                                            self.aerostat_net_lift_n, wind)
            if wind < 1e-9:
                return self.lat, self.lon, self.alt_m + alt
            un, ue = self.wind_ne_ms[0] / wind, self.wind_ne_ms[1] / wind
            return (self.lat + off * un / DEG_M,
                    self.lon + off * ue / (DEG_M * math.cos(math.radians(self.lat))),
                    self.alt_m + alt)
        if self.kind != "balloon":
            return self.lat, self.lon, self.alt_m
        dt = t - self.launch_t
        if dt < 0:
            return None
        alt = self.alt_m + ASCENT_MS * dt
        if alt > BURST_ALT_M:
            return None                                   # burst
        # drift = integral of wind(alt) dt with wind = w0 (1 + g alt)
        h0 = self.alt_m
        drift = dt + WIND_GRADIENT_PER_M * (h0 * dt + 0.5 * ASCENT_MS * dt * dt)
        n = self.lat + self.wind_ne_ms[0] * drift / DEG_M
        e = self.lon + self.wind_ne_ms[1] * drift / (DEG_M * math.cos(math.radians(self.lat)))
        return n, e, alt


class BeaconSim:
    def __init__(self, beacons: Sequence[SimBeacon], secret: bytes,
                 range_sigma_m: float = RANGE_SIGMA_LORA_M, seed: int = 0):
        self.beacons = list(beacons)
        self.secret = secret
        self.range_sigma_m = range_sigma_m
        self.rng = np.random.default_rng(seed)
        self._seq = {b.beacon_id: 0 for b in self.beacons}

    def messages(self, t: float, tamper: Optional[str] = None) -> List[dict]:
        out = []
        for b in self.beacons:
            p = b.position(t)
            if p is None:
                continue
            self._seq[b.beacon_id] += 1
            said = b.stamped if b.stamped is not None else p
            m = {"id": b.beacon_id, "t": t, "lat": said[0], "lon": said[1], "alt_m": said[2],
                 "sigma_m": b.stated_sigma_m(), "seq": self._seq[b.beacon_id],
                 "channel": hop_channel(self.secret, t)}
            if tamper == "unsigned":
                m["sig"] = "0" * 16
            elif tamper == "wrong_channel":
                # a channel the schedule does not use for this slot or its
                # neighbours (the receiver tolerates one slot of clock error)
                nearby = {hop_channel(self.secret, t + k) for k in (-1, 0, 1)}
                m["channel"] = next(c for c in range(32) if c not in nearby)
                m = sign_message(m, self.secret)
            elif tamper == "replay":
                m["seq"] = 1
                m = sign_message(m, self.secret)
            else:
                m = sign_message(m, self.secret)
            out.append(m)
        return out

    def drop_crumb(self, provision: dict, true_lat: float, true_lon: float,
                   true_alt_m: float) -> SimBeacon:
        """A crumb lands at its TRUE point and broadcasts its STAMP."""
        b = SimBeacon(provision["id"], true_lat, true_lon, true_alt_m, provision["sigma_m"],
                      kind="crumb",
                      stamped=(provision["lat"], provision["lon"], provision["alt_m"]))
        self.beacons.append(b)
        self._seq[b.beacon_id] = 0
        return b

    def ranges(self, lat: float, lon: float, alt_m: float, t: float,
               jamming: Optional[JammingField] = None) -> List[Tuple[str, float, float]]:
        """(beacon_id, measured range, sigma) for every beacon in view."""
        out = []
        jammed = (jamming is not None
                  and jamming.cn0_drop_db(lat, lon, "BEACON") > LINK_MARGIN_DB)
        if jammed:
            return out
        coslat = math.cos(math.radians(lat))
        for b in self.beacons:
            p = b.position(t)
            if p is None:
                continue
            dn = (p[0] - lat) * DEG_M
            de = (p[1] - lon) * DEG_M * coslat
            du = p[2] - alt_m
            horiz = math.hypot(dn, de)
            if du > 1000.0:                       # a balloon or other high beacon
                if math.degrees(math.atan2(du, max(horiz, 1e-6))) < ELEVATION_MASK_DEG:
                    continue
            elif horiz > MAX_GROUND_RANGE_M:      # a ground or mast beacon
                continue
            true_range = math.sqrt(dn * dn + de * de + du * du)
            out.append((b.beacon_id, true_range + self.rng.normal(0, self.range_sigma_m),
                        self.range_sigma_m))
        return out
