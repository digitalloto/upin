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
import os
import platform
import shutil
import signal
import threading
from collections import deque
import math
import json
import time
import tomllib
from dataclasses import dataclass, fields
from typing import IO, List, Optional, Tuple

from upin.box.fc_reader import (Airspeed, Attitude, Baro, FcGps, FcReader, Flow, Imu, Range,
                                Throttle, request_streams)
from upin.box.wind_dr import WindDeadReckoning, body_accel_ne
from upin.core.speed_learner import SpeedLearner
from upin.box.gateway import TRUSTED, Gateway, GatewayOutput, GnssEpoch
from upin.box.gnss_parser import MonHw, MonRf, NavPvt, NavSat, UbxStream, decode_ubx
from upin.box.mavlink_out import GpsInput, GpsInputSender, build
from upin.box.replay import epoch_to_json
from upin.detection.constellation_check import ConstellationFix
from upin.detection.flow_integrity import FlowIntegrityCheck
from upin.detection.reachability import Envelope
from upin.core.wind_learner import FlightSample, WindLearner
from upin.box.beacon_radio import BeaconRadio
from upin.box.recorder import FlightRecorder
from upin.box.camera import open_camera
from upin.box.leo_pass import LeoPassRunner
from upin.layers.inertial.learned_io import LearnedInertialOdometryLayer
from upin.layers.optical.camera_flow import CameraFlowLayer
from upin.layers.optical.fiducial import FiducialTagLayer, TagMap
from upin.layers.optical.patch_map import PatchMapLayer
from upin.vision.patch_map import DEG_M as _DEG_M, PatchMap
from upin.layers.rf.beacon_ranging import BeaconRangingLayer
from upin.layers.rf.breadcrumbs import (CRUMB_PREFIX, THREAT_CLEAR, THREAT_JAMMED, THREAT_RISING,
                                        BreadcrumbLayer, DropPolicy)
from upin.layers.rf.formation import PEER_PREFIX, SOURCE_GNSS, SOURCE_UPIN, FormationLayer
from upin.layers.satellite.leo_doppler import LeoDopplerLayer
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
    # wind-and-tilt dead reckoning (upin/box/wind_dr.py): the last velocity
    # rung before coasting, from attitude, the frozen wind and a tilt-to-
    # airspeed curve learned on the trusted leg (needs airframe_id)
    wind_dr: bool = False
    speed_model: str = ""              # curve file for this airframe and payload; "" = in-flight only
    payload_kg: float = 0.0            # the payload the curve belongs to; another is refused
    airspeed_sensor: bool = False      # a REAL airspeed sensor is fitted: VFR_HUD.airspeed is used
    airspeed_sigma_ms: float = 1.0     # ASSUMPTION: pitot 1-sigma; from its datasheet
    # downward camera and tag landmarks (layer 149); "" = off
    camera: str = ""                   # "pi", or a folder of .npy frames
    camera_fov_deg: float = 62.0       # ASSUMPTION: Pi camera v2 horizontal FOV; use the real lens's
    camera_size_px: int = 256
    tag_map: str = ""                  # tags.json: surveyed tag positions
    camera_flow: bool = False          # layer 148: UPIN's own flow from the camera frames
    # self-surveyed patch map (layer 154): "" = off; a file to load, saved there when built
    patch_map: str = ""
    patch_map_build: bool = False      # store patches while the fix is TRUSTED; saved at exit
    patch_spacing_m: float = 15.0      # ASSUMPTION: patches 24 m wide every 15 m overlap along track
    # known-position beacons (layer 151); "" = off
    beacon_radio: str = ""             # serial port of the ranging radio (JSON lines)
    beacon_radio_baud: int = 115200
    beacon_secret_file: str = ""       # file holding the shared secret (bytes)
    breadcrumbs: bool = False          # layer 152: drop crumbs as jamming rises
    breadcrumb_spacing_m: float = 300.0
    breadcrumb_max: int = 6
    breadcrumb_drop_agl_m: float = 50.0  # ASSUMPTION used only when no rangefinder reports height
    # formation cross-check and cooperative fix (layer 153); off by default
    formation: bool = False            # peers on the beacon radio confirm each other's fixes
    drone_id: str = ""                 # this drone's name in the formation ("lead", "w1", ...)
    formation_check_action: str = "warn"   # "distrust" once the radio's ranging sigma is measured
    # LEO Doppler anchor (layer 150); "" = off
    sdr: str = ""                      # "rtl" for an RTL-SDR dongle
    leo_satellites: str = ""           # satellites.json: name, TLE lines, carrier_hz
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
    # flight recording for the offline replay (docs/RECORDING.md); "" = off
    input_log_path: str = ""           # every input the box received, in order (JSON lines)
    frames_dir: str = ""               # camera frames as <t>.npy
    frame_record_hz: float = 2.0       # ASSUMPTION: enough for the camera layers; raise for exact replay


