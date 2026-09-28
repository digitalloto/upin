"""
A map of where GNSS reception was good and where it was not (spec 2.5).

Every epoch the receiver reports how many satellites it tracks and how far
its noise floor has risen. Logged against where the aircraft believed it was,
that becomes a picture of the jamming: its edge, and which way it weakens.
The Escape Manager uses the second to leave a jammed area by the shortest
route; the command centre gets the first when the link returns.

WHAT IT IS HONEST ABOUT

Under jamming the aircraft's own position is uncertain -- that is the whole
problem -- so each entry carries the sigma of the position it was logged at,
and the gradient fit weights entries by it. A cell logged from a 200 m
dead-reckoned guess counts for much less than one logged from a GNSS fix.
With too few cells, or cells all in a line, there is no gradient and the map
says so instead of pointing somewhere.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

DEG_M = 111_320.0


@dataclass
class Cell:
    n: int = 0
    rise_sum: float = 0.0
    tracked_min: int = 10 ** 6
    weight_sum: float = 0.0
    lat_sum: float = 0.0
    lon_sum: float = 0.0

    @property
    def mean_rise_db(self) -> float:
        return self.rise_sum / self.n if self.n else 0.0


@dataclass
class Gradient:
    toward_clear_deg: float        # bearing in which jamming weakens
    slope_db_per_km: float
    cells: int


class JammingMap:
    def __init__(self, cell_m: float = 100.0):
        self.cell_m = cell_m
        self._cells: Dict[Tuple[int, int], Cell] = {}
        self._origin: Optional[Tuple[float, float]] = None

    def _key(self, lat: float, lon: float) -> Tuple[int, int]:
        if self._origin is None:
            self._origin = (lat, lon)
        n = (lat - self._origin[0]) * DEG_M
        e = (lon - self._origin[1]) * DEG_M * math.cos(math.radians(self._origin[0]))
        return (int(math.floor(n / self.cell_m)), int(math.floor(e / self.cell_m)))

    def record(self, lat: float, lon: float, position_sigma_m: float,
               noise_floor_rise_db: float, tracked: int) -> None:
        if not (position_sigma_m > 0 and math.isfinite(position_sigma_m)):
            return
        c = self._cells.setdefault(self._key(lat, lon), Cell())
        w = 1.0 / (position_sigma_m ** 2 + (self.cell_m / 2.0) ** 2)
        c.n += 1
        c.rise_sum += noise_floor_rise_db
        c.tracked_min = min(c.tracked_min, tracked)
        c.weight_sum += w
        c.lat_sum += lat * w
        c.lon_sum += lon * w

    def __len__(self) -> int:
        return len(self._cells)

    def cells(self) -> List[Dict]:
        out = []
        for c in self._cells.values():
            out.append({"lat": c.lat_sum / c.weight_sum,
                        "lon": c.lon_sum / c.weight_sum,
                        "noise_floor_rise_db": c.mean_rise_db,
                        "min_tracked": c.tracked_min, "samples": c.n})
        return out

    def gradient(self, lat: float, lon: float,
                 radius_m: float = 1500.0) -> Optional[Gradient]:
        """Which way the jamming weakens around here, or None if unknown.

        A weighted plane fit, rise = a + b*north + c*east, over nearby cells.
        The direction of steepest descent is where to fly to escape.
        """
        rows, ys, ws = [], [], []
        coslat = math.cos(math.radians(lat))
        for c in self._cells.values():
            clat, clon = c.lat_sum / c.weight_sum, c.lon_sum / c.weight_sum
            n = (clat - lat) * DEG_M
            e = (clon - lon) * DEG_M * coslat
            if math.hypot(n, e) > radius_m:
                continue
            rows.append([1.0, n / 1000.0, e / 1000.0])
            ys.append(c.mean_rise_db)
            ws.append(c.weight_sum)
        if len(rows) < 3:
            return None
        A, y, W = np.array(rows), np.array(ys), np.diag(ws)
        # A single straight transit samples a line. Along it the gradient is
        # real; across it the plane fit is fitting position noise, and on
        # the first try it pointed 82 degrees off. Require genuine 2-D
        # coverage -- a cross-track spread of at least a cell -- or say
        # there is no gradient.
        pts = A[:, 1:] * 1000.0
        wn = np.array(ws) / np.sum(ws)
        centred = pts - wn @ pts
        cov = (centred * wn[:, None]).T @ centred
        if math.sqrt(max(np.linalg.eigvalsh(cov)[0], 0.0)) < self.cell_m:
            return None
        N = A.T @ W @ A
        if np.linalg.cond(N) > 1e8:
            return None                     # cells in a line: no 2-D gradient
        a, b, cc = np.linalg.solve(N, A.T @ W @ y)
        slope = math.hypot(b, cc)
        if slope < 1e-6:
            return None
        return Gradient(math.degrees(math.atan2(-cc, -b)) % 360.0, slope, len(rows))
