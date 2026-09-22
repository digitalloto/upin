"""
Layer 4 — Landmark chain navigation.

The oldest way of getting somewhere without a map reference of your own
position: pick out a thing you can recognise, note where it is on the chart,
take its bearing, and draw the line you must be standing on. Two such lines
cross at your position. Three tell you how much to trust the crossing.

For a drone this is the reset that every dead-reckoning method needs. Layer 2
drifts because wind and battery sag are not fully modelled; this layer does
not drift at all, because it measures against things bolted to the ground.
It also cannot be jammed or spoofed by radio, because nothing here is a
radio — an attacker would have to move a water tower.

WHAT IT DOES

  resection        two or more bearings to charted landmarks, solved by
                   weighted Gauss-Newton in a local tangent plane, with the
                   covariance of the solve reported as the accuracy

  breadcrumbs      every confirmed fix on the way out is recorded with the
                   landmarks that produced it, so the return leg is flown
                   back down a chain of positions that were each measured
                   rather than predicted

  cross-check      a satellite fix that disagrees with a landmark fix is the
                   one that is wrong; the landmark is a physical object and
                   the satellite signal is a waveform anyone can forge

MAP SOURCES

Only Indian sources are accepted — Bhuvan (ISRO/NRSC), Survey of India,
Indian Naval Hydrographic Office charts, Cartosat, or the operator's own
surveyed points. The whitelist in ALLOWED_MAP_SOURCES is the enforcement
point: a landmark built from anything else raises at construction rather
than quietly entering the solve. Adding a source is a deliberate edit to
that set, not something that happens by accident.

WHERE IT REFUSES

Honours the no-fabrication contract. No map, fewer than two usable
observations, bearings too old, landmarks too close together in bearing to
cut a decent angle, or a solve that will not converge — each returns no fix
and names which. A cocked hat is only a position if the lines actually
cross at an angle.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from upin.core.layer_base import (
    LayerCapability, LayerGroup, LayerReading, NavigationLayer,
)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.core.sensor_requirements import (
    DataInput, Hardware, ReferenceData, SensorRequirement,
)

DEG_M = 111_320.0


# ---------------------------------------------------------------------------
# Map provenance
# ---------------------------------------------------------------------------

class MapSource:
    """Indian map sources a landmark may come from.

    UPIN does not use Google Maps or any other foreign basemap, anywhere.
    This is not a preference; for a navigation system intended for Indian
    defence use it is a requirement about where the underlying survey data
    lives and who controls it.
    """
    BHUVAN = "bhuvan"                        # ISRO / NRSC geoportal
    SURVEY_OF_INDIA = "survey_of_india"      # SoI topographic sheets
    NHO_CHART = "nho_chart"                  # Indian Naval Hydrographic Office
    CARTOSAT = "cartosat"                    # ISRO Cartosat imagery products
    FIELD_SURVEY = "field_survey"            # operator's own DGPS survey


ALLOWED_MAP_SOURCES = frozenset({
    MapSource.BHUVAN,
    MapSource.SURVEY_OF_INDIA,
    MapSource.NHO_CHART,
    MapSource.CARTOSAT,
    MapSource.FIELD_SURVEY,
})

# Named so the error message is useful rather than a bare "not in whitelist".
_FOREIGN_SOURCES = ("google", "gmaps", "mapbox", "here", "tomtom", "bing")


class ForeignMapSourceError(ValueError):
    """Raised when a landmark carries a non-Indian map source."""


def validate_map_source(source: str) -> str:
    """Accept only whitelisted Indian sources. Refuse everything else."""
    s = (source or "").strip().lower()
    if not s:
        raise ForeignMapSourceError(
            "landmark has no map source; provenance is required")
    for bad in _FOREIGN_SOURCES:
        if bad in s:
            raise ForeignMapSourceError(
                f"map source {source!r} is a foreign basemap. UPIN uses Indian "
                f"sources only: {sorted(ALLOWED_MAP_SOURCES)}")
    if s not in ALLOWED_MAP_SOURCES:
        raise ForeignMapSourceError(
            f"map source {source!r} is not in the allowed set "
            f"{sorted(ALLOWED_MAP_SOURCES)}")
    return s


# ---------------------------------------------------------------------------
# Landmarks and observations
# ---------------------------------------------------------------------------

@dataclass
class Landmark:
    """One charted object whose position is known and whose source is known.

    position_accuracy_m is the survey accuracy of the charted coordinate,
    not a guess. It propagates into the fix, because a fix cannot be better
    than the chart it was taken against.
    """
    landmark_id: str
    latitude: float
    longitude: float
    source: str
    position_accuracy_m: float
    name: str = ""
    altitude_m: Optional[float] = None
    height_m: Optional[float] = None      # structure height above its base
    feature_type: str = ""                # tower, bridge, tank, spire, junction

    def __post_init__(self):
        self.source = validate_map_source(self.source)
        if self.position_accuracy_m <= 0:
            raise ValueError(
                f"landmark {self.landmark_id}: survey accuracy must be stated "
                f"and positive, got {self.position_accuracy_m}")


@dataclass
class BearingObservation:
    """A measured bearing, and optionally a range, to one landmark.

    bearing_deg is true north, from the aircraft to the landmark, as
    produced by a detection in the camera frame combined with the platform
    attitude. bearing_sigma_deg is what that pipeline reports for this
    detection — not a constant.
    """
    landmark_id: str
    bearing_deg: float
    bearing_sigma_deg: float
    timestamp: float
    range_m: Optional[float] = None
    range_sigma_m: Optional[float] = None

    def __post_init__(self):
        if self.bearing_sigma_deg <= 0:
            raise ValueError("bearing_sigma_deg must be positive")
        if self.range_m is not None and (self.range_sigma_m is None
                                         or self.range_sigma_m <= 0):
            raise ValueError("a range observation must state its sigma")


class LandmarkMap:
    """The charted landmarks available to the aircraft.

    Every entry has been through validate_map_source, so a map that loads is
    a map whose provenance is known.
    """

    def __init__(self, landmarks: Sequence[Landmark] = ()):
        self._by_id: Dict[str, Landmark] = {}
        for lm in landmarks:
            self.add(lm)

    def add(self, landmark: Landmark):
        self._by_id[landmark.landmark_id] = landmark

    def get(self, landmark_id: str) -> Optional[Landmark]:
        return self._by_id.get(landmark_id)

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, landmark_id: object) -> bool:
        return landmark_id in self._by_id

    @property
    def sources(self) -> List[str]:
        return sorted({lm.source for lm in self._by_id.values()})

    def within(self, lat: float, lon: float, radius_m: float) -> List[Landmark]:
        """Charted landmarks within radius_m, nearest first. Deterministic."""
        out = []
        for lm in self._by_id.values():
            d = _flat_distance_m(lat, lon, lm.latitude, lm.longitude)
            if d <= radius_m:
                out.append((d, lm.landmark_id, lm))
        out.sort(key=lambda t: (t[0], t[1]))
        return [lm for _d, _i, lm in out]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def _flat_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dn = (lat2 - lat1) * DEG_M
    de = (lon2 - lon1) * DEG_M * math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.hypot(dn, de)


def wrap_pi(angle_rad: float) -> float:
    """Fold an angle into (-pi, pi]."""
    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


def cut_angle_deg(bearings_deg: Sequence[float]) -> float:
    """Best crossing angle available in a set of bearings.

    Two lines of position that nearly coincide cross at a point that slides
    a long way for a small bearing error. The navigator's rule is to look
    for a wide cut; this returns the widest available, folded into 0-90
    because a 170 degree cut is as good as a 10 degree one is bad.
    """
    best = 0.0
    for i in range(len(bearings_deg)):
        for j in range(i + 1, len(bearings_deg)):
            diff = abs(bearings_deg[i] - bearings_deg[j]) % 180.0
            diff = min(diff, 180.0 - diff)
            best = max(best, diff)
    return best


@dataclass
class ResectionResult:
    """Outcome of one resection solve."""
    converged: bool
    latitude: float = 0.0
    longitude: float = 0.0
    accuracy_m: float = float("inf")
    sigma_north_m: float = float("inf")
    sigma_east_m: float = float("inf")
    iterations: int = 0
    residual_rms_deg: float = float("inf")
    cut_angle_deg: float = 0.0
    condition_number: float = float("inf")
    observations_used: int = 0
    reason: str = ""


def resect(observations: Sequence[BearingObservation],
           landmark_map: LandmarkMap,
           seed: Optional[Tuple[float, float]] = None,
           max_iterations: int = 30,
           tolerance_m: float = 0.01) -> ResectionResult:
    """Solve for position from bearings (and optional ranges) to landmarks.

    Weighted Gauss-Newton in a north-east tangent plane pinned at the
    centroid of the landmarks used. Each bearing contributes the residual

        r = wrap(measured - atan2(E_lm - e, N_lm - n))

    weighted by 1/sigma^2, where sigma combines the bearing uncertainty with
    the angle the chart's own survey error subtends at that range. The
    covariance of the converged solve is (J^T W J)^-1, and that is what is
    reported as the accuracy: it is the geometry's answer, not a label.
    """
    used: List[Tuple[BearingObservation, Landmark]] = []
    for obs in observations:
        lm = landmark_map.get(obs.landmark_id)
        if lm is not None:
            used.append((obs, lm))

    # A bearing pair fixes a position; so does one bearing plus one range.
    rows = sum(2 if o.range_m is not None else 1 for o, _ in used)
    if rows < 2:
        return ResectionResult(False, reason=NoFixReason.INSUFFICIENT_INPUT,
                               observations_used=len(used))

    lat0 = float(np.mean([lm.latitude for _o, lm in used]))
    lon0 = float(np.mean([lm.longitude for _o, lm in used]))
    coslat = max(math.cos(math.radians(lat0)), 0.01)

    def to_ne(lat: float, lon: float) -> Tuple[float, float]:
        return (lat - lat0) * DEG_M, (lon - lon0) * DEG_M * coslat

    lm_ne = [to_ne(lm.latitude, lm.longitude) for _o, lm in used]
    bearings = [o.bearing_deg for o, _lm in used]
    cut = cut_angle_deg(bearings) if len(bearings) >= 2 else 90.0

    if seed is not None:
        x = np.array(to_ne(seed[0], seed[1]), dtype=float)
    else:
        x = _seed(lm_ne, used)

    delta_norm = float("inf")
    iterations = 0
    JtWJ = np.eye(2)
    residuals = np.zeros(rows)

    for iterations in range(1, max_iterations + 1):
        J = np.zeros((rows, 2))
        r = np.zeros(rows)
        w = np.zeros(rows)
        row = 0
        for (obs, lm), (n_lm, e_lm) in zip(used, lm_ne):
            dn = n_lm - x[0]
            de = e_lm - x[1]
            d2 = dn * dn + de * de
            d = math.sqrt(d2)
            if d < 1e-6:                       # standing on the landmark
                return ResectionResult(False, reason=NoFixReason.POOR_GEOMETRY,
                                       cut_angle_deg=cut,
                                       observations_used=len(used))

            predicted = math.atan2(de, dn)
            r[row] = wrap_pi(math.radians(obs.bearing_deg) - predicted)
            J[row, 0] = -de / d2
            J[row, 1] = dn / d2
            # The chart's own error subtends an angle at this range, so a
            # bearing to a coarsely surveyed landmark is worth less.
            sigma_chart = math.atan2(lm.position_accuracy_m, max(d, 1.0))
            sigma = math.hypot(math.radians(obs.bearing_sigma_deg), sigma_chart)
            w[row] = 1.0 / (sigma * sigma)
            row += 1

            if obs.range_m is not None:
                r[row] = obs.range_m - d
                J[row, 0] = dn / d
                J[row, 1] = de / d
                sigma_r = math.hypot(obs.range_sigma_m or 1.0,
                                     lm.position_accuracy_m)
                w[row] = 1.0 / (sigma_r * sigma_r)
                row += 1

        W = np.diag(w)
        JtWJ = J.T @ W @ J
        try:
            cond = float(np.linalg.cond(JtWJ))
        except np.linalg.LinAlgError:           # pragma: no cover - defensive
            cond = float("inf")
        if not np.isfinite(cond) or cond > 1e12:
            return ResectionResult(False, reason=NoFixReason.POOR_GEOMETRY,
                                   cut_angle_deg=cut, condition_number=cond,
                                   observations_used=len(used))
        try:
            delta = -np.linalg.solve(JtWJ, J.T @ W @ r)
        except np.linalg.LinAlgError:           # pragma: no cover - defensive
            return ResectionResult(False, reason=NoFixReason.POOR_GEOMETRY,
                                   cut_angle_deg=cut,
                                   observations_used=len(used))

        # A Gauss-Newton step that flies off is a sign the seed was on the
        # wrong side of a line of position. Cap it rather than diverging.
        step = float(np.linalg.norm(delta))
        if step > 5000.0:
            delta = delta * (5000.0 / step)
            step = 5000.0
        x = x + delta
        delta_norm = step
        residuals = r
        if delta_norm < tolerance_m:
            break

    if delta_norm > 1.0:
        return ResectionResult(False, reason=NoFixReason.DIVERGED,
                               iterations=iterations, cut_angle_deg=cut,
                               observations_used=len(used))

    try:
        cov = np.linalg.inv(JtWJ)
    except np.linalg.LinAlgError:               # pragma: no cover - defensive
        return ResectionResult(False, reason=NoFixReason.POOR_GEOMETRY,
                               cut_angle_deg=cut, observations_used=len(used))

    sigma_n = math.sqrt(max(cov[0, 0], 0.0))
    sigma_e = math.sqrt(max(cov[1, 1], 0.0))
    drms = math.hypot(sigma_n, sigma_e)
    bearing_rows = [i for i in range(rows)]
    rms_deg = math.degrees(math.sqrt(float(np.mean(residuals[bearing_rows] ** 2))))

    return ResectionResult(
        converged=True,
        latitude=lat0 + x[0] / DEG_M,
        longitude=lon0 + x[1] / (DEG_M * coslat),
        accuracy_m=drms,
        sigma_north_m=sigma_n,
        sigma_east_m=sigma_e,
        iterations=iterations,
        residual_rms_deg=rms_deg,
        cut_angle_deg=cut,
        condition_number=float(np.linalg.cond(JtWJ)),
        observations_used=len(used),
        reason="",
    )


def _seed(lm_ne: Sequence[Tuple[float, float]],
          used: Sequence[Tuple[BearingObservation, "Landmark"]]) -> np.ndarray:
    """Deterministic starting point for the solve.

    Preferred: intersect two lines of position. Failing that — a single
    landmark observed with a range — step back down its bearing by the
    measured distance, which lands on the answer directly. Last resort, the
    centroid of the landmarks, which is deterministic and converges for any
    real geometry. The seed is a function of the observations alone, never
    of what the layer solved last time, so a read is a pure function of what
    it was given.
    """
    bearings_deg = [o.bearing_deg for o, _lm in used]
    centroid = np.array([float(np.mean([p[0] for p in lm_ne])),
                         float(np.mean([p[1] for p in lm_ne]))])

    ranged = [(o, p) for (o, _lm), p in zip(used, lm_ne) if o.range_m]
    if len(bearings_deg) < 2 and ranged:
        obs, (n_lm, e_lm) = ranged[0]
        back = math.radians(obs.bearing_deg + 180.0)
        return np.array([n_lm + obs.range_m * math.cos(back),
                         e_lm + obs.range_m * math.sin(back)])

    best: Optional[Tuple[float, np.ndarray]] = None
    for i in range(len(bearings_deg)):
        for j in range(i + 1, len(bearings_deg)):
            b1 = math.radians(bearings_deg[i] + 180.0)
            b2 = math.radians(bearings_deg[j] + 180.0)
            u1 = np.array([math.cos(b1), math.sin(b1)])
            u2 = np.array([math.cos(b2), math.sin(b2)])
            det = u1[0] * (-u2[1]) - (-u2[0]) * u1[1]
            if abs(det) < 1e-6:
                continue
            p1 = np.array(lm_ne[i], dtype=float)
            p2 = np.array(lm_ne[j], dtype=float)
            rhs = p2 - p1
            t1 = (rhs[0] * (-u2[1]) - (-u2[0]) * rhs[1]) / det
            point = p1 + t1 * u1
            quality = abs(det)
            if best is None or quality > best[0]:
                best = (quality, point)
    if best is None:
        return centroid
    point = best[1]
    if not np.all(np.isfinite(point)) or float(np.linalg.norm(point)) > 1e6:
        return centroid
    return point


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

@dataclass
class Breadcrumb:
    """One measured position on the outbound leg, and how it was measured."""
    latitude: float
    longitude: float
    altitude: Optional[float]
    accuracy_m: float
    timestamp: float
    landmark_ids: Tuple[str, ...]
    cut_angle_deg: float


@dataclass
class Leg:
    """Guidance from where you are to the next breadcrumb on the way home."""
    bearing_deg: float
    distance_m: float
    target: Breadcrumb
    remaining_crumbs: int


class LandmarkChain:
    """The trail of measured fixes recorded on the way out.

    Only positions that were actually solved get recorded, so flying the
    chain in reverse is flying back through places the aircraft demonstrably
    was, rather than through a predicted track. That is the whole point: the
    return leg inherits the outbound leg's evidence.
    """

    def __init__(self, min_spacing_m: float = 25.0):
        self._crumbs: List[Breadcrumb] = []
        self._min_spacing_m = min_spacing_m
        self._cursor: Optional[int] = None

    def record(self, crumb: Breadcrumb) -> bool:
        """Add a fix to the trail if it is far enough from the last one."""
        if self._crumbs:
            last = self._crumbs[-1]
            if _flat_distance_m(last.latitude, last.longitude,
                                crumb.latitude, crumb.longitude) < self._min_spacing_m:
                return False
        self._crumbs.append(crumb)
        return True

    def begin_return(self):
        """Point the cursor at the most recent crumb and work backwards."""
        self._cursor = len(self._crumbs) - 1 if self._crumbs else None

    def next_leg(self, lat: float, lon: float,
                 arrival_radius_m: float = 20.0) -> Optional[Leg]:
        """Bearing and distance to the next crumb on the way home.

        Returns None when the trail is empty or has been flown to the end.
        Nothing is invented for an empty trail.
        """
        if not self._crumbs:
            return None
        if self._cursor is None:
            self.begin_return()
        while self._cursor is not None and self._cursor >= 0:
            crumb = self._crumbs[self._cursor]
            dn = (crumb.latitude - lat) * DEG_M
            de = ((crumb.longitude - lon) * DEG_M
                  * math.cos(math.radians((lat + crumb.latitude) / 2.0)))
            dist = math.hypot(dn, de)
            if dist <= arrival_radius_m:
                self._cursor -= 1
                continue
            return Leg(bearing_deg=math.degrees(math.atan2(de, dn)) % 360.0,
                       distance_m=dist, target=crumb,
                       remaining_crumbs=self._cursor + 1)
        return None

    @property
    def crumbs(self) -> List[Breadcrumb]:
        return list(self._crumbs)

    @property
    def length_m(self) -> float:
        total = 0.0
        for a, b in zip(self._crumbs, self._crumbs[1:]):
            total += _flat_distance_m(a.latitude, a.longitude,
                                      b.latitude, b.longitude)
        return total

    def __len__(self) -> int:
        return len(self._crumbs)


# ---------------------------------------------------------------------------
# The layer
# ---------------------------------------------------------------------------

class LandmarkChainLayer(NavigationLayer):
    """Layer 144 — position by resection from charted Indian landmarks.

    Honours the no-fabrication contract. Without a map, without two usable
    observations, with stale observations, with a geometry too narrow to cut,
    or with a solve that will not converge, it returns no fix and says which.
    """

    NO_FABRICATION = True

    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("camera", why="detects and identifies charted landmarks",
                     typical_part="gimbal-stabilised, known field of view",
                     approx_cost_usd=400, already_on_most_drones=True),
            Hardware("attitude reference", why="turns a pixel offset into a "
                                               "true-north bearing",
                     typical_part="AHRS or a calibrated IMU",
                     approx_cost_usd=800, already_on_most_drones=True),
        ],
        inputs=[
            DataInput("landmark bearings", feed_method="observe",
                      units="degrees true",
                      why="each bearing is one line of position"),
        ],
        reference_data=[
            ReferenceData("charted landmark positions",
                          source="Survey of India, Bhuvan, NHO charts, "
                                 "Cartosat or an operator DGPS survey",
                          why="a bearing is only useful to a point whose "
                              "coordinate is known",
                          bundled=False),
        ],
        preconditions=(
            "two independent observations (two bearings, or a bearing and a range)",
            "a cut angle of at least 15 degrees between bearings",
            "observations no older than 5 seconds",
        ),
        notes="Needs no radio of any kind, so it cannot be jammed or spoofed "
              "by RF. Forging it would mean physically moving a landmark.",
    )

    MIN_CUT_ANGLE_DEG = 15.0
    """Below this the lines of position are too near parallel to trust.

    The mariner's rule of thumb, and it is a rule about geometry rather than
    about instruments: at a ten degree cut, one degree of bearing error moves
    the fix roughly six times as far as it would at ninety degrees.
    """

    MAX_OBSERVATION_AGE_S = 5.0
    """A bearing is a statement about where the aircraft was when it was
    taken. On a moving platform an old one is not wrong, it is stale."""

    def __init__(self, landmark_map: Optional[LandmarkMap] = None,
                 min_spacing_m: float = 25.0):
        super().__init__(
            layer_id="lmkchain_e23", layer_number=144,
            name="Landmark Chain Navigation",
            group=LayerGroup.E_OPTICAL_VISION,
            capabilities=[LayerCapability.POSITION, LayerCapability.HEADING],
            is_novel=True,
            description="Resection from charted Indian landmarks with a "
                        "breadcrumb chain for the return leg",
        )
        self._map = landmark_map or LandmarkMap()
        self._observations: List[BearingObservation] = []
        self.chain = LandmarkChain(min_spacing_m=min_spacing_m)
        self._last_crumb_key: Optional[Tuple] = None
        self._fixes = 0

    # -- setup ------------------------------------------------------

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = len(self._map) >= 2
        return True

    def get_accuracy_rating(self) -> float:
        return 0.80

    def load_map(self, landmarks: Sequence[Landmark]):
        """Install charted landmarks. Provenance is checked per landmark."""
        for lm in landmarks:
            self._map.add(lm)
        self.status.is_healthy = len(self._map) >= 2

    @property
    def landmark_map(self) -> LandmarkMap:
        return self._map

    def observe(self, obs: BearingObservation):
        """Feed one bearing produced by the detection pipeline."""
        self._observations.append(obs)

    def observe_many(self, observations: Sequence[BearingObservation]):
        self._observations.extend(observations)

    def clear_observations(self):
        self._observations.clear()

    # -- the reading ------------------------------------------------

    def read(self, now: Optional[float] = None) -> LayerReading:
        now = time.time() if now is None else now

        if len(self._map) == 0:
            return no_fix(self.layer_id, NoFixReason.NO_INPUT,
                          "no landmark map loaded",
                          allowed_map_sources=sorted(ALLOWED_MAP_SOURCES))

        if not self._observations:
            return no_fix(self.layer_id, NoFixReason.NO_INPUT,
                          self.REQUIRES.describe_missing(),
                          landmarks_charted=len(self._map),
                          feed_via=self.REQUIRES.feed_methods)

        fresh = [o for o in self._observations
                 if now - o.timestamp <= self.MAX_OBSERVATION_AGE_S]
        known = [o for o in fresh if o.landmark_id in self._map]
        stale_dropped = len(self._observations) - len(fresh)
        rows = sum(2 if o.range_m is not None else 1 for o in known)

        if rows < 2:
            reason = (NoFixReason.STALE_INPUT if stale_dropped
                      else NoFixReason.INSUFFICIENT_INPUT)
            return no_fix(self.layer_id, reason,
                          "a fix needs two independent observations "
                          "(two bearings, or a bearing and a range)",
                          observations_supplied=len(self._observations),
                          observations_usable=len(known),
                          stale_dropped=stale_dropped)

        bearings = [o.bearing_deg for o in known]
        cut = cut_angle_deg(bearings) if len(bearings) >= 2 else 90.0
        has_range = any(o.range_m is not None for o in known)
        if not has_range and cut < self.MIN_CUT_ANGLE_DEG:
            return no_fix(self.layer_id, NoFixReason.POOR_GEOMETRY,
                          "lines of position too near parallel to cut a fix",
                          cut_angle_deg=round(cut, 2),
                          min_cut_angle_deg=self.MIN_CUT_ANGLE_DEG,
                          landmark_ids=sorted(o.landmark_id for o in known))

        # Deliberately not seeded from the previous fix. Carrying the last
        # solve forward would make a read depend on the layer's history as
        # well as its inputs, and the contract is that identical inputs give
        # an identical answer. The closed-form seed converges anyway.
        result = resect(known, self._map)
        if not result.converged:
            return no_fix(self.layer_id, result.reason or NoFixReason.DIVERGED,
                          "resection did not produce a usable solution",
                          iterations=result.iterations,
                          cut_angle_deg=round(result.cut_angle_deg, 2),
                          observations_usable=len(known))

        landmark_ids = tuple(sorted(o.landmark_id for o in known))
        altitude = self._altitude_hint(known)

        crumb = Breadcrumb(
            latitude=result.latitude, longitude=result.longitude,
            altitude=altitude, accuracy_m=result.accuracy_m,
            timestamp=now, landmark_ids=landmark_ids,
            cut_angle_deg=result.cut_angle_deg,
        )
        # Record once per distinct observation set. Reading twice off the same
        # bearings is the same fix, not a second one, so the chain does not
        # grow and the reading stays bit-identical.
        crumb_key = (landmark_ids,
                     tuple(round(o.bearing_deg, 9) for o in known),
                     tuple(round(o.timestamp, 9) for o in known))
        recorded = False
        if crumb_key != self._last_crumb_key:
            recorded = self.chain.record(crumb)
            self._last_crumb_key = crumb_key
            self._fixes += 1

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=result.latitude,
                              longitude=result.longitude,
                              altitude=altitude,
                              accuracy_m=result.accuracy_m,
                              timestamp=now),
            self_confidence=self._confidence(result),
            is_valid=True,
            raw_data={
                "fabricated": False,
                "landmark_ids": list(landmark_ids),
                "observations_used": result.observations_used,
                "stale_dropped": stale_dropped,
                "cut_angle_deg": round(result.cut_angle_deg, 2),
                "sigma_north_m": round(result.sigma_north_m, 3),
                "sigma_east_m": round(result.sigma_east_m, 3),
                "residual_rms_deg": round(result.residual_rms_deg, 4),
                "iterations": result.iterations,
                "condition_number": round(result.condition_number, 2),
                "map_sources": self._map.sources,
                "chain_length": len(self.chain),
                "chain_distance_m": round(self.chain.length_m, 1),
                "crumb_recorded": recorded,
                "rf_independent": True,
                "can_reset_dead_reckoning": True,
            },
        )

    def _altitude_hint(self, observations: Sequence[BearingObservation]
                       ) -> Optional[float]:
        """Only report altitude when the chart actually carries one.

        Bearings fix a horizontal position and say nothing about height, so
        the altitude here is the charted base elevation of the landmarks
        used, and None when the chart does not give it.
        """
        alts = [self._map.get(o.landmark_id).altitude_m
                for o in observations
                if self._map.get(o.landmark_id) is not None
                and self._map.get(o.landmark_id).altitude_m is not None]
        if not alts:
            return None
        return float(np.mean(alts))

    def _confidence(self, result: ResectionResult) -> float:
        """Confidence from the geometry and the residuals, nothing else.

        Three things the solve actually measured: how tightly the covariance
        came out, how wide the cut was, and how well the bearings agreed with
        each other once a position was chosen.
        """
        acc = max(result.accuracy_m, 0.1)
        spread = 1.0 / (1.0 + acc / 10.0)                  # 10 m -> 0.5
        cut = min(result.cut_angle_deg / 60.0, 1.0)        # 60 deg -> full marks
        agreement = 1.0 / (1.0 + result.residual_rms_deg)  # 1 deg rms -> 0.5
        return float(max(0.0, min(0.99, 0.5 * spread + 0.25 * cut
                                  + 0.25 * agreement)))

    # -- cross-checks -----------------------------------------------

    def check_satellite_claim(self, claimed_lat: float, claimed_lon: float,
                              tolerance_m: float = 50.0,
                              now: Optional[float] = None) -> Dict:
        """Does a satellite fix agree with the landmarks?

        The landmarks are physical objects at surveyed coordinates; the
        satellite fix is a waveform. When they disagree by more than the
        landmark fix's own uncertainty allows, the waveform is the suspect.
        """
        reading = self.read(now=now)
        if not reading.is_valid or reading.position is None:
            return {"checked": False,
                    "reason": reading.raw_data.get("no_fix_reason")}
        gap = _flat_distance_m(reading.position.latitude,
                               reading.position.longitude,
                               claimed_lat, claimed_lon)
        allowed = tolerance_m + 3.0 * reading.position.accuracy_m
        return {
            "checked": True,
            "disagreement_m": gap,
            "allowed_m": allowed,
            "consistent": gap <= allowed,
            "verdict": "CONSISTENT" if gap <= allowed else "SATELLITE_SUSPECT",
            "landmark_accuracy_m": reading.position.accuracy_m,
            "landmark_ids": reading.raw_data["landmark_ids"],
        }

    # -- the return leg ---------------------------------------------

    def return_leg(self, arrival_radius_m: float = 20.0,
                   now: Optional[float] = None) -> Dict:
        """Guidance home along the breadcrumb trail, from the current fix.

        Declines rather than guessing: without a current fix there is no
        "from" and without crumbs there is no "to".
        """
        reading = self.read(now=now)
        if not reading.is_valid or reading.position is None:
            return {"available": False,
                    "reason": reading.raw_data.get("no_fix_reason")}
        if len(self.chain) == 0:
            return {"available": False, "reason": NoFixReason.NO_ANCHOR,
                    "detail": "no breadcrumbs recorded on the outbound leg"}
        leg = self.chain.next_leg(reading.position.latitude,
                                  reading.position.longitude,
                                  arrival_radius_m=arrival_radius_m)
        if leg is None:
            return {"available": False, "reason": "trail_complete",
                    "detail": "flown back to the start of the chain"}
        return {
            "available": True,
            "bearing_deg": round(leg.bearing_deg, 2),
            "distance_m": round(leg.distance_m, 2),
            "remaining_crumbs": leg.remaining_crumbs,
            "target_lat": leg.target.latitude,
            "target_lon": leg.target.longitude,
            "target_accuracy_m": leg.target.accuracy_m,
            "target_landmarks": list(leg.target.landmark_ids),
        }


def reset_dead_reckoning(dr_layer, reading: LayerReading,
                         velocity_ned: Sequence[float] = (0.0, 0.0, 0.0)) -> bool:
    """Re-anchor a command dead-reckoning layer on a landmark fix.

    Composition rather than coupling: Layer 2 knows nothing about landmarks
    and Layer 4 knows nothing about motor commands. This function is the
    only thing that knows both, and it refuses to pass on a fix that is not
    valid, so a drifting estimate is never re-anchored to nothing.
    """
    if not reading.is_valid or reading.position is None:
        return False
    pos = reading.position
    dr_layer.set_anchor(pos.latitude, pos.longitude,
                        pos.altitude if pos.altitude is not None else 0.0,
                        velocity_ned)
    return True
