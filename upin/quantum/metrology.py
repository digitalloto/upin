"""
Quantum metrology — the physics that makes UPIN a quantum navigation system.

The central question of quantum metrology: given N probes, how precisely can
you estimate a phase (and therefore a rotation, a field, a distance, a time)?

  Separable probes   Δφ ≥ 1 / sqrt(ν N)        Standard Quantum Limit (SQL)
  Entangled probes   Δφ ≥ 1 / (N sqrt(ν))      Heisenberg Limit (HL)

The gap between them is a factor of sqrt(N). For a 50-node swarm carrying
entangled sensors that is a 7x precision gain over the same 50 sensors used
independently — obtained without adding a single gram of hardware.

Decoherence is the honest catch. An N-qubit GHZ state dephases N times faster
than a single qubit, so naive Heisenberg scaling is destroyed by any realistic
noise. Escher, de Matos Filho and Davidovich (Nature Physics 7, 406, 2011)
showed the true asymptotic limit under Markovian dephasing is N^(-3/4), not
N^(-1). This module models that honestly: it reports the achievable bound, not
the textbook ideal, and finds the optimal N for a given coherence time.

References (verify before external citation):
  Giovannetti, Lloyd, Maccone, Science 306, 1330 (2004)   — quantum metrology
  Wineland et al., Phys. Rev. A 46, R6797 (1992)          — spin squeezing
  Escher et al., Nature Physics 7, 406 (2011)             — noisy limit
  Braunstein & Caves, PRL 72, 3439 (1994)                 — quantum Fisher info
  Degen, Reinhard, Cappellaro, RMP 89, 035002 (2017)      — quantum sensing

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

HBAR = 1.054_571_817e-34          # J s
H_PLANCK = 6.626_070_15e-34       # J s
C_LIGHT = 299_792_458.0           # m/s
M_CS133 = 2.206_946_5e-25         # kg, caesium-133
M_RB87 = 1.443_160_6e-25          # kg, rubidium-87


class ProbeState:
    """Probe preparations available to a quantum sensor."""
    SEPARABLE = "separable"        # N independent probes -> SQL
    SPIN_SQUEEZED = "squeezed"     # partial entanglement, robust
    GHZ = "ghz"                    # maximal entanglement -> HL, fragile
    NOON = "noon"                  # photonic analogue of GHZ


@dataclass
class MetrologyResult:
    """Outcome of a precision calculation."""
    n_probes: int
    state: str
    phase_uncertainty_rad: float
    sql_uncertainty_rad: float
    heisenberg_uncertainty_rad: float
    quantum_advantage: float        # how many times better than SQL
    fisher_information: float
    decoherence_penalty: float      # 1.0 = none
    is_beating_sql: bool


def binary_entropy(p: float) -> float:
    """h(p) = -p log2 p - (1-p) log2(1-p)."""
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def quantum_fisher_information(n_probes: int, state: str,
                               squeezing_xi2: float = 1.0) -> float:
    """Quantum Fisher information for phase estimation.

    Braunstein & Caves: Δφ ≥ 1/sqrt(ν F_Q). Separable states are capped at
    F_Q = N; a GHZ state reaches F_Q = N². Spin squeezing interpolates
    between them as F_Q = N/ξ².
    """
    if n_probes < 1:
        return 0.0
    if state == ProbeState.SEPARABLE:
        return float(n_probes)
    if state in (ProbeState.GHZ, ProbeState.NOON):
        return float(n_probes) ** 2
    if state == ProbeState.SPIN_SQUEEZED:
        xi2 = max(1e-6, squeezing_xi2)
        return float(n_probes) / xi2
    return float(n_probes)


def dephasing_factor(n_probes: int, state: str,
                     interrogation_time_s: float, t2_s: float) -> float:
    """Loss of signal contrast from Markovian dephasing.

    A single probe decays as exp(-t/T2). An N-body GHZ state accumulates
    phase N times faster and therefore dephases N times faster — this is
    exactly why naive Heisenberg scaling does not survive contact with a
    real environment.
    """
    if t2_s <= 0:
        return 0.0
    n_eff = n_probes if state in (ProbeState.GHZ, ProbeState.NOON) else 1
    return float(np.exp(-n_eff * interrogation_time_s / t2_s))


def phase_uncertainty(n_probes: int, state: str, repetitions: int = 1,
                      interrogation_time_s: float = 0.0,
                      t2_s: float = float("inf"),
                      squeezing_xi2: float = 1.0) -> MetrologyResult:
    """Achievable phase uncertainty including decoherence.

    Δφ = 1 / (sqrt(ν F_Q) · contrast)
    """
    n_probes = max(1, int(n_probes))
    repetitions = max(1, int(repetitions))

    f_q = quantum_fisher_information(n_probes, state, squeezing_xi2)
    contrast = dephasing_factor(n_probes, state, interrogation_time_s, t2_s)
    contrast = max(contrast, 1e-12)

    delta_phi = 1.0 / (math.sqrt(repetitions * f_q) * contrast)
    sql = 1.0 / math.sqrt(repetitions * n_probes)
    hl = 1.0 / (n_probes * math.sqrt(repetitions))

    return MetrologyResult(
        n_probes=n_probes,
        state=state,
        phase_uncertainty_rad=delta_phi,
        sql_uncertainty_rad=sql,
        heisenberg_uncertainty_rad=hl,
        quantum_advantage=sql / delta_phi,
        fisher_information=f_q,
        decoherence_penalty=contrast,
        is_beating_sql=delta_phi < sql,
    )


def optimal_entanglement_size(t2_s: float, interrogation_time_s: float,
                              n_available: int,
                              state: str = ProbeState.GHZ,
                              link_fidelity: float = 1.0) -> Dict:
    """Find the entanglement block size that actually minimises Δφ.

    Three effects fight each other and the optimum is where they balance:

      gain          an N-body GHZ state resolves phase N times better
      dephasing     it also dephases N times faster
      construction  its fidelity is the product of N-1 link fidelities, so
                    it decays exponentially in N for any imperfect channel

    Pass the measured Bell-pair fidelity as `link_fidelity` to include the
    third effect. Leaving it at 1.0 gives the idealised answer, which is
    optimistic by a wide margin on any real link.
    """
    best_n, best_dphi, curve = 1, float("inf"), []
    for n in range(1, max(2, n_available + 1)):
        r = phase_uncertainty(n, state, repetitions=1,
                              interrogation_time_s=interrogation_time_s,
                              t2_s=t2_s)
        dphi = r.phase_uncertainty_rad
        if n > 1 and link_fidelity < 1.0:
            # star of n-1 links; fidelity multiplies, contrast divides
            build_contrast = max(1e-9, link_fidelity ** (n - 1))
            dphi = dphi / build_contrast
        curve.append((n, dphi))
        if dphi < best_dphi:
            best_n, best_dphi = n, dphi

    sql_all = 1.0 / math.sqrt(n_available)
    n_blocks = max(1, n_available // best_n)
    # independent blocks average down as sqrt(n_blocks)
    combined = best_dphi / math.sqrt(n_blocks)

    return {
        "optimal_block_size": best_n,
        "blocks": n_blocks,
        "block_uncertainty_rad": best_dphi,
        "combined_uncertainty_rad": combined,
        "sql_uncertainty_rad": sql_all,
        "advantage_over_sql": sql_all / combined if combined > 0 else 0.0,
        "beats_sql": combined < sql_all,
        "curve": curve[:64],
    }


@dataclass
class SqueezingResult:
    xi_squared: float
    squeezing_db: float
    is_useful: bool
    effective_probes: float


def spin_squeezing(n_atoms: int, variance_reduction: float,
                   coherence: float = 1.0) -> SqueezingResult:
    """Wineland squeezing parameter.

    ξ_R² = N ⟨ΔJ_⊥²⟩ / |⟨J⟩|².  ξ² < 1 means the state is metrologically
    useful: it behaves like N/ξ² independent atoms.
    """
    n_atoms = max(1, int(n_atoms))
    var = max(1e-9, variance_reduction)
    coh = min(1.0, max(1e-9, coherence))
    xi2 = var / (coh ** 2)
    return SqueezingResult(
        xi_squared=xi2,
        squeezing_db=-10.0 * math.log10(xi2) if xi2 > 0 else 0.0,
        is_useful=xi2 < 1.0,
        effective_probes=n_atoms / xi2,
    )


def sagnac_phase_matter_wave(rotation_rate_rad_s: float, area_m2: float,
                             mass_kg: float = M_CS133) -> float:
    """Matter-wave Sagnac phase: Δφ = 2 m Ω A / ħ."""
    return 2.0 * mass_kg * rotation_rate_rad_s * area_m2 / HBAR


def sagnac_phase_optical(rotation_rate_rad_s: float, area_m2: float,
                         wavelength_m: float = 1.55e-6) -> float:
    """Optical Sagnac phase: Δφ = 8π A Ω / (λ c)."""
    return 8.0 * math.pi * area_m2 * rotation_rate_rad_s / (wavelength_m * C_LIGHT)


def matter_wave_advantage(mass_kg: float = M_CS133,
                          wavelength_m: float = 1.55e-6) -> float:
    """Sensitivity ratio of a matter-wave gyro to an optical one.

    Per particle this is m c² / (ħ ω) ≈ 10^11 for caesium against telecom
    light — the reason atom interferometers reach bias stabilities that
    fibre-optic gyros cannot approach.
    """
    photon_energy = H_PLANCK * C_LIGHT / wavelength_m
    rest_energy = mass_kg * C_LIGHT ** 2
    return rest_energy / photon_energy


def quantum_illumination_advantage(signal_photons: float,
                                   background_photons: float,
                                   reflectivity: float) -> Dict:
    """Entangled-probe target detection gain (Tan et al., PRL 101, 253601).

    In the operational regime for stealth detection — weak return, bright
    thermal background — entangled illumination gives a 6 dB (factor 4)
    improvement in the error exponent. Remarkably the advantage survives even
    though the channel destroys the entanglement itself.
    """
    in_regime = (reflectivity < 0.1 and background_photons > 1.0
                 and signal_photons < 1.0)
    factor = 4.0 if in_regime else 1.0 + 3.0 * max(0.0, min(1.0, (
        (1.0 - reflectivity) * min(1.0, background_photons / 10.0))))
    return {
        "advantage_factor": factor,
        "advantage_db": 10.0 * math.log10(factor),
        "in_optimal_regime": in_regime,
        "classical_snr": signal_photons * reflectivity / max(background_photons, 1e-9),
        "quantum_snr": factor * signal_photons * reflectivity / max(background_photons, 1e-9),
    }
