# Component index: every working part of UPIN, what it does, where it is, and what it runs on

The whole working system, one table per kind. "Measured" means a
simulation figure from that component's own tests; nothing here is
flight-proven. The 114 legacy layers that invent readings are not here;
they are in [`LAYER_REGISTER.md`](LAYER_REGISTER.md) with their verdicts.

## The three places code can run

| Where | What it is | What runs there |
|---|---|---|
| **ESP32-S3** | a microcontroller: 240 MHz, under 1 MB of fast memory (up to 8 MB slower), no Linux, no Python, no numpy. Everything is a **port to C** of our own maths, nothing runs as it is | the box core: parsers, the checks, the filter, the decision, GPS_INPUT, wind dead reckoning, the beacon and formation maths, the AI predictor's inference. Marked **ESP32** below |
| **Raspberry Pi 4 / 5** | Linux, Python, numpy, scipy: the repo runs unchanged | everything above plus the camera layers, LEO Doppler, the recorder, the console, learning | marked **Pi** |
| **Mac / PC** | the ground side | the console, the replay, the summary, training the AI predictor, building patch maps; marked **PC** |

The ESP32 column is an engineering judgement from the size of each
component's maths (matrix sizes, memory, operations per second), **not a
measurement**: no port exists yet. "ESP32" means the maths fits a C port
comfortably; "ESP32 (slow)" means it fits with care; "Pi" means it does not.

## A. Position sources (an absolute fix without GNSS)

| # | Component | What it does | Needs | Measured in simulation | Where in the repo | Runs on |
|---:|---|---|---|---|---|---|
| 149 | **Tag landmarks** `fiducial_e25` | a full fix from one printed UPIN tag at a surveyed spot seen by the downward camera; re-anchors the reachable region; ground truth for the range | downward camera, attitude, a tag map (field survey or Indian source) | sub-metre while a tag is in view; an unmapped tag declines | `upin/layers/optical/fiducial.py`, `upin/vision/upin_tag.py` | ESP32 (slow): blob detection on a 256-px frame in C; Pi recommended |
| 154 | **Patch map** `patchmap_e26` | ground the drone surveyed itself on a trusted flight, matched by correlation for an absolute fix that resets the drift | downward camera, rangefinder, attitude, a flight over the same ground | 1.6 m rms flown back along a surveyed track; water, night, changed and repeating ground decline | `upin/layers/optical/patch_map.py`, `upin/vision/patch_map.py`, `tools/build_patch_map.py` | Pi (mosaic correlation, the map in memory) |
| 151 | **Beacon ranging** `beaconrng_d27` | ranges to three or more signed, hopping beacons that know their own positions (tripods, masts, tethered or free balloons), on a band GNSS jammers do not touch | ranging radio, beacons deployed, shared secret, barometer | 6 m rms with four ground beacons at 10 m ranging; a beacon-band jammer silences it, stated | `upin/layers/rf/beacon_ranging.py`, `upin/box/beacon_radio.py` | ESP32: HMAC (hardware SHA) and a 3-unknown solve; the ESP32 can be the radio node itself |
| 152 | **Breadcrumbs** `breadcrumb_d28` | small beacons the drone drops while its fix is still trusted, stamped with their landing position; ranged to on the way back through the jam | ranging radio, crumb units and a dispenser | 20 m rms along a weaving trail; never drops on an untrusted fix | `upin/layers/rf/breadcrumbs.py` | ESP32 (the crumb itself is an ESP32-class device) |
| 153 | **Formation** `formation_d29` | drones in formation compare the distances their receivers imply with the distances the radio measures: a single spoofer gives every receiver the same place and is caught; two trusted peers place a third that lost GNSS | ranging radio on every drone, two or more peers | common spoof caught every epoch; a lead placed to 12 m rms by two wingmen; a tailored spoof passes, stated | `upin/layers/rf/formation.py` | ESP32 |
| 150 | **LEO Doppler anchor** `leodoppler_a21` | one coarse fix per satellite pass from the Doppler curve of a low-orbit satellite on a cheap software radio | RTL-SDR and VHF antenna, fresh orbit elements, barometer, a still receiver | 250 m error, 190 m stated, per pass | `upin/layers/satellite/leo_doppler.py`, `upin/box/sdr.py`, `upin/box/leo_pass.py` | Pi (USB radio, FFT tracking) |
| 1, 2 | **GPS / NavIC raw** `gps_l1`, `navic_l2` | a fix from raw pseudoranges with RAIM and single-satellite exclusion | a receiver that outputs raw measurements and the ephemeris decoder (not built) | RAIM caught a 1 m/s drag after 14 s | `upin/layers/satellite/layers.py`, `gnss_receiver.py` | ESP32 (small least squares); **not wired into the box** |
| 144 | **Landmark chain** `lmkchain_e23` | a fix by resection from bearings to charted landmarks | a landmark detector (not built) and an Indian-source map | resection in simulation | `upin/layers/optical/landmark_chain.py` | ESP32 (the maths); **not wired** |

