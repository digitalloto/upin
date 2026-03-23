"""
Group B — Inertial and Timing Layers (8 layers).

Layer 3:  INS Dead Reckoning
Layer 11: Barometric Altitude
Layer 12: Doppler Velocity Radar
Layer 18: Laser Doppler Velocity Sensor [N]
Layer 27: Quantum Optical Atomic Clock [N, U]
Layer 43: Optic Flow Velocity and Proximity Sensing [N]
Layer 57: Nuclear Magnetic Resonance Gyroscope [N, U]
Layer 58: SERF Atomic Spin Gyroscope [N, U]
"""

from __future__ import annotations

import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class INSDeadReckoningLayer(NavigationLayer):
    """Layer 3 — INS Dead Reckoning.

    Standard inertial navigation using gyroscopes and accelerometers.
    Tracks position from known start through integration of acceleration
    and rotation. Drifts over time without external correction.
    """

    def __init__(self):
        super().__init__(
            layer_id="ins_l3",
            layer_number=3,
            name="INS Dead Reckoning",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY,
                          LayerCapability.HEADING],
            description="Inertial navigation — gyroscope + accelerometer integration",
        )
        self._drift_rate = 0.001  # degrees per second drift
        self._accumulated_drift = 0.0
        self._last_read_time = 0.0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._accumulated_drift = 0.0
        self._last_read_time = time.time()
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def read(self) -> LayerReading:
        now = time.time()
        dt = now - self._last_read_time if self._last_read_time else 0.1
        self._last_read_time = now

        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            base_alt = getattr(self, '_sim_alt', 10.0)

            # INS accumulates drift over time
            self._accumulated_drift += self._drift_rate * dt
            noise_m = 2.0 + self._accumulated_drift
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 1.0)

            heading = getattr(self, '_sim_heading', 45.0) + np.random.normal(0, 0.5)
            velocity = getattr(self, '_sim_velocity', 0.0) + np.random.normal(0, 0.1)

            pos = Position(latitude=lat, longitude=lon, altitude=alt,
                           heading=heading % 360, velocity=max(0, velocity),
                           accuracy_m=noise_m, timestamp=now)
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                heading=heading % 360, velocity=velocity,
                self_confidence=max(0.3, 0.95 - self._accumulated_drift / 100),
                raw_data={"drift_m": self._accumulated_drift, "dt": dt},
            )
        raise NotImplementedError("Live INS requires IMU hardware")

    def reset_drift(self):
        self._accumulated_drift = 0.0

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


class BarometricAltitudeLayer(NavigationLayer):
    """Layer 11 — Barometric Altitude.

    Atmospheric pressure measurement for altitude determination.
    Biologically inspired by fish swim bladder pressure sensing.
    """

    def __init__(self):
        super().__init__(
            layer_id="baro_l11",
            layer_number=11,
            name="Barometric Altitude",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.ALTITUDE],
            bio_inspiration="Fish swim bladder pressure sensing",
            description="Atmospheric pressure altitude measurement",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self._simulated:
            base_alt = getattr(self, '_sim_alt', 10.0)
            alt = base_alt + np.random.normal(0, 5.0)  # ±5m typical
            pos = Position(latitude=0, longitude=0, altitude=alt,
                           accuracy_m=999, altitude_accuracy_m=5.0,
                           timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.7,
                raw_data={"pressure_hpa": 1013.25 - alt * 0.12,
                          "temperature_c": 25.0},
            )
        raise NotImplementedError("Live baro requires pressure sensor")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_alt = alt


