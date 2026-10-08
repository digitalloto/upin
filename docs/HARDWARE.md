# The UPIN box: hardware

A small computer between the sensors and the flight controller. The GNSS
receiver plugs into the box, not the flight controller. UPIN checks every
fix and gives the flight controller a position it can trust, its own
estimate with an honest accuracy, or no fix at all.

> **Status: software only.** Everything below has run in simulation and on
> synthetic byte strings. Nothing has touched a receiver, a flight
> controller or ArduPilot SITL. Nothing here is flight-proven.

## The wiring

```
                         ┌──────────────── UPIN box (Raspberry Pi) ────────────────┐
 GNSS receiver ──UART/USB──▶ gnss_parser ─▶ gateway ─────────────▶ mavlink_out ──UART──▶ flight controller
 (2nd receiver, optional) ─▶   UBX / NMEA     │  1 receiver has a 3-D fix?        GPS_INPUT        (ArduPilot,
                         │                    │  2 receiver reports jamming?                         GPS type = MAV)
 optical flow,           │                    │  3 constellations agree?                                  │
 rangefinder ──I2C/UART──▶ feed_velocity ────▶│  4 physically reachable?                                  │
                         │                    │  5 consistent with UPIN's estimate?                       │
 camera (later) ───CSI/USB▶ L3 / L4 layers    │  → TRUSTED / DEGRADED / NO_FIX                            │
                         │                    ▼                                                           │
                         │                 log (JSON lines) ──▶ replay                                    │
                         │                                                                                │
                         │◀──────────────── MAVLink: IMU, baro, compass, attitude ────────────────────────┘
                         └─────────────────────────────────────────────────────────────────────────────────┘
```

### Getting the sensor data in: three paths, all standard

1. **From the flight controller over MAVLink** (one UART or USB cable). The
   flight controller already reads its IMU, barometer and compass, and can
   read optical flow and a rangefinder. It streams them as MAVLink messages
   (`ATTITUDE`, `RAW_IMU`, `SCALED_PRESSURE`, `OPTICAL_FLOW`,
   `DISTANCE_SENSOR`). The reader is roadmap step 2 (`upin/hardware/`) and
   is not written yet.
2. **Sensors wired straight to the Pi** (UART, I2C, USB): the GNSS
   receiver, a second receiver, a camera.
3. **GNSS in the middle**, the box itself: the receiver goes to the Pi.
   `upin/box/gateway.py` decides and `upin/box/mavlink_out.py` sends
   `GPS_INPUT`. ArduPilot accepts that message as a GPS when the GPS type
   parameter is set to MAV (`GPS1_TYPE = 14` on recent firmware; older
   firmware uses `GPS_TYPE`, so check the firmware actually in use).

**If the box fails**, `GPS_INPUT` stops. The flight controller sees GPS lost
and runs its own failsafe, as it would if a GPS cable came loose.

**Degraded mode is off by default.** When GNSS is distrusted, the box
sends *no fix*. `forward_degraded=True` sends UPIN's own estimate with its
growing `h_acc` instead. Turn that on only after testing in SITL how
ArduPilot's EKF weights it.

## What the checks catch, and what they do not

| Check | Catches | Does not catch |
|---|---|---|
| Receiver 3-D fix and accuracy | lost signal; poor geometry | anything the receiver itself believes |
| Receiver jamming state (`MON-RF`) | jamming the receiver notices | spoofing, which looks clean |
| Constellations agree (`upin/detection/constellation_check.py`) | a spoofer faking one constellation; with three or more, it names that one | **a spoofer faking all constellations consistently.** Commercial multi-constellation simulators can do this. Agreement raises the cost of an attack; it does not make spoofing impossible |
| Reachability (`upin/detection/reachability.py`) | any jump the airframe physically could not make. No statistics: an honest fix never fails it (0 of 11,600 in simulation) | a slow drag-off within what the airframe could fly |
| Kalman innovation gate | drift beyond UPIN's own uncertainty | drift slower than that uncertainty grows; and spoofing from power-on, before any trusted fix |

The cross-constellation check runs **every epoch**, not every few minutes,
because it costs almost nothing.

The slow drag-off is the hardest case. L0's gate checks against an
independent reference and caught a 1 m/s drag-off after 14 s in simulation
(`tests/test_gnss.py`). Motion sensors, dead reckoning, landmarks and
terrain are all independent of GNSS and add further cross-checks.
Direction-of-arrival with an antenna array is the strongest check, and is a
later item.

### Per-constellation fixes: how to get them

