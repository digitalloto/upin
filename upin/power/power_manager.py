"""
Power Management System — UPIN

Dynamic power management for drone deployments. Manages which positioning
layers are active based on battery state, power consumption profiles,
and mission priorities to maximize operational time.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Dict, List, Optional


class PowerState(Enum):
    FULL = auto()        # >80% battery
    NORMAL = auto()      # 50-80% battery
    LOW = auto()         # 20-50% battery
    CRITICAL = auto()    # 5-20% battery
    EMERGENCY = auto()   # <5% battery


class PowerProfile(Enum):
    MAXIMUM_ACCURACY = auto()    # All layers active
    BALANCED = auto()            # Optimize accuracy vs power
    POWER_SAVING = auto()        # Minimal power consumption
    EMERGENCY_ONLY = auto()      # Only essential layers


@dataclass
class LayerPowerConfig:
    """Power configuration for one positioning layer."""
    layer_id: str
    power_consumption_mw: float    # Milliwatts
    accuracy_contribution: float   # 0.0-1.0 how much this layer helps accuracy
    priority: int                 # 1-10 priority (10=critical, 1=optional)
    min_power_state: PowerState   # Minimum power level to keep this layer active


class PowerManager:
    """
    Manages power consumption and layer activation based on battery state.

    Automatically disables power-hungry layers when battery is low while
    maintaining positioning capability with essential layers.
    """

    def __init__(self):
        self.current_battery_level = 100.0  # Percentage
        self.current_power_state = PowerState.FULL
        self.power_profile = PowerProfile.BALANCED

        self.layer_configs: Dict[str, LayerPowerConfig] = {}
        self.power_history: List[Dict] = []

        # Power monitoring
        self.total_power_consumption_mw = 0.0
        self.estimated_runtime_minutes = 0.0

        # Load default layer power configurations
        self._load_default_layer_configs()

    def update_battery_level(self, battery_percentage: float) -> None:
        """Update current battery level and adjust power state."""
        self.current_battery_level = max(0.0, min(100.0, battery_percentage))

        if self.current_battery_level > 80.0:
            self.current_power_state = PowerState.FULL
        elif self.current_battery_level > 50.0:
            self.current_power_state = PowerState.NORMAL
        elif self.current_battery_level > 20.0:
            self.current_power_state = PowerState.LOW
        elif self.current_battery_level > 5.0:
            self.current_power_state = PowerState.CRITICAL
        else:
            self.current_power_state = PowerState.EMERGENCY

        self.power_history.append({
            'timestamp': time.time(),
            'battery_level': self.current_battery_level,
            'power_state': self.current_power_state.name,
            'active_layers': len(self.get_active_layers())
        })

    def get_active_layers(self) -> List[str]:
        """Get list of layers that should be active given current power state."""
        active_layers = []

        for layer_id, config in self.layer_configs.items():
            if self._should_activate_layer(config):
                active_layers.append(layer_id)

        return active_layers

    def _should_activate_layer(self, config: LayerPowerConfig) -> bool:
        """Determine if a layer should be activated given current conditions."""

        power_state_values = {
            PowerState.EMERGENCY: 0,
            PowerState.CRITICAL: 1,
            PowerState.LOW: 2,
            PowerState.NORMAL: 3,
            PowerState.FULL: 4
        }

        current_level = power_state_values[self.current_power_state]
        required_level = power_state_values[config.min_power_state]

        if current_level < required_level:
            return False

        if self.power_profile == PowerProfile.MAXIMUM_ACCURACY:
            return True
        elif self.power_profile == PowerProfile.EMERGENCY_ONLY:
            return config.priority >= 8
        elif self.power_profile == PowerProfile.POWER_SAVING:
            return config.priority >= 6
        else:  # BALANCED
            if self.current_power_state in [PowerState.FULL, PowerState.NORMAL]:
                return config.priority >= 4
            elif self.current_power_state == PowerState.LOW:
                return config.priority >= 6
            else:
                return config.priority >= 8

    def calculate_power_consumption(self, active_layers: List[str]) -> float:
        """Calculate total power consumption for given active layers."""
        total_power = 0.0

        for layer_id in active_layers:
            config = self.layer_configs.get(layer_id)
            if config:
                total_power += config.power_consumption_mw

        return total_power

    def estimate_runtime(self, active_layers: List[str]) -> float:
        """Estimate remaining runtime in minutes with given active layers."""
        power_consumption = self.calculate_power_consumption(active_layers)

        if power_consumption <= 0:
            return float('inf')

        # Assume 5000mAh battery at 3.7V = 18.5Wh = 18500mWh
        total_battery_capacity_mwh = 18500.0
        remaining_capacity_mwh = (self.current_battery_level / 100.0) * total_battery_capacity_mwh

        runtime_hours = remaining_capacity_mwh / power_consumption
        return runtime_hours * 60.0

    def optimize_for_runtime(self, target_runtime_minutes: float) -> List[str]:
        """Select optimal layers to achieve target runtime."""

        efficiency_sorted = []
        for layer_id, config in self.layer_configs.items():
            efficiency = config.accuracy_contribution / max(config.power_consumption_mw, 1.0)
            efficiency_sorted.append((efficiency, layer_id, config))

        efficiency_sorted.sort(reverse=True, key=lambda x: x[0])

        selected_layers: List[str] = []

        for efficiency, layer_id, config in efficiency_sorted:
            test_layers = selected_layers + [layer_id]
            estimated_runtime = self.estimate_runtime(test_layers)

            if estimated_runtime >= target_runtime_minutes:
                selected_layers.append(layer_id)
            else:
                break

        return selected_layers

    def _load_default_layer_configs(self) -> None:
        """Load default power configurations for UPIN layers."""

        configs = [
            LayerPowerConfig("gps", 150.0, 0.9, 8, PowerState.EMERGENCY),
            LayerPowerConfig("imu", 50.0, 0.7, 9, PowerState.EMERGENCY),
            LayerPowerConfig("magnetometer", 25.0, 0.4, 6, PowerState.LOW),
            LayerPowerConfig("barometric", 10.0, 0.3, 5, PowerState.LOW),
            LayerPowerConfig("wifi_rssi", 300.0, 0.6, 7, PowerState.CRITICAL),
            LayerPowerConfig("wifi_csi", 800.0, 0.8, 6, PowerState.NORMAL),
            LayerPowerConfig("cellular", 400.0, 0.5, 7, PowerState.CRITICAL),
            LayerPowerConfig("bluetooth", 100.0, 0.3, 4, PowerState.NORMAL),
            LayerPowerConfig("camera", 2000.0, 0.7, 5, PowerState.NORMAL),
            LayerPowerConfig("lidar", 5000.0, 0.9, 3, PowerState.FULL),
            LayerPowerConfig("uwb", 200.0, 0.8, 4, PowerState.NORMAL),
            LayerPowerConfig("acoustic", 150.0, 0.4, 3, PowerState.NORMAL),
        ]

        for config in configs:
            self.layer_configs[config.layer_id] = config

    def get_power_status(self) -> Dict:
        """Get comprehensive power management status."""
        active_layers = self.get_active_layers()
        power_consumption = self.calculate_power_consumption(active_layers)
        estimated_runtime = self.estimate_runtime(active_layers)

        return {
            'battery_level_percent': self.current_battery_level,
            'power_state': self.current_power_state.name,
            'power_profile': self.power_profile.name,
            'active_layers': active_layers,
            'total_layers': len(self.layer_configs),
            'power_consumption_mw': power_consumption,
            'estimated_runtime_minutes': estimated_runtime,
            'layer_configs': {
                layer_id: {
                    'power_mw': config.power_consumption_mw,
                    'priority': config.priority,
                    'active': layer_id in active_layers
                }
                for layer_id, config in self.layer_configs.items()
            }
        }
