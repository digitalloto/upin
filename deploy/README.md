# Deploying the UPIN box on a Raspberry Pi

**UNTESTED on a Pi.** Read `install.sh` before running it. The campaign that
takes this to a real rig, listening only, is [`docs/FIRST_FLIGHT.md`](../docs/FIRST_FLIGHT.md).

1. Raspberry Pi OS 64-bit, Bookworm or later (Python 3.11+).
2. `git clone` the repo onto the Pi, then `bash deploy/install.sh`.
   - It installs into `/opt/upin` and creates a `upin` user in the `dialout` group.
   - It puts the config at `/etc/upin/box.toml`.
   - It does not start anything.
3. Edit `/etc/upin/box.toml`:
   - set the airframe limits and serial ports;
   - every value marked ASSUMPTION is a starting guess, to be replaced once measured.
4. Free the Pi's UART: `sudo raspi-config` → Interface → Serial.
   Login shell over serial: **No**. Serial hardware: **Yes**. Reboot.
5. A u-blox receiver: set it to output UBX NAV-PVT, NAV-SAT and MON-RF (MON-HW
   on an M8) with `tools/configure_receiver.py --port ... --target usb`, which
   verifies by listening. Any other receiver: NMEA GGA, RMC, GSA, GSV (and GST)
   on at 1-5 Hz, `receiver_protocol = "nmea"`.
6. `tools/preflight.py --config /etc/upin/box.toml` before every start: GO
   or NO-GO, with the reasons.
7. Run the service by hand with `--no-send` first; the unit file runs with
   `--no-send` too. Shadow mode (sending GPS 2) is a later, separate
   decision: [`docs/HARDWARE.md`](../docs/HARDWARE.md).
8. Only when it behaves: `sudo systemctl enable --now upin-box`.
   - Logs: one file per run, `/var/log/upin/box-<date>-<time>.jsonl` and
     `inputs-<date>-<time>.jsonl`; `tools/flight_summary.py` reads them.
   - Status: `journalctl -u upin-box -f` (a status line every ten seconds).
   - Stop: `sudo systemctl stop upin-box` closes cleanly and saves what the run learned.
