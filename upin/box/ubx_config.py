"""
Configure a u-blox receiver from the Pi: enable the messages the box
reads, set the rate, save. Our own UBX encoding from the public protocol.

  CFG-MSG   (0x06 0x01)  message rate per port (M8, F9, M10: legacy, works
                         on all three)
  CFG-RATE  (0x06 0x08)  measurement rate in ms, navigation rate, time ref
  CFG-CFG   (0x06 0x09)  save the current configuration to BBR and flash
  CFG-VALSET (0x06 0x8A) the F9/M10 key-value form (optional, --valset)

Nothing here is trusted until the receiver answers: after sending, the
caller listens and counts what arrives (`observe`), and the tool refuses
to report success from the send alone. **UNTESTED on hardware**; the
frames are built from the interface descriptions and checked byte for
byte in tests. Key ids for CFG-VALSET are the F9 interface description's;
verify on the receiver bought.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import struct
import time
from typing import Callable, Dict, List, Optional, Tuple

from upin.box.gnss_parser import (MON_HW, MON_RF, NAV_PVT, NAV_SAT, NmeaEpochBuilder, NmeaStream,
                                  UbxStream, decode_ubx, ubx_frame)

CFG_MSG = (0x06, 0x01)
CFG_RATE = (0x06, 0x08)
CFG_CFG = (0x06, 0x09)
CFG_VALSET = (0x06, 0x8A)

PORTS = {"i2c": 0, "uart1": 1, "uart2": 2, "usb": 3, "spi": 4}
"""CFG-MSG rate array index per port (DDC/I2C, UART1, UART2, USB, SPI)."""

WANTED = {"NAV-PVT": NAV_PVT, "NAV-SAT": NAV_SAT, "MON-RF": MON_RF, "MON-HW": MON_HW}

# CFG-VALSET keys (F9 / M10 interface descriptions; verify on the receiver)
VALSET_KEYS: Dict[Tuple[str, str], int] = {
    ("NAV-PVT", "i2c"): 0x20910006, ("NAV-PVT", "uart1"): 0x20910007,
    ("NAV-PVT", "uart2"): 0x20910008, ("NAV-PVT", "usb"): 0x20910009,
    ("NAV-SAT", "i2c"): 0x20910015, ("NAV-SAT", "uart1"): 0x20910016,
    ("NAV-SAT", "uart2"): 0x20910017, ("NAV-SAT", "usb"): 0x20910018,
    ("MON-RF", "i2c"): 0x20910359, ("MON-RF", "uart1"): 0x2091035a,
    ("MON-RF", "uart2"): 0x2091035b, ("MON-RF", "usb"): 0x2091035c,
}
KEY_RATE_MEAS = 0x30210001        # U2, ms
KEY_RATE_NAV = 0x30210002         # U2, cycles


# -- frames -------------------------------------------------------------------

def cfg_msg_frame(msg: Tuple[int, int], port: str, rate: int) -> bytes:
    """Enable `msg` on `port` every `rate` navigation solutions (0 = off);
    other ports are left as they are (rate 0 in the array means off for
    them, so only the chosen port is set and the rest sent as 0)."""
    rates = [0] * 6
    rates[PORTS[port]] = rate
    return ubx_frame(*CFG_MSG, struct.pack("<BB6B", msg[0], msg[1], *rates))


def cfg_rate_frame(meas_ms: int, nav_rate: int = 1, time_ref: int = 1) -> bytes:
    """measRate ms between measurements, navRate cycles per solution,
    timeRef 0 UTC / 1 GPS."""
    return ubx_frame(*CFG_RATE, struct.pack("<HHH", meas_ms, nav_rate, time_ref))


def cfg_cfg_save_frame() -> bytes:
    """Save all configuration sections to BBR and flash (deviceMask 0x03)."""
    return ubx_frame(*CFG_CFG, struct.pack("<IIIB", 0x00000000, 0x0000FFFF, 0x00000000, 0x03))


def cfg_valset_frame(items: List[Tuple[int, int, int]], layers: int = 0x07) -> bytes:
    """items: (key, value, size_bytes). layers bit0 RAM, bit1 BBR, bit2 flash."""
    body = struct.pack("<BBBB", 0x00, layers, 0, 0)
    for key, value, size in items:
        body += struct.pack("<I", key) + value.to_bytes(size, "little")
    return ubx_frame(*CFG_VALSET, body)


def plan(port: str, hz: float, messages=("NAV-PVT", "NAV-SAT", "MON-RF", "MON-HW"),
         valset: bool = False) -> List[Tuple[str, bytes]]:
    """The frames to send, in order, with a label each."""
    meas_ms = int(round(1000.0 / hz))
    out: List[Tuple[str, bytes]] = [(f"CFG-RATE {meas_ms} ms (" + f"{hz:g} Hz)", cfg_rate_frame(meas_ms))]
    if valset:
        items = [(KEY_RATE_MEAS, meas_ms, 2), (KEY_RATE_NAV, 1, 2)]
        for name in messages:
            key = VALSET_KEYS.get((name, port))
            if key is not None:
                items.append((key, 1, 1))
        out = [("CFG-VALSET rate + messages on " + port, cfg_valset_frame(items))]
    else:
        for name in messages:
            out.append((f"CFG-MSG {name} on {port} every solution",
                        cfg_msg_frame(WANTED[name], port, 1)))
    out.append(("CFG-CFG save to BBR and flash", cfg_cfg_save_frame()))
    return out


# -- observing what the receiver actually sends --------------------------------

def observe(read: Callable[[], bytes], seconds: float, sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic) -> dict:
    """Count UBX messages by type for `seconds`, and notice NMEA text.
    read() returns whatever bytes are waiting (possibly none)."""
    stream = UbxStream()
    nmea = NmeaStream()
    builder = NmeaEpochBuilder()
    counts: Dict[str, int] = {}
    nmea_lines = 0
    last: Dict[str, object] = {}
    raw = 0
    t0 = clock()
    while clock() - t0 < seconds:
        data = read()
        if not data:
            sleep(0.02)
            continue
        raw += len(data)
        nmea_lines += data.count(b"$G")
        for m in nmea.feed(data):
            f = builder.feed(m)
            if f is not None:
                last["NMEA-FIX"] = f
        for cls, mid, payload in stream.feed(data):
            name = {v: k for k, v in WANTED.items()}.get((cls, mid), f"{cls:02X}-{mid:02X}")
            counts[name] = counts.get(name, 0) + 1
            m = decode_ubx(cls, mid, payload)
            if m is not None:
                last[name] = m
    span = max(clock() - t0, 1e-6)
    talkers = sorted({k for k in nmea.stats.kinds})
    if builder.satellites():
        last["NMEA-SATS"] = builder.satellites()
    return {"seconds": span, "bytes": raw, "counts": counts,
            "rates_hz": {k: v / span for k, v in counts.items()},
            "bad_checksum": stream.stats.bad_checksum, "nmea_lines": nmea_lines, "last": last,
            "nmea": {"sentences": nmea.stats.sentences, "bad_checksum": nmea.stats.bad_checksum,
                     "kinds": dict(nmea.stats.kinds),
                     "rates_hz": {k: v / span for k, v in nmea.stats.kinds.items()},
                     "talkers": talkers}}


def nmea_verdict(obs: dict) -> Tuple[bool, List[str]]:
    """An NMEA receiver: GGA and RMC make epochs, GSV feeds the signal-power
    check, GST gives the receiver's own accuracy; no jamming state exists."""
    n = obs.get("nmea") or {}
    rates = n.get("rates_hz", {})
    notes, ok = [], True
    for kind, why in (("GGA", "position: required"), ("RMC", "velocity"), ("GSA", "3-D and DOP"),
                      ("GSV", "per-satellite signal strength for the signal-power check"),
                      ("GST", "the receiver's own accuracy")):
        r = rates.get(kind, 0.0)
        if r > 0:
            notes.append(f"{kind}: {r:.1f} Hz")
        elif kind == "GGA":
            ok = False
            notes.append("GGA: none received (no position)")
        elif kind == "GST":
            notes.append("GST: none: the receiver states no accuracy; the box assumes HDOP x nmea_uere_m "
                         "(labelled) -- enable GST in the receiver's software if it has it")
        else:
            notes.append(f"{kind}: none ({why} unavailable)")
    sats = obs.get("last", {}).get("NMEA-SATS") or []
    consts: Dict[str, int] = {}
    for s in sats:
        consts[s.constellation] = consts.get(s.constellation, 0) + 1
    if consts:
        notes.append("in view: " + ", ".join(f"{k} {v}" for k, v in sorted(consts.items())))
    notes.append("NMEA carries no jamming state and no raw pseudoranges: those checks read NOT RUN")
    if n.get("bad_checksum"):
        notes.append(f"{n['bad_checksum']} sentences with a bad checksum (wrong baud, or a noisy cable)")
    return ok, notes


