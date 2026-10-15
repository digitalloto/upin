# Wind-and-tilt dead reckoning: the last velocity rung before coasting

When GNSS goes and there is no flow sensor, no camera and no trained
model, the box used to coast: hold the last velocity and let the circle
grow (269 m after 60 s in simulation, 331 m on the flight below). This
component gives it a ground velocity from sensors every drone has:

    ground velocity = air velocity + wind

- **The wind** is the Wind Learner's (`upin/core/wind_learner.py`): learned
  while GNSS was trusted from the lean and the GNSS velocity on several
  headings, **frozen the moment GNSS goes**, its sigma widening with time
  (0.15 m/s per minute, a labelled assumption). This is exactly the limit
  the concept documents name: if the wind shifts after the freeze, the
  estimate is wrong by the shift.
- **The air velocity**, one of two ways:
  - **multirotor**: the Speed Learner's tilt-to-airspeed curve
    (`upin/core/speed_learner.py`), learned on the trusted leg of the same
    flight or loaded for this airframe and payload. At steady state the lean
    balances drag: `g·tan(tilt)·û = a + k|air|·air`. With the flight
    controller's IMU the horizontal acceleration `a` is taken out first, so a
    turn's centripetal lean is not read as airspeed; without an IMU the
    estimate declines while turning.
  - **fixed wing**: the pitot airspeed along the heading (sideslip ignored,
    stated), only with `airspeed_sensor = true`. Without a real sensor
    ArduPilot fills `VFR_HUD.airspeed` from its EKF, which used GNSS: that
    would be circular, so it is never used by default.

It is fed to the filter as `source="wind_dr"` **only when nothing better
has fed it in the last second** (flow chip, camera flow, AI predictor). It
is the last rung of the velocity ladder in `docs/MISSION_INDEX.md`.

> **Status: simulation only.** Simulated flights with quadratic drag and a
> steady wind with gusts (`upin/learned/sim_flights.py`), and the console's
> circuit. Nothing flight-proven. Every threshold is an assumption.

## Where it refuses, and says so

| Reason | Words |
|---|---|
| the wind was never learned | the Wind Learner's own reason: too few steady samples, one heading ("a headwind and a lower airspeed are indistinguishable: turn"), GNSS lost before it was learned |
| no `airframe_id` | "the tilt-to-airspeed curve is per airframe" |
| no curve yet | needs a trusted leg with steady flight on several headings |
| lean outside the learned range | the curve never extrapolates |
| turning, no IMU | the steady-state curve does not apply |
| attitude stale | |

## The sigma

Curve standard error ⊕ wind sigma (growing while frozen) ⊕ measured gust
spread ⊕ the IMU correction's noise through the curve's slope. Measured
coverage below.

## Measured in simulation

| Scenario | Result |
|---|---|
| 300 s trusted leg of random legs in a 3 m/s wind with 0.4 m/s gusts | wind learned to 0.47 m/s (stated ±0.21); curve 5–17.5° |
| then 120 s dead reckoning, IMU-corrected | 0.72 m/s rms against a stated ±0.48, 95% circle covers 91%; position drift after 60 s **25 m** against 73 m holding the last velocity |
| the same, without an IMU | 51 windows declined while turning; steady flight as above |
| **stated limit**: the wind shifts by 3 m/s after the freeze | 3.2 m/s rms error against a stated ±0.36: the frozen wind is wrong by the shift and the sigma does not know |
| through the box: 300 s trusted, 90 s receiver silent | curve learned from 116 steady samples; wind DR fed 187 epochs; error after 60 s **16 m** against **331 m** coasting |
| the console's circuit, 3 m/s breeze | wind learned to 0.04 m/s (stated ±0.07) after a lap; flow sensors off and GNSS denied 40 s: wind DR fed every epoch, 4 m error vs the simulated truth |
| a fixed wing on one heading | the pitot is parsed, but on a single heading there is no wind to add, and the box says so |

`python tests/test_wind_dr.py` reproduces every row.

## What it needs

- `airframe_id` in `box.toml` (the curve is per airframe and payload), and
  `wind_dr = true`;
- a trusted leg with **turns**: the wind triangle is degenerate on one
  heading; a few steady seconds on two or three headings make it observable;
- the flight controller's attitude and IMU (already read);
- optional `speed_model`: the curve is saved there when the flight ends and
  loaded at the next start, so the next flight is ready from the first
  epoch; a curve for another airframe or payload is refused;
- for a fixed wing, a real airspeed sensor and `airspeed_sensor = true`.

ArduPilot's own EKF dead reckons a fixed wing on airspeed and its wind
estimate when GPS is lost; this is the multirotor's equivalent inside UPIN,
and a cross-check on a fixed wing. The box never reads the flight
controller's own velocity or position back (they would contain UPIN's
output).

## Limits, stated

- The frozen wind goes stale; the growth rate is an assumption to replace
  with the operating area's records.
- The curve is per airframe and payload; a changed payload needs a new leg.
- Gusts are budgeted from the learned flight, not measured live.
- A fixed wing's sideslip is ignored.
- The IMU correction trusts the flight controller's attitude; its error
  budget (0.15 m/s² over a second) is an assumption.

## Files

| | |
|---|---|
| `upin/box/wind_dr.py` | the estimate, the IMU correction, the declines |
| `upin/core/wind_learner.py`, `upin/core/speed_learner.py` | the learners, now wired |
| `upin/box/service.py` | `wind_dr`, `speed_model`, `payload_kg`, `airspeed_sensor`; `step_wind_dr`, `_learn_speed`, `save_models` |
| `upin/box/fc_reader.py` | `VFR_HUD.airspeed` |
| `upin/console/sources.py` | the circuit's breeze and lean |
| `tests/test_wind_dr.py` | every figure above |
