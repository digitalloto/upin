"""
Where the console's data comes from. Every source runs the real UPIN box
(Box -> Gateway -> HonestKalman) on its input; only the input differs.

  sim      SIMULATED sensors: a drone flying a circuit, with spoofing and
           GNSS denial you can switch on. It speaks the receiver's own UBX
           protocol and the flight controller's MAVLink fields, so the data
           goes through the same parser and checks as real data. Labelled
           SIMULATION everywhere; the true position is shown as such.
  browser  This device's own location, from the browser (the part of the old
           phone demo that was real). Real data, poor accuracy: phone or
           laptop location, not a GNSS receiver.
  board    The flight controller on USB, its own GPS as the input. Real data.
  live     The full box: the new receiver plus the flight controller.
  replay   A box log, re-decided by today's code.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from typing import List, Optional

from upin.box.fc_reader import P0_HPA
from upin.box.gnss_parser import encode_mon_rf, encode_nav_pvt, encode_nav_sat
from upin.box.gateway import GnssEpoch
from upin.box.replay import epoch_from_json
from upin.box.service import Box, BoxConfig
from upin.console.state import ConsoleState
from upin.detection.reachability import DEG_M

W3C_95_TO_SIGMA = 1.0 / 2.4477
"""Browser location accuracy is a 95% radius (W3C Geolocation API); per-axis
1-sigma is that divided by 2.45."""


class Msg:
    """A MAVLink-shaped message: get_type() plus the field names."""

    def __init__(self, kind, **fields):
        self._kind = kind
        self.__dict__.update(fields)

    def get_type(self):
        return self._kind


class Source:
    controls: List[str] = []

    def __init__(self, state: ConsoleState):
        self.state = state
        self._stop = threading.Event()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._stop.set()

    def control(self, action: str) -> str:
        return f"'{action}' is not available for this source"


# -- simulation -------------------------------------------------------------

class _GaussMarkov:
    """Correlated error: GNSS errors persist for tens of seconds."""

    def __init__(self, rng, sigma, tau_s):
        self.rng, self.sigma, self.tau = rng, sigma, tau_s
        self.x = rng.gauss(0, sigma)

    def step(self, dt):
        a = math.exp(-dt / self.tau)
        self.x = a * self.x + math.sqrt(1 - a * a) * self.rng.gauss(0, self.sigma)
        return self.x


class SimSource(Source):
    """A drone flying a stadium-shaped circuit at constant speed."""

    controls = ["spoof_jump", "spoof_drag", "smart_spoofer", "deny", "flow", "reset"]

    STRAIGHT_M, RADIUS_M, SPEED_MS, ALT_M = 300.0, 60.0, 8.0, 50.0
    GNSS_SIGMA_M, GNSS_TAU_S, FC_GNSS_SIGMA_M = 1.5, 30.0, 2.0
    VEL_SIGMA_MS, HEADING_SIGMA_DEG, FLOW_SIGMA_MS = 0.1, 2.0, 0.2
    SPOOF_JUMP_M, SPOOF_DRAG_MS = 500.0, 1.0
    # Simulated sky (a labelled MODEL for exercising the signal-power layer,
    # not measured data): C/N0 = 30 + 0.2 x elevation + noise, dB-Hz.
    SKY = [("gps", 3, 12), ("gps", 7, 24), ("navic", 2, 31), ("galileo", 11, 38),
           ("gps", 14, 46), ("navic", 5, 53), ("galileo", 19, 61), ("gps", 22, 68),
           ("gps", 28, 77), ("navic", 7, 85)]
    CN0_BASE, CN0_PER_DEG, CN0_SIGMA = 30.0, 0.2, 1.5
    AGC_NORMAL, AGC_SIGMA = 3000.0, 20.0
    SPOOF_CN0, SPOOF_AGC, JAM_AGC = 46.0, 2300.0, 1800.0

    def __init__(self, state, start_lat, start_lon, speed=1.0, seed=None,
                 cfg: Optional[BoxConfig] = None):
        super().__init__(state)
        self.start_lat, self.start_lon = start_lat, start_lon
        self.speed = speed
        self.seed = seed
        self.cfg = cfg or BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0)
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self.rng = random.Random(self.seed)
        self.box = Box(self.cfg)
        self.t = 0.0
        self.err = [_GaussMarkov(self.rng, self.GNSS_SIGMA_M, self.GNSS_TAU_S) for _ in range(2)]
        self.fc_err = [_GaussMarkov(self.rng, self.FC_GNSS_SIGMA_M, self.GNSS_TAU_S) for _ in range(2)]
        self.spoof_jump = self.spoof_drag = self.deny = False
        self.flow = True
        self.smart = False
        self.drag_m = 0.0

    def truth(self, t):
        """(north, east, vn, ve) on the circuit at time t."""
        L, R, v = self.STRAIGHT_M, self.RADIUS_M, self.SPEED_MS
        P = 2 * L + 2 * math.pi * R
        s = (v * t) % P
        if s < L:                                   # south straight, eastbound
            return -R, -L / 2 + s, 0.0, v
        s -= L
        if s < math.pi * R:                         # east turn
            a = -math.pi / 2 + s / R
            return R * math.sin(a), L / 2 + R * math.cos(a), v * math.cos(a), -v * math.sin(a)
        s -= math.pi * R
        if s < L:                                   # north straight, westbound
            return R, L / 2 - s, 0.0, -v
        s -= L                                      # west turn
        a = math.pi / 2 + s / R
        return R * math.sin(a), -L / 2 + R * math.cos(a), v * math.cos(a), -v * math.sin(a)

    def _ll(self, n, e):
        return (self.start_lat + n / DEG_M,
                self.start_lon + e / (DEG_M * math.cos(math.radians(self.start_lat))))

    def control(self, action):
        with self._lock:
            if action == "spoof_jump":
                self.spoof_jump = not self.spoof_jump
                msg = (f"SIMULATION: spoofer {'ON' if self.spoof_jump else 'OFF'}, "
                       f"position jumped {self.SPOOF_JUMP_M:.0f} m east on both receivers")
            elif action == "spoof_drag":
                self.spoof_drag = not self.spoof_drag
                if not self.spoof_drag:
                    self.drag_m = 0.0
                msg = (f"SIMULATION: slow drag-off spoof {'ON' if self.spoof_drag else 'OFF'} "
                       f"({self.SPOOF_DRAG_MS:.0f} m/s north, both receivers)")
            elif action == "smart_spoofer":
                self.smart = not self.smart
                kind = ("SMART: shapes each satellite's power by elevation, "
                        "as a real sky would" if self.smart else
                        "simple: one transmitter, uniform power")
                msg = f"SIMULATION: spoofer type now {kind} (applies when a spoof is on)"
            elif action == "deny":
                self.deny = not self.deny
                msg = f"SIMULATION: GNSS {'jammed (no fix)' if self.deny else 'restored'}"
            elif action == "flow":
                self.flow = not self.flow
                msg = f"SIMULATION: optical-flow sensor {'ON' if self.flow else 'OFF'}"
            elif action == "reset":
                self._reset()
                msg = "SIMULATION: reset"
            else:
                return super().control(action)
        self.state.event(msg, "sim")
        return msg

    def step(self, dt=1.0):
        """One simulated second: flight-controller messages, then a receiver
        epoch, all through the real box."""
        with self._lock:
            self.t += dt
            t, rng, box = self.t, self.rng, self.box
            n, e, vn, ve = self.truth(t)
            heading = math.degrees(math.atan2(ve, vn)) % 360.0
            errs = [g.step(dt) for g in self.err]
            fc_errs = [g.step(dt) for g in self.fc_err]
            if self.spoof_drag:
                self.drag_m += self.SPOOF_DRAG_MS * dt
            sn = self.drag_m
            se = self.SPOOF_JUMP_M if self.spoof_jump else 0.0

            box.on_fc_message(Msg("ATTITUDE", roll=0.0, pitch=0.0, yaw=math.radians(
                heading + rng.gauss(0, self.HEADING_SIGMA_DEG))), t)
            press = P0_HPA * (1 - self.ALT_M / 44330.0) ** 5.255
            box.on_fc_message(Msg("SCALED_PRESSURE", press_abs=press + rng.gauss(0, 0.05),
                                  temperature=3000), t)
            if self.flow:
                speed = math.hypot(vn, ve)
                box.on_fc_message(Msg("OPTICAL_FLOW",
                                      flow_comp_m_x=speed + rng.gauss(0, self.FLOW_SIGMA_MS),
                                      flow_comp_m_y=rng.gauss(0, self.FLOW_SIGMA_MS),
                                      quality=200, ground_distance=self.ALT_M), t)
            if self.deny:
                box.on_fc_message(Msg("GPS_RAW_INT", fix_type=1, lat=0, lon=0, alt=0,
                                      satellites_visible=0, h_acc=0), t)
            else:
                flat, flon = self._ll(n + fc_errs[0] + sn, e + fc_errs[1] + se)
                box.on_fc_message(Msg("GPS_RAW_INT", fix_type=3, lat=round(flat * 1e7),
                                      lon=round(flon * 1e7), alt=round(self.ALT_M * 1000),
                                      satellites_visible=12,
                                      h_acc=round(self.FC_GNSS_SIGMA_M * 1000)), t)

            spoofing = self.spoof_jump or self.spoof_drag
            sky, agc = [], self.AGC_NORMAL + rng.gauss(0, self.AGC_SIGMA)
            for i, (gnss, sv, base_elev) in enumerate(self.SKY):
                elev = base_elev + 3.0 * math.sin(t / 600.0 + i)
                real = self.CN0_BASE + self.CN0_PER_DEG * elev + rng.gauss(0, self.CN0_SIGMA)
                if self.deny:
                    cn0 = 0.0
                elif spoofing and self.smart:
                    cn0 = real + 2.0
                elif spoofing:
                    cn0 = self.SPOOF_CN0 + rng.gauss(0, 0.8)
                else:
                    cn0 = real
                sky.append((gnss, sv, cn0, elev, (37 * i) % 360, cn0 > 0))
            if self.deny:
                agc = self.JAM_AGC + rng.gauss(0, self.AGC_SIGMA)
            elif spoofing and not self.smart:
                agc = self.SPOOF_AGC + rng.gauss(0, self.AGC_SIGMA)
            sat_bytes = encode_nav_sat(int(t * 1000), sky)

            h_acc = self.GNSS_SIGMA_M
            if self.deny:
                data = sat_bytes + encode_mon_rf("critical", 240, round(agc), 200) + encode_nav_pvt(
                    int(t * 1000), 0.0, 0.0, 0.0, 0.0, 0.0, (0.0, 0.0, 0.0), 0.0,
                    fix_type=0, num_sv=0)
            else:
                lat, lon = self._ll(n + errs[0] + sn, e + errs[1] + se)
                v_spoof = self.SPOOF_DRAG_MS if self.spoof_drag else 0.0
                data = sat_bytes + encode_mon_rf("ok", 90, round(agc), 10) + encode_nav_pvt(
                    int(t * 1000), lat, lon, self.ALT_M, h_acc, 3.0,
                    (vn + v_spoof + rng.gauss(0, self.VEL_SIGMA_MS),
                     ve + rng.gauss(0, self.VEL_SIGMA_MS), 0.0),
                    self.VEL_SIGMA_MS * 1.5)
            results = box.on_receiver_bytes(data, t, time.time())
            tlat, tlon = self._ll(n, e)
            for out, sent in results:
                self.state.update(box, out, sent, sending=False,
                                  truth={"lat": tlat, "lon": tlon})
            return results

    def start(self):
        def loop():
            while not self._stop.is_set():
                self.step(1.0)
                self._stop.wait(1.0 / self.speed)
        threading.Thread(target=loop, daemon=True).start()


# -- this device's location ---------------------------------------------------

class BrowserSource(Source):
    controls = ["deny"]

    def __init__(self, state, cfg: Optional[BoxConfig] = None):
        super().__init__(state)
        self.cfg = cfg or BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0)
        self.box = Box(self.cfg)
        self._lock = threading.Lock()

    def control(self, action):
        if action != "deny":
            return super().control(action)
        with self._lock:
            self.box.deny_gnss = not self.box.deny_gnss
            msg = f"GNSS {'DENIED in software' if self.box.deny_gnss else 'restored'}"
        self.state.event(msg, "warn")
        return msg

    def fix(self, d: dict) -> str:
        """One location from the browser. Fields as the Geolocation API gives
        them; accuracy is a 95% radius in metres."""
        try:
            lat, lon, acc = float(d["lat"]), float(d["lon"]), float(d["accuracy"])
        except (KeyError, TypeError, ValueError):
            return "refused: needs lat, lon and accuracy"
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and acc > 0):
            return "refused: out of range"
        vel = None
        speed, heading = d.get("speed"), d.get("heading")
        if speed is not None and heading is not None and math.isfinite(float(heading)):
            h = math.radians(float(heading))
            vel = (float(speed) * math.cos(h), float(speed) * math.sin(h), 0.0)
        alt = d.get("altitude")
        with self._lock:
            now = time.monotonic()
            ep = (GnssEpoch(t=now, fix_type=0) if self.box.deny_gnss else
                  GnssEpoch(t=now, fix_type=3, lat=lat, lon=lon,
                            alt_m=float(alt) if alt is not None else None,
                            h_acc_m=acc * W3C_95_TO_SIGMA,
                            # The browser gives no velocity accuracy, so its
                            # velocity is shown but not fused.
                            vel_ned_ms=vel, s_acc_ms=None))
            out, sent = self.box.process(ep, time.time())
            self.state.update(self.box, out, sent, sending=False)
        return out.mode


# -- the real box -------------------------------------------------------------

class LiveSource(Source):
    """The box service in a thread. gnss_source "receiver" is the full box;
    "fc" is board-only. The deny control exists only with allow_control."""

    def __init__(self, state, cfg: BoxConfig, gnss_source: str, send: bool,
                 allow_control: bool):
        super().__init__(state)
        self.cfg, self.gnss_source = cfg, gnss_source
        self.send = send and gnss_source == "receiver"
        self.controls = ["deny"] if allow_control else []
        self.box = None

    def control(self, action):
        if action != "deny" or "deny" not in self.controls or self.box is None:
            return super().control(action)
        self.box.deny_gnss = not self.box.deny_gnss
        msg = f"GNSS {'DENIED in software' if self.box.deny_gnss else 'restored'}"
        self.state.event(msg, "warn")
        return msg

    def start(self):
        from upin.box.service import run

        def on_start(box):
            self.box = box

        def on_result(box, out, sent):
            self.state.update(box, out, sent, sending=self.send)

        def target():
            try:
                run(self.cfg, send=self.send, gnss_source=self.gnss_source,
                    on_start=on_start, on_result=on_result,
                    stop=self._stop.is_set)
            except (SystemExit, Exception) as exc:   # shown, not swallowed
                self.state.event(f"box stopped: {exc}", "bad")
        threading.Thread(target=target, daemon=True).start()


class ReplaySource(Source):
    def __init__(self, state, path: str, cfg: BoxConfig, speed: float = 1.0):
        super().__init__(state)
        self.path, self.cfg, self.speed = path, cfg, speed

    def start(self):
        def loop():
            box = Box(self.cfg)
            with open(self.path, encoding="utf-8") as f:
                epochs = [epoch_from_json(l) for l in f if l.strip()]
            self.state.event(f"replaying {len(epochs)} epochs from {self.path} "
                             f"(GNSS decisions only; FC sensors are not replayed)")
            last_t = None
            for ep in epochs:
                if self._stop.is_set():
                    return
                if last_t is not None and ep.t > last_t:
                    self._stop.wait((ep.t - last_t) / self.speed)
                last_t = ep.t
                out, sent = box.process(ep, time.time())
                self.state.update(box, out, sent, sending=False)
            self.state.event("replay finished")
        threading.Thread(target=loop, daemon=True).start()
