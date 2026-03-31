"""
UPIN Agent Package — Real and simulated positioning agents.

Base agents:
    BaseAgent           — Abstract base class for all agents

GNSS / Navigation:
    GNSSAgent           — Multi-constellation GNSS with spoofing detection
    LEO_PNT_Agent       — LEO satellite positioning (placeholder)

Real Device Sensors:
    RealWiFiPositioningAgent      — WiFi scan + Mozilla Location Service
    RealCellularPositioningAgent  — Cell tower scan + OpenCellID / MLS
    RealPhoneSensorAgent          — GPS, accelerometer, gyroscope, magnetometer, barometer

Advanced Fusion:
    MultiLayerFishSchooling       — 60 fish schools with adaptive learning
"""

from upin.agents.base_agent import BaseAgent
from upin.agents.gnss_agent import GNSSAgent
from upin.agents.leo_pnt_agent import LEO_PNT_Agent
from upin.agents.real_wifi_agent import RealWiFiPositioningAgent
from upin.agents.real_cellular_agent import RealCellularPositioningAgent
from upin.agents.real_phone_sensor_agent import RealPhoneSensorAgent
from upin.agents.multi_layer_fish_schooling import MultiLayerFishSchooling

__all__ = [
    "BaseAgent",
    "GNSSAgent",
    "LEO_PNT_Agent",
    "RealWiFiPositioningAgent",
    "RealCellularPositioningAgent",
    "RealPhoneSensorAgent",
    "MultiLayerFishSchooling",
]
