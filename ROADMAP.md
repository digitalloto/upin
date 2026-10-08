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
| — | Sensor requirements and operating class for all 140 layers (`upin/layers/requirements_catalog.py`) | done |
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
| 4 | L1 completion: strapdown INS wired in, retained command log (§3) | next | `upin/core/strapdown_ins.py` |
| 5 | Navigation Arbiter: explicit mode, DR time limit (§9) | | |
| 6 | Escape Manager: retrace, rally, jammer gradient, swarm spread (§10) | | |
| 7 | Army grid converter + offline map manager (§11.1–11.2) | | replaces the fake converter in `missions/target_coordination.py` |
| 8 | L3 visual odometry / optical flow (§4) | | |
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

## Known open items

- Two labelled assumptions need hardware data: compass error, and how fast a
  frozen wind estimate goes stale.
- GLONASS, Galileo, BeiDou and QZSS layers are still legacy: the simulator
  has no such constellations.
- The Army grid datum in field use must be confirmed with Army contacts.
- Licensing of Bhuvan, Survey of India and elevation data is unverified.
