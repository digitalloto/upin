# AI motion predictor (layer 147): learning from every test flight

Like a small model that predicts the next character from the text so far,
this layer predicts the drone's **next move** from the last second of its
IMU, attitude and throttle. It is trained on the drone's own test flights
and gets a new chance to improve after every flight.

> **Status: built and tested on simulated flights only.** No real flight log
> has been through it yet. Nothing here says how well it will do on the
> real drone. The first real numbers come from your own logs, recorded in
> the library's `LEARNED_IO.md`.

## How it fits in UPIN

- **It predicts the move, not the coordinate.**
  - It predicts a velocity: how fast and which way, through the air.
  - The wind is added to get ground velocity, and the Kalman filter adds
    that move to the last fix.
  - A model cannot learn absolute coordinates from motion sensors.
- **It is another sensor inside the Kalman filter, not a replacement.**
  - It gives a velocity and **how sure it is**.
  - The filter weighs it against everything else, and its consistency gate
    rejects it when it is clearly wrong.
- **It knows its weather.** Every model records the wind, gusts,
  temperature and manoeuvres it was trained in. In flight:
  - inside that range: normal;
  - outside it: flagged with the numbers (for example "wind 3.8 m/s:
    outside training (up to 2.9)"), and its uncertainty is doubled;
  - far outside: it declines.
- **Off by default.** It feeds the box only when `learned_io_model` is set
  in `box.toml`.

## After each test flight

1. Copy the flight's `.bin` log from the flight controller's SD card.
2. Optionally write `notes.json` with anything worth keeping with the
   flight:
   ```json
   {"payload_kg": 0.4, "site": "Test range A", "imd_weather": "NW 15 km/h, 31 C"}
   ```
3. Run:
   ```bash
   python tools/learn_from_flight.py flight.bin --airframe my-quad-1 --notes notes.json
   ```
4. Read `upin_flights/LEARNED_IO.md`. For this flight it shows:
   - **the weather, measured:** wind and gusts from the Wind Learner,
     temperature from the barometer, plus your notes;
   - **the score before learning:** how the live model did on this flight,
     which it had never seen, with drift over 30, 60 and 120 s GNSS-free
     stretches against plain coasting, and how often the truth stayed
     inside its stated circle;
   - **the new version:** whether it was promoted. A new version goes live
     only if it is **no worse** on the validation flights; otherwise the old
     one stays and the reason is written down.
5. When the record shows it is good enough, set `learned_io_model` in
   `box.toml` to the live model path the tool prints.

Every third usable flight is kept for **validation** and never trained on,
so the comparison stays honest. Every model version is kept.

**For the wind to be measurable**, each flight needs a few steady straight
legs (12 s or more each) on different headings while GNSS is good. A flight
without them is kept but not trained on, and the record says why.

## What the library refuses

- **Two airframes in one library:** a model learns one airframe.
- **Simulated and real flights in one library.**
- **The same flight twice.**

## Try it now, without a drone

```bash
python tools/learn_from_flight.py --simulate 8 --library sim_flights
```

This builds a library of **simulated** flights and shows the whole cycle.
In one such run of 10 simulated flights:
- velocity error on unseen flights fell from 0.97 to 0.64 m/s;
- median drift after 30 s without GNSS was about 8–12 m, against about
  70–130 m coasting.

**These are simulator numbers.** A model trained on the simulator learns
the simulator.

## Honest limits

- **Learned conditions only:** it knows only the airframe, payload and
  weather it has flown in. The weather flag is there for that.
- **Persistent errors:**
  - its errors persist from second to second, and a frozen wind's error
    persists for the whole outage;
  - the learning record measures the persistence on validation flights and
    uses it to size the drift circle (in simulation, 83–100% coverage once
    validated, but poor before any validation flight exists);
  - inside the box's filter, the wind error is still treated as noise. The
    record and the box logs show the real effect.
- **Log parsing untested:** reading real ArduPilot `.bin` logs is untested
  until the first real log. Field names (`IMU.AccX`, `ATT.Roll`,
  `GPS.Spd`, `CTUN.ThO` ...) can differ between firmware versions.
- **Box input units:**
  - in the box, `RAW_IMU` is read as milli-g and milli-rad/s, which is what
    ArduPilot sends; check on your firmware;
  - throttle is taken as the mean of motors 1–4, which assumes a quad.
- **Old module, do not use:** `upin/core/cnn_gru_compensation.py` claims "8 cm
  accuracy" and invents its visual features with random numbers. This layer
  does not use it, and it should not be used.

## Files

| | |
|---|---|
| `upin/layers/inertial/learned_io.py` | the layer: prediction, weather and input checks, declines |
| `upin/learned/inertial_net.py` | the network (plain numpy), uncertainty training and calibration |
| `upin/learned/features.py` | what it reads, what it is taught |
| `upin/learned/flight_library.py` | flights, weather, versions, the learning cycle, the record |
| `upin/learned/sim_flights.py` | simulated flights, for testing only |
| `tools/learn_from_flight.py` | the after-flight command |
| `tests/test_learned_io.py` | contract, learning loop, no silent regressions, weather flag, box path |
