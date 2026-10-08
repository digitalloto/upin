# Raspberry Pi guide: from the box to a working UPIN bench rig

For someone who has never used a Raspberry Pi. Follow it in order. Every
step says what you should see when it worked.

> **Where this stands.** The software is ready to *try*. It has never run on
> a Pi, a real receiver or a real flight controller. This guide is how we
> find out. Propellers stay **off** for everything here. Nothing in this
> guide makes the drone fly on UPIN: it runs beside the drone's own GPS
> ("shadow mode") so you can compare.

## Short answers

| Question | Answer |
|---|---|
| Which Pi? | **Raspberry Pi 5, 4 GB.** Take 8 GB if camera work is coming soon. A Pi 4 also works. A Pi Zero 2 W is the cheap option later, once we've measured that it keeps up |
| How much of the code goes on it? | Copy the **whole repo**: it is simplest and costs nothing. But **run only the box service**, which uses only the honest pieces: fix checks, the reachability circle, the receiver cross-check, HonestKalman and GPS_INPUT. The other layers are never started |
| All the layers, or a few? | **A few.** Most layers either need hardware we don't have (cameras, maps, lab sensors) or invent readings when nothing is connected. On a drone, those invented readings would be dangerous |
| What do I look at to see if it works? | Three windows on your Mac: **(1)** a terminal connected to the Pi, which prints UPIN's mode (TRUSTED / DEGRADED / NO_FIX) and why; **(2)** QGroundControl's MAVLink Inspector, which shows the flight controller receiving UPIN as GPS 2; **(3)** the log file, one line per second, which we analyse afterwards |

## What a Pi is, in one paragraph

A Raspberry Pi is a small, complete computer running Linux. It has no
screen or keyboard of its own. You will control it from your Mac over
Wi-Fi by typing commands into a terminal window (this is called **SSH**).
Its storage is a microSD card. Whatever is on the card is the whole
computer: if something goes badly wrong, you can wipe the card and start
again in 15 minutes.

---

## Step 1: Buy

| Item | Notes |
|---|---|
| Raspberry Pi 5 (4 GB) | |
| Official Raspberry Pi 27 W USB-C power supply | The Pi 5 needs 5 V / 5 A. Phone chargers cause random crashes |
| Active Cooler for the Pi 5 | Clips on; stops it slowing down when hot |
| A case that fits the Active Cooler | |
| microSD card, 32 or 64 GB, "A2", known brand | Plus a card reader for your Mac if it has no slot |
| GNSS receiver module **with a USB port** and u-blox UBX output (M8, M9, M10 or F9 series) | With an **active GNSS antenna**. For NavIC, check that the datasheet says NavIC / IRNSS L5 |
| USB cables to match the receiver and the flight controller | |
| Your Pixhawk-type flight controller running ArduPilot | |

Get prices from Indian distributors; none are listed here.

On your Mac, install **QGroundControl** (free, from qgroundcontrol.com) and
**Raspberry Pi Imager** (free, from raspberrypi.com/software).

## Step 2: Put the operating system on the card

1. Put the microSD card in your Mac. Open **Raspberry Pi Imager**.
2. Choose device **Raspberry Pi 5**. Choose OS **Raspberry Pi OS (64-bit)**.
   Choose your card.
3. When it asks about **OS customisation**, choose *Edit settings*:
   - hostname: `upin-box`
   - username and password: choose them and write them down
   - Wi-Fi: your network name and password; country **IN**
   - **Services tab: enable SSH**, with password authentication
4. Write the card. It takes a few minutes.
5. Put the card in the Pi, attach the cooler and case, plug in power.
   Wait 2–3 minutes for the first boot.

**Worked when:** the Pi's green light flickers and then settles.

## Step 3: Connect to the Pi from your Mac

Open **Terminal** on the Mac (Applications → Utilities) and type:

```bash
ssh yourname@upin-box.local
```

Type `yes` to the first question, then your Pi password. Nothing appears
while you type the password; that is normal.

**Worked when:** the prompt changes to `yourname@upin-box:~ $`. Every
command from here on is typed into this window, on the Pi.

Update the Pi once:

