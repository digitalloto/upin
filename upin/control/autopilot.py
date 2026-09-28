"""
The flight-controller interface: the first thing in UPIN that commands.

Until now every path in this repo ran inward -- sensors to layers to fusion
to a position. The Map-Click Guided layer needs the other direction: take
"fly toward that point" and turn it into an attitude the flight controller
flies. This module is that boundary, and it is deliberately narrow:

    send_attitude(heading_deg, tilt_deg, hold_alt_m)

Point the nose here, tilt forward this much, hold this altitude. That is the
whole vocabulary the spec asks for (section 1.5), and it maps directly onto
ArduPilot's non-GPS guided mode, which accepts attitude targets and holds
altitude on the barometer.

REFUSED, NEVER CLAMPED

"UPIN must never send commands outside safe tilt and speed limits, whatever
the calculation says." A limit can be enforced two ways: clamp the command to
the limit and send it, or refuse it. Clamping is the dangerous one. A guidance
law that asked for 40 degrees of tilt and got 25 is now flying a trajectory it
did not plan, while believing it is flying the one it did -- and in a
GPS-denied aircraft there is nothing to reveal the difference. So a command
outside the limits is refused, the refusal is reported with its reason, and
the aircraft keeps flying its last accepted setpoint. The layer that asked
learns immediately that it cannot have what it wanted.

That rule lives here, in the base class, so the simulated and the real
autopilot enforce it identically.

WHAT IS TESTED AND WHAT IS NOT

`SimulatedAutopilot` closes the loop through the simulator's dynamics and is
tested end to end. `MAVLinkAutopilot` speaks the real protocol and has never
been connected to a flight controller: there is no drone and no SITL here. It
carries UNTESTED = True, imports pymavlink only when asked to connect, and its
PX4 path is unverified -- the spec says so too.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

G = 9.80665


# ---------------------------------------------------------------------------
# Setpoints and limits
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AttitudeSetpoint:
    """What UPIN asks the flight controller to fly."""
    heading_deg: float      # where the nose points, degrees true
    tilt_deg: float         # forward tilt, nose down; this is what makes airspeed
    hold_alt_m: float       # altitude to hold, metres above sea level (baro)
    timestamp: float = 0.0


@dataclass
class CommandResult:
    accepted: bool
    reason: str = ""
    setpoint: Optional[AttitudeSetpoint] = None


@dataclass
class AutopilotLimits:
    """The envelope UPIN is never allowed to command outside.

    `max_tilt_deg` is also the speed guard: forward speed is set by tilt
    against drag, so bounding tilt bounds speed without the autopilot needing
    a speed model of its own.

    `max_alt_step_m` is a guard against a units mistake -- feet for metres, or
    height above ground for height above sea level. A request to hold an
    altitude more than this far from where the aircraft is now is far more
    likely to be a bug than an intention, and a flight controller told to
    climb 300 m because someone passed AGL as MSL will do it.
    """
    max_tilt_deg: float = 25.0
    max_alt_step_m: float = 50.0
    min_alt_m: Optional[float] = None
    max_alt_m: Optional[float] = None

    def violation(self, sp: AttitudeSetpoint,
                  current_alt_m: Optional[float]) -> str:
        """Why this setpoint must be refused, or "" if it may be flown."""
        for name, value in (("heading", sp.heading_deg), ("tilt", sp.tilt_deg),
                            ("altitude", sp.hold_alt_m)):
            if not math.isfinite(value):
                return f"{name} is not a finite number ({value!r})"
        if sp.tilt_deg < 0.0:
            return (f"negative tilt {sp.tilt_deg:.1f} deg: fly backward by "
                    f"turning the nose, not by tilting against it")
        if sp.tilt_deg > self.max_tilt_deg:
            return (f"tilt {sp.tilt_deg:.1f} deg exceeds the "
                    f"{self.max_tilt_deg:.1f} deg limit")
        if self.min_alt_m is not None and sp.hold_alt_m < self.min_alt_m:
            return (f"hold altitude {sp.hold_alt_m:.1f} m is below the "
                    f"{self.min_alt_m:.1f} m floor")
        if self.max_alt_m is not None and sp.hold_alt_m > self.max_alt_m:
            return (f"hold altitude {sp.hold_alt_m:.1f} m is above the "
                    f"{self.max_alt_m:.1f} m ceiling")
        if (current_alt_m is not None
                and abs(sp.hold_alt_m - current_alt_m) > self.max_alt_step_m):
            return (f"hold altitude {sp.hold_alt_m:.1f} m is "
                    f"{abs(sp.hold_alt_m - current_alt_m):.0f} m from the current "
                    f"{current_alt_m:.1f} m, beyond the {self.max_alt_step_m:.0f} m "
                    f"step limit -- check units and datum")
        return ""


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------

class Autopilot(ABC):
    """A flight controller UPIN can command.

    Subclasses implement `_apply` (send an accepted setpoint) and
    `telemetry` (what the controller reports about itself). Limit checking is
    done here, once, for every implementation.
    """

    UNTESTED = False
    """True for an implementation that has never flown anything."""

    def __init__(self, limits: Optional[AutopilotLimits] = None):
        self.limits = limits or AutopilotLimits()
        self._setpoint: Optional[AttitudeSetpoint] = None
        self._refusals: List[Tuple[AttitudeSetpoint, str]] = []

    def send_attitude(self, heading_deg: float, tilt_deg: float,
                      hold_alt_m: float) -> CommandResult:
        sp = AttitudeSetpoint(heading_deg=heading_deg % 360.0
                              if math.isfinite(heading_deg) else heading_deg,
                              tilt_deg=tilt_deg, hold_alt_m=hold_alt_m,
                              timestamp=time.time())
        why = self.limits.violation(sp, self.telemetry().get("altitude_m"))
        if why:
            self._refusals.append((sp, why))
            return CommandResult(False, why, self._setpoint)
        self._apply(sp)
        self._setpoint = sp
        return CommandResult(True, "", sp)

    def hold(self, hold_alt_m: Optional[float] = None) -> CommandResult:
        """Level attitude, current heading, hold altitude. The safe command."""
        t = self.telemetry()
        alt = hold_alt_m if hold_alt_m is not None else t.get("altitude_m")
        if alt is None:
            return CommandResult(False, "no altitude to hold", self._setpoint)
        return self.send_attitude(t.get("heading_deg", 0.0) or 0.0, 0.0, alt)

    @property
    def setpoint(self) -> Optional[AttitudeSetpoint]:
        return self._setpoint

    @property
    def refusals(self) -> List[Tuple[AttitudeSetpoint, str]]:
        return list(self._refusals)

    @abstractmethod
    def _apply(self, sp: AttitudeSetpoint) -> None:
        ...

    @abstractmethod
    def telemetry(self) -> Dict:
        """What the flight controller reports: attitude, altitude, climb rate.

        Not position. Position is what UPIN exists to work out; a flight
        controller that has lost GNSS does not have one to give.
        """
        ...


# ---------------------------------------------------------------------------
# Simulated
# ---------------------------------------------------------------------------

class SimulatedAutopilot(Autopilot):
    """A flight controller flying the simulator's platform.

    It does what ArduPilot's non-GPS guided mode does: fly the commanded
    attitude, and hold altitude by adjusting thrust. The altitude loop is a
    PD controller on the flight controller's own altitude estimate, taken as
    exact here -- barometric error is the flight controller's problem, not
    UPIN's, and modelling it would test the wrong thing.

    Call `update()` before each world step to recompute thrust, or `fly(dt)`
    to update and step together.
    """

    ALT_KP = 0.8      # 1/s^2
    ALT_KD = 1.2      # 1/s
    MAX_VERTICAL_ACCEL = 3.0   # m/s^2

    def __init__(self, world, airframe=None,
                 limits: Optional[AutopilotLimits] = None):
        super().__init__(limits)
        self._world = world
        if not world.dynamics_engaged:
            if airframe is None:
                raise ValueError("the world has no dynamics engaged; supply "
                                 "the airframe it should fly")
            world.engage_dynamics(airframe)
        # Start holding what the aircraft is doing now.
        self._setpoint = AttitudeSetpoint(world.true_heading, 0.0,
                                          world.true_alt, time.time())

    @property
    def world(self):
        return self._world

    def _apply(self, sp: AttitudeSetpoint) -> None:
        self._command_from(sp)

    def update(self) -> None:
        """Recompute thrust for altitude hold and hand the command to the world."""
        if self._setpoint is not None:
            self._command_from(self._setpoint)

    def fly(self, dt: float = 0.1) -> None:
        self.update()
        self._world.step(dt)

    def _command_from(self, sp: AttitudeSetpoint) -> None:
        from upin.layers.inertial.command_dr import MotorCommand

        w = self._world
        airframe = w.airframe
        climb = -w.true_vd
        a_up = self.ALT_KP * (sp.hold_alt_m - w.true_alt) - self.ALT_KD * climb
        a_up = max(-self.MAX_VERTICAL_ACCEL, min(self.MAX_VERTICAL_ACCEL, a_up))

        tilt = math.radians(sp.tilt_deg)
        thrust = (G + a_up) / max(math.cos(tilt), 1e-3)
        throttle = (max(thrust, 0.0) / airframe.thrust_to_mass) ** (
            1.0 / max(airframe.throttle_exponent, 1e-6))
        # Actuator saturation inside the flight controller is physics, not a
        # command outside limits: motors have a maximum. It is not clamped
        # silently -- it is reported in telemetry.
        self._saturated = throttle > 1.0
        throttle = min(throttle, 1.0)

        w.command_attitude(MotorCommand(
            timestamp=w.elapsed, throttle=throttle,
            roll_rad=0.0, pitch_rad=-tilt,
            yaw_rad=math.radians(sp.heading_deg)))

    def telemetry(self) -> Dict:
        w = self._world
        imu = w.get_imu()
        return {
            "heading_deg": w.true_heading,
            "roll_rad": imu["roll_rad"],
            "pitch_rad": imu["pitch_rad"],
            "altitude_m": w.true_alt,
            "climb_ms": -w.true_vd,
            "thrust_saturated": getattr(self, "_saturated", False),
            "wind_estimate_ned": self._fc_wind_estimate(),
            "mode": "GUIDED_NOGPS_SIM",
        }

    def _fc_wind_estimate(self) -> Optional[list]:
        """The flight controller's own wind estimate, if it has one.

        A copter's EKF estimates wind from the mismatch between GNSS velocity
        and its dynamic model, so it has an estimate only while GNSS is
        tracking -- and it is an estimate, with error, not the true wind. The
        spec (section 1.3) wants this as a second opinion for the Wind
        Learner. Under denial it is None, not the last value.
        """
        if self._world.get_gnss_velocity() is None:
            return None
        true = self._world.wind.vector_ned
        err = self._world._rng.normal(0.0, 0.5, size=2)
        return [float(true[0] + err[0]), float(true[1] + err[1]), 0.0]


# ---------------------------------------------------------------------------
# MAVLink -- UNTESTED
# ---------------------------------------------------------------------------

class AutopilotUnavailable(RuntimeError):
    """The real autopilot cannot be reached, and nothing is pretended."""


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> List[float]:
    """ZYX Euler angles to a [w, x, y, z] quaternion, MAVLink's order."""
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return [cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy]


