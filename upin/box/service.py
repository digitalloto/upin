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
from collections import deque
import math
import json
import time
import tomllib
from dataclasses import dataclass, fields
from typing import IO, List, Optional, Tuple

from upin.box.fc_reader import (Attitude, Baro, FcGps, FcReader, Flow, Imu, Range,
                                Throttle, request_streams)
from upin.box.gateway import TRUSTED, Gateway, GatewayOutput, GnssEpoch
from upin.box.gnss_parser import MonRf, NavPvt, NavSat, UbxStream, decode_ubx
from upin.box.mavlink_out import GpsInput, GpsInputSender, build
from upin.box.replay import epoch_to_json
from upin.detection.constellation_check import ConstellationFix
from upin.detection.flow_integrity import FlowIntegrityCheck
from upin.detection.reachability import Envelope
from upin.core.wind_learner import FlightSample, WindLearner
from upin.box.camera import open_camera
from upin.layers.inertial.learned_io import LearnedInertialOdometryLayer
from upin.layers.optical.camera_flow import CameraFlowLayer
from upin.layers.optical.fiducial import FiducialTagLayer, TagMap
from upin.layers.satellite.signal_power import SignalPowerCheckLayer
from upin.learned.features import mean_thrust_direction


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
    power_check_action: str = "warn"   # "distrust" once calibrated on this receiver
    airframe_id: str = ""              # must match the AI predictor's model
    learned_io_model: str = ""         # AI motion predictor model file; "" = off
    # downward camera and tag landmarks (layer 149); "" = off
    camera: str = ""                   # "pi", or a folder of .npy frames
    camera_fov_deg: float = 62.0       # ASSUMPTION: Pi camera v2 horizontal FOV; use the real lens's
    camera_size_px: int = 256
    tag_map: str = ""                  # tags.json: surveyed tag positions
    camera_flow: bool = False          # layer 148: UPIN's own flow from the camera frames
    range_sigma_m: float = 0.1         # ASSUMPTION: rangefinder 1-sigma; from its datasheet
    flow_check_action: str = "distrust"
    """Suspect optical flow is not fed to the filter. Distrust is the default
    here, unlike the signal-power check: a false alarm only costs a few
    seconds of flow (coasting instead), while a fooled flow fed to the filter
    poisons the estimate -- in simulation it then made the box distrust good
    GNSS for the rest of the run. "warn" feeds it anyway and only reports."""
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
                               max_degraded_h_acc_m=cfg.max_degraded_h_acc_m,
                               power_check_action=cfg.power_check_action)
        self.power = SignalPowerCheckLayer()
        self.power.initialize()
        # AI motion predictor (layer 147) and the live wind it needs. The
        # predictor only feeds the filter when a model is configured.
        self.learned = LearnedInertialOdometryLayer(airframe_id=cfg.airframe_id)
        self.learned.initialize()
        if cfg.learned_io_model:
            self.learned.load_model(cfg.learned_io_model)
        self.wind = WindLearner()
        self._wind_frozen = False
        self._att_hist: deque = deque()      # last second of attitude, radians
        if cfg.flow_check_action not in ("warn", "distrust"):
            raise ValueError("flow_check_action must be 'warn' or 'distrust'")
        self.flow_check = FlowIntegrityCheck(heading_sigma_deg=cfg.heading_sigma_deg)
        # Tag landmarks (layer 149): a fix only when a tag map is configured.
        self.tags = FiducialTagLayer()
        self.tags.initialize()
        if cfg.tag_map:
            self.tags.set_map(TagMap.load_json(cfg.tag_map))
        self.last_tag: Optional[dict] = None
        self.frames_seen = 0
        # Camera optical flow (layer 148): runs on the same frames when enabled.
        self.camflow = CameraFlowLayer()
        self.camflow.initialize()
        self.last_camflow: Optional[dict] = None
        self._flow_status: Optional[dict] = None
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
            r, p, y = (math.radians(s.roll_deg), math.radians(s.pitch_deg),
                       math.radians(s.heading_deg))
            self.learned.feed_attitude(r, p, y, now)
            self.camflow.feed_attitude(r, p, s.heading_deg, now)
            self.flow_check.feed_attitude(r, p, y, now)
            self._att_hist.append((now, r, p, y))
            while self._att_hist and self._att_hist[0][0] < now - 1.0:
                self._att_hist.popleft()
        elif isinstance(s, Imu):
            self.learned.feed_imu(s.acc_ms2, s.gyro_rads, now)
            self.flow_check.feed_imu(s.acc_ms2, now)
            self.camflow.feed_gyro(*s.gyro_rads, now)
        elif isinstance(s, Range):
            self.camflow.feed_height(s.distance_m, cfg.range_sigma_m, now)
        elif isinstance(s, Throttle):
            self.learned.feed_throttle(s.value, now)
        elif isinstance(s, Flow):
            att = self.fc.state.attitude
            if s.quality >= cfg.min_flow_quality and att and now - att.t < 0.5:
                self.flow_check.feed_flow(s.forward_ms, s.right_ms, now)
                v = dict(self.flow_check.check(now))
                feed = not (v["verdict"] == "SUSPECT" and cfg.flow_check_action == "distrust")
                v["fed"] = feed
                if not feed:
                    p = self.learned.last
                    v["substitute"] = ("AI motion predictor (layer 147)"
                                       if self.learned.model is not None and p
                                       and p.get("status") == "ok"
                                       else "coasting on the filter's prediction")
                self._flow_status = v
                if feed:
                    self.gateway.feed_flow(s.forward_ms, s.right_ms, att.heading_deg,
                                           cfg.flow_sigma_ms, now)
        elif isinstance(s, Baro):
            self.learned.set_temperature(s.temperature_c)
            # Only while GNSS is not trusted, and only as a change since the
            # last trusted fix: pressure altitude drifts with the weather.
            if self._last_mode != TRUSTED and self._baro_offset is not None:
                self.gateway.feed_altitude(s.pressure_alt_m - self._baro_offset,
                                           cfg.baro_sigma_m, now)
        return s

    # -- receiver ------------------------------------------------------------

    def on_frame(self, image, t: float, fov_deg: Optional[float] = None) -> dict:
        """A downward-camera frame. A tag fix goes through the filter's gate
        and re-anchors the reachability guard; the result is recorded either
        way, including why there was no fix."""
        self.frames_seen += 1
        att = self.fc.state.attitude
        if att is not None:
            self.tags.feed_attitude(math.radians(att.roll_deg), math.radians(att.pitch_deg),
                                    att.heading_deg, att.t)
        self.tags.feed_frame(image, t, fov_deg or self.cfg.camera_fov_deg)
        v = dict(self.tags.solve(t))
        if v["status"] == "ok":
            v["fix"] = self.gateway.feed_position(
                v["lat"], v["lon"], v["sigma_m"], t, source="fiducial",
                alt_m=v["alt_m"], sigma_alt_m=v["sigma_alt_m"], anchor=True)
        self.last_tag = v
        if self.cfg.camera_flow:
            self.camflow.feed_frame(image, t, fov_deg or self.cfg.camera_fov_deg)
            cf = dict(self.camflow.solve())
            cf["fed"] = False
            if cf["status"] == "ok" and att is not None and t - att.t < 0.5:
                self.gateway.feed_flow(cf["forward_ms"], cf["right_ms"], att.heading_deg,
                                       cf["sigma_ms"], t, source="camera_flow")
                cf["fed"] = True
            self.last_camflow = cf
        return v

    def on_receiver_bytes(self, data: bytes, now: float,
                          unix_s: float) -> List[Tuple[GatewayOutput, GpsInput]]:
        results = []
        for cls, mid, payload in self.ubx.feed(data):
            msg = decode_ubx(cls, mid, payload)
            if isinstance(msg, MonRf):
                self._jamming = msg.worst_state
                self.power.feed_rf(msg.blocks, now)
            elif isinstance(msg, NavSat):
                self.power.feed_nav_sat(msg.satellites, now)
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
        power = self.power.check(now) if self.power._sats_t is not None else None
        if self.deny_gnss:
            return GnssEpoch(t=now, fix_type=0, jamming_state=self._jamming,
                             power_check=power)
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
            jamming_state=self._jamming, constellation_fixes=fixes,
            power_check=power)

    def process(self, ep: GnssEpoch, unix_s: float,
                pvt: Optional[NavPvt] = None) -> Tuple[GatewayOutput, GpsInput]:
        started = time.perf_counter()
        if self.learned.model is not None:
            p = self.learned.predict(ep.t)
            if p["status"] == "ok":
                self.gateway.feed_velocity(p["vn"], p["ve"], p["sigma_ms"], ep.t,
                                           source="learned_io")
                self.flow_check.feed_predictor(p["vn"], p["ve"], p["sigma_ms"], ep.t)
        if self._flow_status is not None and ep.t - self._flow_status_time() <= 2.0:
            ep.flow_check = self._flow_status
        out = self.gateway.process(ep)
        self.last_processing_ms = (time.perf_counter() - started) * 1000.0
        baro = self.fc.state.baro
        if (out.mode == TRUSTED and ep.alt_m is not None and baro
                and ep.t - baro.t < 1.0):
            self._baro_offset = baro.pressure_alt_m - ep.alt_m
        self._last_mode = out.mode
        self._update_wind(ep, out)
        if ep.power_check is not None:
            self.power.learn(out.mode == TRUSTED and not self.deny_gnss)
        sent = build(out, unix_s, self.cfg.forward_degraded, gps_id=self.cfg.gps_id)
        self.last_epoch = ep
        self.last_record = self._record(ep, out, sent, unix_s, pvt)
        if self.log is not None:
            self.log.write(json.dumps(self.last_record) + "\n")
            self.log.flush()
        return out, sent

    def _flow_status_time(self) -> float:
        f = self.fc.state.flow
        return f.t if f is not None else float("-inf")

    def _update_wind(self, ep: GnssEpoch, out: GatewayOutput) -> None:
        """Learn the wind while GNSS is trusted; freeze it when GNSS goes."""
        hist = self._att_hist
        if out.mode == TRUSTED and ep.vel_ned_ms is not None and len(hist) >= 5 \
                and ep.t - hist[-1][0] < 0.5:
            if self._wind_frozen:
                self.wind.gnss_restored()
                self._wind_frozen = False
            tilt, direction = mean_thrust_direction([h[1] for h in hist],
                                                    [h[2] for h in hist],
                                                    [h[3] for h in hist])
            self.wind.add_sample(FlightSample(ep.t, direction, tilt, ep.vel_ned_ms[0],
                                              ep.vel_ned_ms[1], ep.s_acc_ms or 0.1))
        if out.mode == TRUSTED and ep.vel_ned_ms is not None:
            self.flow_check.feed_gnss_velocity(ep.vel_ned_ms[0], ep.vel_ned_ms[1],
                                               ep.s_acc_ms or 0.3, ep.t)
        elif out.mode != TRUSTED and not self._wind_frozen and self.wind.samples:
            self.wind.gnss_lost(ep.t)
            self._wind_frozen = True
        est = self.wind.estimate(ep.t)
        if est is not None and math.isfinite(est.sigma_ms):
            self.learned.set_wind(est.north_ms, est.east_ms, est.sigma_ms,
                                  est.gust_sigma_ms)
        else:
            self.learned.clear_wind()

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
            "fixes": {k: dict(v) for k, v in self.gateway.last_fixes.items()},
            "camera_flow": None if self.last_camflow is None else {
                k: self.last_camflow.get(k) for k in
                ("status", "reason", "forward_ms", "right_ms", "sigma_ms", "agreeing_trust",
                 "n_inliers", "n_valid", "fed")},
            "tag": None if self.last_tag is None else {
                k: self.last_tag.get(k) for k in
                ("status", "reason", "tag_id", "range_m", "sigma_m", "lat", "lon", "t")},
            "learned_io": self.learned.last if self.learned.model is not None else None,
            # the signal-power verdict, per-satellite C/N0 and elevation
            # travel inside "epoch" (power_check), for calibration later
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
    cam = (open_camera(cfg.camera, cfg.camera_size_px, cfg.camera_fov_deg)
           if cfg.camera else None)
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
            if cam is not None:
                frame = cam.read()
                if frame is not None:
                    box.on_frame(frame[0], now, cam.fov_deg)
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
