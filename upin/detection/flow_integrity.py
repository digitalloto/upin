"""
Is the optical flow telling the truth?

A downward optical-flow sensor measures how the ground slides under the
camera and assumes the ground never moves. Project a moving pattern on the
floor -- a sweeping grid of laser dots -- and the sensor reports the drone
drifting when it is not; the flight controller flies to cancel the "drift"
and is dragged along. A camera alone cannot tell "I moved" from "the floor
moved". The answer is the same as for GNSS spoofing: check it against
sources the attacker does not control.

  1 IMU          a change in flow velocity over the last ~1.5 s needs an
                 acceleration the IMU felt (gravity removed using attitude).
                 Flow jumps the IMU did not feel: the ground moved. The IMU
                 feels accelerations the flow did not show: the drone is
                 being dragged while the flow is held still. Both fire.
  2 GNSS         while GNSS is trusted, flow must agree with GNSS velocity
  3 AI predictor when layer 147 has a model, flow must agree with it

Each comparison uses the stated uncertainty of both sides; thresholds are
ASSUMPTIONS until calibrated on the real flow sensor, so the box only warns
by default (flow_check_action = "warn"). In "distrust" mode a suspect flow
is not fed to the Kalman filter, and the substitute is stated.

WHAT IT CANNOT CATCH -- stated, and asserted in tests

A sudden jump the IMU did not feel is LATCHED: the flow stays suspect until
the same jump reverses (the pattern stopped) or GNSS or the predictor
confirm it, so a pattern that keeps moving at a steady speed is not
forgotten after the first second. Without GNSS or a predictor, a false latch
keeps flow out until it reverses or the latch expires (LATCH_MAX_S) -- the
cost is coasting, stated, never a poisoned estimate. A reference too coarse
to have resolved the jump (heading error at speed) cannot clear it.

A drag slow enough that its acceleration hides in the IMU's noise over the
window passes test 1. Tests 2 and 3 catch it only while GNSS or a predictor
model is available. Inside UPIN's own camera flow layer (roadmap item 8)
the stronger fix is weighted RANSAC over the tracked points -- trusting
points that have agreed since takeoff -- which a single averaged sensor
value cannot do.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Tuple

import numpy as np

G = 9.80665
OK, SUSPECT, NOT_RUN = "OK", "SUSPECT", "NOT_RUN"


def _rot_nb(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch),
                              math.sin(pitch), math.cos(yaw), math.sin(yaw))
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr]])


class FlowIntegrityCheck:
    WINDOW_S = 1.5
    K_SIGMA = 4.0
    """Four sigma: an honest flow fails a single comparison rarely."""
    FLOW_SIGMA_MS = 0.2
    """**Assumption.** Flow velocity noise, 1 sigma per axis."""
    ACC_SIGMA_MS2 = 0.15
    """**Assumption.** IMU horizontal acceleration error after removing
    gravity, 1 sigma -- mostly from attitude error (1 degree of tilt error
    leaks 0.17 m/s^2 of gravity)."""
    HOLD_S = 5.0
    """A flag stays up this long after the last failing comparison, so an
    ongoing attack does not flicker in and out."""
    MAX_AGE_S = 2.0
    MATCH_S = 0.25
    """A flow sample must be this close in time to the GNSS or predictor
    velocity it is compared with."""

    LATCH_MAX_S = 60.0
    """**Assumption.** A latch nothing has cleared expires after this, so a
    false latch cannot keep flow out for a whole outage. An attack that keeps
    a steady speed for longer is then re-admitted -- stated as a limit."""
    HEADING_NOISE_DEG = 2.0
    """**Assumption.** Heading noise from one sample to the next; it turns
    into flow velocity noise in north/east at speed."""

    def __init__(self, heading_sigma_deg: float = 5.0):
        """heading_sigma_deg: the heading's overall error (bias included), as
        configured for the box; it enters the absolute comparisons."""
        self.heading_sigma_deg = heading_sigma_deg
        self._latch: Optional[Tuple[float, float]] = None
        self._latch_t = 0.0
        self._reversal: Optional[Tuple[float, float, float]] = None
        self._flow: Deque[Tuple[float, float, float]] = deque()   # t, vn, ve
        self._imu: Deque[Tuple[float, float, float]] = deque()    # t, an, ae
        self._att: Optional[Tuple[float, float, float, float]] = None
        self._gnss: Optional[Tuple[float, float, float, float]] = None
        self._pred: Optional[Tuple[float, float, float, float]] = None
        self._last_fire: Optional[float] = None
        self._last_fire_tests: List[str] = []
        self.last: Optional[dict] = None

    # -- inputs -------------------------------------------------------------

    def _trim(self, buf, t):
        while buf and buf[0][0] < t - self.WINDOW_S - 1.0:
            buf.popleft()

    def feed_attitude(self, roll: float, pitch: float, yaw: float, t: float) -> None:
        self._att = (t, roll, pitch, yaw)

    def feed_flow(self, forward_ms: float, right_ms: float, t: float) -> None:
        """Body-frame flow velocity; turned to north/east with the latest
        heading."""
        if self._att is None:
            return
        y = self._att[3]
        vn = forward_ms * math.cos(y) - right_ms * math.sin(y)
        ve = forward_ms * math.sin(y) + right_ms * math.cos(y)
        self._flow.append((t, vn, ve))
        self._trim(self._flow, t)

    def feed_imu(self, acc_body, t: float) -> None:
        """Body specific force (m/s^2). Turned to north/east with attitude,
        gravity removed."""
        if self._att is None:
            return
        _, r, p, y = self._att
        a = _rot_nb(r, p, y) @ np.asarray(acc_body, float) + np.array([0.0, 0.0, G])
        self._imu.append((t, float(a[0]), float(a[1])))
        self._trim(self._imu, t)

    def feed_gnss_velocity(self, vn: float, ve: float, sigma: float, t: float) -> None:
        self._gnss = (t, vn, ve, sigma)

    def feed_predictor(self, vn: float, ve: float, sigma: float, t: float) -> None:
        self._pred = (t, vn, ve, sigma)

    # -- the judgement --------------------------------------------------------

    def check(self, t: float) -> dict:
        tests: List[dict] = []

        def test(name, fired, value, threshold):
            tests.append({"test": name, "fired": bool(fired), "value": value,
                          "threshold": threshold, "unit": "m/s"})

        if not self._flow or t - self._flow[-1][0] > self.MAX_AGE_S:
            self.last = {"verdict": NOT_RUN, "reason": "no recent optical flow", "tests": []}
            return self.last
        tf, vn, ve = self._flow[-1]
        speed = math.hypot(vn, ve)
        released = ""

        # 1 IMU: velocity change vs integrated acceleration over the window.
        start = next((f for f in self._flow if f[0] >= tf - self.WINDOW_S), None)
        imu = [x for x in self._imu if start is not None and start[0] <= x[0] <= tf]
        if start is not None and tf - start[0] >= 0.5 and len(imu) >= 2 \
                and imu[-1][0] - imu[0][0] >= 0.8 * (tf - start[0]):
            ti = np.array([x[0] for x in imu])
            dvn_imu = float(np.trapezoid([x[1] for x in imu], ti))
            dve_imu = float(np.trapezoid([x[2] for x in imu], ti))
            span = tf - start[0]
            rn, re = (vn - start[1]) - dvn_imu, (ve - start[2]) - dve_imu
            resid = math.hypot(rn, re)
            hw = speed * math.radians(self.HEADING_NOISE_DEG)
            lim = self.K_SIGMA * math.sqrt(2 * self.FLOW_SIGMA_MS ** 2 + 2 * hw ** 2
                                           + (self.ACC_SIGMA_MS2 * span) ** 2)
            fired = resid > lim
            rev = self._reversal
            if fired and self._latch is not None and \
                    math.hypot(rn + self._latch[0], re + self._latch[1]) <= lim:
                # The same jump, reversed: the ground pattern stopped.
                self._reversal = (rn, re, tf)
                self._latch, fired = None, False
                released = "flow stepped back by the unexplained amount"
            elif fired and rev is not None and tf - rev[2] <= self.WINDOW_S and \
                    math.hypot(rn - rev[0], re - rev[1]) <= lim:
                # Still the reversal, seen again while it is inside the window.
                fired = False
                released = "flow stepped back by the unexplained amount"
            elif fired and self._latch is None:
                self._latch, self._latch_t = (rn, re), t
            test("flow change vs IMU", fired, round(resid, 2), round(lim, 2))

        # 2 GNSS (fed only on trusted epochs) and 3 the AI predictor: absolute
        # comparisons, each with the flow sample nearest in time to it --
        # comparing across a time offset reads a turn as a disagreement. The
        # heading's bias counts fully here.
        hb = speed * math.radians(self.heading_sigma_deg)
        agreed = False
        for name, ref in (("flow vs trusted GNSS velocity", self._gnss),
                          ("flow vs AI predictor", self._pred)):
            if not ref or t - ref[0] > self.MAX_AGE_S:
                continue
            tr, rn_, re_, rs = ref
            near = min(self._flow, key=lambda f: abs(f[0] - tr))
            if abs(near[0] - tr) > self.MATCH_S:
                continue
            d = math.hypot(near[1] - rn_, near[2] - re_)
            lim = self.K_SIGMA * math.sqrt(self.FLOW_SIGMA_MS ** 2 + hb ** 2 + rs ** 2)
            test(name, d > lim, round(d, 2), round(lim, 2))
            # A reference too coarse to have seen the latched jump cannot
            # clear it.
            if self._latch is not None and lim < 0.5 * math.hypot(*self._latch) and d <= lim:
                agreed = True
        if self._latch is not None and agreed and not any(x["fired"] for x in tests):
            self._latch = None
            released = "flow confirmed by an absolute reference"
        elif self._latch is not None and t - self._latch_t > self.LATCH_MAX_S:
            self._latch = None
            released = (f"latch expired after {self.LATCH_MAX_S:.0f} s; flow re-admitted, "
                        f"the filter's gate still guards it")

        fired = [x["test"] for x in tests if x["fired"]]
        if fired:
            self._last_fire, self._last_fire_tests = t, fired
        held = self._last_fire is not None and t - self._last_fire <= self.HOLD_S
        if fired or held or self._latch is not None:
            names = fired or self._last_fire_tests
            why = "" if fired else (" (latched: unexplained jump not yet reversed or "
                                    "confirmed)" if self._latch is not None else
                                    f" (held {t - self._last_fire:.0f} s)")
            self.last = {"verdict": SUSPECT, "reason":
                         f"optical flow suspect: {', '.join(names)}{why}", "tests": tests}
        elif not tests:
            self.last = {"verdict": NOT_RUN, "reason": "nothing to compare flow with "
                         "(needs IMU, trusted GNSS or the AI predictor)", "tests": []}
        else:
            self.last = {"verdict": OK, "reason": "flow agrees with "
                         + ", ".join(x["test"].split(" vs ")[-1] for x in tests)
                         + (f"; {released}" if released else ""), "tests": tests}
        return self.last