The constellation check needs one fix per constellation, solved from that
constellation alone. A receiver's normal output blends all constellations
into one fix, and that fix cannot be split afterwards. Two ways to get
separate fixes:

- **Two receivers**, each configured to track one constellation (e.g. one
  GPS-only, one NavIC-only). Each one's NAV-PVT becomes a
  `ConstellationFix`. This works with the code as it stands.
- **The flight controller's own GPS as the second receiver.** The box
  service does this automatically: when the flight controller's GPS
  (`GPS_RAW_INT`) reports its accuracy, its fix is cross-checked against the
  box's receiver every epoch. **Caveat:** two receivers tracking the same
  constellations at the same place see the same spoofer, so this alone
  catches a faulty receiver or antenna, not area spoofing. To make it a
  constellation check, split the constellations: for example, set the
  flight controller's receiver to Galileo + BeiDou with ArduPilot's
  `GPS_GNSS_MODE` bitmask, and the box's receiver to GPS + NavIC. Check that
  parameter's bit values in your firmware's documentation.
- **One receiver with raw-measurement output**, solved per constellation by
  the L0 solver (`upin/layers/satellite/gnss_receiver.py`). Not possible
  yet: computing satellite positions from the broadcast ephemeris is not
  built.

## What runs where

| | Runs | How much of UPIN |
|---|---|---|
| **ESP32** | Nothing of UPIN as built | 0%. UPIN is Python with numpy and scipy, which needs Linux. An ESP32 could later be a LoRa radio front end, or run C++ ports of the reachability check and the 7-state filter |
| **Raspberry Pi** | All of UPIN's code | All 140 layers run. But only the honest components below are useful on real sensors, and only they run in the box service |

What the box service uses on real data, today:

| Used | From | Status |
|---|---|---|
| Fix checks, reachability, constellation cross-check, return validation | `upin/box/gateway.py`, `upin/detection/` | tested in simulation |
| HonestKalman: GNSS, heading, barometer, optical-flow velocity | `upin/fusion/honest_kalman.py` | tested in simulation |
| UBX parser; replay | `upin/box/gnss_parser.py`, `replay.py` | tested on synthetic bytes |
| Flight-controller reader; `GPS_INPUT` | `upin/box/fc_reader.py`, `mavlink_out.py` | UNTESTED until SITL |

Not used yet, and why:

| Not used | Why |
|---|---|
| L0 GPS/NavIC layers | they need raw pseudoranges plus satellite positions from the broadcast ephemeris; that decoder is not built |
| Landmark chain (L4) | needs a camera and georeferenced maps |
| Command dead reckoning | needs the flight controller's command stream mapped in; next step |
| Wind and speed learners | ready, but not yet wired into the service |
| Quantum layers | laboratory hardware |
| **The 114 layers that fabricate readings** | **must stay off the drone**: they invent positions when nothing is connected. The box service does not load them |

## UPIN as GPS 2: connecting it

```
new GNSS receiver ──UART/USB──▶ Pi (UPIN box) ◀──── MAVLink, one UART ────▶ flight controller
                                                  sensors in ◀─┘ └─▶ GPS_INPUT out
```

One cable to a TELEM port carries both directions.
- **In:** the flight controller's heading, barometer, optical flow, rangefinder and its own GPS.
- **Out:** `GPS_INPUT`, which ArduPilot files as GPS 2.

**What the box refuses to read.** `GLOBAL_POSITION_INT`, `LOCAL_POSITION_NED` and `GPS2_RAW` are ignored on purpose (`upin/box/fc_reader.py`). Once the flight controller uses the box's GPS, its own position is partly made from UPIN's output. Feeding it back would let UPIN confirm itself.

### ArduPilot parameters

Names follow ArduPilot 4.5 and later. **Check each one against your firmware's parameter list** before setting it.

| Parameter | Shadow mode (first) | Why |
|---|---|---|
| `SERIALn_PROTOCOL` | 2 | MAVLink 2 on the TELEM port wired to the Pi (`n` = that port) |
| `SERIALn_BAUD` | 921 | 921600 baud; must match `fc_baud` in the box config |
| `GPS2_TYPE` | 14 | GPS 2 is MAVLink: the box. Older firmware: `GPS_TYPE2` |
| `GPS_AUTO_SWITCH` | 0 | never switch receivers |
| `GPS_PRIMARY` | 0 | fly on GPS 1, the flight controller's own |

**Shadow mode** means the drone keeps flying on its own GPS. The box runs, logs, and sends GPS 2, which the flight controller shows but does not navigate on. Making UPIN the primary GPS comes later. It changes the flight controller's navigation source, so it is your decision, made after the SITL tests and bench logs.

## Which computer

