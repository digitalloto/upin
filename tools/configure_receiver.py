#!/usr/bin/env python
"""
Enable the UBX messages the box reads, from the Pi, and save them to the
receiver. Then LISTEN and report what actually arrives: the send alone
proves nothing.

    python tools/configure_receiver.py --port /dev/serial/by-id/usb-u-blox... --target usb
    python tools/configure_receiver.py --port /dev/ttyUSB0 --target uart1 --hz 5
    python tools/configure_receiver.py --dry-run                 # print the frames only
    python tools/configure_receiver.py --port ... --valset       # F9/M10 key-value form

--target is the receiver's own name for the port the Pi is wired to: usb
for a USB cable, uart1 for a serial lead. The frames follow the public UBX
protocol (CFG-MSG, CFG-RATE, CFG-CFG; CFG-VALSET with --valset). UNTESTED
on hardware: the verification step is what makes the result honest.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from upin.box.ubx_config import PORTS, observe, plan, verdict  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", help="the receiver's serial device")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--target", choices=sorted(PORTS), default="usb",
                    help="the receiver's port the Pi is on (usb or uart1, usually)")
    ap.add_argument("--hz", type=float, default=5.0, help="navigation rate")
    ap.add_argument("--valset", action="store_true", help="use CFG-VALSET (F9, M10) instead of CFG-MSG")
    ap.add_argument("--no-save", action="store_true", help="do not write the configuration to flash")
    ap.add_argument("--seconds", type=float, default=10.0, help="how long to listen afterwards")
    ap.add_argument("--dry-run", action="store_true", help="print the frames and exit")
    a = ap.parse_args(argv)
    frames = plan(a.target, a.hz, valset=a.valset)
    if a.no_save:
        frames = [f for f in frames if not f[0].startswith("CFG-CFG")]
    for label, frame in frames:
        print(f"{label:48s} {frame.hex()}")
    if a.dry_run:
        return 0
    if not a.port:
        print("--port is required (or --dry-run)", file=sys.stderr)
        return 2
    import serial  # noqa: WPS433
    with serial.Serial(a.port, a.baud, timeout=0) as ser:
        for label, frame in frames:
            ser.write(frame)
            ser.flush()
            time.sleep(0.25)
        print(f"sent {len(frames)} frames; listening {a.seconds:.0f} s ...")
        obs = observe(lambda: ser.read(ser.in_waiting or 0), a.seconds)
    ok, notes = verdict(obs)
    for n in notes:
        print("  " + n)
    print("RESULT:", "configured: the receiver now sends what the box reads" if ok else
          "NOT confirmed: the messages the box needs did not arrive (check --target, --baud, the cable; "
          "an M8 needs MON-HW, an F9/M10 MON-RF)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
