"""
Drive the gateway from a recording, so every decision can be re-run and
inspected off the aircraft.

Two inputs:
  - a raw UBX capture (bytes as logged from the receiver's port): NAV-PVT
    epochs, with the latest MON-RF jamming state attached
  - JSON lines, one GnssEpoch per line (what the box itself logs)

  python -m upin.box.replay capture.ubx --accel 6 --airspeed 20
  python -m upin.box.replay epochs.jsonl --accel 6 --airspeed 20

Prints one line per epoch: time, mode, accuracy, reasons.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Iterable, Iterator, List

from upin.box.gateway import Gateway, GatewayOutput, GnssEpoch
from upin.box.gnss_parser import MonRf, NavPvt, UbxStream, decode_ubx
from upin.detection.constellation_check import ConstellationFix
from upin.detection.reachability import Envelope


def epochs_from_ubx(data: bytes) -> Iterator[GnssEpoch]:
    """NAV-PVT epochs. Time is GPS time of week in seconds (iTOW); a capture
    that crosses a week boundary is not handled."""
    stream = UbxStream()
    jamming = "unknown"
    for cls, mid, payload in stream.feed(data):
        msg = decode_ubx(cls, mid, payload)
        if isinstance(msg, MonRf):
            jamming = msg.worst_state
        elif isinstance(msg, NavPvt):
            yield GnssEpoch(
                t=msg.itow_ms / 1000.0, fix_type=msg.fix_type if msg.gnss_fix_ok else 0,
                lat=msg.lat, lon=msg.lon, alt_m=msg.height_msl_m,
                h_acc_m=msg.h_acc_m, v_acc_m=msg.v_acc_m,
                vel_ned_ms=msg.vel_ned_ms, s_acc_ms=msg.s_acc_ms,
                num_sv=msg.num_sv, jamming_state=jamming)


def epoch_to_json(ep: GnssEpoch) -> str:
    d = asdict(ep)
    return json.dumps(d)


def epoch_from_json(line: str) -> GnssEpoch:
    d = json.loads(line)
    d["constellation_fixes"] = [ConstellationFix(**c)
                                for c in d.get("constellation_fixes", [])]
    if d.get("vel_ned_ms") is not None:
        d["vel_ned_ms"] = tuple(d["vel_ned_ms"])
    return GnssEpoch(**d)


def run(epochs: Iterable[GnssEpoch], gateway: Gateway) -> List[GatewayOutput]:
    return [gateway.process(ep) for ep in epochs]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path")
    ap.add_argument("--accel", type=float, required=True,
                    help="airframe's max horizontal acceleration, m/s^2")
    ap.add_argument("--airspeed", type=float, required=True,
                    help="airframe's max airspeed, m/s")
    ap.add_argument("--wind", type=float, default=15.0)
    a = ap.parse_args(argv)
    gw = Gateway(Envelope(a.accel, a.airspeed, a.wind))
    if a.path.endswith(".jsonl"):
        with open(a.path, encoding="utf-8") as f:
            epochs = [epoch_from_json(l) for l in f if l.strip()]
    else:
        with open(a.path, "rb") as f:
            epochs = list(epochs_from_ubx(f.read()))
    for o in run(epochs, gw):
        acc = f"{o.h_acc_m:6.1f} m" if o.h_acc_m is not None else "     -  "
        print(f"{o.t:10.2f}  {o.mode:8s} {acc}  {'; '.join(o.reasons)}")


if __name__ == "__main__":
    main()
