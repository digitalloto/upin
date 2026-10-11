"""
SIMULATED flights, for testing the learning pipeline. Not real data.

A multirotor flies random legs (new heading, tilt and sideways lean every
few seconds) through a measured-style wind with gusts, using the same
physics as the rest of UPIN's simulator (command_dr.accel_from_command:
thrust rotated by attitude, gravity, quadratic drag on airspeed). The IMU
sees the specific force and body rates that motion implies, with noise.

A model trained on these learns this simulator. Nothing here says how well
a model would do on a real drone; that comes only from real flight logs.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math

import numpy as np

from upin.layers.inertial.command_dr import AirframeModel, MotorCommand, accel_from_command
from upin.learned.features import G, RATE_HZ, FlightRecord

SIM_AIRFRAME = AirframeModel(thrust_to_mass=22.5, drag_coeff=0.08, calibrated=True,
                             airframe_id="sim-quad")


def _rot_nb(roll, pitch, yaw):
    """Body-to-NED rotation, ZYX."""
    cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch),
                              math.sin(pitch), math.cos(yaw), math.sin(yaw))
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr]])


def simulate_flight(flight_id: str, seed: int, duration_s: float = 300.0,
                    wind_ms: float = 3.0, wind_toward_deg: float = 45.0,
                    gust_sigma_ms: float = 0.4, gust_tau_s: float = 5.0,
                    temperature_c: float = 30.0, max_tilt_deg: float = 18.0,
                    airframe: AirframeModel = SIM_AIRFRAME) -> FlightRecord:
    rng = np.random.default_rng(seed)
    dt = 1.0 / RATE_HZ
    n = int(duration_s * RATE_HZ)
    wd = math.radians(wind_toward_deg)
    wind_mean = np.array([wind_ms * math.cos(wd), wind_ms * math.sin(wd), 0.0])
    gust = np.zeros(3)
    v = wind_mean.copy()
    roll = pitch = 0.0
    yaw = rng.uniform(0, 2 * math.pi)
    tgt = (0.0, 0.0, yaw)
    leg_end = 0.0
    out = {k: np.zeros(n) for k in ("roll", "pitch", "yaw", "thr", "vn", "ve")}
    acc_b, gyr_b = np.zeros((n, 3)), np.zeros((n, 3))
    prev = (roll, pitch, yaw)
    for k in range(n):
        t = k * dt
        if t >= leg_end:
            tilt = math.radians(rng.uniform(3, max_tilt_deg))
            lean = math.radians(rng.uniform(-6, 6))
            tgt = (lean, -tilt, rng.uniform(0, 2 * math.pi))
            leg_end = t + rng.uniform(8, 25)
        a = 1 - math.exp(-dt / 0.5)
        roll += a * (tgt[0] - roll)
        pitch += a * (tgt[1] - pitch)
        dyaw = (tgt[2] - yaw + math.pi) % (2 * math.pi) - math.pi
        yaw = (yaw + max(-0.6 * dt, min(0.6 * dt, dyaw))) % (2 * math.pi)
        thr = airframe.hover_throttle / max(math.cos(roll) * math.cos(pitch), 0.3)
        gust += (-gust / gust_tau_s) * dt + gust_sigma_ms * math.sqrt(2 * dt / gust_tau_s) * rng.normal(size=3) * np.array([1, 1, 0])
        cmd = MotorCommand(t, thr, roll, pitch, yaw)
        acc = accel_from_command(cmd, airframe, v, wind_mean + gust)
        acc[2] = 0.0                      # altitude held
        v = v + acc * dt
        v[2] = 0.0
        f_ned = acc - np.array([0.0, 0.0, G])
        acc_b[k] = _rot_nb(roll, pitch, yaw).T @ f_ned
        dr, dp = (roll - prev[0]) / dt, (pitch - prev[1]) / dt
        dy = ((yaw - prev[2] + math.pi) % (2 * math.pi) - math.pi) / dt
        gyr_b[k] = [dr - math.sin(pitch) * dy,
                    math.cos(roll) * dp + math.sin(roll) * math.cos(pitch) * dy,
                    -math.sin(roll) * dp + math.cos(roll) * math.cos(pitch) * dy]
        prev = (roll, pitch, yaw)
        for key, val in (("roll", roll), ("pitch", pitch), ("yaw", yaw), ("thr", thr),
                         ("vn", v[0]), ("ve", v[1])):
            out[key][k] = val
    att_noise = math.radians(0.3)
    return FlightRecord(
        flight_id=flight_id, t=np.arange(n) * dt,
        roll=out["roll"] + rng.normal(0, att_noise, n),
        pitch=out["pitch"] + rng.normal(0, att_noise, n),
        yaw=(out["yaw"] + rng.normal(0, att_noise, n)) % (2 * math.pi),
        acc=acc_b + rng.normal(0, 0.05, (n, 3)),
        gyro=gyr_b + rng.normal(0, 0.003, (n, 3)),
        throttle=out["thr"] + rng.normal(0, 0.005, n),
        gnss_vn=out["vn"] + rng.normal(0, 0.08, n),
        gnss_ve=out["ve"] + rng.normal(0, 0.08, n),
        gnss_ok=np.ones(n, dtype=bool),
        temperature_c=temperature_c + rng.normal(0, 0.2, n),
        pressure_hpa=1005.0 + rng.normal(0, 0.05, n),
        airframe_id=airframe.airframe_id, source="SIMULATED",
        meta={"true_wind_ne": [float(wind_mean[0]), float(wind_mean[1])],
              "true_gust_sigma_ms": gust_sigma_ms})
