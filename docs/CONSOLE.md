# The UPIN console

A live page that shows what the UPIN box is doing:
- its mode (TRUSTED, DEGRADED or NO_FIX) and why;
- each check on the current fix;
- a map with UPIN's position, its accuracy circle and the
  physically-reachable region;
- the GNSS input and the flight-controller sensors.

It runs on a Mac, a Pi or any computer with Python 3.11+, and is opened in
any browser.

## No made-up numbers

The old phone demo (`upin_phone_demo.html`, `replit_demo/`) displayed
random numbers as fusion results, confidence and accuracy, and invented a
GPS fix when no real one was available. **Do not use those to judge UPIN.**
The console replaces them.

| Rule | How it is kept |
|---|---|
| Every number comes from UPIN or a sensor | The page only draws what the server sends. The server only sends what the box, gateway and filter computed (`upin/console/state.py`) |
| Missing stays missing | A sensor that is not connected shows "not connected", never a number. A check that could not run shows NOT RUN and says why |
| Simulation is always labelled | A striped SIMULATION banner on every simulated page. The true position exists only in simulation and is labelled "simulated truth" |
| No randomness, no outside services | `tests/test_console.py` fails if the page's files contain random-number calls, Google, or anything loaded from the internet |

## What it can show: five sources

```bash
python -m upin.console --source sim                       # simulated drone, no hardware
python -m upin.console --source browser                   # this computer's or phone's location
python -m upin.console --source board  --config box.toml  # your flight controller on USB
python -m upin.console --source live   --config box.toml  # the full box
python -m upin.console --source replay --config box.toml --log box.jsonl
```

Then open **http://localhost:8080**.

| Source | Data | What it is good for |
|---|---|---|
| `sim` | **Simulated** sensors: a drone flying a circuit, with buttons for a 500 m spoof jump, a slow 1 m/s drag-off spoof, simple or smart spoofer, GNSS jamming, and optical flow on/off; a simulated sky of 10 satellites for the signal-power layer. It speaks the receiver's UBX protocol and the flight controller's MAVLink fields, so it goes through the same parser and checks as real data | Seeing every behaviour today, with no hardware |
| `browser` | **Real**: this device's location from the browser (the part of the old demo that was real). The browser's 95% accuracy is converted to 1σ | A real moving input from a laptop or phone. Laptop and phone positioning is far less accurate than a GNSS receiver |
| `board` | **Real**: the flight controller's own GPS, heading, barometer, flow and rangefinder, over USB. Listen only | Testing with just your board, before the new receiver arrives |
| `live` | **Real**: the full box (new receiver + flight controller) | The bench and the drone |
| `replay` | **Real**: a box log, re-decided by today's code (GNSS decisions only) | Looking at a test run again |

Notes:
- `board` and `live` need `pip install -e ".[box]"`, which adds pyserial and pymavlink.
- On the bench, the flight controller's USB port appears on a Mac as `/dev/cu.usbmodem…`. Put that in `fc_connection` in the config.
- **Untested on hardware:** the `board` and `live` sources use the box's MAVLink and serial code, which has not yet met a real flight controller.

## Signal-power chart (layer 146)

Each dot is one satellite, as reported by the receiver (UBX NAV-SAT): its
signal strength (C/N0) against its elevation. A real sky rises from left to
right. Once the layer has learned this antenna on trusted fixes, the dashed
line shows that profile. Below the chart is the verdict (CLEAR, SUSPECT
SPOOFING, JAMMING or NOT RUN) with the tests that fired.

In simulation, *Spoofer type: simple/smart* switches the spoofer:
- **simple:** one transmitter, uniform power. The layer flags it.
- **smart:** power shaped by elevation, like a real sky. The layer does
  **not** catch it, and the console shows that rather than hiding it.

A source without NAV-SAT (the browser, or a board-only run) shows an empty
chart that says so.

## Using it on the Mac first

1. **Python 3.11 or newer.** The Mac's built-in `python3` is often older:
   check with `python3 --version`. If it is below 3.11, install Python from
   python.org.
2. Get the code and install it:
   ```bash
   git clone -b claude/patent-application-spec-sEgOc https://github.com/digitalloto/upin.git
   cd upin
   python3 -m venv venv
   venv/bin/pip install -e ".[box]"
   ```
3. Simulation first:
   ```bash
   venv/bin/python -m upin.console --source sim
   ```
   Open http://localhost:8080. Press the spoof and jamming buttons and watch
   the mode, the checks and the circles change.
4. Then your own location:
   ```bash
   venv/bin/python -m upin.console --source browser
   ```
   Press *Share this device's location*. Browsers share location only on
   `localhost` or https, so open the page on the same Mac.
5. Then the board on USB:
   - find its port with `ls /dev/cu.usbmodem*`;
   - make a `box.toml` from `deploy/box.example.toml` with `fc_connection` set to that port;
   - run:
     ```bash
     venv/bin/python -m upin.console --source board --config box.toml
     ```

## On the Pi, viewed from the Mac

```bash
python -m upin.console --source live --config /etc/upin/box.toml --host 0.0.0.0
```

Then open **http://upin-box.local:8080** on the Mac. The *Deny GNSS* button
appears only with `--allow-control`, so nobody on the network can change
what the box does by accident.

## Maps

By the project's rule, **no Google Maps and no non-Indian map sources**.
The map is UPIN's own drawing, with no external library. With no basemap
it shows a metre grid and a scale bar, which works offline in the field.

An Indian tile source can be added with
`--tiles "https://…/{z}/{x}/{y}.png" --tiles-attribution "…"`, for example
Bhuvan (ISRO/NRSC). Only add one once its licence for this use is
confirmed: Bhuvan, Survey of India and elevation-data licensing is still an
open item in `ROADMAP.md`.
