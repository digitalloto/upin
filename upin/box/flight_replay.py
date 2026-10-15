"""
Re-run the whole box on the ground from a flight recording, with GNSS
denied in software from any moment, and measure every source against the
receiver's own logged fix.

    python tools/replay_flight.py --config box.toml --log inputs.jsonl \\
        --frames frames/ --deny-after 60 --deny-for 120

The recording (upin/box/recorder.py) holds every flight-controller
message, beacon-radio line, saved camera frame and receiver epoch in the
order the box received them, so the replay calls the same methods the live
loop calls, in the same order. With every frame saved the decisions come
out the same, epoch for epoch (tested). The receiver kept logging during a
software denial, so the error of UPIN's output against the receiver's fix
is computed, never stated; the receiver's own accuracy is the reference's.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional

import numpy as np

from upin.box.gateway import TRUSTED, GnssEpoch
from upin.box.replay import epoch_from_json
from upin.box.service import Box, BoxConfig, DenySchedule
from upin.detection.reachability import DEG_M


class ReplayMsg:
    """A recorded flight-controller message, MAVLink-shaped again."""

    def __init__(self, kind: str, fields: dict):
        self._kind = kind
        self.__dict__.update(fields)

    def get_type(self) -> str:
        return self._kind


def read_input_log(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def is_input_log(path: str) -> bool:
    """A recorder log starts with a header line; the box's epoch log does not."""
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
        return json.loads(first).get("kind") == "header"
    except (OSError, ValueError, AttributeError):
        return False


@dataclass
class EpochRow:
    t: float
    mode: str
    denied: bool
    lat: Optional[float]
    lon: Optional[float]
    h_acc_m: Optional[float]
    ref_lat: Optional[float]        # the receiver's own logged fix
    ref_lon: Optional[float]
    ref_h_acc_m: Optional[float]
    error_m: Optional[float]
    velocity_source: str
    fixes_accepted: List[str]
    checks_failed: List[str]
    reasons: List[str]


@dataclass
class FlightReport:
    config_path: str
    log_path: str
    frames_dir: Optional[str]
    header: dict
    rows: List[EpochRow] = field(default_factory=list)
    frames_replayed: int = 0
    frames_recorded: int = 0
    frames_seen_live: Optional[int] = None
    denial: Optional[dict] = None
    recorder_notes: List[str] = field(default_factory=list)

    # -- summary ------------------------------------------------------------

    def denied_rows(self) -> List[EpochRow]:
        return [r for r in self.rows if r.denied]

    def summary(self) -> dict:
        modes: Dict[str, int] = {}
        for r in self.rows:
            modes[r.mode] = modes.get(r.mode, 0) + 1
        den = self.denied_rows()
        errs = [r.error_m for r in den if r.error_m is not None]
        vsrc: Dict[str, int] = {}
        fixes: Dict[str, int] = {}
        fails: Dict[str, int] = {}
        for r in den:
            vsrc[r.velocity_source] = vsrc.get(r.velocity_source, 0) + 1
            for s in r.fixes_accepted:
                fixes[s] = fixes.get(s, 0) + 1
        for r in self.rows:
            for c in r.checks_failed:
                fails[c] = fails.get(c, 0) + 1
        at = {}
        if den:
            t0 = den[0].t
            for k in (30, 60, 120):
                cand = [r for r in den if r.t - t0 >= k and r.error_m is not None]
                at[f"error_at_{k}s_m"] = cand[0].error_m if cand else None
        return {
            "epochs": len(self.rows), "modes": modes,
            "denied_epochs": len(den), "denied_seconds": (den[-1].t - den[0].t) if den else 0.0,
            "denied_error_mean_m": float(np.mean(errs)) if errs else None,
            "denied_error_max_m": float(np.max(errs)) if errs else None,
            "denied_error_rms_m": float(np.sqrt(np.mean(np.square(errs)))) if errs else None,
            **at,
            "velocity_sources_during_denial": vsrc,
            "fixes_accepted_during_denial": fixes,
            "checks_failed": fails,
            "frames_replayed": self.frames_replayed, "frames_recorded": self.frames_recorded,
            "frames_seen_live": self.frames_seen_live,
            "reference": "the receiver's own logged fix (its stated accuracy applies)",
        }

    def render(self) -> str:
        s = self.summary()
        L = [f"# Flight replay: {os.path.basename(self.log_path)}", "",
             f"Config `{self.config_path}`; recorded with airframe "
             f"`{self.header.get('airframe_id') or '(none)'}`; {s['epochs']} epochs, modes {s['modes']}.",
             ""]
        if self.frames_seen_live is not None and self.frames_recorded < self.frames_seen_live:
            L += [f"> {self.frames_recorded} of {self.frames_seen_live} live frames were saved "
                  f"(frame_record_hz below the camera rate): the camera layers replay on fewer "
                  f"frames than they had in flight, so decisions can differ.", ""]
        for n in self.recorder_notes:
            L += [f"> recorder: {n}", ""]
        if self.denial:
            L += [f"## GNSS denied in software: {self.denial}", "",
                  f"- epochs denied: {s['denied_epochs']} ({s['denied_seconds']:.0f} s)",
                  f"- UPIN's error against the receiver's logged fix: mean "
                  f"{_fmt(s['denied_error_mean_m'])}, rms {_fmt(s['denied_error_rms_m'])}, "
                  f"worst {_fmt(s['denied_error_max_m'])}",
                  f"- error at +30 s {_fmt(s.get('error_at_30s_m'))}, +60 s "
                  f"{_fmt(s.get('error_at_60s_m'))}, +120 s {_fmt(s.get('error_at_120s_m'))}",
                  f"- velocity sources feeding the filter: {s['velocity_sources_during_denial']}",
                  f"- position fixes accepted: {s['fixes_accepted_during_denial'] or 'none'}",
                  ""]
        L += [f"Checks that failed (all epochs): {s['checks_failed'] or 'none'}", "",
              "| t | mode | denied | error vs receiver | velocity | fixes | reasons |",
              "|---:|---|---|---:|---|---|---|"]
        for r in self.rows:
            L.append(f"| {r.t:.1f} | {r.mode} | {'yes' if r.denied else ''} | {_fmt(r.error_m)} | "
                     f"{r.velocity_source} | {', '.join(r.fixes_accepted)} | "
                     f"{'; '.join(r.reasons)[:120]} |")
        L.append("")
        L.append("Every number above is computed by re-running the box; nothing is flight-proven.")
        return "\n".join(L)


