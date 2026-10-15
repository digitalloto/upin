# UPIN Roadmap

What is built, what is left, and the path to running on real hardware.
Last updated 1 October 2026. Measured layer status lives in
[`README.md`](README.md); this file is the plan.

> Nothing here is flight-proven. No claim of jamming resistance is made
> until the authorised-range test (spec §13.1, step 4). Every performance
> figure below is from simulation and is labelled as such.

## Standing rules

- **No fabricated data.** A layer either computes from real input or
  declines and says what is missing (`upin/core/no_fabrication.py`).
- **Indian map sources only** — Survey of India, Bhuvan, Cartosat, NHO
  charts, or the operator's own survey. Never Google tiles.
- **No partner names** in code or docs. The layered-navigation spec is
  internal and confidential; this roadmap refers to it, it does not copy it.
- **Our own designs from published methods.** No other company's code.

## Part 1 — Honesty programme

| Phase | What | Status |
|---|---|---|
| 0.1 | Fusion engine can report "no fix" (it returned 0°N 0°E before) | done |
| 0.2 | Layers declare the sensors and data they need | done |
| 0.3 | Simulation moved out of layers into a harness; real/sim/off modes; real feed rejects agents that fall back to simulation | done |
| 0.4 | A generated README for every layer, status measured not claimed | done |
| — | Sensor requirements and operating class for all 147 layers (`upin/layers/requirements_catalog.py`) | done |
| 1 | Convert the remaining fabricating layers, one at a time | **114 left** |
| 2 | Delete `set_simulated_position` and the simulation default | after Phase 1 |

## Part 2 — Layered Navigation Spec v1

