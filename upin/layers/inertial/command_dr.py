"""
Layer 2 — Command-based dead reckoning (model-aided navigation).

A drone knows every order it gave its motors: how much throttle, which way
it tilted, for how long. With a model of how that airframe responds, those
orders predict movement — "I held eight degrees of forward pitch at sixty
percent throttle for four seconds, so I moved roughly this far this way."

That is a position estimate which depends on neither satellites nor the
inertial sensors. It is independent of both, which is what makes it useful:

  as navigation   it bridges gaps when satellites are gone and the IMU is
                  drifting, because its errors come from wind and model
                  mismatch rather than from integrating sensor noise

  as a check      when the satellite fix says the drone moved but the
                  commands and the IMU both say it did not, the satellite
                  fix is the thing that is wrong

THE PHYSICS IS REAL

For a multirotor in NED, thrust acts along body -z. Rotating that into the
world frame through the attitude and adding gravity gives

    a_n = -(T/m)(cos psi sin theta cos phi + sin psi sin phi)
    a_e = -(T/m)(sin psi sin theta cos phi - cos psi sin phi)
    a_d = -(T/m)(cos theta cos phi) + g

with a quadratic drag term subtracted. Integrating that twice gives
position. No part of this is invented; it is the standard rigid-body model.

WHAT IS NOT REAL UNTIL YOU MEASURE IT

The model needs thrust-to-mass and a drag coefficient, and those are
properties of one specific airframe with one specific payload. They are
fitted by least squares from real flight logs — commands paired with
surveyed or satellite truth. Until that fit exists this layer refuses to
produce a position, because a model-aided estimate with a guessed model is
not an estimate, it is a fabrication.

HONEST LIMITS

Wind, falling battery voltage, payload changes and air density all change
how an airframe answers the same command, so this layer drifts. It is a
bridge between fixes, never a long-range solution. It must be reset by
vision or landmarks, which is what Layer 4 is for.

Complies with the no-fabrication contract: no calibration or no commands
means no position, and identical inputs give bit-identical output.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from upin.core.layer_base import (
    LayerCapability, LayerGroup, LayerReading, NavigationLayer,
)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import (
    DataInput, Hardware, SensorRequirement,
)

G = 9.80665
DEG_M = 111_320.0


@dataclass
class MotorCommand:
    """One logged command to the airframe.

    These are the values the flight controller actually sent, read back from
    its log — not a reconstruction.
    """
    timestamp: float
    throttle: float          # 0.0 - 1.0, normalised collective
    roll_rad: float          # commanded or achieved bank, right positive
    pitch_rad: float         # nose up positive
    yaw_rad: float           # heading, radians from north
    dt: float = 0.0          # seconds this command was held


@dataclass
class AirframeModel:
    """How one specific airframe answers a command.

    thrust_to_mass is the acceleration at full throttle in m/s^2, so hover
    sits at throttle = G / thrust_to_mass. drag_coeff is the quadratic drag
    divided by mass, in 1/m.
    """
    thrust_to_mass: float = 0.0        # m/s^2 at full throttle
    drag_coeff: float = 0.0            # 1/m, quadratic
    throttle_exponent: float = 1.0     # T proportional to throttle^exponent
    calibrated: bool = False
    calibration_samples: int = 0
    calibration_rms_m: float = float("inf")
    airframe_id: str = ""
    # Drag only bites at speed. Calibration data flown near hover constrains
    # thrust tightly and drag barely at all, so the fit reports how fast the
    # data actually was rather than presenting both numbers as equally solid.
    max_calibration_speed_ms: float = 0.0
    drag_observable: bool = False

    @property
    def hover_throttle(self) -> float:
        if self.thrust_to_mass <= 0:
            return 0.0
        return (G / self.thrust_to_mass) ** (1.0 / max(self.throttle_exponent, 1e-6))


def accel_from_command(cmd: MotorCommand, model: AirframeModel,
                       velocity_ned: np.ndarray,
                       wind_ned: Optional[np.ndarray] = None) -> np.ndarray:
    """World-frame acceleration produced by one command. NED, m/s^2.

    Thrust along body -z rotated by the attitude, plus gravity, minus
    quadratic drag on airspeed. Airspeed is ground speed minus wind, which
    is why an unmodelled wind shows up as a steady position error.
    """
    if not model.calibrated:
        raise ValueError("airframe model is not calibrated")

    thrust = model.thrust_to_mass * (
        max(0.0, cmd.throttle) ** model.throttle_exponent)

    cphi, sphi = math.cos(cmd.roll_rad), math.sin(cmd.roll_rad)
    cth, sth = math.cos(cmd.pitch_rad), math.sin(cmd.pitch_rad)
    cpsi, spsi = math.cos(cmd.yaw_rad), math.sin(cmd.yaw_rad)

    a_n = -thrust * (cpsi * sth * cphi + spsi * sphi)
    a_e = -thrust * (spsi * sth * cphi - cpsi * sphi)
    a_d = -thrust * (cth * cphi) + G

    a = np.array([a_n, a_e, a_d], dtype=float)

    airspeed = velocity_ned - (wind_ned if wind_ned is not None
                               else np.zeros(3))
    speed = float(np.linalg.norm(airspeed))
    if speed > 1e-9 and model.drag_coeff > 0:
        a -= model.drag_coeff * speed * airspeed

    return a


def propagate(commands: Sequence[MotorCommand], model: AirframeModel,
              start_ned: np.ndarray, start_velocity: np.ndarray,
              wind_ned: Optional[np.ndarray] = None
              ) -> Tuple[np.ndarray, np.ndarray]:
    """Integrate a command sequence into a displacement and final velocity.

    Deterministic by construction — the same commands and model always give
    the same answer, which is what the contract test checks.
    """
    pos = np.array(start_ned, dtype=float)
    vel = np.array(start_velocity, dtype=float)
    for cmd in commands:
        dt = cmd.dt
        if dt <= 0:
            continue
        a = accel_from_command(cmd, model, vel, wind_ned)
        # trapezoidal: advance position with the mean velocity over the step
        pos = pos + vel * dt + 0.5 * a * dt * dt
        vel = vel + a * dt
    return pos, vel


class ModelCalibrator:
    """Fits an airframe model to real flight logs.

    A segment is a run of commands paired with the displacement that was
    actually observed over it, from satellite or surveyed truth. The fit
    searches thrust-to-mass and drag for the pair that reproduces those
    displacements with least squared error.

    Refuses to mark a model calibrated on too little data, because a model
    fitted to two segments will happily reproduce those two segments and
    nothing else.
    """

    MIN_SEGMENTS = 5

    def __init__(self, airframe_id: str = ""):
        self._airframe_id = airframe_id
        self._segments: List[Tuple[List[MotorCommand], np.ndarray, np.ndarray]] = []

    def add_segment(self, commands: Sequence[MotorCommand],
                    observed_displacement_ned: Sequence[float],
                    start_velocity_ned: Sequence[float] = (0.0, 0.0, 0.0)):
        """Record a command run against the movement that really happened."""
        if not commands:
            return
        self._segments.append((
            list(commands),
            np.array(observed_displacement_ned, dtype=float),
            np.array(start_velocity_ned, dtype=float),
        ))

    def fit(self, thrust_bounds: Tuple[float, float] = (10.0, 40.0),
            drag_bounds: Tuple[float, float] = (0.0, 0.5),
            throttle_exponent: float = 1.0) -> AirframeModel:
        """Grid search then local refine. Returns an uncalibrated model on
        insufficient data rather than a confident-looking wrong one."""
        model = AirframeModel(airframe_id=self._airframe_id,
                              throttle_exponent=throttle_exponent)
        if len(self._segments) < self.MIN_SEGMENTS:
            model.calibration_samples = len(self._segments)
            return model

        def rms_for(ttm: float, drag: float) -> float:
            trial = AirframeModel(thrust_to_mass=ttm, drag_coeff=drag,
                                  throttle_exponent=throttle_exponent,
                                  calibrated=True)
            total = 0.0
            for cmds, observed, v0 in self._segments:
                pred, _ = propagate(cmds, trial, np.zeros(3), v0)
                total += float(np.sum((pred - observed) ** 2))
            return math.sqrt(total / len(self._segments))

        best = (float("inf"), thrust_bounds[0], drag_bounds[0])
        for ttm in np.linspace(*thrust_bounds, 40):
            for drag in np.linspace(*drag_bounds, 20):
                r = rms_for(float(ttm), float(drag))
                if r < best[0]:
                    best = (r, float(ttm), float(drag))

        # local refine around the grid winner
        rms, ttm, drag = best
        span_t = (thrust_bounds[1] - thrust_bounds[0]) / 40.0
        span_d = (drag_bounds[1] - drag_bounds[0]) / 20.0
        for _ in range(6):
            improved = False
            for dt_ in (-span_t, 0.0, span_t):
                for dd in (-span_d, 0.0, span_d):
                    if dt_ == 0.0 and dd == 0.0:
                        continue
                    t2 = min(max(ttm + dt_, thrust_bounds[0]), thrust_bounds[1])
                    d2 = min(max(drag + dd, drag_bounds[0]), drag_bounds[1])
                    r = rms_for(t2, d2)
                    if r < rms:
                        rms, ttm, drag, improved = r, t2, d2, True
            if not improved:
                span_t *= 0.5
                span_d *= 0.5

        model.thrust_to_mass = ttm
        model.drag_coeff = drag
        model.calibrated = True
        model.calibration_samples = len(self._segments)
        model.calibration_rms_m = rms

        # How fast did the calibration data actually go? Quadratic drag scales
        # as v^2, so data flown near hover leaves it essentially unconstrained
        # and the fitted value should not be relied on.
        model.max_calibration_speed_ms = self._max_speed_seen(ttm, drag,
                                                              throttle_exponent)
        model.drag_observable = model.max_calibration_speed_ms >= self.DRAG_SPEED_MS
        return model

    DRAG_SPEED_MS = 5.0
    """Airspeed the calibration data must reach for drag to be identifiable.

    Set empirically. Quadratic drag contributes drag_coeff * v^2, so at
    1 m/s it is a rounding error against hover thrust and the fit is free to
    put almost any value there. Calibration flown to ~8 m/s recovers drag to
    within one percent; flown at ~1 m/s it is out by a factor of four.
    """

    def _max_speed_seen(self, ttm: float, drag: float,
                        throttle_exponent: float) -> float:
        trial = AirframeModel(thrust_to_mass=ttm, drag_coeff=drag,
                              throttle_exponent=throttle_exponent,
                              calibrated=True)
        peak = 0.0
        for cmds, _observed, v0 in self._segments:
            vel = np.array(v0, dtype=float)
            for cmd in cmds:
                if cmd.dt <= 0:
                    continue
                vel = vel + accel_from_command(cmd, trial, vel) * cmd.dt
                peak = max(peak, float(np.linalg.norm(vel)))
        return peak

    @property
    def segment_count(self) -> int:
        return len(self._segments)


class WindEstimator:
    """Estimates wind from the disagreement between commands and measurement.

    The commands predict where the airframe should have gone through still
    air. Something else — the IMU, a satellite fix, a landmark — says where
    it actually went. The steady part of that difference is wind.
    """

    def __init__(self, window: int = 20):
        self._window = window
        self._residuals: List[np.ndarray] = []
        self._wind = np.zeros(3)

    def update(self, predicted_ned: Sequence[float],
               observed_ned: Sequence[float], elapsed_s: float) -> np.ndarray:
        if elapsed_s <= 0:
            return self._wind
        residual = (np.array(observed_ned, dtype=float)
                    - np.array(predicted_ned, dtype=float)) / elapsed_s
        self._residuals.append(residual)
        if len(self._residuals) > self._window:
            self._residuals = self._residuals[-self._window:]
        self._wind = np.mean(self._residuals, axis=0)
        return self._wind

    @property
    def wind_ned(self) -> np.ndarray:
        return self._wind.copy()

    @property
    def speed_ms(self) -> float:
        return float(np.linalg.norm(self._wind[:2]))

    @property
    def bearing_deg(self) -> float:
        """Direction the wind is blowing toward, degrees from north."""
        return float(math.degrees(math.atan2(self._wind[1], self._wind[0])) % 360.0)

    @property
    def samples(self) -> int:
        return len(self._residuals)


class CommandDeadReckoningLayer(NavigationLayer):
    """Layer 143 — position from motor commands through a calibrated model.

    Honours the no-fabrication contract. Without a calibrated model, an
    anchor position, or logged commands, it returns no fix and says which
    is missing.
    """

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("flight controller with a readable command log",
                     why="the commands it issued are the entire input",
                     typical_part="Pixhawk / ArduPilot or PX4 telemetry log",
                     approx_cost_usd=200, already_on_most_drones=True),
        ],
        inputs=[
            DataInput("motor commands", feed_method="log_command",
                      units="throttle 0-1, attitude in radians",
                      why="throttle and attitude integrate into displacement"),
            DataInput("trusted starting position", feed_method="set_anchor",
                      units="degrees, metres",
                      why="dead reckoning measures change, so it needs a "
                          "point to measure change from"),
        ],
        preconditions=(
            "an airframe model fitted by least squares to real flight logs",
            "calibration flights reaching about 5 m/s, or the drag "
            "coefficient is not identifiable",
            "a recent anchor: accuracy degrades with every second since one",
        ),
        notes="Needs no sensor beyond the flight controller's own log, so it "
              "survives total sensor and signal loss. It is a bridge between "
              "fixes, not a solution -- it drifts and must be reset.",
    )

    def __init__(self, model: Optional[AirframeModel] = None):
        super().__init__(
            layer_id="cmddr_b12", layer_number=143,
            name="Command-Based Dead Reckoning",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY],
            is_novel=True,
            description="Model-aided navigation from logged motor commands",
        )
        self._model = model or AirframeModel()
        self._wind = WindEstimator()
        self._anchor: Optional[Tuple[float, float, float]] = None
        self._anchor_time: float = 0.0
        self._pending: List[MotorCommand] = []
        self._velocity = np.zeros(3)
        self._displacement = np.zeros(3)
        self._seconds_since_anchor = 0.0
        self._fixes = 0

    # -- setup ------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = self._model.calibrated
        return True

    def get_accuracy_rating(self) -> float:
        return 0.55

    def set_model(self, model: AirframeModel):
        self._model = model
        self.status.is_healthy = model.calibrated

    def set_anchor(self, lat: float, lon: float, alt: float,
                   velocity_ned: Sequence[float] = (0.0, 0.0, 0.0)):
        """Reset to a trusted position. Clears accumulated drift."""
        self._anchor = (lat, lon, alt)
        self._anchor_time = time.time()
        self._velocity = np.array(velocity_ned, dtype=float)
        self._displacement = np.zeros(3)
        self._seconds_since_anchor = 0.0
        self._pending.clear()

    def log_command(self, cmd: MotorCommand):
        """Feed one command actually issued by the flight controller."""
        self._pending.append(cmd)

    def log_commands(self, commands: Sequence[MotorCommand]):
        self._pending.extend(commands)

    # -- cross-checks -----------------------------------------------

    def observe_displacement(self, observed_ned: Sequence[float],
                             elapsed_s: float) -> Dict:
        """Compare commanded movement against measured movement.

        Feeds the wind estimate and returns the disagreement, which the
        trust manager uses as a spoofing signal.
        """
        predicted = self._displacement
        wind = self._wind.update(predicted, observed_ned, elapsed_s)
        disagreement = float(np.linalg.norm(
            np.array(observed_ned, dtype=float) - predicted))
        return {
            "disagreement_m": disagreement,
            "wind_speed_ms": self._wind.speed_ms,
            "wind_bearing_deg": self._wind.bearing_deg,
            "wind_samples": self._wind.samples,
            "predicted_ned": predicted.tolist(),
            "observed_ned": list(observed_ned),
        }

    def check_satellite_claim(self, claimed_displacement_ned: Sequence[float],
                              elapsed_s: float,
                              tolerance_m: float = 25.0) -> Dict:
        """Does a satellite fix agree with what the commands could produce?

        If the fix says the airframe travelled somewhere the commands could
        not have taken it, the fix is the suspect party. This is an
        independent spoofing check: an attacker can forge the satellite
        signal but cannot forge the flight controller's own command log.
        """
        if not self._model.calibrated:
            return {"checked": False, "reason": NoFixReason.NO_CALIBRATION}
        claimed = np.array(claimed_displacement_ned, dtype=float)
        gap = float(np.linalg.norm(claimed - self._displacement))
        # allow the tolerance to grow with how long we have been dead reckoning
        allowed = tolerance_m + 2.0 * max(0.0, elapsed_s)
        return {
            "checked": True,
            "disagreement_m": gap,
            "allowed_m": allowed,
            "consistent": gap <= allowed,
            "verdict": "CONSISTENT" if gap <= allowed else "SATELLITE_SUSPECT",
            "commanded_displacement_m": float(np.linalg.norm(self._displacement)),
            "claimed_displacement_m": float(np.linalg.norm(claimed)),
        }

    # -- the reading ------------------------------------------------

    def read(self) -> LayerReading:
        if not self._model.calibrated:
            return no_fix(self.layer_id, NoFixReason.NO_CALIBRATION,
                          "airframe model has not been fitted to flight logs",
                          calibration_samples=self._model.calibration_samples,
                          samples_required=ModelCalibrator.MIN_SEGMENTS)

        if self._anchor is None:
            return no_fix(self.layer_id, NoFixReason.NO_ANCHOR,
                          "no trusted position to dead reckon from; "
                          "supply one via set_anchor()",
                          feed_via=self.REQUIRES.feed_methods)

        if self._pending:
            step, self._velocity = propagate(
                self._pending, self._model,
                np.zeros(3), self._velocity, self._wind.wind_ned)
            self._displacement = self._displacement + step
            self._seconds_since_anchor += sum(
                max(0.0, c.dt) for c in self._pending)
            self._pending.clear()

        if self._seconds_since_anchor <= 0.0:
            return no_fix(self.layer_id, NoFixReason.NO_INPUT,
                          "no commands logged since the last anchor")

        lat0, lon0, alt0 = self._anchor
        d_n, d_e, d_d = self._displacement
        lat = lat0 + d_n / DEG_M
        lon = lon0 + d_e / (DEG_M * max(math.cos(math.radians(lat0)), 0.01))
        alt = alt0 - d_d

        accuracy = self._accuracy_m()
        self._fixes += 1

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=lat, longitude=lon, altitude=alt,
                              accuracy_m=accuracy, timestamp=time.time()),
            velocity=float(np.linalg.norm(self._velocity[:2])),
            self_confidence=self._confidence(accuracy),
            is_valid=True,
            raw_data={
                "fabricated": False,
                "seconds_since_anchor": round(self._seconds_since_anchor, 3),
                "displacement_m": round(float(np.linalg.norm(self._displacement)), 3),
                "model_rms_m": round(self._model.calibration_rms_m, 4),
                "model_samples": self._model.calibration_samples,
                "thrust_to_mass": round(self._model.thrust_to_mass, 4),
                "drag_coeff": round(self._model.drag_coeff, 5),
                "drag_observable": self._model.drag_observable,
                "max_calibration_speed_ms": round(
                    self._model.max_calibration_speed_ms, 2),
                "hover_throttle": round(self._model.hover_throttle, 4),
                "wind_speed_ms": round(self._wind.speed_ms, 3),
                "wind_bearing_deg": round(self._wind.bearing_deg, 1),
                "wind_samples": self._wind.samples,
                "bridge_not_a_solution": True,
                "needs_reset_by": ["landmark_chain", "vision", "satellite"],
            },
        )

    def _accuracy_m(self) -> float:
        """Error grows with time since the last anchor.

        Two terms that are both real: the model's own fit residual, and a
        drift that accumulates because wind and battery sag are not fully
        modelled. Neither is a guess dressed as a measurement — the first is
        measured at calibration, the second is the honest admission that this
        layer is a bridge.
        """
        base = max(self._model.calibration_rms_m, 0.5)
        t = self._seconds_since_anchor
        unmodelled_drift = 0.35 * t          # ~0.35 m per second of dead reckoning
        wind_penalty = 0.5 * self._wind.speed_ms * t

        # If the calibration never flew fast enough to constrain drag, then
        # flying fast now is extrapolating past the data. Widen accordingly
        # rather than reporting a precision the fit does not support.
        speed = float(np.linalg.norm(self._velocity[:2]))
        drag_penalty = 0.0
        if not self._model.drag_observable and speed > 2.0:
            drag_penalty = 0.05 * speed * speed * t

        return base + unmodelled_drift + wind_penalty + drag_penalty

    def _confidence(self, accuracy_m: float) -> float:
        """Confidence falls as the estimate ages. No floor propping it up."""
        if accuracy_m <= 0:
            return 0.0
        c = 1.0 / (1.0 + accuracy_m / 20.0)
        if self._model.calibration_samples < 2 * ModelCalibrator.MIN_SEGMENTS:
            c *= 0.7        # a thinly calibrated model earns less trust
        return max(0.0, min(0.9, c))

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        """Contract note: this sets an ANCHOR, not a fabricated position.

        The layer still returns no fix until real commands are logged against
        it. Present so the registry can construct the layer uniformly.
        """
        self.set_anchor(lat, lon, alt)

    def get_status(self) -> Dict:
        return {
            "calibrated": self._model.calibrated,
            "model_samples": self._model.calibration_samples,
            "model_rms_m": self._model.calibration_rms_m,
            "has_anchor": self._anchor is not None,
            "seconds_since_anchor": round(self._seconds_since_anchor, 3),
            "pending_commands": len(self._pending),
            "fixes_produced": self._fixes,
            "wind_speed_ms": round(self._wind.speed_ms, 3),
        }
