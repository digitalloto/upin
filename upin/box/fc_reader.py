"""
Sensor data from the flight controller, over MAVLink. **UNTESTED** against a
real flight controller or ArduPilot SITL.

The flight controller already reads the drone's IMU, compass, barometer,
optical flow and rangefinder, and its own GPS. It streams them as MAVLink
messages on the same cable the box uses to send GPS_INPUT, so one cable
carries both directions.

WHAT IS READ, AND WHAT IS REFUSED

  ATTITUDE          heading, pitch, roll
  SCALED_PRESSURE   barometric pressure -> pressure altitude
  OPTICAL_FLOW      ground velocity from the downward flow sensor
  DISTANCE_SENSOR   height above ground
  GPS_RAW_INT       the flight controller's own GPS -- an independent
                    second receiver for the cross-check

  GLOBAL_POSITION_INT, LOCAL_POSITION_NED, GPS2_RAW   ignored, on purpose

Once the flight controller uses the box's GPS, its own position and velocity
are partly made from UPIN's output. Feeding them back into UPIN would be
circular: UPIN would confirm itself. GPS2_RAW is the box's own output echoed
back. They are counted in `ignored`, never used.

The heading in ATTITUDE comes from the flight controller's EKF, which can use
GNSS velocity to align yaw. That is a weak dependence, not a loop through
position, and it is stated rather than hidden. Field names follow the MAVLink
common message set. Whether ArduPilot fills OPTICAL_FLOW's compensated
velocity fields, and which way the sensor's x and y point on the airframe,
must be checked on the bench: push the rig forward and look at the sign.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Union

# MAVLink message ids, for SET_MESSAGE_INTERVAL
MSG_IDS = {"GPS_RAW_INT": 24, "SCALED_PRESSURE": 29, "ATTITUDE": 30,
           "OPTICAL_FLOW": 100, "DISTANCE_SENSOR": 132}
MAV_CMD_SET_MESSAGE_INTERVAL = 511
MAV_SENSOR_ROTATION_PITCH_270 = 25          # facing down

CIRCULAR = ("GLOBAL_POSITION_INT", "LOCAL_POSITION_NED", "GPS2_RAW")

P0_HPA = 1013.25


def pressure_altitude_m(press_hpa: float) -> float:
    """International Standard Atmosphere pressure altitude. Off from true
    altitude by the day's weather; the box only ever uses its changes,
    tied to GNSS at the last trusted fix."""
    return 44330.0 * (1.0 - (press_hpa / P0_HPA) ** (1.0 / 5.255))


@dataclass
class Attitude:
    t: float
    roll_deg: float
    pitch_deg: float
    heading_deg: float


@dataclass
class Baro:
    t: float
    press_hpa: float
    pressure_alt_m: float


@dataclass
class Flow:
    t: float
    forward_ms: float               # sensor x, assumed forward -- check
    right_ms: float                 # sensor y, assumed right -- check
    quality: int                    # 0 = invalid, 255 = best
    ground_distance_m: Optional[float]


@dataclass
class Range:
    t: float
    distance_m: float


@dataclass
class FcGps:
    t: float
    fix_type: int
    lat: float
    lon: float
    alt_m: float
    h_acc_m: Optional[float]        # None when the receiver does not report it
    satellites: int
    vel_ne_ms: Optional[tuple] = None   # from ground speed and course, if reported
    vel_acc_ms: Optional[float] = None  # None when not reported


FcSample = Union[Attitude, Baro, Flow, Range, FcGps]


@dataclass
class FcState:
    attitude: Optional[Attitude] = None
    baro: Optional[Baro] = None
    flow: Optional[Flow] = None
    range: Optional[Range] = None
    gps: Optional[FcGps] = None


class FcReader:
    """Turns MAVLink messages into samples. Works on any object with
    get_type() and the message's fields, so it is testable without
    pymavlink."""

    UNTESTED = True

    def __init__(self):
        self.state = FcState()
        self.ignored: Dict[str, int] = {}
        self.counts: Dict[str, int] = {}

    def handle(self, msg, now: float) -> Optional[FcSample]:
        kind = msg.get_type()
        if kind in CIRCULAR:
            self.ignored[kind] = self.ignored.get(kind, 0) + 1
            return None
        parse = getattr(self, "_" + kind.lower(), None)
        if parse is None:
            return None
        sample = parse(msg, now)
        if sample is not None:
            self.counts[kind] = self.counts.get(kind, 0) + 1
        return sample

    def _attitude(self, m, now):
        a = Attitude(now, math.degrees(m.roll), math.degrees(m.pitch),
                     math.degrees(m.yaw) % 360.0)
        self.state.attitude = a
        return a

    def _scaled_pressure(self, m, now):
        if not m.press_abs or m.press_abs <= 0:
            return None
        b = Baro(now, m.press_abs, pressure_altitude_m(m.press_abs))
        self.state.baro = b
        return b

    def _optical_flow(self, m, now):
        if m.quality <= 0:
            self.state.flow = None
            return None
        gd = m.ground_distance if m.ground_distance and m.ground_distance > 0 else None
        f = Flow(now, m.flow_comp_m_x, m.flow_comp_m_y, m.quality, gd)
        self.state.flow = f
        return f

    def _distance_sensor(self, m, now):
        if getattr(m, "orientation", MAV_SENSOR_ROTATION_PITCH_270) != MAV_SENSOR_ROTATION_PITCH_270:
            return None
        if m.current_distance <= 0:
            return None
        r = Range(now, m.current_distance / 100.0)
        self.state.range = r
        return r

    def _gps_raw_int(self, m, now):
        h_acc = getattr(m, "h_acc", 0) or 0       # MAVLink 2 extension, mm
        vel_acc = getattr(m, "vel_acc", 0) or 0   # MAVLink 2 extension, mm/s
        vel, cog = getattr(m, "vel", 65535), getattr(m, "cog", 65535)
        vel_ne = None
        if vel != 65535 and cog != 65535:          # UINT16_MAX = unknown
            c = math.radians(cog / 100.0)
            vel_ne = (vel / 100.0 * math.cos(c), vel / 100.0 * math.sin(c))
        g = FcGps(now, m.fix_type, m.lat * 1e-7, m.lon * 1e-7, m.alt / 1000.0,
                  h_acc / 1000.0 if h_acc > 0 else None, m.satellites_visible,
                  vel_ne, vel_acc / 1000.0 if vel_acc > 0 else None)
        self.state.gps = g
        return g


def request_streams(conn, rate_hz: float = 10.0) -> None:
    """Ask the flight controller for each message at rate_hz. UNTESTED."""
    interval_us = int(1e6 / rate_hz)
    for msg_id in MSG_IDS.values():
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            MAV_CMD_SET_MESSAGE_INTERVAL, 0, msg_id, interval_us, 0, 0, 0, 0, 0)
