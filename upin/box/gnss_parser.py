"""
Parsers for what a GNSS receiver sends over its serial port.

UBX (u-blox binary) -- the messages the box needs:
  NAV-PVT  (0x01 0x07)  position, velocity, time, accuracy estimates
  NAV-SAT  (0x01 0x35)  every satellite tracked: constellation, C/N0,
                        elevation, whether used in the fix
  MON-RF   (0x0A 0x38)  RF front end: the receiver's own jamming state,
                        noise level and AGC per band

NMEA 0183 -- the fallback any receiver speaks:
  GGA  position, fix quality, satellites, HDOP, altitude
  RMC  position, validity, speed and course over ground

Field offsets follow the u-blox interface descriptions for the M8/F9
generations (protocol 18+). **They must be checked against the interface
description of the receiver actually bought** before any field result is
trusted: u-blox revises messages between generations. The tests use byte
strings built from those published layouts -- synthetic test vectors, not
captures from a real receiver.

Every frame's checksum is verified; a corrupt frame is dropped and counted,
never half-parsed.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple, Union

SYNC = b"\xb5\x62"

NAV_PVT = (0x01, 0x07)
NAV_SAT = (0x01, 0x35)
MON_RF = (0x0A, 0x38)

GNSS_ID = {0: "gps", 1: "sbas", 2: "galileo", 3: "beidou", 4: "imes",
           5: "qzss", 6: "glonass", 7: "navic"}
"""UBX gnssId values. NavIC is 7 on receivers that support it -- confirm on
the datasheet; many do not track NavIC at all."""

JAMMING_STATE = {0: "unknown", 1: "ok", 2: "warning", 3: "critical"}


# -- UBX framing ----------------------------------------------------------

def ubx_checksum(body: bytes) -> Tuple[int, int]:
    """8-bit Fletcher over class, id, length and payload."""
    a = b = 0
    for byte in body:
        a = (a + byte) & 0xFF
        b = (b + a) & 0xFF
    return a, b


def ubx_frame(cls: int, mid: int, payload: bytes) -> bytes:
    body = struct.pack("<BBH", cls, mid, len(payload)) + payload
    return SYNC + body + bytes(ubx_checksum(body))


@dataclass
class UbxStats:
    frames: int = 0
    bad_checksum: int = 0
    unknown: int = 0


class UbxStream:
    """Feed it bytes as they arrive; it yields complete, verified frames.
    Resynchronises on the next sync pair after garbage or a bad checksum."""

    MAX_PAYLOAD = 4096

    def __init__(self):
        self._buf = bytearray()
        self.stats = UbxStats()

    def feed(self, data: bytes) -> Iterator[Tuple[int, int, bytes]]:
        self._buf.extend(data)
        while True:
            i = self._buf.find(SYNC)
            if i < 0:
                del self._buf[:-1]          # keep a trailing 0xB5
                return
            del self._buf[:i]
            if len(self._buf) < 6:
                return
            cls, mid, n = struct.unpack_from("<BBH", self._buf, 2)
            if n > self.MAX_PAYLOAD:
                del self._buf[:2]
                continue
            if len(self._buf) < 8 + n:
                return
            body = bytes(self._buf[2:6 + n])
            ck = tuple(self._buf[6 + n:8 + n])
            if ck != ubx_checksum(body):
                self.stats.bad_checksum += 1
                del self._buf[:2]
                continue
            del self._buf[:8 + n]
            self.stats.frames += 1
            yield cls, mid, body[4:]


# -- UBX messages ---------------------------------------------------------

@dataclass
class NavPvt:
    itow_ms: int
    fix_type: int                 # 0 none, 2 2D, 3 3D, 4 GNSS+DR, 5 time only
    gnss_fix_ok: bool
    num_sv: int
    lat: float
    lon: float
    height_msl_m: float
    h_acc_m: float
    v_acc_m: float
    vel_ned_ms: Tuple[float, float, float]
    s_acc_ms: float
    pdop: float
    year: int = 0
    month: int = 0
    day: int = 0
    hour: int = 0
    minute: int = 0
    second: int = 0


def parse_nav_pvt(p: bytes) -> Optional[NavPvt]:
    if len(p) < 92:
        return None
    (itow, year, month, day, hour, minute, second, _valid, _tacc, _nano,
     fix, flags, _flags2, num_sv, lon, lat, _height, hmsl, hacc, vacc,
     vn, ve, vd, _gspeed, _headmot, sacc, _headacc, pdop) = struct.unpack_from(
        "<IHBBBBBBIiBBBBiiiiIIiiiiiIIH", p, 0)
    return NavPvt(
        itow_ms=itow, fix_type=fix, gnss_fix_ok=bool(flags & 0x01),
        num_sv=num_sv, lat=lat * 1e-7, lon=lon * 1e-7,
        height_msl_m=hmsl / 1000.0, h_acc_m=hacc / 1000.0,
        v_acc_m=vacc / 1000.0,
        vel_ned_ms=(vn / 1000.0, ve / 1000.0, vd / 1000.0),
        s_acc_ms=sacc / 1000.0, pdop=pdop * 0.01,
        year=year, month=month, day=day, hour=hour, minute=minute,
        second=second)


@dataclass
class SatInfo:
    constellation: str
    sv_id: int
    cn0_dbhz: int
    elevation_deg: int
    azimuth_deg: int
    used: bool


@dataclass
class NavSat:
    itow_ms: int
    satellites: List[SatInfo] = field(default_factory=list)

    def tracked(self, constellation: str) -> List[SatInfo]:
        return [s for s in self.satellites
                if s.constellation == constellation and s.cn0_dbhz > 0]


def parse_nav_sat(p: bytes) -> Optional[NavSat]:
    if len(p) < 8:
        return None
    itow, _version, num = struct.unpack_from("<IBB", p, 0)
    if len(p) < 8 + 12 * num:
        return None
    sats = []
    for k in range(num):
        gnss, sv, cno, elev, azim, _prres, flags = struct.unpack_from(
            "<BBBbhhI", p, 8 + 12 * k)
        sats.append(SatInfo(GNSS_ID.get(gnss, f"gnss{gnss}"), sv, cno, elev,
                            azim, bool(flags & 0x08)))
    return NavSat(itow, sats)


@dataclass
class RfBlock:
    block_id: int
    jamming_state: str            # the receiver's own verdict
    noise_per_ms: int
    agc_count: int
    jam_indicator: int            # 0..255, CW interference


@dataclass
class MonRf:
    blocks: List[RfBlock] = field(default_factory=list)

    @property
    def worst_state(self) -> str:
        order = ["unknown", "ok", "warning", "critical"]
        states = [b.jamming_state for b in self.blocks] or ["unknown"]
        return max(states, key=order.index)


def parse_mon_rf(p: bytes) -> Optional[MonRf]:
    if len(p) < 4:
        return None
    _version, n = struct.unpack_from("<BB", p, 0)
    if len(p) < 4 + 24 * n:
        return None
    blocks = []
    for k in range(n):
        o = 4 + 24 * k
        block_id, flags = struct.unpack_from("<BB", p, o)
        noise, agc, jam = struct.unpack_from("<HHB", p, o + 12)
        blocks.append(RfBlock(block_id, JAMMING_STATE[flags & 0x03], noise,
                              agc, jam))
    return MonRf(blocks)


UbxMessage = Union[NavPvt, NavSat, MonRf]


def decode_ubx(cls: int, mid: int, payload: bytes) -> Optional[UbxMessage]:
    if (cls, mid) == NAV_PVT:
        return parse_nav_pvt(payload)
    if (cls, mid) == NAV_SAT:
        return parse_nav_sat(payload)
    if (cls, mid) == MON_RF:
        return parse_mon_rf(payload)
    return None


# -- NMEA -----------------------------------------------------------------

def nmea_checksum(body: str) -> int:
    c = 0
    for ch in body:
        c ^= ord(ch)
    return c


def nmea_sentence(body: str) -> str:
    return f"${body}*{nmea_checksum(body):02X}"


def _split(sentence: str) -> Optional[List[str]]:
    s = sentence.strip()
    if not s.startswith("$") or "*" not in s:
        return None
    body, _, ck = s[1:].partition("*")
    try:
        if int(ck[:2], 16) != nmea_checksum(body):
            return None
    except ValueError:
        return None
    return body.split(",")


def _coord(value: str, hemi: str, deg_digits: int) -> Optional[float]:
    if not value or not hemi:
        return None
    deg = float(value[:deg_digits]) + float(value[deg_digits:]) / 60.0
    return -deg if hemi in ("S", "W") else deg


@dataclass
class Gga:
    utc: str
    lat: Optional[float]
    lon: Optional[float]
    quality: int                  # 0 invalid, 1 GNSS, 2 DGNSS, 4 RTK fixed...
    num_sv: int
    hdop: Optional[float]
    alt_msl_m: Optional[float]


@dataclass
class Rmc:
    utc: str
    valid: bool
    lat: Optional[float]
    lon: Optional[float]
    speed_ms: Optional[float]
    course_deg: Optional[float]
    date: str


KNOT_MS = 1852.0 / 3600.0


def parse_nmea(sentence: str) -> Optional[Union[Gga, Rmc]]:
    """GGA or RMC from any talker (GP, GN, GI...). None if the checksum is
    wrong or the sentence is another type."""
    f = _split(sentence)
    if f is None or len(f[0]) < 5:
        return None
    kind = f[0][2:]
    try:
        if kind == "GGA" and len(f) >= 10:
            return Gga(f[1], _coord(f[2], f[3], 2), _coord(f[4], f[5], 3),
                       int(f[6] or 0), int(f[7] or 0),
                       float(f[8]) if f[8] else None,
                       float(f[9]) if f[9] else None)
        if kind == "RMC" and len(f) >= 10:
            return Rmc(f[1], f[2] == "A", _coord(f[3], f[4], 2),
                       _coord(f[5], f[6], 3),
                       float(f[7]) * KNOT_MS if f[7] else None,
                       float(f[8]) if f[8] else None, f[9])
    except ValueError:
        return None
    return None


# -- encoders: for the simulator and tests ---------------------------------
# The simulator speaks the receiver's own protocol, so simulated data goes
# through exactly the parser and checks that real data does.

def encode_nav_pvt(itow_ms: int, lat: float, lon: float, height_msl_m: float,
                   h_acc_m: float, v_acc_m: float,
                   vel_ned_ms: Tuple[float, float, float], s_acc_ms: float,
                   fix_type: int = 3, num_sv: int = 14, pdop: float = 1.5) -> bytes:
    p = bytearray(92)
    struct.pack_into("<IHBBBBBB", p, 0, itow_ms, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into("<BBBB", p, 20, fix_type, 0x01 if fix_type >= 2 else 0x00,
                     0, num_sv)
    struct.pack_into("<iiii", p, 24, round(lon * 1e7), round(lat * 1e7),
                     round(height_msl_m * 1000), round(height_msl_m * 1000))
    struct.pack_into("<II", p, 40, round(h_acc_m * 1000), round(v_acc_m * 1000))
    vn, ve, vd = vel_ned_ms
    struct.pack_into("<iiii", p, 48, round(vn * 1000), round(ve * 1000),
                     round(vd * 1000), round((vn * vn + ve * ve) ** 0.5 * 1000))
    struct.pack_into("<I", p, 68, round(s_acc_ms * 1000))
    struct.pack_into("<H", p, 76, round(pdop * 100))
    return ubx_frame(*NAV_PVT, bytes(p))


def encode_mon_rf(jamming_state: str, noise_per_ms: int = 90,
                  agc_count: int = 3000, jam_indicator: int = 10) -> bytes:
    code = {v: k for k, v in JAMMING_STATE.items()}[jamming_state]
    p = bytearray(4 + 24)
    struct.pack_into("<BB", p, 0, 0, 1)
    struct.pack_into("<BB", p, 4, 0, code)
    struct.pack_into("<HHB", p, 16, noise_per_ms, agc_count, jam_indicator)
    return ubx_frame(*MON_RF, bytes(p))


def encode_nav_sat(itow_ms: int, sats) -> bytes:
    """sats: (constellation, sv_id, cn0_dbhz, elevation_deg, azimuth_deg, used)."""
    code = {v: k for k, v in GNSS_ID.items()}
    p = bytearray(8 + 12 * len(sats))
    struct.pack_into("<IBB", p, 0, itow_ms, 1, len(sats))
    for k, (gnss, sv, cno, elev, azim, used) in enumerate(sats):
        struct.pack_into("<BBBbhhI", p, 8 + 12 * k, code[gnss], sv,
                         max(0, min(255, round(cno))), round(elev), round(azim), 0,
                         (0x08 if used else 0) | (0x07 if cno > 0 else 0))
    return ubx_frame(*NAV_SAT, bytes(p))
