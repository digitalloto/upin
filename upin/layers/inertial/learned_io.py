"""
Layer 147 -- AI motion predictor (learned inertial odometry), learnedio_b14.

Like a model that predicts the next character from the text so far, this
predicts the drone's next move from the last second of its IMU, attitude and
throttle. It outputs a velocity and how sure it is; the Kalman filter adds
that move to the last fix and keeps it on point, and its consistency gate
throws the prediction out when it is clearly wrong. It never reports a
position of its own.

It is trained on the drone's own test flights, one flight at a time
(upin/learned/flight_library.py, tools/learn_from_flight.py), and every
model records the weather and manoeuvres it was trained in. In flight the
layer compares the live conditions with that envelope:

  inside            normal
  outside           flagged with the numbers, uncertainty widened
  far outside       declines -- "wind 14 m/s; trained only up to 5 m/s"

The model predicts velocity THROUGH THE AIR; the live wind (the Wind
Learner's estimate, frozen when GNSS goes) is added to get ground velocity.
Without a wind estimate it declines rather than assume calm.

WHAT IT CANNOT DO -- stated

- It knows only the airframe, payload and conditions it was trained on.
- A model trained on simulated flights knows only the simulator.
- Its errors persist from second to second, and a wind error persists for
  the whole outage. The persistence is measured on validation flights
  (error_rho) and used to inflate the uncertainty it reports; the frozen
  wind's error is still a bias the box's filter treats as noise. The
  learning record measures the effect on flights it never saw.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.sensor_requirements import DataInput, Hardware, SensorRequirement
from upin.learned.features import RATE_HZ, WINDOW_S, from_heading_frame, window_features
from upin.learned.inertial_net import InertialNet


class LearnedInertialOdometryLayer(NavigationLayer):
    """Predicts velocity from IMU, attitude and throttle with a model trained
    on this airframe's own flights."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("flight controller IMU and attitude", already_on_most_drones=True,
                     why="the motion the model reads",
                     typical_part="ArduPilot flight controller over MAVLink"),
        ],
        inputs=[
            DataInput("trained model for this airframe", feed_method="load_model",
                      units="model file from tools/learn_from_flight.py",
                      why="trained on this airframe's own test flights"),
            DataInput("IMU specific force and rates", feed_method="feed_imu",
                      units="m/s^2, rad/s", why="the last second of motion"),
            DataInput("attitude", feed_method="feed_attitude", units="radians",
                      why="tilt drives airspeed; heading turns it to north/east"),
            DataInput("throttle", feed_method="feed_throttle", units="0..1"),
            DataInput("wind estimate", feed_method="set_wind", units="m/s",
                      why="air velocity + wind = ground velocity"),
            DataInput("temperature (optional)", feed_method="set_temperature",
                      units="deg C", why="weather check against training"),
        ],
        preconditions=("model trained on the same airframe",
                       "a learned wind (the drone flew steady legs on a few headings "
                       "while GNSS was good)"),
        notes="Velocity only, never a position. Flags conditions outside its "
              "training. Off in the box unless a model is configured.",
    )

    WIDEN_PER_FLAG = 2.0
    BUFFER_S = 1.6

    def __init__(self, model: Optional[InertialNet] = None, airframe_id: str = ""):
        super().__init__(
            layer_id="learnedio_b14", layer_number=147,
            name="AI Motion Predictor (Learned Inertial Odometry)",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.VELOCITY],
            description="Predicts velocity from the last second of IMU, attitude "
                        "and throttle, with a model trained on this airframe's "
                        "own flights. Flags weather outside its training.",
        )
        self.model = model
        self.airframe_id = airframe_id
        self._imu: Deque[Tuple[float, np.ndarray]] = deque()
        self._att: Deque[Tuple[float, float, float, float]] = deque()
        self._thr: Deque[Tuple[float, float]] = deque()
        self._wind: Optional[dict] = None
        self._temp: Optional[float] = None
        self.last: Optional[dict] = None

    # -- contract ---------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.0          # no position of its own

    # -- inputs -----------------------------------------------------------

    def load_model(self, path: str) -> None:
        self.model = InertialNet.load(path)

    def _trim(self, buf, t):
        while buf and buf[0][0] < t - self.BUFFER_S:
            buf.popleft()

    def feed_imu(self, acc, gyro, t: float) -> None:
        self._imu.append((t, np.r_[np.asarray(acc, float), np.asarray(gyro, float)]))
        self._trim(self._imu, t)

    def feed_attitude(self, roll: float, pitch: float, yaw: float, t: float) -> None:
        self._att.append((t, roll, pitch, yaw))
        self._trim(self._att, t)

    def feed_throttle(self, throttle: float, t: float) -> None:
        self._thr.append((t, float(throttle)))
        self._trim(self._thr, t)

    def set_wind(self, north_ms: float, east_ms: float, sigma_ms: float,
                 gust_sigma_ms: float = 0.0) -> None:
        self._wind = {"north_ms": north_ms, "east_ms": east_ms,
                      "sigma_ms": sigma_ms, "gust_sigma_ms": gust_sigma_ms}

    def clear_wind(self) -> None:
        self._wind = None

    def set_temperature(self, celsius: Optional[float]) -> None:
        self._temp = celsius

    # -- the prediction -----------------------------------------------------

    def _declined(self, reason_code: str, why: str) -> dict:
        self.last = {"status": "declined", "reason_code": reason_code, "reason": why,
                     **self._model_info()}
        return self.last

    def _model_info(self) -> dict:
        if self.model is None:
            return {"model": None}
        m = self.model.meta
        return {"model": {"version": m.get("version"), "airframe_id": m.get("airframe_id"),
                          "kind": m.get("kind"), "flights": len(m.get("trained_on", [])),
                          "validated": m.get("validated", False),
                          "envelope": m.get("envelope", {})}}

    def predict(self, t: float) -> dict:
        if self.model is None:
            return self._declined(NoFixReason.NO_CALIBRATION,
                                  "no trained model loaded")
        meta = self.model.meta
        if self.airframe_id and meta.get("airframe_id") not in (None, self.airframe_id):
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"model trained on airframe {meta.get('airframe_id')!r}, "
                                  f"this is {self.airframe_id!r}")
        span = (t - WINDOW_S, t)
        for name, buf in (("IMU", self._imu), ("attitude", self._att), ("throttle", self._thr)):
            if not buf or buf[0][0] > span[0] + 0.1 or buf[-1][0] < t - 0.25:
                return self._declined(NoFixReason.NO_INPUT,
                                      f"needs the last {WINDOW_S:.0f} s of {name}")
        if self._wind is None:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT,
                                  "no wind estimate: needs air velocity + wind")
        grid = np.linspace(span[0], span[1], int(WINDOW_S * RATE_HZ))
        ti = np.array([x[0] for x in self._imu])
        imu = np.stack([x[1] for x in self._imu])
        acc = np.stack([np.interp(grid, ti, imu[:, j]) for j in range(3)], 1)
        gyro = np.stack([np.interp(grid, ti, imu[:, j]) for j in range(3, 6)], 1)
        ta = np.array([x[0] for x in self._att])
        roll = np.interp(grid, ta, [x[1] for x in self._att])
        pitch = np.interp(grid, ta, [x[2] for x in self._att])
        yaw = float(self._att[-1][3])
        thr = np.interp(grid, [x[0] for x in self._thr], [x[1] for x in self._thr])

        flags, decline = self._conditions(roll, pitch, acc, gyro)
        if decline:
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  "far outside training: " + "; ".join(decline))
        X = window_features(roll, pitch, acc, gyro, thr)[None, :]
        mu, sig = self.model.predict(X)
        vn, ve = from_heading_frame(mu[0, 0], mu[0, 1], yaw)
        vn, ve = float(vn + self._wind["north_ms"]), float(ve + self._wind["east_ms"])
        widen = self.WIDEN_PER_FLAG ** min(len(flags), 2)
        s_air = float(sig.max()) * widen
        rho = float(meta.get("error_rho", 0.0))
        s_feed = math.sqrt(s_air ** 2 * (1 + rho) / (1 - rho) + self._wind["sigma_ms"] ** 2)
        self.last = {"status": "ok", "vn": vn, "ve": ve, "sigma_air_ms": s_air,
                     "sigma_ms": s_feed, "error_rho": rho, "widened_by": widen,
                     "flags": flags, "wind": dict(self._wind), "t": t,
                     **self._model_info()}
        return self.last

    def _conditions(self, roll, pitch, acc, gyro) -> Tuple[List[str], List[str]]:
        env = (self.model.meta or {}).get("envelope", {})
        flags, decline = [], []

        def check(name, value, limit, unit, far):
            if limit is None or value is None:
                return
            if value > far:
                decline.append(f"{name} {value:.1f} {unit}; trained only up to {limit:.1f}")
            elif value > limit:
                flags.append(f"{name} {value:.1f} {unit}: outside training (up to {limit:.1f})")

        w = env.get("wind_speed_ms")
        if w:
            speed = math.hypot(self._wind["north_ms"], self._wind["east_ms"])
            check("wind", speed, w[1] + max(1.0, 0.25 * w[1]), "m/s", 2 * w[1] + 2)
        g = env.get("gust_sigma_ms")
        if g:
            check("gusts", self._wind.get("gust_sigma_ms", 0.0), 1.5 * g[1] + 0.2, "m/s",
                  3 * g[1] + 1)
        tmp = env.get("temperature_c")
        if tmp and self._temp is not None:
            if not (tmp[0] - 10 <= self._temp <= tmp[1] + 10):
                flags.append(f"temperature {self._temp:.0f} °C: outside training "
                             f"({tmp[0]:.0f}–{tmp[1]:.0f} °C)")
        tilt = float(np.degrees(np.arccos(np.clip(np.cos(roll) * np.cos(pitch), -1, 1))).max())
        lim = env.get("max_tilt_deg")
        if lim:
            check("tilt", tilt, 1.2 * lim[1], "deg", 2 * lim[1])
        lim = env.get("max_gyro_rads")
        if lim:
            check("rotation rate", float(np.linalg.norm(gyro, axis=1).max()),
                  1.2 * lim[1], "rad/s", 2.5 * lim[1])
        return flags, decline

    def read(self) -> LayerReading:
        t = self._att[-1][0] if self._att else None
        v = self.predict(t) if t is not None else (
            self._declined(NoFixReason.NO_CALIBRATION, "no trained model loaded")
            if self.model is None else
            self._declined(NoFixReason.NO_INPUT, "no attitude or IMU received"))
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        return LayerReading(layer_id=self.layer_id, position=None,
                            velocity=math.hypot(v["vn"], v["ve"]),
                            heading=math.degrees(math.atan2(v["ve"], v["vn"])) % 360.0,
                            self_confidence=1.0 / (1.0 + v["sigma_ms"]),
                            is_valid=True,
                            raw_data={"fabricated": False, "independent": True, **v})