def verdict(obs: dict, need=("NAV-PVT", "NAV-SAT")) -> Tuple[bool, List[str]]:
    """Did the receiver deliver what the box needs? With the reasons. A
    receiver speaking NMEA is judged by nmea_verdict."""
    if not obs["counts"] and (obs.get("nmea") or {}).get("sentences"):
        return nmea_verdict(obs)
    notes = []
    ok = True
    for name in need:
        r = obs["rates_hz"].get(name, 0.0)
        if r <= 0:
            ok = False
            notes.append(f"{name}: none received")
        else:
            notes.append(f"{name}: {r:.1f} Hz")
    rf, hw = obs["rates_hz"].get("MON-RF", 0.0), obs["rates_hz"].get("MON-HW", 0.0)
    if rf > 0:
        notes.append(f"MON-RF: {rf:.1f} Hz (jamming state and AGC available)")
    elif hw > 0:
        notes.append(f"MON-HW: {hw:.1f} Hz (M8: jamming state and AGC from MON-HW)")
    else:
        notes.append("no MON-RF or MON-HW: the box will have no receiver jamming state or AGC")
    if obs["bad_checksum"]:
        notes.append(f"{obs['bad_checksum']} frames with a bad checksum (wrong baud, or a noisy cable)")
    if obs["nmea_lines"] and not obs["counts"]:
        ok = False
        notes.append("only NMEA text seen: the receiver is not sending UBX on this port")
    if obs["bytes"] == 0:
        ok = False
        notes.append("nothing at all received: wrong port, wrong baud, or the receiver is off")
    return ok, notes
