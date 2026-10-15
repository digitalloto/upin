"""
Patch map: ground imagery the drone surveyed itself, and the matching that
turns a live downward frame into an absolute position.

THE MAP
  On a flight with trusted GNSS, every `spacing` metres the downward frame
  is rectified to a north-up, metre-scaled square of ground (PATCH_M across
  at GSD_M per pixel) centred on the point below the drone, and stored with
  the fix it was stamped with and that fix's sigma. The map is the flown
  corridor, nothing more: it is only as good as the fixes it was built
  with, and it says so through the stamp sigmas it carries.

THE MATCH
  A live frame is rectified the same way. The map patches near the drone's
  own estimate are painted into one local mosaic, and the centre of the
  live patch is slid over it with normalised cross-correlation (invariant
  to brightness and contrast, not to the ground changing). The best peak
  gives the position; its height says how sure, its sharpness how precise,
  and the second-best peak whether the ground repeats.

Our own numpy code, like the camera flow. The rectification is the exact
inverse of the tag layer's ray geometry (upin/vision/upin_tag.py), so a
leaning drone's frame lands on the right ground.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.ndimage import map_coordinates

from upin.layers.optical.landmark_chain import validate_map_source
from upin.vision.upin_tag import _rot_body_to_ned

DEG_M = 111_320.0
PATCH_M = 24.0
"""**Assumption.** Patch width in metres: fits inside a 40-degree camera at
50 m with room for the lean. Wider patches match more surely and cost
more memory."""
GSD_M = 0.5
"""**Assumption.** Ground sampling distance of the stored patches, metres
per pixel: 48 x 48 pixels per patch, 9 KB as float32."""
MAP_FORMAT = 1


def boresight_offset(roll: float, pitch: float, heading_deg: float, agl_m: float
                     ) -> Tuple[float, float]:
    """(north, east) metres from the point below the camera to the ground
    point its optical axis hits: where a leaning drone actually looks."""
    R = _rot_body_to_ned(roll, pitch, math.radians(heading_deg))
    d = R @ np.array([0.0, 0.0, 1.0])
    if d[2] <= 1e-3:
        return float("nan"), float("nan")
    return float(agl_m * d[0] / d[2]), float(agl_m * d[1] / d[2])


def rectify(image: np.ndarray, fov_deg: float, roll: float, pitch: float, heading_deg: float,
            agl_m: float, patch_m: float = PATCH_M, gsd_m: float = GSD_M
            ) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float]]:
    """North-up ground patch centred on the ground point the camera LOOKS AT
    (the boresight, offset from the nadir by the lean), sampled from the
    frame through the attitude; (patch, valid, offset) where valid marks
    pixels the frame covers and offset is the boresight's (north, east)
    from the point below the camera. A stamp or a fix referred to the
    patch centre is corrected by that offset."""
    img = np.asarray(image, float)
    h, w = img.shape[:2]
    f = (w / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    n = int(round(patch_m / gsd_m))
    on, oe = boresight_offset(roll, pitch, heading_deg, agl_m)
    if not math.isfinite(on):
        on = oe = 0.0
    idx = (np.arange(n) - (n - 1) / 2.0) * gsd_m
    dn = idx[::-1][:, None] * np.ones((1, n)) + on     # row 0 = north edge
    de = np.ones((n, 1)) * idx[None, :] + oe           # col 0 = west edge
    v = np.stack([dn, de, np.full_like(dn, agl_m)], axis=-1)
    R = _rot_body_to_ned(roll, pitch, math.radians(heading_deg))
    b = v @ R                                           # R^T applied to each vector
    bz = b[..., 2]
    ok = bz > 1e-3
    bz_safe = np.where(ok, bz, 1.0)
    rows = cy - f * b[..., 0] / bz_safe
    cols = cx + f * b[..., 1] / bz_safe
    inside = ok & (rows >= 0) & (rows <= h - 1) & (cols >= 0) & (cols <= w - 1)
    patch = map_coordinates(img, [rows, cols], order=1, mode="constant", cval=0.0)
    patch = np.where(inside, patch, 0.0).astype(np.float32)
    return patch, inside, (on, oe)


class PatchMap:
    """Patches with their stamped positions, saved as one .npz."""

    def __init__(self, source: str = "field_survey", patch_m: float = PATCH_M,
                 gsd_m: float = GSD_M, name: str = ""):
        self.source = validate_map_source(source)
        self.patch_m, self.gsd_m, self.name = float(patch_m), float(gsd_m), name
        self.patches: List[np.ndarray] = []
        self.valid: List[np.ndarray] = []
        self.lat: List[float] = []
        self.lon: List[float] = []
        self.alt_m: List[float] = []
        self.sigma_m: List[float] = []
        self.t: List[float] = []

    def __len__(self) -> int:
        return len(self.patches)

    def add(self, patch: np.ndarray, valid: np.ndarray, lat: float, lon: float,
            alt_m: float, sigma_m: float, t: float) -> int:
        self.patches.append(np.asarray(patch, np.float32))
        self.valid.append(np.asarray(valid, bool))
        self.lat.append(float(lat)); self.lon.append(float(lon))
        self.alt_m.append(float(alt_m)); self.sigma_m.append(float(sigma_m)); self.t.append(float(t))
        return len(self.patches) - 1

    def offsets_m(self, lat: float, lon: float) -> np.ndarray:
        """(north, east) of every patch centre from (lat, lon), metres."""
        if not self.patches:
            return np.zeros((0, 2))
        coslat = math.cos(math.radians(lat))
        return np.stack([(np.array(self.lat) - lat) * DEG_M,
                         (np.array(self.lon) - lon) * DEG_M * coslat], axis=1)

    def nearest_m(self, lat: float, lon: float) -> Optional[float]:
        if not self.patches:
            return None
        return float(np.min(np.hypot(*self.offsets_m(lat, lon).T)))

    def candidates(self, lat: float, lon: float, radius_m: float) -> List[int]:
        if not self.patches:
            return []
        d = np.hypot(*self.offsets_m(lat, lon).T)
        return [int(i) for i in np.where(d <= radius_m)[0]]

    def centres(self) -> List[Tuple[float, float]]:
        return list(zip(self.lat, self.lon))

    def save(self, path: str) -> None:
        meta = {"format": MAP_FORMAT, "source": self.source, "patch_m": self.patch_m,
                "gsd_m": self.gsd_m, "name": self.name, "n": len(self.patches)}
        np.savez_compressed(path, meta=json.dumps(meta),
                            patches=np.stack(self.patches) if self.patches else np.zeros((0, 1, 1), np.float32),
                            valid=np.stack(self.valid) if self.valid else np.zeros((0, 1, 1), bool),
                            lat=np.array(self.lat), lon=np.array(self.lon), alt_m=np.array(self.alt_m),
                            sigma_m=np.array(self.sigma_m), t=np.array(self.t))

    @classmethod
    def load(cls, path: str) -> "PatchMap":
        d = np.load(path, allow_pickle=False)
        meta = json.loads(str(d["meta"]))
        if meta.get("format") != MAP_FORMAT:
            raise ValueError(f"patch map format {meta.get('format')} is not {MAP_FORMAT}")
        m = cls(meta["source"], meta["patch_m"], meta["gsd_m"], meta.get("name", ""))
        for k in range(int(meta["n"])):
            m.add(d["patches"][k], d["valid"][k], d["lat"][k], d["lon"][k], d["alt_m"][k],
                  d["sigma_m"][k], d["t"][k])
        return m


def build_mosaic(pmap: PatchMap, idx: Sequence[int], lat0: float, lon0: float, half_m: float
                 ) -> Tuple[np.ndarray, np.ndarray, int]:
    """Paint the chosen patches into one north-up grid centred on (lat0,
    lon0): (image, coverage count, size). Overlaps are averaged."""
    g = pmap.gsd_m
    n = 2 * int(round(half_m / g)) + 1
    acc = np.zeros((n, n)); cnt = np.zeros((n, n))
    c = (n - 1) // 2
    off = pmap.offsets_m(lat0, lon0)
    p = pmap.patches[0].shape[0] if pmap.patches else 0
    pc = (p - 1) / 2.0
    for i in idx:
        dn, de = off[i]
        r0 = int(round(c - dn / g - pc)); c0 = int(round(c + de / g - pc))
        rs, cs = slice(max(r0, 0), min(r0 + p, n)), slice(max(c0, 0), min(c0 + p, n))
        if rs.stop <= rs.start or cs.stop <= cs.start:
            continue
        prs = slice(rs.start - r0, rs.stop - r0); pcs = slice(cs.start - c0, cs.stop - c0)
        v = pmap.valid[i][prs, pcs]
        acc[rs, cs] += np.where(v, pmap.patches[i][prs, pcs], 0.0)
        cnt[rs, cs] += v
    img = np.where(cnt > 0, acc / np.maximum(cnt, 1), 0.0)
    return img, cnt, n


def _ncc_windows(mosaic: np.ndarray, cover: np.ndarray, tpl: np.ndarray,
                 min_cover: float = 0.7) -> np.ndarray:
    """Masked NCC of tpl against every window of mosaic, over the pixels the
    map covers; -1 where less than min_cover of the window is covered. A
    window at the corridor's edge still matches on the part that exists."""
    w = tpl.shape[0]
    H, W = mosaic.shape[0] - w + 1, mosaic.shape[1] - w + 1
    if H <= 0 or W <= 0:
        return np.zeros((max(H, 0), max(W, 0)))
    win = sliding_window_view(mosaic, (w, w))
    msk = sliding_window_view((cover > 0).astype(float), (w, w))
    n = np.einsum("ijkl->ij", msk)
    sw = np.einsum("ijkl,ijkl->ij", win, msk)
    sww = np.einsum("ijkl,ijkl,ijkl->ij", win, win, msk)
    st = np.einsum("ijkl,kl->ij", msk, tpl)
    stt = np.einsum("ijkl,kl->ij", msk, tpl * tpl)
    swt = np.einsum("ijkl,ijkl,kl->ij", win, msk, tpl)
    n_safe = np.maximum(n, 1.0)
    num = swt - sw * st / n_safe
    var_w = sww - sw * sw / n_safe
    var_t = stt - st * st / n_safe
    den = np.sqrt(np.maximum(var_w, 1e-12) * np.maximum(var_t, 1e-12))
    ncc = np.where((n >= min_cover * w * w) & (var_w > 1e-9) & (var_t > 1e-9), num / den, -1.0)
    return ncc


