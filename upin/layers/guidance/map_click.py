"""
L2 -- Map-Click Guided Layer (spec section 1).

The operator clicks a point on the map. With GNSS gone, the aircraft still
has three things: roughly where it was at the last trusted fix, the wind it
measured before GNSS was lost, and how fast it flies at a given tilt. From
those it works out "point the nose this way, tilt this much" and flies it.
The operator watches the video and re-clicks if it drifts.

THE CALCULATION (spec 1.2, each control cycle)

  1. bearing and distance from the estimated position to the target
  2. desired ground velocity: along the bearing, tapering near the target
  3. required air velocity = desired ground velocity minus wind -- the crab
  4. heading from the air velocity's direction; tilt from its magnitude, via
     the Speed Learner's table
  5. time to target = distance / ground speed
  6. send heading, tilt and altitude to the flight controller
  7. advance the position estimate and grow its uncertainty
  8. stop on arrival, a correction, or uncertainty past the limit

WHAT THIS LAYER IS AND IS NOT

It is guidance first. The position it reports is its own propagation of the
last trusted fix -- the fix plus what the commands and the frozen wind say
has happened since. That makes it useful to the operator as "position plus
a growing circle" (spec 1.6), but it is not independent evidence: fusing it
back into the estimate it came from would count the same fix twice. The
reading says so, in raw_data["independent"] = False.

WHERE IT REFUSES

  no fix            there is nothing to propagate from
  no wind           spec 1.3 wants the frozen wind; if GNSS went before the
                    wind was learned there is none, and flying as if calm is
                    guessing. Refused rather than assumed.
  no speed table    it cannot turn an airspeed into a tilt
  wind too strong   if the crosswind is faster than the fastest airspeed the
                    table has seen, no heading holds the track. It reports
                    that instead of sending a command it knows will not work.

The uncertainty that grows between fixes is built from things that were
measured -- the fix's own sigma, the wind estimate's sigma (which grows while
frozen), the speed table's scatter -- plus two declared assumptions for
things not yet measured on hardware: compass error and how well the airspeed
transient is modelled. Both are labelled where they are defined.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Tuple

import numpy as np

from upin.core.layer_base import (
    LayerCapability, LayerGroup, LayerReading, NavigationLayer,
)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import (
    DataInput, Hardware, SensorRequirement,
)
from upin.geo.greatcircle import destination, distance_bearing, offset_ne

G = 9.80665
R95_PER_SIGMA = 2.4477
"""A 2-D circle containing 95% of a circular Gaussian has radius 2.4477
sigma, where sigma is the per-axis standard deviation."""


class GuidanceState(Enum):
    IDLE = "idle"                          # no target
    NO_FIX = "no_fix"
    NO_WIND = "no_wind"
    NO_SPEED_TABLE = "no_speed_table"
    EN_ROUTE = "en_route"
    ARRIVED = "arrived"                    # station-keeping over the target
    CANNOT_HOLD_TRACK = "cannot_hold_track"
    COMMAND_REFUSED = "command_refused"
    UNCERTAINTY_EXCEEDED = "uncertainty_exceeded"


@dataclass
class GuidanceStatus:
    state: GuidanceState
    reason: str = ""
    distance_m: Optional[float] = None
    bearing_deg: Optional[float] = None
    eta_s: Optional[float] = None
    ground_speed_ms: Optional[float] = None
    heading_cmd_deg: Optional[float] = None
    tilt_cmd_deg: Optional[float] = None
    radius95_m: Optional[float] = None


@dataclass
class _Fix:
    lat: float
    lon: float
    alt: float
    sigma_m: float
    source: str
    t: float


class MapClickGuidedLayer(NavigationLayer):
    """Fly to a clicked point without GNSS: heading, tilt and time."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("flight controller in a non-GPS attitude mode",
                     why="flies the heading and tilt this layer computes",
                     typical_part="ArduPilot GUIDED_NOGPS (PX4 path unverified)",
                     approx_cost_usd=200, already_on_most_drones=True),
            Hardware("compass / AHRS",
                     why="the nose direction the crab is steered by",
                     typical_part="flight controller's own magnetometer",
                     approx_cost_usd=0, already_on_most_drones=True),
            Hardware("barometer",
                     why="altitude hold while GNSS is gone",
                     typical_part="flight controller's own barometer",
                     approx_cost_usd=0, already_on_most_drones=True),
        ],
        inputs=[
            DataInput("target point", feed_method="set_target",
                      units="degrees, metres",
                      why="the operator's map click"),
            DataInput("last trusted fix", feed_method="set_fix",
                      units="degrees, metres, 1-sigma metres",
                      why="the point the estimate is propagated from"),
            DataInput("wind and speed learners", feed_method="attach",
                      units="WindLearner, SpeedLearner",
                      why="the frozen wind and the tilt-to-airspeed table"),
        ],
        preconditions=(
            "wind learned while GNSS was healthy (spec 1.3), or no guidance",
            "a primed speed table for this airframe and payload (spec 1.4)",
            "wind slower than the fastest airspeed in the table",
        ),
        notes="Guidance first. Its position is a propagation of the last "
              "trusted fix and is marked not independent, so it is never "
              "fused back into the estimate it came from.",
    )

    COMPASS_SIGMA_DEG = 2.0
    """**Assumption.** Heading error of a calibrated compass in flight, 1
    sigma. Unmeasured on this airframe; replace with the value from its own
    compass calibration."""

    TRANSIENT_NOISE_M2_PER_S = 0.1
    """**Assumption.** Position variance added per second for how well the
    first-order airspeed lag models a real turn. Small because the lag model
    tracked true ground velocity to the centimetre in calm simulated air;
    unmeasured on hardware.

    It used to be 1.0 and stood in for gust drift too. Gusts are now measured
    by the Wind Learner and budgeted separately, so this term covers only
    what it says."""

    def __init__(self, autopilot=None, wind_learner=None, speed_learner=None,
                 cruise_airspeed_ms: Optional[float] = None,
                 arrive_m: float = 15.0, max_radius_m: float = 150.0,
                 approach_gain: float = 0.2,
                 on_uncertainty_exceeded: Optional[Callable] = None):
        """`on_uncertainty_exceeded(layer, status)` is the escape manager's
        hook. Return True to take control; L2 then stops commanding. Return
        False (or supply nothing) and L2 holds station against the wind."""
        super().__init__(
            layer_id="mapclick_b13", layer_number=145,
            name="Map-Click Guided Navigation",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING,
                          LayerCapability.VELOCITY],
            is_novel=True,
            description="Fly to a clicked point without GNSS by heading, "
                        "tilt and time, crabbing into the learned wind",
        )
        self._autopilot = autopilot
        self._wind = wind_learner
        self._speed = speed_learner
        self.cruise_airspeed_ms = cruise_airspeed_ms
        self.arrive_m = arrive_m
        self.max_radius_m = max_radius_m
        self.approach_gain = approach_gain
        self.on_uncertainty_exceeded = on_uncertainty_exceeded

        self._target: Optional[Tuple[float, float, Optional[float]]] = None
        self._fix: Optional[_Fix] = None
        self._est: Optional[Tuple[float, float]] = None
        self._air = np.zeros(2)
        self._e_wind = self._e_speed = self._e_heading = 0.0
        self._var_transient = 0.0
        self._var_gust = 0.0
        self._last_t: Optional[float] = None
        self._status = GuidanceStatus(GuidanceState.IDLE, "no target")
        self._handed_over = False
        self._exceeded_reported = False

    # -- wiring -----------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5

    def attach(self, autopilot=None, wind_learner=None, speed_learner=None):
        if autopilot is not None:
            self._autopilot = autopilot
        if wind_learner is not None:
            self._wind = wind_learner
        if speed_learner is not None:
            self._speed = speed_learner

    # -- inputs -----------------------------------------------------

    def set_target(self, lat: float, lon: float,
                   alt_m: Optional[float] = None) -> None:
        """The operator's click. Altitude defaults to holding the current one."""
        self._target = (lat, lon, alt_m)
        self._handed_over = False

    def set_fix(self, lat: float, lon: float, alt: float, sigma_m: float,
                now: float, source: str = "trusted",
                velocity_ne: Optional[Tuple[float, float]] = None) -> None:
        """A trusted position: GNSS before loss, a landmark, terrain, a swarm
        anchor, or the operator. Resets the estimate and shrinks the circle."""
        if not (sigma_m > 0 and math.isfinite(sigma_m)):
            raise ValueError("a fix must state a positive, finite sigma")
        self._fix = _Fix(lat, lon, alt, sigma_m, source, now)
        self._est = (lat, lon)
        self._e_wind = self._e_speed = self._e_heading = 0.0
        self._var_transient = 0.0
        self._var_gust = 0.0
        self._last_t = now
        if velocity_ne is not None:
            w = self._wind_ne(now)
            wind = w if w is not None else np.zeros(2)
            self._air = np.array(velocity_ne, dtype=float) - wind
        # A fix shrinks the circle; guidance may resume.
        self._handed_over = False
        self._exceeded_reported = False

    def operator_fix(self, lat: float, lon: float, sigma_m: float,
                     now: float) -> None:
        """'I am here', clicked from the live video (spec 1.7)."""
        alt = self._fix.alt if self._fix else 0.0
        self.set_fix(lat, lon, alt, sigma_m, now, source="operator")

    def nudge(self, forward_m: float = 0.0, right_m: float = 0.0) -> None:
        """Shift the target relative to the current heading (spec 1.7)."""
        if self._target is None:
            return
        hdg = self._heading_now()
        if hdg is None:
            return
        h = math.radians(hdg)
        north = forward_m * math.cos(h) - right_m * math.sin(h)
        east = forward_m * math.sin(h) + right_m * math.cos(h)
        lat, lon = offset_ne(self._target[0], self._target[1], north, east)
        self._target = (lat, lon, self._target[2])

    # -- helpers ----------------------------------------------------

    def _wind_ne(self, now: float) -> Optional[np.ndarray]:
        if self._wind is None:
            return None
        est = self._wind.estimate(now)
        return None if est is None else np.array([est.north_ms, est.east_ms])

    def _wind_sigma(self, now: float) -> float:
        est = self._wind.estimate(now) if self._wind is not None else None
        return est.sigma_ms if est is not None else float("inf")

    def _heading_now(self) -> Optional[float]:
        if self._autopilot is None:
            return None
        t = self._autopilot.telemetry()
        if t.get("heading_deg") is not None:
            return float(t["heading_deg"])
        sp = self._autopilot.setpoint
        return sp.heading_deg if sp is not None else None

    def _max_airspeed(self) -> Optional[float]:
        rng = self._speed.learned_range if self._speed is not None else None
        if rng is None:
            return None
        found = self._speed.lookup(rng[1])
        return found[0] if found else None

    def sigma_m(self) -> Optional[float]:
        if self._fix is None:
            return None
        return math.sqrt(self._fix.sigma_m ** 2 + self._e_wind ** 2
                         + self._e_speed ** 2 + self._e_heading ** 2
                         + self._var_transient + self._var_gust)

    def radius95_m(self) -> Optional[float]:
        s = self.sigma_m()
        return None if s is None else R95_PER_SIGMA * s

    # -- the control cycle ------------------------------------------

    def step(self, now: float) -> GuidanceStatus:
        """One guidance cycle: propagate, plan, command."""
        if self._fix is None:
            return self._set(GuidanceState.NO_FIX, "no trusted fix to start from")
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now
        wind = self._wind_ne(now)

        # 7. advance the estimate over the interval just flown, using what
        #    the flight controller was actually holding.
        if dt > 0 and wind is not None:
            self._propagate(dt, wind, now)

        radius = self.radius95_m()
        if self._handed_over:
            # The escape manager has control; stay out of its way.
            return self._status
        if radius is not None and radius > self.max_radius_m:
            status = self._set(GuidanceState.UNCERTAINTY_EXCEEDED,
                               f"95% radius {radius:.0f} m exceeds the "
                               f"{self.max_radius_m:.0f} m limit")
            taken = False
            if not self._exceeded_reported:
                self._exceeded_reported = True
                if self.on_uncertainty_exceeded is not None:
                    taken = bool(self.on_uncertainty_exceeded(self, status))
            if taken:
                self._handed_over = True
                return status
            # Nobody has taken over. Stop chasing the target, but do not go
            # level: a level multirotor in wind is carried downwind at the
            # wind's speed. Hold station against the frozen wind instead,
            # which is the least-bad thing an aircraft that does not know
            # where it is can do.
            if wind is not None and self._autopilot is not None:
                self._station_keep(wind)
            elif self._autopilot is not None:
                self._autopilot.hold()
            return status

        if self._target is None:
            return self._set(GuidanceState.IDLE, "no target")
        if wind is None:
            why = self._wind.why_not() if self._wind is not None else "no wind learner"
            return self._set(GuidanceState.NO_WIND,
                             f"no wind estimate ({why}); refusing to fly as if calm")
        if self._speed is None or not self._speed.primed:
            return self._set(GuidanceState.NO_SPEED_TABLE,
                             "speed table not primed; cannot turn airspeed into tilt")
        if self._autopilot is None:
            return self._set(GuidanceState.NO_FIX, "no autopilot attached")

        return self._plan_and_command(wind, radius)

    def _propagate(self, dt: float, wind: np.ndarray, now: float) -> None:
        sp = self._autopilot.setpoint if self._autopilot is not None else None
        tele = self._autopilot.telemetry() if self._autopilot is not None else {}
        heading = tele.get("heading_deg")
        if heading is None and sp is not None:
            heading = sp.heading_deg
        tilt = sp.tilt_deg if sp is not None else 0.0
        steady_speed, speed_sigma = 0.0, 0.0
        if tilt > 0 and self._speed is not None:
            found = self._speed.lookup(tilt)
            if found is not None:
                steady_speed = found[0]
                # The bias in the table's mean, not the scatter of its
                # samples: the scatter is turbulence, budgeted as gusts.
                se = self._speed.mean_sigma(tilt)
                speed_sigma = se if se is not None and math.isfinite(se) else 0.0
        h = math.radians(heading or 0.0)
        nose = np.array([math.cos(h), math.sin(h)])
        steady = steady_speed * nose

        drag = self._speed.drag_estimate() if self._speed is not None else None
        if drag is not None:
            # The real horizontal dynamics, with a drag coefficient learned
            # from the table: forward thrust g tan(tilt) along the nose, minus
            # quadratic drag on airspeed. A first-order lag stood in for this
            # and under-estimated how hard a fast aircraft decelerates after a
            # turn -- nine metres of error in the first fifteen seconds of a
            # calm-air flight whose steady-state tracking was centimetre-good.
            k = drag[0]
            thrust = G * math.tan(math.radians(tilt)) * nose
            n_sub = max(1, int(math.ceil(dt / 0.05)))
            h_sub = dt / n_sub
            for _ in range(n_sub):
                self._air = self._air + (thrust - k * float(np.linalg.norm(self._air))
                                         * self._air) * h_sub
        else:
            # Drag not demonstrably quadratic: approach the steady air
            # velocity with a first-order lag, and let the transient term in
            # the error budget carry the difference.
            if tilt > 0.5 and steady_speed > 0:
                tau = max(1.0, steady_speed / (G * math.tan(math.radians(tilt))))
            else:
                tau = 3.0
            self._air = self._air + (steady - self._air) * min(1.0, dt / tau)

        ground = self._air + wind
        lat, lon = offset_ne(self._est[0], self._est[1],
                             float(ground[0]) * dt, float(ground[1]) * dt)
        self._est = (lat, lon)

        airspeed = float(np.linalg.norm(self._air))
        self._e_wind += self._wind_sigma(now) * dt
        self._e_speed += speed_sigma * dt
        self._e_heading += airspeed * math.radians(self.COMPASS_SIGMA_DEG) * dt
        self._var_transient += self.TRANSIENT_NOISE_M2_PER_S * dt
        self._var_gust = self._gust_variance(now)

    def _gust_variance(self, now: float) -> float:
        """Position variance from gusts the frozen mean wind cannot see.

        The exact integral of a first-order Gauss-Markov wind of spread sigma
        and correlation time tau, per axis:
            var(t) = 2 sigma^2 tau (t - tau (1 - exp(-t / tau)))
        with sigma and tau measured by the Wind Learner, not assumed. It grows
        like t^2 for short times and like t for long ones: turbulence
        averages out, slowly.
        """
        est = self._wind.estimate(now) if self._wind is not None else None
        if est is None or est.gust_tau_s <= 0 or self._fix is None:
            return 0.0
        t = max(0.0, now - self._fix.t)
        tau, sig = est.gust_tau_s, est.gust_sigma_ms
        # The gusts were measured from a finite window, so their power is
        # known only to a confidence interval. Budget its 95% upper bound, not
        # the point estimate: with a few minutes of learning the point estimate
        # alone left the truth outside the stated circle a fifth of the time.
        upper = max(1.0, est.gust_power_upper_factor)
        return upper * 2.0 * sig * sig * tau * (t - tau * (1.0 - math.exp(-t / tau)))

    def _plan_and_command(self, wind: np.ndarray, radius: float) -> GuidanceStatus:
        tlat, tlon, talt = self._target
        dist, brg = distance_bearing(self._est[0], self._est[1], tlat, tlon)
        hold_alt = talt if talt is not None else (
            self._autopilot.telemetry().get("altitude_m") or self._fix.alt)

        s_max = self._max_airspeed()
        cruise = self.cruise_airspeed_ms or 0.75 * s_max
        g_des = min(cruise, self.approach_gain * dist)
        u = np.array([math.cos(math.radians(brg)), math.sin(math.radians(brg))])
        v_air = g_des * u - wind

        if np.linalg.norm(v_air) > s_max:
            # Hold the track at a lower ground speed: the largest g with
            # |g u - w| = s_max.
            uw = float(u @ wind)
            disc = uw * uw - float(wind @ wind) + s_max * s_max
            if disc < 0:
                return self._set(
                    GuidanceState.CANNOT_HOLD_TRACK,
                    f"crosswind {abs(u[0] * wind[1] - u[1] * wind[0]):.1f} m/s exceeds "
                    f"the fastest learned airspeed {s_max:.1f} m/s",
                    distance_m=dist, bearing_deg=brg, radius95_m=radius)
            g = uw + math.sqrt(disc)
            if g <= 0:
                return self._set(
                    GuidanceState.CANNOT_HOLD_TRACK,
                    f"headwind stronger than the fastest learned airspeed "
                    f"{s_max:.1f} m/s: no headway possible",
                    distance_m=dist, bearing_deg=brg, radius95_m=radius)
            g_des = g
            v_air = g_des * u - wind

        # Solving for the ground speed at the table's top airspeed returns that
        # airspeed only up to rounding; left alone, a hair over the top bin
        # made tilt_for() refuse and the state flicker to "cannot hold track".
        airspeed = min(float(np.linalg.norm(v_air)), s_max)
        if airspeed < 0.2:
            heading = self._heading_now() or brg
            tilt = 0.0
        else:
            heading = math.degrees(math.atan2(v_air[1], v_air[0])) % 360.0
            tilt = self._speed.tilt_for(airspeed)
            if tilt is None:
                return self._set(GuidanceState.CANNOT_HOLD_TRACK,
                                 f"airspeed {airspeed:.2f} m/s is outside the "
                                 f"learned table", distance_m=dist,
                                 bearing_deg=brg, radius95_m=radius)

        result = self._autopilot.send_attitude(heading, tilt, hold_alt)
        if not result.accepted:
            return self._set(GuidanceState.COMMAND_REFUSED, result.reason,
                             distance_m=dist, bearing_deg=brg,
                             heading_cmd_deg=heading, tilt_cmd_deg=tilt,
                             radius95_m=radius)

        state = (GuidanceState.ARRIVED if dist <= self.arrive_m
                 else GuidanceState.EN_ROUTE)
        return self._set(state, "", distance_m=dist, bearing_deg=brg,
                         eta_s=dist / g_des if g_des > 0.05 else None,
                         ground_speed_ms=g_des, heading_cmd_deg=heading,
                         tilt_cmd_deg=tilt, radius95_m=radius)

    def _station_keep(self, wind: np.ndarray) -> None:
        """Fly into the wind at its own speed: zero ground velocity, if the
        frozen wind is right."""
        airspeed = float(np.linalg.norm(wind))
        hold_alt = self._autopilot.telemetry().get("altitude_m") or self._fix.alt
        if airspeed < 0.2 or self._speed is None:
            self._autopilot.hold(hold_alt)
            return
        tilt = self._speed.tilt_for(airspeed)
        if tilt is None:
            self._autopilot.hold(hold_alt)
            return
        heading = math.degrees(math.atan2(-wind[1], -wind[0])) % 360.0
        self._autopilot.send_attitude(heading, tilt, hold_alt)

    def _set(self, state: GuidanceState, reason: str, **kw) -> GuidanceStatus:
        if "radius95_m" not in kw:
            kw["radius95_m"] = self.radius95_m()
        self._status = GuidanceStatus(state, reason, **kw)
        return self._status

    @property
    def guidance(self) -> GuidanceStatus:
        return self._status

    # -- the reading ------------------------------------------------

    def read(self) -> LayerReading:
        """The propagated estimate, with the circle it might be anywhere in."""
        if self._fix is None or self._est is None:
            return no_fix(self.layer_id, NoFixReason.NO_ANCHOR,
                          self.REQUIRES.describe_missing(["target point"]
                                                         if self._target else []),
                          feed_via=self.REQUIRES.feed_methods)
        sigma = self.sigma_m()
        radius = R95_PER_SIGMA * sigma
        st = self._status
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=self._est[0], longitude=self._est[1],
                              altitude=self._fix.alt,
                              accuracy_m=math.sqrt(2.0) * sigma,
                              timestamp=self._last_t or 0.0),
            heading=st.heading_cmd_deg,
            velocity=st.ground_speed_ms,
            self_confidence=float(1.0 / (1.0 + radius / 50.0)),
            is_valid=True,
            raw_data={
                "fabricated": False,
                "independent": False,
                "derived_from": f"fix from {self._fix.source}",
                "radius95_m": round(radius, 2),
                "sigma_m": round(sigma, 3),
                "seconds_since_fix": round((self._last_t or self._fix.t)
                                           - self._fix.t, 2),
                "guidance_state": st.state.value,
                "guidance_reason": st.reason,
                "distance_to_target_m": st.distance_m,
                "eta_s": st.eta_s,
                "error_budget_m": {
                    "fix": round(self._fix.sigma_m, 3),
                    "wind": round(self._e_wind, 3),
                    "airspeed": round(self._e_speed, 3),
                    "compass_assumed": round(self._e_heading, 3),
                    "transient_assumed": round(math.sqrt(self._var_transient), 3),
                    "gusts_measured": round(math.sqrt(self._var_gust), 3),
                },
            },
        )
