"""
What the console shows, built only from what UPIN actually computed.

Rules this file keeps, and the tests check:
- Every number comes from the box, the gateway, the filter or a sensor
  sample. Nothing is filled in, smoothed for looks, or defaulted.
- Anything absent is None, with a reason where one is known. The page shows
  None as "not connected" / "not available", never as a number.
- Simulation is labelled at the top level, so the page cannot show it
  without the banner. Truth exists only in simulation and is named as such.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from upin.detection.reachability import DEG_M

R95_PER_SIGMA = 2.4477
"""Per-axis 1-sigma to a 95% circle radius, for a circular Gaussian."""


def clean(x: Any) -> Any:
    """JSON-safe: NaN and infinity become None, tuples become lists."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dn = (lat2 - lat1) * DEG_M
    de = (lon2 - lon1) * DEG_M * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dn, de)


class ConsoleState:
    TRAIL = 900
    EVENTS = 200

    def __init__(self, source: str, label: str, simulated: bool,
                 controls: List[str], note: str = ""):
        self._lock = threading.Lock()
        self.source = {"kind": source, "label": label, "simulated": simulated,
                       "controls": controls, "note": note}
        self._epochs = 0
        self._times: Deque[float] = deque(maxlen=20)
        self._trail: Deque[list] = deque(maxlen=self.TRAIL)
        self._input_trail: Deque[list] = deque(maxlen=self.TRAIL)
        self._truth_trail: Deque[list] = deque(maxlen=self.TRAIL)
        self._events: Deque[dict] = deque(maxlen=self.EVENTS)
        self._last_mode: Optional[str] = None
        self._errors: Deque[float] = deque(maxlen=self.TRAIL)
        self._snapshot: Dict[str, Any] = {"source": self.source, "epochs": 0,
                                          "mode": None, "waiting": True}

    # -- events ----------------------------------------------------------

    def event(self, text: str, level: str = "info") -> None:
        with self._lock:
            self._events.appendleft({"t": time.time(), "level": level,
                                     "text": text})

    # -- one epoch ---------------------------------------------------------

    def update(self, box, out, sent, sending: bool,
               truth: Optional[dict] = None) -> None:
        """box: the Box that just processed an epoch; out: its
        GatewayOutput; sent: the GpsInput built for the flight controller;
        truth: simulation only."""
        if truth is not None and not self.source["simulated"]:
            raise ValueError("truth is only shown for simulated sources")
        now = time.time()
        ep = box.last_epoch
        gw = box.gateway
        st = box.fc.state
        est = gw.kf.estimate()
        region = gw.guard.region(ep.t if ep else 0.0)

        with self._lock:
            self._epochs += 1
            self._times.append(now)
            if out.mode != self._last_mode:
                level = {"TRUSTED": "good", "DEGRADED": "warn",
                         "NO_FIX": "bad"}.get(out.mode, "info")
                self._events.appendleft({"t": now, "level": level,
                                         "text": f"{out.mode}: {'; '.join(out.reasons)}"})
                self._last_mode = out.mode
            if out.lat is not None:
                self._trail.append([out.lat, out.lon, out.mode])
            if ep is not None and ep.fix_type >= 3:
                self._input_trail.append([ep.lat, ep.lon])
            error_m = None
            if truth is not None:
                self._truth_trail.append([truth["lat"], truth["lon"]])
                if out.lat is not None:
                    error_m = distance_m(out.lat, out.lon, truth["lat"], truth["lon"])
                    self._errors.append(error_m)

            rate = None
            if len(self._times) >= 2 and self._times[-1] > self._times[0]:
                rate = (len(self._times) - 1) / (self._times[-1] - self._times[0])

            def age(sample):
                return None if sample is None else max(0.0, (ep.t if ep else 0.0) - sample.t)

            snap = {
                "source": self.source,
                "waiting": False,
                "t_unix": now,
                "epochs": self._epochs,
                "rate_hz": rate,
                "processing_ms": box.last_processing_ms,
                "mode": out.mode,
                "reasons": list(out.reasons),
                "caveat": out.caveat,
                "output": None if out.lat is None else {
                    "lat": out.lat, "lon": out.lon, "alt_m": out.alt_m,
                    "h_acc_m": out.h_acc_m,
                    "r95_m": out.h_acc_m * R95_PER_SIGMA if out.h_acc_m else None,
                    "vel_ned_ms": out.vel_ned_ms, "num_sv": out.num_sv},
                "sent": {"sending": sending, "gps_id": sent.gps_id,
                         "gps_instance": sent.gps_id + 1,
                         "fix_type": sent.fix_type,
                         "horiz_accuracy": sent.horiz_accuracy if sent.fix_type else None},
                "input": None if ep is None else {
                    "fix_type": ep.fix_type,
                    "lat": ep.lat if ep.fix_type >= 3 else None,
                    "lon": ep.lon if ep.fix_type >= 3 else None,
                    "h_acc_m": ep.h_acc_m if ep.fix_type >= 3 else None,
                    "num_sv": ep.num_sv, "jamming_state": ep.jamming_state,
                    "denied_in_software": box.deny_gnss,
                    "second_fixes": [{"name": f.constellation, "lat": f.lat,
                                      "lon": f.lon, "sigma_m": f.sigma_m}
                                     for f in ep.constellation_fixes]},
                "checks": list(gw.last_checks),
                "region": None if region is None else {
                    "seconds_since_anchor": region["seconds_since_anchor"],
                    "manoeuvre_centre": region["manoeuvre_centre"],
                    "manoeuvre_radius_m": region["manoeuvre_radius_m"],
                    "speed_centre": region["speed_centre"],
                    "speed_radius_m": region["speed_radius_m"]},
                "estimate": None if est is None else {
                    "lat": est.lat, "lon": est.lon, "drms_m": est.drms_m,
                    "velocity_ne_ms": est.velocity_ne,
                    "sigma_velocity_ms": est.sigma_velocity_ms,
                    "heading_deg": est.heading_deg},
                "sensors": {
                    "heading": None if st.attitude is None else {
                        "deg": st.attitude.heading_deg, "age_s": age(st.attitude)},
                    "baro": None if st.baro is None else {
                        "press_hpa": st.baro.press_hpa,
                        "pressure_alt_m": st.baro.pressure_alt_m, "age_s": age(st.baro)},
                    "flow": None if st.flow is None else {
                        "forward_ms": st.flow.forward_ms, "right_ms": st.flow.right_ms,
                        "quality": st.flow.quality, "age_s": age(st.flow)},
                    "range": None if st.range is None else {
                        "m": st.range.distance_m, "age_s": age(st.range)},
                    "fc_gps": None if st.gps is None else {
                        "fix_type": st.gps.fix_type, "lat": st.gps.lat,
                        "lon": st.gps.lon, "h_acc_m": st.gps.h_acc_m,
                        "satellites": st.gps.satellites, "age_s": age(st.gps)},
                    "ignored_circular": dict(box.fc.ignored)},
                "signal_power": getattr(getattr(box, "power", None), "last_verdict", None)
                if ep is not None and ep.power_check is not None else None,
                "truth": None if truth is None else {
                    "label": "simulated truth", "lat": truth["lat"],
                    "lon": truth["lon"], "error_m": error_m,
                    "max_error_m": max(self._errors) if self._errors else None},
                "trail": list(self._trail),
                "input_trail": list(self._input_trail),
                "truth_trail": list(self._truth_trail),
                "events": list(self._events),
            }
            self._snapshot = clean(snap)

    def get(self) -> Dict[str, Any]:
        with self._lock:
            snap = dict(self._snapshot)
            snap["events"] = list(self._events)
            snap["source"] = self.source
            return snap