## B. Velocity sources (keep the estimate moving when GNSS is gone)

| # | Component | What it does | Needs | Measured | Where | Runs on |
|---:|---|---|---|---|---|---|
| — | **Flow chip** (box) | the flight controller's optical-flow sensor, integrity-checked against the IMU | flow sensor and rangefinder on the flight controller | 60 s denied: 4.7 m with flow against 269 m coasting | `upin/box/service.py`, `upin/detection/flow_integrity.py` | ESP32 |
| 148 | **Camera flow** `camflow_e24` | UPIN's own optical flow from the camera: block matching with weighted RANSAC, a sweeping laser-dot pattern thrown out, gyro-compensated | downward camera, rangefinder, gyro | 0.2–0.4 m/s; the moving pattern rejected | `upin/layers/optical/camera_flow.py` | ESP32 (slow) in C at a low frame rate; Pi recommended |
| — | **Wind-and-tilt dead reckoning** (box) | the lean's airspeed from a curve learned on the trusted leg, IMU-corrected for turns, plus the frozen wind; or a pitot on a fixed wing | attitude, IMU; nothing extra | 16 m after 60 s denied against 331 m coasting; a wind shift after the freeze is the limit | `upin/box/wind_dr.py`, `upin/core/wind_learner.py`, `upin/core/speed_learner.py` | ESP32 |
| 147 | **AI motion predictor** `learnedio_b14` | a small network (two hidden layers, 48 and 32, about 4,500 weights) predicting ground velocity from IMU, attitude and throttle, trained flight by flight, flagging weather outside its training | a trained model for this airframe | about 0.5 m/s inside its training | `upin/layers/inertial/learned_io.py`, `upin/learned/`, `tools/learn_from_flight.py` | **inference** ESP32 (a few thousand multiplies per window); **training** PC |
| 143 | **Command dead reckoning** `cmddr_b12` | position from the motor commands through a calibrated airframe model | the command stream and a calibration flight | 1–2 m while claiming 20–42 m | `upin/layers/inertial/command_dr.py` | ESP32; **not wired** |

## C. Checks on every GNSS fix (spoofing and jamming)

| Component | What it catches | Does not catch | Where | Runs on |
|---|---|---|---|---|
| **Physically reachable region** | a jump the airframe could not have made since the last trusted fix | a slow drag inside the envelope | `upin/detection/reachability.py` | ESP32 |
| **Filter gate** (innovation test) | a fix inconsistent with UPIN's own estimate | a drag slower than the filter's own uncertainty | `upin/fusion/honest_kalman.py` | ESP32 |
| **Constellation cross-check** | two receivers or two constellations disagreeing | a spoofer faking all consistently | `upin/detection/constellation_check.py` | ESP32 |
| **Receiver jamming report** | jamming the receiver itself notices (u-blox MON-RF / MON-HW) | anything on an NMEA receiver (no such report) | `upin/box/gnss_parser.py` | ESP32 |
| **Signal power** (146) `cn0spoof_a20` | one transmitter: powers too uniform, too strong, no rise with elevation, all jumping together, AGC dropping; tells jamming from spoofing; learns this antenna's profile | a spoofer shaping power by elevation at realistic levels; warn-only until calibrated | `upin/layers/satellite/signal_power.py` | ESP32 |
| **Optical-flow integrity** | a moving pattern under the flow sensor (jumps the IMU did not feel) | a drag hidden in IMU noise | `upin/detection/flow_integrity.py` | ESP32 |
| **Formation consistency** (153) | every receiver reporting the same place while the ranges show the formation intact; one bad receiver as the odd one out | a tailored multi-transmitter spoof | `upin/layers/rf/formation.py` | ESP32 |
| **Return validation** | GNSS must pass every check for five epochs before it is trusted again | | `upin/box/gateway.py` | ESP32 |

## D. The decision, the fusion, the links

