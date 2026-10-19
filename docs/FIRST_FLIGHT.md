# The first real data: bench, car, bird, all listening only

The goal of the first outings is **data, not control**: the UPIN box on a
real rig, reading the GNSS receiver and the flight controller, logging and
recording everything, sending nothing, so that afterwards UPIN can be
measured against the receiver and against the flight controller's own
GPS, and improved from real logs. Three outings, in this order, each with
a "done when". Nothing here makes UPIN flight-proven; it makes the first
numbers real.

> **What the box sends in listen-only mode.** Eight MAVLink
> `SET_MESSAGE_INTERVAL` requests at start, asking the flight controller
> for its sensor streams. That is all. No position, no heartbeat, no
> command that changes flight. With `--no-send` the `GPS_INPUT` sender is
> never called; the systemd unit ships with `--no-send`.

## What you need

- The Pi (4 or 5, 64-bit OS, Python 3.11+), its official supply on the
  bench and a BEC rated for it on the bird, a high-endurance card.
- The GNSS receiver on a **USB-UART adapter** (or its own USB), and the
  flight controller's TELEM port on a **second USB-UART adapter**. On the
  first flights, two USB links: stable names under `/dev/serial/by-id/`,
  no GPIO wiring, no logic-level questions. A powered hub if the Pi's USB
  browns out.
- The flight controller with ArduPilot, flying on its own GPS as always.
- Optional, later: a downward camera and rangefinder. Not for the first
  clean data.

## 1. Bench: the kitchen table

Done when `tools/preflight.py` says GO and a `--no-send` run reaches
TRUSTED by a window.

```bash
cd /opt/upin                        # after deploy/install.sh (PI_GUIDE Steps 1-6)
ls /dev/serial/by-id/               # the receiver's and the flight controller's names
sudo nano /etc/upin/box.toml        # receiver_port, fc_connection, airframe limits, airframe_id
sudo -u upin venv/bin/python tools/preflight.py --config /etc/upin/box.toml
```

The preflight measures: Python and the libraries; the config; the ports;
**the receiver**: what arrives in ten seconds (NAV-PVT, NAV-SAT, MON-RF or
MON-HW, rates, bad checksums, NMEA-only), the fix, the satellites, the
stated accuracy, the receiver's own UTC; **the flight controller**: a
heartbeat, who it is, every stream's rate against what was asked,
whether its GPS reports an accuracy, which optional streams are absent;
**the disk**. NOTE lines are facts; NO-GO lines must be fixed.

