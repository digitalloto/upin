"""
Parsers for what a GNSS receiver sends over its serial port.

UBX (u-blox binary) -- the messages the box needs:
  NAV-PVT  (0x01 0x07)  position, velocity, time, accuracy estimates
  NAV-SAT  (0x01 0x35)  every satellite tracked: constellation, C/N0,
                        elevation, whether used in the fix
  MON-RF   (0x0A 0x38)  RF front end: the receiver's own jamming state,
                        noise level and AGC per band (F9, M10)
  MON-HW   (0x0A 0x09)  the same on the M8 generation, which has no MON-RF:
                        jamming state, jamming indicator and AGC count

NMEA 0183 -- what receivers that are not u-blox speak (any talker: GP,
GL, GA, GB, GI for NavIC, GN for a blended fix):
  GGA  position, fix quality, satellites, HDOP, altitude
  RMC  position, validity, speed and course over ground
  GSA  fix dimension (2-D / 3-D), the satellites used, PDOP/HDOP/VDOP
  GSV  every satellite in view: PRN, elevation, azimuth, C/N0 -- the
       NAV-SAT equivalent, for the signal-power check
  GST  the receiver's own position error estimate, if it sends one
  ZDA  UTC date and time
NMEA carries no jamming state and no raw pseudoranges. Without GST the
receiver states no accuracy; the box then assumes one from HDOP (labelled).

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

import math
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple, Union

SYNC = b"\xb5\x62"

NAV_PVT = (0x01, 0x07)
NAV_SAT = (0x01, 0x35)
MON_RF = (0x0A, 0x38)
MON_HW = (0x0A, 0x09)

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


@dataclass
class MonHw:
    """MON-HW on the M8 generation. Offsets per the M8 interface description
    (protocol 18): noisePerMS at 16, agcCnt at 18, flags at 22 (bits 2-3 =
    jammingState), jamInd at 45. **Verify on the receiver bought.**"""
    noise_per_ms: int
    agc_count: int
    jamming_state: str
    jam_indicator: int

    @property
    def worst_state(self) -> str:
        return self.jamming_state

    def as_mon_rf(self) -> "MonRf":
        """The same facts in MON-RF's shape, so the box treats both alike."""
        return MonRf([RfBlock(0, self.jamming_state, self.noise_per_ms, self.agc_count,
                              self.jam_indicator)])


def parse_mon_hw(p: bytes) -> Optional[MonHw]:
    if len(p) < 60:
        return None
    noise, agc = struct.unpack_from("<HH", p, 16)
    flags = p[22]
    jam_ind = p[45]
    return MonHw(noise, agc, JAMMING_STATE[(flags >> 2) & 0x03], jam_ind)


def encode_mon_hw(jamming_state: str, noise_per_ms: int = 90, agc_count: int = 3000,
                  jam_indicator: int = 10) -> bytes:
    """A synthetic MON-HW frame for tests, in the layout parse_mon_hw reads."""
    code = {v: k for k, v in JAMMING_STATE.items()}[jamming_state]
    p = bytearray(60)
    struct.pack_into("<HH", p, 16, noise_per_ms, agc_count)
    p[22] = (code & 0x03) << 2
    p[45] = jam_indicator
    return ubx_frame(*MON_HW, bytes(p))


UbxMessage = Union[NavPvt, NavSat, MonRf, MonHw]


def decode_ubx(cls: int, mid: int, payload: bytes) -> Optional[UbxMessage]:
    if (cls, mid) == NAV_PVT:
        return parse_nav_pvt(payload)
    if (cls, mid) == NAV_SAT:
        return parse_nav_sat(payload)
    if (cls, mid) == MON_RF:
        return parse_mon_rf(payload)
    if (cls, mid) == MON_HW:
        return parse_mon_hw(payload)
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


@dataclass
class Gsa:
    talker: str                   # GP, GL, GA, GB, GI (NavIC), GN (all)
    fix_type: int                 # 1 none, 2 2-D, 3 3-D
    sat_ids: List[int]
    pdop: Optional[float]
    hdop: Optional[float]
    vdop: Optional[float]


@dataclass
class Gsv:
    talker: str
    total_msgs: int
    msg_num: int
    in_view: int
    sats: List[SatInfo]           # the up-to-four in this message; used=False until GSA says


