"""
Carrier tracking for the LEO Doppler layer: from radio samples to a
frequency-versus-time series.

  track_carrier   chunk the IQ stream, FFT each chunk, take the strongest
                  line near the expected carrier with parabolic
                  interpolation; sigma from the bin width and the line's
                  signal-to-noise. Returns one observation per chunk.
  synth_iq        SIMULATION: a tone following a given frequency series,
                  plus noise, for testing the tracker without a radio.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np


def track_carrier(iq: np.ndarray, fs_hz: float, t0_unix: float, expect_hz: float = 0.0,
                  search_hz: float = 6000.0, chunk_s: float = 1.0,
                  min_snr_db: float = 6.0) -> List[Tuple[float, float, float]]:
    """(t_unix, frequency offset from the tuned centre in Hz, sigma Hz) per
    chunk in which a line stands clearly above the noise."""
    n = int(chunk_s * fs_hz)
    out = []
    win = np.hanning(n)
    for k in range(len(iq) // n):
        seg = iq[k * n:(k + 1) * n] * win
        spec = np.abs(np.fft.fftshift(np.fft.fft(seg))) ** 2
        freqs = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / fs_hz))
        sel = np.abs(freqs - expect_hz) <= search_hz
        if sel.sum() < 8:
            continue
        idx = np.flatnonzero(sel)
        i = idx[np.argmax(spec[idx])]
        noise = np.median(spec[idx])
        snr_db = 10 * math.log10(max(spec[i] / max(noise, 1e-30), 1e-12))
        if snr_db < min_snr_db or i == 0 or i == len(spec) - 1:
            continue
        a, b, c = spec[i - 1], spec[i], spec[i + 1]
        delta = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        bin_hz = fs_hz / n
        f_hat = freqs[i] + delta * bin_hz
        sigma = bin_hz / math.sqrt(max(10 ** (snr_db / 10), 1.0)) + 0.05 * bin_hz
        out.append((t0_unix + (k + 0.5) * chunk_s, float(f_hat), float(sigma)))
    return out


def synth_iq(freq_hz_series: np.ndarray, fs_hz: float, chunk_s: float = 1.0,
             snr_db: float = 10.0, rng=None) -> np.ndarray:
    """SIMULATION: a carrier whose offset follows freq_hz_series, one value
    per chunk, with complex white noise at the given SNR per sample."""
    rng = rng or np.random.default_rng(0)
    n = int(chunk_s * fs_hz)
    phase = 0.0
    out = np.empty(n * len(freq_hz_series), dtype=complex)
    amp_noise = 10 ** (-snr_db / 20)
    for k, f in enumerate(freq_hz_series):
        t = np.arange(n) / fs_hz
        seg = np.exp(1j * (phase + 2 * np.pi * f * t))
        phase = (phase + 2 * np.pi * f * n / fs_hz) % (2 * np.pi)
        out[k * n:(k + 1) * n] = seg + amp_noise * (rng.normal(size=n) + 1j * rng.normal(size=n)) / math.sqrt(2)
    return out