**Your receiver speaks NMEA, not u-blox binary.** The box reads it as it
is: GGA (position), RMC (velocity), GSA (3-D and DOP), GSV (every
satellite's signal strength, NavIC included, for the signal-power check)
and GST if the receiver can send it (its own accuracy). Make sure those
sentences are on at 1 to 5 Hz in the receiver's own software; set
`receiver_protocol = "nmea"` (or leave `auto`). Without GST the receiver
states no accuracy, so the box assumes HDOP times `nmea_uere_m` (3 m, a
labelled assumption) and every record says so; if the receiver has a GST
option, turn it on. NMEA carries no jamming state and no raw
pseudoranges: those checks read NOT RUN, honestly. The flight controller's
own GPS is still the second receiver for the cross-check.

For a u-blox receiver that sends only NMEA, UBX can be enabled from the
Pi and verified by listening (not needed for yours):

```bash
sudo -u upin venv/bin/python tools/configure_receiver.py \
     --port /dev/serial/by-id/usb-u-blox_... --target usb --hz 5
```

`--target` is the receiver's own name for the port the Pi is on: `usb`
for a USB cable, `uart1` for a serial lead through an adapter. The script
sends CFG-RATE, CFG-MSG for the four messages, CFG-CFG to save, then
listens ten seconds and reports what now arrives; it never claims success
from the send alone.

If the preflight says the flight controller's GPS reports no accuracy:
in the ground station, set its `GPS_TYPE` to the u-blox driver if the
receiver is a u-blox (not auto, not NMEA), so ArduPilot fills the accuracy
fields. Without them UPIN's cross-check reads NOT RUN and the summary says
so; the flight still gives data.

Then the run itself, by hand:

```bash
sudo -u upin venv/bin/python -m upin.box.service --config /etc/upin/box.toml --no-send
```

Every ten seconds it prints one status line: epochs, the fix, satellites
and accuracy, UBX frames and bad checksums, the mode, each flight-
controller stream's rate, the recorder's size, free disk, and a plain
warning if the receiver has gone silent or the heartbeat has stopped.
Stop with Ctrl-C: it closes cleanly and prints what it saved. One log
file per run: `/var/log/upin/box-<date>-<time>.jsonl` and
`inputs-<date>-<time>.jsonl`.

## 2. Car: what you already did with the flight controller

Done when the summary shows the two receivers a few metres apart, UPIN
TRUSTED most of the time, and the software denial's error as a number.

Put the rig in a car: the flight controller powered and **unarmed**, its
GPS and the box's receiver with sky view (on the dashboard or the roof),
the Pi on the BEC or a USB power bank. Run the preflight, then:

```bash
sudo -u upin venv/bin/python -m upin.box.service --config /etc/upin/box.toml \
     --no-send --deny-after 180 --deny-for 120
```

Drive twenty minutes with turns. After three minutes of TRUSTED the box
denies GNSS to itself for two minutes (the receiver keeps logging; the
flight controller never knows), then lets it back. Afterwards, on the
Mac:

```bash
python tools/flight_summary.py box-<date>.jsonl --report car.md
python tools/replay_flight.py --config box.toml --log inputs-<date>.jsonl --deny-from 600 --deny-for 60
```

`car.md` gives the receiver's figures, the box receiver against the
flight controller's GPS, UPIN's modes and every check, and the denial's
error at +30, +60 and +120 s against the receiver's own fix. The replay
tries other denial moments on the same recording. In a car the wind
learner has no lean to learn from, so the denial will show coasting; that
is expected and is still the first real coasting number.

## 3. Bird, listening only

Done when a normal mission with turns, one software denial and the
recording on comes back with a summary and a replay.

- The flight controller flies on its own GPS as always. Change **nothing**
  that gives UPIN authority: `GPS2_TYPE` stays as it is, no
  `GPS_AUTO_SWITCH` or `GPS_PRIMARY` changes. Only the TELEM port's
  `SERIALn_PROTOCOL = 2` and `SERIALn_BAUD` matching `fc_baud`, and
  `GPS_TYPE` for the accuracy fields (above).
- Mount the Pi, the receiver's antenna with sky view and clear of the
  flight controller's antenna, the two USB links strain-relieved. Power
  the Pi before arming so the preflight and the heartbeat happen on the
  ground; run the service (or `systemctl start upin-box`, which runs with
  `--no-send`) with recording on and a `--deny-after 180 --deny-for 120`
  if the mission is long enough. The denial lives inside the box; the
  aircraft never sees it.
- Fly a normal mission with turns, a few minutes, as you would anyway.
  **Legal and safe:** fly where you are permitted; never a jammer, ever;
  software denial only.
- Land, stop the service (`systemctl stop upin-box` or Ctrl-C), copy the
  logs.

## 4. The data back

Copy from the Pi, per run: `/var/log/upin/box-<date>.jsonl`,
`inputs-<date>.jsonl`, `frames-<date>/` if a camera was fitted,
`preflight-<date>.json`, and the flight controller's `.bin` log. Run the
summary and the replay yourself, then send the files.

What happens with them: the summary and the replay become the first real
rows in `ROADMAP.md` (the receiver's accuracy, the two-receiver
difference, UPIN's TRUSTED fraction, the denial error); the flight
controller's `.bin` feeds `tools/learn_from_flight.py`, the AI motion
predictor's first real training and the first test of the real-log
parser; the signal-power layer gets its first real sky to learn from; and
every assumption that the logs contradict gets replaced by a measurement.

## Limits, stated

- Everything in the live path meets real hardware for the first time on
  your bench. The preflight exists so that meeting is informative; the
  UBX field offsets follow the M8/F9 layouts, and the preflight prints
  what it decodes so a wrong layout shows as wrong numbers, not silence.
- The receiver configuration script is written from the published UBX
  protocol and verified by listening, never assumed.
- A car gives no lean, so no wind learning and no wind dead reckoning;
  the bird does.
- Nothing becomes flight-proven by these outings. They make the first
  numbers real, which is the point.
