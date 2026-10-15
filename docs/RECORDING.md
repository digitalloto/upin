# Flight recording and offline replay: the zero-risk way to test every layer

The concept documents' test roadmap in two steps: **fly the normal route
in shadow mode and record everything; then re-run the whole box on the
ground with GNSS denied in software from any moment, and measure every
source against the receiver's own logged fix.** This is that, for every
sensor the box reads.

> **Status: tested on simulated flights through the real box.** The
> recorder and the replay run on the console's simulation (every sensor
> simulated, every layer live). Disk and write rates on a real Pi are
> unmeasured. Nothing is flight-proven.

## Record

In `box.toml`:

```toml
input_log_path = "/var/log/upin/inputs.jsonl"   # every input, in order
frames_dir = "/var/log/upin/frames"             # camera frames, <t>.npy
frame_record_hz = 2.0                           # ASSUMPTION; see below
```

The recorder (`upin/box/recorder.py`) writes **what the box received, in
the order it received it**: every flight-controller message (attitude,
IMU, barometer, flow, rangefinder, the flight controller's own GPS,
airspeed), every beacon-radio line, every saved camera frame (with its
field of view), and every receiver epoch as the box parsed it. A header
line carries the config the flight was flown with. The box's own epoch log
(`log_path`) is unchanged and still the thing to send after a Step 9 test.

Sizes, labelled estimates until measured on the Pi: a 256-pixel float32
frame is 256 KB, so 2 Hz is about 30 MB a minute; the flight-controller
stream at 10–50 Hz is under 1 MB a minute. When the card's free space
falls below 500 MB (an assumption) the recorder stops saving frames and
writes why; **the box, its epoch log and the flight carry on**.

## Replay

```bash
python tools/replay_flight.py --config box.toml --log inputs.jsonl --frames frames/
python tools/replay_flight.py --config box.toml --log inputs.jsonl --frames frames/ \
    --deny-after 60 --deny-for 120 --report denied.md
python tools/replay_flight.py --config box.toml --log inputs.jsonl --deny-from 250 --deny-for 60
```

The replay (`upin/box/flight_replay.py`) builds a fresh box from the same
`box.toml` and calls the same methods the live loop calls, in the recorded
order. `--deny-after` and `--deny-for` work as the live software denial;
`--deny-from` denies from a recording time. The receiver kept logging, so
during the denial UPIN's output is measured against **the receiver's own
fix** (whose stated accuracy is the reference's). The report gives the
mode timeline, the error at +30, +60 and +120 s, which velocity source fed
the filter each second (flow chip, camera flow, AI predictor, wind DR,
coasting), which position fixes were accepted (tags, beacons, crumbs,
formation, patch map), and every check that failed.

The console replays a recording through the whole box, in time:

```bash
python -m upin.console --source replay --config box.toml --log inputs.jsonl --frames frames/
```

A plain epoch log still replays the GNSS decisions only, as before.

## What was measured

| | |
|---|---|
| A 70 s console-sim run with a spoof and a denial, every frame saved (1,750 flight-controller messages, 840 radio lines, 140 frames, 37 MB) | the replay reproduced every mode and every accepted fix, positions identical to the centimetre (frames are saved as float32) |
| A denial injected at t = 40 s for 30 s into a clean recording | 30 DEGRADED epochs; error against the receiver's logged fix 2.2 m mean, 4.0 m worst; the flow chip fed the filter every second; beacon and formation fixes accepted every second |
| The live-style schedule (`--deny-after 20 --deny-for 10`) | 10 denied epochs starting after 20 s of TRUSTED |
| A config for another airframe | refused: the learned curves and models would not match |
| Free space below the limit | frames stop with a note; the log and the box carry on |

`python tests/test_recording.py` reproduces every row.

## Limits, stated

- A replay reproduces the live decisions exactly only when every frame was
  saved (`frame_record_hz` at or above the camera rate). At 2 Hz the camera
  layers replay on fewer frames than they had in flight, and the report
  says so.
- The signal-power layer's per-satellite learning is not replayed; its
  verdict travels inside each recorded epoch and the gateway acts on it as
  it did.
- Models learned in flight (the tilt-to-airspeed curve) start from the
  file the config names, as they did live, and are re-learned during the
  replay.
- The reference is the receiver's fix, not the truth. On the authorised
  range the tags (`tools/tag_truth.py`) are the independent truth.

## Files

| | |
|---|---|
| `upin/box/recorder.py` | the recorder: input log, frames, the disk cap |
| `upin/box/flight_replay.py` | the replay and the report |
| `tools/replay_flight.py` | the command line |
| `upin/console/sources.py` (`ReplaySource`) | the console's full replay |
| `tests/test_recording.py` | every figure above |