def climb_thrust(hold_alt_m: float, current_alt_m: Optional[float],
                 gain_per_m: float = 0.02) -> float:
    """ArduPilot GUIDED_NOGPS reads thrust as a climb-rate demand.

    With the default GUID_OPTIONS, 0.5 means hold altitude, 0 full descent,
    1 full climb. Altitude hold is therefore a proportional demand around 0.5.
    Documented ArduCopter behaviour; not verified against a vehicle.
    """
    if current_alt_m is None:
        return 0.5
    return max(0.0, min(1.0, 0.5 + gain_per_m * (hold_alt_m - current_alt_m)))


class MAVLinkAutopilot(Autopilot):
    """ArduPilot over MAVLink, in GUIDED_NOGPS. **Never flown.**

    Sends SET_ATTITUDE_TARGET with body rates ignored. PX4's equivalent
    offboard attitude path is not verified, per the spec (section 1.5). This
    class does not arm the vehicle and does not change its mode on its own:
    arming and mode are the operator's decisions.
    """

    UNTESTED = True
    TYPE_MASK_IGNORE_BODY_RATES = 0b00000111

    def __init__(self, connection_string: str,
                 limits: Optional[AutopilotLimits] = None,
                 source_system: int = 255):
        super().__init__(limits)
        self.connection_string = connection_string
        self.source_system = source_system
        self._conn = None
        self._boot = time.time()
        self._last_telemetry: Dict = {}

    def connect(self, timeout_s: float = 10.0):
        try:
            from pymavlink import mavutil  # noqa: WPS433 -- lazy by design
        except ImportError as exc:
            raise AutopilotUnavailable(
                "pymavlink is not installed. MAVLinkAutopilot is untested and "
                "needs `pip install pymavlink` plus a flight controller or "
                "ArduPilot SITL to talk to.") from exc
        self._conn = mavutil.mavlink_connection(
            self.connection_string, source_system=self.source_system)
        if self._conn.wait_heartbeat(timeout=timeout_s) is None:
            raise AutopilotUnavailable(
                f"no heartbeat from {self.connection_string} in {timeout_s} s")
        return self._conn

    def _require(self):
        if self._conn is None:
            raise AutopilotUnavailable("not connected; call connect() first")
        return self._conn

    def _apply(self, sp: AttitudeSetpoint) -> None:
        conn = self._require()
        q = euler_to_quaternion(0.0, -math.radians(sp.tilt_deg),
                                math.radians(sp.heading_deg))
        thrust = climb_thrust(sp.hold_alt_m, self._last_telemetry.get("altitude_m"))
        conn.mav.set_attitude_target_send(
            int((time.time() - self._boot) * 1000),
            conn.target_system, conn.target_component,
            self.TYPE_MASK_IGNORE_BODY_RATES, q, 0.0, 0.0, 0.0, thrust)

    def telemetry(self) -> Dict:
        if self._conn is None:
            return {}
        for msg_type in ("ATTITUDE", "VFR_HUD"):
            msg = self._conn.recv_match(type=msg_type, blocking=False)
            if msg is None:
                continue
            if msg_type == "ATTITUDE":
                self._last_telemetry.update(
                    roll_rad=msg.roll, pitch_rad=msg.pitch,
                    heading_deg=math.degrees(msg.yaw) % 360.0)
            else:
                self._last_telemetry.update(altitude_m=msg.alt,
                                            climb_ms=msg.climb)
        return dict(self._last_telemetry)
