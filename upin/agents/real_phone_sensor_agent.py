"""
Real Phone Sensor Agent — UPIN

Accesses real device sensors: GPS, accelerometer, gyroscope, magnetometer,
barometer. Works on Linux (gpsd, lm-sensors, iio), Android (Termux),
and falls back to simulation when sensors are unavailable.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from upin.agents.base_agent import BaseAgent


@dataclass
class GPSReading:
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float = 0.0
    speed_mps: float = 0.0
    heading_deg: float = 0.0
    accuracy_m: float = 0.0
    satellites: int = 0
    fix_type: str = "none"  # none, 2d, 3d
    timestamp: float = 0.0


@dataclass
class IMUReading:
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 0.0
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0
    mag_x: float = 0.0
    mag_y: float = 0.0
    mag_z: float = 0.0
    heading_deg: float = 0.0
    timestamp: float = 0.0


@dataclass
class BaroReading:
    pressure_hpa: float = 1013.25
    temperature_c: float = 20.0
    altitude_m: float = 0.0  # Derived from pressure
    timestamp: float = 0.0


@dataclass
class SensorSnapshot:
    """Complete snapshot of all phone sensors at one moment."""
    gps: GPSReading = field(default_factory=GPSReading)
    imu: IMUReading = field(default_factory=IMUReading)
    baro: BaroReading = field(default_factory=BaroReading)
    timestamp: float = 0.0
    platform: str = "unknown"
    sensors_available: List[str] = field(default_factory=list)


class RealPhoneSensorAgent(BaseAgent):
    """
    Accesses real device sensors: GPS, accelerometer, gyroscope,
    magnetometer, barometer.

    Platform support:
      - Linux: gpsd (GPS), IIO subsystem (IMU), lm-sensors (temp)
      - Android/Termux: termux-location, termux-sensor
      - Fallback: simulated sensor data for testing
    """

    def __init__(self, agent_id: str = "phone_sensors"):
        super().__init__(agent_id, "PHONE_SENSORS")
        self.status = "ACTIVE"
        self._platform = sys.platform
        self._is_termux = os.path.exists("/data/data/com.termux")
        self._last_snapshot: Optional[SensorSnapshot] = None
        self._cache_ttl_s = 2.0
        self._read_count = 0

        # Detect available sensors on init
        self._available_sensors = self._detect_sensors()

    # ── BaseAgent interface ────────────────────────────────────────

    def get_reading(self) -> Dict:
        snap = self.get_snapshot()
        conf = 0.0
        if snap.gps.fix_type in ("2d", "3d"):
            conf = max(0.1, min(0.95, 1.0 - snap.gps.accuracy_m / 100.0))
        elif snap.imu.accel_z != 0:
            conf = 0.3  # IMU-only dead reckoning is low confidence

        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "lat": snap.gps.latitude,
            "lon": snap.gps.longitude,
            "accuracy_m": snap.gps.accuracy_m,
            "altitude_m": snap.gps.altitude_m or snap.baro.altitude_m,
            "speed_mps": snap.gps.speed_mps,
            "heading_deg": snap.imu.heading_deg or snap.gps.heading_deg,
            "accel": (snap.imu.accel_x, snap.imu.accel_y, snap.imu.accel_z),
            "gyro": (snap.imu.gyro_x, snap.imu.gyro_y, snap.imu.gyro_z),
            "mag": (snap.imu.mag_x, snap.imu.mag_y, snap.imu.mag_z),
            "pressure_hpa": snap.baro.pressure_hpa,
            "temperature_c": snap.baro.temperature_c,
            "confidence": conf,
            "sensors_available": snap.sensors_available,
            "platform": snap.platform,
            "timestamp": snap.timestamp,
            "status": "ACTIVE",
        }

    def is_available(self) -> bool:
        return True

    def calibrate(self) -> bool:
        self._last_snapshot = None
        self._available_sensors = self._detect_sensors()
        return True

    # ── Public API ─────────────────────────────────────────────────

    def get_snapshot(self) -> SensorSnapshot:
        """Get full sensor snapshot. Uses cache if fresh."""
        if (self._last_snapshot and
                time.time() - self._last_snapshot.timestamp < self._cache_ttl_s):
            return self._last_snapshot

        self._read_count += 1
        snap = SensorSnapshot(timestamp=time.time(), platform=self._platform)

        # GPS
        gps = self._read_gps()
        if gps:
            snap.gps = gps
            snap.sensors_available.append("gps")

        # IMU (accel + gyro + mag)
        imu = self._read_imu()
        if imu:
            snap.imu = imu
            if imu.accel_z != 0:
                snap.sensors_available.append("accelerometer")
            if imu.gyro_x != 0 or imu.gyro_y != 0 or imu.gyro_z != 0:
                snap.sensors_available.append("gyroscope")
            if imu.mag_x != 0 or imu.mag_y != 0 or imu.mag_z != 0:
                snap.sensors_available.append("magnetometer")

        # Barometer
        baro = self._read_barometer()
        if baro:
            snap.baro = baro
            snap.sensors_available.append("barometer")

        # If nothing real was found, simulate
        if not snap.sensors_available:
            snap = self._simulate_snapshot()

        self._last_snapshot = snap
        return snap

    def get_gps(self) -> Optional[GPSReading]:
        return self._read_gps() or self._simulate_gps()

    def get_imu(self) -> Optional[IMUReading]:
        return self._read_imu() or self._simulate_imu()

    def get_barometer(self) -> Optional[BaroReading]:
        return self._read_barometer() or self._simulate_baro()

    # ── Sensor detection ───────────────────────────────────────────

    def _detect_sensors(self) -> List[str]:
        available = []

        # GPS
        if self._is_termux or self._check_command("gpspipe"):
            available.append("gps")

        # IMU via IIO
        if os.path.exists("/sys/bus/iio/devices"):
            for dev in os.listdir("/sys/bus/iio/devices"):
                path = f"/sys/bus/iio/devices/{dev}/name"
                if os.path.exists(path):
                    try:
                        name = open(path).read().strip().lower()
                        if "accel" in name:
                            available.append("accelerometer")
                        if "gyro" in name:
                            available.append("gyroscope")
                        if "magn" in name:
                            available.append("magnetometer")
                    except (IOError, PermissionError):
                        pass

        # Barometer via IIO or hwmon
        if os.path.exists("/sys/bus/iio/devices"):
            available.append("barometer")  # Optimistic; actual read will verify

        if self._is_termux:
            available.extend(["accelerometer", "gyroscope", "magnetometer", "barometer"])

        return list(set(available))

    @staticmethod
    def _check_command(cmd: str) -> bool:
        try:
            subprocess.run(["which", cmd], capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── GPS Readers ────────────────────────────────────────────────

    def _read_gps(self) -> Optional[GPSReading]:
        if self._is_termux:
            return self._read_gps_termux()
        return self._read_gps_gpsd()

    def _read_gps_gpsd(self) -> Optional[GPSReading]:
        """Read GPS from gpsd (Linux)."""
        try:
            result = subprocess.run(
                ["gpspipe", "-w", "-n", "1"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            for line in result.stdout.strip().split("\n"):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if data.get("class") == "TPV":
                    return GPSReading(
                        latitude=data.get("lat", 0.0),
                        longitude=data.get("lon", 0.0),
                        altitude_m=data.get("altMSL", data.get("alt", 0.0)),
                        speed_mps=data.get("speed", 0.0),
                        heading_deg=data.get("track", 0.0),
                        accuracy_m=data.get("epx", data.get("eph", 10.0)),
                        satellites=data.get("nSat", 0),
                        fix_type="3d" if data.get("mode", 0) >= 3 else
                                 "2d" if data.get("mode", 0) == 2 else "none",
                        timestamp=time.time(),
                    )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _read_gps_termux(self) -> Optional[GPSReading]:
        """Read GPS on Android via Termux."""
        try:
            result = subprocess.run(
                ["termux-location", "-p", "gps", "-r", "once"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return GPSReading(
                    latitude=data.get("latitude", 0.0),
                    longitude=data.get("longitude", 0.0),
                    altitude_m=data.get("altitude", 0.0),
                    speed_mps=data.get("speed", 0.0),
                    heading_deg=data.get("bearing", 0.0),
                    accuracy_m=data.get("accuracy", 10.0),
                    fix_type="3d",
                    timestamp=time.time(),
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return None

    # ── IMU Readers ────────────────────────────────────────────────

    def _read_imu(self) -> Optional[IMUReading]:
        if self._is_termux:
            return self._read_imu_termux()
        return self._read_imu_iio()

    def _read_imu_iio(self) -> Optional[IMUReading]:
        """Read IMU from Linux IIO subsystem."""
        reading = IMUReading(timestamp=time.time())
        found_anything = False

        iio_base = "/sys/bus/iio/devices"
        if not os.path.exists(iio_base):
            return None

        for dev in os.listdir(iio_base):
            dev_path = f"{iio_base}/{dev}"

            # Accelerometer
            for axis, attr in [("x", "accel_x"), ("y", "accel_y"), ("z", "accel_z")]:
                raw_path = f"{dev_path}/in_accel_{axis}_raw"
                if os.path.exists(raw_path):
                    try:
                        raw = float(open(raw_path).read().strip())
                        scale_path = f"{dev_path}/in_accel_scale"
                        scale = float(open(scale_path).read().strip()) if os.path.exists(scale_path) else 1.0
                        setattr(reading, attr, raw * scale)
                        found_anything = True
                    except (IOError, ValueError, PermissionError):
                        pass

            # Gyroscope
            for axis, attr in [("x", "gyro_x"), ("y", "gyro_y"), ("z", "gyro_z")]:
                raw_path = f"{dev_path}/in_anglvel_{axis}_raw"
                if os.path.exists(raw_path):
                    try:
                        raw = float(open(raw_path).read().strip())
                        scale_path = f"{dev_path}/in_anglvel_scale"
                        scale = float(open(scale_path).read().strip()) if os.path.exists(scale_path) else 1.0
                        setattr(reading, attr, raw * scale)
                        found_anything = True
                    except (IOError, ValueError, PermissionError):
                        pass

            # Magnetometer
            for axis, attr in [("x", "mag_x"), ("y", "mag_y"), ("z", "mag_z")]:
                raw_path = f"{dev_path}/in_magn_{axis}_raw"
                if os.path.exists(raw_path):
                    try:
                        raw = float(open(raw_path).read().strip())
                        scale_path = f"{dev_path}/in_magn_scale"
                        scale = float(open(scale_path).read().strip()) if os.path.exists(scale_path) else 1.0
                        setattr(reading, attr, raw * scale)
                        found_anything = True
                    except (IOError, ValueError, PermissionError):
                        pass

        if found_anything:
            # Derive heading from magnetometer
            if reading.mag_x != 0 or reading.mag_y != 0:
                reading.heading_deg = (math.degrees(math.atan2(reading.mag_y, reading.mag_x)) + 360) % 360
            return reading

        return None

    def _read_imu_termux(self) -> Optional[IMUReading]:
        """Read IMU from Termux sensor API."""
        reading = IMUReading(timestamp=time.time())
        found = False

        for sensor_type in ["accelerometer", "gyroscope", "magnetic_field"]:
            try:
                result = subprocess.run(
                    ["termux-sensor", "-s", sensor_type, "-n", "1"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    continue

                data = json.loads(result.stdout)
                values = data.get(sensor_type, {}).get("values", [0, 0, 0])

                if sensor_type == "accelerometer" and len(values) >= 3:
                    reading.accel_x, reading.accel_y, reading.accel_z = values[:3]
                    found = True
                elif sensor_type == "gyroscope" and len(values) >= 3:
                    reading.gyro_x, reading.gyro_y, reading.gyro_z = values[:3]
                    found = True
                elif sensor_type == "magnetic_field" and len(values) >= 3:
                    reading.mag_x, reading.mag_y, reading.mag_z = values[:3]
                    reading.heading_deg = (math.degrees(math.atan2(values[1], values[0])) + 360) % 360
                    found = True

            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError,
                    ValueError, IndexError):
                pass

        return reading if found else None

    # ── Barometer Reader ───────────────────────────────────────────

    def _read_barometer(self) -> Optional[BaroReading]:
        if self._is_termux:
            return self._read_baro_termux()
        return self._read_baro_iio()

    def _read_baro_iio(self) -> Optional[BaroReading]:
        """Read barometer from Linux IIO."""
        iio_base = "/sys/bus/iio/devices"
        if not os.path.exists(iio_base):
            return None

        for dev in os.listdir(iio_base):
            raw_path = f"{iio_base}/{dev}/in_pressure_raw"
            if os.path.exists(raw_path):
                try:
                    raw = float(open(raw_path).read().strip())
                    scale_path = f"{iio_base}/{dev}/in_pressure_scale"
                    scale = float(open(scale_path).read().strip()) if os.path.exists(scale_path) else 1.0
                    pressure_kpa = raw * scale
                    pressure_hpa = pressure_kpa * 10.0  # kPa to hPa

                    # Barometric altitude formula
                    altitude = 44330.0 * (1.0 - (pressure_hpa / 1013.25) ** (1.0 / 5.255))

                    return BaroReading(
                        pressure_hpa=pressure_hpa,
                        altitude_m=altitude,
                        timestamp=time.time(),
                    )
                except (IOError, ValueError, PermissionError):
                    pass

        return None

    def _read_baro_termux(self) -> Optional[BaroReading]:
        """Read barometer from Termux."""
        try:
            result = subprocess.run(
                ["termux-sensor", "-s", "pressure", "-n", "1"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                values = data.get("pressure", {}).get("values", [1013.25])
                pressure = values[0] if values else 1013.25
                altitude = 44330.0 * (1.0 - (pressure / 1013.25) ** (1.0 / 5.255))
                return BaroReading(
                    pressure_hpa=pressure,
                    altitude_m=altitude,
                    timestamp=time.time(),
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return None

    # ── Simulation ─────────────────────────────────────────────────

    def _simulate_snapshot(self) -> SensorSnapshot:
        import random
        return SensorSnapshot(
            gps=self._simulate_gps(),
            imu=self._simulate_imu(),
            baro=self._simulate_baro(),
            timestamp=time.time(),
            platform=self._platform,
            sensors_available=["gps_sim", "accel_sim", "gyro_sim", "mag_sim", "baro_sim"],
        )

    def _simulate_gps(self) -> GPSReading:
        import random
        return GPSReading(
            latitude=13.0827 + random.gauss(0, 0.0001),
            longitude=80.2707 + random.gauss(0, 0.0001),
            altitude_m=10.0 + random.gauss(0, 2),
            speed_mps=random.uniform(0, 2),
            heading_deg=random.uniform(0, 360),
            accuracy_m=5 + random.uniform(0, 10),
            satellites=random.randint(6, 14),
            fix_type="3d",
            timestamp=time.time(),
        )

    def _simulate_imu(self) -> IMUReading:
        import random
        mx, my = random.gauss(25, 5), random.gauss(-10, 5)
        return IMUReading(
            accel_x=random.gauss(0, 0.5),
            accel_y=random.gauss(0, 0.5),
            accel_z=random.gauss(9.8, 0.3),
            gyro_x=random.gauss(0, 2),
            gyro_y=random.gauss(0, 2),
            gyro_z=random.gauss(0, 2),
            mag_x=mx, mag_y=my,
            mag_z=random.gauss(45, 3),
            heading_deg=(math.degrees(math.atan2(my, mx)) + 360) % 360,
            timestamp=time.time(),
        )

    def _simulate_baro(self) -> BaroReading:
        import random
        p = 1013.25 + random.gauss(0, 2)
        return BaroReading(
            pressure_hpa=p,
            temperature_c=25 + random.gauss(0, 2),
            altitude_m=44330.0 * (1.0 - (p / 1013.25) ** (1.0 / 5.255)),
            timestamp=time.time(),
        )

    # ── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "platform": self._platform,
            "is_termux": self._is_termux,
            "detected_sensors": self._available_sensors,
            "read_count": self._read_count,
            "cache_ttl_s": self._cache_ttl_s,
            "last_sensors": self._last_snapshot.sensors_available if self._last_snapshot else [],
        }