def _ncc_at(mosaic: np.ndarray, cover: np.ndarray, tpl: np.ndarray, r: int, c: int,
            min_cover: float = 0.7) -> Optional[float]:
    w = tpl.shape[0]
    if r < 0 or c < 0 or r + w > mosaic.shape[0] or c + w > mosaic.shape[1]:
        return None
    m = cover[r:r + w, c:c + w] > 0
    if m.mean() < min_cover:
        return None
    a, b = mosaic[r:r + w, c:c + w][m], tpl[m]
    az, bz = a - a.mean(), b - b.mean()
    den = math.sqrt(float(np.sum(az * az)) * float(np.sum(bz * bz)))
    return float(np.sum(az * bz)) / den if den > 1e-12 else None


def match(live: np.ndarray, live_valid: np.ndarray, mosaic: np.ndarray, cover: np.ndarray,
          gsd_m: float, window_m: float = 16.0, exclusion_m: float = 6.0) -> dict:
    """Slide the live patch's centre window over the mosaic. Returns the
    peak, its position (row, col of the window centre in the mosaic), the
    second peak outside the exclusion radius, and the peak's width."""
    n = live.shape[0]
    w = int(round(window_m / gsd_m))
    s = (n - w) // 2
    tpl = live[s:s + w, s:s + w]
    tv = live_valid[s:s + w, s:s + w]
    if not tv.all():
        return {"status": "declined", "reason": "the ground under the drone is not fully in the "
                "frame (lean or height)", "valid_fraction": float(tv.mean())}
    # coarse pass at twice the sampling distance
    k = 2
    mo = mosaic[:mosaic.shape[0] // k * k, :mosaic.shape[1] // k * k]
    co = cover[:mo.shape[0], :mo.shape[1]]
    mo_c = mo.reshape(mo.shape[0] // k, k, mo.shape[1] // k, k).mean(axis=(1, 3))
    co_c = co.reshape(co.shape[0] // k, k, co.shape[1] // k, k).min(axis=(1, 3))
    tp_c = tpl[:w // k * k, :w // k * k].reshape(w // k, k, w // k, k).mean(axis=(1, 3))
    ncc_c = _ncc_windows(mo_c, co_c, tp_c)
    if ncc_c.size == 0 or ncc_c.max() <= -1.0:
        return {"status": "declined", "reason": "no fully covered window in the map near the prior"}
    r_c, c_c = np.unravel_index(int(np.argmax(ncc_c)), ncc_c.shape)
    # second peak: the best value farther than the exclusion radius
    rr, cc = np.indices(ncc_c.shape)
    far = np.hypot(rr - r_c, cc - c_c) * gsd_m * k > exclusion_m
    second = float(ncc_c[far].max()) if far.any() and (ncc_c[far] > -1).any() else -1.0
    # fine pass around the coarse peak
    R = 3
    best, best_pos = -2.0, (r_c * k, c_c * k)
    vals = {}
    for dr in range(-R, R + 1):
        for dc in range(-R, R + 1):
            r, c = r_c * k + dr, c_c * k + dc
            v = _ncc_at(mosaic, cover, tpl, r, c)
            if v is None:
                continue
            vals[(dr, dc)] = v
            if v > best:
                best, best_pos = v, (r, c)
    if best <= -2.0:
        return {"status": "declined", "reason": "the map does not cover enough of the ground around "
                "the best coarse match"}
    br, bc = best_pos[0] - r_c * k, best_pos[1] - c_c * k
    curv = []
    for (a, b) in (((-1, 0), (1, 0)), ((0, -1), (0, 1))):
        va, vb = vals.get((br + a[0], bc + a[1])), vals.get((br + b[0], bc + b[1]))
        if va is not None and vb is not None:
            curv.append(va + vb - 2 * best)
    kappa = -min(curv) if curv else 0.0
    # width of the peak: how far the correlation falls by what is left of
    # it (1 - peak). ASSUMPTION, checked in simulation by coverage.
    sigma_px = math.sqrt((1.0 - best) / kappa) if kappa > 1e-6 else 10.0
    sigma_px = min(max(sigma_px, 0.5), 10.0)
    return {"status": "ok", "peak": best, "second": second, "row": best_pos[0] + (w - 1) / 2.0,
            "col": best_pos[1] + (w - 1) / 2.0, "sigma_px": sigma_px, "window_px": w,
            "coarse_peak": float(ncc_c.max())}
