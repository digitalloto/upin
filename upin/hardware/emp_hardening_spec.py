"""
EMP Hardening Specifications — UPIN UAV Hardware

Hardware protection specifications for different UAV groups against
electromagnetic pulse (EMP), high-power microwave (HPM), and
electronic warfare threats.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from enum import auto, Enum
from typing import Dict, List


class UAVGroup(Enum):
    GROUP_1 = auto()   # <1.5kg
    GROUP_2 = auto()   # 1.5-25kg
    GROUP_3 = auto()   # 25-150kg
    GROUP_4 = auto()   # 150-600kg
    GROUP_5 = auto()   # >600kg


class HardwareSpec:
    """
    UAV hardware configuration and EMP hardening specifications.

    Provides recommended UPIN agent configurations and protection
    specifications for different UAV weight groups.
    """

    def __init__(self):
        self.uav_group_configs = self._init_group_configs()
        self.faraday_shield_spec = self._init_faraday_spec()

    def _init_group_configs(self) -> Dict[UAVGroup, Dict]:
        return {
            UAVGroup.GROUP_1: {
                "weight_range": "<1.5kg",
                "description": "Micro UAV - minimal payload",
                "recommended_agents": [
                    "imu", "barometric", "magnetometer", "visual_odometry",
                ],
                "optional_agents": ["acoustic_beacon"],
                "communication": ["LoRa_mesh"],
                "power_budget_w": 5,
                "emp_hardening": "NONE - size/weight constraints",
                "protection_level": "Inherent only (small target cross-section)",
                "mil_std_compliance": "Not practical",
                "notes": "Rely on distributed swarm redundancy for EMP resilience",
            },
            UAVGroup.GROUP_2: {
                "weight_range": "1.5-25kg",
                "description": "Small UAV - limited payload",
                "recommended_agents": [
                    "gps", "imu", "barometric", "magnetometer",
                    "visual_odometry", "wifi_rssi",
                ],
                "optional_agents": ["cellular", "acoustic_beacon", "uwb"],
                "communication": ["LoRa_mesh", "WiFi", "4G/5G"],
                "power_budget_w": 25,
                "emp_hardening": "Basic EMI shielding only",
                "protection_level": "Component-level transient protection",
                "mil_std_compliance": "MIL-STD-461 - partial (power lines only)",
                "notes": "Basic surge protection on power and antenna inputs",
            },
            UAVGroup.GROUP_3: {
                "weight_range": "25-150kg",
                "description": "Medium UAV - moderate payload",
                "recommended_agents": [
                    "gps", "imu", "barometric", "magnetometer", "visual_slam",
                    "wifi_csi", "cellular", "uwb", "acoustic_ranging",
                ],
                "optional_agents": ["lidar", "leo_pnt"],
                "communication": ["LoRa_mesh", "WiFi", "4G/5G", "Satcom"],
                "power_budget_w": 150,
                "emp_hardening": "Partial Faraday cage - critical components",
                "protection_level": "MIL-STD-461G compliance recommended",
                "mil_std_compliance": "MIL-STD-461G (conducted and radiated)",
                "antenna_protection": "PIN diode limiters on all RF inputs",
                "notes": "Balance between protection and operational capability",
            },
            UAVGroup.GROUP_4: {
                "weight_range": "150-600kg",
                "description": "Large UAV - substantial payload",
                "recommended_agents": [
                    "gps_crpa", "dual_imu", "barometric", "magnetometer",
                    "visual_slam", "wifi_csi", "cellular_mimo", "uwb",
                    "acoustic_ranging", "lidar",
                ],
                "optional_agents": ["leo_pnt", "quantum_timing"],
                "communication": ["LoRa_mesh", "WiFi", "4G/5G", "Satcom", "Directional"],
                "power_budget_w": 500,
                "emp_hardening": "Full Faraday cage with filtered penetrations",
                "protection_level": "MIL-STD-461G + MIL-STD-464 compliance",
                "mil_std_compliance": "Full MIL-STD-461G and MIL-STD-464",
                "antenna_protection": "CRPA + PIN limiters + HPM protection",
                "redundancy": "Dual processors in separate shielded compartments",
                "notes": "Military-grade EMP protection",
            },
            UAVGroup.GROUP_5: {
                "weight_range": ">600kg",
                "description": "Heavy UAV - maximum capability",
                "recommended_agents": "ALL_AVAILABLE",
                "optional_agents": [],
                "communication": ["Full spectrum capability"],
                "power_budget_w": 2000,
                "emp_hardening": "Maximum protection - nested Faraday cages",
                "protection_level": "MIL-STD-461G + MIL-STD-464 + custom HPM shields",
                "mil_std_compliance": "Full military standards + enhanced protection",
                "antenna_protection": "Multi-layer: CRPA + limiters + HPM shields",
                "redundancy": "Triple redundant systems, separated compartments",
                "notes": "Strategic platform - maximum survivability",
            },
        }

    def _init_faraday_spec(self) -> Dict:
        return {
            "shielding_material": {
                "primary": "Aluminum alloy 6061-T6",
                "high_frequency": "Mu-metal for >1GHz threats",
                "thickness_mm": 2.0,
                "conductivity": ">3.5 x 10^7 S/m",
            },
            "attenuation_targets": {
                "minimum_db": 60,
                "frequency_range": "10kHz - 18GHz",
                "test_standard": "MIL-STD-188-125-1",
                "hpm_protection": "Additional 20dB for >1GW/m^2 fields",
            },
            "aperture_treatment": {
                "cable_entries": "Filtered connectors (pi-filter minimum)",
                "antenna_feeds": "Waveguide beyond cutoff + PIN limiters",
                "ventilation": "Honeycomb panels (fc < 500MHz)",
                "access_panels": "Conductive gaskets, spring fingers",
                "seam_treatment": "Welded or bolted with gaskets",
            },
            "antenna_protection": {
                "gps_cellular": "External to shield - protected by PIN limiters",
                "limiter_specification": {
                    "type": "PIN diode limiters",
                    "threshold_dbm": 10,
                    "insertion_loss_db": "<0.5",
                    "recovery_time_ns": "<100",
                    "hpm_rating": "1kW peak, 10W average",
                },
                "crpa_enhancement": "Controlled Reception Pattern Antenna - Group 4+ only",
            },
            "grounding_system": {
                "chassis_ground": "All shielded components bonded to chassis",
                "ground_impedance": "<2.5 milliohms DC",
                "bond_resistance": "<2.5 milliohms between panels",
                "ground_plane": "Continuous under all electronics",
            },
            "protection_layers": {
                "layer_1": "Outer Faraday cage (primary electromagnetic shield)",
                "layer_2": "Filtered power entry (prevent conducted threats)",
                "layer_3": "Component-level protection (TVS diodes, ferrites)",
                "layer_4": "Software countermeasures (fault detection, recovery)",
            },
            "standards_compliance": {
                "primary": "MIL-STD-461G (electromagnetic compatibility)",
                "shielding": "MIL-STD-285 (shielding effectiveness)",
                "hpm": "MIL-STD-464 (high power microwave)",
                "testing": "MIL-STD-188-125-1 (EMP testing)",
            },
        }

    def get_recommended_config(self, uav_group: UAVGroup) -> Dict:
        """Get recommended configuration for specified UAV group."""
        config = self.uav_group_configs[uav_group].copy()

        if uav_group in [UAVGroup.GROUP_3, UAVGroup.GROUP_4, UAVGroup.GROUP_5]:
            config["faraday_requirements"] = self.faraday_shield_spec
        else:
            config["faraday_requirements"] = "Not applicable - size/weight constraints"

        return config

    def get_agent_recommendations(
        self, uav_group: UAVGroup, mission_type: str = "STANDARD"
    ) -> List[str]:
        """Get UPIN agent recommendations for UAV group and mission."""
        config = self.uav_group_configs.get(uav_group, {})

        recommended = config.get("recommended_agents", [])
        if isinstance(recommended, str):
            recommended = []
        optional = config.get("optional_agents", [])

        if mission_type == "EW_CONTESTED":
            priority_agents = [
                a for a in recommended
                if not any(rf in a.lower() for rf in ["wifi", "cellular", "gps"])
            ]
            for a in ["imu", "barometric", "magnetometer", "visual_slam"]:
                if a not in priority_agents:
                    priority_agents.append(a)
            return priority_agents
        elif mission_type == "GPS_DENIED":
            return [a for a in recommended + optional if "gps" not in a.lower()]
        else:
            return list(recommended)

    def get_protection_summary(self, uav_group: UAVGroup) -> Dict:
        config = self.uav_group_configs.get(uav_group, {})

        return {
            "uav_group": uav_group.name,
            "weight_range": config.get("weight_range", "Unknown"),
            "emp_hardening": config.get("emp_hardening", "None"),
            "protection_level": config.get("protection_level", "None"),
            "mil_std_compliance": config.get("mil_std_compliance", "None"),
            "antenna_protection": config.get("antenna_protection", "None"),
            "recommended_agents": len(config.get("recommended_agents", [])),
            "survivability_rating": self._calculate_survivability(uav_group),
        }

    def _calculate_survivability(self, uav_group: UAVGroup) -> str:
        ratings = {
            UAVGroup.GROUP_1: "LOW - distributed swarm resilience only",
            UAVGroup.GROUP_2: "LOW-MEDIUM - basic component protection",
            UAVGroup.GROUP_3: "MEDIUM - partial hardening with critical protection",
            UAVGroup.GROUP_4: "HIGH - full military-grade protection",
            UAVGroup.GROUP_5: "MAXIMUM - strategic-level survivability",
        }
        return ratings.get(uav_group, "UNKNOWN")
