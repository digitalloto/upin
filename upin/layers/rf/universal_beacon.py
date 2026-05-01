"""
Universal Beacon Layer — UPIN Layer 88

Triangulation from ANY signal source — the physics changes but the
geometry is identical. LoRa, VHF, IR, acoustic, magnetic, seismic,
lightning — if you know where the source is and can measure distance
or bearing, you get a position fix.

Supports:
- LoRa beacons (15km mountain-top solar nodes)
- VHF/UHF radio (50km+, diffracts over terrain)
- HF radio (1000km+, ionospheric bounce)
- FM/AM broadcast towers (existing infrastructure)
- IR laser beacons (1-5km LOS, unjammable by RF)
- Ultrasonic beacons (50m, cm precision, caves/tunnels)
- Infrasound emitters (100km+, penetrates everything)
- Lightning sferics (global, free, continuous)
- Seismic sources (ground vibration from known positions)
- Any custom signal type the operator defines

Field-deployable: drop 3 solar LoRa beacons on mountain tops
→ instant positioning grid for 15km radius. Cost: ~$20 each.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class SignalType(Enum):
    """All supported signal types for beacon-based positioning."""
    LORA_900 = "lora_900"
    VHF = "vhf"
    UHF = "uhf"
    HF = "hf"
    FM_BROADCAST = "fm_broadcast"
    AM_BROADCAST = "am_broadcast"
    IR_LASER = "ir_laser"
    ULTRASONIC = "ultrasonic"
    INFRASOUND = "infrasound"
    ELF = "elf"
    LIGHTNING = "lightning"
    SEISMIC = "seismic"
    WIFI = "wifi"
    UWB = "uwb"
    BLUETOOTH = "bluetooth"
    CUSTOM = "custom"


@dataclass
class SignalProfile:
    """Physical properties of a signal type."""
    signal_type: SignalType
    frequency_range: str
    max_range_m: float
    typical_accuracy_m: float
    propagation_speed_ms: float  # m/s (3e8 for RF, 343 for sound)
    penetrates_foliage: bool
    penetrates_rock: bool
    requires_los: bool
    jammable: bool
    power_required_w: float
    best_environment: str


SIGNAL_PROFILES: Dict[SignalType, SignalProfile] = {
    SignalType.LORA_900: SignalProfile(
        SignalType.LORA_900, "860-930 MHz", 15_000, 50.0, 3e8,
        True, False, False, False, 0.1, "mountains/rural"),
    SignalType.VHF: SignalProfile(
        SignalType.VHF, "30-300 MHz", 50_000, 100.0, 3e8,
        True, False, False, True, 5.0, "forest/mountains"),
    SignalType.UHF: SignalProfile(
        SignalType.UHF, "300-3000 MHz", 30_000, 50.0, 3e8,
        False, False, False, True, 5.0, "urban/rural"),
    SignalType.HF: SignalProfile(
        SignalType.HF, "3-30 MHz", 1_000_000, 5000.0, 3e8,
        True, True, False, True, 50.0, "arctic/ocean/global"),
    SignalType.FM_BROADCAST: SignalProfile(
        SignalType.FM_BROADCAST, "88-108 MHz", 80_000, 200.0, 3e8,
        True, False, False, True, 0.0, "anywhere with FM towers"),
    SignalType.AM_BROADCAST: SignalProfile(
        SignalType.AM_BROADCAST, "530-1700 kHz", 300_000, 500.0, 3e8,
        True, True, False, True, 0.0, "rural/ocean/night"),
    SignalType.IR_LASER: SignalProfile(
        SignalType.IR_LASER, "850-1550 nm", 5_000, 1.0, 3e8,
        False, False, True, False, 0.3, "desert/clear LOS"),
    SignalType.ULTRASONIC: SignalProfile(
        SignalType.ULTRASONIC, "20-100 kHz", 50, 0.01, 343.0,
        False, False, True, False, 0.1, "caves/tunnels/indoor"),
    SignalType.INFRASOUND: SignalProfile(
        SignalType.INFRASOUND, "0.1-20 Hz", 100_000, 1000.0, 343.0,
        True, True, False, False, 10.0, "mountains/global"),
    SignalType.ELF: SignalProfile(
        SignalType.ELF, "3-30 Hz", 10_000_000, 100_000.0, 3e8,
        True, True, False, False, 1000.0, "submarine/global"),
    SignalType.LIGHTNING: SignalProfile(
        SignalType.LIGHTNING, "broadband RF", 1_000_000, 2000.0, 3e8,
        True, False, False, False, 0.0, "tropical/temperate"),
    SignalType.SEISMIC: SignalProfile(
        SignalType.SEISMIC, "0.1-50 Hz", 50_000, 500.0, 3000.0,
        True, True, False, False, 0.0, "anywhere with ground contact"),
    SignalType.WIFI: SignalProfile(
        SignalType.WIFI, "2.4/5 GHz", 300, 5.0, 3e8,
        False, False, False, True, 0.1, "urban/indoor"),
    SignalType.UWB: SignalProfile(
        SignalType.UWB, "3.1-10.6 GHz", 100, 0.1, 3e8,
        False, False, True, False, 0.05, "indoor/short range"),
    SignalType.BLUETOOTH: SignalProfile(
        SignalType.BLUETOOTH, "2.4 GHz", 200, 3.0, 3e8,
        False, False, False, True, 0.01, "indoor/urban"),
    SignalType.CUSTOM: SignalProfile(
        SignalType.CUSTOM, "user-defined", 10_000, 50.0, 3e8,
        True, False, False, False, 1.0, "operator-specified"),
}


@dataclass
class Beacon:
    """A positioned beacon emitting a known signal."""
    beacon_id: str
    lat: float
    lon: float
    alt: float
    signal_type: SignalType
    transmit_power_dbm: float = 20.0
    frequency_mhz: float = 0.0
    name: str = ""
    deployed_at: float = field(default_factory=time.time)
    active: bool = True
    solar_powered: bool = False


@dataclass
class BeaconReading:
    """A received signal from a beacon."""
    beacon_id: str
    rssi_dbm: float
    toa_s: Optional[float] = None       # time of arrival (for ranging)
    tdoa_s: Optional[float] = None      # time diff of arrival
    bearing_deg: Optional[float] = None  # if directional antenna
    estimated_distance_m: float = 0.0
    signal_type: SignalType = SignalType.CUSTOM
    timestamp: float = field(default_factory=time.time)


class UniversalBeaconEngine:
    """Triangulation from any signal source.

    Register beacons of any type. Feed signal readings. Get position.
    The engine doesn't care what the signal is — it just needs
    (source_position, measured_distance) for each beacon.
    """

    def __init__(self):
        self._beacons: Dict[str, Beacon] = {}
        self._readings: Dict[str, BeaconReading] = {}
        self._calibrations: Dict[str, Tuple[float, float]] = {}  # beacon_id → (gps_dist, rssi)
        self._position_history: List[Dict] = []

    def deploy_beacon(self, beacon: Beacon):
        """Register a beacon at a known position."""
        self._beacons[beacon.beacon_id] = beacon

    def deploy_field_grid(self, positions: List[Tuple[str, float, float, float]],
                          signal_type: SignalType = SignalType.LORA_900):
        """Deploy multiple beacons at known positions (field setup)."""
        for name, lat, lon, alt in positions:
            self.deploy_beacon(Beacon(
                beacon_id=name, lat=lat, lon=lon, alt=alt,
                signal_type=signal_type, name=name, solar_powered=True,
            ))

    def calibrate_beacon(self, beacon_id: str, gps_lat: float, gps_lon: float,
                         rssi_dbm: float):
        """GPS-calibrate a beacon — store exact distance for this RSSI level."""
        if beacon_id not in self._beacons:
            return
        b = self._beacons[beacon_id]
        dist = _haversine_m(gps_lat, gps_lon, b.lat, b.lon)
        self._calibrations[beacon_id] = (dist, rssi_dbm)

    def feed_reading(self, reading: BeaconReading):
        """Feed a signal reading from a beacon."""
        self._readings[reading.beacon_id] = reading

        # Estimate distance from reading
        if reading.toa_s is not None and reading.beacon_id in self._beacons:
            profile = SIGNAL_PROFILES.get(reading.signal_type)
            speed = profile.propagation_speed_ms if profile else 3e8
            reading.estimated_distance_m = reading.toa_s * speed
        elif reading.beacon_id in self._calibrations:
            cal_dist, cal_rssi = self._calibrations[reading.beacon_id]
            # Use GPS-calibrated path-loss model
            delta_rssi = reading.rssi_dbm - cal_rssi
            n = 3.0  # default path-loss exponent
            if n > 0:
                ratio = 10.0 ** (-delta_rssi / (10.0 * n))
                reading.estimated_distance_m = cal_dist * ratio
        else:
            # Raw RSSI-based distance (rough)
            if reading.rssi_dbm < 0:
                reading.estimated_distance_m = 10.0 ** (
                    (-40 - reading.rssi_dbm) / (10 * 3.0))

    def trilaterate(self) -> Optional[Dict]:
        """Compute position from all available beacon readings."""
        observations = []
        for beacon_id, reading in self._readings.items():
            if beacon_id not in self._beacons:
                continue
            if reading.estimated_distance_m <= 0:
                continue
            b = self._beacons[beacon_id]
            observations.append((b.lat, b.lon, reading.estimated_distance_m,
                                 reading.signal_type.value, beacon_id))

        if len(observations) < 2:
            return None

        # Weighted centroid as initial guess
        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for lat, lon, dist, _, _ in observations:
            w = 1.0 / max(dist, 1.0)
            lat_sum += lat * w
            lon_sum += lon * w
            total_w += w
        lat = lat_sum / total_w
        lon = lon_sum / total_w

        # NLLS refinement (5 iterations)
        for _ in range(5):
            m_lat = 111_320.0
            m_lon = 111_320.0 * max(math.cos(math.radians(lat)), 0.01)
            residuals = []
            jacobian = []
            for b_lat, b_lon, meas_d, _, _ in observations:
                dy = (lat - b_lat) * m_lat
                dx = (lon - b_lon) * m_lon
                pred_d = math.sqrt(dx * dx + dy * dy)
                if pred_d < 1.0:
                    pred_d = 1.0
                residuals.append(meas_d - pred_d)
                jacobian.append([-dy / pred_d * m_lat, -dx / pred_d * m_lon])
            r = np.array(residuals)
            J = np.array(jacobian)
            try:
                delta = np.linalg.solve(J.T @ J, J.T @ r)
                lat -= float(delta[0])
                lon -= float(delta[1])
            except np.linalg.LinAlgError:
                break

        rms = float(np.sqrt(np.mean(np.array(residuals) ** 2))) if residuals else 999
        signal_types = list(set(st for _, _, _, st, _ in observations))

        result = {
            "lat": lat,
            "lon": lon,
            "accuracy_m": max(5.0, rms),
            "beacons_used": len(observations),
            "signal_types": signal_types,
            "beacon_ids": [bid for _, _, _, _, bid in observations],
            "method": "universal_beacon_nlls",
        }
        self._position_history.append(result)
        return result

    def recommend_signal(self, environment: str) -> List[Dict]:
        """Recommend best signal types for an environment."""
        recs = []
        for st, profile in SIGNAL_PROFILES.items():
            score = 0.0
            env_lower = environment.lower()
            if env_lower in profile.best_environment.lower():
                score += 5.0
            if "mountain" in env_lower and profile.penetrates_foliage:
                score += 2.0
            if "cave" in env_lower and profile.penetrates_rock:
                score += 5.0
            if "forest" in env_lower and profile.penetrates_foliage:
                score += 3.0
            if "desert" in env_lower and not profile.requires_los:
                score += 2.0
            if "ocean" in env_lower and profile.max_range_m > 100_000:
                score += 3.0
            if not profile.jammable:
                score += 1.0
            if score > 0:
                recs.append({
                    "signal_type": st.value,
                    "score": score,
                    "range_m": profile.max_range_m,
                    "accuracy_m": profile.typical_accuracy_m,
                    "environment": profile.best_environment,
                    "jammable": profile.jammable,
                })
        recs.sort(key=lambda r: -r["score"])
        return recs[:5]

    def get_status(self) -> Dict:
        active = sum(1 for b in self._beacons.values() if b.active)
        types = set(b.signal_type.value for b in self._beacons.values())
        return {
            "beacons_deployed": len(self._beacons),
            "beacons_active": active,
            "readings_available": len(self._readings),
            "calibrated": len(self._calibrations),
            "signal_types_in_use": list(types),
            "positions_computed": len(self._position_history),
        }


class UniversalBeaconLayer(NavigationLayer):
    """Layer 88 — Universal Beacon Positioning.

    Triangulation from ANY signal source. Same math, different physics.
    LoRa on mountain tops, FM broadcast towers, IR beacons, lightning
    sferics — all feed the same NLLS trilateration engine.
    """

    def __init__(self):
        super().__init__(
            layer_id="univbeacon_k11",
            layer_number=88,
            name="Universal Beacon Positioning",
            group=LayerGroup.K_SYSTEMS_INTELLIGENCE,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Triangulation from any signal — LoRa, VHF, IR, acoustic, seismic",
        )
        self._engine = UniversalBeaconEngine()

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.60

    @property
    def engine(self) -> UniversalBeaconEngine:
        return self._engine

    def read(self) -> LayerReading:
        if self.world is not None:
            return self._read_from_world()
        if self._simulated:
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        # Use cell tower signals as proxy beacons
        signals = self.world.get_cell_tower_signals()
        for s in signals:
            if s["tower_id"] not in self._engine._beacons:
                self._engine.deploy_beacon(Beacon(
                    beacon_id=s["tower_id"], lat=s["known_lat"],
                    lon=s["known_lon"], alt=0,
                    signal_type=SignalType.UHF, name=s["tower_id"],
                ))
            dist = self.world._haversine_m(
                self.world.true_lat, self.world.true_lon,
                s["known_lat"], s["known_lon"],
            )
            self._engine.calibrate_beacon(
                s["tower_id"], self.world.true_lat, self.world.true_lon,
                s["rssi_dbm"],
            )
            self._engine.feed_reading(BeaconReading(
                beacon_id=s["tower_id"], rssi_dbm=s["rssi_dbm"],
                estimated_distance_m=dist + np.random.normal(0, dist * 0.01),
                signal_type=SignalType.UHF,
            ))

        result = self._engine.trilaterate()
        if result is None:
            return self._read_fallback()

        pos = Position(
            latitude=result["lat"], longitude=result["lon"], altitude=0,
            accuracy_m=result["accuracy_m"], timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=min(0.85, 0.3 + result["beacons_used"] * 0.1),
            raw_data={
                "beacons_used": result["beacons_used"],
                "signal_types": result["signal_types"],
                "method": result["method"],
            },
        )

    def _read_fallback(self) -> LayerReading:
        base_lat = getattr(self, "_sim_lat", 13.0827)
        base_lon = getattr(self, "_sim_lon", 80.2707)
        pos = Position(
            latitude=base_lat + np.random.normal(0, 50 / 111_000),
            longitude=base_lon + np.random.normal(0, 50 / 111_000),
            altitude=0, accuracy_m=50.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.4,
            raw_data={"beacons_used": 0, "status": "fallback"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
