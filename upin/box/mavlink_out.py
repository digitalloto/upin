"""
GPS_INPUT to the flight controller. **UNTESTED** -- never connected to a
flight controller or ArduPilot SITL.

ArduPilot accepts MAVLink GPS_INPUT (message 232) as a GPS when a GPS
instance is set to the MAV type (GPS1_TYPE = 14 on recent versions; older
ones use GPS_TYPE -- check the parameter list of the firmware in use). The
box then *is* the flight controller's GPS. If the box dies, messages stop,
the flight controller sees GPS lost and runs its own failsafe.

What is sent per mode:

  TRUSTED   the receiver's fix and accuracies, fix_type 3
  DEGRADED  by default, fix_type 0 (no fix): the flight controller's
            failsafe decides. With forward_degraded=True, UPIN's estimate
            with its own h_acc and fix_type 3. Leave it off until the
            flight controller's response to a growing h_acc has been tested
            in SITL -- ArduPilot's EKF may weight the estimate differently
            from what h_acc suggests.
  NO_FIX    fix_type 0

The message is built as plain data (`build`) so it can be tested without
pymavlink; `send` imports pymavlink only when a connection is made.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from upin.box.gateway import DEGRADED, NO_FIX, TRUSTED, GatewayOutput

GPS_EPOCH_UNIX = 315964800          # 1980-01-06
LEAP_SECONDS_GPS_UTC = 18
"""GPS - UTC since 2017. A constant that changes when a leap second is
announced; the receiver's own GPS time is the better source once parsed."""

# GPS_INPUT_IGNORE_FLAGS
IGNORE_ALT = 1
IGNORE_HDOP = 2
IGNORE_VDOP = 4
IGNORE_VEL_HORIZ = 8
IGNORE_VEL_VERT = 16
IGNORE_SPEED_ACCURACY = 32
IGNORE_HORIZONTAL_ACCURACY = 64
IGNORE_VERTICAL_ACCURACY = 128


@dataclass
class GpsInput:
    time_usec: int
    gps_id: int
    ignore_flags: int
    time_week_ms: int
    time_week: int
    fix_type: int
    lat: int                        # degE7
    lon: int                        # degE7
    alt: float                      # m, MSL
    hdop: float
    vdop: float
    vn: float
    ve: float
    vd: float
    speed_accuracy: float
    horiz_accuracy: float
    vert_accuracy: float
    satellites_visible: int


def gps_week(unix_s: float):
    g = unix_s - GPS_EPOCH_UNIX + LEAP_SECONDS_GPS_UTC
    week = int(g // 604800)
    return week, int(round((g - week * 604800) * 1000))


def build(out: GatewayOutput, unix_s: float, forward_degraded: bool = False,
          gps_id: int = 0) -> GpsInput:
    week, week_ms = gps_week(unix_s)
    send_fix = out.mode == TRUSTED or (out.mode == DEGRADED and forward_degraded)
    if not send_fix or out.lat is None:
        return GpsInput(int(unix_s * 1e6), gps_id, 0xFF, week_ms, week, 0,
                        0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    flags = IGNORE_HDOP | IGNORE_VDOP
    if out.alt_m is None:
        flags |= IGNORE_ALT | IGNORE_VERTICAL_ACCURACY
    if out.vel_ned_ms is None:
        flags |= IGNORE_VEL_HORIZ | IGNORE_VEL_VERT | IGNORE_SPEED_ACCURACY
    if out.mode == DEGRADED:
        flags |= IGNORE_VEL_VERT | IGNORE_ALT | IGNORE_VERTICAL_ACCURACY
    vn, ve, vd = out.vel_ned_ms or (0.0, 0.0, 0.0)
    return GpsInput(
        int(unix_s * 1e6), gps_id, flags, week_ms, week, 3,
        int(round(out.lat * 1e7)), int(round(out.lon * 1e7)),
        out.alt_m or 0.0, 0.0, 0.0, vn, ve, vd, out.s_acc_ms or 0.0,
        out.h_acc_m or 0.0, 0.0, out.num_sv)


class GpsInputSender:
    UNTESTED = True

    def __init__(self, connection_string: str, forward_degraded: bool = False,
                 source_system: int = 1, source_component: int = 191,
                 gps_id: int = 0, conn=None):
        """gps_id: which GPS instance the flight controller files this under
        (0 = GPS 1, 1 = GPS 2). conn: an already-open pymavlink connection,
        so reading sensors and sending GPS_INPUT share one cable."""
        self.connection_string = connection_string
        self.forward_degraded = forward_degraded
        self.source_system = source_system
        self.source_component = source_component   # 191 = onboard computer
        self.gps_id = gps_id
        self._conn = conn

    def connect(self, timeout_s: float = 10.0):
        try:
            from pymavlink import mavutil  # noqa: WPS433 -- lazy by design
        except ImportError as exc:
            raise RuntimeError(
                "pymavlink is not installed. GpsInputSender is untested and "
                "needs `pip install pymavlink` plus a flight controller or "
                "ArduPilot SITL.") from exc
        self._conn = mavutil.mavlink_connection(
            self.connection_string, source_system=self.source_system,
            source_component=self.source_component)
        if self._conn.wait_heartbeat(timeout=timeout_s) is None:
            raise RuntimeError(f"no heartbeat from {self.connection_string}")
        return self._conn

    def send(self, out: GatewayOutput, unix_s: Optional[float] = None) -> GpsInput:
        if self._conn is None:
            raise RuntimeError("not connected; call connect() first")
        m = build(out, time.time() if unix_s is None else unix_s,
                  self.forward_degraded, gps_id=self.gps_id)
        self._conn.mav.gps_input_send(
            m.time_usec, m.gps_id, m.ignore_flags, m.time_week_ms, m.time_week,
            m.fix_type, m.lat, m.lon, m.alt, m.hdop, m.vdop, m.vn, m.ve, m.vd,
            m.speed_accuracy, m.horiz_accuracy, m.vert_accuracy,
            m.satellites_visible)
        return m
