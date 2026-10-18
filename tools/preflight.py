#!/usr/bin/env python
"""
Go / no-go before every start of the UPIN box, on the Pi, with the same
box.toml the box will run with.

    python tools/preflight.py --config /etc/upin/box.toml
    python tools/preflight.py --config /etc/upin/box.toml --seconds 20 --json
    python tools/preflight.py --config /etc/upin/box.toml --skip-fc      # receiver only

It opens the receiver's port and listens; it connects to the flight
controller, waits for a heartbeat, sends the same eight stream-rate
requests the box sends (nothing else), and listens. It prints what it
measured and a RESULT line, writes the same as JSON beside the logs, and
exits 1 on NO-GO. docs/FIRST_FLIGHT.md.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from upin.box import preflight as pf  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--seconds", type=float, default=10.0, help="how long to listen to each link")
    ap.add_argument("--gnss-source", choices=["receiver", "fc"], default="receiver")
    ap.add_argument("--skip-fc", action="store_true", help="do not connect to the flight controller")
    ap.add_argument("--skip-receiver", action="store_true")
    ap.add_argument("--unit", default="/etc/systemd/system/upin-box.service")
    ap.add_argument("--json", action="store_true", help="also print the JSON record")
    a = ap.parse_args(argv)

    checks = pf.check_environment()
    cfg, cc = pf.check_config(a.config)
    checks += cc
    extra = {}
    if cfg is not None:
        checks += pf.check_ports(cfg, a.gnss_source)
        if a.gnss_source == "receiver" and not a.skip_receiver and os.path.exists(cfg.receiver_port):
            try:
                import serial  # noqa: WPS433
                ser = serial.Serial(cfg.receiver_port, cfg.receiver_baud, timeout=0)
                try:
                    rc, obs = pf.check_receiver(lambda: ser.read(ser.in_waiting or 0), a.seconds)
                finally:
                    ser.close()
                checks += rc
                extra["receiver"] = {k: v for k, v in obs.items() if k != "last"}
            except Exception as exc:  # noqa: BLE001
                checks.append(pf.Check("receiver", "port", pf.NOGO, f"{cfg.receiver_port}: {exc}"))
        if not a.skip_fc:
            try:
                from pymavlink import mavutil  # noqa: WPS433
                conn = mavutil.mavlink_connection(cfg.fc_connection, baud=cfg.fc_baud,
                                                  source_system=1, source_component=191)
                try:
                    fc, info = pf.check_flight_controller(conn, a.seconds)
                finally:
                    conn.close()
                checks += fc
                extra["flight_controller"] = info
            except Exception as exc:  # noqa: BLE001
                checks.append(pf.Check("flight controller", "link", pf.NOGO, f"{cfg.fc_connection}: {exc}"))
        log_path = time.strftime(cfg.log_path) if "%" in cfg.log_path else cfg.log_path
        checks += pf.check_disk(cfg, log_path)
        checks += pf.check_unit_file(a.unit)
    print(pf.render(checks))
    rec = pf.to_json(checks, {"config": a.config, "unix": time.time(), **extra})
    if cfg is not None:
        d = os.path.dirname(time.strftime(cfg.log_path) if "%" in cfg.log_path else cfg.log_path) or "."
        out = os.path.join(d, time.strftime("preflight-%Y%m%d-%H%M%S.json"))
        try:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=1, default=str)
            print(f"written: {out}")
        except OSError as exc:
            print(f"could not write {out}: {exc}")
    if a.json:
        print(json.dumps(rec, indent=1, default=str))
    return 0 if pf.overall(checks) == pf.GO else 1


if __name__ == "__main__":
    sys.exit(main())
