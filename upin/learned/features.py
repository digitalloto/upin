"""
What the AI motion predictor reads, and what it is taught to predict.

A FLIGHT RECORD is a set of arrays on one time grid (RATE_HZ): attitude,
body-frame specific force and rates from the IMU, normalised throttle, and,
for training, GNSS velocity with a mask saying where GNSS was good.

FEATURES describe the last WINDOW_S seconds without reference to which way
the drone points: attitude, throttle, and the IMU's means, spreads and the
shape of the window in a few chunks. No heading, no position. The model
learns how this airframe moves, not where it was.

THE TARGET is velocity through the air, in the heading frame (forward,
right):
    air velocity = GNSS ground velocity - the flight's measured wind,
turned by the heading. At run time the prediction is turned back by the live
heading and the live wind is added. So the model learns the airframe, while
the wind it was trained in stays a separate, measured quantity, and the
weather check can compare it.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

RATE_HZ = 50.0
WINDOW_S = 1.0
STRIDE_S = 0.5
CHUNKS = 5
G = 9.80665


@dataclass
class FlightRecord:
    """One flight on a uniform time grid. Angles in radians."""
    flight_id: str
    t: np.ndarray
    roll: np.ndarray
    pitch: np.ndarray
    yaw: np.ndarray
    acc: np.ndarray            # (N, 3) body specific force, m/s^2
    gyro: np.ndarray           # (N, 3) body rates, rad/s
    throttle: np.ndarray       # 0..1
    gnss_vn: Optional[np.ndarray] = None
    gnss_ve: Optional[np.ndarray] = None
    gnss_ok: Optional[np.ndarray] = None
    temperature_c: Optional[np.ndarray] = None
    pressure_hpa: Optional[np.ndarray] = None
    airframe_id: str = ""
    source: str = ""           # "ardupilot log: <file>" or "SIMULATED"
    meta: Dict = field(default_factory=dict)

    def __len__(self):
        return len(self.t)

    def save(self, path: str) -> None:
        arrays = {k: getattr(self, k) for k in
                  ("t", "roll", "pitch", "yaw", "acc", "gyro", "throttle",
                   "gnss_vn", "gnss_ve", "gnss_ok", "temperature_c", "pressure_hpa")
                  if getattr(self, k) is not None}
        np.savez_compressed(path, **arrays)

    @classmethod
    def load(cls, path: str, flight_id: str, airframe_id: str = "",
             source: str = "") -> "FlightRecord":
        d = np.load(path, allow_pickle=False)
        get = lambda k: d[k] if k in d.files else None  # noqa: E731
        return cls(flight_id, d["t"], d["roll"], d["pitch"], d["yaw"], d["acc"],
                   d["gyro"], d["throttle"], get("gnss_vn"), get("gnss_ve"),
                   get("gnss_ok"), get("temperature_c"), get("pressure_hpa"),
                   airframe_id, source)


def thrust_direction(roll: float, pitch: float, yaw: float) -> Tuple[float, float]:
    """(tilt_deg, direction_deg): how far, and toward which compass
    direction, the thrust vector leans. Same rotation as
    command_dr.accel_from_command."""
    cphi, sphi = math.cos(roll), math.sin(roll)
    cth, sth = math.cos(pitch), math.sin(pitch)
    cpsi, spsi = math.cos(yaw), math.sin(yaw)
    a_n = -(cpsi * sth * cphi + spsi * sphi)
    a_e = -(spsi * sth * cphi - cpsi * sphi)
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, cth * cphi))))
    return tilt, math.degrees(math.atan2(a_e, a_n)) % 360.0


def mean_thrust_direction(roll, pitch, yaw) -> Tuple[float, float]:
    """(tilt_deg, direction_deg) averaged over a window: mean tilt, circular
    mean direction. Single samples are too noisy at low tilt for the Wind
    Learner's steadiness test."""
    td = [thrust_direction(a, b, c) for a, b, c in zip(roll, pitch, yaw)]
    tilt = float(np.mean([x[0] for x in td]))
    d = math.degrees(math.atan2(np.mean([math.sin(math.radians(x[1])) for x in td]),
                                np.mean([math.cos(math.radians(x[1])) for x in td])))
    return tilt, d % 360.0


def window_features(roll, pitch, acc, gyro, throttle) -> np.ndarray:
    """Heading-free features of one window (arrays of equal length)."""
    f = [roll.mean(), pitch.mean(), roll.std(), pitch.std(),
         throttle.mean(), throttle.std(),
         *acc.mean(axis=0), *acc.std(axis=0), *gyro.mean(axis=0), *gyro.std(axis=0)]
    for chunk in np.array_split(np.arange(len(roll)), CHUNKS):
        f += [roll[chunk].mean(), pitch[chunk].mean(),
              acc[chunk, 0].mean(), acc[chunk, 1].mean()]
    return np.asarray(f, dtype=float)


N_FEATURES = 6 + 12 + 4 * CHUNKS


def to_heading_frame(vn, ve, yaw):
    c, s = np.cos(yaw), np.sin(yaw)
    return vn * c + ve * s, -vn * s + ve * c


def from_heading_frame(fwd, right, yaw):
    c, s = np.cos(yaw), np.sin(yaw)
    return fwd * c - right * s, fwd * s + right * c


def windows(rec: FlightRecord, wind_ne: Tuple[float, float]):
    """Training windows: (X, Y, end_index). Only windows whose end has good
    GNSS. Y is (forward, right) air velocity."""
    n = int(WINDOW_S * RATE_HZ)
    step = int(STRIDE_S * RATE_HZ)
    X, Y, ends = [], [], []
    for end in range(n, len(rec) + 1, step):
        i = end - 1
        if rec.gnss_ok is None or not rec.gnss_ok[i]:
            continue
        sl = slice(end - n, end)
        X.append(window_features(rec.roll[sl], rec.pitch[sl], rec.acc[sl],
                                 rec.gyro[sl], rec.throttle[sl]))
        Y.append(to_heading_frame(rec.gnss_vn[i] - wind_ne[0],
                                  rec.gnss_ve[i] - wind_ne[1], rec.yaw[i]))
        ends.append(i)
    if not X:
        return np.zeros((0, N_FEATURES)), np.zeros((0, 2)), np.zeros(0, int)
    return np.asarray(X), np.asarray(Y, dtype=float), np.asarray(ends)


def input_ranges(rec: FlightRecord) -> Dict[str, float]:
    """What this flight's inputs spanned: for the input-range guard."""
    return {
        "max_tilt_deg": float(np.degrees(np.arccos(np.clip(
            np.cos(rec.roll) * np.cos(rec.pitch), -1, 1))).max()),
        "max_acc_horizontal_ms2": float(np.hypot(rec.acc[:, 0], rec.acc[:, 1]).max()),
        "max_gyro_rads": float(np.linalg.norm(rec.gyro, axis=1).max()),
    }
