"""
Runs the LEO Doppler layer on the box: waits for a pass, records it, fits
it, hands the fix to the gateway. UNTESTED against a real radio or sky.

  satellites.json   [{"name": "...", "tle1": "...", "tle2": "...", "carrier_hz": 137500000}]

Each cycle the runner asks each satellite's orbit whether it is above the
elevation mask from the box's current prior. During a pass it reads the
radio in one-second chunks, tracks the carrier, and feeds the layer. When
the satellite sets it solves, and an accepted fix goes to the gateway as
`leo_doppler` -- without re-anchoring the reachable region, because a fix
hundreds of metres wide must not narrow a physical bound.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import time
from typing import Callable, List, Optional

from upin.layers.satellite.doppler_track import track_carrier
from upin.layers.satellite.leo_doppler import LeoDopplerLayer, TleOrbit, enu_elevation_deg


class LeoPassRunner:
    UNTESTED = True
    ELEVATION_MASK_DEG = 10.0

    def __init__(self, satellites_file: str, sdr_factory: Callable[[float], object],
                 layer: LeoDopplerLayer, now_unix: Optional[float] = None):
        with open(satellites_file, encoding="utf-8") as f:
            entries = json.load(f)
        now = time.time() if now_unix is None else now_unix
        self.sats = [(e["name"], TleOrbit(e["tle1"], e["tle2"], e["name"], now), float(e["carrier_hz"]))
                     for e in entries]
        self.sdr_factory = sdr_factory
        self.layer = layer
        self._sdr = None
        self._active: Optional[int] = None
        self.status = "idle: no satellite above the mask"
        self.last_fix: Optional[dict] = None

    def step(self, prior_lat: float, prior_lon: float, prior_sigma_m: float,
             alt_m: float, alt_sigma_m: float, now_unix: float) -> Optional[dict]:
        """One cycle; returns a fix dict when a pass has just been solved."""
        up = [k for k, (_, orbit, _) in enumerate(self.sats)
              if enu_elevation_deg(prior_lat, prior_lon, alt_m, orbit.state_eci(now_unix)[0],
                                   now_unix) > self.ELEVATION_MASK_DEG]
        if self._active is None:
            if not up:
                return None
            self._active = up[0]
            name, orbit, carrier = self.sats[self._active]
            self._sdr = self.sdr_factory(carrier)
            self.layer.set_orbit(orbit, carrier)
            self.status = f"recording a pass of {name}"
            return None
        name, orbit, carrier = self.sats[self._active]
        if self._active in up:
            iq = self._sdr.read(1.0)
            for t, f_off, sigma in track_carrier(iq, self._sdr.sample_rate_hz, now_unix - 1.0):
                self.layer.feed_doppler(t, carrier + f_off, sigma)
            self.status = f"recording {name}: {len(self.layer._obs)} points"
            return None
        # the satellite has set: solve
        self.layer.set_prior(prior_lat, prior_lon, prior_sigma_m)
        self.layer.set_altitude(alt_m, alt_sigma_m)
        v = dict(self.layer.solve())
        self._sdr.close()
        self._sdr, self._active = None, None
        self.layer.clear()
        self.status = (f"{name}: fix ±{v['sigma_m']:.0f} m" if v["status"] == "ok"
                       else f"{name}: {v['reason']}")
        self.last_fix = v
        return v
