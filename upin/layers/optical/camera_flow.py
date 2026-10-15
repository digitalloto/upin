"""
Layer 148 -- camera optical flow with weighted RANSAC (camflow_e24).

UPIN's own ground-velocity sensor from a downward camera. A flow-sensor
chip on the flight controller averages the motion of everything it sees,
so a sweeping grid of laser dots drags its answer and the drone follows the
dots (upin/detection/flow_integrity.py catches that from the outside). This
layer works from the pixels, so it can do what the chip cannot: judge each
tracked point and keep only the motion the trusted ones agree on.

HOW

  patches        a grid of small patches in the last frame, each found again
                 in the new frame by block matching (sum of absolute
                 differences over a search window, parabolic sub-pixel
                 refinement). Each patch is one point with a displacement, a
                 contrast and a distinctiveness.
  gyro           the shift the drone's own rotation would cause (from the
                 body rates and the focal length) is removed first, so a turn
                 is not read as a sideways slide.
  weighted RANSAC
                 every point proposes "the ground moved by my displacement";
                 the proposal that the most TRUST agrees with wins, and the
                 answer is the trust-weighted mean of its inliers. Trust is
                 earned by agreeing since takeoff and lost quickly by
                 disagreeing, so points on the still floor outweigh points on
                 a moving pattern.
  velocity       pixels become metres with the rangefinder height and the
                 field of view; sigma from the inliers' spread, the height's
                 sigma and the frame interval.

WHERE IT REFUSES

No frame pair, frames too far apart, no height, too little texture (most
patches below MIN_CONTRAST or not distinctive), no rotation data, or less
than half the trust agreeing on one motion: "cannot tell the drone moving
from the floor moving". Each declines and says which.

LIMITS: needs texture, height and light; if the moving pattern covers most
points from before takeoff there is nothing to trust against; roll/pitch
compensation signs are from the geometry and UNVERIFIED on hardware (yaw
is verified in simulation); compute cost on the Pi is to be measured.
Thresholds are assumptions until measured on the real camera.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Tuple

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.sensor_requirements import DataInput, Hardware, SensorRequirement


class CameraFlowLayer(NavigationLayer):
    """Ground velocity from a downward camera, robust to moving patterns."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("downward camera", why="the frames the flow is measured in",
                     typical_part="Pi global-shutter camera on the companion computer"),
            Hardware("downward rangefinder", already_on_most_drones=True,
                     why="turns pixels into metres",
                     typical_part="lidar or ultrasonic rangefinder on the flight controller"),
            Hardware("gyroscope", already_on_most_drones=True,
                     why="removes the drone's own rotation from the flow",
                     typical_part="flight controller IMU over MAVLink"),
        ],
        inputs=[
            DataInput("camera frames", feed_method="feed_frame",
                      units="greyscale image, field of view in degrees"),
            DataInput("height above ground", feed_method="feed_height", units="m, 1-sigma m"),
            DataInput("body rates", feed_method="feed_gyro", units="rad/s"),
            DataInput("attitude", feed_method="feed_attitude", units="radians, degrees",
                      why="heading turns body velocity to north/east"),
        ],
        preconditions=("ground texture in view", "frames no more than MAX_DT_S apart"),
        notes="Velocity only, never a position. Keeps the motion the trusted "
              "points agree on; a moving pattern is thrown out as outliers.",
    )

    PATCH_PX = 16
    GRID = 6
    SEARCH_PX = 12
    MAX_DT_S = 0.5
    HEIGHT_STALE_S = 1.0
    GYRO_STALE_S = 0.5
    MIN_CONTRAST = 0.03
    """**Assumption.** Patch standard deviation (0..1 image) below which a
    patch has no texture to track. Measure on the real camera."""
    MIN_DISTINCT = 1.4
    """**Assumption.** Mean-to-minimum SAD ratio below which a match is not
    distinctive (a flat or repeating patch)."""
    SAD_CAP = 0.1
    """**Assumption.** Per-pixel difference cap (0..1 image), about three
    times the ground's texture contrast. A few bright pixels -- a laser dot
    -- then cannot dominate a patch's match: a robust (truncated) sum of
    absolute differences. None disables it, for the naive baseline."""
    USE_RANSAC = True
    """False gives a plain mean over all tracked points: the naive flow the
    reel's attack works on. For comparison only."""
    INLIER_TOL_PX = 1.5
    """**Assumption.** How far a point may differ from the winning motion and
    still count as agreeing: block matching on low-contrast ground scatters
    by about a pixel. Measure on the real camera."""
    CLEAR_OUTLIER_X = 2.0
    """A point beyond CLEAR_OUTLIER_X x the tolerance is clearly on something
    that moved differently and loses trust; between the two it is neither
    trusted more nor less."""
    MIN_AGREEING_TRUST = 0.5
    FULL_AGREEMENT = 0.8
    """Agreement below this widens the stated sigma in proportion."""
    TRUST_INIT, TRUST_GAIN, TRUST_LOSS, TRUST_FLOOR = 0.5, 0.1, 0.3, 0.02

    def __init__(self):
        super().__init__(
            layer_id="camflow_e24", layer_number=148,
            name="Camera Optical Flow (weighted RANSAC)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.VELOCITY],
            description="Ground velocity from a downward camera; keeps the motion "
                        "the trusted points agree on, so a moving pattern on the "
                        "ground is thrown out.",
        )
        self._prev: Optional[Tuple[np.ndarray, float]] = None
        self._cur: Optional[Tuple[np.ndarray, float]] = None
        self._fov: Optional[float] = None
        self._height: Optional[Tuple[float, float, float]] = None
        self._gyro: Deque[Tuple[float, float, float, float]] = deque()
        self._att = None
        self.trust = np.full((self.GRID, self.GRID), self.TRUST_INIT)
        self._last_T = np.zeros(2)            # last translation, px, to centre the search
        self._last_dt: Optional[float] = None
        self.last: Optional[dict] = None

    # -- contract -----------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.0

    # -- inputs -------------------------------------------------------------

    def feed_frame(self, image: np.ndarray, t: float, fov_deg: float) -> None:
        img = np.asarray(image, float)
        if img.max() > 1.5:
            img = img / 255.0
        self._prev, self._cur, self._fov = self._cur, (img, t), fov_deg

    def feed_height(self, agl_m: float, sigma_m: float, t: float) -> None:
        self._height = (agl_m, sigma_m, t)

    def feed_gyro(self, wx: float, wy: float, wz: float, t: float) -> None:
        self._gyro.append((t, wx, wy, wz))
        while self._gyro and self._gyro[0][0] < t - 2.0:
            self._gyro.popleft()

    def feed_attitude(self, roll: float, pitch: float, heading_deg: float, t: float) -> None:
        self._att = (t, roll, pitch, heading_deg)

    # -- the solve ----------------------------------------------------------

    def _declined(self, code, why, **extra) -> dict:
        self.last = {"status": "declined", "reason_code": code, "reason": why, **extra}
        return self.last

    def _centres(self, size: int) -> np.ndarray:
        margin = self.SEARCH_PX + self.PATCH_PX // 2 + 1
        return np.linspace(margin, size - 1 - margin, self.GRID).round().astype(int)

    def _match(self, prev: np.ndarray, cur: np.ndarray, r0: int, c0: int,
               guess: Tuple[int, int] = (0, 0)):
        """(displacement row, col) of the previous patch in the current frame,
        with its contrast and distinctiveness. The search window is centred
        on `guess` (the shift rotation and the last velocity predict), so the
        search radius only has to cover the change since the last frame."""
        h, R = self.PATCH_PX // 2, self.SEARCH_PX
        patch = prev[r0 - h:r0 + h, c0 - h:c0 + h]
        contrast = float(patch.std())
        gr, gc = guess
        top, left = r0 + gr - h - R, c0 + gc - h - R
        if top < 0 or left < 0 or top + 2 * (h + R) > cur.shape[0] or left + 2 * (h + R) > cur.shape[1]:
            return 0.0, 0.0, 0.0, 0.0            # predicted off the frame: untrackable
        window = cur[top:top + 2 * (h + R), left:left + 2 * (h + R)]
        wins = sliding_window_view(window, (self.PATCH_PX, self.PATCH_PX))
        diff = np.abs(wins - patch)
        if self.SAD_CAP is not None:
            diff = np.minimum(diff, self.SAD_CAP)
        sad = diff.sum(axis=(2, 3))
        i, j = np.unravel_index(np.argmin(sad), sad.shape)
        distinct = float(sad.mean() / max(sad[i, j], 1e-9))
        di, dj = float(i - R + gr), float(j - R + gc)
        # parabolic sub-pixel refinement where the minimum is interior
        if 0 < i < sad.shape[0] - 1:
            a, b, c = sad[i - 1, j], sad[i, j], sad[i + 1, j]
            if a + c - 2 * b > 1e-9:
                di += 0.5 * (a - c) / (a + c - 2 * b)
        if 0 < j < sad.shape[1] - 1:
            a, b, c = sad[i, j - 1], sad[i, j], sad[i, j + 1]
            if a + c - 2 * b > 1e-9:
                dj += 0.5 * (a - c) / (a + c - 2 * b)
        return di, dj, contrast, distinct

    def _rotation_shift(self, rows, cols, size, f, dt) -> Optional[np.ndarray]:
        """Pixel shift each patch would show from the drone's rotation alone."""
        t1 = self._cur[1]
        rates = [g for g in self._gyro if t1 - dt - 0.05 <= g[0] <= t1 + 0.05]
        if not rates:
            return None
        wx, wy, wz = (float(np.mean([g[k] for g in rates])) for k in (1, 2, 3))
        cy = cx = (size - 1) / 2.0
        x_fwd = -(rows - cy)                 # body-frame offsets in pixels
        y_right = cols - cx
        dpsi = wz * dt                       # yaw: ground rotates the other way
        x2 = x_fwd * math.cos(dpsi) + y_right * math.sin(dpsi)
        y2 = -x_fwd * math.sin(dpsi) + y_right * math.cos(dpsi)
        d_row = -(x2 - x_fwd) - f * wy * dt  # pitch nose-up: camera looks back
        d_col = (y2 - y_right) - f * wx * dt # roll right: camera looks right
        return np.stack([d_row, d_col], axis=1)

    def solve(self) -> dict:
        if self._prev is None or self._cur is None:
            return self._declined(NoFixReason.NO_INPUT, "needs two camera frames")
        (prev, t0), (cur, t1) = self._prev, self._cur
        dt = t1 - t0
        if dt <= 0 or dt > self.MAX_DT_S:
            return self._declined(NoFixReason.STALE_INPUT,
                                  f"frames {dt:.2f} s apart (limit {self.MAX_DT_S} s)")
        if prev.shape != cur.shape or prev.shape[0] != prev.shape[1]:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT, "frames must be equal and square")
        if self._height is None or t1 - self._height[2] > self.HEIGHT_STALE_S:
            return self._declined(NoFixReason.NO_INPUT, "no height above ground within 1 s")
        size = cur.shape[0]
        f = (size / 2.0) / math.tan(math.radians(self._fov) / 2.0)
        cs = self._centres(size)
        rows, cols = np.meshgrid(cs, cs, indexing="ij")
        rows, cols = rows.ravel(), cols.ravel()
        rot = self._rotation_shift(rows, cols, size, f, dt)
        if rot is None:
            return self._declined(NoFixReason.NO_INPUT, "no gyro rates covering the frame interval")
        d = np.zeros((len(rows), 2))
        contrast = np.zeros(len(rows))
        distinct = np.zeros(len(rows))
        guess = rot + self._last_T * (dt / self._last_dt if self._last_dt else 0.0)
        for k, (r0, c0) in enumerate(zip(rows, cols)):
            g = (int(round(guess[k, 0])), int(round(guess[k, 1])))
            d[k, 0], d[k, 1], contrast[k], distinct[k] = self._match(prev, cur, r0, c0, g)
        valid = (contrast >= self.MIN_CONTRAST) & (distinct >= self.MIN_DISTINCT)
        if valid.sum() < 4:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT,
                                  f"too little texture: {int(valid.sum())} of {len(rows)} "
                                  f"patches trackable")
        d = d - rot
        w = self.trust.ravel()
        # weighted RANSAC: the displacement the most trust agrees with
        best_score, best, best_tol, best_i = -1.0, None, 0.0, 0
        total = float(w[valid].sum())
        if not self.USE_RANSAC:                  # naive: everything counts equally
            best, best_score, best_tol, best_i = valid, total, 1e9, int(np.flatnonzero(valid)[0])
            w = np.ones_like(w)
        for i in (np.flatnonzero(valid) if self.USE_RANSAC else ()):
            tol = self.INLIER_TOL_PX + 0.05 * np.linalg.norm(d[i])
            inl = valid & (np.linalg.norm(d - d[i], axis=1) < tol)
            score = float(w[inl].sum())
            if score > best_score:
                best_score, best, best_tol, best_i = score, inl, tol, i
        agreeing = best_score / total if total > 0 else 0.0
        # trust: earned slowly by agreeing, lost quickly by clearly disagreeing
        tr = self.trust.ravel()
        tr[best] += self.TRUST_GAIN * (1 - tr[best])
        clear = valid & (np.linalg.norm(d - d[best_i], axis=1) >= self.CLEAR_OUTLIER_X * best_tol)
        tr[clear] = np.maximum(tr[clear] * self.TRUST_LOSS, self.TRUST_FLOOR)
        self.trust = tr.reshape(self.GRID, self.GRID)
        if agreeing < self.MIN_AGREEING_TRUST:
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"only {agreeing:.0%} of the trust agrees on one motion: "
                                  f"cannot tell the drone moving from the floor moving",
                                  agreeing=agreeing, n_inliers=int(best.sum()))
        wi = w[best]
        T = (d[best] * wi[:, None]).sum(axis=0) / wi.sum()
        self._last_T, self._last_dt = T.copy(), dt
        spread = np.sqrt(((d[best] - T) ** 2 * wi[:, None]).sum(axis=0) / wi.sum())
        sigma_px = float(np.hypot(spread.max() / math.sqrt(best.sum()), 0.25))
        agl, sigma_agl, _ = self._height
        gsd = agl / f
        forward = float(T[0] * gsd / dt)     # ground slides backward when the drone goes forward
        right = float(-T[1] * gsd / dt)
        speed = math.hypot(forward, right)
        sigma = math.hypot(sigma_px * gsd / dt, speed * sigma_agl / max(agl, 1e-6))
        # When fewer trusted points agree, part of a moving pattern may be
        # inside the winning cluster: widen. Measured in the console
        # simulation under a partial attack, the error still exceeds this
        # (about 0.9 m/s rms against 0.3 stated); see docs/CAMERA_FLOW.md.
        sigma *= max(1.0, self.FULL_AGREEMENT / agreeing)
        self.last = {"status": "ok", "t": t1, "forward_ms": forward, "right_ms": right,
                     "sigma_ms": sigma, "agreeing_trust": agreeing,
                     "n_inliers": int(best.sum()), "n_valid": int(valid.sum()),
                     "n_points": int(len(rows)), "dt": dt, "gsd_m": gsd,
                     "plain_mean_forward_ms": float(d[valid, 0].mean() * gsd / dt),
                     "plain_mean_right_ms": float(-d[valid, 1].mean() * gsd / dt)}
        return self.last

    def read(self) -> LayerReading:
        v = self.solve()
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        heading = None
        if self._att is not None:
            y = math.radians(self._att[3])
            vn = v["forward_ms"] * math.cos(y) - v["right_ms"] * math.sin(y)
            ve = v["forward_ms"] * math.sin(y) + v["right_ms"] * math.cos(y)
            heading = math.degrees(math.atan2(ve, vn)) % 360.0
        return LayerReading(layer_id=self.layer_id, position=None,
                            velocity=math.hypot(v["forward_ms"], v["right_ms"]),
                            heading=heading, self_confidence=1.0 / (1.0 + v["sigma_ms"]),
                            raw_data={"fabricated": False, "independent": True, **v})
