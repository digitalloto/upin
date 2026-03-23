"""
UPIN Simulation World — Ground Truth Generator.

Provides a coherent simulated environment that every layer queries
independently to compute its own position estimate through its own
sensor physics chain. Each layer gets raw sensor data (not a position)
and must compute coordinates using its own algorithm.

This is the key architectural distinction: layers don't share a position —
they each independently derive one from different physical principles.
If any layer's computation diverges beyond the Mahalanobis threshold,
the fusion engine flags potential spoofing or jamming.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ── Earth constants ──────────────────────────────────────────────
R_EARTH = 6_371_000.0  # metres
DEG_PER_M = 1.0 / 111_000.0  # approximate degrees per metre


@dataclass
class Satellite:
    """A navigation satellite in orbit."""
    sat_id: str
    orbit_radius_m: float
    inclination_deg: float
    raan_deg: float  # right ascension of ascending node
    phase_deg: float  # initial phase angle
    constellation: str  # "GPS", "NavIC", "LEO", etc.

    def position_ecef(self, t: float) -> tuple[float, float, float]:
        """Compute satellite ECEF position at time t (seconds)."""
        # Simplified circular orbit model
        period = 2 * math.pi * math.sqrt(self.orbit_radius_m ** 3 / 3.986e14)
        angle = math.radians(self.phase_deg) + 2 * math.pi * t / period
        inc = math.radians(self.inclination_deg)
        raan = math.radians(self.raan_deg)

        # Position in orbital plane
        x_orb = self.orbit_radius_m * math.cos(angle)
        y_orb = self.orbit_radius_m * math.sin(angle)

        # Rotate to ECEF (simplified — ignores Earth rotation for sim)
        x = (x_orb * math.cos(raan) -
             y_orb * math.sin(raan) * math.cos(inc))
        y = (x_orb * math.sin(raan) +
             y_orb * math.cos(raan) * math.cos(inc))
        z = y_orb * math.sin(inc)

        return (x, y, z)

    @staticmethod
    def from_subsatellite(sat_id: str, lon_deg: float, lat_deg: float,
                          alt_km: float, constellation: str) -> 'Satellite':
        """Create a satellite at a known sub-satellite point.

        Useful for GEO/GSO satellites at known positions.
        """
        sat = Satellite(
            sat_id=sat_id,
            orbit_radius_m=(R_EARTH + alt_km * 1000),
            inclination_deg=abs(lat_deg),
            raan_deg=lon_deg,
            phase_deg=0.0,
            constellation=constellation,
        )
        # Store direct ECEF for this satellite
        lat_r = math.radians(lat_deg)
        lon_r = math.radians(lon_deg)
        r = R_EARTH + alt_km * 1000
        sat._fixed_ecef = (
            r * math.cos(lat_r) * math.cos(lon_r),
            r * math.cos(lat_r) * math.sin(lon_r),
            r * math.sin(lat_r),
        )
        return sat

    def get_ecef(self, t: float) -> tuple[float, float, float]:
        """Get ECEF, using fixed position if set, else orbital model."""
        if hasattr(self, '_fixed_ecef'):
            return self._fixed_ecef
        return self.position_ecef(t)


@dataclass
class WiFiAccessPoint:
    """A known WiFi access point with fixed position."""
    bssid: str
    lat: float
    lon: float
    tx_power_dbm: float = 20.0


@dataclass
class CellTower:
    """A cell tower with known position."""
    tower_id: str
    lat: float
    lon: float
    frequency_mhz: float = 1800.0
    tx_power_dbm: float = 43.0


@dataclass
class RFEmitter:
    """A ground-based RF navigation emitter."""
    emitter_id: str
    lat: float
    lon: float
    frequency_mhz: float
    tx_power_dbm: float = 50.0


@dataclass
class AcousticBeacon:
    """An underwater acoustic beacon."""
    beacon_id: str
    lat: float
    lon: float
    depth_m: float
    frequency_hz: float = 12_000.0


class SimulationWorld:
    """Central ground truth generator for the UPIN simulation.

    The world maintains:
    - True platform state (position, velocity, heading)
    - Satellite constellation positions
    - Magnetic field model
    - Terrain feature database
    - WiFi AP / cell tower / RF emitter locations
    - Gravity model
    - Acoustic beacon positions

    Each layer queries this world for raw sensor data, then computes
    its own position estimate using its own algorithm.
    """

    def __init__(
        self,
        start_lat: float = 13.0827,
        start_lon: float = 80.2707,
        start_alt: float = 100.0,
        start_heading: float = 45.0,
        start_velocity: float = 50.0,  # m/s
    ):
        # ── True platform state ──
        self.true_lat = start_lat
        self.true_lon = start_lon
        self.true_alt = start_alt
        self.true_heading = start_heading  # degrees true north
        self.true_velocity = start_velocity  # m/s ground speed
        self.true_vn = start_velocity * math.cos(math.radians(start_heading))
        self.true_ve = start_velocity * math.sin(math.radians(start_heading))
        self.true_vd = 0.0  # m/s down

        self._start_time = time.time()
        self._elapsed = 0.0

        # ── Satellite constellation ──
        self.gps_satellites = self._init_gps_constellation()
        self.navic_satellites = self._init_navic_constellation()
        self.leo_satellites = self._init_leo_constellation()

        # ── Terrestrial infrastructure ──
        self.wifi_aps = self._init_wifi_aps()
        self.cell_towers = self._init_cell_towers()
        self.rf_emitters = self._init_rf_emitters()
        self.loran_stations = self._init_loran_stations()

        # ── Underwater infrastructure ──
        self.acoustic_beacons = self._init_acoustic_beacons()

        # ── Pre-computed maps ──
        self._magnetic_seed = np.random.RandomState(42)
        self._gravity_seed = np.random.RandomState(137)
        self._terrain_seed = np.random.RandomState(256)

        # ── Spoofing/jamming state ──
        self.gps_spoofed = False
        self.gps_spoof_offset = (0.0, 0.0, 0.0)
        self.gps_jammed = False
        self.navic_jammed = False

    # ── Time stepping ──────────────────────────────────────────

    def step(self, dt: float = 0.1) -> None:
        """Advance ground truth by dt seconds along current heading."""
        self._elapsed += dt

        # Move position
        self.true_lat += (self.true_vn * dt / R_EARTH) * (180.0 / math.pi)
        cos_lat = math.cos(math.radians(self.true_lat))
        if abs(cos_lat) > 1e-10:
            self.true_lon += (self.true_ve * dt /
                              (R_EARTH * cos_lat)) * (180.0 / math.pi)
        self.true_alt -= self.true_vd * dt

        # Slight random heading drift (wind)
        self.true_heading += np.random.normal(0, 0.1)
        self.true_heading %= 360.0
        self.true_vn = self.true_velocity * math.cos(math.radians(self.true_heading))
        self.true_ve = self.true_velocity * math.sin(math.radians(self.true_heading))

    @property
    def true_position(self) -> tuple[float, float, float]:
        return (self.true_lat, self.true_lon, self.true_alt)

    @property
    def elapsed(self) -> float:
        return self._elapsed

    # ── Satellite systems ──────────────────────────────────────

    def _init_gps_constellation(self) -> list[Satellite]:
        """GPS: 31 satellites in 6 orbital planes, ~20,200 km altitude."""
        sats = []
        for plane in range(6):
            for slot in range(5):
                sats.append(Satellite(
                    sat_id=f"G{plane * 5 + slot + 1:02d}",
                    orbit_radius_m=R_EARTH + 20_200_000,
                    inclination_deg=55.0,
                    raan_deg=plane * 60.0,
                    phase_deg=slot * 72.0 + plane * 12.0,
                    constellation="GPS",
                ))
        return sats

    def _init_navic_constellation(self) -> list[Satellite]:
        """NavIC: 3 GEO + 4 GSO satellites over India.

        GEO satellites are at fixed longitudes over Indian Ocean.
        GSO satellites trace figure-8 patterns over India.
        All 7 should be visible from Indian subcontinent.
        """
        sats = []
        # 3 Geostationary at fixed longitudes over India/Indian Ocean
        for i, lon_deg in enumerate([34.0, 83.0, 129.5]):
            sats.append(Satellite.from_subsatellite(
                f"N{i + 1}", lon_deg, 0.0, 35_786, "NavIC"
            ))
        # 4 Geosynchronous inclined — at known positions over India
        for i, (lon_deg, lat_deg) in enumerate([
            (55.0, 29.0), (55.0, -29.0),
            (111.75, 29.0), (111.75, -29.0),
        ]):
            sats.append(Satellite.from_subsatellite(
                f"N{i + 4}", lon_deg, lat_deg, 35_786, "NavIC"
            ))
        return sats

    def _init_leo_constellation(self) -> list[Satellite]:
        """LEO authenticated signals: Xona Pulsar-like, ~1200 km."""
        sats = []
        for i in range(24):
            sats.append(Satellite(
                sat_id=f"L{i + 1:02d}",
                orbit_radius_m=R_EARTH + 1_200_000,
                inclination_deg=87.0,
                raan_deg=i * 15.0,
                phase_deg=i * 30.0,
                constellation="LEO",
            ))
        return sats

    def get_pseudoranges(
        self, constellation: str, clock_bias_m: float = 0.0
    ) -> list[dict]:
        """Compute pseudoranges from platform to visible satellites.

        Each satellite returns:
            - sat_id, true_range_m, pseudorange_m (with noise + clock bias)
            - elevation_deg (for visibility check)
            - sat_ecef (for trilateration)

        This is what a real GPS/NavIC receiver computes before trilateration.
        """
        if constellation == "GPS":
            sats = self.gps_satellites
            noise_std = 3.0  # metres
            mask_angle = 10.0
        elif constellation == "NavIC":
            sats = self.navic_satellites
            noise_std = 1.0
            mask_angle = 5.0  # GEO sats always high elevation from India
        elif constellation == "LEO":
            sats = self.leo_satellites
            noise_std = 0.5
            mask_angle = 10.0
        else:
            return []

        # Platform position in ECEF (simplified)
        plat_ecef = self._lla_to_ecef(self.true_lat, self.true_lon, self.true_alt)

        results = []
        for sat in sats:
            sat_ecef = sat.get_ecef(self._elapsed)
            dx = sat_ecef[0] - plat_ecef[0]
            dy = sat_ecef[1] - plat_ecef[1]
            dz = sat_ecef[2] - plat_ecef[2]
            true_range = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)

            # Compute elevation angle properly using dot product
            # Unit vector from platform to satellite
            range_vec = np.array([dx, dy, dz])
            plat_vec = np.array(plat_ecef)
            plat_norm = np.linalg.norm(plat_vec)
            if plat_norm < 1:
                continue
            up_unit = plat_vec / plat_norm
            cos_zenith = np.dot(range_vec, up_unit) / (true_range * 1.0)
            elevation = 90.0 - math.degrees(math.acos(
                max(-1, min(1, cos_zenith))
            ))
            if elevation < mask_angle:
                continue  # Below mask angle

            # Add pseudorange noise and clock bias
            pseudorange = true_range + np.random.normal(0, noise_std) + clock_bias_m

            # Apply spoofing offset for GPS
            if constellation == "GPS" and self.gps_spoofed:
                spoof_pos = (
                    self.true_lat + self.gps_spoof_offset[0],
                    self.true_lon + self.gps_spoof_offset[1],
                    self.true_alt + self.gps_spoof_offset[2],
                )
                spoof_ecef = self._lla_to_ecef(*spoof_pos)
                dx2 = sat_ecef[0] - spoof_ecef[0]
                dy2 = sat_ecef[1] - spoof_ecef[1]
                dz2 = sat_ecef[2] - spoof_ecef[2]
                pseudorange = math.sqrt(dx2 ** 2 + dy2 ** 2 + dz2 ** 2) + np.random.normal(0, noise_std)

            results.append({
                "sat_id": sat.sat_id,
                "true_range_m": true_range,
                "pseudorange_m": pseudorange,
                "elevation_deg": elevation,
                "sat_ecef": sat_ecef,
            })

        return results

    # ── Magnetic field model ───────────────────────────────────

    def get_magnetic_field(
        self, lat: Optional[float] = None, lon: Optional[float] = None
    ) -> dict:
        """Return magnetic field components at a position.

        Uses a simplified IGRF-like model with spatial variation.
        Returns intensity (nT), inclination, declination.
        """
        lat = lat if lat is not None else self.true_lat
        lon = lon if lon is not None else self.true_lon

        # Base field varies with latitude (dipole approximation)
        base_intensity = 30000 + 20000 * math.sin(math.radians(lat))
        # Spatial anomalies — deterministic based on position
        anomaly = (150 * math.sin(lat * 7.3 + lon * 4.1) +
                   80 * math.cos(lat * 11.7 - lon * 8.3) +
                   40 * math.sin(lat * 23.1 + lon * 17.9))
        intensity = base_intensity + anomaly

        inclination = 30.0 + 30.0 * math.sin(math.radians(lat))
        declination = -2.0 + 4.0 * math.sin(math.radians(lon * 0.5))

        return {
            "intensity_nt": intensity,
            "inclination_deg": inclination,
            "declination_deg": declination,
            "bx_nt": intensity * math.cos(math.radians(inclination)),
            "bz_nt": intensity * math.sin(math.radians(inclination)),
        }

    def magnetic_field_at_grid(self) -> dict[tuple[int, int], float]:
        """Return precomputed magnetic field intensity on a grid.

        Used by magnetic map matching layers to find best-fit position.
        Grid resolution: 0.01 degrees (~1.1 km).
        """
        grid = {}
        for lat_i in range(int((self.true_lat - 1) * 100),
                           int((self.true_lat + 1) * 100)):
            for lon_i in range(int((self.true_lon - 1) * 100),
                               int((self.true_lon + 1) * 100)):
                lat = lat_i / 100.0
                lon = lon_i / 100.0
                field = self.get_magnetic_field(lat, lon)
                grid[(lat_i, lon_i)] = field["intensity_nt"]
        return grid

    # ── Gravity model ──────────────────────────────────────────

    def get_gravity(
        self, lat: Optional[float] = None, lon: Optional[float] = None
    ) -> dict:
        """Return gravity field at position.

        Uses WGS84 normal gravity + spatial anomalies.
        """
        lat = lat if lat is not None else self.true_lat
        lon = lon if lon is not None else self.true_lon

        # Normal gravity (Somigliana formula simplified)
        g0 = 9.780327 * (1 + 0.0053024 * math.sin(math.radians(lat)) ** 2)
        # Free-air correction for altitude
        g = g0 - 3.086e-6 * self.true_alt

        # Gravity anomaly (spatial variation) in mGal
        anomaly_mgal = (5.0 * math.sin(lat * 13.7 + lon * 9.3) +
                        3.0 * math.cos(lat * 27.1 - lon * 19.7))

        # Gravity gradient (Eötvös)
        gradient = 3000.0 + 50 * math.sin(lat * 5.1 + lon * 3.7)

        return {
            "g_ms2": g + anomaly_mgal * 1e-5,
            "anomaly_mgal": anomaly_mgal,
            "gradient_eotvos": gradient,
        }

    def gravity_at_grid(self) -> dict[tuple[int, int], float]:
        """Precomputed gravity on a grid for map matching."""
        grid = {}
        for lat_i in range(int((self.true_lat - 0.5) * 100),
                           int((self.true_lat + 0.5) * 100)):
            for lon_i in range(int((self.true_lon - 0.5) * 100),
                               int((self.true_lon + 0.5) * 100)):
                lat = lat_i / 100.0
                lon = lon_i / 100.0
                grav = self.get_gravity(lat, lon)
                grid[(lat_i, lon_i)] = grav["anomaly_mgal"]
        return grid

    # ── Terrain model ──────────────────────────────────────────

    def get_terrain_features(self) -> list[dict]:
        """Return terrain features visible from current position.

        Simulates a terrain feature database with known lat/lon for each
        feature. The terrain matching layer correlates observed features
        with this database to compute position.
        """
        features = []
        rng = np.random.RandomState(int(self.true_lat * 1000 + self.true_lon * 1000) % (2**31))
        n_features = rng.randint(50, 200)
        for i in range(n_features):
            # Features within ~2km of true position
            f_lat = self.true_lat + rng.uniform(-0.02, 0.02)
            f_lon = self.true_lon + rng.uniform(-0.02, 0.02)
            features.append({
                "feature_id": f"TF{i:04d}",
                "lat": f_lat,
                "lon": f_lon,
                "type": rng.choice(["building", "road_intersection",
                                     "river_bend", "coastline", "ridge"]),
                "signature": rng.random(16).tolist(),  # feature descriptor
            })
        return features

    # ── WiFi / Cell / RF infrastructure ────────────────────────

    def _init_wifi_aps(self) -> list[WiFiAccessPoint]:
        rng = np.random.RandomState(100)
        aps = []
        for i in range(30):
            aps.append(WiFiAccessPoint(
                bssid=f"AA:BB:CC:DD:{i:02X}:00",
                lat=self.true_lat + rng.uniform(-0.01, 0.01),
                lon=self.true_lon + rng.uniform(-0.01, 0.01),
                tx_power_dbm=20.0,
            ))
        return aps

    def _init_cell_towers(self) -> list[CellTower]:
        rng = np.random.RandomState(200)
        towers = []
        for i in range(12):
            towers.append(CellTower(
                tower_id=f"CT{i:03d}",
                lat=self.true_lat + rng.uniform(-0.05, 0.05),
                lon=self.true_lon + rng.uniform(-0.05, 0.05),
            ))
        return towers

    def _init_rf_emitters(self) -> list[RFEmitter]:
        rng = np.random.RandomState(300)
        emitters = []
        for i in range(8):
            emitters.append(RFEmitter(
                emitter_id=f"RF{i:02d}",
                lat=self.true_lat + rng.uniform(-0.1, 0.1),
                lon=self.true_lon + rng.uniform(-0.1, 0.1),
                frequency_mhz=400 + i * 50,
            ))
        return emitters

    def _init_loran_stations(self) -> list[RFEmitter]:
        """eLORAN transmitter stations — widely separated."""
        return [
            RFEmitter("LORAN_A", self.true_lat + 2.0, self.true_lon - 1.5, 100.0, 1000.0),
            RFEmitter("LORAN_B", self.true_lat - 1.5, self.true_lon + 2.5, 100.0, 1000.0),
            RFEmitter("LORAN_C", self.true_lat + 0.5, self.true_lon + 3.0, 100.0, 1000.0),
        ]

    def _init_acoustic_beacons(self) -> list[AcousticBeacon]:
        return [
            AcousticBeacon("AB01", self.true_lat + 0.01, self.true_lon - 0.01, 50.0),
            AcousticBeacon("AB02", self.true_lat - 0.01, self.true_lon + 0.01, 50.0),
            AcousticBeacon("AB03", self.true_lat + 0.005, self.true_lon + 0.015, 50.0),
        ]

    def get_wifi_rssi(self) -> list[dict]:
        """Compute RSSI from each visible WiFi AP using path loss model."""
        results = []
        for ap in self.wifi_aps:
            dist = self._haversine_m(self.true_lat, self.true_lon, ap.lat, ap.lon)
            if dist > 500:
                continue  # Out of range
            # Log-distance path loss model
            if dist < 1:
                dist = 1
            rssi = ap.tx_power_dbm - 40 - 20 * math.log10(dist)
            rssi += np.random.normal(0, 3)  # Shadow fading
            results.append({
                "bssid": ap.bssid,
                "rssi_dbm": rssi,
                "known_lat": ap.lat,
                "known_lon": ap.lon,
            })
        return results

    def get_cell_tower_signals(self) -> list[dict]:
        """Compute signal strength from each visible cell tower."""
        results = []
        for tower in self.cell_towers:
            dist = self._haversine_m(self.true_lat, self.true_lon,
                                     tower.lat, tower.lon)
            if dist > 10_000:
                continue
            if dist < 1:
                dist = 1
            rssi = tower.tx_power_dbm - 30 - 35 * math.log10(dist)
            rssi += np.random.normal(0, 6)
            timing_advance = dist / 3e8 * 1e6  # microseconds
            results.append({
                "tower_id": tower.tower_id,
                "rssi_dbm": rssi,
                "timing_advance_us": timing_advance + np.random.normal(0, 0.1),
                "known_lat": tower.lat,
                "known_lon": tower.lon,
            })
        return results

    def get_rf_emitter_signals(self) -> list[dict]:
        """Compute signal timing from ground RF emitters."""
        results = []
        for emitter in self.rf_emitters:
            dist = self._haversine_m(self.true_lat, self.true_lon,
                                     emitter.lat, emitter.lon)
            toa = dist / 3e8  # time of arrival in seconds
            results.append({
                "emitter_id": emitter.emitter_id,
                "toa_s": toa + np.random.normal(0, 1e-7),
                "known_lat": emitter.lat,
                "known_lon": emitter.lon,
            })
        return results

    def get_loran_signals(self) -> list[dict]:
        """Compute eLORAN signal timing."""
        results = []
        for station in self.loran_stations:
            dist = self._haversine_m(self.true_lat, self.true_lon,
                                     station.lat, station.lon)
            toa = dist / 3e8
            results.append({
                "station_id": station.emitter_id,
                "toa_s": toa + np.random.normal(0, 5e-8),
                "known_lat": station.lat,
                "known_lon": station.lon,
            })
        return results

    def get_acoustic_arrivals(self) -> list[dict]:
        """Compute acoustic signal arrival times from beacons."""
        sound_speed = 1500.0  # m/s underwater
        results = []
        for beacon in self.acoustic_beacons:
            dist = self._haversine_m(self.true_lat, self.true_lon,
                                     beacon.lat, beacon.lon)
            toa = dist / sound_speed
            results.append({
                "beacon_id": beacon.beacon_id,
                "toa_s": toa + np.random.normal(0, 0.001),
                "known_lat": beacon.lat,
                "known_lon": beacon.lon,
            })
        return results

    def get_star_positions(self) -> list[dict]:
        """Return bright star positions for celestial navigation."""
        # Simplified — fixed star catalog with known declination/RA
        stars = [
            {"name": "Polaris", "ra_deg": 37.95, "dec_deg": 89.26, "mag": 1.97},
            {"name": "Sirius", "ra_deg": 101.29, "dec_deg": -16.72, "mag": -1.46},
            {"name": "Canopus", "ra_deg": 95.99, "dec_deg": -52.70, "mag": -0.74},
            {"name": "Arcturus", "ra_deg": 213.92, "dec_deg": 19.18, "mag": -0.05},
            {"name": "Vega", "ra_deg": 279.23, "dec_deg": 38.78, "mag": 0.03},
            {"name": "Rigel", "ra_deg": 78.63, "dec_deg": -8.20, "mag": 0.13},
            {"name": "Betelgeuse", "ra_deg": 88.79, "dec_deg": 7.41, "mag": 0.42},
            {"name": "Acrux", "ra_deg": 186.65, "dec_deg": -63.10, "mag": 0.76},
        ]
        # Add measured altitude (with atmospheric refraction noise)
        for star in stars:
            # Simplified altitude = declination + (90 - lat)
            alt = star["dec_deg"] + (90 - self.true_lat)
            alt = max(-90, min(90, alt))
            star["measured_altitude_deg"] = alt + np.random.normal(0, 0.02)
            # Azimuth (simplified)
            star["measured_azimuth_deg"] = (star["ra_deg"] - self._elapsed * 0.25) % 360
            star["measured_azimuth_deg"] += np.random.normal(0, 0.05)
        return [s for s in stars if s.get("measured_altitude_deg", 0) > 5]

    def get_chemical_gradients(self) -> dict:
        """Return ocean chemical properties at current position."""
        # Chemical properties vary spatially
        return {
            "temperature_c": 26.0 + 2.0 * math.sin(self.true_lat * 5.0),
            "salinity_psu": 35.0 + 0.5 * math.cos(self.true_lon * 3.0),
            "dissolved_o2_mgl": 7.5 - 0.3 * math.sin(self.true_lat * 8.0),
            "ph": 8.1 + 0.05 * math.cos(self.true_lon * 6.0),
        }

    def get_ionospheric_density(self) -> dict:
        """Return ionospheric electron density at current position."""
        # TEC varies with latitude and time of day
        base_tec = 25.0 + 15.0 * math.cos(math.radians(self.true_lat - 15))
        return {
            "tecu": base_tec + np.random.normal(0, 2),
            "electron_density_m3": (base_tec * 1e16 +
                                     np.random.normal(0, 1e14)),
        }

    def get_schumann_resonance(self) -> dict:
        """Schumann resonance signature at current position."""
        # The fundamental varies slightly with position relative to
        # thunderstorm activity centers
        return {
            "fundamental_hz": 7.83 + 0.02 * math.sin(self.true_lat * 2.1),
            "amplitude_pv": 0.5 + 0.1 * math.cos(self.true_lon * 1.5),
            "harmonic_2_hz": 14.3 + 0.01 * math.sin(self.true_lat * 3.0),
        }

    def get_muon_flux(self) -> dict:
        """Cosmic ray muon timing from reference stations."""
        # Muon timing differences from 3 reference stations
        return {
            "station_1_dt_ns": np.random.normal(0, 5),
            "station_2_dt_ns": np.random.normal(0, 5),
            "station_3_dt_ns": np.random.normal(0, 5),
            "flux_per_m2_min": 10000 + np.random.normal(0, 100),
        }

    def get_barometric_pressure(self) -> float:
        """Return barometric pressure at current altitude (hPa)."""
        # ISA standard atmosphere
        return 1013.25 * (1 - 2.25577e-5 * self.true_alt) ** 5.25588

    def get_pulsar_timing(self) -> list[dict]:
        """X-ray pulsar timing residuals for XNAV."""
        pulsars = [
            {"name": "B0531+21", "period_ms": 33.0, "ra_deg": 83.63, "dec_deg": 22.01},
            {"name": "B1937+21", "period_ms": 1.558, "ra_deg": 294.91, "dec_deg": 21.58},
            {"name": "B1821-24", "period_ms": 3.054, "ra_deg": 276.13, "dec_deg": -24.87},
        ]
        for p in pulsars:
            # Timing residual encodes position (simplified)
            # True residual based on position
            p["residual_ns"] = (
                10.0 * math.sin(math.radians(self.true_lat - p["dec_deg"])) +
                10.0 * math.cos(math.radians(self.true_lon - p["ra_deg"])) +
                np.random.normal(0, 2.0)
            )
        return pulsars

    # ── Spoofing/jamming controls ──────────────────────────────

    def set_gps_spoofing(self, offset_lat: float, offset_lon: float,
                         offset_alt: float = 0.0) -> None:
        self.gps_spoofed = True
        self.gps_spoof_offset = (offset_lat, offset_lon, offset_alt)

    def clear_gps_spoofing(self) -> None:
        self.gps_spoofed = False
        self.gps_spoof_offset = (0.0, 0.0, 0.0)

    def set_gps_jamming(self, jammed: bool = True) -> None:
        self.gps_jammed = jammed

    # ── Utility ────────────────────────────────────────────────

    def _lla_to_ecef(self, lat: float, lon: float, alt: float) -> tuple:
        """Convert lat/lon/alt to ECEF (simplified spherical)."""
        lat_r = math.radians(lat)
        lon_r = math.radians(lon)
        r = R_EARTH + alt
        x = r * math.cos(lat_r) * math.cos(lon_r)
        y = r * math.cos(lat_r) * math.sin(lon_r)
        z = r * math.sin(lat_r)
        return (x, y, z)

    def _ecef_to_lla(self, x: float, y: float, z: float) -> tuple:
        """Convert ECEF to lat/lon/alt (simplified spherical)."""
        r = math.sqrt(x ** 2 + y ** 2 + z ** 2)
        lat = math.degrees(math.asin(z / r))
        lon = math.degrees(math.atan2(y, x))
        alt = r - R_EARTH
        return (lat, lon, alt)

    @staticmethod
    def _haversine_m(lat1: float, lon1: float,
                     lat2: float, lon2: float) -> float:
        """Distance in metres between two lat/lon points."""
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
