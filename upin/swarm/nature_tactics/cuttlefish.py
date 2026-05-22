"""
Cuttlefish Camouflage — UPIN Swarm

Dynamic signature morphing for decoy drones. Cuttlefish change their
colour, pattern, and texture in milliseconds to mimic anything —
a rock, a piece of coral, a different species entirely.

Applied to drones: decoy drones dynamically change their radar cross
section, infrared signature, and visual appearance to mimic different
aircraft types. The enemy can't tell which is the real strike drone
and which is a $50 decoy pretending to be an F-35.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class SignatureType:
    RADAR = "radar"
    INFRARED = "infrared"
    VISUAL = "visual"
    ACOUSTIC = "acoustic"
    RF_EMISSION = "rf_emission"


@dataclass
class AircraftSignatureProfile:
    """The signature profile of an aircraft type to mimic."""
    aircraft_type: str
    rcs_m2: float              # radar cross section in m²
    ir_temperature_k: float    # infrared temperature
    visual_size_m: float       # apparent visual size
    acoustic_db: float         # noise level
    rf_emissions: List[str] = field(default_factory=list)  # transponder types


MIMICRY_PROFILES = {
    "fighter_jet": AircraftSignatureProfile(
        "fighter_jet", rcs_m2=5.0, ir_temperature_k=800,
        visual_size_m=15, acoustic_db=120,
        rf_emissions=["IFF_MODE_4", "TACAN", "RADAR_X"]),
    "heavy_bomber": AircraftSignatureProfile(
        "heavy_bomber", rcs_m2=100.0, ir_temperature_k=600,
        visual_size_m=40, acoustic_db=130,
        rf_emissions=["IFF_MODE_4", "RADAR_S", "SATCOM"]),
    "transport_aircraft": AircraftSignatureProfile(
        "transport_aircraft", rcs_m2=50.0, ir_temperature_k=500,
        visual_size_m=35, acoustic_db=110,
        rf_emissions=["IFF_MODE_3", "TCAS", "ADS_B"]),
    "helicopter": AircraftSignatureProfile(
        "helicopter", rcs_m2=10.0, ir_temperature_k=700,
        visual_size_m=12, acoustic_db=100,
        rf_emissions=["IFF_MODE_3", "TACAN"]),
    "cruise_missile": AircraftSignatureProfile(
        "cruise_missile", rcs_m2=0.1, ir_temperature_k=900,
        visual_size_m=5, acoustic_db=90,
        rf_emissions=["RADAR_ALTIMETER"]),
    "stealth_drone": AircraftSignatureProfile(
        "stealth_drone", rcs_m2=0.001, ir_temperature_k=350,
        visual_size_m=3, acoustic_db=60,
        rf_emissions=[]),
    "civilian_airliner": AircraftSignatureProfile(
        "civilian_airliner", rcs_m2=80.0, ir_temperature_k=450,
        visual_size_m=50, acoustic_db=125,
        rf_emissions=["ADS_B", "TCAS", "IFF_MODE_3"]),
}


@dataclass
class ActiveMimicry:
    """Current mimicry state of a decoy drone."""
    drone_id: str
    mimicking: str  # aircraft_type being mimicked
    profile: AircraftSignatureProfile
    activated_at: float
    # Active signature modifications
    radar_reflector_rcs_m2: float = 0.0
    ir_emitter_temp_k: float = 300.0
    lens_magnification: float = 1.0
    acoustic_playback_db: float = 0.0
    rf_transponder_active: bool = False


class CuttlefishCamouflage:
    """Dynamic signature morphing for decoy drones.

    A $50 decoy drone can mimic a fighter jet's radar cross section
    (corner reflectors), infrared signature (IR emitters), visual size
    (Fresnel lens), and RF emissions (transponder spoofing).

    The enemy wastes missiles on decoys while the real strike drone
    approaches undetected with minimized signatures.
    """

    def __init__(self):
        self._active_mimicry: Dict[str, ActiveMimicry] = {}
        self._morph_count = 0
        self._available_profiles = dict(MIMICRY_PROFILES)

    def start_mimicry(self, drone_id: str, target_type: str) -> Dict:
        """Start mimicking an aircraft type."""
        if target_type not in self._available_profiles:
            return {"error": f"Unknown type: {target_type}",
                    "available": list(self._available_profiles.keys())}

        profile = self._available_profiles[target_type]
        mimicry = ActiveMimicry(
            drone_id=drone_id,
            mimicking=target_type,
            profile=profile,
            activated_at=time.time(),
            radar_reflector_rcs_m2=profile.rcs_m2,
            ir_emitter_temp_k=profile.ir_temperature_k,
            lens_magnification=profile.visual_size_m / 0.5,  # drone is ~0.5m
            acoustic_playback_db=profile.acoustic_db,
            rf_transponder_active=len(profile.rf_emissions) > 0,
        )
        self._active_mimicry[drone_id] = mimicry
        self._morph_count += 1

        return {
            "status": "MIMICRY_ACTIVE",
            "drone_id": drone_id,
            "mimicking": target_type,
            "rcs_m2": profile.rcs_m2,
            "ir_temp_k": profile.ir_temperature_k,
            "visual_magnification": mimicry.lens_magnification,
            "rf_emissions": profile.rf_emissions,
        }

    def morph(self, drone_id: str, new_type: str) -> Dict:
        """Switch mimicry to a different aircraft type mid-flight."""
        if drone_id in self._active_mimicry:
            self.stop_mimicry(drone_id)
        return self.start_mimicry(drone_id, new_type)

    def stop_mimicry(self, drone_id: str):
        """Return to natural (minimal) signature."""
        self._active_mimicry.pop(drone_id, None)

    def randomize_mimicry(self, drone_ids: List[str]) -> List[Dict]:
        """Assign random different profiles to multiple decoys.

        Makes each decoy look like a different aircraft type —
        the enemy sees a mixed formation and can't tell which is real.
        """
        types = list(self._available_profiles.keys())
        results = []
        for did in drone_ids:
            chosen = random.choice(types)
            results.append(self.start_mimicry(did, chosen))
        return results

    def get_enemy_perception(self, drone_id: str) -> Optional[Dict]:
        """What the enemy sees when they detect this drone."""
        m = self._active_mimicry.get(drone_id)
        if not m:
            return {"perceived_as": "small_drone", "rcs_m2": 0.01,
                    "threat_assessment": "LOW"}
        return {
            "perceived_as": m.mimicking,
            "rcs_m2": m.radar_reflector_rcs_m2,
            "ir_signature_k": m.ir_emitter_temp_k,
            "visual_size_m": m.profile.visual_size_m,
            "rf_emissions": m.profile.rf_emissions,
            "threat_assessment": "HIGH" if m.profile.rcs_m2 > 5 else "MEDIUM",
        }

    def get_status(self) -> Dict:
        return {
            "active_mimics": len(self._active_mimicry),
            "total_morphs": self._morph_count,
            "profiles_available": list(self._available_profiles.keys()),
            "active": {did: m.mimicking
                       for did, m in self._active_mimicry.items()},
        }
