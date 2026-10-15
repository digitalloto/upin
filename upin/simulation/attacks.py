"""
Attacks painted into the simulator's ground image. SIMULATION ONLY.

  laser_dots   a grid of bright dots sweeping across the ground at a chosen
               speed -- the attack from the reel: a flow sensor that averages
               everything it sees follows the dots.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np

from upin.simulation.environment import ground_texture
from upin.simulation.markers import SimTag, paint_tags, patch_mapping


def laser_dots(image: np.ndarray, north: np.ndarray, east: np.ndarray, t: float,
               speed_ne: Tuple[float, float] = (0.0, 3.0), spacing_m: float = 2.0,
               dot_m: float = 0.5, brightness: float = 1.0) -> np.ndarray:
    """Bright dots on a grid that moves across the ground at speed_ne."""
    n0 = north - speed_ne[0] * t
    e0 = east - speed_ne[1] * t
    dn = (n0 % spacing_m) - spacing_m / 2.0
    de = (e0 % spacing_m) - spacing_m / 2.0
    out = np.array(image, float, copy=True)
    out[dn * dn + de * de < (dot_m / 2.0) ** 2] = brightness
    return out


def camera_frame(center_east_m: float, center_north_m: float, heading_deg: float,
                 agl_m: float, fov_deg: float, size_px: int, t: float,
                 tags: Sequence[SimTag] = (), dots: Optional[dict] = None,
                 seed: int = 911, pixel_noise: float = 0.0, rng=None,
                 roll: float = 0.0, pitch: float = 0.0) -> Tuple[np.ndarray, float]:
    """One downward-camera frame: texture, optional tags, optional dots.
    roll and pitch (radians) lean the camera with the airframe."""
    north, east, gsd = patch_mapping(center_east_m, center_north_m, heading_deg,
                                     agl_m, fov_deg, size_px, roll, pitch)
    img = ground_texture(np.nan_to_num(east), np.nan_to_num(north), seed)
    img = np.where(np.isnan(north), 0.0, img)
    if tags:
        img = paint_tags(img, np.nan_to_num(north), np.nan_to_num(east), tags)
    if dots:
        img = laser_dots(img, np.nan_to_num(north), np.nan_to_num(east), t, **dots)
    if pixel_noise > 0:
        img = img + (rng or np.random.default_rng(0)).normal(0.0, pixel_noise, img.shape)
    return img, gsd
