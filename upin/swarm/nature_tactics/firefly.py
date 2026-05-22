"""
Firefly Synchronization — UPIN Swarm

Leaderless time synchronization across the mesh. Each drone adjusts
its clock based on neighbors' timestamps — no GPS time needed.

Real fireflies sync their flashing using only local observation:
if your neighbor flashed slightly before you, speed up slightly.
If after, slow down. Over time the entire swarm synchronizes
to within microseconds — with zero central controller.

Applied to drones: mesh time sync for coordinated operations
(wave wash attacks, formation maneuvers, sensor fusion timestamps)
when GPS time is denied.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ClockState:
    """One drone's internal clock state."""
    drone_id: str
    local_time: float  # this drone's internal clock
    offset_from_true: float = 0.0  # how far off real time
    adjustment_rate: float = 0.0  # current correction being applied
    sync_confidence: float = 0.0  # 0-1, how confident in sync


class FireflyTimeSync:
    """Leaderless time synchronization — no GPS, no master clock.

    Each drone periodically broadcasts its timestamp. When it receives
    a neighbor's timestamp, it nudges its own clock toward the neighbor's.
    Over iterations, all clocks converge to the same time.

    Algorithm (Mirollo-Strogatz inspired):
    1. Each drone has an internal phase (0 to 1)
    2. When phase reaches 1.0 → "flash" (broadcast timestamp)
    3. When you see a neighbor flash → nudge your phase forward by epsilon
    4. Over time, all phases align → synchronized flashing → synchronized clocks
    """

    def __init__(self, coupling_strength: float = 0.05,
                 flash_period_s: float = 1.0):
        self._coupling = coupling_strength
        self._period = flash_period_s
        self._clocks: Dict[str, ClockState] = {}
        self._sync_rounds = 0
        self._max_offset_history: deque = deque(maxlen=100)

    def add_drone(self, drone_id: str, initial_offset_ms: float = 0.0):
        """Add a drone with an initial clock offset (simulates imperfect clocks)."""
        self._clocks[drone_id] = ClockState(
            drone_id=drone_id,
            local_time=time.time() + initial_offset_ms / 1000.0,
            offset_from_true=initial_offset_ms / 1000.0,
        )

    def receive_flash(self, receiver_id: str, sender_id: str,
                      sender_timestamp: float) -> Dict:
        """A drone received a neighbor's timestamp broadcast.

        Adjusts its own clock toward the sender's time.
        """
        receiver = self._clocks.get(receiver_id)
        sender = self._clocks.get(sender_id)
        if not receiver or not sender:
            return {"adjusted": False}

        # Time difference: positive means receiver is behind
        diff = sender_timestamp - receiver.local_time
        adjustment = diff * self._coupling

        receiver.local_time += adjustment
        receiver.offset_from_true += adjustment
        receiver.adjustment_rate = adjustment

        return {
            "adjusted": True,
            "diff_ms": round(diff * 1000, 3),
            "adjustment_ms": round(adjustment * 1000, 3),
            "receiver_offset_ms": round(receiver.offset_from_true * 1000, 3),
        }

    def sync_round(self) -> Dict:
        """Run one complete sync round — every drone broadcasts to neighbors.

        In practice this happens continuously; here we simulate one
        round where each drone exchanges timestamps with all others.
        """
        self._sync_rounds += 1
        adjustments = []

        drones = list(self._clocks.keys())
        for i, sender_id in enumerate(drones):
            sender = self._clocks[sender_id]
            for receiver_id in drones:
                if receiver_id == sender_id:
                    continue
                result = self.receive_flash(
                    receiver_id, sender_id, sender.local_time)
                if result["adjusted"]:
                    adjustments.append(result)

        # Compute max offset across all drones
        offsets = [abs(c.offset_from_true) for c in self._clocks.values()]
        max_offset = max(offsets) if offsets else 0
        avg_offset = sum(offsets) / max(1, len(offsets))
        self._max_offset_history.append(max_offset)

        # Update confidence based on convergence
        for clock in self._clocks.values():
            clock.sync_confidence = max(0, 1.0 - abs(clock.offset_from_true) * 100)

        return {
            "round": self._sync_rounds,
            "drones": len(self._clocks),
            "max_offset_ms": round(max_offset * 1000, 3),
            "avg_offset_ms": round(avg_offset * 1000, 3),
            "adjustments": len(adjustments),
            "converged": max_offset < 0.001,  # <1ms = converged
        }

    def get_synchronized_time(self) -> float:
        """Get the consensus time from the swarm (average of all clocks)."""
        if not self._clocks:
            return time.time()
        return sum(c.local_time for c in self._clocks.values()) / len(self._clocks)

    def get_status(self) -> Dict:
        offsets = [abs(c.offset_from_true) for c in self._clocks.values()]
        return {
            "drones": len(self._clocks),
            "sync_rounds": self._sync_rounds,
            "max_offset_ms": round(max(offsets) * 1000, 3) if offsets else 0,
            "avg_offset_ms": round(sum(offsets) / max(1, len(offsets)) * 1000, 3) if offsets else 0,
            "converged": max(offsets, default=1) < 0.001,
            "coupling_strength": self._coupling,
        }
