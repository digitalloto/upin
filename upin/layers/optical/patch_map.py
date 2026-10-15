"""
Layer 154 -- self-surveyed patch-map matching (patchmap_e26).

The map-matching rung of the concept documents, made honest: the map is
ground imagery the drone surveyed ITSELF on a flight with trusted GNSS (or
the trusted leg of this one), stored as north-up metre-scaled patches
stamped with the fix each was taken on. When GNSS is gone over the same
ground, the live frame is matched against those patches for an ABSOLUTE
fix that resets the drift. An Indian-source orthophoto can be imported
into the same patch format later; a foreign source is refused.

THE RULE: a patch is never stored from an untrusted or loose fix (the
breadcrumb rule). The map carries the stamp sigma of every patch, and
every fix it gives carries that sigma.

WHERE IT REFUSES, AND SAYS SO
  no map; no height above ground; no attitude; a frame too dark; no texture
  (water, sand); the ground under the drone outside the frame (lean); no
  patch within the prior's radius; a correlation peak below MIN_PEAK; a
  second peak nearly as high (repetitive ground); stale inputs.

Day only; needs texture and a known height; seasons, shadows and crops
change the ground; the map covers only the flown corridor. Stated.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import (DataInput, Hardware, ReferenceData,
                                           SensorRequirement)
from upin.vision.patch_map import DEG_M, PatchMap, build_mosaic, match, rectify


class PatchMapLayer(NavigationLayer):
    """An absolute fix from the ground the drone has seen before."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("downward camera", why="sees the ground",
                     typical_part="Pi global-shutter camera on the companion computer"),
            Hardware("downward rangefinder", why="scales the frame to metres",
                     typical_part="lidar rangefinder on the flight controller"),
        ],
        inputs=[
            DataInput("camera frames", feed_method="feed_frame",
                      units="greyscale image, field of view in degrees"),
            DataInput("attitude", feed_method="feed_attitude", units="radians, degrees true",
                      why="rectifies the frame to north-up ground"),
            DataInput("height above ground", feed_method="feed_height", units="m, 1-sigma m"),
            DataInput("own prior position", feed_method="set_prior",
                      units="degrees, 1-sigma m", why="chooses which patches to search"),
        ],
        reference_data=[
            ReferenceData("patch map", why="ground the drone surveyed on a trusted flight, "
                          "or an Indian-source orthophoto imported into the same format",
                          source="the drone's own survey (field_survey) or an allowed Indian source"),
        ],
        preconditions=("daylight and textured ground", "a map patch within the prior's radius",
                       "a correlation peak above MIN_PEAK with no rival"),
        notes="Never stores a patch from an untrusted or loose fix. Every fix carries the "
              "stamp sigma of the patches it matched.",
    )

    MIN_PEAK = 0.7
    """**Assumption.** Normalised cross-correlation below this is not a match.
    Unrelated simulated ground peaked at 0.60 over a 48 m search, genuine
    matches at 0.9; set from real flights over real ground."""
    AMBIGUITY_RATIO = 0.9
    """**Assumption.** A second peak above this fraction of the best means the
    ground repeats (rows of crops, a tiled roof): declined."""
    MIN_TEXTURE_STD = 0.03
    """**Assumption.** Brightness spread below this (water, uniform sand) is no
    texture to match."""
    MIN_BRIGHTNESS = 0.05
    MAX_STAMP_SIGMA_M = 5.0
    """**Assumption.** A patch stamped with a looser fix is not worth keeping."""
    MAX_SEARCH_M = 100.0
    MIN_VALID_FRACTION = 0.9
    FRAME_STALE_S, ATT_STALE_S, HEIGHT_STALE_S = 1.0, 0.5, 1.0

    def __init__(self, spacing_m: float = 15.0):
        super().__init__(
            layer_id="patchmap_e26", layer_number=154,
            name="Self-Surveyed Patch Map Matching",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION],
            description="An absolute fix from matching the downward frame against "
                        "north-up ground patches the drone itself stored on a trusted "
                        "flight; resets the drift of every velocity source.",
        )
        self.spacing_m = spacing_m
        self.map: Optional[PatchMap] = None
        self._frame: Optional[Tuple[np.ndarray, float, float]] = None
        self._att: Optional[Tuple[float, float, float, float]] = None
        self._height: Optional[Tuple[float, float, float]] = None
        self._prior: Optional[Tuple[float, float, float]] = None
        self.last: Optional[dict] = None
        self.last_learn: Optional[dict] = None
        self.learned = 0

    # -- contract ---------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7

    # -- inputs -----------------------------------------------------------

    def set_map(self, pmap: PatchMap) -> None:
        self.map = pmap

    def feed_attitude(self, roll: float, pitch: float, heading_deg: float, t: float) -> None:
        self._att = (t, roll, pitch, heading_deg)

    def feed_height(self, agl_m: float, sigma_m: float, t: float) -> None:
        self._height = (agl_m, sigma_m, t)

    def feed_frame(self, image: np.ndarray, t: float, fov_deg: float) -> None:
        img = np.asarray(image, float)
        if img.max() > 1.5:
            img = img / 255.0
        self._frame = (img, t, fov_deg)

    def set_prior(self, lat: float, lon: float, sigma_m: float) -> None:
        self._prior = (lat, lon, sigma_m)

    # -- shared -----------------------------------------------------------

    def _declined(self, code, why, **extra) -> dict:
        self.last = {"status": "declined", "reason_code": code, "reason": why, **extra}
        return self.last

    def _rectified(self, t: float):
        """(patch, valid, offset, reason): the live frame as north-up ground
        around the boresight point, or why not."""
        if self._frame is None:
            return None, None, None, (NoFixReason.NO_INPUT, "no camera frame")
        img, ft, fov = self._frame
        if t - ft > self.FRAME_STALE_S:
            return None, None, None, (NoFixReason.STALE_INPUT, f"frame {t - ft:.1f} s old")
        if self._att is None or abs(ft - self._att[0]) > self.ATT_STALE_S:
            return None, None, None, (NoFixReason.NO_INPUT, "no attitude within 0.5 s of the frame")
        if self._height is None or ft - self._height[2] > self.HEIGHT_STALE_S:
            return None, None, None, (NoFixReason.NO_INPUT, "no height above ground within 1 s")
        if float(img.mean()) < self.MIN_BRIGHTNESS:
            return None, None, None, (NoFixReason.INSUFFICIENT_INPUT,
                                      f"frame too dark (mean {img.mean():.3f}): no light")
        _, roll, pitch, heading = self._att
        gsd = self.map.gsd_m if self.map is not None else None
        patch_m = self.map.patch_m if self.map is not None else None
        kw = {} if gsd is None else {"patch_m": patch_m, "gsd_m": gsd}
        patch, valid, off = rectify(img, fov, roll, pitch, heading, self._height[0], **kw)
        if not math.isfinite(off[0]) or valid.mean() < self.MIN_VALID_FRACTION:
            return None, None, None, (NoFixReason.INSUFFICIENT_INPUT,
                                      f"only {valid.mean():.0%} of the patch is in the frame "
                                      f"(lean {math.degrees(math.hypot(roll, pitch)):.0f} deg)")
        std = float(patch[valid].std())
        if std < self.MIN_TEXTURE_STD:
            return None, None, None, (NoFixReason.INSUFFICIENT_INPUT,
                                      f"no texture to match (brightness spread {std:.3f}): water, "
                                      f"uniform ground or haze")
        return patch, valid, off, None

    # -- building ---------------------------------------------------------

    def learn(self, lat: float, lon: float, alt_m: float, sigma_m: float, trusted: bool,
              t: float) -> dict:
        """Store the current frame as a patch at the fix (lat, lon) if the
        fix is trusted and tight, the ground is textured, and the spot is
        new. Returns what happened and why."""
        def no(why):
            self.last_learn = {"stored": False, "reason": why, "t": t}
            return self.last_learn
        if not trusted:
            return no("fix not trusted: a patch stamped with a guess would poison every later fix")
        if not (sigma_m <= self.MAX_STAMP_SIGMA_M):
            return no(f"fix looser than {self.MAX_STAMP_SIGMA_M:.0f} m (±{sigma_m:.1f} m): not stored")
        if self.map is None:
            self.map = PatchMap("field_survey")
        near = self.map.nearest_m(lat, lon)
        if near is not None and near < self.spacing_m:
            return no(f"a patch {near:.0f} m away already covers this spot")
        patch, valid, off, why = self._rectified(t)
        if why is not None:
            return no(why[1])
        # the patch is centred where the camera looked: stamp that point
        slat = lat + off[0] / DEG_M
        slon = lon + off[1] / (DEG_M * math.cos(math.radians(lat)))
        i = self.map.add(patch, valid, slat, slon, alt_m, sigma_m, t)
        self.learned += 1
        self.last_learn = {"stored": True, "index": i, "t": t, "sigma_m": sigma_m, "lat": slat,
                           "lon": slon, "boresight_offset_m": [off[0], off[1]]}
        return self.last_learn

    # -- matching ---------------------------------------------------------

    def solve(self, t: float) -> dict:
        if self.map is None or len(self.map) == 0:
            return self._declined(NoFixReason.NO_INPUT, "no patch map")
        patch, valid, off, why = self._rectified(t)
        if why is not None:
            return self._declined(*why)
        if self._prior is None:
            return self._declined(NoFixReason.NO_ANCHOR, "no prior position to search around")
        # search around where the camera looks, not where the drone is
        plat0, plon0, psig = self._prior
        plat = plat0 + off[0] / DEG_M
        plon = plon0 + off[1] / (DEG_M * math.cos(math.radians(plat0)))
        radius = min(3.0 * psig + self.map.patch_m, self.MAX_SEARCH_M)
        idx = self.map.candidates(plat, plon, radius)
        if not idx:
            near = self.map.nearest_m(plat, plon)
            return self._declined(NoFixReason.NO_INPUT,
                                  f"no map patch within {radius:.0f} m of the prior (nearest "
                                  f"{near:.0f} m away): off the surveyed corridor")
        half = radius + self.map.patch_m / 2.0
        mosaic, cover, n = build_mosaic(self.map, idx, plat, plon, half)
        m = match(patch, valid, mosaic, cover, self.map.gsd_m)
        if m["status"] != "ok":
            return self._declined(NoFixReason.INSUFFICIENT_INPUT, m["reason"], candidates=len(idx))
        if m["peak"] < self.MIN_PEAK:
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"best correlation {m['peak']:.2f} below {self.MIN_PEAK}: the ground "
                                  f"does not match the map here (changed, or not surveyed)",
                                  peak=m["peak"], candidates=len(idx))
        if m["second"] > self.AMBIGUITY_RATIO * m["peak"]:
            return self._declined(NoFixReason.POOR_GEOMETRY,
                                  f"ambiguous: a second peak at {m['second']:.2f} rivals the best "
                                  f"{m['peak']:.2f}; the ground repeats", peak=m["peak"],
                                  second=m["second"], candidates=len(idx))
        g = self.map.gsd_m
        c = (n - 1) / 2.0
        dn = (c - m["row"]) * g
        de = (m["col"] - c) * g
        lat = plat + dn / DEG_M                      # the matched boresight point
        lon = plon + de / (DEG_M * math.cos(math.radians(plat)))
        # which patches the matched window actually sat on, for their stamps
        offs = self.map.offsets_m(lat, lon)
        used = [i for i in idx if np.hypot(*offs[i]) <= self.map.patch_m]
        stamp = max(self.map.sigma_m[i] for i in used) if used else max(self.map.sigma_m[i] for i in idx)
        agl, agl_sig, _ = self._height
        scale_err = (math.hypot(dn, de) + self.map.patch_m / 2.0) * agl_sig / max(agl, 1.0)
        sigma = math.sqrt((m["sigma_px"] * g) ** 2 + stamp ** 2 + scale_err ** 2)
        # back from the boresight point to the point below the drone
        fix_lat = lat - off[0] / DEG_M
        fix_lon = lon - off[1] / (DEG_M * math.cos(math.radians(lat)))
        self.last = {
            "status": "ok", "t": t, "lat": fix_lat, "lon": fix_lon, "sigma_m": sigma,
            "boresight_offset_m": [off[0], off[1]],
            "peak": m["peak"], "second": m["second"], "sigma_match_m": m["sigma_px"] * g,
            "stamp_sigma_m": stamp, "scale_sigma_m": scale_err, "candidates": len(idx),
            "patches_used": used, "offset_from_prior_m": math.hypot(dn, de),
            "map_patches": len(self.map),
        }
        return self.last

    def read(self) -> LayerReading:
        t = self._frame[1] if self._frame is not None else 0.0
        v = self.solve(t)
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=v["lat"], longitude=v["lon"], altitude=None,
                              accuracy_m=v["sigma_m"] * math.sqrt(2)),
            self_confidence=float(v["peak"]),
            raw_data={"fabricated": False, "independent": True, **v},
        )