| # | Item (spec section) | Status | Where |
|---|---|---|---|
| F1 | Simulator: wind, commandable dynamics, jamming zones, ground texture | done | `upin/simulation/environment.py` |
| F2 | Flight-controller interface; commands refused, never clamped | done (MAVLink untested) | `upin/control/autopilot.py` |
| 1 | Wind Learner + Speed Learner (§1.3, §1.4) | done | `upin/core/wind_learner.py`, `speed_learner.py` |
| 2 | L2 Map-Click Guided Layer (§1) | done | `upin/layers/guidance/map_click.py` |
| 3 | L0 GNSS/NavIC jamming, RAIM, spoof checks, return validation, jamming map (§2) | done | `upin/layers/satellite/gnss_*.py`, `upin/detection/jamming_map.py` |
| — | **The UPIN box**: Pi between GNSS and the flight controller; reachability guard, cross-constellation check, UBX/NMEA parsers, gateway, `GPS_INPUT` (untested) | done (software) | `upin/box/`, `upin/detection/reachability.py`, `constellation_check.py`, [`docs/HARDWARE.md`](docs/HARDWARE.md) |
| — | **Box as GPS 2**: flight-controller reader (refuses circular inputs), Pi service, shadow mode, Pi install files, SITL check script | done (software; I/O untested) | `upin/box/fc_reader.py`, `service.py`, `deploy/`, `tools/sitl_box.py` |
| — | **UPIN console**: live page (simulation, this device's location, board-only, live box, replay); no made-up numbers, tested; replaces the old phone demo, which displayed random values | done (sim/browser/replay tested; board/live untested on hardware) | `upin/console/`, [`docs/CONSOLE.md`](docs/CONSOLE.md) |
| — | **Layer 146, GNSS signal-power spoof check** (`cn0spoof_a20`): C/N0 uniformity, elevation dependence, strength, simultaneous rise, AGC vs C/N0, this antenna's learned profile. Warn-only in the box until calibrated | done (simulation; thresholds unmeasured) | `upin/layers/satellite/signal_power.py` |
| — | **Layer 147, AI motion predictor** (`learnedio_b14`): learned inertial odometry trained flight by flight (`tools/learn_from_flight.py`); each flight scored before it is learned from; promotion only if no worse; measured weather per flight; flags conditions outside training. Off in the box unless configured | done (simulated flights only; real-log parsing untested) | `upin/layers/inertial/learned_io.py`, `upin/learned/`, [`docs/LEARNED_IO.md`](docs/LEARNED_IO.md) |
| — | **Optical-flow integrity check** (from the laser-dot reel): flow vs IMU, trusted GNSS and the AI predictor; latches an unexplained jump until it reverses or is confirmed; suspect flow not fed to the filter (default) | done (simulation; thresholds unmeasured) | `upin/detection/flow_integrity.py` |
| — | **Layer 149, tag landmarks** (`fiducial_e25`): our own printed tag; one tag at a surveyed spot is a full fix with accuracy from the geometry; re-anchors the reachable region; `tools/tag_truth.py` measures every other source against it | done (simulation; camera driver untested) | `upin/layers/optical/fiducial.py`, `upin/vision/upin_tag.py`, [`docs/TAGS.md`](docs/TAGS.md) |
| 8 | **L3 camera optical flow, layer 148** (`camflow_e24`): block matching plus weighted RANSAC with trust earned since takeoff; a sweeping laser-dot grid is thrown out; gyro-compensated; declines without texture, height or agreement | done (simulation; camera untested) | `upin/layers/optical/camera_flow.py`, [`docs/CAMERA_FLOW.md`](docs/CAMERA_FLOW.md) |
| — | **Layer 151, known-position beacon ranging** (`beaconrng_d27`): the balloon idea; signed, hopping beacons that broadcast their own positions and sigmas; weighted least squares with DOP; a GNSS jammer leaves it alone, a band jammer silences it, both shown | done (simulation; radio and beacon firmware not built) | `upin/layers/rf/beacon_ranging.py`, [`docs/BEACONS.md`](docs/BEACONS.md) |
| — | **Layer 150, LEO Doppler anchor** (`leodoppler_a21`): one coarse fix per satellite pass on a cheap software radio; fits position, oscillator offset and drift; refuses stale orbits, weak priors (mirror ambiguity) and fixes far from the prior (a wrong satellite fits perfectly); honest replacement path for the fabricating `leo_l19` | done (simulation; radio untested) | `upin/layers/satellite/leo_doppler.py`, [`docs/LEO_DOPPLER.md`](docs/LEO_DOPPLER.md) |
| — | **Layer 152, breadcrumb beacons** (`breadcrumb_d28`): small beacons the drone drops as jamming rises, while its fix is trusted, each stamped with its landing position and sigma; ranged to inside the jam through layer 151; never drops on an untrusted fix | done (simulation; crumb firmware and release mechanism not built) | `upin/layers/rf/breadcrumbs.py`, [`docs/BREADCRUMBS.md`](docs/BREADCRUMBS.md) |
| — | **Aerostat beacon and the carry-and-release numbers**: a `tethered` beacon kind whose stated sigma grows with wind uncertainty; `tools/compare_balloon_carry.py` → `BALLOON_CARRY.md` (balloon size, drag, deflated mass, release timeline inside a jammer, balloon-lifted drone, comparison table) | done (labelled physics, not measurements) | `upin/simulation/balloon_physics.py`, [`docs/BEACONS.md`](docs/BEACONS.md) |
| — | **Mission index**: `upin/layers/mission_catalog.py` (every honest component: gives, needs, situations, simulation figures, config, README), `tools/mission_index.py` (the index and a "what do I load" query), "When to use it" on every honest layer's page | done | [`docs/MISSION_INDEX.md`](docs/MISSION_INDEX.md) |
| 4 | L1 completion: strapdown INS wired in, retained command log (§3) | next | `upin/core/strapdown_ins.py` |
| 5 | Navigation Arbiter: explicit mode, DR time limit (§9) | | |
| 6 | Escape Manager: retrace, rally, jammer gradient, swarm spread (§10) | | |
| 7 | Army grid converter + offline map manager (§11.1–11.2) | | replaces the fake converter in `missions/target_coordination.py` |
| 8 | L3 visual odometry / optical flow (§4) | flow done as layer 148 (above); visual odometry (position from frames) not built | |
| 9 | L4 landmark matching on georeferenced maps (§5) | | builds on `lmkchain_e23` |
| 10 | L5 terrain matching (§6) | | |
| 11 | L6 swarm cooperative ranging (§7) | | |
| 12 | Datalink, console adapters, security — replaces unsafe `SecureComm` (§11.3–11.5) | | |
| 13 | Safety: corridor keep-in, swept NFZ checks, separation, readiness gate (§12) | | |
| — | L7 SUDARSHANA (§8) | roadmap only | |

Simulation results so far (not field results): L2 reached a 500 m GPS-denied
target with the truth inside its stated 95% circle ~98% of the time in gusty
air; L0 caught a 1 m/s drag-off spoof after 14 s.

## Part 3 — Raspberry Pi bench milestone

**Goal:** the Pi reads real GNSS, IMU and other sensors, outputs honest
coordinates with an accuracy circle, and keeps navigating with minimal
error when GNSS is denied in software.

**Not ready yet**, for three reasons: no hardware drivers exist; the
GPS-denied core (items 4, 5, 8) is not built; nothing has been measured on
real sensors. The code itself runs on a Pi (Python, numpy, scipy).

### Recommended hardware

Pi as companion computer to an ArduPilot flight controller — the same
arrangement the drone will fly with, so one driver path covers bench and
flight.

| Item | Role |
|---|---|
| Raspberry Pi 5 (8 GB), cooler, official supply, NVMe/high-endurance card | runs UPIN, logs everything |
| Pixhawk-standard flight controller, ArduPilot | IMU, barometer, compass over MAVLink |
| Multi-band GNSS receiver with raw-measurement output, wired to the Pi | position, C/N0, jamming indicators, later raw pseudoranges |
| NavIC-capable receiver — confirm NavIC L5 and raw output on the datasheet | sovereign signal |
| Optical-flow sensor + downward rangefinder | ground velocity and height: the main GNSS-denied error reducer |
| Downward camera | later L3/L4 work |
| Antennas, cables, power bank | moving tests |

No prices are listed: get supplier quotes. The earlier ESP32-S3 prototype
plan in `UPIN_MASTER.md` cannot run the Python stack; an ESP32 could serve
as a sensor front end feeding the Pi. The cheapest board that runs UPIN
unchanged is the Pi Zero 2 W, not yet benchmarked. The box wiring and the
device comparison are in [`docs/HARDWARE.md`](docs/HARDWARE.md).

### Steps

**Fastest path to hardware:** the box as the flight controller's GPS 2, in
shadow mode. The day-by-day plan is in
[`docs/HARDWARE.md`](docs/HARDWARE.md#first-week); a beginner's step-by-step version is [`docs/PI_GUIDE.md`](docs/PI_GUIDE.md).

1. **Core (no hardware):** items 4 and 5, and item 8 pulled forward.
2. **Drivers** in `upin/hardware/`, read-only: MAVLink reader, GNSS reader
   (NAV-PVT, NAV-SAT, MON-RF), a receiver-solved input path for L0, a
   `HardwareFeed` using the same observation names as the simulator, and a
   recorder/replayer.
3. **Pi deployment:** install script, config, systemd service, coordinates
   as local JSON plus a CSV log.
4. **Tests on the rig** — walk and drive with GNSS disabled in software
   (never real jamming outside an authorised range), logged GNSS as truth,
   replayed to measure real error. Those figures fill the spec's §13.2
   blanks.

## Fusion: HonestKalman option (awaiting decision)

`upin/fusion/honest_kalman.py` is a separate, honest Kalman filter built
beside the live engine without changing it. `FUSION_COMPARISON.md` measures
it against every fusion option in the repo on identical inputs;
`docs/KALMAN.md` explains the method and its limits. **Which option runs
live is the user's decision.** Wiring it in is a separate step.

**Backup:** the state before this work is commit `44b41a2`, pushed to
GitHub. Restore with `git checkout 44b41a2`. A named tag
`backup/pre-kalman-2026-10-05` exists locally; this session cannot push
tags, so to name it on GitHub use Releases → "Draft a new release" →
create the tag on commit `44b41a2`.

## Decisions on record

- **INSLIB (github.com/jnz/INSLIB): not adopted as code.** AGPL-3.0 would
  require publishing UPIN's source; the spec forbids others' code; and it
  holds attitude and altitude through a GNSS outage, not horizontal position.
  Useful only as a published reference. Using its code would need a
  commercial licence from the author.
- **Crypto:** the `cryptography` library will replace the homebrew
  `SecureComm` (whose signature check accepts any non-empty string).
- **Vision:** L3 in plain numpy; no OpenCV dependency.

## Research: the receiver's correlator (needs a software-defined radio)

A receiver finds each satellite by correlating a known code against noise.
With raw radio samples from an SDR, instead of a finished receiver, UPIN
could:
- watch the correlation peak's shape, where a spoofer overlapping the real
  signal distorts it (signal-quality monitoring);
- spot a second peak for one satellite;
- integrate longer with the IMU's help (aided tracking) for a few dB more
  margin against weak or distant jamming. Not against a strong nearby
  jammer.

This is research-grade work: SDR hardware, heavy processing, and our own
implementation. The well-known open GNSS SDR software is GPL, and the spec
forbids others' code. Layer 146 uses the part available today: the
receiver's own C/N0 and AGC reports.

Follow-up: newer u-blox receivers report their own spoofing-detection state.
Check the purchased receiver's datasheet and feed it in as another check if
it has one.

## Recorded for later, each with what triggers it

From the reels of 12 October 2026, built only when the trigger happens:

| Item | Trigger |
|---|---|
| Fiducial-tag landmark layer: tags at surveyed spots give a precise fix (home, landing pad, test-range ground truth for calibrating every other layer) | **built** (layer 149, 15 Oct 2026, pulled forward at the user's request; still needs the camera) |
| Same code in simulation and on the drone: ArduPilot SITL + Gazebo, extending `tools/sitl_box.py` | the box first runs against SITL (bench plan, day 1) |
| Independent GNSS-band jamming monitor with a cheap software radio (RTL-SDR): noise in the band vs a learned baseline; also the cheap way into the correlator research | GNSS hardware is on the bench and a second jamming opinion is wanted. The same dongle now serves layer 150 (LEO Doppler) |
| Weighted RANSAC inside UPIN's own camera flow, trusting points that have agreed since takeoff | **built** (layer 148, 15 Oct 2026; still needs the camera) |
| Radxa Zero 3W as a cheaper companion computer (4 cores, 2 GB, NPU, per its maker; unverified) | benchmarking the box on boards other than the Pi |

## Open decision: filter lock-out after a poisoned estimate

**Problem.** Testing the optical-flow check showed that a corrupted internal
position estimate can leave the fusion filter overconfident. Incoming GNSS
fixes then look inconsistent with the bad estimate and the box keeps
rejecting them, even when they are good. This is the "filter lock-out"
condition. It is a filter-integrity problem: the filter cannot tell an
attack from its own error.

**Original choice.** Two options were on the table: (a) reset the filter's
uncertainty so good GNSS can be accepted again, or (b) stay locked out and
keep rejecting.

**Status.** Deferred by the user on 14 October 2026. No code change now.

**Direction.** The condition will be handled by a future navigation-safety
layer rather than by a one-off filter rule. That layer will:

- score whether it is currently safe to navigate, using the box's checks
  (optical flow, GNSS consistency, dead-reckoning drift) and the filter's own
  internal state (uncertainty, time since last accepted fix, innovation
  history);
- fall back to return-to-home when the score says navigation is not safe;
- carry decision logic and further safety measures that will be designed
  from concrete use cases the user is still exploring.

**Interim posture (conscious choice, known gap).** Until the safety layer
exists, the current behaviour stands: on lock-out the box keeps rejecting
and reports the condition. This is a deliberate interim decision, not a
default. Its known gap is that a lock-out caused by internal corruption
(not an attack) leaves the vehicle holding a wrong position with no
automatic fallback.

Because of that gap:

- Real-hardware logging of lock-out frequency runs on bench, tethered or
  geofenced tests only.
- Any free flight before the safety layer exists requires a bounded guard
  first: lock-out persisting beyond a set time or distance triggers
  return-to-home. The thresholds are to be set from the logged data.
  [TO CONFIRM: thresholds not yet defined]

**What the logs must record.** For every lock-out event: time of onset,
duration, filter uncertainty at onset, number of GNSS fixes rejected, which
check first flagged the inconsistency, and how the event ended (recovered,
landed, test stopped). This data sets the thresholds for the guard above
and feeds the design of the safety-layer scoring.

**Trigger to reopen.** When the user brings the use cases for the safety
layer. The two original options (reset uncertainty vs stay locked out) are
then folded into that layer's design rather than decided in isolation.

## Known open items

- Two labelled assumptions need hardware data: compass error, and how fast a
  frozen wind estimate goes stale.
- GLONASS, Galileo, BeiDou and QZSS layers are still legacy: the simulator
  has no such constellations.
- The Army grid datum in field use must be confirmed with Army contacts.
- Licensing of Bhuvan, Survey of India and elevation data is unverified.
