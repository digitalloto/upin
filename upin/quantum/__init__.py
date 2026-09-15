"""
UPIN Quantum — the first quantum navigation system.

Not a platform carrying quantum sensors. A system whose sensors are
entangled with one another, whose clocks are synchronised below the standard
quantum limit, whose ranging cannot be spoofed because the no-cloning theorem
forbids it, and whose fusion runs quantum algorithms.

Modules:
    metrology     SQL vs Heisenberg scaling, Fisher information, squeezing
    entanglement  Bell pair distribution, GHZ states, swapping, purification
    qkd           BB84 and E91 key distribution for the swarm mesh
    algorithms    Grover map search, QAOA weights, quantum RNG
    layers        Group Q navigation layers (Q1-Q8)

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from upin.quantum.algorithms import (
    GroverPositionSearch, QAOALayerWeights, QuantumRNG,
)
from upin.quantum.entanglement import (
    EntangledPair, EntanglementDistributor, GHZNetwork, no_cloning_verification,
)
from upin.quantum.metrology import (
    MetrologyResult, ProbeState, matter_wave_advantage,
    optimal_entanglement_size, phase_uncertainty,
    quantum_fisher_information, quantum_illumination_advantage,
    sagnac_phase_matter_wave, sagnac_phase_optical, spin_squeezing,
)
from upin.quantum.qkd import BB84, E91, QKDMeshNetwork, QuantumKey

__all__ = [
    "ProbeState", "MetrologyResult", "phase_uncertainty",
    "quantum_fisher_information", "optimal_entanglement_size",
    "spin_squeezing", "sagnac_phase_matter_wave", "sagnac_phase_optical",
    "matter_wave_advantage", "quantum_illumination_advantage",
    "EntangledPair", "EntanglementDistributor", "GHZNetwork",
    "no_cloning_verification",
    "BB84", "E91", "QKDMeshNetwork", "QuantumKey",
    "GroverPositionSearch", "QAOALayerWeights", "QuantumRNG",
]
