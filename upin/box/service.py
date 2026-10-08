"""
The program the Pi runs: receiver in, flight controller in and out.

  receiver (UART/USB) --UBX--> parse --> gateway --> GPS_INPUT --> flight controller
  flight controller --MAVLink--> heading, baro, optical flow, its own GPS --^

  python -m upin.box.service --config box.toml
  python -m upin.box.service --config box.toml --deny-gnss   # GNSS denied in software
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

from upin.box.fc_reader import Attitude, Baro, FcReader, Flow, request_streams
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
        out = self.gateway.process(ep)
        baro = self.fc.state.baro
        if (out.mode == TRUSTED and ep.alt_m is not None and baro
                and ep.t - baro.t < 1.0):
            self._baro_offset = baro.pressure_alt_m - ep.alt_m
        self._last_mode = out.mode
        sent = build(out, unix_s, self.cfg.forward_degraded, gps_id=self.cfg.gps_id)
        if self.log is not None:
            self.log.write(json.dumps(self._record(ep, out, sent, unix_s, pvt)) + "\n")
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


def run(cfg: BoxConfig, deny_gnss: bool = False, send: bool = True) -> None:
    """The live loop. UNTESTED: needs pyserial, pymavlink, a receiver and a
    flight controller or SITL."""
    try:
        import serial  # noqa: WPS433 -- lazy by design
        from pymavlink import mavutil  # noqa: WPS433
    except ImportError as exc:
        raise SystemExit("needs `pip install pyserial pymavlink` "
                         "(see deploy/install.sh)") from exc
    rx = serial.Serial(cfg.receiver_port, cfg.receiver_baud, timeout=0.02)
    conn = mavutil.mavlink_connection(cfg.fc_connection, baud=cfg.fc_baud,
                                      source_system=1, source_component=191)
    print(f"waiting for flight controller heartbeat on {cfg.fc_connection} ...")
    if conn.wait_heartbeat(timeout=30) is None:
        raise SystemExit("no heartbeat from the flight controller")
    request_streams(conn)
    sender = GpsInputSender(cfg.fc_connection, cfg.forward_degraded,
                            gps_id=cfg.gps_id, conn=conn)
    print(f"UPIN box running: GPS instance {cfg.gps_id + 1}, "
          f"{'shadow' if cfg.shadow else 'LIVE'}, "
          f"{'GNSS DENIED in software, ' if deny_gnss else ''}"
          f"{'sending' if send else 'NOT sending'}; log {cfg.log_path}")
    with open(cfg.log_path, "a", encoding="utf-8") as log:
        box = Box(cfg, deny_gnss, log)
        last_mode = None
        while True:
            data = rx.read(rx.in_waiting or 1)
            now, unix_s = time.monotonic(), time.time()
            while True:
                msg = conn.recv_match(blocking=False)
                if msg is None:
                    break
                box.on_fc_message(msg, now)
            for out, _ in box.on_receiver_bytes(data, now, unix_s):
                if send:
                    sender.send(out, unix_s)
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
    a = ap.parse_args(argv)
    run(load_config(a.config), deny_gnss=a.deny_gnss, send=not a.no_send)


if __name__ == "__main__":
    main()
