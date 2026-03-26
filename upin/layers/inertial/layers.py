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

import math
import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


# ── Earth / physics constants ─────────────────────────────────
R_EARTH = 6_371_000.0          # metres
DEG_PER_M_LAT = 1.0 / 111_000.0   # approximate degrees-latitude per metre
ISA_P0 = 1013.25              # standard sea-level pressure (hPa)


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
        # Sensor error parameters
        self._accel_bias = 0.0          # m/s² — slowly varying accelerometer bias
        self._accel_noise_std = 0.05    # m/s² — white noise on accelerometer
        self._gyro_drift_rate = 0.001   # degrees/s — gyroscope drift rate
        self._accel_bias_walk = 1e-4    # m/s² per second — bias random walk

        # Internal dead-reckoned state
        self._dr_lat = 0.0
        self._dr_lon = 0.0
        self._dr_alt = 0.0
        self._dr_heading = 0.0
        self._dr_vn = 0.0              # north velocity m/s
        self._dr_ve = 0.0              # east velocity m/s
        self._dr_vd = 0.0              # down velocity m/s

        # Accumulated drift tracking
        self._accumulated_drift = 0.0   # metres of total positional drift
        self._heading_drift = 0.0       # degrees of accumulated heading drift
        self._last_read_time = 0.0
        self._initialized_state = False

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._accumulated_drift = 0.0
        self._heading_drift = 0.0
        self._accel_bias = 0.0
        self._initialized_state = False
        self._last_read_time = time.time()
        return True

    def get_accuracy_rating(self) -> float:
        return 0.75

    def _init_state_from_world(self):
        """Seed internal state from world ground truth (first fix)."""
        w = self.world
        self._dr_lat = w.true_lat
        self._dr_lon = w.true_lon
        self._dr_alt = w.true_alt
        self._dr_heading = w.true_heading
        self._dr_vn = w.true_vn
        self._dr_ve = w.true_ve
        self._dr_vd = w.true_vd
        self._initialized_state = True

    def read(self) -> LayerReading:
        now = time.time()
        dt = now - self._last_read_time if self._last_read_time else 0.1
        dt = min(dt, 2.0)  # clamp to avoid huge jumps
        self._last_read_time = now

        # ── World-driven physics simulation ──
        if self.world is not None:
            if not self._initialized_state:
                self._init_state_from_world()

            w = self.world

            # 1. Read true velocity from world (what the accelerometer
            #    would integrate to if perfect)
            true_vn = w.true_vn
            true_ve = w.true_ve
            true_vd = w.true_vd

            # 2. Accelerometer: compute acceleration from velocity change
            #    and add noise + bias
            self._accel_bias += np.random.normal(0, self._accel_bias_walk * dt)
            accel_noise_n = np.random.normal(0, self._accel_noise_std) + self._accel_bias
            accel_noise_e = np.random.normal(0, self._accel_noise_std) + self._accel_bias
            accel_noise_d = np.random.normal(0, self._accel_noise_std * 0.5)

            # Measured acceleration = true acceleration + noise
            # True acceleration ≈ (true_v - dr_v) / dt, but we don't have
            # previous true_v. Instead, use world velocity directly with noise.
            measured_vn = true_vn + accel_noise_n * dt
            measured_ve = true_ve + accel_noise_e * dt
            measured_vd = true_vd + accel_noise_d * dt

            # 3. Integrate noisy velocity to update position
            self._dr_vn = measured_vn
            self._dr_ve = measured_ve
            self._dr_vd = measured_vd

            # Position integration (dead reckoning step)
            self._dr_lat += (self._dr_vn * dt / R_EARTH) * (180.0 / math.pi)
            cos_lat = math.cos(math.radians(self._dr_lat))
            if abs(cos_lat) > 1e-10:
                self._dr_lon += (self._dr_ve * dt / (R_EARTH * cos_lat)) * (180.0 / math.pi)
            self._dr_alt -= self._dr_vd * dt

            # 4. Gyroscope drift on heading
            gyro_noise = np.random.normal(0, 0.05)  # instantaneous noise
            self._heading_drift += self._gyro_drift_rate * dt
            self._dr_heading = w.true_heading + self._heading_drift + gyro_noise
            self._dr_heading %= 360.0

            # 5. Track accumulated positional drift (for confidence calc)
            lat_err_m = (self._dr_lat - w.true_lat) / DEG_PER_M_LAT
            lon_err_m = (self._dr_lon - w.true_lon) / (DEG_PER_M_LAT * max(cos_lat, 1e-10))
            self._accumulated_drift = math.sqrt(lat_err_m ** 2 + lon_err_m ** 2)

            velocity = math.sqrt(self._dr_vn ** 2 + self._dr_ve ** 2)
            accuracy_m = max(2.0, self._accumulated_drift)

            pos = Position(
                latitude=self._dr_lat,
                longitude=self._dr_lon,
                altitude=self._dr_alt,
                heading=self._dr_heading,
                velocity=velocity,
                accuracy_m=accuracy_m,
                timestamp=now,
            )
            return LayerReading(
                layer_id=self.layer_id,
                position=pos,
                heading=self._dr_heading,
                velocity=velocity,
                self_confidence=max(0.3, 0.95 - self._accumulated_drift / 100),
                raw_data={
                    "drift_m": self._accumulated_drift,
                    "heading_drift_deg": self._heading_drift,
                    "accel_bias": self._accel_bias,
                    "dt": dt,
                },
            )

        # ── Legacy fallback: fixed simulated position ──
        if self._simulated:
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            base_alt = getattr(self, '_sim_alt', 10.0)

            # INS accumulates drift over time
            self._accumulated_drift += self._gyro_drift_rate * dt * 111_000
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
        """Reset accumulated drift (e.g. after external aiding correction)."""
        self._accumulated_drift = 0.0
        self._heading_drift = 0.0
        self._accel_bias = 0.0
        if self.world is not None:
            self._init_state_from_world()

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
        # Sensor noise parameters
        self._pressure_noise_hpa = 0.3   # typical MEMS baro noise
        self._temperature_c = 15.0       # assumed ISA temperature

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            # 1. Read raw barometric pressure from world
            true_pressure = self.world.get_barometric_pressure()

            # 2. Add sensor noise
            measured_pressure = true_pressure + np.random.normal(0, self._pressure_noise_hpa)

            # 3. Convert pressure to altitude using ISA hypsometric formula
            #    alt = 44330 * (1 - (P / P0) ^ 0.1903)
            ratio = measured_pressure / ISA_P0
            baro_alt = 44330.0 * (1.0 - math.pow(ratio, 0.1903))

            # Altitude accuracy depends on pressure noise
            # d(alt)/d(P) ≈ -44330 * 0.1903 * (P/P0)^(-0.8097) / P0
            # Roughly ~8 m per hPa near sea level
            alt_accuracy_m = abs(self._pressure_noise_hpa * 8.0)

            pos = Position(
                latitude=0.0,
                longitude=0.0,
                altitude=baro_alt,
                accuracy_m=999.0,
                altitude_accuracy_m=alt_accuracy_m,
                timestamp=now,
            )
            return LayerReading(
                layer_id=self.layer_id,
                position=pos,
                self_confidence=0.7,
                raw_data={
                    "pressure_hpa": measured_pressure,
                    "temperature_c": self._temperature_c,
                    "baro_alt_m": baro_alt,
                },
            )

        # ── Legacy fallback ──
        if self._simulated:
            base_alt = getattr(self, '_sim_alt', 10.0)
            alt = base_alt + np.random.normal(0, 5.0)  # ±5m typical
            pos = Position(latitude=0, longitude=0, altitude=alt,
                           accuracy_m=999, altitude_accuracy_m=5.0,
                           timestamp=now)
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
        # Radar parameters
        self._transmit_freq_ghz = 24.0   # K-band radar
        self._velocity_noise_std = 0.5   # m/s noise floor

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.8

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            # 1. Read true ground speed from world
            true_vel = self.world.true_velocity

            # 2. Compute Doppler shift: fd = 2 * v * f0 / c
            #    Then recover velocity from measured Doppler with noise
            c = 3e8  # speed of light m/s
            f0 = self._transmit_freq_ghz * 1e9
            true_doppler_hz = 2.0 * true_vel * f0 / c

            # 3. Add measurement noise to Doppler frequency
            doppler_noise_hz = np.random.normal(0, self._velocity_noise_std * 2 * f0 / c)
            measured_doppler_hz = true_doppler_hz + doppler_noise_hz

            # 4. Recover velocity from measured Doppler
            measured_vel = measured_doppler_hz * c / (2.0 * f0)

            signal_quality = min(1.0, 0.95 - 0.001 * abs(measured_vel - true_vel))

            return LayerReading(
                layer_id=self.layer_id,
                velocity=max(0.0, measured_vel),
                self_confidence=0.85,
                raw_data={
                    "ground_speed_ms": measured_vel,
                    "doppler_hz": measured_doppler_hz,
                    "signal_quality": max(0.0, signal_quality),
                    "transmit_freq_ghz": self._transmit_freq_ghz,
                },
            )

        # ── Legacy fallback ──
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
        # Laser parameters
        self._wavelength_nm = 1550.0     # eye-safe infrared
        self._error_fraction = 0.0003    # 0.03% error

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.95

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            w = self.world

            # 1. Read true 3D velocity components from world
            true_vn = w.true_vn
            true_ve = w.true_ve
            true_vd = w.true_vd
            true_speed = w.true_velocity

            # 2. Laser Doppler measures each axis independently
            #    with 0.03% proportional error
            noise_n = np.random.normal(0, abs(true_vn) * self._error_fraction + 0.001)
            noise_e = np.random.normal(0, abs(true_ve) * self._error_fraction + 0.001)
            noise_d = np.random.normal(0, abs(true_vd) * self._error_fraction + 0.001)

            meas_vn = true_vn + noise_n
            meas_ve = true_ve + noise_e
            meas_vd = true_vd + noise_d

            measured_speed = math.sqrt(meas_vn ** 2 + meas_ve ** 2 + meas_vd ** 2)

            return LayerReading(
                layer_id=self.layer_id,
                velocity=max(0.0, measured_speed),
                self_confidence=0.95,
                raw_data={
                    "vx": meas_ve,
                    "vy": meas_vn,
                    "vz": meas_vd,
                    "speed_ms": measured_speed,
                    "wavelength_nm": self._wavelength_nm,
                    "error_pct": self._error_fraction * 100,
                },
            )

        # ── Legacy fallback ──
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
        # Clock physics parameters
        self._fractional_stability = 1e-15   # Allan deviation at 1s
        self._time_offset_ns = 0.0           # nanoseconds offset from true time
        self._drift_rate_ns_per_s = 0.0      # slow drift (sub-picosecond/s)

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._time_offset_ns = 0.0
        self._drift_rate_ns_per_s = 0.0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.98  # Highest timing precision

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            # 1. Sub-picosecond random walk drift per read
            #    Fractional frequency stability 1e-15 means ~1e-15 s/s drift
            self._drift_rate_ns_per_s += np.random.normal(0, 1e-6)  # pico-drift walk
            self._time_offset_ns += self._drift_rate_ns_per_s * 0.001  # sub-ps step
            self._time_offset_ns += np.random.normal(0, 0.001)  # white phase noise

            # 2. Precise time = true time + accumulated offset
            precise_time = now + self._time_offset_ns * 1e-9

            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.99,
                raw_data={
                    "precise_time_ns": int(precise_time * 1e9),
                    "offset_ns": self._time_offset_ns,
                    "drift_rate_ns_per_s": self._drift_rate_ns_per_s,
                    "stability": self._fractional_stability,
                    "atoms": "ytterbium",
                    "elapsed_s": self.world.elapsed,
                },
            )

        # ── Legacy fallback ──
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
        # Optic flow parameters
        self._focal_length_px = 800.0    # camera focal length in pixels
        self._noise_fraction = 0.10      # ~10% velocity error

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            w = self.world

            # 1. True velocity from world
            true_vel = w.true_velocity
            true_alt = w.true_alt

            # 2. Optic flow rate: flow_px_s = v * focal_length / altitude
            #    (for downward-looking camera)
            ground_height = max(true_alt, 1.0)  # avoid division by zero
            true_flow = true_vel * self._focal_length_px / ground_height

            # 3. Add noise (~10% of velocity, plus texture-dependent noise)
            flow_noise = np.random.normal(0, true_flow * self._noise_fraction + 1.0)
            measured_flow = true_flow + flow_noise

            # 4. Recover velocity from measured flow
            measured_vel = measured_flow * ground_height / self._focal_length_px

            # 5. Proximity estimate from flow divergence
            proximity_m = ground_height + np.random.normal(0, ground_height * 0.05)

            return LayerReading(
                layer_id=self.layer_id,
                velocity=max(0.0, measured_vel),
                self_confidence=0.75,
                raw_data={
                    "flow_px_s": measured_flow,
                    "proximity_m": max(0.1, proximity_m),
                    "ground_height_m": ground_height,
                    "focal_length_px": self._focal_length_px,
                },
            )

        # ── Legacy fallback ──
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
        # NMR physics parameters
        self._larmor_freq_hz = 42.577e6   # ¹H gyromagnetic ratio × B₀
        self._heading_noise_std = 0.1     # degrees — measurement noise
        self._b0_field_t = 1.0            # Tesla — applied magnetic field

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.9

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            # 1. True heading from world
            true_heading = self.world.true_heading

            # 2. NMR measures heading via Larmor precession frequency shift
            #    The gyroscope detects rotation through changes in the
            #    nuclear spin precession phase. Drift-free because the
            #    Larmor frequency is an absolute reference.
            larmor_shift_hz = np.random.normal(0, 0.01)  # tiny freq noise
            measured_larmor = self._larmor_freq_hz + larmor_shift_hz

            # 3. Add 0.1° heading noise (white, no drift accumulation)
            heading_noise = np.random.normal(0, self._heading_noise_std)
            measured_heading = (true_heading + heading_noise) % 360.0

            return LayerReading(
                layer_id=self.layer_id,
                heading=measured_heading,
                self_confidence=0.92,
                raw_data={
                    "larmor_freq_hz": measured_larmor,
                    "b0_field_t": self._b0_field_t,
                    "drift_free": True,
                    "heading_noise_deg": self._heading_noise_std,
                },
            )

        # ── Legacy fallback ──
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
        # SERF physics parameters
        self._spin_rate_hz = 1e6          # alkali atom spin precession rate
        self._heading_noise_std = 0.15    # degrees — slightly noisier than NMR
        self._cell_volume_cc = 150.0      # chip-scale form factor
        self._alkali_metal = "rubidium"

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.88

    def read(self) -> LayerReading:
        now = time.time()

        # ── World-driven physics simulation ──
        if self.world is not None:
            # 1. True heading from world
            true_heading = self.world.true_heading

            # 2. SERF measures rotation through atomic spin polarisation.
            #    In the SERF regime, spin-exchange collisions are suppressed,
            #    allowing ultra-sensitive rotation measurement.
            spin_noise = np.random.normal(0, 10.0)  # Hz noise on spin rate
            measured_spin = self._spin_rate_hz + spin_noise

            # 3. Add 0.15° heading noise
            heading_noise = np.random.normal(0, self._heading_noise_std)
            measured_heading = (true_heading + heading_noise) % 360.0

            return LayerReading(
                layer_id=self.layer_id,
                heading=measured_heading,
                self_confidence=0.9,
                raw_data={
                    "spin_rate": measured_spin,
                    "volume_cc": self._cell_volume_cc,
                    "alkali": self._alkali_metal,
                    "heading_noise_deg": self._heading_noise_std,
                },
            )

        # ── Legacy fallback ──
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


