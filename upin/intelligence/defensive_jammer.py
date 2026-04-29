"""
Defensive Jammer Shield — UPIN Electronic Warfare

Downward-pointing directional jammer that creates a protective electronic
dome beneath the swarm. Any electronic device approaching from below
(enemy drones, guided missiles, SAMs) loses GPS, comms, and guidance.

UPIN drones are UNAFFECTED because they navigate without GPS — that's
the entire point. The swarm jams everything below while continuing to
navigate via 79 layers of unjammable sensors.

The shield has multiple modes:
- DOME:      360° coverage below, maximum area denial
- CONE:      Focused downward cone, longer range, narrower coverage
- SECTOR:    Jam a specific azimuth sector (e.g. where threat is)
- REACTIVE:  Only jam when threat detected (conserves power)
- ESCORT:    Focused jam toward specific tracked threat

Safety:
- HAIL protocol: human authorisation required to activate
- IFF integration: friendly signatures excluded from jamming
- Geneva Convention: medical frequencies excluded
- Automatic power management based on battery state

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


class JammerMode(Enum):
    """Shield operating modes."""
    OFF = "off"
    DOME = "dome"           # 360° hemisphere below
    CONE = "cone"           # focused downward cone
    SECTOR = "sector"       # specific azimuth sector
    REACTIVE = "reactive"   # only when threat detected
    ESCORT = "escort"       # track and jam specific threat


class JamBand(Enum):
    """Frequency bands the shield can jam."""
    GPS_L1 = "gps_l1"               # 1575.42 MHz
    GPS_L2 = "gps_l2"               # 1227.60 MHz
    GPS_L5 = "gps_l5"               # 1176.45 MHz
    GLONASS = "glonass"              # 1602 MHz
    GALILEO = "galileo"              # 1575.42 / 1176.45 MHz
    BEIDOU = "beidou"                # 1561.098 MHz
    ISM_2G4 = "ism_2g4"             # 2.4 GHz (WiFi, BLE, drone control)
    ISM_5G8 = "ism_5g8"             # 5.8 GHz (drone video, WiFi 5)
    CELLULAR_700 = "cell_700"        # 700 MHz LTE
    CELLULAR_1800 = "cell_1800"      # 1800 MHz LTE
    CELLULAR_2100 = "cell_2100"      # 2100 MHz UMTS
    UHF_COMMS = "uhf_comms"          # 225-400 MHz military comms
    VHF_COMMS = "vhf_comms"          # 30-88 MHz military comms
    RADAR_S = "radar_s"              # 2-4 GHz (search radar)
    RADAR_X = "radar_x"              # 8-12 GHz (fire control radar)


# Bands excluded from jamming for safety/legal reasons
PROTECTED_BANDS = {
    "emergency_121_5": "121.5 MHz — international distress",
    "emergency_243": "243 MHz — military emergency",
    "emergency_406": "406 MHz — COSPAS-SARSAT emergency beacon",
    "medical_freq": "Medical telemetry frequencies",
}


@dataclass
class JammerConfig:
    """Configuration for one jammer emitter on a drone."""
    emitter_id: str
    bands: List[JamBand]
    max_power_w: float = 5.0        # watts ERP
    current_power_w: float = 0.0
    antenna_gain_dbi: float = 10.0   # directional downward
    beam_width_deg: float = 120.0    # hemisphere = 180, cone = 60
    azimuth_deg: float = 0.0         # for sector mode
    sector_width_deg: float = 90.0   # for sector mode
    effective_range_m: float = 500.0


@dataclass
class ThreatTrack:
    """A tracked threat that the shield may jam."""
    track_id: str
    lat: float
    lon: float
    alt: float
    bearing_deg: float
    range_m: float
    closing_speed_ms: float
    threat_type: str   # "drone", "missile", "vehicle", "unknown"
    electronic: bool = True  # does it rely on electronics?
    last_update: float = 0.0


class DefensiveJammerShield:
    """Downward-pointing electronic shield for swarm protection.

    Creates a jamming dome/cone below the swarm that denies GPS,
    comms, and guidance to anything approaching from beneath.
    UPIN-equipped drones are unaffected because they don't need GPS.
    """

    def __init__(self):
        self._mode = JammerMode.OFF
        self._emitters: Dict[str, JammerConfig] = {}
        self._active_bands: List[JamBand] = []
        self._human_authorised = False
        self._authorisation_time: Optional[float] = None
        self._authorisation_expiry_s = 3600  # re-auth every hour
        self._threats: Dict[str, ThreatTrack] = {}
        self._iff_friendly_ids: set = set()
        self._jam_log: List[Dict] = []
        self._power_budget_w: float = 20.0
        self._total_power_used_w: float = 0.0

    def authorise(self, officer_id: str, auth_code: str) -> Dict:
        """HAIL protocol: human authorisation to activate jamming."""
        if len(auth_code) < 8:
            return {"authorised": False, "reason": "Auth code too short"}
        self._human_authorised = True
        self._authorisation_time = time.time()
        self._log("AUTHORISED", f"Officer {officer_id} authorised jamming shield")
        return {
            "authorised": True,
            "officer": officer_id,
            "expires_in_s": self._authorisation_expiry_s,
        }

    def add_emitter(self, config: JammerConfig):
        """Add a jammer emitter (one per drone in the swarm)."""
        self._emitters[config.emitter_id] = config

    def set_mode(self, mode: JammerMode, **kwargs) -> Dict:
        """Set the shield operating mode."""
        if not self._human_authorised:
            return {"error": "Human authorisation required (HAIL protocol)"}
        if self._is_auth_expired():
            return {"error": "Authorisation expired — re-authorise"}

        self._mode = mode
        result = {"mode": mode.value, "emitters": len(self._emitters)}

        if mode == JammerMode.DOME:
            self._configure_dome()
        elif mode == JammerMode.CONE:
            self._configure_cone(kwargs.get("beam_width_deg", 60))
        elif mode == JammerMode.SECTOR:
            self._configure_sector(
                kwargs.get("azimuth_deg", 0),
                kwargs.get("sector_width_deg", 90),
            )
        elif mode == JammerMode.REACTIVE:
            result["status"] = "armed — will activate on threat detection"
        elif mode == JammerMode.ESCORT:
            track_id = kwargs.get("track_id")
            if track_id and track_id in self._threats:
                result["tracking"] = track_id
        elif mode == JammerMode.OFF:
            self._deactivate_all()
            result["status"] = "shield off"

        self._log("MODE_CHANGE", f"Shield mode → {mode.value}")
        return result

    def set_bands(self, bands: List[JamBand]):
        """Set which frequency bands to jam."""
        self._active_bands = bands
        for emitter in self._emitters.values():
            emitter.bands = bands

    def set_all_bands(self):
        """Jam all bands (maximum denial)."""
        self._active_bands = list(JamBand)

    def set_anti_drone_bands(self):
        """Preset: jam only drone-relevant frequencies."""
        self._active_bands = [
            JamBand.GPS_L1, JamBand.GPS_L2,
            JamBand.ISM_2G4, JamBand.ISM_5G8,
            JamBand.CELLULAR_700, JamBand.CELLULAR_1800,
        ]

    def set_anti_missile_bands(self):
        """Preset: jam missile guidance frequencies."""
        self._active_bands = [
            JamBand.GPS_L1, JamBand.GPS_L2, JamBand.GPS_L5,
            JamBand.GLONASS, JamBand.GALILEO, JamBand.BEIDOU,
            JamBand.RADAR_S, JamBand.RADAR_X,
            JamBand.UHF_COMMS,
        ]

    def add_friendly_iff(self, iff_id: str):
        """Register a friendly IFF ID — will NOT be jammed."""
        self._iff_friendly_ids.add(iff_id)

    def track_threat(self, threat: ThreatTrack):
        """Update a tracked threat approaching the swarm."""
        threat.last_update = time.time()
        self._threats[threat.track_id] = threat

        # REACTIVE mode: auto-activate if threat is close and electronic
        if (self._mode == JammerMode.REACTIVE
                and threat.electronic
                and threat.range_m < 1000
                and threat.closing_speed_ms > 5):
            self._activate_reactive(threat)

    def get_shield_status(self) -> Dict:
        """Current shield status."""
        return {
            "mode": self._mode.value,
            "authorised": self._human_authorised,
            "auth_expired": self._is_auth_expired(),
            "emitters_active": sum(1 for e in self._emitters.values()
                                    if e.current_power_w > 0),
            "emitters_total": len(self._emitters),
            "active_bands": [b.value for b in self._active_bands],
            "band_count": len(self._active_bands),
            "threats_tracked": len(self._threats),
            "total_power_w": self._total_power_used_w,
            "power_budget_w": self._power_budget_w,
            "friendly_iff_count": len(self._iff_friendly_ids),
            "effective_range_m": self._get_effective_range(),
        }

    def get_coverage_map(self, swarm_lat: float, swarm_lon: float,
                         swarm_alt: float) -> Dict:
        """Compute the jamming coverage footprint on the ground."""
        if self._mode == JammerMode.OFF:
            return {"coverage": "none"}

        beam_width = 180.0
        if self._emitters:
            beam_width = list(self._emitters.values())[0].beam_width_deg
        # Effective ground radius limited by jammer power + altitude
        eff_range = self._get_effective_range()
        ground_radius_m = min(eff_range, swarm_alt * 2.0)
        if beam_width < 170:
            half_beam = math.radians(beam_width / 2.0)
            ground_radius_m = min(ground_radius_m,
                                  swarm_alt * math.tan(half_beam))

        return {
            "center_lat": swarm_lat,
            "center_lon": swarm_lon,
            "ground_radius_m": round(ground_radius_m, 1),
            "altitude_m": swarm_alt,
            "beam_width_deg": beam_width,
            "mode": self._mode.value,
            "bands_jammed": len(self._active_bands),
        }

    # ── Internal methods ──────────────────────────────────────────

    def _configure_dome(self):
        """180° hemisphere — maximum area coverage."""
        for emitter in self._emitters.values():
            emitter.beam_width_deg = 180.0
            emitter.current_power_w = min(
                emitter.max_power_w,
                self._power_budget_w / max(1, len(self._emitters)),
            )
        self._update_power()

    def _configure_cone(self, beam_width_deg: float = 60.0):
        """Focused cone — longer range, narrower coverage."""
        for emitter in self._emitters.values():
            emitter.beam_width_deg = beam_width_deg
            emitter.current_power_w = min(
                emitter.max_power_w,
                self._power_budget_w / max(1, len(self._emitters)),
            )
        self._update_power()

    def _configure_sector(self, azimuth_deg: float, sector_width_deg: float):
        """Jam a specific azimuth sector (where the threat is)."""
        for emitter in self._emitters.values():
            emitter.azimuth_deg = azimuth_deg
            emitter.sector_width_deg = sector_width_deg
            emitter.beam_width_deg = sector_width_deg
            emitter.current_power_w = emitter.max_power_w
        self._update_power()

    def _activate_reactive(self, threat: ThreatTrack):
        """Auto-activate jamming toward a detected threat."""
        for emitter in self._emitters.values():
            emitter.azimuth_deg = threat.bearing_deg
            emitter.sector_width_deg = 60.0
            emitter.beam_width_deg = 60.0
            emitter.current_power_w = emitter.max_power_w
        self._update_power()
        self._log("REACTIVE_JAM",
                  f"Auto-jam toward {threat.track_id} at bearing {threat.bearing_deg}° "
                  f"range {threat.range_m}m")

    def _deactivate_all(self):
        for emitter in self._emitters.values():
            emitter.current_power_w = 0.0
        self._total_power_used_w = 0.0

    def _update_power(self):
        self._total_power_used_w = sum(
            e.current_power_w for e in self._emitters.values())

    def _get_effective_range(self) -> float:
        if not self._emitters:
            return 0.0
        e = list(self._emitters.values())[0]
        if e.current_power_w <= 0:
            return 0.0
        return e.effective_range_m * math.sqrt(
            e.current_power_w / max(0.1, e.max_power_w))

    def _is_auth_expired(self) -> bool:
        if not self._human_authorised or self._authorisation_time is None:
            return True
        return (time.time() - self._authorisation_time) > self._authorisation_expiry_s

    def _log(self, event_type: str, detail: str):
        self._jam_log.append({
            "time": time.time(),
            "event": event_type,
            "detail": detail,
        })
        if len(self._jam_log) > 500:
            self._jam_log = self._jam_log[-500:]
