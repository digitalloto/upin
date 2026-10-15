"""
Frames from a downward camera for the box. UNTESTED on hardware.

  PiCameraSource   the Raspberry Pi camera through picamera2 (lazy import),
                   greyscale frames at a chosen size
  FolderSource     frames saved as .npy files named by their time, for
                   replaying a recorded run

The camera's field of view must be the real lens's: it sets every distance
the tag and flow layers compute. The default is a labelled assumption.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

DEFAULT_FOV_DEG = 62.0
"""**Assumption.** Horizontal field of view of a Raspberry Pi camera module
v2 (about 62 degrees per its datasheet). Check the module actually fitted;
a Camera Module 3 is wider."""


class FrameSource:
    fov_deg: float = DEFAULT_FOV_DEG

    def read(self) -> Optional[Tuple[np.ndarray, float]]:
        """(greyscale image, monotonic time) or None when no new frame."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class PiCameraSource(FrameSource):
    UNTESTED = True

    def __init__(self, size_px: int = 256, fov_deg: float = DEFAULT_FOV_DEG,
                 rate_hz: float = 10.0):
        try:
            from picamera2 import Picamera2  # noqa: WPS433 -- lazy by design
        except ImportError as exc:
            raise RuntimeError("picamera2 is not installed (pip install -e '.[camera]' "
                               "on the Pi); PiCameraSource is untested") from exc
        self.fov_deg = fov_deg
        self._period = 1.0 / rate_hz
        self._next = 0.0
        self._cam = Picamera2()
        self._cam.configure(self._cam.create_video_configuration(
            main={"size": (size_px, size_px), "format": "YUV420"}))
        self._cam.start()

    def read(self):
        now = time.monotonic()
        if now < self._next:
            return None
        self._next = now + self._period
        yuv = self._cam.capture_array("main")
        n = yuv.shape[1]
        return np.asarray(yuv[:n, :n], float) / 255.0, now      # the Y plane

    def close(self):
        self._cam.stop()


class FolderSource(FrameSource):
    """Frames `<t>.npy` (float image) in a folder, replayed in time order at
    the recorded spacing, or as fast as asked."""

    def __init__(self, folder: str, fov_deg: float = DEFAULT_FOV_DEG,
                 realtime: bool = True):
        self.fov_deg = fov_deg
        self._files = sorted(Path(folder).glob("*.npy"), key=lambda p: float(p.stem))
        self._i = 0
        self._realtime = realtime
        self._t0 = time.monotonic()
        self._first = float(self._files[0].stem) if self._files else 0.0

    def read(self):
        if self._i >= len(self._files):
            return None
        f = self._files[self._i]
        t = float(f.stem)
        if self._realtime and time.monotonic() - self._t0 < t - self._first:
            return None
        self._i += 1
        return np.load(f), t


def open_camera(spec: str, size_px: int, fov_deg: float) -> FrameSource:
    if spec == "pi":
        return PiCameraSource(size_px, fov_deg)
    if Path(spec).is_dir():
        return FolderSource(spec, fov_deg)
    raise ValueError(f"camera must be 'pi' or a folder of .npy frames, not {spec!r}")