| Component | What it does | Where | Runs on |
|---|---|---|---|
| **Gateway** | one decision per epoch: TRUSTED (the receiver's fix), DEGRADED (UPIN's own estimate with its honest, growing accuracy), NO_FIX; every check's result kept for the log and the console | `upin/box/gateway.py` | ESP32 |
| **HonestKalman** | the 7-state filter (position, velocity, altitude, heading) that fuses every source through a statistical gate and never shrinks below the receiver's accuracy | `upin/fusion/honest_kalman.py` | ESP32 (7×7 matrices) |
| **Receiver parsers** | u-blox UBX (NAV-PVT, NAV-SAT, MON-RF, MON-HW) and NMEA (GGA, RMC, GSA, GSV, GST, ZDA, NavIC as GI) | `upin/box/gnss_parser.py` | ESP32 |
| **Flight-controller reader** | attitude, IMU, barometer, flow, rangefinder, throttle, airspeed and the flight controller's own GPS over MAVLink; refuses the circular messages | `upin/box/fc_reader.py` | ESP32 (a MAVLink C library is a driver) |
| **GPS_INPUT sender** | UPIN as GPS 2 for ArduPilot, shadow mode first | `upin/box/mavlink_out.py` | ESP32 |
| **The box** | wires all of the above: one process, one config, one log line per epoch | `upin/box/service.py`, `deploy/` | Pi today; the ESP32 port would be this file in C |
| **Mission catalogue** | which layers to load for which mission, the fallback ladders | `upin/layers/mission_catalog.py`, [`MISSION_INDEX.md`](MISSION_INDEX.md) | PC (a document) |

## E. Ground tools (never on the aircraft)

| Tool | What it does | Where |
|---|---|---|
| Preflight | go / no-go on both links before a start | `tools/preflight.py`, `upin/box/preflight.py` |
| Receiver setup | enables the UBX messages on a u-blox from the Pi, verified by listening | `tools/configure_receiver.py`, `upin/box/ubx_config.py` |
| Recorder and replay | every input recorded in order; the whole box re-run with a software denial at any moment | `upin/box/recorder.py`, `upin/box/flight_replay.py`, `tools/replay_flight.py` |
| Flight summary | the receiver, the two receivers compared, UPIN's checks, every denial measured | `tools/flight_summary.py` |
| Console | the live page: every number computed, nothing made up, no foreign maps | `upin/console/` |
| Tag truth | every source measured against accepted tag fixes | `tools/tag_truth.py` |
| Learn from flight | trains and scores the AI predictor after each flight | `tools/learn_from_flight.py` |
| Simulation | a drone, a receiver speaking UBX, a jammer, spoofers, beacons, a formation, a leaning camera: the real box on simulated inputs | `upin/simulation/` |

## F. What fits where: the short answer

**An ESP32-S3 build**, as a C port of our own maths, in this order:
the parsers, the gateway and its checks (reachable region, filter gate,
cross-check, signal power, return validation), HonestKalman, GPS_INPUT,
wind-and-tilt dead reckoning with the two learners, the formation and
beacon maths with HMAC, the AI predictor's inference. That is the "light
program" that turns any GNSS receiver into a checked GPS 2 with dead
reckoning. No camera layer, no LEO Doppler, no recorder, no console. It
has not been ported; the judgement is from the size of the maths.

**A Raspberry Pi** runs everything in this index unchanged, and is what
the first flights use.

**What needs more than a Pi, by layer:**

| Layer | What it needs beyond the Pi |
|---|---|
| Tags (149), camera flow (148), patch map (154) | a downward camera and a rangefinder; daylight |
| Beacons (151), breadcrumbs (152), formation (153) | a ranging radio per node, beacon or crumb units, a shared secret; the radio firmware is not written |
| LEO Doppler (150) | an RTL-SDR dongle, a VHF antenna, fresh orbit elements |
| AI predictor (147) | a model trained on this airframe's own flights |
| GPS / NavIC raw (1, 2) and the satellite-subset check | a receiver that outputs raw pseudoranges and navigation frames (an F9-class u-blox; not the NMEA receiver on the box), plus an ephemeris decoder, not built |
| Cross-check | a second receiver that reports its accuracy (the flight controller's GPS with the u-blox driver) |
| Landmark chain (144) | a landmark detector and an Indian-source map |

## G. The most effective, by what the simulations say

For a drone with only the flight controller and the receiver: the checks
plus wind-and-tilt dead reckoning. For a drone with a camera and
rangefinder: the patch map (metres, absolute, resets the drift) and the
tags (sub-metre where placed), with camera flow between them. For a
group of drones: the formation check, the only one that catches a
single-transmitter spoof when every single-receiver check passes. For a
long denial far from the base: beacons and breadcrumbs. Every one of
those sentences is a simulation result until the first real logs.
