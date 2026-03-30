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
        """Load a preset layer configuration. Returns (count, message)."""
        presets = {
            "minimal": [
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "vslam_l31", "magano_l6", "doppler_l12",
            ],
            "urban": [
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "wifi_l8", "celltower_l9", "vslam_l31", "vio_l32",
                "magano_l6", "doppler_l12", "uwb_d06",
            ],
            "maritime": [
                "gps_l1", "navic_l2", "ins_l3", "baro_l11",
                "sonar_l34", "focsonar_l35", "acoustic_l10",
                "polwater_l25b", "latline_l48", "hydrowake_l37",
                "depthpres_b10", "magano_l6",
            ],
            "gps_denied": [
                "ins_l3", "baro_l11", "magano_l6", "dualqmag_l17",
                "terrain_l5", "vslam_l31", "opticflow_l43",
                "nmrgyro_l57", "serfgyro_l58", "gravgrad_l28a",
                "muon_l40", "schumann_l59",
            ],
            "all": list(ALL_LAYER_CLASSES.keys()),
        }

        if preset not in presets:
            return 0, f"Unknown preset. Options: {', '.join(presets.keys())}"

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
