"""
Flight recorder: everything the box received, in the order it received it,
so the whole box can be re-run on the ground (upin/box/flight_replay.py).

The input log is JSON lines with a running sequence number:

  {"kind": "header", ...}            the config the flight was recorded with
  {"kind": "fc", "type": "ATTITUDE", "fields": {...}, "t": ...}
  {"kind": "radio", "line": "...", "t": ...}          beacon radio lines
  {"kind": "frame", "file": "<t>.npy", "t": ...}      a saved camera frame
  {"kind": "epoch", "epoch": {...GnssEpoch...}, "t": ..., "unix": ...}

Camera frames go to `frames_dir` as float32 `.npy` named by their own
timestamp, at most `frame_hz` a second (**assumption** 2 Hz: a 256-px
frame is 256 KB, so 2 Hz is about 30 MB a minute on the Pi's card). A
replay reproduces the live decisions exactly only when every frame was
saved (frame_hz at or above the camera's rate); at a lower rate the
replayed camera layers see fewer frames, and the report says so.

Recording never stops the box: when the card's free space falls below
`min_free_mb` the recorder stops saving and records why.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from typing import IO, Optional

import numpy as np


class FlightRecorder:
    MIN_FREE_MB = 500.0
    """**Assumption.** Below this much free space the recorder stops; the
    box, its epoch log and the flight carry on."""
    CHECK_EVERY = 25           # frames between free-space checks

    def __init__(self, input_log_path: str = "", frames_dir: str = "",
                 frame_hz: float = 2.0, min_free_mb: float = MIN_FREE_MB,
                 header: Optional[dict] = None):
        self.input_log_path, self.frames_dir = input_log_path, frames_dir
        self.frame_hz = frame_hz
        self.min_free_mb = min_free_mb
        self._log: Optional[IO[str]] = None
        if input_log_path:
            Path(input_log_path).parent.mkdir(parents=True, exist_ok=True)
            self._log = open(input_log_path, "a", encoding="utf-8")
        if frames_dir:
            Path(frames_dir).mkdir(parents=True, exist_ok=True)
        self.seq = 0
        self.counts = {"fc": 0, "radio": 0, "frame": 0, "epoch": 0}
        self.frames_seen = 0
        self.bytes = 0
        self.stopped: Optional[str] = None
        self._next_frame_t = -math.inf
        if header is not None:
            self._write({"kind": "header", **header})

    # -- writing ------------------------------------------------------------

    def _write(self, rec: dict) -> None:
        if self._log is None:
            return
        self.seq += 1
        line = json.dumps({"seq": self.seq, **rec}, default=str) + "\n"
        self._log.write(line)
        self.bytes += len(line)
        if self.seq % 50 == 0:
            self._log.flush()

    @staticmethod
    def _fields(msg) -> dict:
        if hasattr(msg, "to_dict"):
            d = msg.to_dict()
            d.pop("mavpackettype", None)
            return d
        return {k: v for k, v in vars(msg).items() if not k.startswith("_")}

    def fc_message(self, msg, t: float) -> None:
        if self._log is None:
            return
        self.counts["fc"] += 1
        self._write({"kind": "fc", "t": t, "type": msg.get_type(), "fields": self._fields(msg)})

    def radio_line(self, line: str, t: float) -> None:
        if self._log is None:
            return
        self.counts["radio"] += 1
        self._write({"kind": "radio", "t": t, "line": line})

    def frame(self, image, t: float, fov_deg: Optional[float] = None) -> Optional[str]:
        """Save the frame if the rate allows and the disk has room; returns
        the file name or None. The field of view travels with the frame:
        the camera layers scale by it."""
        self.frames_seen += 1
        if not self.frames_dir or self.stopped or t < self._next_frame_t:
            return None
        if self.counts["frame"] % self.CHECK_EVERY == 0:
            free_mb = shutil.disk_usage(self.frames_dir).free / 1e6
            if free_mb < self.min_free_mb:
                self.stopped = (f"free space {free_mb:.0f} MB below {self.min_free_mb:.0f} MB: "
                                "frames no longer saved; the box carries on")
                self._write({"kind": "note", "t": t, "text": self.stopped})
                return None
        name = f"{t:.3f}.npy"
        path = os.path.join(self.frames_dir, name)
        np.save(path, np.asarray(image, dtype=np.float32))
        self.bytes += os.path.getsize(path)
        self.counts["frame"] += 1
        self._next_frame_t = t + 1.0 / self.frame_hz
        self._write({"kind": "frame", "t": t, "file": name, "fov_deg": fov_deg})
        return name

    def epoch(self, epoch_json: str, t: float, unix_s: float) -> None:
        if self._log is None:
            return
        self.counts["epoch"] += 1
        self._write({"kind": "epoch", "t": t, "unix": unix_s, "epoch": json.loads(epoch_json)})

    # -- status -------------------------------------------------------------

    def status(self) -> dict:
        return {"input_log": self.input_log_path or None, "frames_dir": self.frames_dir or None,
                "counts": dict(self.counts), "frames_seen": self.frames_seen,
                "frames_saved": self.counts["frame"], "megabytes": self.bytes / 1e6,
                "stopped": self.stopped}

    def close(self) -> None:
        if self._log is not None:
            self._log.flush()
            self._log.close()
            self._log = None
