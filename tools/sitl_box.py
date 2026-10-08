"""
Day 1 check: does ArduPilot accept the UPIN box as GPS 2?

**UNTESTED** -- written without access to ArduPilot SITL. Run it on a laptop
(Linux or WSL is easiest) with ArduPilot's simulator:

    sim_vehicle.py -v ArduCopter --console --map       # in the ardupilot tree
    pip install pymavlink
    python tools/sitl_box.py --connect tcp:127.0.0.1:5762 --set-params
    # restart SITL so the GPS type change takes effect, then:
    python tools/sitl_box.py --connect tcp:127.0.0.1:5762

It talks to the simulator only. Never point --set-params at a real aircraft
without checking each parameter on the ground station first.

What it checks, in three phases:
  A  30 s of trusted fixes near SITL's own position -> GPS2_RAW shows a 3-D
     fix at the position sent
  B  10 s of "no fix" from the box -> GPS2_RAW drops below 3-D
  C  10 s of silence (box dead) -> ArduPilot reports GPS 2 lost

Synthetic fixes: SITL's own position plus 1.5 m Gaussian noise. This tests
the plumbing, not navigation.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time

sys.path.insert(0, ".")

from upin.box.gateway import Gateway, GnssEpoch  # noqa: E402
from upin.box.mavlink_out import GpsInputSender  # noqa: E402
from upin.detection.reachability import Envelope  # noqa: E402

PARAMS = [
    # (name, value, why). Names follow ArduPilot 4.5+; older firmware uses
    # GPS_TYPE2 instead of GPS2_TYPE. Check against your firmware's list.
    ("GPS2_TYPE", 14, "GPS 2 is MAVLink (the UPIN box)"),
    ("GPS_AUTO_SWITCH", 0, "never switch: fly on the primary only"),
    ("GPS_PRIMARY", 0, "primary = GPS 1, the flight controller's own (shadow)"),
]


def set_params(conn) -> None:
    for name, value, why in PARAMS:
        conn.mav.param_set_send(conn.target_system, conn.target_component,
                                name.encode(), float(value), 9)  # 9 = REAL32
        ack = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=3)
        got = ack.param_value if ack and ack.param_id == name else None
        print(f"  {name} = {value:<3} ({why}) -> "
              f"{'set' if got == value else 'NOT CONFIRMED: set it by hand'}")
    print("Restart SITL so the GPS type takes effect, then run without --set-params.")


def watch_gps2(conn, seconds, send=None):
    """Run for `seconds`, calling send() at 5 Hz; return GPS2_RAW messages."""
    seen = []
    end = time.time() + seconds
    next_send = 0.0
    while time.time() < end:
        if send is not None and time.time() >= next_send:
            send()
            next_send = time.time() + 0.2
        msg = conn.recv_match(type="GPS2_RAW", blocking=True, timeout=0.05)
        if msg is not None:
            seen.append(msg)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", default="tcp:127.0.0.1:5762")
    ap.add_argument("--set-params", action="store_true")
    a = ap.parse_args()
    try:
        from pymavlink import mavutil
    except ImportError:
        print("pip install pymavlink")
        return 2
    conn = mavutil.mavlink_connection(a.connect, source_system=1,
                                      source_component=191)
    print(f"waiting for heartbeat on {a.connect} ...")
    if conn.wait_heartbeat(timeout=30) is None:
        print("no heartbeat: is SITL running?")
        return 2
    if a.set_params:
        set_params(conn)
        return 0

    home = conn.recv_match(type="GPS_RAW_INT", blocking=True, timeout=10)
    if home is None or home.fix_type < 3:
        print("SITL's own GPS has no fix yet; wait and retry")
        return 2
    lat0, lon0 = home.lat * 1e-7, home.lon * 1e-7
    print(f"SITL position {lat0:.6f}, {lon0:.6f}")

    gw = Gateway(Envelope(6.0, 20.0))
    sender = GpsInputSender(a.connect, gps_id=1, conn=conn)
    t0 = time.time()
    last = {}
    dlat = 1.0 / 111_320.0
    dlon = dlat / math.cos(math.radians(lat0))

    def send_fix():
        ep = GnssEpoch(t=time.time() - t0, fix_type=3,
                       lat=lat0 + random.gauss(0, 1.5) * dlat,
                       lon=lon0 + random.gauss(0, 1.5) * dlon,
                       alt_m=home.alt / 1000.0, h_acc_m=1.5, v_acc_m=3.0,
                       vel_ned_ms=(0.0, 0.0, 0.0), s_acc_ms=0.3, num_sv=14,
                       jamming_state="ok")
        last["msg"] = sender.send(gw.process(ep))

    def send_none():
        ep = GnssEpoch(t=time.time() - t0, fix_type=0)
        sender.send(gw.process(ep))

    results = []

    print("A: 30 s of trusted fixes as GPS 2 ...")
    seen = watch_gps2(conn, 30, send_fix)
    good = [m for m in seen[-10:] if m.fix_type >= 3
            and abs(m.lat - last["msg"].lat) < 1000 and abs(m.lon - last["msg"].lon) < 1000]  # ~10 m: 1.5 m noise, different epochs
    results.append(("GPS2_RAW shows a 3-D fix near what was sent", len(good) >= 5))

    print("B: 10 s of 'no fix' ...")
    seen = watch_gps2(conn, 10, send_none)
    results.append(("GPS2_RAW drops below 3-D when the box sends no fix",
                    bool(seen) and all(m.fix_type < 3 for m in seen[-5:])))

    print("C: 10 s of silence (box dead) ...")
    seen = watch_gps2(conn, 10)
    results.append(("GPS 2 reported lost when the box goes silent",
                    not seen or all(m.fix_type < 3 for m in seen[-5:])))

    for name, ok in results:
        print(f"[{'ok' if ok else 'FAIL'}] {name}")
    print("Check the ground station too: GPS 2 status, and that the vehicle "
          "still navigates on GPS 1 throughout (shadow mode).")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