```bash
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

Wait one minute, then `ssh` in again.

## Step 4: Get the UPIN code and check it runs on the Pi

The repo is private, so GitHub needs a **token** instead of your password:

1. On github.com: Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate.
2. Give it access to `digitalloto/upin` only, with **Contents: read-only**,
   and a short expiry.
3. Copy the token.

On the Pi:

```bash
sudo apt install -y git python3-venv python3-dev rsync
git clone -b claude/patent-application-spec-sEgOc https://github.com/digitalloto/upin.git
cd upin
python3 -m venv venv
venv/bin/pip install -e ".[box]"
```

When git asks for a password, paste the token.

Now run the box's tests **on the Pi**:

```bash
time venv/bin/python tests/test_box.py
venv/bin/python tests/test_box_service.py
venv/bin/python tests/test_reachability.py
venv/bin/python tests/test_constellation_check.py
```

**Worked when:** each test file ends with `N/N ... tests passed`. The `time`
line tells us how fast the Pi is. Send me that output: it is our first real
measurement on the hardware.

## Step 5: Set up the GNSS receiver

Our software reads the receiver's **UBX** messages: NAV-PVT (position),
NAV-SAT (satellites) and MON-RF (jamming state). Most receivers send only
plain NMEA text out of the box, so they must be switched on once and saved.

> **Gap:** we have no configuration script yet. The receiver maker's tool
> (u-center) runs on Windows only. Ask me and I'll write a small script that
> configures the receiver from the Pi. Until then, configure it once on any
> Windows PC with u-center: enable NAV-PVT, NAV-SAT and MON-RF on the USB
> port at 1 Hz, then *save configuration*.

Plug the receiver into the Pi by USB, with the antenna **outdoors or at a
window with sky view**. Then find its name:

```bash
ls /dev/serial/by-id/
```

**Worked when:** you see a line with `u-blox` in it. Copy the full name;
you'll use it in Step 6. These names never change, unlike `/dev/ttyACM0`,
which can swap when you plug things in a different order.

## Step 6: Install the box service

```bash
cd ~/upin
bash deploy/install.sh
```

This copies UPIN to `/opt/upin`, creates a `upin` user allowed to use
serial ports, and puts the settings file at `/etc/upin/box.toml`. It does
**not** start anything.

Edit the settings:

```bash
sudo nano /etc/upin/box.toml
```

Change these, then save with **Ctrl-O, Enter, Ctrl-X**:

| Setting | Set it to |
|---|---|
| `receiver_port` | `/dev/serial/by-id/...u-blox...` from Step 5 |
| `fc_connection` | leave for now; Step 8 sets it |
| `max_accel_ms2`, `max_airspeed_ms` | your airframe's real limits. If unsure, ask me with the drone's weight, motor thrust and top speed |

Leave everything marked ASSUMPTION as it is for now.

## Step 7: First run, receiver only, sending nothing

The service needs a flight controller to start. So this step is the
receiver check: plug the **flight controller into the Pi by USB** (no
battery, no propellers). Find its name:

```bash
ls /dev/serial/by-id/
```

You'll see a second line, usually with `ArduPilot` in it. Put that in
`fc_connection` in `/etc/upin/box.toml`. Then run the service by hand,
sending nothing:

```bash
sudo -u upin /opt/upin/venv/bin/python -m upin.box.service \
     --config /etc/upin/box.toml --no-send
