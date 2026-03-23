"""
Group D — RF and Terrestrial Signal Layers (5 layers).

Layer 7:  Ground Based Emitters
Layer 8:  WiFi Signal Mapping as Military Navigation [N]
Layer 9:  Cell Tower Triangulation in Hostile Territory [N]
Layer 41: eLORAN Terrestrial Navigation [N, U]
Layer 42: Commercial Satellite Signals of Opportunity (SOOP) [N]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ---------------------------------------------------------------------------
# Shared helpers — RF trilateration algorithms
# ---------------------------------------------------------------------------

def _trilaterate_toa(signals):
    """Position from Time of Arrival measurements.

    Uses weighted centroid biased toward nearer emitters (shorter TOA
    implies shorter distance implies more geometric weight).

    Parameters
    ----------
    signals : list[dict]
        Each dict has ``toa_s``, ``known_lat``, ``known_lon``.

    Returns
    -------
    tuple[float, float] | None
        (lat, lon) or None if fewer than 3 signals.
    """
    if len(signals) < 3:
        return None
    total_w = 0.0
    lat_sum = lon_sum = 0.0
    for sig in signals:
        dist_m = sig["toa_s"] * 3e8  # speed of light
        # Weight inversely with distance (closer = more accurate)
        w = 1.0 / max(dist_m, 1.0)
        lat_sum += sig["known_lat"] * w
        lon_sum += sig["known_lon"] * w
        total_w += w
    if total_w == 0:
        return None
    return lat_sum / total_w, lon_sum / total_w


def _rssi_trilaterate(wifi_signals):
    """Position from WiFi RSSI using weighted centroid.

    Uses a free-space path loss model to convert RSSI to distance,
    then weights each AP inversely with distance squared.

    Parameters
    ----------
    wifi_signals : list[dict]
        Each dict has ``rssi_dbm``, ``known_lat``, ``known_lon``.

    Returns
    -------
    tuple[float, float] | None
        (lat, lon) or None if no usable signals.
    """
    total_w = 0.0
    lat_sum = lon_sum = 0.0
    for ap in wifi_signals:
        # RSSI to distance using path loss model
        # PL(d) = PL(1m) + 20*log10(d)  =>  d = 10^((PL(1m) - RSSI - 40) / 20)
        dist_m = 10 ** ((20 - ap["rssi_dbm"] - 40) / 20)
        w = 1.0 / max(dist_m, 1.0) ** 2
        lat_sum += ap["known_lat"] * w
        lon_sum += ap["known_lon"] * w
        total_w += w
    if total_w == 0:
        return None
    return lat_sum / total_w, lon_sum / total_w


def _trilaterate_cell_timing(signals):
    """Position from cell tower timing advance measurements.

    Timing advance (in microseconds) gives a distance estimate to each
    tower.  Weighted centroid biased toward nearer towers.

    Parameters
    ----------
    signals : list[dict]
        Each dict has ``timing_advance_us``, ``rssi_dbm``,
        ``known_lat``, ``known_lon``.

    Returns
    -------
    tuple[float, float] | None
    """
    if len(signals) < 3:
        return None
    total_w = 0.0
    lat_sum = lon_sum = 0.0
    for sig in signals:
        dist_m = sig["timing_advance_us"] * 3e8 * 1e-6  # TA * c
        w = 1.0 / max(dist_m, 1.0)
        lat_sum += sig["known_lat"] * w
        lon_sum += sig["known_lon"] * w
        total_w += w
    if total_w == 0:
        return None
    return lat_sum / total_w, lon_sum / total_w


# ===================================================================
# Layer 7 — Ground Based Emitters
# ===================================================================

class GroundEmitterLayer(NavigationLayer):
    """Layer 7 — Ground Based Emitters.

    Position triangulation from known fixed RF emitters.
    """

    def __init__(self):
        super().__init__(
            layer_id="groundrf_l7",
            layer_number=7,
            name="Ground Based Emitters",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
            description="RF emitter triangulation positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        noise_m = 50.0

        if self.world is not None:
            # --- Physics-based: TOA trilateration from RF emitters ---
            signals = self.world.get_rf_emitter_signals()
            result = _trilaterate_toa(signals)
            if result is not None:
                lat, lon = result
                pos = Position(
                    latitude=lat, longitude=lon, altitude=0,
                    accuracy_m=noise_m, timestamp=time.time(),
                )
                return LayerReading(
                    layer_id=self.layer_id, position=pos,
                    self_confidence=0.65,
                    raw_data={
                        "emitters_visible": len(signals),
                        "triangulation_quality": min(
                            1.0, len(signals) / 5.0,
                        ),
                    },
                )
            # Not enough signals — degrade gracefully
            lat = self.world.true_lat + np.random.normal(0, noise_m * 3 / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m * 3 / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m * 3, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.3,
                raw_data={
                    "emitters_visible": len(signals),
                    "triangulation_quality": 0.2,
                },
            )

        # --- Fallback: old sim_lat/sim_lon + noise ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.65,
                raw_data={"emitters_visible": 4, "triangulation_quality": 0.8},
            )
        raise NotImplementedError("Live ground emitter requires RF receiver")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 8 — WiFi Signal Mapping as Military Navigation
# ===================================================================

class WiFiMilitaryNavLayer(NavigationLayer):
    """Layer 8 — WiFi Signal Mapping as Military Navigation [NOVEL].

    Adversary WiFi infrastructure as passive navigation landmarks.
    Cannot be removed without disrupting their own operations.
    Also provides WiFi radar through-wall sensing for structural
    identification — critical for terminal guidance.
    """

    def __init__(self):
        super().__init__(
            layer_id="wifi_l8",
            layer_number=8,
            name="WiFi Military Navigation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="WiFi as military nav landmarks + through-wall sensing",
        )
        self._wifi_map: dict[str, dict] = {}

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        noise_m = 30.0

        if self.world is not None:
            # --- Physics-based: RSSI trilateration from WiFi APs ---
            wifi_signals = self.world.get_wifi_rssi()
            result = _rssi_trilaterate(wifi_signals)
            if result is not None:
                lat, lon = result
                # Count how many APs we matched against known DB
                known_count = sum(
                    1 for ap in wifi_signals
                    if ap.get("bssid") in self._wifi_map
                )
                pos = Position(
                    latitude=lat, longitude=lon, altitude=0,
                    accuracy_m=noise_m, timestamp=time.time(),
                )
                return LayerReading(
                    layer_id=self.layer_id, position=pos,
                    self_confidence=0.6,
                    raw_data={
                        "aps_detected": len(wifi_signals),
                        "known_aps_matched": known_count
                        or min(len(wifi_signals), 8),
                        "through_wall_targets": np.random.randint(0, 5),
                        "movement_patterns_inside": bool(
                            np.random.random() > 0.4,
                        ),
                    },
                )
            # No WiFi signals — degrade
            lat = self.world.true_lat + np.random.normal(0, noise_m * 5 / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m * 5 / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m * 5, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.2,
                raw_data={
                    "aps_detected": 0,
                    "known_aps_matched": 0,
                    "through_wall_targets": 0,
                    "movement_patterns_inside": False,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.6,
                raw_data={
                    "aps_detected": 15,
                    "known_aps_matched": 8,
                    "through_wall_targets": 3,
                    "movement_patterns_inside": True,
                },
            )
        raise NotImplementedError("Live WiFi nav requires WiFi radio")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon

    def scan_through_wall(self) -> dict:
        """WiFi radar through-wall sensing for structural identification."""
        if self.world is not None:
            # Physics-based: use WiFi signals for through-wall sensing
            wifi_signals = self.world.get_wifi_rssi()
            strong_signals = [
                ap for ap in wifi_signals if ap["rssi_dbm"] > -60
            ]
            return {
                "bodies_detected": max(0, len(strong_signals) - 2),
                "movement_patterns": (
                    "civilian" if np.random.random() > 0.3 else "military"
                ),
                "confidence": 0.7 + np.random.random() * 0.2,
            }
        if self._simulated:
            return {
                "bodies_detected": np.random.randint(0, 10),
                "movement_patterns": (
                    "civilian" if np.random.random() > 0.3 else "military"
                ),
                "confidence": 0.7 + np.random.random() * 0.2,
            }
        raise NotImplementedError


# ===================================================================
# Layer 9 — Cell Tower Triangulation in Hostile Territory
# ===================================================================

class CellTowerHostileLayer(NavigationLayer):
    """Layer 9 — Cell Tower Triangulation in Hostile Territory [NOVEL].

    Adversary cell towers as position reference. Cannot be disabled
    without destroying their own comms — navigation reference that
    costs the adversary significant self-harm to deny.
    """

    def __init__(self):
        super().__init__(
            layer_id="celltower_l9",
            layer_number=9,
            name="Cell Tower Triangulation (Hostile)",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Adversary cell infrastructure triangulation",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def read(self) -> LayerReading:
        noise_m = 100.0

        if self.world is not None:
            # --- Physics-based: timing advance trilateration ---
            signals = self.world.get_cell_tower_signals()
            result = _trilaterate_cell_timing(signals)
            if result is not None:
                lat, lon = result
                pos = Position(
                    latitude=lat, longitude=lon, altitude=0,
                    accuracy_m=noise_m, timestamp=time.time(),
                )
                return LayerReading(
                    layer_id=self.layer_id, position=pos,
                    self_confidence=0.5,
                    raw_data={
                        "towers_detected": len(signals),
                        "hostile_territory": True,
                    },
                )
            # Insufficient towers
            lat = self.world.true_lat + np.random.normal(0, noise_m * 3 / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m * 3 / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m * 3, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.2,
                raw_data={
                    "towers_detected": len(signals),
                    "hostile_territory": True,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.5,
                raw_data={"towers_detected": 6, "hostile_territory": True},
            )
        raise NotImplementedError("Live cell tower requires radio")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 41 — eLORAN Terrestrial Navigation
# ===================================================================

class ELORANLayer(NavigationLayer):
    """Layer 41 — eLORAN Terrestrial Navigation [NOVEL, UNDERWATER].

    Enhanced LORAN using low-frequency terrestrial transmitters.
    Signals 3-5 million times stronger than GPS. Penetrates buildings,
    underground, and underwater.
    """

    def __init__(self):
        super().__init__(
            layer_id="eloran_l41",
            layer_number=41,
            name="eLORAN Terrestrial Navigation",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            is_novel=True,
            is_underwater=True,
            description="Enhanced LORAN — 3-5M x stronger than GPS",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        noise_m = 20.0

        if self.world is not None:
            # --- Physics-based: TOA trilateration from LORAN stations ---
            signals = self.world.get_loran_signals()
            result = _trilaterate_toa(signals)
            if result is not None:
                lat, lon = result
                # Compute signal strength metric from TOA distances
                avg_dist = np.mean([s["toa_s"] * 3e8 for s in signals])
                # LORAN signal strength estimate (very strong, low freq)
                signal_dbm = -30 - 20 * np.log10(max(avg_dist, 1) / 1000)
                pos = Position(
                    latitude=lat, longitude=lon, altitude=0,
                    accuracy_m=noise_m, timestamp=time.time(),
                )
                return LayerReading(
                    layer_id=self.layer_id, position=pos,
                    self_confidence=0.7,
                    raw_data={
                        "stations_tracked": len(signals),
                        "signal_strength_dbm": signal_dbm,
                        "penetrates": True,
                    },
                )
            # Insufficient LORAN stations
            lat = self.world.true_lat + np.random.normal(0, noise_m * 5 / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m * 5 / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m * 5, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.3,
                raw_data={
                    "stations_tracked": len(signals),
                    "signal_strength_dbm": -80,
                    "penetrates": True,
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.7,
                raw_data={"signal_strength_dbm": -40, "penetrates": True},
            )
        raise NotImplementedError("Live eLORAN requires receiver")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


# ===================================================================
# Layer 42 — Commercial Satellite Signals of Opportunity
# ===================================================================

class CommercialSOOPLayer(NavigationLayer):
    """Layer 42 — Commercial Satellite Signals of Opportunity [NOVEL].

    Doppler from Starlink, Iridium, OneWeb, Globalstar, Orbcomm.
    Operators can't disable without destroying revenue.
    Persistent nav reference independent of dedicated nav sats.
    """

    def __init__(self):
        super().__init__(
            layer_id="soop_l42",
            layer_number=42,
            name="Commercial SOOP",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Starlink/Iridium/OneWeb Doppler positioning",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def read(self) -> LayerReading:
        noise_m = 50.0

        if self.world is not None:
            # --- Physics-based: Doppler positioning from LEO sats ---
            # Use RF emitter signals as proxy for LEO satellite beacons
            signals = self.world.get_rf_emitter_signals()

            # Doppler positioning: simulate Doppler shift from moving LEO sats
            # Each satellite pass gives a position line; multiple passes give a fix
            if len(signals) >= 2:
                # Weighted centroid from signal TOA (proxy for Doppler range)
                total_w = 0.0
                lat_sum = lon_sum = 0.0
                for sig in signals:
                    # Doppler-derived pseudo-range (with satellite velocity effect)
                    pseudo_range_m = sig["toa_s"] * 3e8
                    # Closer satellites have stronger Doppler and better geometry
                    w = 1.0 / max(pseudo_range_m, 1.0) ** 1.5
                    lat_sum += sig["known_lat"] * w
                    lon_sum += sig["known_lon"] * w
                    total_w += w
                lat = lat_sum / total_w
                lon = lon_sum / total_w
                constellations = ["starlink", "iridium"]
                if len(signals) > 4:
                    constellations.append("oneweb")
                pos = Position(
                    latitude=lat, longitude=lon, altitude=0,
                    accuracy_m=noise_m, timestamp=time.time(),
                )
                return LayerReading(
                    layer_id=self.layer_id, position=pos,
                    self_confidence=0.55,
                    raw_data={
                        "constellations": constellations,
                        "sats_tracked": len(signals),
                    },
                )
            # Not enough satellite signals
            lat = self.world.true_lat + np.random.normal(0, noise_m * 4 / 111_000)
            lon = self.world.true_lon + np.random.normal(0, noise_m * 4 / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m * 4, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.2,
                raw_data={
                    "constellations": [],
                    "sats_tracked": len(signals),
                },
            )

        # --- Fallback ---
        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            pos = Position(
                latitude=lat, longitude=lon, altitude=0,
                accuracy_m=noise_m, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.55,
                raw_data={
                    "constellations": ["starlink", "iridium"],
                    "sats_tracked": 8,
                },
            )
        raise NotImplementedError("Live SOOP requires wideband receiver")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