@dataclass
class Gst:
    utc: str
    sigma_lat_m: Optional[float]
    sigma_lon_m: Optional[float]
    sigma_alt_m: Optional[float]

    @property
    def h_acc_m(self) -> Optional[float]:
        if self.sigma_lat_m is None or self.sigma_lon_m is None:
            return None
        return max(self.sigma_lat_m, self.sigma_lon_m)


@dataclass
class Zda:
    utc: str
    day: int
    month: int
    year: int


KNOT_MS = 1852.0 / 3600.0
TALKER_CONSTELLATION = {"GP": "gps", "GL": "glonass", "GA": "galileo", "GB": "beidou",
                        "BD": "beidou", "GI": "navic", "GQ": "qzss", "GN": "mixed"}


def _f(x: str) -> Optional[float]:
    return float(x) if x not in ("", None) else None


def parse_nmea(sentence: str) -> Optional[Union[Gga, Rmc, Gsa, Gsv, Gst, Zda]]:
    """GGA, RMC, GSA, GSV, GST or ZDA from any talker. None if the checksum
    is wrong or the sentence is another type."""
    f = _split(sentence)
    if f is None or len(f[0]) < 5:
        return None
    talker, kind = f[0][:2], f[0][2:]
    try:
        if kind == "GGA" and len(f) >= 10:
            return Gga(f[1], _coord(f[2], f[3], 2), _coord(f[4], f[5], 3),
                       int(f[6] or 0), int(f[7] or 0), _f(f[8]), _f(f[9]))
        if kind == "RMC" and len(f) >= 10:
            return Rmc(f[1], f[2] == "A", _coord(f[3], f[4], 2),
                       _coord(f[5], f[6], 3),
                       float(f[7]) * KNOT_MS if f[7] else None, _f(f[8]), f[9])
        if kind == "GSA" and len(f) >= 18:
            ids = [int(x) for x in f[3:15] if x]
            return Gsa(talker, int(f[2] or 1), ids, _f(f[15]), _f(f[16]), _f(f[17]))
        if kind == "GSV" and len(f) >= 4:
            sats = []
            for k in range(4, len(f) - 3, 4):
                if not f[k]:
                    continue
                sats.append(SatInfo(TALKER_CONSTELLATION.get(talker, talker.lower()), int(f[k]),
                                    int(f[k + 3] or 0), int(f[k + 1] or 0), int(f[k + 2] or 0), False))
            return Gsv(talker, int(f[1] or 1), int(f[2] or 1), int(f[3] or 0), sats)
        if kind == "GST" and len(f) >= 9:
            return Gst(f[1], _f(f[6]), _f(f[7]), _f(f[8]))
        if kind == "ZDA" and len(f) >= 5:
            return Zda(f[1], int(f[2] or 0), int(f[3] or 0), int(f[4] or 0))
    except ValueError:
        return None
    return None


@dataclass
class NmeaStats:
    sentences: int = 0
    bad_checksum: int = 0
    kinds: dict = field(default_factory=dict)


class NmeaStream:
    """Feed it bytes as they arrive; it yields parsed sentences. Binary
    (UBX) bytes on the same port are ignored, so both parsers can share."""

    def __init__(self):
        self._buf = bytearray()
        self.stats = NmeaStats()

    def feed(self, data: bytes) -> Iterator[Union[Gga, Rmc, Gsa, Gsv, Gst, Zda]]:
        self._buf.extend(data)
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                if len(self._buf) > 4096:
                    del self._buf[:-512]
                return
            line = bytes(self._buf[:i]); del self._buf[:i + 1]
            j = line.find(b"$")
            if j < 0:
                continue
            text = line[j:].decode("ascii", "ignore").strip()
            if "*" not in text:
                continue
            kind = text[3:6]
            self.stats.kinds[kind] = self.stats.kinds.get(kind, 0) + 1
            m = parse_nmea(text)
            if m is None:
                if _split(text) is None:
                    self.stats.bad_checksum += 1
                continue
            self.stats.sentences += 1
            yield m