```

**Worked when:**
- it prints `waiting for flight controller heartbeat ...`, then `UPIN box running ... NOT sending`;
- within a minute or two of sky view it prints `TRUSTED: all checks passed`.

Stop it with **Ctrl-C**. Look at the log:

```bash
tail -n 3 /var/log/upin/box.jsonl
```

Each line is one second: the receiver's position and accuracy, the flight
controller's own GPS, the heading, UPIN's mode and the reason for it.

## Step 8: Shadow mode, with UPIN as GPS 2

1. Connect the flight controller to your **Mac** by USB and open
   **QGroundControl**.
2. Vehicle Setup → Parameters. Search for and set:
   - `GPS2_TYPE` = **14** (MAV). On older firmware it is `GPS_TYPE2`.
   - `GPS_AUTO_SWITCH` = **0**
   - `GPS_PRIMARY` = **0**

   The last two make sure the drone keeps using its own GPS. Reboot the
   flight controller (Tools → Reboot Vehicle).
3. Move the flight controller's USB back to the **Pi**. Run the service,
   this time sending:

   ```bash
   sudo -u upin /opt/upin/venv/bin/python -m upin.box.service --config /etc/upin/box.toml
   ```

4. To watch from the Mac at the same time: connect the flight controller's
   **telemetry radio**, or a second USB port if it has one, to the Mac. Open
   QGroundControl → Analyze Tools → **MAVLink Inspector** → `GPS2_RAW`.

**Worked when:**
- `GPS2_RAW` shows `fix_type` 3 and a latitude and longitude close to the receiver's;
- the drone's main position still comes from its own GPS 1.

### Watching it on the UPIN console

Instead of the terminal, you can watch everything on a live page. Stop the
service and run the console on the Pi:

```bash
sudo -u upin /opt/upin/venv/bin/python -m upin.console --source live \
     --config /etc/upin/box.toml --host 0.0.0.0 --allow-control
```

On the Mac, open **http://upin-box.local:8080**. It shows:
- the mode and why;
- every check;
- the map with UPIN's accuracy circle and the physically-reachable region;
- the receiver and the flight-controller sensors.

Try it on the Mac first with `--source sim`, which needs no hardware; see
[`CONSOLE.md`](CONSOLE.md).

## Step 9: The GPS-denied test

UPIN can only carry on without GNSS after it has trusted GNSS first. So the
test runs in one go: trusted GNSS, then GNSS switched off in software, then
back on.

```bash
sudo -u upin /opt/upin/venv/bin/python -m upin.box.service \
     --config /etc/upin/box.toml --deny-after 60 --deny-for 120
```

This runs 60 s on trusted GNSS, then 120 s with GNSS denied, then back.

**Worked when:**
- it prints `--- GNSS DENIED in software ---`, then `DEGRADED`, then later
  `NO_FIX` once UPIN's own accuracy grows past the 50 m limit;
- after `--- GNSS restored ---`, it validates for 5 epochs and returns to
  `TRUSTED`.

How long it stays DEGRADED depends on the sensors. Without optical flow it
only coasts, and that is short. Carry the rig while it runs, then send me
`/var/log/upin/box.jsonl`. The receiver kept logging during the denial, so
I can measure UPIN's real error against it.

Never use a real jammer: it is illegal outside an authorised range.
Software denial does the job.

## Step 10: Make it start by itself (only once Steps 7–9 work)

```bash
sudo systemctl enable --now upin-box
journalctl -u upin-box -f          # watch it live; Ctrl-C stops watching, not the service
sudo systemctl stop upin-box       # stop it
```

---

## If something goes wrong

| You see | Likely cause and fix |
|---|---|
| `ssh: Could not resolve hostname upin-box.local` | The Pi is not on Wi-Fi yet: wait, or re-check the Wi-Fi settings from Step 2 |
| `Permission denied` on a serial port | Run the service as `sudo -u upin ...` as shown; the `upin` user has serial access |
| Stuck at `waiting for flight controller heartbeat` | Wrong `fc_connection`; re-check `ls /dev/serial/by-id/`. Is the flight controller powered by USB? |
| Running, but never prints TRUSTED | The receiver is sending NMEA, not UBX (Step 5); or it has no sky view; or the antenna isn't connected |
| `GPS2_RAW` never appears in QGroundControl | `GPS2_TYPE` not set to 14, or the flight controller wasn't rebooted after setting it |
| `DEGRADED: constellations disagree` | The flight controller's GPS and the new receiver disagree by more than their stated accuracy. Check both antennas have sky view |
| The Pi reboots by itself | Power: use the official 27 W supply |

## What comes after this guide

1. Measure the GNSS-denied error from your logs (Step 9). These become the
   first real numbers in `ROADMAP.md`.
2. Add an optical-flow sensor and rangefinder to the flight controller. That
   is the biggest single improvement to the GNSS-denied error.
3. Only after SITL tests and good bench logs, and only if you decide so:
   UPIN as the primary GPS.
4. Then, if wanted, port the light layers to an ESP32-S3.