class RadarAltimeterLayer(NavigationLayer):
    """Radar ground-return altimeter for aerial platforms.

    Measures true height above terrain using pulse return timing.
    Bio-inspired by barn owl hunting — precise height from sound return.
    """

    def __init__(self):
        super().__init__(
            layer_id="radar_alt_b09",
            layer_number=63,
            name="Radar Altimeter",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.ALTITUDE],
            bio_inspiration="Barn owl hunting height estimation",
            description="Radar pulse return altitude for aerial platforms",
        )
        self._altitude_noise_m = 0.5

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.90

    def read(self) -> LayerReading:
        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
            true_alt = getattr(self.world, "true_alt", 100.0)
            measured_alt = true_alt + np.random.normal(0, self._altitude_noise_m)
            pos = Position(
                latitude=true_lat, longitude=true_lon,
                altitude=measured_alt,
                accuracy_m=self._altitude_noise_m * 2, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.96,
                raw_data={"altitude_m": measured_alt, "terrain_clearance_m": measured_alt},
            )

        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            base_alt = getattr(self, "_sim_alt", 100.0)
            measured_alt = base_alt + np.random.normal(0, self._altitude_noise_m)
            pos = Position(
                latitude=base_lat, longitude=base_lon,
                altitude=measured_alt,
                accuracy_m=self._altitude_noise_m * 2, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.96,
                raw_data={"altitude_m": measured_alt, "terrain_clearance_m": measured_alt},
            )
        raise NotImplementedError("Live radar altimeter requires RF hardware")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


