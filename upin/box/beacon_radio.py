"""
The beacon radio on the box. UNTESTED on hardware.

A ranging radio module (2.4 GHz LoRa-class with ranging, or UWB) attached
over serial, running firmware that prints one JSON object per line:

  {"type": "msg", "id": "b1", "t": 1760000000.0, "lat": 13.08, "lon": 80.27,
   "alt_m": 12000.0, "sigma_m": 5.0, "seq": 412, "channel": 17, "sig": "..."}
  {"type": "range", "id": "b1", "range_m": 15320.4, "sigma_m": 10.0}

The box checks every message (signature, hop schedule, sequence, age) in
layer 151 before it counts. The radio firmware itself is not part of this
repo yet.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from typing import List


class BeaconRadio:
    UNTESTED = True

    def __init__(self, port: str, baud: int = 115200):
        try:
            import serial  # noqa: WPS433 -- lazy by design
        except ImportError as exc:
            raise RuntimeError("pyserial is not installed (the [box] extra)") from exc
        self._ser = serial.Serial(port, baud, timeout=0)
        self._buf = b""

    def read_lines(self) -> List[str]:
        data = self._ser.read(self._ser.in_waiting or 1)
        if not data:
            return []
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        return [ln.decode("utf-8", "replace").strip() for ln in lines if ln.strip()]

    def close(self) -> None:
        self._ser.close()
