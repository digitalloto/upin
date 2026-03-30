"""
Interactive Layer Manager — UPIN

Provides a user-facing interface to dynamically add, remove, enable,
disable, and inspect navigation layers at runtime. Wraps the fusion
engine's register/unregister with higher-level operations.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from upin.core.layer_base import NavigationLayer, LayerReading
from upin.layers.registry import ALL_LAYER_CLASSES, LayerRegistry


@dataclass
class LayerEvent:
    """One layer management event."""
    timestamp: float
    action: str       # ADD, REMOVE, ENABLE, DISABLE, WEIGHT_CHANGE
    layer_id: str
    detail: str


class LayerManager:
    """
    Interactive layer management for UPIN.

    Allows operators to:
    - List all available and active layers
    - Add/remove individual layers at runtime
    - Enable/disable layers without removing them
    - Adjust layer weights and priorities
    - Get layer health and reading diagnostics
    - Create custom layer sets for specific environments
    """

    def __init__(self):
        self._registry = LayerRegistry()
        self._active_layers: Dict[str, NavigationLayer] = {}
        self._disabled_layers: Dict[str, NavigationLayer] = {}
        self._layer_weights: Dict[str, float] = {}
        self._event_log: List[LayerEvent] = []

    # ── Layer Discovery ───────────────────────────────────────────

    def list_available(self) -> List[Dict]:
        """List all available layer types that can be added."""
        available = []
        for layer_id, cls in ALL_LAYER_CLASSES.items():
            instance = cls()
            available.append({
                "layer_id": layer_id,
                "name": instance.name,
                "group": instance.group.value,
                "is_novel": instance.is_novel,
                "is_underwater": instance.is_underwater,
                "accuracy_rating": instance.get_accuracy_rating(),
                "active": layer_id in self._active_layers,
                "disabled": layer_id in self._disabled_layers,
            })
        return available

    def list_active(self) -> List[Dict]:
        """List currently active layers with status."""
        active = []
        for layer_id, layer in self._active_layers.items():
            active.append({
                "layer_id": layer_id,
                "name": layer.name,
                "group": layer.group.value,
                "weight": self._layer_weights.get(layer_id, 1.0),
                "accuracy_rating": layer.get_accuracy_rating(),
                "healthy": layer.status.is_healthy,
            })
        return active

    # ── Add / Remove ──────────────────────────────────────────────

    def add_layer(self, layer_id: str) -> Tuple[bool, str]:
        """Add a layer by ID. Returns (success, message)."""
        if layer_id in self._active_layers:
            return False, f"Layer {layer_id} is already active"

        if layer_id in self._disabled_layers:
            # Re-enable disabled layer
            self._active_layers[layer_id] = self._disabled_layers.pop(layer_id)
            self._log("ENABLE", layer_id, "Re-enabled from disabled")
            return True, f"Layer {layer_id} re-enabled"

        if layer_id not in ALL_LAYER_CLASSES:
            return False, f"Unknown layer ID: {layer_id}. Use list_available() to see options."

        layer = ALL_LAYER_CLASSES[layer_id]()
        self._active_layers[layer_id] = layer
        self._layer_weights[layer_id] = layer.get_accuracy_rating()
        self._log("ADD", layer_id, f"Added with weight {self._layer_weights[layer_id]:.2f}")
        return True, f"Layer {layer_id} ({layer.name}) added"

    def remove_layer(self, layer_id: str) -> Tuple[bool, str]:
        """Remove a layer entirely."""
        if layer_id in self._active_layers:
            del self._active_layers[layer_id]
            self._layer_weights.pop(layer_id, None)
            self._log("REMOVE", layer_id, "Removed from active")
            return True, f"Layer {layer_id} removed"

        if layer_id in self._disabled_layers:
            del self._disabled_layers[layer_id]
            self._log("REMOVE", layer_id, "Removed from disabled")
            return True, f"Layer {layer_id} removed"

        return False, f"Layer {layer_id} not found"

    def disable_layer(self, layer_id: str) -> Tuple[bool, str]:
        """Disable a layer without removing it (can be re-enabled)."""
        if layer_id not in self._active_layers:
            return False, f"Layer {layer_id} is not active"

        self._disabled_layers[layer_id] = self._active_layers.pop(layer_id)
        self._log("DISABLE", layer_id, "Moved to disabled")
        return True, f"Layer {layer_id} disabled"

    def enable_layer(self, layer_id: str) -> Tuple[bool, str]:
        """Re-enable a disabled layer."""
        if layer_id not in self._disabled_layers:
            return False, f"Layer {layer_id} is not disabled"

        self._active_layers[layer_id] = self._disabled_layers.pop(layer_id)
        self._log("ENABLE", layer_id, "Moved to active")
        return True, f"Layer {layer_id} enabled"

    # ── Weight Management ─────────────────────────────────────────

    def set_weight(self, layer_id: str, weight: float) -> Tuple[bool, str]:
        """Set the fusion weight for a layer (0.0-1.0)."""
        if layer_id not in self._active_layers:
            return False, f"Layer {layer_id} is not active"

        weight = max(0.0, min(1.0, weight))
        old = self._layer_weights.get(layer_id, 1.0)
        self._layer_weights[layer_id] = weight
        self._log("WEIGHT_CHANGE", layer_id, f"{old:.2f} -> {weight:.2f}")
        return True, f"Layer {layer_id} weight set to {weight:.2f}"

    # ── Bulk Operations ───────────────────────────────────────────

    def load_preset(self, preset: str) -> Tuple[int, str]:
        """Load a preset layer configuration.

        Presets are organised in three categories:

        **Environment presets** — where is the unit operating?
          minimal, urban, rural, maritime, submarine, aerial, gps_denied, all

        **Mission presets** — what is the mission?
          mission_recon, mission_strike, mission_casevac, mission_patrol,
          mission_covert

        **Unit presets** — what hardware is the UPIN mounted on?
          unit_micro_uav, unit_small_uav, unit_medium_uav, unit_large_uav,
          unit_heavy_uav, unit_ground_vehicle, unit_naval_vessel,
          unit_submarine, unit_soldier

        **Precision presets** — what accuracy do you need?
          precision_centimetre (<10cm), precision_submetre (<1m),
          precision_tactical (1-5m), precision_navigation (5-15m),
          precision_area (15-50m), precision_degraded (50-200m GPS denied)
        """
        presets = self._get_all_presets()

        if preset not in presets:
            cats: Dict[str, List[str]] = {}
            for k in sorted(presets):
                if k.startswith("mission_"):
                    cats.setdefault("mission", []).append(k)
                elif k.startswith("unit_"):
                    cats.setdefault("unit", []).append(k)
                else:
                    cats.setdefault("environment", []).append(k)
            lines = [f"  {c}: {', '.join(v)}" for c, v in cats.items()]
            return 0, "Unknown preset. Available:\n" + "\n".join(lines)

        # Clear current layers
        self._active_layers.clear()
        self._disabled_layers.clear()
        self._layer_weights.clear()

        # Add preset layers
        count = 0
        for layer_id in presets[preset]:
            ok, _ = self.add_layer(layer_id)
            if ok:
                count += 1

        return count, f"Loaded '{preset}' preset with {count} layers"

    # ── Diagnostics ───────────────────────────────────────────────

    def get_layer_info(self, layer_id: str) -> Optional[Dict]:
        """Get detailed info about a specific layer."""
        layer = self._active_layers.get(layer_id) or self._disabled_layers.get(layer_id)
        if not layer:
            return None

        return {
            "layer_id": layer_id,
            "name": layer.name,
            "group": layer.group.value,
            "description": layer.description,
            "bio_inspiration": layer.bio_inspiration,
            "is_novel": layer.is_novel,
            "is_underwater": layer.is_underwater,
            "accuracy_rating": layer.get_accuracy_rating(),
            "weight": self._layer_weights.get(layer_id, 1.0),
            "active": layer_id in self._active_layers,
            "status": {
                "is_active": layer.status.is_active,
                "is_healthy": layer.status.is_healthy,
                "is_trusted": layer.status.is_trusted,
            },
        }

    def get_summary(self) -> Dict:
        """Get layer management summary."""
        return {
            "total_available": len(ALL_LAYER_CLASSES),
            "active": len(self._active_layers),
            "disabled": len(self._disabled_layers),
            "events_logged": len(self._event_log),
        }

    def get_event_log(self, last_n: int = 20) -> List[Dict]:
        """Get recent management events."""
        return [
            {"time": e.timestamp, "action": e.action, "layer": e.layer_id, "detail": e.detail}
            for e in self._event_log[-last_n:]
        ]

    def _log(self, action: str, layer_id: str, detail: str) -> None:
        self._event_log.append(LayerEvent(
            timestamp=time.time(), action=action,
            layer_id=layer_id, detail=detail,
        ))

    # ── Preset Definitions ────────────────────────────────────────

    def _get_all_presets(self) -> Dict[str, List[str]]:
        """Return the complete preset catalogue."""

        # ── Shared building blocks ────────────────────────────────
        _CORE_GPS = ["gps_l1", "navic_l2", "ins_l3", "baro_l11"]
        _CORE_INTERNAL = [                           # unjammable
            "ins_l3", "baro_l11", "magano_l6", "dualqmag_l17",
            "opticflow_l43", "nmrgyro_l57", "serfgyro_l58",
            "gravgrad_l28a", "muon_l40",
        ]
        _RF_URBAN = ["wifi_l8", "celltower_l9", "uwb_d06", "lora_d07"]
        _OPTICAL = ["vslam_l31", "vio_l32", "lidar_l33", "terrain_l5"]
        _ACOUSTIC_WATER = ["acoustic_l10", "sonar_l34", "focsonar_l35"]
        _MAG_FULL = ["magano_l6", "dualqmag_l17", "magmap_l23",
                     "nvdiamond_l30", "efield_c07"]

        return {
            # ── Environment presets ───────────────────────────────
            "minimal": [
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "vslam_l31", "magano_l6", "doppler_l12",
            ],
            "urban": _CORE_GPS + _RF_URBAN + [
                "vslam_l31", "vio_l32", "magano_l6", "doppler_l12",
            ],
            "rural": _CORE_GPS + [
                "magano_l6", "terrain_l5", "eloran_l41", "lora_d07",
                "opticflow_l43", "doppler_l12", "polsky_l25a",
                "monarch_e10",
            ],
            "maritime": _CORE_GPS + _ACOUSTIC_WATER + [
                "polwater_l25b", "latline_l48", "hydrowake_l37",
                "depthpres_b10", "magano_l6", "tern_k05",
            ],
            "submarine": _CORE_INTERNAL + _ACOUSTIC_WATER + [
                "depthpres_b10", "latline_l48", "hydrowake_l37",
                "polwater_l25b", "chemgrad_l26", "efield_c07",
            ],
            "aerial": _CORE_GPS + [
                "doppler_l12", "radaralt_b09", "baro_l11",
                "magano_l6", "opticflow_l43", "startrack_l4",
                "polsky_l25a", "vslam_l31", "monarch_e10",
            ],
            "gps_denied": _CORE_INTERNAL + [
                "terrain_l5", "vslam_l31", "schumann_l59",
                "tern_k05", "monarch_e10",
            ],
            "all": list(ALL_LAYER_CLASSES.keys()),

            # ── Mission presets ───────────────────────────────────
            "mission_recon": _CORE_GPS + _OPTICAL + [
                "magano_l6", "thermal_l38", "hyperspec_l39",
                "opticflow_l43", "tern_k05",
            ],
            "mission_strike": _CORE_GPS + [
                "doppler_l12", "laserdop_l18", "vslam_l31",
                "magano_l6", "rfanomaly_l16", "tern_k05",
                "radaralt_b09",
            ],
            "mission_casevac": _CORE_GPS + [
                "doppler_l12", "radaralt_b09", "vslam_l31",
                "beacon_l20", "radius_l22", "magano_l6",
            ],
            "mission_patrol": _CORE_GPS + _RF_URBAN + [
                "vslam_l31", "magano_l6", "doppler_l12",
                "rfanomaly_l16", "spoofmap_l21",
            ],
            "mission_covert": _CORE_INTERNAL + [
                "terrain_l5", "vslam_l31", "polsky_l25a",
                "monarch_e10", "tern_k05",
            ],

            # ── Unit presets (by hardware platform) ───────────────
            "unit_micro_uav": [                      # <1.5 kg
                "ins_l3", "baro_l11", "magano_l6", "opticflow_l43",
            ],
            "unit_small_uav": [                      # 1.5-25 kg
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "magano_l6", "opticflow_l43", "vslam_l31",
                "wifi_l8",
            ],
            "unit_medium_uav": _CORE_GPS + [         # 25-150 kg
                "magano_l6", "vslam_l31", "wifi_l8", "celltower_l9",
                "uwb_d06", "doppler_l12", "radaralt_b09",
                "opticflow_l43", "rfanomaly_l16",
            ],
            "unit_large_uav": _CORE_GPS + _OPTICAL + _MAG_FULL + [ # 150-600 kg
                "doppler_l12", "laserdop_l18", "radaralt_b09",
                "wifi_l8", "celltower_l9", "uwb_d06",
                "thermal_l38", "rfanomaly_l16", "tern_k05",
            ],
            "unit_heavy_uav": list(ALL_LAYER_CLASSES.keys()),  # >600 kg — all layers
            "unit_ground_vehicle": _CORE_GPS + _RF_URBAN + _OPTICAL + [
                "magano_l6", "doppler_l12", "seismic_l36",
                "tactile_l45", "odometer_l60",
            ],
            "unit_naval_vessel": _CORE_GPS + _ACOUSTIC_WATER + [
                "magano_l6", "dualqmag_l17", "polwater_l25b",
                "latline_l48", "hydrowake_l37", "depthpres_b10",
                "eloran_l41", "soop_l42", "tern_k05",
            ],
            "unit_submarine": _CORE_INTERNAL + _ACOUSTIC_WATER + [
                "depthpres_b10", "latline_l48", "hydrowake_l37",
                "polwater_l25b", "chemgrad_l26", "efield_c07",
                "gravimeter_l28b", "seismic_l36",
            ],
            "unit_soldier": [                        # Dismounted infantry
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "magano_l6", "celltower_l9", "wifi_l8",
                "beacon_l20", "spoofmap_l21",
            ],

            # ── Precision presets (by accuracy requirement) ───────
            "precision_centimetre": [                 # <10 cm — survey grade
                "gps_l1", "navic_l2", "uwb_d06", "ins_l3",
                "vslam_l31", "lidar_l33", "laserdop_l18",
                "depthpres_b10", "qclock_l27",
            ],
            "precision_submetre": [                   # <1 m — precision strike
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "uwb_d06", "vslam_l31", "lidar_l33",
                "doppler_l12", "magano_l6", "radaralt_b09",
            ],
            "precision_tactical": [                   # 1-5 m — tactical ops
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "vslam_l31", "magano_l6", "doppler_l12",
                "wifi_l8", "celltower_l9", "opticflow_l43",
            ],
            "precision_navigation": [                 # 5-15 m — general nav
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "magano_l6", "doppler_l12", "terrain_l5",
            ],
            "precision_area": [                       # 15-50 m — area awareness
                "gps_l1", "ins_l3", "baro_l11", "magano_l6",
                "celltower_l9",
            ],
            "precision_degraded": _CORE_INTERNAL + [  # 50-200 m — GPS denied fallback
                "terrain_l5", "vslam_l31", "schumann_l59",
            ],
        }