class DepthPressureSensorLayer(NavigationLayer):
    """Underwater depth positioning via hydrostatic pressure measurement.

    Gives submarines precise depth without any active emission.
    Bio-inspired by sperm whale deep-dive pressure adaptation.
    """

    def __init__(self):
        super().__init__(
            layer_id="depth_pressure_b10",
            layer_number=64,
            name="Depth Pressure Sensor",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.ALTITUDE],
            is_underwater=True,
            bio_inspiration="Sperm whale deep-dive pressure sensing",
            description="Passive hydrostatic pressure depth for submerged platforms",
        )
        self._pressure_noise_kpa = 0.2

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.92

    def read(self) -> LayerReading:
        if self.world is not None:
            true_lat = self.world.true_lat
            true_lon = self.world.true_lon
            depth_m = getattr(self.world, "depth_m", 0.0)
            pressure_kpa = 101.325 + (depth_m * 9.81)
            measured_pressure = pressure_kpa + np.random.normal(0, self._pressure_noise_kpa)
            depth_from_pressure = (measured_pressure - 101.325) / 9.81
            depth_error_m = abs(depth_from_pressure - depth_m)
            pos = Position(
                latitude=true_lat, longitude=true_lon, altitude=-depth_from_pressure,
                accuracy_m=max(0.1, depth_error_m), timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.98,
                raw_data={"pressure_kpa": measured_pressure, "depth_m": depth_from_pressure},
            )

        if self._simulated:
            base_lat = getattr(self, "_sim_lat", 13.0827)
            base_lon = getattr(self, "_sim_lon", 80.2707)
            measured_pressure = 101.325 + np.random.normal(0, self._pressure_noise_kpa)
            depth_from_pressure = (measured_pressure - 101.325) / 9.81
            pos = Position(
                latitude=base_lat, longitude=base_lon, altitude=-depth_from_pressure,
                accuracy_m=0.1, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.98,
                raw_data={"pressure_kpa": measured_pressure, "depth_m": depth_from_pressure},
            )
        raise NotImplementedError("Live depth sensor requires pressure transducer")

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
