"""
Per-layer adapters: the only place that knows how to feed a given layer.

A feed supplies physical quantities. A layer wants them in its own shape --
a `MotorCommand`, a `BearingObservation`, a list of ranges. An adapter is the
small piece of translation between the two, and there is exactly one per
converted layer.

Keeping the translation here rather than inside the layer is the whole point.
The layer exposes an input method and computes from whatever arrives; it never
learns where the data came from, so the code path exercised in simulation is
the code path that flies.

WHERE THE NOISE GOES

An adapter adds the sensor noise. That is deliberate and it is what the
no-fabrication contract asks for: noise belongs in the simulator, injected at
the input, never inside a layer manufacturing precision it does not have. An
adapter deriving a bearing from true position and perturbing it by the
detector's real angular error is simulating a camera. A layer doing the same
thing internally is lying about one.

THE RULE ADAPTERS MUST OBEY

An adapter may read TRUE_STATE to derive a geometry -- the bearing from here
to a charted tower, the range to a beacon. It may not hand true position to a
layer as if it were a measurement. That is the original bug, relocated. The
harness checks for it: if a layer's reported position tracks ground truth
exactly, the adapter is cheating, and `NavigationHarness.audit_adapters()`
says so.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np

from upin.simulation.feeds import Feed, Observation, TrueState

DEG_M = 111_320.0
G = 9.80665


@dataclass
class Adapter:
    """How one layer is fed from one source.

    `drive` returns True when it actually supplied something, so the harness
    can count layers that are genuinely fed apart from ones merely registered.

    `provision` sets up the reference data and calibration a layer needs
    before any observation is useful -- a landmark chart, a fitted airframe
    model. In the field these come from a survey and a calibration flight; in
    simulation something has to stand in for them, and it belongs here rather
    than inside the layer. A layer with no chart should decline, and it does;
    provisioning is what a real deployment would have done beforehand.
    """
    layer_id: str
    drive: Callable[[object, Feed, float, np.random.Generator], bool]
    needs: List[str]
    note: str = ""
    provision: Optional[Callable[[object, Feed, np.random.Generator], bool]] = None


ADAPTERS: Dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    ADAPTERS[adapter.layer_id] = adapter
    return adapter


def adapter_for(layer_id: str) -> Optional[Adapter]:
    return ADAPTERS.get(layer_id)


# ---------------------------------------------------------------------------
# Layer 2 — command-based dead reckoning (cmddr_b12)
# ---------------------------------------------------------------------------

def _drive_command_dr(layer, feed: Feed, dt: float,
                      rng: np.random.Generator) -> bool:
    """Synthesise the flight controller's command stream from world motion.

    The world models where the platform is going but not what the pilot asked
    for, so this works backwards: the acceleration needed to produce the
    world's current velocity implies an attitude and a throttle, which is what
    the flight controller would have commanded to fly it.

    That is a real inversion of the same rigid-body model the layer integrates
    forward, not a shortcut. The layer still has to do its own work, and it
    still accumulates the drift that makes command dead reckoning a bridge
    rather than a solution.
    """
    from upin.layers.inertial.command_dr import MotorCommand

    state = feed.observation(Observation.TRUE_STATE)
    if state is None or dt <= 0:
        return False

    model = getattr(layer, "_model", None)
    if model is None or not getattr(model, "calibrated", False):
        # Without a fitted airframe the layer will decline anyway, and it is
        # right to: feeding it commands it cannot interpret would be feeding
        # it nothing.
        return False

    # The anchor is a fix from somewhere trustworthy. In simulation the first
    # one is the world's own start; afterwards the layer dead reckons and is
    # reset by whatever Layer 4 or a satellite fix supplies.
    if getattr(layer, "_anchor", None) is None:
        layer.set_anchor(state.latitude, state.longitude, state.altitude,
                         (state.velocity_north, state.velocity_east, 0.0))
        return True

    prev = getattr(layer, "_harness_prev_velocity", None)
    v_now = np.array([state.velocity_north, state.velocity_east, 0.0])
    v_prev = np.array(prev) if prev is not None else v_now
    layer._harness_prev_velocity = tuple(v_now)

    accel = (v_now - v_prev) / dt

    # Invert the layer's own forward model, which is
    #     a = thrust_world + [0, 0, G] - drag_coeff * |v| * v
    # so the thrust that produces a given acceleration is
    #     thrust_world = a - [0, 0, G] + drag_coeff * |v| * v
    #
    # The drag term is the part that matters and the part it is easy to drop.
    # The world integrates velocity without modelling airframe drag, so level
    # flight there needs no forward tilt -- but the layer's model does apply
    # drag, and a command stream that ignores it commands a drone to coast.
    # Leaving it out bled a simulated 50 m/s cruise down to 5 m/s in under two
    # seconds while the layer still claimed metre accuracy.
    speed = float(np.linalg.norm(v_now))
    drag = model.drag_coeff * speed * v_now
    thrust_vec = np.array([accel[0] + drag[0],
                           accel[1] + drag[1],
                           accel[2] + drag[2] - G])
    magnitude = float(np.linalg.norm(thrust_vec))
    if magnitude < 1e-6:
        return False

    yaw = math.radians(state.heading_deg)

    # Exact inverse of accel_from_command's attitude rotation. That forward
    # model writes the unit thrust direction as
    #     u = [cψ sθ cφ + sψ sφ,  sψ sθ cφ - cψ sφ,  cθ cφ]
    # so rotating u's horizontal part back through the yaw gives
    #     x_body = sθ cφ      y_body = -sφ
    # and the attitude falls straight out. Solving it exactly rather than by
    # a tilt-and-bearing approximation matters: the approximation put the
    # roll sign wrong at non-zero yaw and quietly injected vertical drift.
    u = -thrust_vec / magnitude
    x_body = math.cos(yaw) * u[0] + math.sin(yaw) * u[1]
    y_body = -math.sin(yaw) * u[0] + math.cos(yaw) * u[1]

    roll = math.asin(max(-1.0, min(1.0, -y_body)))
    pitch = math.atan2(x_body, u[2])

    throttle = (magnitude / model.thrust_to_mass) ** (
        1.0 / max(model.throttle_exponent, 1e-6))

    # A throttle above 1.0 means the trajectory needs more thrust than this
    # airframe has. Clamping it and sending the command anyway would feed the
    # layer a command the aircraft could not have flown, and the layer would
    # integrate it as though it had -- inventing a position from a physically
    # impossible input. Better to supply nothing and let the layer's accuracy
    # degrade honestly with the gap.
    if not (0.0 <= throttle <= 1.0):
        return False

    # The controller's own command quantisation and servo error. Small, real,
    # and the reason command dead reckoning drifts at all.
    cmd = MotorCommand(
        timestamp=state.timestamp,
        throttle=float(throttle + rng.normal(0, 0.002)),
        roll_rad=float(roll + rng.normal(0, 0.002)),
        pitch_rad=float(pitch + rng.normal(0, 0.002)),
        yaw_rad=float(yaw),
        dt=dt,
    )
    layer.log_command(cmd)
    return True


def _provision_command_dr(layer, feed: Feed, rng: np.random.Generator) -> bool:
    """Stand in for the calibration flight this layer cannot fly in a test.

    Real calibration fits thrust-to-mass and drag by least squares against
    logged flights. Simulating that honestly would mean flying the simulated
    airframe first; what matters for the harness is that the layer has a model
    whose provenance is recorded, so the numbers here are marked as coming
    from a simulated calibration rather than a real one.
    """
    from upin.layers.inertial.command_dr import AirframeModel

    model = getattr(layer, "_model", None)
    if model is not None and getattr(model, "calibrated", False):
        return False                       # already calibrated, leave it alone

    # Drag has to match the flight envelope the world actually flies. The
    # test airframe elsewhere in the repo uses drag_coeff=0.08, which is fine
    # at the ~8 m/s those tests fly but makes 50 m/s impossible: quadratic
    # drag at 50 m/s would be 0.08 * 50^2 = 200 m/s^2 against 22.5 m/s^2 of
    # available thrust. Provisioning that model here saturated the throttle
    # every tick and fed the layer commands the airframe could not execute.
    # SIM_DRAG_COEFF puts terminal velocity comfortably above cruise.
    layer.set_model(AirframeModel(
        thrust_to_mass=SIM_THRUST_TO_MASS,
        drag_coeff=SIM_DRAG_COEFF,
        calibrated=True,
        calibration_samples=12,
        calibration_rms_m=0.02,
        airframe_id="simulated-quad",
        max_calibration_speed_ms=8.0,
        drag_observable=True,
    ))
    return True


SIM_THRUST_TO_MASS = 22.5
"""Acceleration at full throttle, m/s^2. About 2.3 g, a normal quadrotor."""

SIM_DRAG_COEFF = 0.004
"""Quadratic drag over mass, 1/m. Terminal velocity is sqrt(thrust/drag),
here about 75 m/s, so the simulated 50 m/s cruise sits inside the envelope
with thrust to spare for manoeuvring."""


register(Adapter(
    layer_id="cmddr_b12",
    drive=_drive_command_dr,
    provision=_provision_command_dr,
    needs=[Observation.TRUE_STATE],
    note="inverts the rigid-body model to recover the commands that would "
         "have flown the world's motion",
))


# ---------------------------------------------------------------------------
# Layer 4 — landmark chain (lmkchain_e23)
# ---------------------------------------------------------------------------

def _drive_landmark_chain(layer, feed: Feed, dt: float,
                          rng: np.random.Generator) -> bool:
    """Compute what the camera would see: bearings to charted landmarks.

    The world models stereo camera geometry but carries no landmark database,
    so the bearings are derived from the layer's own loaded chart and the true
    platform position. Only landmarks within sight are offered, and each
    bearing is perturbed by the detector's angular error -- which is exactly
    what the layer then weights by when it solves.
    """
    from upin.layers.optical.landmark_chain import BearingObservation

    state = feed.observation(Observation.TRUE_STATE)
    if state is None:
        return False

    lmap = getattr(layer, "_map", None)
    if lmap is None or len(lmap) == 0:
        # No chart loaded. The layer will decline and say so, correctly.
        return False

    visible = lmap.within(state.latitude, state.longitude, MAX_SIGHT_M)
    if len(visible) < 2:
        return False

    sigma_deg = BEARING_SIGMA_DEG
    coslat = max(math.cos(math.radians(state.latitude)), 0.01)
    observations = []
    for lm in visible[:MAX_LANDMARKS_IN_VIEW]:
        dn = (lm.latitude - state.latitude) * DEG_M
        de = (lm.longitude - state.longitude) * DEG_M * coslat
        true_bearing = math.degrees(math.atan2(de, dn)) % 360.0
        observations.append(BearingObservation(
            landmark_id=lm.landmark_id,
            bearing_deg=float((true_bearing + rng.normal(0, sigma_deg)) % 360.0),
            bearing_sigma_deg=sigma_deg,
            timestamp=state.timestamp,
        ))

    layer.clear_observations()
    layer.observe_many(observations)
    return True


MAX_SIGHT_M = 5_000.0
"""How far a landmark stays identifiable. Beyond a few kilometres a water
tower is a smudge, and a bearing to a smudge is not a bearing."""

MAX_LANDMARKS_IN_VIEW = 6
"""A camera frame holds a handful of recognisable objects, not a chart."""

BEARING_SIGMA_DEG = 0.5
"""Angular error of a detection in a gimbal-stabilised frame, combining pixel
centroiding with attitude error. Half a degree is achievable and not
flattering."""


def _provision_landmark_chain(layer, feed: Feed,
                              rng: np.random.Generator) -> bool:
    """Lay a charted landmark field around the world's starting point.

    A real deployment loads a chart surveyed from Indian sources. There is no
    such chart in this repo, so the harness surveys one: a ring of landmarks
    at known offsets, each carrying a survey accuracy and the FIELD_SURVEY
    provenance, because that is what they honestly are -- points whose
    coordinates are known exactly because they were placed, which is the
    simulation equivalent of a DGPS survey.

    The positions are deterministic, so a seeded run is reproducible.
    """
    from upin.layers.optical.landmark_chain import Landmark, MapSource

    if len(getattr(layer, "_map", [])) > 0:
        return False

    state = feed.observation(Observation.TRUE_STATE)
    if state is None:
        return False

    coslat = max(math.cos(math.radians(state.latitude)), 0.01)
    placed = []
    for i, (north_m, east_m, kind) in enumerate(SURVEYED_FIELD):
        placed.append(Landmark(
            landmark_id=f"sim_{kind}_{i}",
            latitude=state.latitude + north_m / DEG_M,
            longitude=state.longitude + east_m / (DEG_M * coslat),
            source=MapSource.FIELD_SURVEY,
            position_accuracy_m=1.5,
            name=f"simulated {kind}",
            altitude_m=state.altitude - 100.0,
            feature_type=kind,
        ))
    layer.load_map(placed)
    return True


SURVEYED_FIELD = (
    (1200.0, 0.0, "tower"),
    (-400.0, 1500.0, "bridge"),
    (-900.0, -1100.0, "tank"),
    (600.0, -1400.0, "spire"),
    (-1500.0, 300.0, "junction"),
)
"""Where the simulated survey put its landmarks, in metres north and east of
the world's start. Spread wide enough to give a decent cut angle from
anywhere inside the ring, which is the condition the layer actually checks."""


register(Adapter(
    layer_id="lmkchain_e23",
    drive=_drive_landmark_chain,
    provision=_provision_landmark_chain,
    needs=[Observation.TRUE_STATE],
    note="derives camera bearings to the layer's own charted landmarks",
))
