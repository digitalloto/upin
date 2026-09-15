"""
Quantum timing prior — Q3 feeding the TDOA layers.

Every time-difference-of-arrival fix in UPIN shares one hidden dependency:
how well the receivers agree on what time it is. The layer computes a range
as toa_s * propagation_speed, so a clock error becomes a range error directly,
and it is a *systematic* error — averaging more measurements does not remove
it. One nanosecond of sync error is 30 cm of RF range error and stays there.

Four layers already in UPIN are limited this way:

    acoustic_l10   passive acoustic triangulation   1500 m/s
    eloran_l41     eLORAN terrestrial               3e8 m/s
    otdoa_d22      LTE observed TDOA                3e8 m/s
    univbeacon_k11 universal beacon                 varies by signal

Q3's entangled clock network knows its own sync uncertainty. This module
turns that number into an honest accuracy floor for each of those layers and
applies it at fusion time.

Deliberately built as a post-processor. It reads LayerReading objects and
returns adjusted ones — no existing layer file is modified, so nothing that
works today can break. A platform with no quantum clock simply never calls
it and the layers behave exactly as before.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from upin.core.layer_base import LayerReading

C_LIGHT = 299_792_458.0
SOUND_WATER = 1500.0
SOUND_AIR = 343.0

# Propagation speed per TDOA layer, used to convert sync error into range error
TDOA_LAYERS: Dict[str, float] = {
    "acoustic_l10": SOUND_WATER,
    "seabed_f05": SOUND_WATER,
    "airsonar_f06": SOUND_AIR,
    "eloran_l41": C_LIGHT,
    "otdoa_d22": C_LIGHT,
    "ecid_d21": C_LIGHT,
    "univbeacon_k11": C_LIGHT,
    "omega_d15": C_LIGHT,
    "decca_d16": C_LIGHT,
    "pseudolite_d14": C_LIGHT,
    "gps_l1": C_LIGHT,
    "navic_l2": C_LIGHT,
}

# Sync quality a free-running oscillator holds without any discipline.
# A decent TCXO drifts into the tens of nanoseconds within a minute.
FREE_RUNNING_SYNC_NS = 50.0


@dataclass
class TimingState:
    """Current swarm-wide timing quality."""
    sync_uncertainty_ns: float = FREE_RUNNING_SYNC_NS
    source: str = "free_running"          # free_running | classical | quantum
    clocks_in_network: int = 0
    advantage_over_sql: float = 1.0
    updated_at: float = field(default_factory=time.time)

    def age_s(self) -> float:
        return max(0.0, time.time() - self.updated_at)

    def effective_sync_ns(self, holdover_drift_ns_per_s: float = 2.0) -> float:
        """Sync degrades after the last sync pulse — holdover is not free."""
        return self.sync_uncertainty_ns + holdover_drift_ns_per_s * self.age_s()


class QuantumTimingPrior:
    """Converts Q3 clock sync quality into per-layer range accuracy floors.

    Usage is deliberately one-directional. Q3 pushes its sync state in,
    the fusion engine pulls adjusted readings out, and no layer knows this
    module exists.
    """

    def __init__(self, holdover_drift_ns_per_s: float = 2.0):
        self._state = TimingState()
        self._holdover = holdover_drift_ns_per_s
        self._updates = 0
        self._readings_adjusted = 0
        self._best_sync_ns = FREE_RUNNING_SYNC_NS

    # -- input side -------------------------------------------------

    def update_from_q3(self, q3_reading: LayerReading) -> Dict:
        """Ingest a reading from the Q3 quantum clock network layer."""
        d = q3_reading.raw_data or {}
        sync_ns = d.get("sync_uncertainty_ns")
        if sync_ns is None:
            return {"accepted": False, "reason": "no sync_uncertainty_ns in reading"}

        mode = d.get("sync_mode", "unknown")
        self._state = TimingState(
            sync_uncertainty_ns=float(sync_ns),
            source="quantum" if mode == "entangled_ghz" else "classical",
            clocks_in_network=int(d.get("clocks_in_network", 0)),
            advantage_over_sql=float(d.get("advantage_over_sql", 1.0)),
        )
        self._updates += 1
        self._best_sync_ns = min(self._best_sync_ns, float(sync_ns))
        return {
            "accepted": True,
            "sync_ns": float(sync_ns),
            "source": self._state.source,
            "improvement_over_free_running": FREE_RUNNING_SYNC_NS / max(float(sync_ns), 1e-9),
        }

    def set_classical(self, sync_ns: float, source: str = "classical"):
        """Fall back to a classically disciplined clock (GPS-steered, PTP)."""
        self._state = TimingState(sync_uncertainty_ns=sync_ns, source=source)
        self._updates += 1

    # -- query side -------------------------------------------------

    def range_floor_m(self, layer_id: str) -> Optional[float]:
        """Systematic range error this layer cannot beat at current sync."""
        speed = TDOA_LAYERS.get(layer_id)
        if speed is None:
            return None
        return self._state.effective_sync_ns(self._holdover) * 1e-9 * speed

    def improvement_factor(self, layer_id: str) -> float:
        """How much better this layer is than it would be free-running."""
        speed = TDOA_LAYERS.get(layer_id)
        if speed is None:
            return 1.0
        free = FREE_RUNNING_SYNC_NS * 1e-9 * speed
        now = max(self.range_floor_m(layer_id) or free, 1e-12)
        return free / now

    # -- application ------------------------------------------------

    def apply(self, reading: LayerReading) -> LayerReading:
        """Adjust one reading's accuracy to respect the timing floor.

        The floor can only make a reading *more* honest. If a layer already
        claims worse accuracy than the timing floor, that claim stands —
        timing is not its binding constraint. If it claims better than the
        floor, the claim is impossible and gets corrected upward.
        """
        floor = self.range_floor_m(reading.layer_id)
        if floor is None or reading.position is None:
            return reading

        claimed = reading.position.accuracy_m or 0.0
        if claimed >= floor:
            limited_by = "layer_physics"
            new_acc = claimed
        else:
            limited_by = "clock_sync"
            new_acc = floor

        reading.position.accuracy_m = new_acc

        # A quantum-synced clock earns a modest confidence uplift; a stale
        # or free-running one costs confidence.
        if self._state.source == "quantum" and limited_by == "layer_physics":
            reading.self_confidence = min(0.99, reading.self_confidence * 1.10)
        elif limited_by == "clock_sync" and self._state.source == "free_running":
            reading.self_confidence *= 0.80

        raw = dict(reading.raw_data or {})
        raw.update({
            "timing_floor_m": round(floor, 6),
            "timing_limited_by": limited_by,
            "sync_uncertainty_ns": round(
                self._state.effective_sync_ns(self._holdover), 5),
            "sync_source": self._state.source,
            "timing_improvement_x": round(self.improvement_factor(reading.layer_id), 2),
        })
        reading.raw_data = raw
        self._readings_adjusted += 1
        return reading

    def apply_all(self, readings: Iterable[LayerReading]) -> List[LayerReading]:
        return [self.apply(r) for r in readings]

    def affected_layers(self, available: Optional[Iterable[str]] = None) -> List[str]:
        ids = set(TDOA_LAYERS)
        if available is not None:
            ids &= set(available)
        return sorted(ids)

    def get_status(self) -> Dict:
        s = self._state
        return {
            "sync_uncertainty_ns": round(s.sync_uncertainty_ns, 5),
            "effective_sync_ns": round(s.effective_sync_ns(self._holdover), 5),
            "source": s.source,
            "clocks_in_network": s.clocks_in_network,
            "advantage_over_sql": round(s.advantage_over_sql, 3),
            "age_s": round(s.age_s(), 3),
            "best_sync_ns": round(self._best_sync_ns, 5),
            "updates": self._updates,
            "readings_adjusted": self._readings_adjusted,
            "rf_range_floor_m": round(
                s.effective_sync_ns(self._holdover) * 1e-9 * C_LIGHT, 4),
            "acoustic_range_floor_m": round(
                s.effective_sync_ns(self._holdover) * 1e-9 * SOUND_WATER, 9),
            "tdoa_layers_covered": len(TDOA_LAYERS),
        }