def expand_path(path: str) -> str:
    """Log and recording paths may carry strftime codes, so every run gets
    its own file: /var/log/upin/box-%Y%m%d-%H%M%S.jsonl."""
    return time.strftime(path) if path and "%" in path else path


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
    if cfg.formation and not cfg.drone_id:
        raise ValueError("formation = true needs drone_id: the name this drone broadcasts under")
    if cfg.formation and not cfg.beacon_secret_file:
        raise ValueError("formation = true needs beacon_secret_file: peers sign with it")
    if cfg.speed_model and not cfg.airframe_id:
        raise ValueError("speed_model needs airframe_id: the tilt-to-airspeed curve is per airframe")
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
                               power_check_action=cfg.power_check_action,
                               formation_check_action=cfg.formation_check_action)
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
        self._acc_hist: deque = deque()      # last second of horizontal acceleration, NED
        # Wind-and-tilt dead reckoning: the curve is per airframe and payload.
        self.speed: Optional[SpeedLearner] = None
        if cfg.airframe_id:
            if cfg.speed_model and os.path.exists(cfg.speed_model):
                self.speed = SpeedLearner.load(cfg.speed_model, cfg.airframe_id, cfg.payload_kg)
            else:
                self.speed = SpeedLearner(cfg.airframe_id, cfg.payload_kg)
        self.wind_dr = WindDeadReckoning(self.wind, self.speed)
        self.last_wind_dr: Optional[dict] = None
        self._pending_speed: List[FlightSample] = []
        self.speed_samples_learned = 0
        self._velocity_fed: Tuple[float, str] = (float("-inf"), "")
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
        # Patch map (layer 154): matches when a map exists; builds while trusted if asked.
        self.patchmap = PatchMapLayer(cfg.patch_spacing_m)
        self.patchmap.initialize()
        if cfg.patch_map and os.path.exists(cfg.patch_map):
            self.patchmap.set_map(PatchMap.load(cfg.patch_map))
        self.last_patch: Optional[dict] = None
        # Known-position beacons (layer 151): fixes only with a secret and radio.
        self.beacons = BeaconRangingLayer()
        self.beacons.initialize()
        if cfg.beacon_secret_file:
            with open(cfg.beacon_secret_file, "rb") as f:
                self.beacons.set_secret(f.read().strip())
        self.last_beacons: Optional[dict] = None
        # Breadcrumbs (layer 152): same secret and radio as the beacons.
        self.crumbs = BreadcrumbLayer(DropPolicy(cfg.breadcrumb_spacing_m, cfg.breadcrumb_max))
        self.crumbs.initialize()
        if cfg.beacon_secret_file:
            self.crumbs.set_secret(self.beacons._secret)
        self.drops: List[dict] = []
        self.last_crumbs: Optional[dict] = None
        self._radio_out = None            # callable(line) to the beacon radio
        # Formation (layer 153): peers on the same radio and secret.
        self.formation = FormationLayer(cfg.drone_id)
        self.formation.initialize()
        if cfg.beacon_secret_file:
            self.formation.set_secret(self.beacons._secret)
        self.last_formation: Optional[dict] = None
        self.last_own_message: Optional[dict] = None
        # LEO Doppler anchor (layer 150): runs only with an SDR and satellites.
        self.leo = LeoDopplerLayer()
        self.leo.initialize()
        self.leo_runner: Optional[LeoPassRunner] = None
        self.last_leo: Optional[dict] = None
        self._flow_status: Optional[dict] = None
        self.fc = FcReader()
        self.ubx = UbxStream()
        self._jamming = "unknown"
        self._baro_offset: Optional[float] = None
        self._last_mode: Optional[str] = None
        self.last_epoch: Optional[GnssEpoch] = None
        self.last_record: Optional[dict] = None
        self.last_processing_ms: Optional[float] = None
        self.epochs = 0
        # Flight recorder: what the box received, for the offline replay.
        self.recorder: Optional[FlightRecorder] = None
        self.recorder_paths = (expand_path(cfg.input_log_path), expand_path(cfg.frames_dir))
        if cfg.input_log_path or cfg.frames_dir:
            header = {k: v for k, v in cfg.__dict__.items()
                      if k not in ("input_log_path", "frames_dir", "log_path", "beacon_secret_file")}
            self.recorder = FlightRecorder(self.recorder_paths[0], self.recorder_paths[1],
                                           cfg.frame_record_hz, header=header)
        self.sending: Optional[bool] = None       # set by the live loop; None in tests and the console
        self.last_receiver_bytes_t: Optional[float] = None
        self._fc_counts_prev: dict = {}

    # -- flight controller ---------------------------------------------------

    def on_fc_message(self, msg, now: float):
        if self.recorder is not None:
            self.recorder.fc_message(msg, now)
        s = self.fc.handle(msg, now)
        cfg = self.cfg
        if isinstance(s, Attitude):
            self.gateway.feed_heading(s.heading_deg, cfg.heading_sigma_deg, now,
                                      source="fc_attitude")
            r, p, y = (math.radians(s.roll_deg), math.radians(s.pitch_deg),
                       math.radians(s.heading_deg))
            self.learned.feed_attitude(r, p, y, now)
            self.camflow.feed_attitude(r, p, s.heading_deg, now)
            self.patchmap.feed_attitude(r, p, s.heading_deg, now)
            self.flow_check.feed_attitude(r, p, y, now)
            self._att_hist.append((now, r, p, y))
            while self._att_hist and self._att_hist[0][0] < now - 1.0:
                self._att_hist.popleft()
        elif isinstance(s, Imu):
            self.learned.feed_imu(s.acc_ms2, s.gyro_rads, now)
            self.flow_check.feed_imu(s.acc_ms2, now)
            self.camflow.feed_gyro(*s.gyro_rads, now)
            att = self.fc.state.attitude
            if att is not None and now - att.t < 0.5:
                self._acc_hist.append((now, *body_accel_ne(
                    s.acc_ms2, math.radians(att.roll_deg), math.radians(att.pitch_deg),
                    math.radians(att.heading_deg))))
                while self._acc_hist and self._acc_hist[0][0] < now - 1.0:
                    self._acc_hist.popleft()
        elif isinstance(s, Range):
            self.camflow.feed_height(s.distance_m, cfg.range_sigma_m, now)
            self.patchmap.feed_height(s.distance_m, cfg.range_sigma_m, now)
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
                    self._velocity_fed = (now, "flow chip")
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
        if self.recorder is not None:
            self.recorder.frame(image, t, fov_deg or self.cfg.camera_fov_deg)
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
                self._velocity_fed = (t, "camera flow")
            self.last_camflow = cf
        if self.cfg.patch_map or self.cfg.patch_map_build:
            self.patchmap.feed_frame(image, t, fov_deg or self.cfg.camera_fov_deg)
            self.step_patch_map(t)
        return v

    def step_patch_map(self, t: float) -> None:
        """Build: store this frame at the trusted receiver fix, moved to the
        frame time with the fix's velocity. Match: when the fix is not
        trusted and a map exists, an accepted match re-anchors the filter."""
        pm = self.patchmap
        ep = self.last_epoch
        v: dict = {"status": "idle", "map_patches": len(pm.map) if pm.map is not None else 0}
        trusted = self._last_mode == TRUSTED and ep is not None and ep.fix_type >= 3
        if self.cfg.patch_map_build:
            if trusted and t - ep.t <= 1.5:
                vn, ve = (ep.vel_ned_ms[0], ep.vel_ned_ms[1]) if ep.vel_ned_ms else (0.0, 0.0)
                dt = t - ep.t
                lat = ep.lat + vn * dt / _DEG_M
                lon = ep.lon + ve * dt / (_DEG_M * math.cos(math.radians(ep.lat)))
                sigma = math.hypot(ep.h_acc_m, (ep.s_acc_ms or 0.5) * dt)
                r = pm.learn(lat, lon, ep.alt_m if ep.alt_m is not None else 0.0, sigma, True, t)
            else:
                r = pm.learn(0.0, 0.0, 0.0, float("inf"), False, t)
            v = {"status": "building", "stored": r["stored"], "reason": r.get("reason"),
                 "map_patches": len(pm.map) if pm.map is not None else 0, "learned": pm.learned}
        if not trusted and pm.map is not None and len(pm.map):
            est = self.gateway.kf.estimate()
            if est is not None:
                pm.set_prior(est.lat, est.lon, max(est.drms_m, 1.0))
            m = dict(pm.solve(t))
            if m["status"] == "ok":
                m["fix"] = self.gateway.feed_position(m["lat"], m["lon"], m["sigma_m"], t,
                                                      source="patch_map", anchor=True)
            m["building"] = v if v["status"] == "building" else None
            m["map_patches"] = len(pm.map)
            v = m
        self.last_patch = v

    def on_beacon_line(self, line: str, t: float) -> Optional[str]:
        """One JSON line from the beacon radio: a beacon's signed message or a
        range. Returns what the layer did with it."""
        if self.recorder is not None:
            self.recorder.radio_line(line, t)
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return "unreadable line"
        bid = str(d.get("id", ""))
        target = (self.crumbs if bid.startswith(CRUMB_PREFIX)
                  else self.formation if bid.startswith(PEER_PREFIX) else self.beacons)
        if d.get("type") == "msg":
            return target.feed_message(d, t)
        if d.get("type") == "range":
            return target.feed_range(bid, float(d.get("range_m", 0)), float(d.get("sigma_m", 0)), t)
        return "unknown line type"

    def threat_level(self, ep: GnssEpoch, out: GatewayOutput) -> int:
        """0 clear, 1 rising, 2 jammed -- from what the box already knows."""
        if ep.fix_type < 3 or ep.jamming_state == "critical":
            return THREAT_JAMMED
        pc = ep.power_check or {}
        if (pc.get("verdict") == "JAMMING" or ep.jamming_state == "warning"
                or out.mode != TRUSTED):
            return THREAT_RISING
        return THREAT_CLEAR

    def step_breadcrumbs(self, ep: GnssEpoch, out: GatewayOutput) -> None:
        """Feed the crumb layer, drop when the policy says, solve a fix."""
        c = self.crumbs
        if out.lat is not None:
            c.feed_fix(out.lat, out.lon, out.alt_m, out.h_acc_m, ep.t, out.mode == TRUSTED)
        est = self.wind.estimate(ep.t)
        if est is not None and math.isfinite(est.sigma_ms):
            c.feed_wind(est.north_ms, est.east_ms, math.hypot(est.sigma_ms, est.gust_sigma_ms))
        r = self.fc.state.range
        if r is not None and ep.t - r.t < 2.0:
            c.feed_agl(r.distance_m, ep.t)
        elif self.cfg.breadcrumb_drop_agl_m > 0:
            c.feed_agl(self.cfg.breadcrumb_drop_agl_m, ep.t)
        c.feed_threat(self.threat_level(ep, out))
        if self.cfg.breadcrumbs:
            rec = c.drop(ep.t)
            if rec is not None:
                self.drops.append(rec)
                if self._radio_out is not None:
                    self._radio_out(json.dumps(rec))
        baro = self.fc.state.baro
        if baro is not None and self._baro_offset is not None and ep.t - baro.t < 2.0:
            c.set_altitude(baro.pressure_alt_m - self._baro_offset, self.cfg.baro_sigma_m, ep.t)
        est = self.gateway.kf.estimate()
        if est is not None:
            c.set_prior(est.lat, est.lon)
        v = c.solve(ep.t)
        if v["status"] == "ok":
            v["fix"] = self.gateway.feed_position(v["lat"], v["lon"], v["sigma_m"], ep.t,
                                                  source="breadcrumbs", alt_m=v["alt_m"],
                                                  sigma_alt_m=v["sigma_alt_m"], anchor=True)
        self.last_crumbs = v

    def formation_check(self, ep: GnssEpoch) -> dict:
        """Layer 153's verdict on this epoch's own fix, before the gateway
        decides; NOT_RUN with the reason when there is no fix to check."""
        if ep.fix_type < 3 or not (math.isfinite(ep.h_acc_m) and ep.h_acc_m > 0):
            return {"verdict": "NOT_RUN", "reason": "no own GNSS fix to check against the formation"}
        return self.formation.check(ep.lat, ep.lon, ep.alt_m, ep.h_acc_m, ep.t)

    def step_formation(self, ep: GnssEpoch, out: GatewayOutput) -> None:
        """Broadcast my own checked fix to the peers; when my fix is not
        trusted, take a fix from two or more peers that still trust theirs."""
        f = self.formation
        baro = self.fc.state.baro
        alt = None
        if baro is not None and self._baro_offset is not None and ep.t - baro.t < 2.0:
            alt = baro.pressure_alt_m - self._baro_offset
            f.set_altitude(alt, self.cfg.baro_sigma_m, ep.t)
        est = self.gateway.kf.estimate()
        if out.lat is not None and out.h_acc_m:
            f.set_prior(out.lat, out.lon, out.h_acc_m)
        elif est is not None:
            f.set_prior(est.lat, est.lon, est.drms_m)
        trusted = out.mode == TRUSTED
        msg_alt = out.alt_m if out.alt_m is not None else alt
        if out.lat is not None and out.h_acc_m and msg_alt is not None:
            vel = out.vel_ned_ms if out.vel_ned_ms is not None else (
                (est.velocity_ne[0], est.velocity_ne[1]) if est is not None else (0.0, 0.0))
            m = f.own_message(out.lat, out.lon, msg_alt, out.h_acc_m, vel[0], vel[1], trusted,
                              SOURCE_GNSS if trusted else SOURCE_UPIN, ep.t)
            self.last_own_message = m
            if self._radio_out is not None:
                self._radio_out(json.dumps({"type": "msg", **m}))
        if trusted:
            v = {"status": "standby", "reason": "own GNSS trusted: no peer fix needed",
                 "n_anchors": len(f.anchors(ep.t))}
        else:
            v = dict(f.solve(ep.t))
            if v["status"] == "ok":
                v["fix"] = self.gateway.feed_position(v["lat"], v["lon"], v["sigma_m"], ep.t,
                                                      source="formation", alt_m=v["alt_m"],
                                                      sigma_alt_m=v["sigma_alt_m"], anchor=True)
        v["check"] = ep.formation_check
        v["peers"] = f.peers_snapshot(ep.t)
        self.last_formation = v

    def step_leo(self, now_unix: float, t: float) -> None:
        """Advance the LEO pass runner; an accepted fix enters the filter
        without re-anchoring the reachable region (too coarse for that)."""
        if self.leo_runner is None:
            return
        est = self.gateway.kf.estimate()
        baro = self.fc.state.baro
        if est is None or baro is None or self._baro_offset is None:
            self.last_leo = {"status": "waiting", "reason": "needs a prior position and a "
                             "GNSS-calibrated barometric altitude"}
            return
        v = self.leo_runner.step(est.lat, est.lon, max(est.drms_m, 100.0),
                                 baro.pressure_alt_m - self._baro_offset,
                                 self.cfg.baro_sigma_m, now_unix)
        if v is not None and v["status"] == "ok":
            v["fix"] = self.gateway.feed_position(v["lat"], v["lon"], v["sigma_m"], t,
                                                  source="leo_doppler", anchor=False)
        self.last_leo = v if v is not None else {"status": "running", "reason": self.leo_runner.status}

    def solve_beacons(self, t: float) -> dict:
        """Solve the beacon fix for this moment; an accepted fix re-anchors
        the reachable region like a tag fix."""
        baro = self.fc.state.baro
        if baro is not None and self._baro_offset is not None and t - baro.t < 2.0:
            self.beacons.set_altitude(baro.pressure_alt_m - self._baro_offset,
                                      self.cfg.baro_sigma_m, t)
        est = self.gateway.kf.estimate()
        if est is not None:
            self.beacons.set_prior(est.lat, est.lon)
        v = dict(self.beacons.solve(t))
        if v["status"] == "ok":
            v["fix"] = self.gateway.feed_position(v["lat"], v["lon"], v["sigma_m"], t,
                                                  source="beacons", alt_m=v["alt_m"],
                                                  sigma_alt_m=v["sigma_alt_m"], anchor=True)
        self.last_beacons = v
        return v

    def on_receiver_bytes(self, data: bytes, now: float,
                          unix_s: float) -> List[Tuple[GatewayOutput, GpsInput]]:
        results = []
        if data:
            self.last_receiver_bytes_t = now
        for cls, mid, payload in self.ubx.feed(data):
            msg = decode_ubx(cls, mid, payload)
            if isinstance(msg, MonHw):             # the M8 generation's form of MON-RF
                msg = msg.as_mon_rf()
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
                self._velocity_fed = (ep.t, "AI predictor")
                self.flow_check.feed_predictor(p["vn"], p["ve"], p["sigma_ms"], ep.t)
        if self._flow_status is not None and ep.t - self._flow_status_time() <= 2.0:
            ep.flow_check = self._flow_status
        if self.cfg.formation:
            ep.formation_check = self.formation_check(ep)
        out = self.gateway.process(ep)
        self.last_processing_ms = (time.perf_counter() - started) * 1000.0
        baro = self.fc.state.baro
        if (out.mode == TRUSTED and ep.alt_m is not None and baro
                and ep.t - baro.t < 1.0):
            self._baro_offset = baro.pressure_alt_m - ep.alt_m
        self._last_mode = out.mode
        self._update_wind(ep, out)
        if self.cfg.wind_dr:
            self.step_wind_dr(ep, out)
        if self.beacons._secret is not None:
            self.solve_beacons(ep.t)
        if self.crumbs.inner._secret is not None:
            self.step_breadcrumbs(ep, out)
        if self.cfg.formation and self.formation._secret is not None:
            self.step_formation(ep, out)
        if ep.power_check is not None:
            self.power.learn(out.mode == TRUSTED and not self.deny_gnss)
        sent = build(out, unix_s, self.cfg.forward_degraded, gps_id=self.cfg.gps_id)
        self.epochs += 1
        self.last_epoch = ep
        self.last_record = self._record(ep, out, sent, unix_s, pvt)
        if self.log is not None:
            self.log.write(json.dumps(self.last_record) + "\n")
            self.log.flush()
        if self.recorder is not None:
            self.recorder.epoch(epoch_to_json(ep), ep.t, unix_s)
        return out, sent

    SPEED_BATCH = 10
    """Steady samples learned into the tilt curve at a time, so each batch's
    correlation (gusts) is measured rather than counted as independent."""

    def _learn_speed(self, t: float) -> None:
        """Feed the steady samples the Wind Learner kept into the tilt curve,
        once the wind they need is known."""
        if self.speed is None or len(self._pending_speed) < self.SPEED_BATCH:
            return
        est = self.wind.estimate(t)
        if est is None or est.frozen:
            return
        self.speed_samples_learned += self.speed.learn_from_samples(self._pending_speed, est)
        self._pending_speed.clear()

    def step_wind_dr(self, ep: GnssEpoch, out: GatewayOutput) -> None:
        """The last velocity rung before coasting: the lean (or the pitot)
        plus the frozen wind, fed only when nothing better has."""
        cfg = self.cfg
        att = self.fc.state.attitude
        hist = [h for h in self._att_hist if h[0] >= ep.t - 1.0]
        tilt = direction = turn_rate = None
        if att is not None and ep.t - att.t <= 1.0 and len(hist) >= 3:
            tilt, direction = mean_thrust_direction([h[1] for h in hist], [h[2] for h in hist],
                                                    [h[3] for h in hist])
            dyaw = (hist[-1][3] - hist[0][3] + math.pi) % (2 * math.pi) - math.pi
            span = hist[-1][0] - hist[0][0]
            turn_rate = math.degrees(dyaw / span) if span > 0.2 else None
        acc = [a for a in self._acc_hist if a[0] >= ep.t - 1.0]
        accel_ne = ((sum(a[1] for a in acc) / len(acc), sum(a[2] for a in acc) / len(acc))
                    if len(acc) >= 5 else None)
        airspeed = None
        a = self.fc.state.airspeed
        if cfg.airspeed_sensor and a is not None and ep.t - a.t <= 1.0:
            airspeed = (a.ms, cfg.airspeed_sigma_ms)
        v = dict(self.wind_dr.estimate(ep.t, tilt, direction, accel_ne, turn_rate, airspeed,
                                       None if att is None else att.heading_deg))
        v["fed"] = False
        if v["status"] == "ok":
            fed_t, fed_src = self._velocity_fed
            if out.mode == TRUSTED:
                v["why_not_fed"] = "own GNSS trusted"
            elif ep.t - fed_t <= 1.0:
                v["why_not_fed"] = f"{fed_src} fed the filter {ep.t - fed_t:.1f} s ago"
            else:
                self.gateway.feed_velocity(v["vn"], v["ve"], v["sigma_ms"], ep.t, source="wind_dr")
                v["fed"] = True
        v["curve_samples"] = self.speed_samples_learned
        self.last_wind_dr = v

    def status_line(self, now: float, interval_s: float, last_heartbeat_t: Optional[float] = None,
                    log_dir: str = ".") -> str:
        """One line for the terminal every few seconds: is everything alive?"""
        ep = self.last_epoch
        if ep is None:
            rx = "no epoch yet"
        elif ep.fix_type >= 3:
            rx = f"fix 3D sats {ep.num_sv} hAcc {ep.h_acc_m:.1f} m"
        else:
            rx = f"fix type {ep.fix_type}"
        st = self.ubx.stats
        counts = self.fc.counts
        delta = {k: counts[k] - self._fc_counts_prev.get(k, 0) for k in counts}
        self._fc_counts_prev = dict(counts)
        short = {"ATTITUDE": "att", "RAW_IMU": "imu", "SCALED_PRESSURE": "baro", "GPS_RAW_INT": "fcgps",
                 "DISTANCE_SENSOR": "range", "OPTICAL_FLOW": "flow", "SERVO_OUTPUT_RAW": "servo",
                 "VFR_HUD": "hud"}
        fc = " ".join(f"{short.get(k, k.lower()[:5])}:{v / max(interval_s, 1e-6):.0f}Hz"
                      for k, v in sorted(delta.items()) if v) or "nothing"
        parts = [f"epochs {self.epochs}", rx, f"ubx {st.frames} frames/{st.bad_checksum} bad",
                 f"mode {self._last_mode or '-'}", f"fc {fc}"]
        if self.recorder is not None:
            r = self.recorder.status()
            parts.append(f"rec {r['megabytes']:.0f} MB" + (" STOPPED" if r["stopped"] else ""))
        try:
            parts.append(f"free {shutil.disk_usage(log_dir).free / 1e6:.0f} MB")
        except OSError:
            pass
        warn = []
        if self.last_receiver_bytes_t is None and self.epochs == 0:
            warn.append("RECEIVER: nothing received yet")
        elif self.last_receiver_bytes_t is not None and now - self.last_receiver_bytes_t > 5.0:
            warn.append(f"RECEIVER SILENT {now - self.last_receiver_bytes_t:.0f} s")
        if last_heartbeat_t is not None and now - last_heartbeat_t > 5.0:
            warn.append(f"NO HEARTBEAT {now - last_heartbeat_t:.0f} s")
        line = time.strftime("%H:%M:%S") + " | " + " | ".join(parts)
        return line + (" | " + "; ".join(warn) if warn else "")

    def close(self) -> dict:
        """End of flight: save what was learned, close the recorder."""
        saved = self.save_models()
        status = None
        if self.recorder is not None:
            self.recorder._write({"kind": "note", "t": -1.0,
                                  "text": f"frames seen live: {self.frames_seen}"})
            status = self.recorder.status()
            status["frames_seen_live"] = self.frames_seen
            self.recorder.close()
        return {"saved": saved, "recorder": status}

    def save_models(self) -> List[str]:
        """Persist what this flight learned: the tilt-to-airspeed curve, if a
        file is configured and the flight added to it."""
        saved = []
        if self.speed is not None and self.cfg.speed_model and self.speed_samples_learned > 0:
            self.speed.save(self.cfg.speed_model)
            saved.append(self.cfg.speed_model)
        pm = self.patchmap
        if self.cfg.patch_map_build and self.cfg.patch_map and pm.map is not None and pm.learned > 0:
            pm.map.save(self.cfg.patch_map)
            saved.append(self.cfg.patch_map)
        return saved

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
            sample = FlightSample(ep.t, direction, tilt, ep.vel_ned_ms[0],
                                  ep.vel_ned_ms[1], ep.s_acc_ms or 0.1)
            if self.wind.add_sample(sample):
                self._pending_speed.append(sample)
            self._learn_speed(ep.t)
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
            "sending": self.sending,
            "receiver": None if pvt is None else {
                "fix_type": pvt.fix_type, "lat": pvt.lat, "lon": pvt.lon,
                "alt_m": pvt.height_msl_m, "h_acc_m": pvt.h_acc_m,
                "num_sv": pvt.num_sv, "jamming": self._jamming,
                "itow_ms": pvt.itow_ms,
                "utc": (f"{pvt.year:04d}-{pvt.month:02d}-{pvt.day:02d} {pvt.hour:02d}:{pvt.minute:02d}:"
                        f"{pvt.second:02d}") if pvt.year else None},
            "fc_gps": None if g is None else {
                "fix_type": g.fix_type, "lat": g.lat, "lon": g.lon, "alt_m": g.alt_m,
                "h_acc_m": g.h_acc_m, "satellites": g.satellites, "age_s": ep.t - g.t},
            "checks": list(self.gateway.last_checks),
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
            "wind_dr": None if self.last_wind_dr is None else {
                k: self.last_wind_dr.get(k) for k in
                ("status", "reason", "vn", "ve", "sigma_ms", "airspeed_ms", "air_source", "fed",
                 "why_not_fed", "effective_tilt_deg", "imu_corrected", "wind", "curve_samples")},
            "fixes": {k: dict(v) for k, v in self.gateway.last_fixes.items()},
            "leo_doppler": None if self.last_leo is None else {
                k: self.last_leo.get(k) for k in
                ("status", "reason", "satellite", "sigma_m", "lat", "lon", "max_elevation_deg")},
            "breadcrumbs": None if self.last_crumbs is None else {
                k: self.last_crumbs.get(k) for k in
                ("status", "reason", "crumbs_dropped", "crumbs_in_range", "sigma_m", "lat", "lon",
                 "last_drop_reason")},
            "drops": [{"id": d["id"], "lat": d["lat"], "lon": d["lon"], "sigma_m": d["sigma_m"],
                       "t": d["t"]} for d in self.drops],
            "beacons": None if self.last_beacons is None else {
                k: self.last_beacons.get(k) for k in
                ("status", "reason", "n_beacons", "sigma_m", "hdop", "lat", "lon", "rejected")},
            "formation": None if self.last_formation is None else {
                **{k: self.last_formation.get(k) for k in
                   ("status", "reason", "n_anchors", "anchors", "sigma_m", "hdop", "lat", "lon",
                    "mirror_distance_m", "rejected")},
                "check": None if not self.last_formation.get("check") else {
                    k: self.last_formation["check"].get(k) for k in
                    ("verdict", "reason", "pattern", "suspect", "max_z", "n_pairs")},
                "peers": self.last_formation.get("peers")},
            "camera_flow": None if self.last_camflow is None else {
                k: self.last_camflow.get(k) for k in
                ("status", "reason", "forward_ms", "right_ms", "sigma_ms", "agreeing_trust",
                 "n_inliers", "n_valid", "fed")},
            "patch_map": None if self.last_patch is None else {
                k: self.last_patch.get(k) for k in
                ("status", "reason", "lat", "lon", "sigma_m", "peak", "second", "candidates",
                 "map_patches", "stored", "learned", "offset_from_prior_m")},
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
    radio = BeaconRadio(cfg.beacon_radio, cfg.beacon_radio_baud) if cfg.beacon_radio else None
    if radio is not None and cfg.breadcrumbs and not cfg.beacon_secret_file:
        raise SystemExit("breadcrumbs need beacon_secret_file: the crumbs sign with it")
    if cfg.formation and radio is None:
        raise SystemExit("formation needs beacon_radio: the peers talk and range over it")
    if cfg.sdr and cfg.leo_satellites:
        from upin.box.sdr import RtlSdrSource
        if cfg.sdr != "rtl":
            raise SystemExit("sdr must be 'rtl' (RTL-SDR dongle) or empty")
    log_path = expand_path(cfg.log_path)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    print(f"UPIN box running: GNSS from {gnss_source}, GPS instance "
          f"{cfg.gps_id + 1}, {'shadow' if cfg.shadow else 'LIVE'}, "
          f"{'GNSS DENIED in software, ' if deny_gnss else ''}"
          f"{'sending' if send else 'NOT sending'}; log {log_path}")
    if threading.current_thread() is threading.main_thread():
        def _term(signum, frame):              # systemctl stop: a clean close, like Ctrl-C
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, _term)
    with open(log_path, "a", encoding="utf-8") as log:
        from upin import __version__
        log.write(json.dumps({
            "run_start": time.time(), "log_path": log_path,
            "config": {k: v for k, v in cfg.__dict__.items() if k != "beacon_secret_file"},
            "flags": {"send": send, "deny_gnss": deny_gnss, "gnss_source": gnss_source,
                      "deny_after": None if schedule is None else schedule.after_s,
                      "deny_for": None if schedule is None else schedule.for_s},
            "upin_version": __version__, "python": platform.python_version(),
            "host": platform.node()}) + "\n")
        log.flush()
        box = Box(cfg, deny_gnss, log)
        box.sending = send
        if box.recorder is not None:
            print(f"recording inputs to {box.recorder_paths[0] or '(off)'}, frames to "
                  f"{box.recorder_paths[1] or '(off)'}")
        if radio is not None:
            box._radio_out = radio.write_line
        if cfg.sdr and cfg.leo_satellites:
            box.leo_runner = LeoPassRunner(cfg.leo_satellites,
                                           lambda hz: RtlSdrSource(hz), box.leo)
        if on_start is not None:
            on_start(box)
        last_mode = None
        last_status = time.monotonic()
        last_heartbeat = time.monotonic()
        STATUS_EVERY_S = 10.0
        try:
            while stop is None or not stop():
                if rx is not None:
                    data = rx.read(rx.in_waiting or 1)
                else:
                    data = b""
                    time.sleep(0.02)
                now, unix_s = time.monotonic(), time.time()
                if now - last_status >= STATUS_EVERY_S:
                    print(box.status_line(now, now - last_status, last_heartbeat,
                                          os.path.dirname(log_path) or "."), flush=True)
                    last_status = now
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
                        box.on_frame(frame[0], frame[1], cam.fov_deg)   # the frame's own time
                if radio is not None:
                    for line in radio.read_lines():
                        box.on_beacon_line(line, now)
                box.step_leo(unix_s, now)
                while True:
                    msg = conn.recv_match(blocking=False)
                    if msg is None:
                        break
                    if msg.get_type() == "HEARTBEAT":
                        last_heartbeat = now
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

        finally:
            done = box.close()
            for path in done["saved"]:
                print(f"saved what this flight learned: {path}")
            if done["recorder"]:
                r = done["recorder"]
                print(f"recorded {r['counts']} ({r['megabytes']:.0f} MB)"
                      + (f"; {r['stopped']}" if r["stopped"] else ""))
            for handle in (rx, cam, radio, conn):
                try:
                    if handle is not None:
                        handle.close()
                except Exception:          # noqa: BLE001 -- closing is best effort
                    pass
            print(f"{box.epochs} epochs logged to {log_path}")

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
    ap.add_argument("--gnss-source", choices=["receiver", "fc"], default="receiver",
                    help="'fc': board only, the flight controller's own GPS is the input (never sends)")
    a = ap.parse_args(argv)
    if a.deny_gnss and a.deny_after is not None:
        ap.error("use --deny-gnss or --deny-after, not both")
    schedule = DenySchedule(a.deny_after, a.deny_for) if a.deny_after is not None else None
    try:
        run(load_config(a.config), deny_gnss=a.deny_gnss, send=not a.no_send,
            schedule=schedule, gnss_source=a.gnss_source)
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