class DopplerVelocityLayer(NavigationLayer):
    """Layer 12 — Doppler Velocity Radar.

    Measures velocity through Doppler shift of radar signals
    reflected from ground surface.
    """

    def __init__(self):
        super().__init__(
            layer_id="doppler_l12",
            layer_number=12,
            name="Doppler Velocity Radar",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.VELOCITY],
            description="Doppler radar ground velocity measurement",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.8

    def read(self) -> LayerReading:
        if self._simulated:
            velocity = getattr(self, '_sim_velocity', 50.0)
            vel = velocity + np.random.normal(0, 0.5)
            return LayerReading(
                layer_id=self.layer_id, velocity=max(0, vel),
                self_confidence=0.85,
                raw_data={"ground_speed_ms": vel, "signal_quality": 0.9},
            )
        raise NotImplementedError("Live Doppler requires radar hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_velocity = 50.0


class LaserDopplerLayer(NavigationLayer):
    """Layer 18 — Laser Doppler Velocity Sensor [NOVEL].

    3D velocity via laser Doppler velocimetry. Advanced Navigation
    demonstrated 29m error over 100km (0.03% error rate).
    """

    def __init__(self):
        super().__init__(
            layer_id="laserdop_l18",
            layer_number=18,
            name="Laser Doppler Velocity Sensor",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.VELOCITY],
            is_novel=True,
            description="Laser Doppler 3D velocity — 0.03% accuracy",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.95

    def read(self) -> LayerReading:
        if self._simulated:
            velocity = getattr(self, '_sim_velocity', 50.0)
            vel = velocity + np.random.normal(0, 0.015 * velocity)  # 0.03% error
            return LayerReading(
                layer_id=self.layer_id, velocity=max(0, vel),
                self_confidence=0.95,
                raw_data={"vx": vel * 0.7, "vy": vel * 0.7, "vz": 0.0},
            )
        raise NotImplementedError("Live laser Doppler requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_velocity = 50.0


class QuantumAtomicClockLayer(NavigationLayer):
    """Layer 27 — Quantum Optical Atomic Clock [NOVEL, UNDERWATER].

    Portable optical clocks (Rb/Yb), 20-200x more precise than GPS clocks.
    DARPA ROCkN: shoebox-sized, maintains timing for months without external signal.
    Improves accuracy across every other layer simultaneously.
    """

    def __init__(self):
        super().__init__(
            layer_id="qclock_l27",
            layer_number=27,
            name="Quantum Optical Atomic Clock",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.TIMING],
            is_novel=True,
            is_underwater=True,
            description="Quantum atomic clock — GPS-independent precision timing",
        )
        self._time_offset_ns = 0.0  # nanoseconds offset from true time

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._time_offset_ns = 0.0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.98  # Highest timing precision

    def read(self) -> LayerReading:
        if self._simulated:
            # Drift: ~1e-15 fractional frequency stability
            self._time_offset_ns += np.random.normal(0, 0.001)  # sub-picosecond drift
            precise_time = time.time() + self._time_offset_ns * 1e-9
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.99,
                raw_data={
                    "precise_time_ns": int(precise_time * 1e9),
                    "offset_ns": self._time_offset_ns,
                    "stability": 1e-15,
                    "atoms": "ytterbium",
                },
            )
        raise NotImplementedError("Live quantum clock requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class OpticFlowLayer(NavigationLayer):
    """Layer 43 — Optic Flow Velocity and Proximity Sensing [NOVEL].

    Velocity and proximity from visual feature motion across camera frames.
    Inspired by insect compound eye optic flow sensing.
    Works in textureless environments where Visual SLAM struggles.
    """

    def __init__(self):
        super().__init__(
            layer_id="opticflow_l43",
            layer_number=43,
            name="Optic Flow Velocity Sensing",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.VELOCITY],
            is_novel=True,
            bio_inspiration="Insect compound eye optic flow",
            description="Visual optic flow velocity and proximity",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def read(self) -> LayerReading:
        if self._simulated:
            velocity = getattr(self, '_sim_velocity', 10.0)
            vel = velocity + np.random.normal(0, 1.0)
            return LayerReading(
                layer_id=self.layer_id, velocity=max(0, vel),
                self_confidence=0.75,
                raw_data={"flow_px_s": vel * 100, "proximity_m": 5.0},
            )
        raise NotImplementedError("Live optic flow requires camera")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_velocity = 10.0


class NMRGyroscopeLayer(NavigationLayer):
    """Layer 57 — Nuclear Magnetic Resonance Gyroscope [NOVEL, UNDERWATER].

    Measures rotation via Larmor frequency shifts of nuclear magnetic moments.
    Different physical principle from INS — no drift accumulation.
    Quantum X Labs filed provisional patent March 2026.
    """

    def __init__(self):
        super().__init__(
            layer_id="nmrgyro_l57",
            layer_number=57,
            name="NMR Gyroscope",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            is_underwater=True,
            description="Nuclear magnetic resonance rotation sensing — drift-free",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.9

    def read(self) -> LayerReading:
        if self._simulated:
            heading = getattr(self, '_sim_heading', 45.0)
            h = heading + np.random.normal(0, 0.1)  # Very precise
            return LayerReading(
                layer_id=self.layer_id, heading=h % 360,
                self_confidence=0.92,
                raw_data={"larmor_freq_hz": 42.577e6, "drift_free": True},
            )
        raise NotImplementedError("Live NMR gyro requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0


class SERFGyroscopeLayer(NavigationLayer):
    """Layer 58 — SERF Atomic Spin Gyroscope [NOVEL, UNDERWATER].

    Spin-Exchange Relaxation Free gyroscope using alkali metal atoms.
    Chip-scale (150cc) by Northrop Grumman.
    Different mechanism from NMR — independent redundancy.
    """

    def __init__(self):
        super().__init__(
            layer_id="serfgyro_l58",
            layer_number=58,
            name="SERF Atomic Spin Gyroscope",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            is_underwater=True,
            description="SERF atomic spin rotation sensing — chip-scale",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.88

    def read(self) -> LayerReading:
        if self._simulated:
            heading = getattr(self, '_sim_heading', 45.0)
            h = heading + np.random.normal(0, 0.15)
            return LayerReading(
                layer_id=self.layer_id, heading=h % 360,
                self_confidence=0.9,
                raw_data={"spin_rate": 1e6, "volume_cc": 150},
            )
        raise NotImplementedError("Live SERF gyro requires hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_heading = 45.0
