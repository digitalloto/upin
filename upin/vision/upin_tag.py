"""
The UPIN tag: a printed marker that gives a drone its position.

DESIGN (our own; not a tag library)

An 8 x 8 grid of cells. The outer ring is black, the next ring white, and
the inner 4 x 4 carries the code: 8 id bits followed by 8 check bits
(the id XOR 0x5C). That gives a dark square with a bright hole, which is what
the detector looks for, and a code that a plain patch of ground never
produces by accident. Ids whose code could be mistaken for another id when
the tag is seen rotated are excluded at import (VALID_IDS), so a tag reads
the same from any direction and the reading also says which way it faces.

  B B B B B B B B      B = black, W = white, c = code cell (black = 1)
  B W W W W W W B
  B W c c c c W B
  B W c c c c W B
  B W c c c c W B
  B W c c c c W B
  B W W W W W W B
  B B B B B B B B

DETECTION (numpy + scipy.ndimage)

  threshold against the local mean -> dark components -> keep the ones that
  are big enough and have a bright hole -> four corners as the farthest
  pixels from the centroid in four angular sectors -> homography from the
  four corners to the tag square -> sample the border, the ring and the
  code -> decode with the rotation check

POSE

A pinhole camera looking down. Each corner pixel is a ray; the rays meet
flat ground at a height that makes the tag's ground footprint the size the
tag really is. That gives the camera's height and the tag's offset on the
ground from the point straight below the camera. The drone is at the tag's
surveyed position minus that offset.

Limits: written for a downward camera at modest tilt; corners are found to
about a pixel, so the error grows with height and shrinks with resolution.
Every accuracy figure is computed from the geometry, never assumed.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy import ndimage

GRID = 8
CODE = 4
CODE_OFFSET = 2
CHECK_MASK = 0x5C
"""Not a palindrome on purpose: a tag read upside down then never passes
the check (a palindromic mask would make every 180-degree reading valid)."""
CORNER_SIGMA_PX = 0.7
"""**Assumption.** Corner localisation error, 1-sigma, for integer-pixel
corner picking. Measure on the real camera by holding the drone still."""


# -- the code -------------------------------------------------------------

def pattern_bits(tag_id: int) -> int:
    return ((tag_id & 0xFF) << 8) | ((tag_id ^ CHECK_MASK) & 0xFF)


def _grid_from_bits(bits: int) -> np.ndarray:
    return np.array([[(bits >> (15 - (r * CODE + c))) & 1 for c in range(CODE)]
                     for r in range(CODE)], dtype=bool)


def _bits_from_grid(grid: np.ndarray) -> int:
    bits = 0
    for r in range(CODE):
        for c in range(CODE):
            bits = (bits << 1) | int(grid[r, c])
    return bits


def _decode_bits(bits: int) -> Optional[int]:
    tag_id, chk = bits >> 8, bits & 0xFF
    return tag_id if chk == ((tag_id ^ CHECK_MASK) & 0xFF) else None


def _valid_ids() -> frozenset:
    """Ids that decode to themselves and to nothing valid when rotated."""
    ok = []
    for tag_id in range(256):
        g = _grid_from_bits(pattern_bits(tag_id))
        if any(_decode_bits(_bits_from_grid(np.rot90(g, k))) is not None
               for k in (1, 2, 3)):
            continue
        ok.append(tag_id)
    return frozenset(ok)


VALID_IDS = _valid_ids()


def decode_grid(grid: np.ndarray) -> Optional[Tuple[int, int]]:
    """(tag_id, rotation) for a 4x4 boolean grid (True = black), or None."""
    for k in range(4):
        tag_id = _decode_bits(_bits_from_grid(np.rot90(grid, k)))
        if tag_id is not None and tag_id in VALID_IDS:
            return tag_id, k
    return None


# -- rendering ------------------------------------------------------------

def cell_colours(tag_id: int) -> np.ndarray:
    """8x8 array, 0.0 = black, 1.0 = white."""
    if tag_id not in VALID_IDS:
        raise ValueError(f"tag id {tag_id} is not a valid UPIN tag id "
                         f"({len(VALID_IDS)} valid ids; see VALID_IDS)")
    cells = np.ones((GRID, GRID))
    cells[0, :] = cells[-1, :] = cells[:, 0] = cells[:, -1] = 0.0
    code = _grid_from_bits(pattern_bits(tag_id))
    cells[CODE_OFFSET:CODE_OFFSET + CODE, CODE_OFFSET:CODE_OFFSET + CODE] = \
        np.where(code, 0.0, 1.0)
    return cells


def render(tag_id: int, cell_px: int = 40, quiet_cells: int = 1) -> np.ndarray:
    """A printable image (0..1) with a white quiet zone around the tag."""
    cells = cell_colours(tag_id)
    n = GRID + 2 * quiet_cells
    big = np.ones((n, n))
    big[quiet_cells:quiet_cells + GRID, quiet_cells:quiet_cells + GRID] = cells
    return np.kron(big, np.ones((cell_px, cell_px)))


def save_png(image: np.ndarray, path: str) -> None:
    """8-bit greyscale PNG, written with zlib only."""
    img = (np.clip(image, 0, 1) * 255).astype(np.uint8)
    h, w = img.shape
    raw = b"".join(b"\x00" + img[r].tobytes() for r in range(h))

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


# -- detection ------------------------------------------------------------

@dataclass
class TagDetection:
    tag_id: int
    corners_px: np.ndarray        # (4, 2) as (col, row), in tag order: the
                                  # corner nearest tag cell (0,0) first, then
                                  # clockwise in the tag's own frame
    centre_px: Tuple[float, float]
    size_px: float                # mean side length
    rotation: int                 # quarter turns from the tag's own frame


def _homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """3x3 H with dst ~ H src, from four point pairs (direct linear solve)."""
    A, b = [], []
    for (u, v), (x, y) in zip(src, dst):
        A.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        b.append(x)
        A.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        b.append(y)
    h = np.linalg.solve(np.array(A, float), np.array(b, float))
    return np.append(h, 1.0).reshape(3, 3)


def _apply(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    return p[:, :2] / p[:, 2:3]


def _corners(rows: np.ndarray, cols: np.ndarray) -> Optional[np.ndarray]:
    """Four corners of a roughly square blob: the farthest pixel from the
    centroid, then the farthest within +-35 degrees of each quarter turn."""
    cy, cx = rows.mean(), cols.mean()
    dy, dx = rows - cy, cols - cx
    d = np.hypot(dx, dy)
    ang = np.arctan2(dy, dx)
    first = ang[np.argmax(d)]
    out = []
    for k in range(4):
        target = first + k * math.pi / 2
        diff = np.abs((ang - target + math.pi) % (2 * math.pi) - math.pi)
        sel = diff < math.radians(35)
        if not sel.any():
            return None
        i = np.flatnonzero(sel)[np.argmax(d[sel])]
        out.append((cols[i], rows[i]))
    return np.array(out, float)


def _sample(dark: np.ndarray, H: np.ndarray, uv: np.ndarray) -> np.ndarray:
    xy = _apply(H, uv)
    c = np.clip(np.rint(xy[:, 0]).astype(int), 0, dark.shape[1] - 1)
    r = np.clip(np.rint(xy[:, 1]).astype(int), 0, dark.shape[0] - 1)
    return dark[r, c]


def detect(image: np.ndarray, min_size_px: float = 24.0,
           contrast: float = 0.15) -> List[TagDetection]:
    """All UPIN tags in a greyscale image (any range)."""
    img = np.asarray(image, float)
    if img.max() > 1.5:
        img = img / 255.0
    win = max(9, int(min(img.shape) / 6) | 1)
    local = ndimage.uniform_filter(img, win, mode="reflect")
    dark = img < np.minimum(local - contrast, 0.5)
    labels, n = ndimage.label(dark, structure=np.ones((3, 3)))
    if n == 0:
        return []
    out: List[TagDetection] = []
    objects = ndimage.find_objects(labels)
    for idx, sl in enumerate(objects, start=1):
        if sl is None:
            continue
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if min(h, w) < min_size_px or max(h, w) > 3 * min(h, w):
            continue
        comp = labels[sl] == idx
        filled = ndimage.binary_fill_holes(comp)
        hole = filled.sum() - comp.sum()
        if hole < 0.25 * filled.sum():
            continue                        # no bright hole: not a tag border
        rows, cols = np.nonzero(comp)
        corners = _corners(rows + sl[0].start, cols + sl[1].start)
        if corners is None:
            continue
        side = np.mean([np.linalg.norm(corners[(k + 1) % 4] - corners[k]) for k in range(4)])
        if side < min_size_px:
            continue
        # image corner pixels sit on the outer edge; the tag square's corners
        # are half a pixel further out, so map tag coords 0..8 to the pixel
        # corners pushed out by half a pixel each way
        centre = corners.mean(axis=0)
        pushed = corners + 0.5 * np.sign(corners - centre)
        H = _homography(np.array([[0, 0], [GRID, 0], [GRID, GRID], [0, GRID]], float),
                        pushed)
        # structural checks: border dark, ring bright
        border = [(i + 0.5, j + 0.5) for i in range(GRID) for j in range(GRID)
                  if i in (0, GRID - 1) or j in (0, GRID - 1)]
        ring = [(i + 0.5, j + 0.5) for i in range(1, GRID - 1) for j in range(1, GRID - 1)
                if i in (1, GRID - 2) or j in (1, GRID - 2)]
        if _sample(dark, H, np.array(border, float)).mean() < 0.9:
            continue
        if (~_sample(dark, H, np.array(ring, float))).mean() < 0.9:
            continue
        code_uv = np.array([(CODE_OFFSET + c + 0.5, CODE_OFFSET + r + 0.5)
                            for r in range(CODE) for c in range(CODE)], float)
        grid = _sample(dark, H, code_uv).reshape(CODE, CODE)
        decoded = decode_grid(grid)
        if decoded is None:
            continue
        tag_id, rot = decoded
        # corners in the tag's own frame: undo the rotation the decode found
        ordered = np.roll(pushed, -rot, axis=0)
        out.append(TagDetection(tag_id, ordered, (float(centre[0]), float(centre[1])),
                                float(side), rot))
    return out


# -- pose -----------------------------------------------------------------

def _rot_body_to_ned(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch),
                              math.sin(pitch), math.cos(yaw), math.sin(yaw))
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr]])


@dataclass
class TagPose:
    agl_m: float                  # camera height above the tag's ground
    offset_north_m: float         # tag relative to the point below the camera
    offset_east_m: float
    sigma_h_m: float              # per-axis 1-sigma of the offset
    sigma_agl_m: float
    tag_yaw_rel_deg: float        # tag's cell-(0,0) direction relative to north


def pose(det: TagDetection, image_shape: Tuple[int, int], fov_deg: float,
         roll: float, pitch: float, heading_deg: float, tag_size_m: float) -> TagPose:
    """Where the tag is on the ground relative to the camera, and how high
    the camera is, from the detection and the attitude (radians, degrees)."""
    h, w = image_shape[:2]
    f = (w / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    R = _rot_body_to_ned(roll, pitch, math.radians(heading_deg))

    def ground_unit(col, row):
        # row 0 is forward, col 0 is left: body x forward, y right, z down
        ray = np.array([-(row - cy) / f, (col - cx) / f, 1.0])
        d = R @ ray
        return d[:2] / d[2]                 # ground offset per metre of height

    corners = np.array([ground_unit(c, r) for c, r in det.corners_px])
    side_per_m = np.mean([np.linalg.norm(corners[(k + 1) % 4] - corners[k]) for k in range(4)])
    agl = tag_size_m / side_per_m
    centre = corners.mean(axis=0) * agl
    gsd = agl / f
    sigma_px = CORNER_SIGMA_PX
    sigma_agl = agl * sigma_px * math.sqrt(2) / det.size_px
    sigma_h = math.sqrt((sigma_px * gsd) ** 2
                        + (np.linalg.norm(centre) * sigma_px * math.sqrt(2) / det.size_px) ** 2)
    edge = corners[1] - corners[0]          # tag's +u direction on the ground
    yaw_rel = math.degrees(math.atan2(edge[1], edge[0])) % 360.0
    return TagPose(float(agl), float(centre[0]), float(centre[1]), float(sigma_h),
                   float(sigma_agl), float(yaw_rel))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Print a UPIN tag as a PNG")
    ap.add_argument("tag_id", type=int)
    ap.add_argument("path")
    ap.add_argument("--cell-px", type=int, default=60,
                    help="pixels per cell; the tag is 8 cells plus a white margin")
    a = ap.parse_args()
    save_png(render(a.tag_id, a.cell_px), a.path)
    print(f"tag {a.tag_id} written to {a.path}: print it so the 8 black-to-black "
          f"cells measure the size_m you put in the tag map")
