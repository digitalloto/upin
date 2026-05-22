"""
Frequency Hopping Spread Spectrum (FHSS) — UPIN

Anti-jam overlay that can be applied on top of any radio.
Rapidly switches transmission frequency across a wide band
following a pseudo-random sequence known only to the swarm.

A jammer would need to jam the ENTIRE band simultaneously
(very high power) instead of just one frequency. Makes
individual-frequency jamming ineffective.

Used by: military radios (SINCGARS), Bluetooth (79 channels),
GPS military signal (P(Y) code).

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class HopSequence:
    """A frequency hopping pattern."""
    sequence_id: str
    frequencies_mhz: List[float]
    hop_rate_hz: float  # hops per second
    dwell_time_ms: float  # time on each frequency
    seed: int = 0  # PRNG seed (shared secret)


class FrequencyHopper:
    """FHSS anti-jam overlay for any radio channel.

    Generates a pseudo-random hop sequence from a shared secret seed.
    All swarm members with the same seed hop in synchronization.
    An adversary without the seed can't predict the next frequency.

    Hop rate: 100-1000 hops/second (military grade).
    Band width: typically 30-80 MHz spread.
    """

    def __init__(self, band_start_mhz: float = 902.0,
                 band_end_mhz: float = 928.0,
                 num_channels: int = 50,
                 hop_rate_hz: float = 200):
        self._band_start = band_start_mhz
        self._band_end = band_end_mhz
        self._num_channels = num_channels
        self._hop_rate = hop_rate_hz
        self._dwell_ms = 1000.0 / hop_rate_hz

        # Generate channel table
        step = (band_end_mhz - band_start_mhz) / num_channels
        self._channels = [band_start_mhz + i * step for i in range(num_channels)]

        self._seed: int = 0
        self._hop_index: int = 0
        self._sequence: List[int] = []
        self._jammed_channels: set = set()

    def set_seed(self, seed: int):
        """Set the shared secret seed for hop sequence generation."""
        self._seed = seed
        self._generate_sequence()

    def set_seed_from_key(self, key: str):
        """Derive seed from a passphrase/key."""
        h = hashlib.sha256(key.encode()).digest()
        self._seed = int.from_bytes(h[:4], 'big')
        self._generate_sequence()

    def _generate_sequence(self):
        """Generate pseudo-random hop sequence from seed."""
        import random
        rng = random.Random(self._seed)
        self._sequence = list(range(self._num_channels))
        rng.shuffle(self._sequence)
        # Extend to 1000 hops (repeating shuffled pattern)
        full = []
        for _ in range(20):
            perm = list(range(self._num_channels))
            rng.shuffle(perm)
            full.extend(perm)
        self._sequence = full

    def get_current_frequency(self) -> float:
        """Get the current transmission frequency."""
        if not self._sequence:
            return self._channels[0]
        idx = self._sequence[self._hop_index % len(self._sequence)]
        return self._channels[idx % self._num_channels]

    def hop(self) -> Dict:
        """Advance to next frequency in the sequence."""
        self._hop_index += 1
        freq = self.get_current_frequency()
        channel_idx = self._sequence[self._hop_index % len(self._sequence)]

        # Skip jammed channels
        skipped = 0
        while channel_idx in self._jammed_channels and skipped < self._num_channels:
            self._hop_index += 1
            channel_idx = self._sequence[self._hop_index % len(self._sequence)]
            freq = self._channels[channel_idx % self._num_channels]
            skipped += 1

        return {
            "frequency_mhz": round(freq, 3),
            "channel": channel_idx % self._num_channels,
            "hop_number": self._hop_index,
            "dwell_ms": self._dwell_ms,
            "jammed_channels_skipped": skipped,
        }

    def report_jammed_channel(self, channel_idx: int):
        """Mark a channel as jammed — will be skipped in future hops."""
        self._jammed_channels.add(channel_idx)

    def clear_jammed(self):
        self._jammed_channels.clear()

    def get_anti_jam_effectiveness(self) -> Dict:
        """How effective is the hopping against current jamming?"""
        total = self._num_channels
        jammed = len(self._jammed_channels)
        available = total - jammed
        # Jammer needs to jam ALL channels to be effective
        # With 50 channels, jamming 5 = 90% of comms still works
        effectiveness = available / max(1, total)
        return {
            "total_channels": total,
            "jammed_channels": jammed,
            "available_channels": available,
            "comm_availability_pct": round(effectiveness * 100, 1),
            "jammer_needs_to_cover_mhz": round(self._band_end - self._band_start, 1),
            "hop_rate_hz": self._hop_rate,
        }

    def get_status(self) -> Dict:
        return {
            "band_mhz": f"{self._band_start}-{self._band_end}",
            "channels": self._num_channels,
            "hop_rate_hz": self._hop_rate,
            "dwell_ms": self._dwell_ms,
            "current_frequency_mhz": round(self.get_current_frequency(), 3),
            "hop_number": self._hop_index,
            "jammed_channels": len(self._jammed_channels),
            "seed_set": self._seed != 0,
            **self.get_anti_jam_effectiveness(),
        }
