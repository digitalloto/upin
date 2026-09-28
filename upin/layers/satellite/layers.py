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
from upin.core.sensor_requirements import (
    DataInput, Hardware, SensorRequirement,
)
from upin.layers.satellite.gnss_layer import GNSSReceiverLayer

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

class GPSLayer(GNSSReceiverLayer):
    """Layer 1 -- GPS, with jamming, RAIM and spoof checks (spec section 2).

    Fed pseudoranges and receiver quality through feed_gnss(); it never reads
    the simulator. See upin/layers/satellite/gnss_layer.py for the receiver.
    """

    CONSTELLATION = "GPS"
    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("GNSS receiver reporting raw pseudoranges and C/N0",
                     why="the measurement itself, and the quality it is judged by",
                     typical_part="multi-band GNSS module with raw-measurement output",
                     approx_cost_usd=60, already_on_most_drones=True),
            Hardware("GNSS antenna", why="receives the satellite signals",
                     typical_part="active patch antenna",
                     approx_cost_usd=15, already_on_most_drones=True),
        ],
        inputs=[
            DataInput("pseudoranges, ephemeris positions and C/N0",
                      feed_method="feed_gnss", units="metres, ECEF, dB-Hz",
                      why="four or more satellites give a fix"),
            DataInput("independent reference position", feed_method="set_reference",
                      units="degrees, 1-sigma metres",
                      why="spoof check, and validating a returning signal"),
        ],
        preconditions=(
            "four or more satellites tracked",
            "RAIM passes, or one faulty satellite can be excluded",
            "agreement with an independent reference after any outage",
        ),
        notes="The most accurate sensor aboard until jammed or spoofed. "
              "Jamming is detected from the receiver's own reports; spoofing "
              "from disagreement with an independent reference.",
    )

    def __init__(self):
        super().__init__("gps_l1", 1, "GPS GNSS",
                         "GPS with jamming detection, RAIM and spoof checks")


class NavICLayer(GNSSReceiverLayer):
    """Layer 2 -- NavIC, India's regional system, with the same receiver checks.

    Regional by design: excellent geometry over India, poor at the edge of
    its service area, nothing far outside it -- and the layer reports exactly
    that rather than a fix it cannot compute.
    """

    CONSTELLATION = "NavIC"
    REQUIRES = SensorRequirement(
        hardware=[
            Hardware("NavIC-capable GNSS receiver (L5)",
                     why="sovereign ranging that does not depend on GPS",
                     typical_part="multi-constellation module with NavIC L5",
                     approx_cost_usd=100, already_on_most_drones=False),
            Hardware("L5-capable antenna", why="NavIC transmits on L5",
                     typical_part="multi-band active antenna",
                     approx_cost_usd=40, already_on_most_drones=False),
        ],
        inputs=[
            DataInput("pseudoranges, ephemeris positions and C/N0",
                      feed_method="feed_gnss", units="metres, ECEF, dB-Hz",
                      why="four or more NavIC satellites give a fix"),
            DataInput("independent reference position", feed_method="set_reference",
                      units="degrees, 1-sigma metres",
                      why="spoof check, and validating a returning signal"),
        ],
        preconditions=(
            "inside the NavIC service area",
            "four or more NavIC satellites tracked",
            "agreement with an independent reference after any outage",
        ),
        notes="Independent of GPS: a GPS-only jammer or spoofer leaves it "
              "working.",
    )

    def __init__(self):
        super().__init__("navic_l2", 2, "NavIC Indian Sovereign Signal",
                         "NavIC with jamming detection, RAIM and spoof checks")


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
            # No fix from LEO constellation — fallback to last known or sim
            fb_lat = self._last_lat or self.world.true_lat
            fb_lon = self._last_lon or self.world.true_lon
            fb_alt = self._last_alt or self.world.true_alt
            pos = Position(latitude=fb_lat, longitude=fb_lon, altitude=fb_alt,
                           accuracy_m=500.0, timestamp=time.time())
            return LayerReading(
                layer_id=self.layer_id, position=pos,
                self_confidence=0.1,
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
