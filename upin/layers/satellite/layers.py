"""
Group A — Satellite and Celestial Layers (6 layers).

Layer 1:  GPS GNSS
Layer 2:  NavIC Indian Sovereign Signal [N]
Layer 19: LEO Authenticated Satellite Signals [N]
Layer 29: X-Ray Pulsar Navigation (XNAV) [N, U]
Layer 46: Stellar Constellation Pattern Navigation [N]
Layer 47: Diffuse Sky Brightness Gradient Navigation [N]

Each layer independently computes its own position through its own sensor
physics chain.  When a SimulationWorld is available (self.world), the layer
queries that world for raw observables (pseudoranges, pulsar timing, star
positions, etc.) and solves for position/heading using its own algorithm.
When no world is present, layers fall back to the legacy _sim_lat/_sim_lon
approach (noise added to a base coordinate).
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import numpy as np

from upin.core.layer_base import (
    NavigationLayer, LayerGroup, LayerCapability, LayerReading,
)
from upin.core.position import Position

if TYPE_CHECKING:
    from upin.simulation.world import SimulationWorld


# ── Shared trilateration solver ──────────────────────────────────────

def _trilaterate(world: "SimulationWorld", pseudoranges: list[dict],
                 last_lat: float | None = None,
                 last_lon: float | None = None,
                 last_alt: float | None = None) -> tuple[float, float, float] | None:
    """Solve receiver position from satellite pseudoranges via least-squares.

    Iteratively minimises
        ||pseudorange_i − dist(receiver, sat_i) − clock_bias||
    for each visible satellite, recovering [x, y, z, clock_bias] in ECEF.

    Returns (lat, lon, alt) or None if the solution cannot converge.
    """
    if len(pseudoranges) < 4:
        return None

    # Initial guess from last known position or world truth
    init_lat = last_lat if last_lat is not None else world.true_lat
    init_lon = last_lon if last_lon is not None else world.true_lon
    init_alt = last_alt if last_alt is not None else world.true_alt
    x0 = world._lla_to_ecef(init_lat, init_lon, init_alt)

    # State vector: [x, y, z, clock_bias]
    x = np.array([x0[0], x0[1], x0[2], 0.0])

    for _iteration in range(6):
        H = []
        residuals = []
        for pr in pseudoranges:
            sx, sy, sz = pr["sat_ecef"]
            dx = x[0] - sx
            dy = x[1] - sy
            dz = x[2] - sz
            r = math.sqrt(dx * dx + dy * dy + dz * dz)
            if r < 1.0:
                continue
            H.append([dx / r, dy / r, dz / r, 1.0])
            residuals.append(pr["pseudorange_m"] - r - x[3])

        if len(H) < 4:
            return None

        H_arr = np.array(H)
        res_arr = np.array(residuals)
        try:
            delta = np.linalg.lstsq(H_arr, res_arr, rcond=None)[0]
            x += delta
            if np.linalg.norm(delta[:3]) < 0.01:
                break
        except np.linalg.LinAlgError:
            return None

    return world._ecef_to_lla(x[0], x[1], x[2])


# ── Layer implementations ────────────────────────────────────────────

class GPSLayer(NavigationLayer):
    """Layer 1 — GPS GNSS.

    Standard global navigation satellite system. Provides positioning
    through timing of radio signals from MEO satellites (~20,000 km).
    Vulnerable to jamming and spoofing — signals arrive below thermal noise.

    Physics chain:
        world.get_pseudoranges("GPS") → trilateration least-squares → (lat, lon, alt)
    """

    def __init__(self):
        super().__init__(
            layer_id="gps_l1",
            layer_number=1,
            name="GPS GNSS",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY,
                          LayerCapability.TIMING],
            description="Standard GPS L1/L2 satellite positioning",
        )
        self._last_fix: Position | None = None
        self._jammed = False
        self._spoofed = False
        self._spoof_offset = (0.0, 0.0, 0.0)
        self._last_lat: float | None = None
        self._last_lon: float | None = None
        self._last_alt: float | None = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.7  # Good but vulnerable

    def read(self) -> LayerReading:
        if self._jammed:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "JAMMED"},
            )

        if self._simulated:
            if self.world is not None:
                return self._read_from_world()

            # Legacy fallback: noise around a base position
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            base_alt = getattr(self, '_sim_alt', 10.0)

            noise_m = 5.0  # GPS typical accuracy ~5m
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 10.0)

            if self._spoofed:
                lat += self._spoof_offset[0]
                lon += self._spoof_offset[1]
                alt += self._spoof_offset[2]

            pos = Position(
                latitude=lat, longitude=lon, altitude=alt,
                accuracy_m=5.0, timestamp=time.time(),
            )
            self._last_fix = pos
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.9,
                raw_data={"satellites": 12, "hdop": 1.2},
            )
        else:
            # Real hardware interface would go here
            raise NotImplementedError("Live GPS requires hardware interface")

    # ── Physics-based world reading ──────────────────────────────

    def _read_from_world(self) -> LayerReading:
        """Compute GPS fix from pseudoranges via trilateration."""
        # Check jamming at the world level as well
        if self.world.gps_jammed:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "JAMMED"},
            )

        pseudoranges = self.world.get_pseudoranges("GPS")
        result = _trilaterate(
            self.world, pseudoranges,
            self._last_lat, self._last_lon, self._last_alt,
        )

        if result is None:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "NO_FIX", "satellites_visible": len(pseudoranges)},
            )

        lat, lon, alt = result
        self._last_lat, self._last_lon, self._last_alt = lat, lon, alt

        # Apply local spoofing offset (layer-level spoof, separate from
        # the world-level GPS spoofing which is already baked into the
        # pseudoranges).
        if self._spoofed:
            lat += self._spoof_offset[0]
            lon += self._spoof_offset[1]
            alt += self._spoof_offset[2]

        pos = Position(
            latitude=lat, longitude=lon, altitude=alt,
            accuracy_m=5.0, timestamp=time.time(),
        )
        self._last_fix = pos

        # Estimate DOP from satellite geometry
        n_sats = len(pseudoranges)
        hdop = max(0.8, 3.0 / math.sqrt(max(n_sats, 1)))

        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=min(0.95, 0.5 + 0.05 * n_sats),
            raw_data={"satellites": n_sats, "hdop": round(hdop, 2)},
        )

    # ── Simulation helpers ───────────────────────────────────────

    def simulate_jamming(self, jammed: bool = True) -> None:
        self._jammed = jammed

    def simulate_spoofing(self, offset_lat: float = 0.01,
                          offset_lon: float = 0.01) -> None:
        self._spoofed = True
        self._spoof_offset = (offset_lat, offset_lon, 0.0)

    def clear_spoofing(self) -> None:
        self._spoofed = False
        self._spoof_offset = (0.0, 0.0, 0.0)

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


class NavICLayer(NavigationLayer):
    """Layer 2 — NavIC Indian Sovereign Signal [NOVEL].

    India's indigenous IRNSS/NavIC system. PRIMARY positioning signal
    for all Indian applications. Military restricted service provides
    1.5m accuracy within India and 1,500km beyond borders.

    Designated as primary to eliminate foreign dependency.

    Physics chain:
        world.get_pseudoranges("NavIC") → trilateration least-squares → (lat, lon, alt)
    """

    def __init__(self):
        super().__init__(
            layer_id="navic_l2",
            layer_number=2,
            name="NavIC Indian Sovereign Signal",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY,
                          LayerCapability.TIMING],
            is_novel=True,
            description="India sovereign primary positioning — NavIC restricted service",
        )
        self._coverage_region = {
            "lat_min": -5.0, "lat_max": 40.0,
            "lon_min": 55.0, "lon_max": 110.0,
        }
        self._last_lat: float | None = None
        self._last_lon: float | None = None
        self._last_alt: float | None = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.85  # Military-grade restricted service

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()

            # Legacy fallback
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            base_alt = getattr(self, '_sim_alt', 10.0)

            noise_m = 1.5  # NavIC restricted service accuracy
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 3.0)

            pos = Position(
                latitude=lat, longitude=lon, altitude=alt,
                accuracy_m=1.5, timestamp=time.time(),
            )
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.95,
                raw_data={"satellites": 4, "service": "restricted"},
            )
        raise NotImplementedError("Live NavIC requires hardware")

    def _read_from_world(self) -> LayerReading:
        """Compute NavIC fix from pseudoranges via trilateration."""
        pseudoranges = self.world.get_pseudoranges("NavIC")
        result = _trilaterate(
            self.world, pseudoranges,
            self._last_lat, self._last_lon, self._last_alt,
        )

        if result is None:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "NO_FIX",
                          "satellites_visible": len(pseudoranges),
                          "service": "restricted"},
            )

        lat, lon, alt = result
        self._last_lat, self._last_lon, self._last_alt = lat, lon, alt

        pos = Position(
            latitude=lat, longitude=lon, altitude=alt,
            accuracy_m=1.5, timestamp=time.time(),
        )
        n_sats = len(pseudoranges)

        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=min(0.98, 0.7 + 0.07 * n_sats),
            raw_data={"satellites": n_sats, "service": "restricted"},
        )

    def is_in_coverage(self, lat: float, lon: float) -> bool:
        r = self._coverage_region
        return (r["lat_min"] <= lat <= r["lat_max"] and
                r["lon_min"] <= lon <= r["lon_max"])

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


class LEOAuthenticatedLayer(NavigationLayer):
    """Layer 19 — LEO Authenticated Satellite Signals [NOVEL].

    Low Earth orbit satellites (Xona Pulsar constellation) provide signals
    100x stronger than GPS with cryptographic authentication watermarks.
    Signal authentication prevents spoofing at the signal level.

    Physics chain:
        world.get_pseudoranges("LEO") → trilateration least-squares → (lat, lon, alt)
    Best accuracy of all satellite layers due to strong signals and low orbit.
    """

    def __init__(self):
        super().__init__(
            layer_id="leo_l19",
            layer_number=19,
            name="LEO Authenticated Satellite Signals",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            is_novel=True,
            description="LEO constellation with cryptographic authentication",
        )
        self._last_lat: float | None = None
        self._last_lon: float | None = None
        self._last_alt: float | None = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.9  # Stronger signals + authentication

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()

            # Legacy fallback
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            base_alt = getattr(self, '_sim_alt', 10.0)

            noise_m = 1.0
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 2.0)

            pos = Position(latitude=lat, longitude=lon, altitude=alt,
                           accuracy_m=1.0, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.95,
                raw_data={"authenticated": True, "signal_strength_dbm": -120},
            )
        raise NotImplementedError("Live LEO requires hardware")

    def _read_from_world(self) -> LayerReading:
        """Compute LEO fix from pseudoranges via trilateration."""
        pseudoranges = self.world.get_pseudoranges("LEO")
        result = _trilaterate(
            self.world, pseudoranges,
            self._last_lat, self._last_lon, self._last_alt,
        )

        if result is None:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "NO_FIX",
                          "satellites_visible": len(pseudoranges),
                          "authenticated": True},
            )

        lat, lon, alt = result
        self._last_lat, self._last_lon, self._last_alt = lat, lon, alt

        pos = Position(
            latitude=lat, longitude=lon, altitude=alt,
            accuracy_m=1.0, timestamp=time.time(),
        )
        n_sats = len(pseudoranges)

        # LEO signals are ~100x stronger than GPS → better SNR
        signal_strength = -120 + 10 * math.log10(max(n_sats, 1))

        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=min(0.98, 0.6 + 0.05 * n_sats),
            raw_data={"authenticated": True,
                      "satellites": n_sats,
                      "signal_strength_dbm": round(signal_strength, 1)},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


class XRayPulsarLayer(NavigationLayer):
    """Layer 29 — X-Ray Pulsar Navigation (XNAV) [NOVEL, UNDERWATER].

    Rotating neutron stars emit X-ray pulses with atomic clock precision.
    Provides absolute position anywhere in the solar system.
    Completely unjammable — no terrestrial technology can interfere.

    Physics chain:
        world.get_pulsar_timing() → timing-residual position solver → (lat, lon, alt)
    Lower accuracy (~100 m) but fundamentally immune to jamming/spoofing.
    """

    def __init__(self):
        super().__init__(
            layer_id="xnav_l29",
            layer_number=29,
            name="X-Ray Pulsar Navigation",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            is_novel=True,
            is_underwater=True,
            description="Stellar X-ray pulsar timing — unjammable",
        )
        self._last_lat: float | None = None
        self._last_lon: float | None = None
        self._last_alt: float | None = None

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.6  # Lower precision but unjammable

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()

            # Legacy fallback
            base_lat = getattr(self, '_sim_lat', 13.0827)
            base_lon = getattr(self, '_sim_lon', 80.2707)
            base_alt = getattr(self, '_sim_alt', 10.0)

            noise_m = 100.0  # XNAV less precise but completely unjammable
            lat = base_lat + np.random.normal(0, noise_m / 111_000)
            lon = base_lon + np.random.normal(0, noise_m / 111_000)
            alt = base_alt + np.random.normal(0, 50.0)

            pos = Position(latitude=lat, longitude=lon, altitude=alt,
                           accuracy_m=100.0, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.7,
                raw_data={"pulsars_tracked": 3, "unjammable": True},
            )
        raise NotImplementedError("Live XNAV requires X-ray detector")

    def _read_from_world(self) -> LayerReading:
        """Compute position from pulsar timing residuals.

        Each pulsar gives a timing residual that encodes position through
        the relationship:
            residual = A·sin(lat − dec) + B·cos(lon − ra) + noise
        We invert this system using least-squares over all tracked pulsars.
        """
        pulsars = self.world.get_pulsar_timing()
        if len(pulsars) < 2:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "INSUFFICIENT_PULSARS",
                          "pulsars_tracked": len(pulsars),
                          "unjammable": True},
            )

        # Iterative solver: linearise residual model around current guess
        lat_est = (self._last_lat if self._last_lat is not None
                   else self.world.true_lat)
        lon_est = (self._last_lon if self._last_lon is not None
                   else self.world.true_lon)

        for _iteration in range(8):
            H = []
            obs = []
            for p in pulsars:
                dec = p["dec_deg"]
                ra = p["ra_deg"]
                # Predicted residual at current estimate
                predicted = (10.0 * math.sin(math.radians(lat_est - dec)) +
                             10.0 * math.cos(math.radians(lon_est - ra)))
                # Partial derivatives
                d_lat = 10.0 * math.cos(math.radians(lat_est - dec)) * math.radians(1.0)
                d_lon = -10.0 * math.sin(math.radians(lon_est - ra)) * math.radians(1.0)
                H.append([d_lat, d_lon])
                obs.append(p["residual_ns"] - predicted)

            H_arr = np.array(H)
            obs_arr = np.array(obs)
            try:
                delta = np.linalg.lstsq(H_arr, obs_arr, rcond=None)[0]
                lat_est += delta[0]
                lon_est += delta[1]
                if abs(delta[0]) < 1e-6 and abs(delta[1]) < 1e-6:
                    break
            except np.linalg.LinAlgError:
                break

        alt_est = (self._last_alt if self._last_alt is not None
                   else self.world.true_alt)

        self._last_lat = lat_est
        self._last_lon = lon_est
        self._last_alt = alt_est

        pos = Position(
            latitude=lat_est, longitude=lon_est, altitude=alt_est,
            accuracy_m=100.0, timestamp=time.time(),
        )
        return LayerReading(
            layer_id=self.layer_id, position=pos,
            self_confidence=0.7,
            raw_data={"pulsars_tracked": len(pulsars), "unjammable": True},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt


class StellarConstellationLayer(NavigationLayer):
    """Layer 46 — Stellar Constellation Pattern Navigation [NOVEL].

    Star constellation pattern recognition for heading and direction.
    Inspired by the Bogong moth (confirmed Nature, June 2025).
    More robust than single-star tracking.

    Physics chain:
        world.get_star_positions() → star pattern matching → heading
    This is a heading-only layer; it does not produce a position fix.
    """

    def __init__(self):
        super().__init__(
            layer_id="stellar_l46",
            layer_number=46,
            name="Stellar Constellation Pattern Navigation",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Bogong moth stellar navigation",
            description="Star pattern recognition for heading determination",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.65

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()

            # Legacy fallback
            true_heading = getattr(self, '_sim_heading', 45.0)
            heading = true_heading + np.random.normal(0, 2.0)
            return LayerReading(
                layer_id=self.layer_id, heading=heading % 360,
                self_confidence=0.8,
                raw_data={"constellations_matched": 5, "sky_visible": True},
            )
        raise NotImplementedError("Live stellar nav requires star tracker")

    def _read_from_world(self) -> LayerReading:
        """Derive heading from observed star positions.

        Strategy: compare measured azimuths of known stars against their
        catalogue azimuths predicted for a reference heading of 0°.  The
        mean offset gives the platform heading.
        """
        stars = self.world.get_star_positions()
        if len(stars) < 2:
            return LayerReading(
                layer_id=self.layer_id, is_valid=False,
                raw_data={"status": "INSUFFICIENT_STARS",
                          "sky_visible": False},
            )

        # Each star's measured azimuth encodes the platform heading.
        # The catalogue azimuth at heading=0 is just the RA-based value.
        # Measured azimuth = catalogue_azimuth + true_heading + noise
        # so heading ≈ mean(measured_az - catalogue_az).
        heading_estimates = []
        for star in stars:
            # Catalogue azimuth at heading=0 (same formula as world but
            # without heading rotation — the world already provides the
            # measured value which includes the implicit heading offset).
            catalogue_az = (star["ra_deg"] - self.world.elapsed * 0.25) % 360
            measured_az = star["measured_azimuth_deg"]
            diff = (measured_az - catalogue_az + 180) % 360 - 180
            heading_estimates.append(diff)

        # Robust mean: reject outliers beyond 2σ
        estimates = np.array(heading_estimates)
        median = np.median(estimates)
        mad = np.median(np.abs(estimates - median))
        if mad > 0:
            inliers = estimates[np.abs(estimates - median) < 3 * mad]
            if len(inliers) > 0:
                estimates = inliers

        heading = float(np.mean(estimates)) % 360

        # Add small sensor noise (star tracker jitter)
        heading = (heading + np.random.normal(0, 0.5)) % 360

        return LayerReading(
            layer_id=self.layer_id, heading=heading,
            self_confidence=min(0.9, 0.5 + 0.1 * len(stars)),
            raw_data={"constellations_matched": len(stars),
                      "sky_visible": True},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt
        self._sim_heading = 45.0


class DiffuseSkyLayer(NavigationLayer):
    """Layer 47 — Diffuse Sky Brightness Gradient Navigation [NOVEL].

    Night sky brightness gradient including Milky Way diffuse light
    for heading derivation. Inspired by dung beetle Milky Way navigation.
    Works when individual stars are not identifiable.

    Physics chain:
        world.true_heading + sensor noise → heading
    Lowest accuracy heading source but works in poor visibility.
    """

    def __init__(self):
        super().__init__(
            layer_id="skygrad_l47",
            layer_number=47,
            name="Diffuse Sky Brightness Gradient Navigation",
            group=LayerGroup.A_SATELLITE_CELESTIAL,
            capabilities=[LayerCapability.HEADING],
            is_novel=True,
            bio_inspiration="Dung beetle Milky Way navigation",
            description="Sky brightness gradient for heading",
        )

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.5  # Lower accuracy, useful as backup

    def read(self) -> LayerReading:
        if self._simulated:
            if self.world is not None:
                return self._read_from_world()

            # Legacy fallback
            true_heading = getattr(self, '_sim_heading', 45.0)
            heading = true_heading + np.random.normal(0, 5.0)
            return LayerReading(
                layer_id=self.layer_id, heading=heading % 360,
                self_confidence=0.6,
                raw_data={"gradient_detected": True, "night_sky": True},
            )
        raise NotImplementedError("Live sky gradient requires camera")

    def _read_from_world(self) -> LayerReading:
        """Derive heading from diffuse sky brightness gradient.

        The Milky Way band provides a broad directional cue.  We model
        the sensor as observing the true heading with significant Gaussian
        noise (~5°), reflecting the low angular resolution of gradient-based
        sensing.
        """
        heading = self.world.true_heading + np.random.normal(0, 5.0)
        heading = heading % 360

        return LayerReading(
            layer_id=self.layer_id, heading=heading,
            self_confidence=0.6,
            raw_data={"gradient_detected": True, "night_sky": True},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 10.0):
        self._sim_lat = lat
        self._sim_lon = lon
        self._sim_alt = alt
        self._sim_heading = 45.0
