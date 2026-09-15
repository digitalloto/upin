"""
Group Q — Quantum Navigation Layers.

UPIN's claim to being the first quantum navigation *system*, as distinct from
a platform that carries quantum sensors, rests on this group. The difference
is not marketing. It is architectural:

  A quantum sensor  is quantum inside and classical outside. It produces a
                    number. The number is fused classically with every other
                    number. The quantum advantage stops at the enclosure wall.

  A quantum system  entangles its sensors with one another, distributes those
                    correlations across the platform or the swarm, and lets
                    the fusion itself exploit them. The advantage scales with
                    the number of nodes.

Eight layers implement that:

  Q1  Entangled Photon Ranging       unspoofable range — no-cloning enforced
  Q2  Distributed Quantum Sensing    sqrt(N) precision across an entangled swarm
  Q3  Quantum Clock Network          Heisenberg-limited time sync for TDOA
  Q4  Atom Interferometer Gyroscope  ~10^11 per-particle Sagnac advantage
  Q5  Squeezed Light Interferometry  sub-shot-noise inertial displacement
  Q6  Quantum Illumination Radar     6 dB detection gain against stealth
  Q7  Quantum-Secured Position       QKD-authenticated position exchange
  Q8  Quantum-Enhanced Fusion        Grover map matching + QAOA layer weights

Every layer degrades gracefully to a classical equivalent when entanglement
is unavailable, because on any real mission it frequently will be.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional

import numpy as np

from upin.core.layer_base import (
    LayerCapability, LayerGroup, LayerReading, NavigationLayer,
)
from upin.core.position import Position
from upin.quantum.algorithms import GroverPositionSearch, QAOALayerWeights, QuantumRNG
from upin.quantum.entanglement import (
    EntanglementDistributor, GHZNetwork, no_cloning_verification,
)
from upin.quantum.metrology import (
    M_CS133, ProbeState, matter_wave_advantage, optimal_entanglement_size,
    phase_uncertainty, quantum_illumination_advantage, sagnac_phase_matter_wave,
    sagnac_phase_optical, spin_squeezing,
)
from upin.quantum.qkd import QKDMeshNetwork

DEG_M = 111_320.0


def _base_position(layer: NavigationLayer) -> tuple[float, float, float]:
    """Truth source for simulation: the world if present, else the sim anchor."""
    if layer.world is not None:
        return (layer.world.true_lat, layer.world.true_lon, layer.world.true_alt)
    return (getattr(layer, "_sim_lat", 13.0827),
            getattr(layer, "_sim_lon", 80.2707),
            getattr(layer, "_sim_alt", 100.0))


# =====================================================================
# Q1 — Entangled Photon Ranging
# =====================================================================

class EntangledPhotonRangingLayer(NavigationLayer):
    """Layer 135 — ranging that cannot be spoofed, by physics.

    Every classical ranging scheme shares one weakness: the signal can be
    copied. A spoofer records it, delays it, replays it stronger, and the
    receiver believes the false range. GPS spoofing is exactly this attack.

    Entangled photon ranging closes it. Half of each entangled pair is kept
    at the transmitter; the other half goes to the target and back. Timing
    correlations between the two halves give the range. An adversary who
    intercepts must measure — and the no-cloning theorem guarantees no
    measurement reproduces the state. The optimal universal cloner is capped
    at fidelity 5/6, so an intercept-resend attack cannot push measured
    fidelity above 0.833. The receiver sees that ceiling and knows.

    This is the first ranging method in UPIN where spoofing is not merely
    detected after the fact but forbidden in advance.
    """

    def __init__(self):
        super().__init__(
            layer_id="qrange_q01", layer_number=135,
            name="Entangled Photon Ranging",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.POSITION, LayerCapability.TIMING],
            is_novel=True,
            description="Unspoofable ranging enforced by the no-cloning theorem",
        )
        self._dist = EntanglementDistributor(source_rate_hz=1e7, t2_coherence_s=0.5)
        self._anchors: List[str] = []
        self._intercepts = 0
        self._measurements = 0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._dist.register_node("SELF", 0.0, 0.0, 0.0)
        return True

    def get_accuracy_rating(self) -> float:
        return 0.95

    def register_anchor(self, anchor_id: str, lat: float, lon: float, alt: float = 0.0):
        self._dist.register_node(anchor_id, lat, lon, alt)
        if anchor_id not in self._anchors:
            self._anchors.append(anchor_id)

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)
        self._dist._nodes["SELF"] = (lat, lon, alt)

        if not self._anchors:
            for i, (dlat, dlon) in enumerate(
                    [(0.01, 0.0), (-0.008, 0.006), (0.002, -0.011), (-0.004, -0.009)]):
                self.register_anchor(f"QA{i:02d}", lat + dlat, lon + dlon, alt)

        ranges, fidelities, expected_fids, intercepted = [], [], [], False
        for anchor in self._anchors:
            pairs = self._dist.distribute("SELF", anchor, count=64)
            if not pairs:
                continue
            f = float(np.mean([p.fidelity for p in pairs]))
            fidelities.append(f)
            # What this channel should deliver given its loss — the baseline
            # the no-cloning test compares against. Comparing to a fixed ideal
            # would flag every long link as an attack.
            ax, ay, az = self._dist._nodes[anchor]
            sep = self._dist._separation("SELF", anchor)
            expected_fids.append(0.25 + 0.74 * self._dist.channel_transmission(sep))
            # Timing precision improves with the square root of usable pairs
            sigma_m = 0.30 / math.sqrt(max(1, len(pairs)))
            ax, ay, _ = self._dist._nodes[anchor]
            true_r = math.hypot((lat - ax) * DEG_M,
                                (lon - ay) * DEG_M * math.cos(math.radians(lat)))
            ranges.append((anchor, true_r + np.random.normal(0, sigma_m), sigma_m))

        if len(ranges) < 3:
            return self._degraded(lat, lon, alt, "insufficient_entanglement")

        mean_f = float(np.mean(fidelities))
        mean_expected = float(np.mean(expected_fids)) if expected_fids else 0.97
        verdict = no_cloning_verification(mean_f, expected_fidelity=mean_expected)
        if verdict["interception_detected"]:
            self._intercepts += 1
            intercepted = True

        # Range-weighted trilateration onto the anchor set
        wsum = lat_s = lon_s = 0.0
        for anchor, r, sig in ranges:
            ax, ay, _ = self._dist._nodes[anchor]
            w = 1.0 / max(sig, 1e-6) ** 2
            lat_s += ax * w
            lon_s += ay * w
            wsum += w
        est_lat = lat + (lat - lat_s / wsum) * 0.02 + np.random.normal(0, 3e-8)
        est_lon = lon + (lon - lon_s / wsum) * 0.02 + np.random.normal(0, 3e-8)

        accuracy = float(np.mean([s for _, _, s in ranges])) * 2.0
        self._measurements += 1
        self._dist.prune()

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=est_lat, longitude=est_lon, altitude=alt,
                              accuracy_m=accuracy, timestamp=time.time()),
            self_confidence=0.15 if intercepted else min(0.97, mean_f),
            is_valid=True,
            raw_data={
                "anchors_ranged": len(ranges),
                "mean_bell_fidelity": round(mean_f, 4),
                "expected_channel_fidelity": round(mean_expected, 4),
                "range_sigma_m": round(accuracy / 2.0, 4),
                "no_cloning_verdict": verdict["verdict"],
                "interception_detected": intercepted,
                "cloner_fidelity_ceiling": verdict["optimal_cloner_limit"],
                "spoofing_physically_forbidden": not intercepted,
                "total_intercepts": self._intercepts,
            },
        )

    def _degraded(self, lat, lon, alt, reason) -> LayerReading:
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=lat, longitude=lon, altitude=alt,
                              accuracy_m=50.0, timestamp=time.time()),
            self_confidence=0.1, is_valid=True,
            raw_data={"status": reason, "fallback": "classical_timing"},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q2 — Distributed Quantum Sensing Network
# =====================================================================

class DistributedQuantumSensingLayer(NavigationLayer):
    """Layer 136 — sqrt(N) precision gain across an entangled swarm.

    Fifty drones each carrying a magnetometer, measuring independently,
    average their errors down as 1/sqrt(50) — a factor of 7.

    Fifty drones sharing a GHZ state measure the field *collectively*. The
    phase accumulates coherently across all fifty, so the estimate improves
    as 1/50 — a further factor of 7 on top, for free, with no extra hardware.

    The catch is honest and modelled here: an N-body GHZ state dephases N
    times faster. The layer solves for the block size that actually minimises
    uncertainty given the coherence time, splits the swarm into that many
    independent blocks, and averages across them. That is the real optimum,
    not the textbook one.
    """

    def __init__(self, sensor_type: str = "magnetometer"):
        super().__init__(
            layer_id="qsense_q02", layer_number=136,
            name="Distributed Quantum Sensing Network",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.POSITION, LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="Entangled multi-node sensing beyond the standard quantum limit",
        )
        self._sensor_type = sensor_type
        self._dist = EntanglementDistributor(source_rate_hz=5e6, t2_coherence_s=0.20)
        self._ghz = GHZNetwork(self._dist)
        self._nodes: List[str] = []
        self._t_interrogate = 0.010
        self._best_advantage = 1.0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.88

    def register_swarm(self, node_ids: List[str], positions: List[tuple]):
        self._nodes = list(node_ids)
        for nid, (lat, lon, alt) in zip(node_ids, positions):
            self._dist.register_node(nid, lat, lon, alt)

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)

        if not self._nodes:
            self.register_swarm(
                [f"QN{i:02d}" for i in range(12)],
                [(lat + np.random.normal(0, 0.0005),
                  lon + np.random.normal(0, 0.0005), alt) for _ in range(12)])

        n = len(self._nodes)

        # Measure what this swarm's links actually deliver after purification,
        # then size the GHZ blocks for that — not for an ideal channel.
        probe = self._dist.distribute(self._nodes[0], self._nodes[1], count=16)
        raw_f = float(np.mean([p.fidelity for p in probe])) if probe else 0.8
        purified_f = raw_f
        for _ in range(2):
            g = raw_f
            num = purified_f * g + ((1 - purified_f) / 3) * ((1 - g) / 3)
            den = (purified_f * g + purified_f * (1 - g) / 3
                   + g * (1 - purified_f) / 3
                   + 5 * ((1 - purified_f) / 3) * ((1 - g) / 3))
            if den > 0:
                purified_f = min(0.999, num / den)
        for p in probe:
            p.consumed = True

        plan = optimal_entanglement_size(
            t2_s=self._dist._t2,
            interrogation_time_s=self._t_interrogate,
            n_available=n, state=ProbeState.GHZ,
            link_fidelity=purified_f)

        block = max(2, plan["optimal_block_size"])
        blocks = [self._nodes[i:i + block] for i in range(0, n, block)]
        blocks = [b for b in blocks if len(b) >= 2]

        estimates, sigmas = [], []
        for grp in blocks:
            st = self._ghz.create(grp)
            if st is None:
                continue
            true_phase = 0.4 * math.sin(lat * 13.0) + 0.3 * math.cos(lon * 9.0)
            m = self._ghz.measure(st["ghz_id"], true_phase)
            if m:
                estimates.append(m["phase_estimate_rad"])
                sigmas.append(m["uncertainty_rad"])

        if not estimates:
            return self._classical_fallback(lat, lon, alt, n)

        w = 1.0 / np.array(sigmas) ** 2
        combined_sigma = float(1.0 / math.sqrt(w.sum()))
        sql = 1.0 / math.sqrt(n)
        advantage = sql / combined_sigma if combined_sigma > 0 else 1.0
        self._best_advantage = max(self._best_advantage, advantage)

        # Better phase resolution maps directly to a tighter position fix
        accuracy = max(0.05, 8.0 * combined_sigma)
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(
                latitude=lat + np.random.normal(0, accuracy / DEG_M),
                longitude=lon + np.random.normal(0, accuracy / DEG_M),
                altitude=alt, accuracy_m=accuracy, timestamp=time.time()),
            self_confidence=min(0.95, 0.55 + 0.1 * advantage),
            is_valid=True,
            raw_data={
                "sensor_type": self._sensor_type,
                "swarm_nodes": n,
                "ghz_block_size": block,
                "blocks_measured": len(estimates),
                "combined_sigma_rad": round(combined_sigma, 8),
                "sql_sigma_rad": round(sql, 8),
                "advantage_over_sql": round(advantage, 3),
                "beats_sql": combined_sigma < sql,
                "link_fidelity_raw": round(raw_f, 4),
                "link_fidelity_purified": round(purified_f, 4),
                "limited_by": ("link_fidelity" if purified_f < 0.9
                               else "decoherence" if block < n else "swarm_size"),
                "effective_t2_s": round(self._dist._t2 / block, 5),
            },
        )

    def _classical_fallback(self, lat, lon, alt, n) -> LayerReading:
        acc = 8.0 / math.sqrt(max(1, n))
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=lat, longitude=lon, altitude=alt,
                              accuracy_m=acc, timestamp=time.time()),
            self_confidence=0.45, is_valid=True,
            raw_data={"status": "entanglement_unavailable",
                      "fallback": "classical_averaging",
                      "advantage_over_sql": 1.0, "swarm_nodes": n},
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q3 — Quantum Clock Network
# =====================================================================

class QuantumClockNetworkLayer(NavigationLayer):
    """Layer 137 — entangled clock synchronisation for TDOA positioning.

    Every time-difference-of-arrival fix in UPIN — acoustic beacons, eLORAN,
    OTDOA, universal beacons — is limited by how well the receivers agree on
    time. One nanosecond of clock error is thirty centimetres of position
    error, and it is a systematic error that no amount of averaging removes.

    Entangled clock networks (Komar et al. 2014) beat the standard quantum
    limit on synchronisation. The layer reports the position error floor its
    current sync quality implies, so the fusion engine can weight every
    TDOA-derived layer accordingly.
    """

    def __init__(self):
        super().__init__(
            layer_id="qclocknet_q03", layer_number=137,
            name="Quantum Clock Network",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.TIMING, LayerCapability.POSITION],
            is_novel=True,
            description="Entangled clock sync below the standard quantum limit",
        )
        self._dist = EntanglementDistributor(source_rate_hz=1e6, t2_coherence_s=1.0)
        self._ghz = GHZNetwork(self._dist)
        self._clocks: Dict[str, float] = {}
        self._sync_rounds = 0
        self._best_sync_ns = float("inf")

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.92

    def register_clock(self, node_id: str, lat: float, lon: float,
                       alt: float = 0.0, offset_ns: float = 0.0):
        self._dist.register_node(node_id, lat, lon, alt)
        self._clocks[node_id] = offset_ns

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)

        if not self._clocks:
            for i in range(8):
                self.register_clock(
                    f"QC{i:02d}",
                    lat + np.random.normal(0, 0.002),
                    lon + np.random.normal(0, 0.002), alt,
                    offset_ns=float(np.random.normal(0, 50.0)))

        nodes = list(self._clocks.keys())
        n = len(nodes)
        st = self._ghz.create(nodes)

        if st is None:
            sigma_ns = 50.0 / math.sqrt(n)
            mode, advantage = "classical_two_way", 1.0
        else:
            m = self._ghz.measure(st["ghz_id"], 0.0)
            # Phase uncertainty at the clock transition maps to timing jitter
            sigma_ns = max(0.001, m["uncertainty_rad"] * 8.0)
            mode = "entangled_ghz"
            advantage = m["advantage_over_sql"]
            for k in self._clocks:
                self._clocks[k] *= 0.25       # sync pulls offsets toward zero

        self._sync_rounds += 1
        self._best_sync_ns = min(self._best_sync_ns, sigma_ns)

        # 1 ns of sync error is ~0.3 m of TDOA position error
        pos_floor_m = sigma_ns * 0.2998
        residual = float(np.std(list(self._clocks.values()))) if self._clocks else 0.0

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(
                latitude=lat + np.random.normal(0, pos_floor_m / DEG_M),
                longitude=lon + np.random.normal(0, pos_floor_m / DEG_M),
                altitude=alt, accuracy_m=max(0.05, pos_floor_m),
                timestamp=time.time()),
            self_confidence=min(0.96, 0.6 + 0.08 * advantage),
            is_valid=True,
            raw_data={
                "clocks_in_network": n,
                "sync_mode": mode,
                "sync_uncertainty_ns": round(sigma_ns, 5),
                "tdoa_position_floor_m": round(pos_floor_m, 4),
                "residual_offset_std_ns": round(residual, 3),
                "advantage_over_sql": round(advantage, 3),
                "sync_rounds": self._sync_rounds,
                "best_sync_ns": round(self._best_sync_ns, 5),
                "improves_layers": ["acoustic_l10", "eloran_l41",
                                     "otdoa_d22", "univbeacon_k11"],
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q4 — Atom Interferometer Gyroscope
# =====================================================================

class AtomInterferometerGyroLayer(NavigationLayer):
    """Layer 138 — matter-wave Sagnac rotation sensing.

    The Sagnac phase for a matter wave is Δφ = 2 m Ω A / ħ. Because a caesium
    atom's rest energy vastly exceeds a telecom photon's energy, the
    per-particle sensitivity ratio m c² / ħω is of order 10^11.

    The practical consequence for UPIN is bias stability. A fibre-optic gyro
    drifts at roughly 0.01 deg/hr; an atom interferometer reaches 10^-5
    deg/hr or better. Heading drift is what ultimately destroys every dead-
    reckoning solution, so this layer is what lets the strapdown INS hold a
    heading for hours instead of minutes when every external signal is gone.
    """

    def __init__(self, enclosed_area_m2: float = 0.01):
        super().__init__(
            layer_id="atomgyro_q04", layer_number=138,
            name="Atom Interferometer Gyroscope",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.HEADING, LayerCapability.VELOCITY],
            is_novel=True,
            is_underwater=True,
            description="Matter-wave Sagnac gyroscope — ~10^11 per-particle advantage",
        )
        self._area = enclosed_area_m2
        self._mass = M_CS133
        self._n_atoms = 1_000_000
        self._t_interrogate = 0.5
        self._heading_deg = 0.0
        self._accumulated_drift_deg = 0.0
        self._reads = 0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._accumulated_drift_deg = 0.0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.96

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)
        self._reads += 1

        omega_true = math.radians(
            self.world.true_heading if self.world is not None else 0.0) * 0.0
        earth_rate = 7.292115e-5 * math.sin(math.radians(lat))
        omega_total = omega_true + earth_rate

        phi = sagnac_phase_matter_wave(omega_total, self._area, self._mass)

        # Squeezed atomic ensemble beats the atom shot-noise limit
        sq = spin_squeezing(self._n_atoms, variance_reduction=0.1, coherence=0.95)
        res = phase_uncertainty(
            self._n_atoms, ProbeState.SPIN_SQUEEZED,
            repetitions=1, interrogation_time_s=self._t_interrogate,
            t2_s=2.0, squeezing_xi2=sq.xi_squared)

        dphi = res.phase_uncertainty_rad
        d_omega = dphi * abs(2.0 * self._mass * self._area / 1.054571817e-34) ** -1
        drift_deg_hr = math.degrees(d_omega) * 3600.0

        self._accumulated_drift_deg += drift_deg_hr / 3600.0
        self._heading_deg = (
            (self.world.true_heading if self.world is not None else 45.0)
            + self._accumulated_drift_deg) % 360.0

        optical_dphi = sagnac_phase_optical(omega_total, self._area)
        ratio = matter_wave_advantage(self._mass)

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=lat, longitude=lon, altitude=alt,
                              heading=self._heading_deg, accuracy_m=1.0,
                              timestamp=time.time()),
            heading=self._heading_deg,
            self_confidence=0.94,
            is_valid=True,
            raw_data={
                "sagnac_phase_rad": float(phi),
                "optical_equivalent_rad": float(optical_dphi),
                "per_particle_advantage": f"{ratio:.3e}",
                "atoms": self._n_atoms,
                "squeezing_db": round(sq.squeezing_db, 2),
                "phase_uncertainty_rad": float(dphi),
                "bias_drift_deg_per_hr": float(f"{drift_deg_hr:.3e}"),
                "accumulated_drift_deg": round(self._accumulated_drift_deg, 8),
                "earth_rate_rad_s": earth_rate,
                "beats_shot_noise": res.is_beating_sql,
                "fog_equivalent_drift_deg_hr": 0.01,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q5 — Squeezed Light Interferometry
# =====================================================================

class SqueezedLightInterferometryLayer(NavigationLayer):
    """Layer 139 — sub-shot-noise displacement sensing.

    Shot noise is not a hardware defect. It is the vacuum fluctuation floor
    of the electromagnetic field, and no amount of engineering removes it —
    but squeezed vacuum redistributes it. Push uncertainty into the phase
    quadrature you do not care about and the amplitude quadrature you do care
    about gets quieter.

    LIGO has run 3-6 dB of squeezing since 2019 to detect sub-proton
    displacements. The same technique applied to an onboard interferometer
    gives displacement sensing far below the classical floor, which feeds the
    INS directly.
    """

    def __init__(self, squeezing_db: float = 6.0, wavelength_nm: float = 1064.0):
        super().__init__(
            layer_id="qsqueeze_q05", layer_number=139,
            name="Squeezed Light Interferometry",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.POSITION, LayerCapability.VELOCITY],
            is_novel=True,
            description="Sub-shot-noise interferometric displacement sensing",
        )
        self._squeeze_db = squeezing_db
        self._wavelength = wavelength_nm * 1e-9
        self._photon_rate = 1e15
        self._integration_s = 0.001
        self._cum_disp_m = 0.0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._cum_disp_m = 0.0
        return True

    def get_accuracy_rating(self) -> float:
        return 0.93

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)

        n_photons = self._photon_rate * self._integration_s
        shot_noise_rad = 1.0 / math.sqrt(n_photons)
        squeeze_factor = 10.0 ** (-self._squeeze_db / 20.0)
        squeezed_rad = shot_noise_rad * squeeze_factor

        # Phase to displacement: δx = δφ λ / 4π
        disp_classical = shot_noise_rad * self._wavelength / (4 * math.pi)
        disp_squeezed = squeezed_rad * self._wavelength / (4 * math.pi)

        velocity = self.world.true_velocity if self.world is not None else 0.0
        measured = velocity * self._integration_s + np.random.normal(0, disp_squeezed)
        self._cum_disp_m += abs(measured)

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(
                latitude=lat + np.random.normal(0, disp_squeezed / DEG_M),
                longitude=lon + np.random.normal(0, disp_squeezed / DEG_M),
                altitude=alt, accuracy_m=max(1e-12, disp_squeezed * 3),
                timestamp=time.time()),
            velocity=measured / max(self._integration_s, 1e-9),
            self_confidence=0.91,
            is_valid=True,
            raw_data={
                "squeezing_db": self._squeeze_db,
                "photons_per_measurement": f"{n_photons:.2e}",
                "shot_noise_phase_rad": f"{shot_noise_rad:.3e}",
                "squeezed_phase_rad": f"{squeezed_rad:.3e}",
                "displacement_classical_m": f"{disp_classical:.3e}",
                "displacement_squeezed_m": f"{disp_squeezed:.3e}",
                "improvement_factor": round(1.0 / squeeze_factor, 3),
                "cumulative_displacement_m": round(self._cum_disp_m, 9),
                "beats_shot_noise": True,
                "reference": "LIGO runs 3-6 dB since O3",
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q6 — Quantum Illumination Radar
# =====================================================================

class QuantumIlluminationRadarLayer(NavigationLayer):
    """Layer 140 — 6 dB detection gain against low-observable targets.

    Quantum illumination keeps one half of an entangled pair and sends the
    other to probe the scene. The channel is so lossy and noisy that the
    entanglement itself is completely destroyed — and yet joint measurement
    of the retained and returned modes still beats any classical transmitter
    of the same energy by 6 dB in the error exponent (Tan et al. 2008).

    That is the counter-intuitive part and also the operationally useful one:
    the advantage appears precisely in the regime that defines stealth
    detection — weak return, bright background, low transmit power. A
    quantum illumination radar also transmits so little energy that it is
    itself hard to detect, which matters under EMCON.
    """

    def __init__(self):
        super().__init__(
            layer_id="qradar_q06", layer_number=140,
            name="Quantum Illumination Radar",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.THREAT_DETECT, LayerCapability.ENVIRONMENT],
            is_novel=True,
            description="Entangled-probe detection with 6 dB gain over classical radar",
        )
        self._signal_photons = 0.01
        self._background_photons = 20.0
        self._detections = 0
        self._tracks: List[Dict] = []

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        self._tracks = []
        return True

    def get_accuracy_rating(self) -> float:
        return 0.85

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)

        self._tracks = []
        n_targets = int(np.random.choice([0, 0, 1, 1, 2], p=[.35, .25, .2, .13, .07]))
        for i in range(n_targets):
            reflectivity = float(np.random.choice([0.001, 0.01, 0.05],
                                                  p=[0.4, 0.4, 0.2]))
            qi = quantum_illumination_advantage(
                self._signal_photons, self._background_photons, reflectivity)
            detectable_classically = qi["classical_snr"] > 0.01
            self._tracks.append({
                "track_id": f"QI-{self._detections + i:04d}",
                "bearing_deg": round(float(np.random.uniform(0, 360)), 1),
                "range_m": round(float(np.random.uniform(500, 8000))),
                "reflectivity": reflectivity,
                "classification": ("stealth" if reflectivity < 0.005
                                   else "low_observable" if reflectivity < 0.02
                                   else "conventional"),
                "advantage_db": round(qi["advantage_db"], 2),
                "classical_would_miss": not detectable_classically,
                "requires_iff": True,
                "requires_human_auth": True,
            })
        self._detections += n_targets

        qi_ref = quantum_illumination_advantage(
            self._signal_photons, self._background_photons, 0.01)
        missed = sum(1 for t in self._tracks if t["classical_would_miss"])

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=lat, longitude=lon, altitude=alt,
                              accuracy_m=25.0, timestamp=time.time()),
            self_confidence=0.82,
            is_valid=True,
            raw_data={
                "targets_detected": n_targets,
                "stealth_targets_found": missed,
                "advantage_db": round(qi_ref["advantage_db"], 2),
                "in_optimal_regime": qi_ref["in_optimal_regime"],
                "signal_photons_per_mode": self._signal_photons,
                "background_photons_per_mode": self._background_photons,
                "transmit_power_low_probability_of_intercept": True,
                "tracks": self._tracks,
                "total_detections": self._detections,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q7 — Quantum-Secured Position Exchange
# =====================================================================

class QuantumSecuredPositionLayer(NavigationLayer):
    """Layer 141 — position sharing that survives a quantum adversary.

    Cooperative positioning only works if the shared positions are true.
    Classical authentication rests on computational hardness, which a
    sufficiently large quantum computer dissolves — and which harvest-now-
    decrypt-later collection already undermines today.

    This layer carries swarm position exchange over QKD. Keys come from
    physics; an eavesdropper raises the error rate and is caught before any
    key is used. Combined with the no-cloning ranging of Q1, a swarm can
    establish mutual positions that an adversary can neither read nor forge.
    """

    def __init__(self, protocol: str = "BB84"):
        super().__init__(
            layer_id="qsecpos_q07", layer_number=141,
            name="Quantum-Secured Position Exchange",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="QKD-authenticated cooperative positioning",
        )
        self._qkd = QKDMeshNetwork(protocol=protocol)
        self._peers: Dict[str, tuple] = {}
        self._verified = 0
        self._rejected = 0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.86

    def register_peer(self, peer_id: str, lat: float, lon: float, alt: float = 0.0):
        self._peers[peer_id] = (lat, lon, alt)

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)

        if not self._peers:
            for i in range(5):
                self.register_peer(
                    f"QP{i:02d}",
                    lat + np.random.normal(0, 0.001),
                    lon + np.random.normal(0, 0.001), alt)

        verified, rejected = [], []
        for pid, (plat, plon, palt) in self._peers.items():
            # ~1 link in 12 is under attack in this scenario
            attacked = np.random.random() < 0.08
            key = self._qkd.establish("SELF", pid, eavesdropper=attacked)
            if key.is_secure:
                verified.append((pid, plat, plon, palt, key.qber))
                self._verified += 1
            else:
                rejected.append((pid, key.qber))
                self._rejected += 1

        if not verified:
            return LayerReading(
                layer_id=self.layer_id,
                position=Position(latitude=lat, longitude=lon, altitude=alt,
                                  accuracy_m=200.0, timestamp=time.time()),
                self_confidence=0.05, is_valid=True,
                raw_data={"status": "ALL_PEERS_COMPROMISED",
                          "peers_rejected": len(rejected),
                          "action": "ISOLATE_AND_USE_INTERNAL_LAYERS"})

        lat_s = float(np.mean([v[1] for v in verified]))
        lon_s = float(np.mean([v[2] for v in verified]))
        acc = max(1.0, 12.0 / math.sqrt(len(verified)))
        st = self._qkd.get_status()

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(
                latitude=lat * 0.85 + lat_s * 0.15,
                longitude=lon * 0.85 + lon_s * 0.15,
                altitude=alt, accuracy_m=acc, timestamp=time.time()),
            self_confidence=min(0.93, 0.5 + 0.09 * len(verified)),
            is_valid=True,
            raw_data={
                "peers_total": len(self._peers),
                "peers_verified": len(verified),
                "peers_rejected": len(rejected),
                "protocol": st["protocol"],
                "mean_qber": round(st["mean_qber"], 5),
                "key_bits_available": st["total_key_bits"],
                "eavesdropper_alerts": st["eavesdropper_alerts"],
                "security": "information_theoretic",
                "quantum_computer_resistant": True,
                "lifetime_verified": self._verified,
                "lifetime_rejected": self._rejected,
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt


# =====================================================================
# Q8 — Quantum-Enhanced Fusion
# =====================================================================

class QuantumEnhancedFusionLayer(NavigationLayer):
    """Layer 142 — quantum computation applied to UPIN's own fusion problem.

    The seven layers above use quantum physics to sense better. This one uses
    quantum computation to *fuse* better, and that is a separate claim.

    Two problems inside UPIN are natural fits:

      Map matching is unstructured search. The gravity, magnetic and
      bathymetric layers each scan a grid for the cell matching a
      measurement. Grover does that in O(sqrt(N)) — for a 40,000-cell grid,
      200 oracle calls instead of 20,000.

      Weight allocation across 129 layers under power and EMCON budgets is a
      constrained combinatorial optimisation. QAOA is built for exactly this
      shape of problem.

    Both run here as classical simulations that report the quantum call
    budget honestly. The interface is the one real hardware will use.
    """

    def __init__(self):
        super().__init__(
            layer_id="qfusion_q08", layer_number=142,
            name="Quantum-Enhanced Fusion",
            group=LayerGroup.Q_QUANTUM,
            capabilities=[LayerCapability.POSITION],
            is_novel=True,
            description="Grover map matching and QAOA weight allocation",
        )
        self._grover = GroverPositionSearch()
        self._qaoa = QAOALayerWeights(depth=3)
        self._qrng = QuantumRNG()
        self._searches = 0
        self._total_speedup = 0.0

    def initialize(self) -> bool:
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self) -> float:
        return 0.80

    def read(self) -> LayerReading:
        lat, lon, alt = _base_position(self)

        # Grover over a magnetic-anomaly grid
        if self.world is not None and hasattr(self.world, "get_magnetic_field"):
            measured = self.world.get_magnetic_field()["intensity_nt"]
            grid = {}
            for i in range(-30, 31):
                for j in range(-30, 31):
                    clat, clon = lat + i * 0.001, lon + j * 0.001
                    grid[(int(clat * 100), int(clon * 100))] = \
                        self.world.get_magnetic_field(clat, clon)["intensity_nt"]
            g = self._grover.search_grid(measured, grid, tolerance=5.0)
        else:
            grid_n = 3721
            g = {"found": True, "lat": lat, "lon": lon, "residual": 1.2,
                 "oracle_calls": self._grover.optimal_iterations(grid_n) + 1,
                 "classical_calls": grid_n // 2, "grid_size": grid_n,
                 "speedup": (grid_n // 2) / max(1, self._grover.optimal_iterations(grid_n) + 1)}

        self._searches += 1
        self._total_speedup += g.get("speedup", 1.0)

        # QAOA over a representative layer set
        scores = np.abs(np.random.normal(0.6, 0.2, 40))
        power = np.abs(np.random.normal(1.2, 0.5, 40))
        q = self._qaoa.optimise(scores, power, power_budget_w=25.0)

        health = self._qrng.health_check(sample_bits=2048)
        acc = max(0.5, g.get("residual", 5.0) * 2.0)

        return LayerReading(
            layer_id=self.layer_id,
            position=Position(
                latitude=g.get("lat", lat), longitude=g.get("lon", lon),
                altitude=alt, accuracy_m=acc, timestamp=time.time()),
            self_confidence=0.72,
            is_valid=True,
            raw_data={
                "grover_grid_size": g.get("grid_size"),
                "grover_oracle_calls": g.get("oracle_calls"),
                "grover_classical_calls": g.get("classical_calls"),
                "grover_speedup": round(g.get("speedup", 1.0), 1),
                "grover_residual_nt": round(g.get("residual", 0.0), 3),
                "mean_speedup": round(self._total_speedup / max(1, self._searches), 1),
                "qaoa_layers_active": q.layers_active,
                "qaoa_cost": round(q.cost, 4),
                "qaoa_evaluations": q.evaluations,
                "qrng_health_passed": health["passed"],
                "qrng_entropy_per_bit": round(health["shannon_entropy_per_bit"], 5),
                "complexity": "O(sqrt(N)) vs O(N) classical",
            },
        )

    def set_simulated_position(self, lat: float, lon: float, alt: float = 100.0):
        self._sim_lat, self._sim_lon, self._sim_alt = lat, lon, alt
