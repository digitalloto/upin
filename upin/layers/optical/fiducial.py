"""
Layer 149 -- tag landmarks (fiducial_e25).

A printed UPIN tag at a surveyed spot. When the downward camera sees it, the
tag's apparent size gives the camera's height, its position in the frame
gives the offset on the ground, and the tag's surveyed coordinates give the
drone's position. One tag is a full fix, with accuracy computed from the
geometry (upin/vision/upin_tag.py).

FIRST USE: GROUND TRUTH

On the test range, tags at surveyed spots tell the real error of every
other layer, with no GNSS involved (tools/tag_truth.py). Then: a landing
pad, "home" without GNSS, indoor tests.

Map sources: the same whitelist as the landmark layer -- Indian sources or
the operator's own survey. A tag's survey accuracy propagates into the fix.

WHERE IT REFUSES (no-fabrication contract)

No map, no frame, no attitude, stale frame, no tag in view, a tag not in
the map, or a tag too small to read -- each returns no fix and says which.

LIMITS: only where tags are placed; range scales with tag size and camera
resolution (a tag must span MIN_TAG_PX pixels); needs light; written for a
downward camera at modest tilt.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

from upin.core.layer_base import (LayerCapability, LayerGroup, LayerReading,
                                  NavigationLayer)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import (DataInput, Hardware, ReferenceData,
                                           SensorRequirement)
from upin.layers.optical.landmark_chain import validate_map_source
from upin.vision.upin_tag import VALID_IDS, TagDetection, detect, pose

DEG_M = 111_320.0


@dataclass
class TagEntry:
    tag_id: int
    latitude: float
    longitude: float
    size_m: float
    source: str
    position_accuracy_m: float          # survey accuracy, 1-sigma
    altitude_m: Optional[float] = None
    name: str = ""

    def __post_init__(self):
        self.source = validate_map_source(self.source)
        if self.tag_id not in VALID_IDS:
            raise ValueError(f"tag id {self.tag_id} is not a valid UPIN tag id")
        if self.size_m <= 0 or self.position_accuracy_m <= 0:
            raise ValueError(f"tag {self.tag_id}: size and survey accuracy must be "
                             f"stated and positive")


class TagMap:
    def __init__(self, entries: Sequence[TagEntry] = ()):
        self.entries: Dict[int, TagEntry] = {}
        for e in entries:
            if e.tag_id in self.entries:
                raise ValueError(f"tag id {e.tag_id} appears twice in the map")
            self.entries[e.tag_id] = e

    @classmethod
    def load_json(cls, path: str) -> "TagMap":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls([TagEntry(**d) for d in data["tags"]])

    def __len__(self):
        return len(self.entries)


class FiducialTagLayer(NavigationLayer):
    """A full position fix from one surveyed printed tag."""

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("downward camera", why="sees the tag",
                     typical_part="Pi global-shutter camera on the companion computer"),
        ],
        inputs=[
            DataInput("camera frames", feed_method="feed_frame",
                      units="greyscale image, field of view in degrees"),
            DataInput("attitude", feed_method="feed_attitude",
                      units="radians, degrees true",
                      why="turns the image offset into north/east"),
        ],
        reference_data=[
            ReferenceData("tag map", why="surveyed positions and sizes of the tags",
                          source="field survey or an allowed Indian map source"),
        ],
        preconditions=("a tag in view spanning at least MIN_TAG_PX pixels",
                       "the tag's id in the map"),
        notes="One tag gives a full fix; accuracy from the geometry and the "
              "survey. Ground truth for the test range before anything else.",
    )

    MIN_TAG_PX = 24.0
    """**Assumption.** Three pixels per cell is the least the sampler reads
    reliably; measure on the real camera."""
    FRAME_STALE_S = 1.0
    ATT_STALE_S = 0.5

    def __init__(self, tag_map: Optional[TagMap] = None):
        super().__init__(
            layer_id="fiducial_e25", layer_number=149,
            name="Tag Landmarks (printed fiducials)",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.ALTITUDE],
            description="A full position fix from a printed UPIN tag at a "
                        "surveyed spot, seen by the downward camera.",
        )
        self.map = tag_map
        self._frame = None
        self._frame_t: Optional[float] = None
        self._fov: Optional[float] = None
        self._att = None
        self.last: Optional[dict] = None

    # -- contract -----------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.9

    # -- inputs -------------------------------------------------------------

    def set_map(self, tag_map: TagMap) -> None:
        self.map = tag_map

    def feed_attitude(self, roll: float, pitch: float, heading_deg: float, t: float) -> None:
        self._att = (t, roll, pitch, heading_deg)

    def feed_frame(self, image: np.ndarray, t: float, fov_deg: float) -> None:
        self._frame, self._frame_t, self._fov = np.asarray(image), t, fov_deg

    # -- the solve ----------------------------------------------------------

    def _declined(self, code: str, why: str, **extra) -> dict:
        self.last = {"status": "declined", "reason_code": code, "reason": why, **extra}
        return self.last

    def solve(self, t: Optional[float] = None) -> dict:
        if self.map is None or len(self.map) == 0:
            return self._declined(NoFixReason.NO_INPUT, "no tag map")
        if self._frame is None:
            return self._declined(NoFixReason.NO_INPUT, "no camera frame")
        now = self._frame_t if t is None else t
        if now - self._frame_t > self.FRAME_STALE_S:
            return self._declined(NoFixReason.STALE_INPUT,
                                  f"frame {now - self._frame_t:.1f} s old")
        if self._att is None or abs(self._frame_t - self._att[0]) > self.ATT_STALE_S:
            return self._declined(NoFixReason.NO_INPUT, "no attitude within 0.5 s of the frame")
        dets: List[TagDetection] = detect(self._frame, min_size_px=self.MIN_TAG_PX)
        if not dets:
            return self._declined(NoFixReason.INSUFFICIENT_INPUT, "no tag in view")
        known = [d for d in dets if d.tag_id in self.map.entries]
        if not known:
            ids = sorted({d.tag_id for d in dets})
            return self._declined(NoFixReason.FAILED_VALIDATION,
                                  f"tag id(s) {ids} seen but not in the map",
                                  seen_ids=ids)
        det = max(known, key=lambda d: d.size_px)       # closest: best precision
        entry = self.map.entries[det.tag_id]
        _, roll, pitch, heading = self._att
        p = pose(det, self._frame.shape, self._fov, roll, pitch, heading, entry.size_m)
        lat = entry.latitude - p.offset_north_m / DEG_M
        lon = entry.longitude - p.offset_east_m / (DEG_M * math.cos(math.radians(entry.latitude)))
        sigma = math.sqrt(p.sigma_h_m ** 2 + entry.position_accuracy_m ** 2)
        self.last = {
            "status": "ok", "t": self._frame_t, "tag_id": det.tag_id, "name": entry.name,
            "lat": lat, "lon": lon,
            "alt_m": None if entry.altitude_m is None else entry.altitude_m + p.agl_m,
            "sigma_m": sigma, "sigma_alt_m": p.sigma_agl_m, "agl_m": p.agl_m,
            "range_m": math.hypot(p.offset_north_m, p.offset_east_m, p.agl_m),
            "tag_px": det.size_px, "tags_in_view": sorted({d.tag_id for d in dets}),
            "tag_yaw_rel_deg": p.tag_yaw_rel_deg,
        }
        return self.last

    def read(self) -> LayerReading:
        v = self.solve()
        if v["status"] != "ok":
            return no_fix(self.layer_id, v["reason_code"], v["reason"],
                          feed_via=self.REQUIRES.feed_methods)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=v["lat"], longitude=v["lon"], altitude=v["alt_m"],
                              accuracy_m=v["sigma_m"] * math.sqrt(2),      # DRMS
                              altitude_accuracy_m=v["sigma_alt_m"]),
            self_confidence=1.0 / (1.0 + v["sigma_m"]),
            raw_data={"fabricated": False, "independent": True, **v},
        )
