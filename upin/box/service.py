"""
The program the Pi runs: receiver in, flight controller in and out.

  receiver (UART/USB) --UBX--> parse --> gateway --> GPS_INPUT --> flight controller
  flight controller --MAVLink--> heading, baro, optical flow, its own GPS --^

  python -m upin.box.service --config box.toml
  python -m upin.box.service --config box.toml --deny-gnss   # GNSS denied in software
  python -m upin.box.service --config box.toml --deny-after 60 --deny-for 120
      # trusted GNSS for 60 s, then denied in software for 120 s, then back:
      # the GPS-denied test. UPIN can only coast after a trusted fix, so
      # denying from the start shows nothing but NO_FIX.
  python -m upin.box.service --config box.toml --no-send     # listen and log only

Every epoch is one JSON line in the log: what the receiver said, what the
flight controller's GPS said, the gateway's decision and why, and exactly
what was sent. `python -m upin.box.replay` re-runs the GNSS decisions from it
(without the flight-controller inputs, which are logged but not replayed).

SHADOW MODE (the default) sends to GPS 2. The flight controller keeps
navigating on its own GPS 1, as long as its parameters say so (see
docs/HARDWARE.md). That is a flight-controller setting this code cannot
enforce. Check it on the ground station before every flight.

If the receiver goes silent, no GPS_INPUT is sent and the flight controller
sees GPS 2 lost: its own failsafe, by design.

The Box class is pure logic and is tested. `run()` opens the serial port and
the MAVLink link; it is UNTESTED until it meets ArduPilot SITL or a bench
flight controller.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import argparse
import json
import time
import tomllib
from dataclasses import dataclass, fields
from typing import IO, List, Optional, Tuple

from upin.box.fc_reader import Attitude, Baro, FcGps, FcReader, Flow, request_streams
from upin.box.gateway import TRUSTED, Gateway, GatewayOutput, GnssEpoch
from upin.box.gnss_parser import MonRf, NavPvt, UbxStream, decode_ubx
from upin.box.mavlink_out import GpsInput, GpsInputSender, build
from upin.box.replay import epoch_to_json
from upin.detection.constellation_check import ConstellationFix
from upin.detection.reachability import Envelope


@dataclass
class BoxConfig:
    # airframe -- from its spec, never tuned to a result
    max_accel_ms2: float
    max_airspeed_ms: float
    max_wind_ms: float = 15.0
    # ports
    receiver_port: str = "/dev/ttyUSB0"
    receiver_baud: int = 115200
    fc_connection: str = "/dev/ttyAMA0"
    fc_baud: int = 921600
    # output
    gps_id: int = 1                 # 1 = GPS 2 on the flight controller
    shadow: bool = True
    forward_degraded: bool = False
    max_degraded_h_acc_m: float = 50.0
    # sensor noise -- ASSUMPTIONS until measured on the airframe
    heading_sigma_deg: float = 5.0
    flow_sigma_ms: float = 0.3
    min_flow_quality: int = 100
    baro_sigma_m: float = 1.0
    fc_gps_max_age_s: float = 1.0
    log_path: str = "upin_box.jsonl"


def load_config(path: str) -> BoxConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    flat = {}
    for section in raw.values():
        if isinstance(section, dict):
            flat.update(section)
    known = {f.name for f in fields(BoxConfig)}
    unknown = sorted(set(flat) - known)
    if unknown:
        raise ValueError(f"unknown config keys: {unknown}")
    cfg = BoxConfig(**flat)
    if cfg.shadow and cfg.gps_id == 0:
        raise ValueError("shadow mode must not send as GPS 1 (gps_id 0): "
                         "use gps_id = 1 so the flight controller keeps its own GPS")
    return cfg


class Box:
    def __init__(self, cfg: BoxConfig, deny_gnss: bool = False,
                 log: Optional[IO[str]] = None):
        self.cfg = cfg
        self.deny_gnss = deny_gnss
        self.log = log
        self.gateway = Gateway(Envelope(cfg.max_accel_ms2, cfg.max_airspeed_ms,
                                        cfg.max_wind_ms),
                               max_degraded_h_acc_m=cfg.max_degraded_h_acc_m)
        self.fc = FcReader()
        self.ubx = UbxStream()
        self._jamming = "unknown"
        self._baro_offset: Optional[float] = None
        self._last_mode: Optional[str] = None
        self.last_epoch: Optional[GnssEpoch] = None
        self.last_record: Optional[dict] = None
        self.last_processing_ms: Optional[float] = None

    # -- flight controller ---------------------------------------------------

    def on_fc_message(self, msg, now: float):
        s = self.fc.handle(msg, now)
        cfg = self.cfg
        if isinstance(s, Attitude):
            self.gateway.feed_heading(s.heading_deg, cfg.heading_sigma_deg, now,
                                      source="fc_attitude")
        elif isinstance(s, Flow):
            att = self.fc.state.attitude
            if s.quality >= cfg.min_flow_quality and att and now - att.t < 0.5:
                self.gateway.feed_flow(s.forward_ms, s.right_ms, att.heading_deg,
                                       cfg.flow_sigma_ms, now)
        elif isinstance(s, Baro):
            # Only while GNSS is not trusted, and only as a change since the
            # last trusted fix: pressure altitude drifts with the weather.
            if self._last_mode != TRUSTED and self._baro_offset is not None:
                self.gateway.feed_altitude(s.pressure_alt_m - self._baro_offset,
                                           cfg.baro_sigma_m, now)
        return s

    # -- receiver ------------------------------------------------------------

    def on_receiver_bytes(self, data: bytes, now: float,
                          unix_s: float) -> List[Tuple[GatewayOutput, GpsInput]]:
        results = []
        for cls, mid, payload in self.ubx.feed(data):
            msg = decode_ubx(cls, mid, payload)
            if isinstance(msg, MonRf):
                self._jamming = msg.worst_state
            elif isinstance(msg, NavPvt):
                results.append(self.process(self._epoch(msg, now), unix_s, msg))
        return results

    def epoch_from_fc_gps(self, g: FcGps, now: float) -> GnssEpoch:
        """Board-only mode: the flight controller's own GPS is the input.
        No jamming report and no second receiver to cross-check against;
        the checks say so. h_acc must be reported, or the fix is unusable."""
        if self.deny_gnss:
            return GnssEpoch(t=now, fix_type=0)
        if g.h_acc_m is None:       # a fix with no stated accuracy: refused
            return GnssEpoch(t=now, fix_type=g.fix_type, lat=g.lat, lon=g.lon,
                             num_sv=g.satellites)
        vel = None
        if g.vel_ne_ms is not None and g.vel_acc_ms:
            vel = (g.vel_ne_ms[0], g.vel_ne_ms[1], 0.0)
        return GnssEpoch(t=now, fix_type=g.fix_type, lat=g.lat, lon=g.lon,
                         alt_m=g.alt_m, h_acc_m=g.h_acc_m, vel_ned_ms=vel,
                         s_acc_ms=g.vel_acc_ms if vel else None,
                         num_sv=g.satellites)

    def _epoch(self, pvt: NavPvt, now: float) -> GnssEpoch:
        if self.deny_gnss:
            return GnssEpoch(t=now, fix_type=0, jamming_state=self._jamming)
        fix_type = pvt.fix_type if pvt.gnss_fix_ok else 0
        fixes = []
        g = self.fc.state.gps
        if (fix_type >= 3 and g and g.fix_type >= 3 and g.h_acc_m
                and now - g.t <= self.cfg.fc_gps_max_age_s):
            fixes = [ConstellationFix("box_receiver", pvt.lat, pvt.lon, pvt.h_acc_m),
                     ConstellationFix("fc_gps", g.lat, g.lon, g.h_acc_m)]
        return GnssEpoch(
            t=now, fix_type=fix_type, lat=pvt.lat, lon=pvt.lon,
            alt_m=pvt.height_msl_m, h_acc_m=pvt.h_acc_m, v_acc_m=pvt.v_acc_m,
            vel_ned_ms=pvt.vel_ned_ms, s_acc_ms=pvt.s_acc_ms, num_sv=pvt.num_sv,
            jamming_state=self._jamming, constellation_fixes=fixes)

    def process(self, ep: GnssEpoch, unix_s: float,
                pvt: Optional[NavPvt] = None) -> Tuple[GatewayOutput, GpsInput]:
        started = time.perf_counter()
        out = self.gateway.process(ep)
        self.last_processing_ms = (time.perf_counter() - started) * 1000.0
        baro = self.fc.state.baro
        if (out.mode == TRUSTED and ep.alt_m is not None and baro
                and ep.t - baro.t < 1.0):
            self._baro_offset = baro.pressure_alt_m - ep.alt_m
        self._last_mode = out.mode
        sent = build(out, unix_s, self.cfg.forward_degraded, gps_id=self.cfg.gps_id)
        self.last_epoch = ep
        self.last_record = self._record(ep, out, sent, unix_s, pvt)
        if self.log is not None:
            self.log.write(json.dumps(self.last_record) + "\n")
            self.log.flush()
        return out, sent

    def _record(self, ep, out, sent, unix_s, pvt):
        g, att, flow = self.fc.state.gps, self.fc.state.attitude, self.fc.state.flow
        return {
            "t": ep.t, "unix": unix_s, "deny_gnss": self.deny_gnss,
            "epoch": json.loads(epoch_to_json(ep)),
            "receiver": None if pvt is None else {
                "fix_type": pvt.fix_type, "lat": pvt.lat, "lon": pvt.lon,
                "alt_m": pvt.height_msl_m, "h_acc_m": pvt.h_acc_m,
                "num_sv": pvt.num_sv, "jamming": self._jamming},
            "fc_gps": None if g is None else {
                "fix_type": g.fix_type, "lat": g.lat, "lon": g.lon,
                "h_acc_m": g.h_acc_m, "age_s": ep.t - g.t},
            "heading_deg": None if att is None else att.heading_deg,
            "flow": None if flow is None else {
                "forward_ms": flow.forward_ms, "right_ms": flow.right_ms,
                "quality": flow.quality},
            "mode": out.mode, "reasons": out.reasons,
            "lat": out.lat, "lon": out.lon, "h_acc_m": out.h_acc_m,
            "sent": {"gps_id": sent.gps_id, "fix_type": sent.fix_type,
                     "lat": sent.lat, "lon": sent.lon,
                     "horiz_accuracy": sent.horiz_accuracy},
            "ignored_circular": dict(self.fc.ignored),
        }


class DenySchedule:
    """Software GNSS denial for tests: after GNSS has been TRUSTED for
    `after_s` seconds, deny it for `for_s` seconds, then let it back once."""

    def __init__(self, after_s: Optional[float], for_s: float = 60.0):
        self.after_s = after_s
        self.for_s = for_s
        self._trusted_since: Optional[float] = None
        self._denied_from: Optional[float] = None
        self.finished = False

    def denied(self, last_mode: Optional[str], now: float) -> bool:
        if self.after_s is None or self.finished:
            return False
        if self._denied_from is not None:
            if now - self._denied_from >= self.for_s:
                self.finished = True
                return False
            return True
        if last_mode == TRUSTED:
            if self._trusted_since is None:
                self._trusted_since = now
            if now - self._trusted_since >= self.after_s:
                self._denied_from = now
                return True
        else:
            self._trusted_since = None
        return False


def run(cfg: BoxConfig, deny_gnss: bool = False, send: bool = True,
        schedule: Optional[DenySchedule] = None, gnss_source: str = "receiver",
        on_start=None, on_result=None, stop=None) -> None:
    """The live loop. UNTESTED: needs pyserial, pymavlink, a receiver and a
    flight controller or SITL.

    gnss_source "receiver": the new GNSS receiver on its own port (the box).
    gnss_source "fc": board only -- the flight controller's own GPS is the
    input, for testing UPIN with just the board. Never sends: GPS 2 would
    only echo GPS 1 back.

    on_start(box) and on_result(box, out, sent) let the console watch;
    stop() returning True ends the loop."""
    try:
        import serial  # noqa: WPS433 -- lazy by design
        from pymavlink import mavutil  # noqa: WPS433
    except ImportError as exc:
        raise SystemExit("needs `pip install pyserial pymavlink` "
                         "(see deploy/install.sh)") from exc
    if gnss_source == "fc" and send:
        print("board-only mode: not sending GPS_INPUT (it would echo GPS 1)")
        send = False
    rx = (serial.Serial(cfg.receiver_port, cfg.receiver_baud, timeout=0.02)
          if gnss_source == "receiver" else None)
    conn = mavutil.mavlink_connection(cfg.fc_connection, baud=cfg.fc_baud,
                                      source_system=1, source_component=191)
    print(f"waiting for flight controller heartbeat on {cfg.fc_connection} ...")
    if conn.wait_heartbeat(timeout=30) is None:
        raise SystemExit("no heartbeat from the flight controller")
    request_streams(conn)
    sender = GpsInputSender(cfg.fc_connection, cfg.forward_degraded,
                            gps_id=cfg.gps_id, conn=conn)
    print(f"UPIN box running: GNSS from {gnss_source}, GPS instance "
          f"{cfg.gps_id + 1}, {'shadow' if cfg.shadow else 'LIVE'}, "
          f"{'GNSS DENIED in software, ' if deny_gnss else ''}"
          f"{'sending' if send else 'NOT sending'}; log {cfg.log_path}")
    with open(cfg.log_path, "a", encoding="utf-8") as log:
        box = Box(cfg, deny_gnss, log)
        if on_start is not None:
            on_start(box)
        last_mode = None
        while stop is None or not stop():
            if rx is not None:
                data = rx.read(rx.in_waiting or 1)
            else:
                data = b""
                time.sleep(0.02)
            now, unix_s = time.monotonic(), time.time()
            if schedule is not None:
                was = box.deny_gnss
                box.deny_gnss = schedule.denied(box._last_mode, now)
                if box.deny_gnss != was:
                    print(f"{time.strftime('%H:%M:%S')} --- GNSS "
                          f"{'DENIED in software' if box.deny_gnss else 'restored'} ---")
            results = []
            while True:
                msg = conn.recv_match(blocking=False)
                if msg is None:
                    break
                sample = box.on_fc_message(msg, now)
                if gnss_source == "fc" and isinstance(sample, FcGps):
                    results.append(box.process(box.epoch_from_fc_gps(sample, now),
                                               unix_s))
            results += box.on_receiver_bytes(data, now, unix_s)
            for out, sent in results:
                if send:
                    sender.send(out, unix_s)
                if on_result is not None:
                    on_result(box, out, sent)
                if out.mode != last_mode:
                    print(f"{time.strftime('%H:%M:%S')} {out.mode}: "
                          f"{'; '.join(out.reasons)}")
                    last_mode = out.mode


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="UPIN box: GNSS checks, then "
                                 "GPS_INPUT to the flight controller")
    ap.add_argument("--config", required=True)
    ap.add_argument("--deny-gnss", action="store_true",
                    help="drop GNSS in software, for GPS-denied tests")
    ap.add_argument("--no-send", action="store_true",
                    help="listen and log only; send nothing to the flight controller")
    ap.add_argument("--deny-after", type=float, metavar="S",
                    help="after S seconds of trusted GNSS, deny it in software")
    ap.add_argument("--deny-for", type=float, default=60.0, metavar="S",
                    help="how long --deny-after denies GNSS (default 60 s)")
    a = ap.parse_args(argv)
    if a.deny_gnss and a.deny_after is not None:
        ap.error("use --deny-gnss or --deny-after, not both")
    schedule = DenySchedule(a.deny_after, a.deny_for) if a.deny_after is not None else None
    run(load_config(a.config), deny_gnss=a.deny_gnss, send=not a.no_send,
        schedule=schedule)


if __name__ == "__main__":
    main()
