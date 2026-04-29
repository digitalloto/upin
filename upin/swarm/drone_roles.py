"""
Drone Role Specialisation — UPIN Swarm

Different drones in a swarm serve different roles, each with unique
sensor loadouts, UPIN layer configurations, and mission capabilities.

Roles:
- DECOY:    Appear bigger/more important. Lens amplifiers, radar reflectors,
            IR emitters. Draws fire away from real assets. Minimal nav needed.
- SPOTTER:  Eyes of the swarm. Full camera + sensor suite, target designation,
            sensor relay. Needs precise positioning for accurate intel.
- STRIKE:   Primary mission drone. Carries main payload. Full nav for
            precision delivery. Protected by decoys.
- SCOUT:    Light, fast, expendable. Minimum sensors for maximum range.
            Maps ahead for the swarm. Route learning is critical.
- EW:       Electronic Warfare. Jammer detection, false position broadcasting,
            spectrum analysis. Needs RF layers, not visual.
- RELAY:    Mesh communication node. Extends swarm comms range. Needs
            cooperative mesh positioning. Stays at optimal relay points.
- CASEVAC:  Medical evacuation. Priority routing, hospital waypoints.
            Needs CASEVAC flight planning integration.
- CARGO:    Heavy payload transport. Conservative nav, stable flight.
            Terrain following for low-altitude delivery.

Each role auto-selects the right UPIN layer preset, equipment loadout,
and mission parameters. Drones can switch roles dynamically.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


class DroneRole(Enum):
    """Available drone roles in a swarm."""
    DECOY = "decoy"
    SPOTTER = "spotter"
    STRIKE = "strike"
    SCOUT = "scout"
    EW = "ew"               # Electronic Warfare
    RELAY = "relay"          # Mesh communication relay
    CASEVAC = "casevac"      # Medical evacuation
    CARGO = "cargo"          # Heavy payload transport


@dataclass
class Equipment:
    """Physical equipment a drone carries for its role."""
    name: str
    weight_g: float
    power_draw_w: float
    description: str


@dataclass
class RoleProfile:
    """Complete profile for a drone role."""
    role: DroneRole
    display_name: str
    description: str
    # UPIN layer IDs this role needs active
    required_layers: List[str]
    # Optional layers (nice to have, drop if power/weight limited)
    optional_layers: List[str]
    # Equipment loadout
    equipment: List[Equipment]
    # Mission parameters
    max_speed_ms: float = 30.0
    max_altitude_m: float = 500.0
    min_altitude_m: float = 5.0
    endurance_minutes: float = 30.0
    expendable: bool = False
    # Signature management
    signature_amplify: bool = False    # decoys amplify their signature
    signature_minimise: bool = False   # stealth minimises signature
    emissions_allowed: bool = True
    # Priority (higher = more protected by swarm)
    protection_priority: int = 5       # 1=expendable, 10=must protect


# ═══════════════════════════════════════════════════════════════
# DECOY EQUIPMENT
# ═══════════════════════════════════════════════════════════════

DECOY_EQUIPMENT = [
    Equipment("radar_reflector", 50, 0,
              "Corner reflector array — amplifies radar cross-section 10×"),
    Equipment("ir_emitter", 30, 5,
              "IR heat source — mimics larger engine thermal signature"),
    Equipment("rf_transponder", 20, 3,
              "Active transponder — responds to IFF queries as 'large aircraft'"),
    Equipment("lens_magnifier", 40, 0,
              "Fresnel lens array — makes drone appear 5× larger to cameras"),
    Equipment("chaff_dispenser", 80, 1,
              "Chaff/flare cartridges — draws radar/IR guided threats"),
    Equipment("acoustic_emitter", 25, 4,
              "Speaker — plays engine noise of larger aircraft"),
]

SPOTTER_EQUIPMENT = [
    Equipment("eo_camera_4k", 120, 8,
              "Electro-optical 4K camera with 30× zoom"),
    Equipment("ir_camera", 90, 6,
              "Thermal IR imager — NETD < 40mK"),
    Equipment("laser_rangefinder", 60, 4,
              "Eye-safe 1550nm rangefinder — 5km range, ±1m accuracy"),
    Equipment("target_designator", 45, 5,
              "Laser target designation — NATO STANAG 3733"),
    Equipment("video_downlink", 30, 3,
              "Encrypted real-time video feed to ground station"),
    Equipment("multi_spectral", 150, 10,
              "Multi-spectral sensor — visible + NIR + SWIR"),
]

STRIKE_EQUIPMENT = [
    Equipment("payload_bay", 500, 0,
              "Precision payload delivery mechanism"),
    Equipment("terminal_guidance", 80, 6,
              "Terminal guidance sensor suite — final approach corrections"),
    Equipment("eo_camera_hd", 80, 5,
              "HD camera for target verification before release"),
    Equipment("encrypted_datalink", 30, 3,
              "C2 datalink for human-in-the-loop authorization"),
]

SCOUT_EQUIPMENT = [
    Equipment("wide_angle_camera", 30, 3,
              "150° wide-angle camera — maximum situational awareness"),
    Equipment("lidar_mini", 60, 5,
              "Miniature LiDAR — 50m range obstacle detection"),
    Equipment("mesh_radio", 15, 2,
              "Low-power mesh radio — relay findings to swarm"),
]

EW_EQUIPMENT = [
    Equipment("spectrum_analyser", 100, 8,
              "Wideband spectrum analyser — 30MHz to 6GHz"),
    Equipment("jammer_module", 150, 20,
              "Directional RF jammer — GPS/comms denial for targets"),
    Equipment("false_position_tx", 80, 12,
              "GPS spoofing transmitter — broadcasts false position"),
    Equipment("sigint_receiver", 70, 6,
              "SIGINT receiver — intercepts/locates enemy comms"),
    Equipment("elint_antenna", 60, 5,
              "ELINT antenna array — characterises enemy radar emissions"),
]

RELAY_EQUIPMENT = [
    Equipment("mesh_relay_radio", 40, 8,
              "High-power mesh relay — extends swarm comms 10km"),
    Equipment("directional_antenna", 30, 3,
              "Steerable directional antenna — focused comms link"),
    Equipment("crypto_processor", 20, 2,
              "Onboard encryption for secure relay"),
]

CASEVAC_EQUIPMENT = [
    Equipment("medical_pod", 300, 0,
              "Casualty stabilisation pod — temp control, O2 supply"),
    Equipment("medical_beacon", 20, 2,
              "IFF medical beacon — protected under Geneva Convention"),
    Equipment("auto_landing", 50, 4,
              "Precision auto-landing system for confined LZ"),
]

CARGO_EQUIPMENT = [
    Equipment("cargo_bay", 2000, 0,
              "External cargo hook + internal bay — max 5kg payload"),
    Equipment("terrain_radar", 80, 6,
              "Terrain-following radar — safe low-altitude delivery"),
    Equipment("auto_release", 40, 2,
              "GPS-triggered automatic cargo release"),
]


# ═══════════════════════════════════════════════════════════════
# ROLE PROFILES — layers + equipment + parameters
# ═══════════════════════════════════════════════════════════════

ROLE_PROFILES: Dict[DroneRole, RoleProfile] = {

    DroneRole.DECOY: RoleProfile(
        role=DroneRole.DECOY,
        display_name="Decoy",
        description="Draws enemy attention. Appears bigger and more important.",
        required_layers=[
            "gps_l1", "ins_l3", "baro_l11",
        ],
        optional_layers=[
            "magano_l6", "opticflow_l43",
        ],
        equipment=DECOY_EQUIPMENT,
        max_speed_ms=40.0,
        max_altitude_m=1000.0,
        endurance_minutes=15,
        expendable=True,
        signature_amplify=True,
        protection_priority=1,
    ),

    DroneRole.SPOTTER: RoleProfile(
        role=DroneRole.SPOTTER,
        display_name="Spotter",
        description="Forward observer. Full camera + sensor suite for intel.",
        required_layers=[
            "gps_l1", "navic_l2", "ins_l3", "baro_l11",
            "vslam_l31", "vio_l32", "magano_l6",
            "thermal_l38", "eagleeye_e13", "terrainfp_k07",
        ],
        optional_layers=[
            "hyperspec_l39", "lidar_l33", "opticflow_l43",
            "doppler_l12", "dted_e15",
        ],
        equipment=SPOTTER_EQUIPMENT,
        max_speed_ms=25.0,
        max_altitude_m=500.0,
        endurance_minutes=45,
        expendable=False,
        signature_minimise=True,
        protection_priority=8,
    ),

    DroneRole.STRIKE: RoleProfile(
        role=DroneRole.STRIKE,
        display_name="Strike",
        description="Primary mission. Precision payload delivery.",
        required_layers=[
            "gps_l1", "navic_l2", "ins_l3", "baro_l11",
            "vslam_l31", "magano_l6", "doppler_l12",
            "radaralt_b09", "dted_e15", "eagleeye_e13",
            "rfanomaly_l16", "terrainfp_k07",
        ],
        optional_layers=[
            "vio_l32", "terrain_l5", "laserdop_l18",
            "opticflow_l43", "startrack_l4",
        ],
        equipment=STRIKE_EQUIPMENT,
        max_speed_ms=35.0,
        max_altitude_m=3000.0,
        endurance_minutes=60,
        expendable=False,
        protection_priority=10,
    ),

    DroneRole.SCOUT: RoleProfile(
        role=DroneRole.SCOUT,
        display_name="Scout",
        description="Light and fast. Maps ahead for the swarm.",
        required_layers=[
            "gps_l1", "ins_l3", "baro_l11", "magano_l6",
            "opticflow_l43", "vslam_l31",
        ],
        optional_layers=[
            "wifi_l8", "celltower_l9", "rfanomaly_l16",
        ],
        equipment=SCOUT_EQUIPMENT,
        max_speed_ms=50.0,
        max_altitude_m=300.0,
        endurance_minutes=20,
        expendable=True,
        signature_minimise=True,
        protection_priority=2,
    ),

    DroneRole.EW: RoleProfile(
        role=DroneRole.EW,
        display_name="Electronic Warfare",
        description="Jammer detection, false position, spectrum analysis.",
        required_layers=[
            "gps_l1", "ins_l3", "baro_l11", "magano_l6",
            "rfanomaly_l16", "wifi_l8", "celltower_l9",
            "groundrf_l7", "soop_l42",
        ],
        optional_layers=[
            "eloran_l41", "lora_d07", "uwb_d06",
            "ionosphere_l49", "schumann_l59",
        ],
        equipment=EW_EQUIPMENT,
        max_speed_ms=25.0,
        max_altitude_m=500.0,
        endurance_minutes=40,
        expendable=False,
        emissions_allowed=True,
        protection_priority=7,
    ),

    DroneRole.RELAY: RoleProfile(
        role=DroneRole.RELAY,
        display_name="Mesh Relay",
        description="Communication relay. Extends swarm range.",
        required_layers=[
            "gps_l1", "ins_l3", "baro_l11", "magano_l6",
            "swarmrel_l15",
        ],
        optional_layers=[
            "opticflow_l43", "vslam_l31",
        ],
        equipment=RELAY_EQUIPMENT,
        max_speed_ms=20.0,
        max_altitude_m=1000.0,
        endurance_minutes=90,
        expendable=False,
        protection_priority=6,
    ),

    DroneRole.CASEVAC: RoleProfile(
        role=DroneRole.CASEVAC,
        display_name="CASEVAC",
        description="Medical evacuation. Protected under Geneva Convention.",
        required_layers=[
            "gps_l1", "navic_l2", "ins_l3", "baro_l11",
            "magano_l6", "vslam_l31", "radaralt_b09",
            "beacon_l20", "dted_e15",
        ],
        optional_layers=[
            "doppler_l12", "opticflow_l43", "terrain_l5",
        ],
        equipment=CASEVAC_EQUIPMENT,
        max_speed_ms=30.0,
        max_altitude_m=500.0,
        endurance_minutes=45,
        expendable=False,
        emissions_allowed=True,
        protection_priority=9,
    ),

    DroneRole.CARGO: RoleProfile(
        role=DroneRole.CARGO,
        display_name="Cargo",
        description="Heavy payload transport. Low and slow.",
        required_layers=[
            "gps_l1", "navic_l2", "ins_l3", "baro_l11",
            "magano_l6", "radaralt_b09", "terrain_l5",
            "dted_e15",
        ],
        optional_layers=[
            "vslam_l31", "doppler_l12", "opticflow_l43",
        ],
        equipment=CARGO_EQUIPMENT,
        max_speed_ms=20.0,
        max_altitude_m=200.0,
        min_altitude_m=10.0,
        endurance_minutes=30,
        expendable=False,
        protection_priority=4,
    ),
}


# ═══════════════════════════════════════════════════════════════
# DRONE INSTANCE — A specific drone with assigned role
# ═══════════════════════════════════════════════════════════════

@dataclass
class DroneInstance:
    """A specific drone in the swarm with an assigned role."""
    drone_id: str
    callsign: str
    role: DroneRole
    profile: RoleProfile
    active_layers: List[str] = field(default_factory=list)
    current_lat: float = 0.0
    current_lon: float = 0.0
    current_alt: float = 0.0
    battery_pct: float = 100.0
    status: str = "ready"  # ready, airborne, rtb, lost, destroyed

    def total_equipment_weight_g(self) -> float:
        return sum(e.weight_g for e in self.profile.equipment)

    def total_power_draw_w(self) -> float:
        return sum(e.power_draw_w for e in self.profile.equipment)


class SwarmRoleManager:
    """Manages role assignment and specialisation for a drone swarm.

    Assigns roles based on mission requirements, manages dynamic
    role switching, and ensures the swarm has the right mix of
    capabilities for the current situation.
    """

    def __init__(self):
        self._drones: Dict[str, DroneInstance] = {}

    def add_drone(self, drone_id: str, callsign: str,
                  role: DroneRole) -> DroneInstance:
        """Add a drone to the swarm with a specific role."""
        profile = ROLE_PROFILES[role]
        drone = DroneInstance(
            drone_id=drone_id,
            callsign=callsign,
            role=role,
            profile=profile,
            active_layers=list(profile.required_layers),
        )
        self._drones[drone_id] = drone
        return drone

    def switch_role(self, drone_id: str, new_role: DroneRole) -> bool:
        """Dynamically switch a drone's role mid-mission."""
        if drone_id not in self._drones:
            return False
        drone = self._drones[drone_id]
        profile = ROLE_PROFILES[new_role]
        drone.role = new_role
        drone.profile = profile
        drone.active_layers = list(profile.required_layers)
        return True

    def get_drone(self, drone_id: str) -> Optional[DroneInstance]:
        return self._drones.get(drone_id)

    def get_by_role(self, role: DroneRole) -> List[DroneInstance]:
        return [d for d in self._drones.values() if d.role == role]

    def assign_swarm_formation(self, mission_type: str) -> Dict[str, List[str]]:
        """Auto-assign a balanced formation for a mission type.

        Returns dict of role -> list of drone_ids.
        """
        formations = {
            "reconnaissance": {
                DroneRole.SPOTTER: 0.4,
                DroneRole.SCOUT: 0.3,
                DroneRole.RELAY: 0.1,
                DroneRole.DECOY: 0.2,
            },
            "strike": {
                DroneRole.STRIKE: 0.2,
                DroneRole.SPOTTER: 0.2,
                DroneRole.DECOY: 0.3,
                DroneRole.EW: 0.15,
                DroneRole.RELAY: 0.15,
            },
            "escort": {
                DroneRole.SCOUT: 0.3,
                DroneRole.DECOY: 0.3,
                DroneRole.EW: 0.2,
                DroneRole.RELAY: 0.2,
            },
            "resupply": {
                DroneRole.CARGO: 0.4,
                DroneRole.SCOUT: 0.2,
                DroneRole.DECOY: 0.2,
                DroneRole.RELAY: 0.2,
            },
            "casevac": {
                DroneRole.CASEVAC: 0.3,
                DroneRole.SCOUT: 0.2,
                DroneRole.DECOY: 0.2,
                DroneRole.EW: 0.15,
                DroneRole.RELAY: 0.15,
            },
        }
        ratios = formations.get(mission_type, formations["reconnaissance"])
        all_drones = list(self._drones.values())
        result: Dict[str, List[str]] = {}
        idx = 0
        for role, fraction in ratios.items():
            count = max(1, int(len(all_drones) * fraction))
            assigned = []
            for _ in range(count):
                if idx < len(all_drones):
                    self.switch_role(all_drones[idx].drone_id, role)
                    assigned.append(all_drones[idx].drone_id)
                    idx += 1
            result[role.value] = assigned
        return result

    def get_swarm_summary(self) -> Dict:
        roles_count: Dict[str, int] = {}
        for d in self._drones.values():
            roles_count[d.role.value] = roles_count.get(d.role.value, 0) + 1
        total_weight = sum(d.total_equipment_weight_g()
                           for d in self._drones.values())
        total_power = sum(d.total_power_draw_w()
                          for d in self._drones.values())
        return {
            "total_drones": len(self._drones),
            "roles": roles_count,
            "total_equipment_weight_g": total_weight,
            "total_power_draw_w": total_power,
            "expendable": sum(1 for d in self._drones.values()
                              if d.profile.expendable),
            "protected": sum(1 for d in self._drones.values()
                             if d.profile.protection_priority >= 7),
        }