def _fmt(x) -> str:
    return "-" if x is None else f"{x:.1f} m"


def _distance_m(lat1, lon1, lat2, lon2) -> float:
    dn = (lat2 - lat1) * DEG_M
    de = (lon2 - lon1) * DEG_M * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dn, de)


def replay(cfg: BoxConfig, config_path: str, log_path: str, frames_dir: Optional[str] = None,
           deny_from: Optional[float] = None, deny_after: Optional[float] = None,
           deny_for: float = 60.0, on_epoch: Optional[Callable] = None,
           pace: Optional[Callable[[float, float], None]] = None) -> FlightReport:
    """Run the box over the recording. deny_from: a recording time from
    which GNSS is denied for deny_for seconds; deny_after: seconds of
    TRUSTED before the denial (as the live --deny-after). on_epoch(box,
    out, sent, row) after every epoch; pace(last_t, t) before each epoch,
    for a real-time replay."""
    header = {}
    cfg = BoxConfig(**{**cfg.__dict__, "input_log_path": "", "frames_dir": ""})
    rows: List[EpochRow] = []
    box = Box(cfg)
    schedule = DenySchedule(deny_after, deny_for) if deny_after is not None else None
    report = FlightReport(config_path, log_path, frames_dir, header, rows)
    last_t: Optional[float] = None
    n_frames_logged = 0
    for rec in read_input_log(log_path):
        kind = rec.get("kind")
        if kind == "header":
            header.update({k: v for k, v in rec.items() if k not in ("kind", "seq")})
            report.header = header
            rec_af = header.get("airframe_id") or ""
            if rec_af and cfg.airframe_id and rec_af != cfg.airframe_id:
                raise ValueError(f"recording was made with airframe_id {rec_af!r}, the config says "
                                 f"{cfg.airframe_id!r}: the learned curves and models would not match")
            report.frames_seen_live = header.get("frames_seen_live")
            continue
        t = float(rec["t"])
        if kind == "fc":
            box.on_fc_message(ReplayMsg(rec["type"], rec["fields"]), t)
        elif kind == "radio":
            box.on_beacon_line(rec["line"], t)
        elif kind == "frame":
            n_frames_logged += 1
            if frames_dir:
                path = os.path.join(frames_dir, rec["file"])
                if os.path.exists(path):
                    box.on_frame(np.load(path), t, rec.get("fov_deg") or cfg.camera_fov_deg)
                    report.frames_replayed += 1
        elif kind == "note":
            text = rec.get("text", "")
            if text.startswith("frames seen live: "):
                report.frames_seen_live = int(text.split(": ")[1])
            else:
                report.recorder_notes.append(text)
        elif kind == "epoch":
            ep = epoch_from_json(json.dumps(rec["epoch"]))
            ref = (ep.lat, ep.lon, ep.h_acc_m) if ep.fix_type >= 3 else (None, None, None)
            denied = False
            if schedule is not None:
                denied = schedule.denied(box._last_mode, t)
            elif deny_from is not None:
                denied = deny_from <= t < deny_from + deny_for
            if denied:
                ep = GnssEpoch(t=ep.t, fix_type=0, jamming_state=ep.jamming_state,
                               power_check=ep.power_check)
            if pace is not None and last_t is not None:
                pace(last_t, t)
            last_t = t
            out, sent = box.process(ep, float(rec.get("unix", 0.0)))
            err = (None if out.lat is None or ref[0] is None
                   else _distance_m(out.lat, out.lon, ref[0], ref[1]))
            fed_t, fed_src = box._velocity_fed
            wd = box.last_wind_dr
            if wd and wd.get("fed"):
                vsrc = "wind DR"
            elif t - fed_t <= 1.0:
                vsrc = fed_src
            else:
                vsrc = "gnss" if out.mode == TRUSTED else "coasting"
            fixes = [s for s, f in box.gateway.last_fixes.items()
                     if f.get("accepted") and abs(f.get("t", -1e9) - t) <= 1.0]
            failed = [c["check"] for c in box.gateway.last_checks if c["status"] == "FAIL"]
            row = EpochRow(t, out.mode, denied, out.lat, out.lon, out.h_acc_m, ref[0], ref[1],
                           ref[2], err, vsrc, fixes, failed, list(out.reasons))
            rows.append(row)
            if on_epoch is not None:
                on_epoch(box, out, sent, row)
    report.frames_recorded = n_frames_logged
    if deny_from is not None or deny_after is not None:
        report.denial = (f"from t = {deny_from:.0f} s for {deny_for:.0f} s" if deny_from is not None
                         else f"after {deny_after:.0f} s of TRUSTED, for {deny_for:.0f} s")
    box.close()
    return report
