"""
Tags painted into the simulator's ground, for testing the tag layer.

Reproduces ground_patch's pixel-to-ground mapping (upin/simulation/
environment.py) so a UPIN tag placed at a world position appears in the
downward camera's frame exactly where the geometry says, with the right size
and rotation. Then the detector and pose maths can be checked against known
truth. SIMULATION ONLY.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from upin.simulation.environment import ground_texture
from upin.vision.upin_tag import GRID, _rot_body_to_ned, cell_colours


@dataclass(frozen=True)
class SimTag:
    tag_id: int
    north_m: float
    east_m: float
    size_m: float
    yaw_deg: float = 0.0          # direction of the tag's +u (column) axis


def patch_mapping(center_east_m: float, center_north_m: float, heading_deg: float,
                  agl_m: float, fov_deg: float, size_px: int,
                  roll: float = 0.0, pitch: float = 0.0
                  ) -> Tuple[np.ndarray, np.ndarray, float]:
    """(north, east, gsd) per pixel. Level: the same mapping as ground_patch.
    With a lean (roll, pitch in radians) the camera looks along the body
    axis: each pixel's ray is rotated by the attitude and intersected with
    the flat ground, the exact inverse of upin_tag.pose()'s geometry, so a
    leaning drone sees ground ahead of or beside its nadir point."""
    gsd = 2.0 * agl_m * math.tan(math.radians(fov_deg) / 2.0) / size_px
    psi = math.radians(heading_deg)
    if roll == 0.0 and pitch == 0.0:
        idx = (np.arange(size_px) - (size_px - 1) / 2.0) * gsd
        forward = idx[::-1][:, None]
        right = idx[None, :]
        north = center_north_m + forward * math.cos(psi) - right * math.sin(psi)
        east = center_east_m + forward * math.sin(psi) + right * math.cos(psi)
        return north, east, gsd
    f = (size_px / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    c = (size_px - 1) / 2.0
    rows, cols = np.meshgrid(np.arange(size_px), np.arange(size_px), indexing="ij")
    rays = np.stack([-(rows - c) / f, (cols - c) / f, np.ones_like(rows, dtype=float)], axis=-1)
    R = _rot_body_to_ned(roll, pitch, psi)
    d = rays @ R.T
    dz = np.where(d[..., 2] > 1e-3, d[..., 2], np.nan)      # rays above the horizon hit nothing
    north = center_north_m + agl_m * d[..., 0] / dz
    east = center_east_m + agl_m * d[..., 1] / dz
    return north, east, gsd


def paint_tags(image: np.ndarray, north: np.ndarray, east: np.ndarray,
               tags: Sequence[SimTag]) -> np.ndarray:
    out = np.array(image, float, copy=True)
    for tag in tags:
        yaw = math.radians(tag.yaw_deg)
        dn, de = north - tag.north_m, east - tag.east_m
        u = dn * math.cos(yaw) + de * math.sin(yaw)
        v = -dn * math.sin(yaw) + de * math.cos(yaw)
        cu = np.floor((u / tag.size_m + 0.5) * GRID).astype(int)
        cv = np.floor((v / tag.size_m + 0.5) * GRID).astype(int)
        inside = (cu >= 0) & (cu < GRID) & (cv >= 0) & (cv < GRID)
        cells = cell_colours(tag.tag_id)
        out[inside] = cells[cv[inside], cu[inside]]
    return out


def ground_patch_with_tags(center_east_m: float, center_north_m: float,
                           heading_deg: float, agl_m: float, fov_deg: float,
                           size_px: int, tags: Sequence[SimTag], seed: int = 911,
                           pixel_noise: float = 0.0, rng=None, roll: float = 0.0,
                           pitch: float = 0.0) -> Tuple[np.ndarray, float]:
    north, east, gsd = patch_mapping(center_east_m, center_north_m, heading_deg,
                                     agl_m, fov_deg, size_px, roll, pitch)
    img = paint_tags(ground_texture(east, north, seed), north, east, tags)
    if pixel_noise > 0:
        img = img + (rng or np.random.default_rng(0)).normal(0.0, pixel_noise, img.shape)
    return img, gsd
