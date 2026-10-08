# Deploying the UPIN box on a Raspberry Pi

**UNTESTED on a Pi.** Read `install.sh` before running it.

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
5. Set the receiver to output UBX NAV-PVT, NAV-SAT and MON-RF on the port wired
   to the Pi, at `receiver_baud`, at 1–5 Hz. Use the receiver maker's
   configuration tool and save the configuration to the receiver.
6. Run the service by hand with `--no-send` first, then in shadow mode.
   The ArduPilot parameters are in [`docs/HARDWARE.md`](../docs/HARDWARE.md).
7. Only when it behaves: `sudo systemctl enable --now upin-box`.
   - Logs: `/var/log/upin/box.jsonl`.
   - Status: `journalctl -u upin-box -f`.
