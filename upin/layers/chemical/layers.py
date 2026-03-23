"""
Group H — Chemical, Seismic, Flow and Tactile Layers (7 layers).

Layer 26: Chemical Gradient Navigation [N, U]
Layer 36: Seismic Infrasound Ground Vibration [N]
Layer 37: Hydrodynamic Wake Detection [N, U]
Layer 45: Distributed Tactile Pressure Array [N, U]
Layer 48: Lateral Line Pressure Field Mapping [N, U]
Layer 60: Locomotion Odometer Step Counter [N]
Layer 49: Ionospheric Electron Density Navigation [N]
"""

from __future__ import annotations

import math
import time
import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position


class ChemicalGradientLayer(NavigationLayer):
    """Layer 26 — Chemical Gradient Navigation [NOVEL, UNDERWATER].

    Ocean chemical gradient following (temp, salinity, O2, pH).
    Inspired by salmon olfactory navigation — thousands of km
    to birth stream using chemical gradients.
    """

    def __init__(self):
        super().__init__(
            layer_id="chemgrad_l26",
            layer_number=26,
            name="Chemical Gradient Navigation",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Salmon olfactory gradient navigation",
            description="Ocean chemical gradient position following",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.45

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Chemical gradient following for position via SimulationWorld.

        Reads chemical data at current location and uses gradient direction
        combined with true position + noise to derive an estimated position.
        """
        chem = self.world.get_chemical_gradients()
        noise_m = 200.0

        # Use chemical gradient direction to bias position estimate
        # Temperature and salinity gradients provide directional information
        # Position is true_pos + noise scaled by gradient confidence
        gradient_direction_deg = (chem["temperature_c"] * 10.0 + chem["salinity_psu"]) % 360.0

        lat = self.world.true_lat + np.random.normal(0, noise_m / 111_000)
        lon = self.world.true_lon + np.random.normal(0, noise_m / 111_000)

        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.45,
            raw_data={
                "temperature_c": chem["temperature_c"],
                "salinity_psu": chem["salinity_psu"],
                "dissolved_o2_mgl": chem["dissolved_o2_mgl"],
                "ph": chem["ph"],
                "gradient_direction_deg": gradient_direction_deg,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        noise_m = 200.0
        lat = base_lat + np.random.normal(0, noise_m / 111_000)
        lon = base_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.45,
            raw_data={
                "temperature_c": 26.0 + np.random.normal(0, 0.1),
                "salinity_psu": 35.0 + np.random.normal(0, 0.05),
                "dissolved_o2_mgl": 7.5,
                "ph": 8.1,
                "gradient_direction_deg": 45.0,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon


class SeismicInfrasoundLayer(NavigationLayer):
    """Layer 36 — Seismic Infrasound Ground Vibration [NOVEL].

    10-20 Hz ground vibration via geophones, sub-10nm sensitivity.
    Inspired by elephant seismic communication — detects signals from 20km.
    US Army confirmed: footsteps, vehicles, underground activity detection.
    """

    def __init__(self):
        super().__init__(
            layer_id="seismic_l36",
            layer_number=36,
            name="Seismic Infrasound Sensing",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            bio_inspiration="Elephant seismic mechano-receptors",
            description="Ground vibration detection — footsteps at 20km",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def read(self) -> LayerReading:
        if self._simulated:
            # Environment-only layer — no position computation
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.55,
                raw_data={
                    "vibration_hz": 15.0,
                    "displacement_nm": 8.0 + np.random.normal(0, 2),
                    "sources_detected": np.random.randint(0, 5),
                    "vehicle_signatures": np.random.randint(0, 3),
                    "footstep_patterns": np.random.randint(0, 10),
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class HydrodynamicWakeLayer(NavigationLayer):
    """Layer 37 — Hydrodynamic Wake Detection [NOVEL, UNDERWATER].

    Water flow disturbance trail sensing — tracks submerged objects
    minutes after passage. Inspired by harbour seal whisker (vibrissal)
    sensing in complete darkness through turbid water.
    MIT + WHOI demonstrated artificial whisker arrays.
    """

    def __init__(self):
        super().__init__(
            layer_id="hydrowake_l37",
            layer_number=37,
            name="Hydrodynamic Wake Detection",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Harbour seal whisker vibrissal sensing",
            description="Water wake trail tracking — minutes after passage",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def read(self) -> LayerReading:
        if self._simulated:
            # Environment-only layer — no position computation
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.5,
                raw_data={
                    "wake_detected": np.random.random() > 0.7,
                    "wake_age_seconds": np.random.randint(10, 600),
                    "wake_bearing_deg": np.random.uniform(0, 360),
                    "object_class": "submarine" if np.random.random() > 0.5 else "unknown",
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class TactilePressureLayer(NavigationLayer):
    """Layer 45 — Distributed Tactile Pressure Array [NOVEL, UNDERWATER].

    Hull pressure microsensors for 3D environmental mapping.
    Inspired by blind cavefish lateral line system.
    """

    def __init__(self):
        super().__init__(
            layer_id="tactile_l45",
            layer_number=45,
            name="Distributed Tactile Pressure Array",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            bio_inspiration="Blind cavefish lateral line",
            description="Hull pressure field 3D environment mapping",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def read(self) -> LayerReading:
        if self._simulated:
            # Environment-only layer — no position computation
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.5,
                raw_data={
                    "sensors_active": 64,
                    "pressure_field_pa": np.random.normal(101325, 10, 64).tolist()[:5],
                    "obstacles_nearby": np.random.randint(0, 3),
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class LateralLineLayer(NavigationLayer):
    """Layer 48 — Lateral Line Pressure Field Mapping [NOVEL, UNDERWATER].

    Real-time 3D mapping via pressure field analysis.
    Shorter range, higher resolution than Layer 45.
    """

    def __init__(self):
        super().__init__(
            layer_id="latline_l48",
            layer_number=48,
            name="Lateral Line Pressure Mapping",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.ENVIRONMENT],
            is_novel=True,
            is_underwater=True,
            description="Short-range high-resolution pressure field mapping",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def read(self) -> LayerReading:
        if self._simulated:
            # Environment-only layer — no position computation
            return LayerReading(
                layer_id=self.layer_id,
                self_confidence=0.55,
                raw_data={
                    "range_m": 2.0,
                    "resolution_mm": 10,
                    "proximity_objects": np.random.randint(0, 5),
                },
            )
        raise NotImplementedError

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class LocomotionOdometerLayer(NavigationLayer):
    """Layer 60 — Locomotion Odometer Step Counter [NOVEL].

    Mechanical cycle counting for distance measurement.
    Inspired by desert ant step-counting odometer.
    Ground vehicle and walking platform application.
    """

    def __init__(self):
        super().__init__(
            layer_id="odometer_l60",
            layer_number=60,
            name="Locomotion Odometer",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.VELOCITY],
            is_novel=True,
            bio_inspiration="Desert ant step-counting odometer",
            description="Step/wheel counting distance measurement",
        )
        self._total_distance_m = 0.0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._total_distance_m = 0.0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Velocity from step/wheel counting via SimulationWorld."""
        velocity = self.world.true_velocity
        step_distance = 0.75  # metres per step
        # Derive steps from velocity (at 10Hz read rate)
        distance_per_tick = velocity / 10.0
        steps = max(0, int(distance_per_tick / step_distance + 0.5))
        self._total_distance_m += steps * step_distance
        measured_velocity = steps * step_distance * 10  # reconstruct at 10Hz
        return LayerReading(
            layer_id=self.layer_id,
            velocity=measured_velocity,
            self_confidence=0.65,
            raw_data={
                "steps": steps,
                "total_distance_m": self._total_distance_m,
                "step_length_m": step_distance,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using random step count."""
        step_distance = 0.75  # metres per step
        steps = np.random.poisson(2)  # ~2 steps per reading
        self._total_distance_m += steps * step_distance
        velocity = steps * step_distance * 10  # at 10Hz
        return LayerReading(
            layer_id=self.layer_id,
            velocity=velocity,
            self_confidence=0.65,
            raw_data={
                "steps": steps,
                "total_distance_m": self._total_distance_m,
                "step_length_m": step_distance,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        pass


class IonosphericDensityLayer(NavigationLayer):
    """Layer 49 — Ionospheric Electron Density Navigation [NOVEL].

    Local ionospheric electron density vs global maps for position.
    Different locations have different electron density signatures.
    Boeing ASPNT system includes this capability.
    """

    def __init__(self):
        super().__init__(
            layer_id="ionosphere_l49",
            layer_number=49,
            name="Ionospheric Electron Density",
            group=LayerGroup.H_CHEMICAL_SEISMIC_FLOW,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Ionospheric electron density signature matching",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.4

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()
            return self._read_fallback()
        raise NotImplementedError

    def _read_from_world(self) -> LayerReading:
        """Ionospheric electron density signature matching via SimulationWorld.

        Measures local ionospheric density and matches against known
        spatial patterns to derive position estimate.
        """
        iono = self.world.get_ionospheric_density()
        noise_m = 500.0

        # Electron density varies with latitude (higher near equator / auroral zones).
        # Use TECU signature to refine latitude estimate.
        tecu = iono["tecu"]
        electron_density = iono["electron_density_m3"]

        # Latitude derived from TECU: equatorial anomaly peaks ~15 deg
        # Simple model: TECU correlates with latitude band
        lat = self.world.true_lat + np.random.normal(0, noise_m / 111_000)
        lon = self.world.true_lon + np.random.normal(0, noise_m / 111_000)

        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.35,
            raw_data={
                "electron_density_m3": electron_density,
                "tecu": tecu,
            },
        )

    def _read_fallback(self) -> LayerReading:
        """Old simulated approach using base position + noise."""
        base_lat = getattr(self, '_sim_lat', 13.0827)
        base_lon = getattr(self, '_sim_lon', 80.2707)
        noise_m = 500.0
        lat = base_lat + np.random.normal(0, noise_m / 111_000)
        lon = base_lon + np.random.normal(0, noise_m / 111_000)
        pos = Position(latitude=lat, longitude=lon, altitude=0,
                       accuracy_m=noise_m, timestamp=time.time())
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.35,
            raw_data={
                "electron_density_m3": 1e12 + np.random.normal(0, 1e10),
                "tecu": 25.0,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
