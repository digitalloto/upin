"""
Preflight: go / no-go before every start of the box, on the Pi, with the
same box.toml. Every line is measured on the spot, nothing assumed.

  environment   Python 3.11+, pyserial, pymavlink, numpy, scipy
  config        box.toml loads; what it enables; the ports it names exist
  receiver      opens; what arrives in N seconds: NAV-PVT, NAV-SAT, MON-RF
                or MON-HW, rates, bad checksums, NMEA-only; the fix, the
                satellites, the stated accuracy, the receiver's own UTC
  flight ctrl   a heartbeat; who it is; after the stream requests, what
                arrives at what rate against what was asked; whether its
                GPS reports an accuracy (the cross-check needs it); which
                optional streams are absent (that layer will decline)
  disk          free space where the logs and frames go, and the rate the
                recorder will write

The pure functions take callables and fake messages, so the logic is
tested without hardware; `tools/preflight.py` wires the real ports.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional, Tuple

from upin.box.fc_reader import FAST_IDS, MSG_IDS, FcReader, request_streams
from upin.box.ubx_config import observe, verdict as receiver_verdict

GO, NOGO, NOTE = "GO", "NO-GO", "NOTE"

MIN_FREE_MB = 2000.0
"""**Assumption.** Enough for an hour of epoch logs and inputs plus a
margin; frames need more, and the rate line says how much."""
FRAME_MB = 0.256
"""A 256-pixel float32 frame."""
OPTIONAL_STREAMS = {
    "DISTANCE_SENSOR": "camera flow, tags and the patch map scale by the rangefinder",
    "OPTICAL_FLOW": "the flow-chip velocity",
    "VFR_HUD": "the pitot airspeed (fixed wing only)",
    "SERVO_OUTPUT_RAW": "the AI predictor's throttle",
    "SCALED_PRESSURE": "the barometric altitude while GNSS is gone",
}


@dataclass
class Check:
    section: str
    name: str
    status: str          # GO | NO-GO | NOTE
    detail: str


# -- environment and config ---------------------------------------------------------

def check_environment() -> List[Check]:
    out = []
    v = sys.version_info
    out.append(Check("environment", "python", GO if v >= (3, 11) else NOGO,
                     f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 11) else " (needs 3.11+: tomllib)")))
    for mod, why in (("serial", "pyserial: the receiver's port"), ("pymavlink", "the flight controller"),
                     ("numpy", "the filter"), ("scipy", "the checks")):
        try:
            importlib.import_module(mod)
            out.append(Check("environment", mod, GO, why))
        except ImportError:
            out.append(Check("environment", mod, NOGO, f"not installed ({why}): pip install -e '.[box]'"))
    return out


def check_config(path: str, listen_only: bool = True):
    from upin.box.service import load_config
    out = []
    try:
        cfg = load_config(path)
    except Exception as exc:             # noqa: BLE001 -- the reason is the point
        return None, [Check("config", "box.toml", NOGO, f"{path}: {exc}")]
    out.append(Check("config", "box.toml", GO, f"{path} loads"))
    out.append(Check("config", "airframe", GO if cfg.max_accel_ms2 > 0 and cfg.max_airspeed_ms > 0 else NOGO,
                     f"max_accel {cfg.max_accel_ms2} m/s2, max_airspeed {cfg.max_airspeed_ms} m/s"))
    if cfg.wind_dr and not cfg.airframe_id:
        out.append(Check("config", "wind_dr", NOTE, "wind_dr is on but airframe_id is empty: the tilt "
                         "curve is per airframe, so wind DR will decline"))
    on = [k for k in ("camera_flow", "breadcrumbs", "formation", "patch_map_build", "wind_dr")
          if getattr(cfg, k)]
    out.append(Check("config", "layers on", NOTE, ", ".join(on) or "none beyond the checks and the filter"))
    rec = []
    if cfg.input_log_path:
        rec.append("inputs")
    if cfg.frames_dir:
        rec.append(f"frames at {cfg.frame_record_hz:g} Hz")
    out.append(Check("config", "recording", NOTE if rec else NOGO if listen_only else NOTE,
                     ", ".join(rec) if rec else "recording off: set input_log_path (and frames_dir) so the "
                     "flight can be replayed; a data flight without it is half a flight"))
    out.append(Check("config", "mode", NOTE, f"gps_id {cfg.gps_id} (GPS instance {cfg.gps_id + 1}), "
                     f"{'shadow' if cfg.shadow else 'LIVE'}; listen-only runs send nothing regardless"))
    return cfg, out


def check_ports(cfg, gnss_source: str = "receiver") -> List[Check]:
    out = []
    by_id = "/dev/serial/by-id"
    names = sorted(os.listdir(by_id)) if os.path.isdir(by_id) else []
    out.append(Check("ports", "serial devices", NOTE, ", ".join(names) if names else "no /dev/serial/by-id entries"))
    if gnss_source == "receiver":
        ok = os.path.exists(cfg.receiver_port)
        out.append(Check("ports", "receiver_port", GO if ok else NOGO,
                         cfg.receiver_port + ("" if ok else ": not found (unplugged, or the name changed; "
                                              "use /dev/serial/by-id/...)")))
    fc = cfg.fc_connection
    if fc.startswith("/dev/"):
        ok = os.path.exists(fc)
        out.append(Check("ports", "fc_connection", GO if ok else NOGO, fc + ("" if ok else ": not found")))
    else:
        out.append(Check("ports", "fc_connection", NOTE, f"{fc}: a network or pymavlink address, checked "
                         "by the heartbeat below"))
    return out


# -- the receiver --------------------------------------------------------------------

def check_receiver(read: Callable[[], bytes], seconds: float = 10.0,
                   sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic) -> Tuple[List[Check], dict]:
    obs = observe(read, seconds, sleep, clock)
    ok, notes = receiver_verdict(obs)
    proto = "NMEA" if not obs["counts"] and (obs.get("nmea") or {}).get("sentences") else "UBX"
    out = [Check("receiver", "messages", GO if ok else NOGO, f"{proto}: " + "; ".join(notes))]
    fix = obs["last"].get("NMEA-FIX")
    if fix is not None and proto == "NMEA":
        sane = -90 <= fix.lat <= 90 and -180 <= fix.lon <= 180 and 0 <= fix.num_sv <= 100
        out.append(Check("receiver", "last fix", GO if sane else NOGO,
                         f"quality {fix.quality}, fix type {fix.fix_type}, {fix.num_sv} satellites, "
                         f"HDOP {fix.hdop}, {fix.lat:.5f}, {fix.lon:.5f}, UTC {fix.utc}"
                         + ("" if fix.gst_h_acc_m is None else f", receiver accuracy {fix.gst_h_acc_m:.1f} m")))
        if sane and fix.fix_type < 3:
            out.append(Check("receiver", "sky", NOTE, "no 3-D fix yet: antenna outdoors with sky view, "
                             "then wait a minute"))
    pvt = obs["last"].get("NAV-PVT")
    if pvt is not None:
        sane = (-90 <= pvt.lat <= 90 and -180 <= pvt.lon <= 180 and 0 <= pvt.h_acc_m < 1e5
                and 0 <= pvt.num_sv <= 100)
        utc = (f"{pvt.year:04d}-{pvt.month:02d}-{pvt.day:02d} {pvt.hour:02d}:{pvt.minute:02d}:"
               f"{pvt.second:02d}" if pvt.year else "no UTC yet")
        out.append(Check("receiver", "last fix", GO if sane else NOGO,
                         f"fix type {pvt.fix_type}, {pvt.num_sv} satellites, hAcc {pvt.h_acc_m:.1f} m, "
                         f"{pvt.lat:.5f}, {pvt.lon:.5f}, UTC {utc}" +
                         ("" if sane else " -- these look wrong: check the NAV-PVT layout against the "
                          "receiver's interface description")))
        if sane and pvt.fix_type < 3:
            out.append(Check("receiver", "sky", NOTE, "no 3-D fix yet: antenna outdoors with sky view, "
                             "then wait a minute"))
    sat = obs["last"].get("NAV-SAT")
    if sat is not None:
        consts = {}
        for s in sat.satellites:
            consts[s.constellation] = consts.get(s.constellation, 0) + 1
        out.append(Check("receiver", "constellations", NOTE,
                         ", ".join(f"{k} {v}" for k, v in sorted(consts.items())) or "none listed"))
    return out, obs


# -- the flight controller -------------------------------------------------------------

def check_flight_controller(conn, seconds: float = 10.0, sleep: Callable[[float], None] = time.sleep,
                            clock: Callable[[], float] = time.monotonic,
                            heartbeat_timeout: float = 30.0) -> Tuple[List[Check], dict]:
    """conn: a pymavlink-like connection (wait_heartbeat, recv_match, mav,
    target_system, target_component). Sends the eight stream-rate requests
    the box sends; nothing else."""
    out: List[Check] = []
    hb = conn.wait_heartbeat(timeout=heartbeat_timeout)
    if hb is None:
        out.append(Check("flight controller", "heartbeat", NOGO,
                         f"none in {heartbeat_timeout:.0f} s: wrong port or baud, or the flight controller is off"))
        return out, {}
    armed = bool(getattr(hb, "base_mode", 0) & 128)
    out.append(Check("flight controller", "heartbeat", GO,
                     f"system {getattr(conn, 'target_system', '?')} component "
                     f"{getattr(conn, 'target_component', '?')}, vehicle type {getattr(hb, 'type', '?')}, "
                     f"autopilot {getattr(hb, 'autopilot', '?')}, {'ARMED' if armed else 'disarmed'}"))
    request_streams(conn)
    reader = FcReader()
    counts: Dict[str, int] = {}
    t0 = clock()
    while clock() - t0 < seconds:
        msg = conn.recv_match(blocking=False)
        if msg is None:
            sleep(0.005)
            continue
        kind = msg.get_type()
        counts[kind] = counts.get(kind, 0) + 1
        reader.handle(msg, clock())
    span = max(clock() - t0, 1e-6)
    rates = {k: v / span for k, v in counts.items()}
    asked = {name: FAST_IDS.get(name, 10.0) for name in MSG_IDS}
    for name, want in asked.items():
        got = rates.get(name, 0.0)
        if got >= 0.5 * want:
            out.append(Check("flight controller", name, GO, f"{got:.1f} Hz (asked {want:g})"))
        elif got > 0:
            out.append(Check("flight controller", name, NOTE, f"{got:.1f} Hz, asked {want:g}: slow link "
                             "or the flight controller caps it; the box copes with any rate"))
        elif name in OPTIONAL_STREAMS:
            out.append(Check("flight controller", name, NOTE, f"absent: {OPTIONAL_STREAMS[name]} will "
                             "not be available; that layer declines and says so"))
        elif name == "GPS_RAW_INT":
            out.append(Check("flight controller", name, NOTE, "absent: no second receiver for the "
                             "cross-check (it will read NOT RUN)"))
        else:
            out.append(Check("flight controller", name, NOGO, "absent: the box needs attitude and IMU"))
    g = reader.state.gps
    if g is not None:
        if g.h_acc_m is None:
            out.append(Check("flight controller", "GPS accuracy", NOTE,
                             "GPS_RAW_INT carries no h_acc: the cross-check against the flight "
                             "controller's GPS will read NOT RUN. If its receiver is a u-blox, set its "
                             "GPS_TYPE to the u-blox driver so ArduPilot fills the accuracy fields"))
        else:
            out.append(Check("flight controller", "GPS accuracy", GO,
                             f"h_acc {g.h_acc_m:.1f} m, fix type {g.fix_type}, {g.satellites} satellites"))
    ignored = [k for k in counts if k in ("GLOBAL_POSITION_INT", "LOCAL_POSITION_NED", "GPS2_RAW")]
    if ignored:
        out.append(Check("flight controller", "refused as circular", NOTE, ", ".join(ignored) + " arrive and are ignored"))
    return out, {"counts": counts, "rates_hz": rates, "seconds": span}


# -- disk --------------------------------------------------------------------------------

def check_disk(cfg, log_path: str, minutes: float = 30.0) -> List[Check]:
    out = []
    seen = set()
    for label, path in (("logs", log_path), ("inputs", cfg.input_log_path), ("frames", cfg.frames_dir)):
        if not path:
            continue
        d = os.path.dirname(path) or "."
        while d and not os.path.exists(d):
            d = os.path.dirname(d) or "."
        if d in seen:
            continue
        seen.add(d)
        free_mb = shutil.disk_usage(d).free / 1e6
        out.append(Check("disk", f"free for {label} ({d})", GO if free_mb >= MIN_FREE_MB else NOGO,
                         f"{free_mb:.0f} MB free" + ("" if free_mb >= MIN_FREE_MB else
                                                      f" (below {MIN_FREE_MB:.0f} MB)")))
    if cfg.frames_dir:
        per_min = cfg.frame_record_hz * 60.0 * FRAME_MB
        out.append(Check("disk", "frame rate", NOTE, f"{per_min:.0f} MB a minute at {cfg.frame_record_hz:g} "
                         f"frames/s, about {per_min * minutes:.0f} MB for {minutes:.0f} minutes"))
    return out


def check_unit_file(path: str) -> List[Check]:
    if not os.path.exists(path):
        return [Check("service", "unit file", NOTE, f"{path} not installed (fine when running by hand)")]
    text = open(path, encoding="utf-8").read()
    has = "--no-send" in text
    detail = ("runs with --no-send (listen-only)" if has
              else "SENDS GPS_INPUT: add --no-send for listen-only flights; remove it only for shadow "
                   "mode, PI_GUIDE Step 8")
    return [Check("service", "unit file", GO if has else NOTE, f"{path} {detail}")]


# -- the verdict ------------------------------------------------------------------------

def overall(checks: List[Check]) -> str:
    return NOGO if any(c.status == NOGO for c in checks) else GO


def render(checks: List[Check], title: str = "UPIN preflight") -> str:
    lines = [title, "=" * len(title)]
    section = None
    for c in checks:
        if c.section != section:
            section = c.section
            lines.append(f"\n[{section}]")
        lines.append(f"  {c.status:5s}  {c.name}: {c.detail}")
    lines.append(f"\nRESULT: {overall(checks)}")
    if overall(checks) == NOGO:
        lines.append("Fix every NO-GO line, then run again. NOTE lines are facts, not failures.")
    return "\n".join(lines)


def to_json(checks: List[Check], extra: Optional[dict] = None) -> dict:
    return {"result": overall(checks), "checks": [asdict(c) for c in checks], **(extra or {})}