@dataclass
class NmeaFix:
    """One receiver epoch assembled from a GGA and its RMC (same UTC), with
    the latest GSA, GST, ZDA and the satellites in view."""
    utc: str
    date: str
    lat: float
    lon: float
    alt_msl_m: Optional[float]
    quality: int
    num_sv: int
    hdop: Optional[float]
    fix_type: int                           # 3 for 3-D (GSA), else 2
    vel_ne_ms: Optional[Tuple[float, float]]
    pdop: Optional[float]
    vdop: Optional[float]
    gst_h_acc_m: Optional[float]
    gst_v_acc_m: Optional[float]
    sats: List[SatInfo]
    year: int = 0
    month: int = 0
    day: int = 0


class NmeaEpochBuilder:
    """Pairs each GGA with the RMC of the same UTC (either order); a GGA
    that never gets its RMC is released, without velocity, when the next
    GGA arrives. GSV messages are gathered per talker until a cycle is
    complete; GSA marks which satellites the fix used."""

    def __init__(self):
        self._gga: Optional[Gga] = None
        self._rmc: Optional[Rmc] = None
        self._gsa: Dict[str, Gsa] = {}
        self._gst: Optional[Gst] = None
        self._zda: Optional[Zda] = None
        self._gsv_partial: Dict[str, List[SatInfo]] = {}
        self._gsv_done: Dict[str, List[SatInfo]] = {}

    def feed(self, m) -> Optional[NmeaFix]:
        if isinstance(m, Gga):
            pending = None
            if self._gga is not None and (self._rmc is None or self._rmc.utc != self._gga.utc):
                pending = self._fix(self._gga, None)         # the previous GGA, no RMC came
            self._gga = m
            if self._rmc is not None and self._rmc.utc == m.utc:
                out = self._fix(m, self._rmc)
                self._gga = self._rmc = None
                return out
            return pending
        if isinstance(m, Rmc):
            self._rmc = m
            if self._gga is not None and self._gga.utc == m.utc:
                out = self._fix(self._gga, m)
                self._gga = self._rmc = None
                return out
            return None
        if isinstance(m, Gsa):
            self._gsa[m.talker] = m
        elif isinstance(m, Gst):
            self._gst = m
        elif isinstance(m, Zda):
            self._zda = m
        elif isinstance(m, Gsv):
            part = self._gsv_partial.setdefault(m.talker, [])
            if m.msg_num == 1:
                part.clear()
            part.extend(m.sats)
            if m.msg_num >= m.total_msgs:
                self._gsv_done[m.talker] = list(part)
                self._gsv_partial[m.talker] = []
        return None

    def satellites(self) -> List[SatInfo]:
        used = set()
        for g in self._gsa.values():
            used.update(g.sat_ids)
        out = []
        for sats in self._gsv_done.values():
            for s in sats:
                out.append(SatInfo(s.constellation, s.sv_id, s.cn0_dbhz, s.elevation_deg,
                                   s.azimuth_deg, s.sv_id in used))
        return out

    def _fix(self, gga: Gga, rmc: Optional[Rmc]) -> Optional[NmeaFix]:
        if gga.lat is None or gga.lon is None:
            return NmeaFix(gga.utc, rmc.date if rmc else "", 0.0, 0.0, None, 0, gga.num_sv, gga.hdop,
                           0, None, None, None, None, None, self.satellites())
        vel = None
        if rmc is not None and rmc.valid and rmc.speed_ms is not None and rmc.course_deg is not None:
            c = math.radians(rmc.course_deg)
            vel = (rmc.speed_ms * math.cos(c), rmc.speed_ms * math.sin(c))
        gsa = self._gsa.get("GN") or (next(iter(self._gsa.values())) if self._gsa else None)
        fix_type = 0 if gga.quality == 0 else (3 if (gsa is not None and gsa.fix_type == 3)
                                                 or (gsa is None and gga.alt_msl_m is not None) else 2)
        gst = self._gst                      # once per cycle; at worst one cycle old
        z = self._zda
        return NmeaFix(gga.utc, rmc.date if rmc else "", gga.lat, gga.lon, gga.alt_msl_m, gga.quality,
                       gga.num_sv, gga.hdop, fix_type, vel,
                       gsa.pdop if gsa else None, gsa.vdop if gsa else None,
                       gst.h_acc_m if gst else None, gst.sigma_alt_m if gst else None,
                       self.satellites(),
                       z.year if z else 0, z.month if z else 0, z.day if z else 0)


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