| Device | Runs UPIN? | Use |
|---|---|---|
| **ESP32 / ESP32-S3** | **No.** It has no Linux, about 0.5 MB of internal RAM (a few MB more on modules with PSRAM), and no numpy or scipy | A sensor front end, or a small GNSS-in-the-middle bridge rewritten in C++. Small pieces such as the reachability check or a 7-state Kalman filter could be ported later; the full stack cannot |
| **Raspberry Pi Zero 2 W** | Yes, unchanged: Linux, quad-core, 512 MB | The cheapest board that runs it. Expected to be enough for GNSS + IMU + fusion + the box checks; **not yet benchmarked** |
| **Raspberry Pi 4 / 5** | Yes | Needed once the camera layers (L3 optical flow, L4 landmarks) run. The bench milestone in `ROADMAP.md` uses a Pi 5 |

No prices are listed. Get quotes from Indian distributors.

## Bench parts for the box

| Part | Why |
|---|---|
| Pi (above), official power supply, high-endurance card | runs the box, logs every epoch |
| GNSS receiver with UBX output (NAV-PVT, NAV-SAT, MON-RF) | the parsers are written for UBX; NMEA GGA/RMC works as a fallback without the jamming state |
| A second receiver, or one with NavIC (check the datasheet for NavIC L5) | the constellation cross-check |
| Pixhawk-standard flight controller with ArduPilot, or ArduPilot SITL on a laptop first | the `GPS_INPUT` path |
| Optical-flow sensor and downward rangefinder | keep the degraded estimate tight. In simulation, 60 s with no GNSS gave an `h_acc` of 269 m coasting and 4.7 m with flow velocity (the flow sigma of 0.3 m/s is assumed, not measured). The coasting figure is set by the filter's assumed manoeuvre noise and is pessimistic for a steady flight |
| USB-UART adapters, antennas, cables | |

**Before trusting any field result**, check the UBX field offsets in
`upin/box/gnss_parser.py` against the interface description of the
receiver actually bought. They follow the M8/F9 generation descriptions.

## Running it

On the Pi (after `deploy/install.sh`; see `deploy/README.md`):

```bash
python -m upin.box.service --config /etc/upin/box.toml --no-send    # listen and log only
python -m upin.box.service --config /etc/upin/box.toml              # shadow: send as GPS 2
python -m upin.box.service --config /etc/upin/box.toml --deny-after 60 --deny-for 120
    # trusted 60 s, then GNSS denied in software for 120 s: the GPS-denied test
```

Tests and replay, anywhere:

```bash
python tests/test_box.py                   # parsers, gateway, GPS_INPUT, replay
python tests/test_box_service.py           # FC reader, the service logic, config
python tests/test_reachability.py
python tests/test_constellation_check.py

# replay a capture from the receiver's port, or the box's own JSON-lines log
python -m upin.box.replay capture.ubx  --accel 6 --airspeed 20
python -m upin.box.replay epochs.jsonl --accel 6 --airspeed 20   # also reads the service log
```

`--accel` and `--airspeed` are the airframe's limits: its maximum
horizontal acceleration and its top airspeed. Take them from the
airframe's spec or from `Envelope.from_airframe(thrust_to_mass,
max_airspeed)`. Never tune them to make a result look better. Limits set
too tight cause false alarms; limits set too loose let more through.

## First week

| Day | What | Done when |
|---|---|---|
| 1 | ArduPilot SITL on a laptop (Linux or WSL is easiest). Run `python tools/sitl_box.py --set-params`, restart SITL, run `python tools/sitl_box.py` | All three checks print `[ok]`: GPS 2 shows UPIN's fix; it drops when the box sends no fix; it is reported lost when the box goes silent |
| 2 | Pi set up with `deploy/install.sh`. Receiver on its port with NAV-PVT, NAV-SAT and MON-RF enabled. Run the service with `--no-send` | The logged positions and accuracy match the receiver's own software |
| 3 | Bench, propellers off: Pi wired to the flight controller, parameters as above, shadow mode | The ground station shows GPS 2. The log has heading, barometer, the flight controller's GPS and UPIN's mode every epoch. The drone still uses GPS 1 |
| 4–5 | Walk or drive the rig with `--deny-after 60 --deny-for 120` (trusted, then denied in software, then back). Replay the logs | Real error with GNSS denied, measured against the logged GNSS. Those figures go into `ROADMAP.md` |

Never jam real signals outside an authorised range: `--deny-after` drops
GNSS in software. A beginner's version of these steps, from unboxing the
Pi, is in [`PI_GUIDE.md`](PI_GUIDE.md).
