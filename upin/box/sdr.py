"""
A cheap software-defined radio on the box. UNTESTED on hardware.

RtlSdrSource wraps an RTL-SDR dongle through pyrtlsdr (lazy import): tune
to a centre frequency, read complex samples. The LEO Doppler layer's
tracker turns those into a frequency-versus-time series.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import numpy as np


class RtlSdrSource:
    UNTESTED = True

    def __init__(self, center_hz: float, sample_rate_hz: float = 240_000.0, gain="auto"):
        try:
            from rtlsdr import RtlSdr  # noqa: WPS433 -- lazy by design
        except ImportError as exc:
            raise RuntimeError("pyrtlsdr is not installed (pip install -e '.[sdr]')") from exc
        self._sdr = RtlSdr()
        self._sdr.sample_rate = sample_rate_hz
        self._sdr.center_freq = center_hz
        self._sdr.gain = gain
        self.sample_rate_hz = sample_rate_hz
        self.center_hz = center_hz

    def read(self, seconds: float) -> np.ndarray:
        n = int(seconds * self.sample_rate_hz)
        n = (n // 1024) * 1024 or 1024
        return np.asarray(self._sdr.read_samples(n), dtype=complex)

    def close(self) -> None:
        self._sdr.close()
