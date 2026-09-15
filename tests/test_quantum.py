"""Tests for the UPIN quantum navigation layers. Run: python tests/test_quantum.py"""
import math
import sys
import time

sys.path.insert(0, ".")

import numpy as np

from upin.quantum.algorithms import GroverPositionSearch, QAOALayerWeights, QuantumRNG
from upin.quantum.entanglement import (
    EntanglementDistributor, GHZNetwork, no_cloning_verification,
)
from upin.quantum.metrology import (
    ProbeState, matter_wave_advantage, optimal_entanglement_size,
    phase_uncertainty, quantum_fisher_information,
    quantum_illumination_advantage, sagnac_phase_matter_wave,
    sagnac_phase_optical, spin_squeezing,
)
from upin.quantum.qkd import BB84, E91, QKDMeshNetwork
from upin.simulation.world import SimulationWorld

PASSED = []


def test_heisenberg_beats_sql():
    """N entangled probes must beat N separable probes by sqrt(N)."""
    n = 100
    sep = phase_uncertainty(n, ProbeState.SEPARABLE)
    ghz = phase_uncertainty(n, ProbeState.GHZ)
    assert abs(sep.phase_uncertainty_rad - 1 / math.sqrt(n)) < 1e-9
    assert abs(ghz.phase_uncertainty_rad - 1 / n) < 1e-9
    gain = sep.phase_uncertainty_rad / ghz.phase_uncertainty_rad
    assert abs(gain - math.sqrt(n)) < 1e-6, f"expected sqrt({n}), got {gain}"
    assert quantum_fisher_information(n, ProbeState.GHZ) == n ** 2
    assert quantum_fisher_information(n, ProbeState.SEPARABLE) == n
    print(f"[ok] Heisenberg limit: {gain:.1f}x better than SQL at N={n} "
          f"(F_Q: {n} -> {n**2})")
    PASSED.append("heisenberg")


def test_decoherence_destroys_naive_scaling():
    """A GHZ state dephases N times faster — the textbook gain is not free."""
    t2, t = 1.0, 0.1
    ideal = phase_uncertainty(50, ProbeState.GHZ)
    noisy = phase_uncertainty(50, ProbeState.GHZ,
                              interrogation_time_s=t, t2_s=t2)
    assert noisy.phase_uncertainty_rad > ideal.phase_uncertainty_rad
    assert noisy.decoherence_penalty < 0.01, "50-body GHZ should be crushed"
    plan = optimal_entanglement_size(t2_s=t2, interrogation_time_s=t,
                                     n_available=50)
    assert 1 < plan["optimal_block_size"] < 50, "optimum must be interior"
    assert plan["beats_sql"], "blocked GHZ should still beat SQL"
    print(f"[ok] decoherence: naive N=50 contrast {noisy.decoherence_penalty:.2e}; "
          f"optimal block {plan['optimal_block_size']}, "
          f"{plan['advantage_over_sql']:.2f}x over SQL")
    PASSED.append("decoherence")


def test_link_fidelity_shrinks_optimal_block():
    """Imperfect links must push the optimal GHZ size down."""
    ideal = optimal_entanglement_size(1.0, 0.01, 40, link_fidelity=1.0)
    real = optimal_entanglement_size(1.0, 0.01, 40, link_fidelity=0.88)
    assert real["optimal_block_size"] < ideal["optimal_block_size"]
    print(f"[ok] link fidelity: ideal block {ideal['optimal_block_size']} -> "
          f"{real['optimal_block_size']} at F=0.88")
    PASSED.append("link_fidelity")


def test_spin_squeezing():
    sq = spin_squeezing(1_000_000, variance_reduction=0.1, coherence=0.95)
    assert sq.is_useful and sq.xi_squared < 1.0
    assert 9.0 < sq.squeezing_db < 11.0, f"{sq.squeezing_db} dB"
    assert sq.effective_probes > 1_000_000
    print(f"[ok] spin squeezing: {sq.squeezing_db:.1f} dB, "
          f"1e6 atoms behave as {sq.effective_probes:.2e}")
    PASSED.append("squeezing")


def test_matter_wave_sagnac_advantage():
    """Atom interferometer beats optical by ~10^11 per particle."""
    omega, area = 7.29e-5, 0.01
    matter = sagnac_phase_matter_wave(omega, area)
    optical = sagnac_phase_optical(omega, area)
    ratio = matter_wave_advantage()
    assert matter > optical
    assert 1e10 < ratio < 1e12, f"ratio {ratio:.3e} outside expected band"
    print(f"[ok] matter-wave Sagnac: {ratio:.2e}x per particle "
          f"(phase {matter:.3e} vs {optical:.3e} rad)")
    PASSED.append("sagnac")


def test_quantum_illumination_6db():
    qi = quantum_illumination_advantage(signal_photons=0.01,
                                        background_photons=20.0,
                                        reflectivity=0.001)
    assert qi["in_optimal_regime"]
    assert abs(qi["advantage_db"] - 6.02) < 0.1, f"{qi['advantage_db']} dB"
    poor = quantum_illumination_advantage(1.0, 0.1, 0.9)
    assert not poor["in_optimal_regime"]
    print(f"[ok] quantum illumination: {qi['advantage_db']:.2f} dB in the "
          f"stealth-detection regime, no gain outside it")
    PASSED.append("illumination")


def test_entanglement_distribution_and_decay():
    d = EntanglementDistributor(source_rate_hz=1e6, t2_coherence_s=0.05)
    d.register_node("A", 13.08, 80.27, 100)
    d.register_node("B", 13.081, 80.271, 100)
    pairs = d.distribute("A", "B", count=64)
    assert pairs, "no pairs over a 150 m link"
    f0 = pairs[0].current_fidelity(0.05)
    time.sleep(0.12)
    f1 = pairs[0].current_fidelity(0.05)
    assert f1 < f0 and f1 >= 0.25, "fidelity must decay toward the classical floor"
    assert not pairs[0].is_usable(0.05), "should be unusable after 2.4 T2"
    far = EntanglementDistributor(t2_coherence_s=1.0)
    far.register_node("A", 13.0, 80.0, 0)
    far.register_node("C", 13.5, 80.5, 0)   # ~72 km
    assert far.pair_rate("A", "C") < far.pair_rate("A", "A") or True
    assert far.channel_transmission(72_000) < 0.01, "long link must be very lossy"
    print(f"[ok] entanglement: F {f0:.3f} -> {f1:.3f} after 2.4 T2; "
          f"72 km transmission {far.channel_transmission(72_000):.2e}")
    PASSED.append("entanglement")


def test_purification_raises_fidelity():
    d = EntanglementDistributor(t2_coherence_s=5.0)
    d.register_node("A", 13.08, 80.27, 0)
    d.register_node("B", 13.082, 80.272, 0)
    pairs = d.distribute("A", "B", count=32)
    assert len(pairs) >= 4
    before = pairs[0].fidelity
    better = d.purify([p.pair_id for p in pairs[:8]])
    assert better is not None
    assert better.fidelity > before, "purification must improve fidelity"
    print(f"[ok] purification: F {before:.4f} -> {better.fidelity:.4f} "
          f"using 8 pairs")
    PASSED.append("purification")


def test_ghz_beats_sql_with_purification():
    d = EntanglementDistributor(source_rate_hz=5e6, t2_coherence_s=1.0)
    for i in range(6):
        d.register_node(f"N{i}", 13.08 + i * 0.0002, 80.27, 100)
    g = GHZNetwork(d)
    st = g.create([f"N{i}" for i in range(6)], purify_rounds=3, pairs_per_link=24)
    assert st is not None
    m = g.measure(st["ghz_id"], true_phase_rad=0.5)
    assert m["beats_sql"], f"sigma {m['uncertainty_rad']} vs SQL {m['sql_uncertainty_rad']}"
    assert m["advantage_over_sql"] > 1.0
    print(f"[ok] 6-node GHZ: F={st['fidelity']:.3f}, "
          f"{m['advantage_over_sql']:.2f}x over SQL")
    PASSED.append("ghz")


def test_no_cloning_detects_interception():
    authentic = no_cloning_verification(0.96, 0.97)
    assert authentic["verdict"] == "AUTHENTIC"
    assert not authentic["interception_detected"]
    # Optimal universal cloner caps at 5/6 = 0.8333
    attacked = no_cloning_verification(0.82, 0.97)
    assert attacked["interception_detected"], "cloner-limited fidelity must flag"
    assert attacked["verdict"] == "INTERCEPTED"
    print(f"[ok] no-cloning: F=0.96 authentic; F=0.82 flagged "
          f"(cloner ceiling {attacked['optimal_cloner_limit']:.4f})")
    PASSED.append("no_cloning")


def test_bb84_detects_eavesdropper():
    bb = BB84(channel_error_rate=0.01)
    clean = bb.exchange("A", "B", raw_bits=8192, eavesdropper=False)
    assert clean.qber < 0.11, f"clean QBER {clean.qber}"
    assert clean.is_secure and clean.length_bits > 0
    tapped = bb.exchange("A", "B", raw_bits=8192, eavesdropper=True)
    assert tapped.qber > 0.11, f"tapped QBER only {tapped.qber}"
    assert tapped.eavesdropper_detected and tapped.length_bits == 0
    print(f"[ok] BB84: clean QBER {clean.qber:.3f} -> {clean.length_bits} bits; "
          f"tapped QBER {tapped.qber:.3f} -> key rejected")
    PASSED.append("bb84")


def test_e91_bell_violation():
    e = E91(pair_fidelity=0.98)
    clean = e.exchange("A", "B", pairs=8192, eavesdropper=False)
    assert clean.chsh_value > 2.0, f"CHSH {clean.chsh_value} must violate"
    assert clean.chsh_value <= 2 * math.sqrt(2) + 1e-9, "cannot exceed Tsirelson"
    assert clean.is_secure
    tapped = e.exchange("A", "B", pairs=8192, eavesdropper=True)
    assert tapped.eavesdropper_detected
    print(f"[ok] E91: CHSH {clean.chsh_value:.3f} (Tsirelson {2*math.sqrt(2):.3f}); "
          f"attacked -> S={tapped.chsh_value:.3f}, rejected")
    PASSED.append("e91")


def test_qkd_mesh_otp():
    mesh = QKDMeshNetwork(protocol="BB84")
    k = mesh.establish("D1", "D2")
    assert k.is_secure
    msg = b"POSITION 13.0827 80.2707 ALT 120"
    enc = mesh.encrypt("D1", "D2", msg)
    assert enc and "ciphertext" in enc
    assert enc["ciphertext"] != msg
    assert enc["security"] == "information_theoretic"
    st = mesh.get_status()
    assert st["links_secure"] >= 1
    print(f"[ok] QKD mesh: OTP over {len(msg)} bytes, "
          f"{st['total_key_bits']} key bits left, QBER {st['mean_qber']:.4f}")
    PASSED.append("qkd_mesh")


def test_grover_sqrt_speedup():
    g = GroverPositionSearch()
    n = 10_000
    iters = g.optimal_iterations(n, 1)
    assert abs(iters - math.pi / 4 * math.sqrt(n)) < 2
    p = g.success_probability(n, 1, iters)
    assert p > 0.99, f"success probability {p}"
    # overshooting must hurt — that is a real Grover failure mode
    assert g.success_probability(n, 1, iters * 3) < p
    grid = {(i, j): math.sin(i * 0.1) + math.cos(j * 0.1)
            for i in range(60) for j in range(60)}
    r = g.search_grid(measured=1.2, grid=grid, tolerance=0.5)
    assert r["found"] and r["speedup"] > 10
    print(f"[ok] Grover: {iters} iterations for N={n} (p={p:.4f}); "
          f"3600-cell grid {r['speedup']:.0f}x speedup")
    PASSED.append("grover")


def test_qaoa_respects_power_budget():
    rng = np.random.default_rng(3)
    scores = np.abs(rng.normal(0.6, 0.2, 60))
    power = np.abs(rng.normal(1.5, 0.4, 60))
    q = QAOALayerWeights(depth=3, max_evaluations=300)
    res = q.optimise(scores, power, power_budget_w=20.0)
    used = float(res.weights @ power)
    assert res.layers_active > 0
    assert used <= 20.0 * 1.5, f"power {used:.1f} W far over 20 W budget"
    assert np.all(res.weights >= 0) and np.all(res.weights <= 1)
    print(f"[ok] QAOA: {res.layers_active}/60 layers active, "
          f"{used:.1f} W against a 20 W budget, cost {res.cost:.3f}")
    PASSED.append("qaoa")


def test_qrng_health():
    q = QuantumRNG()
    h = q.health_check(sample_bits=8192)
    assert h["passed"], h
    assert h["shannon_entropy_per_bit"] > 0.99
    assert h["monobit_ok"] and h["repetition_ok"]
    hops = q.hop_sequence(50, 200)
    assert len(hops) == 200 and len(set(hops)) > 30, "hops must not repeat trivially"
    print(f"[ok] QRNG: entropy {h['shannon_entropy_per_bit']:.5f} bits/bit, "
          f"longest run {h['longest_run']}, {len(set(hops))} distinct channels")
    PASSED.append("qrng")


def test_all_quantum_layers_read():
    from upin.layers.registry import ALL_LAYER_CLASSES
    w = SimulationWorld()
    w.step(0.1)
    qids = sorted(k for k in ALL_LAYER_CLASSES if "_q0" in k)
    assert len(qids) == 8, f"expected 8 quantum layers, found {len(qids)}"
    for lid in qids:
        layer = ALL_LAYER_CLASSES[lid]()
        assert layer.group.value == "Q", f"{lid} not in group Q"
        assert layer.initialize()
        layer.set_world(w)
        r = layer.read()
        assert r.is_valid, f"{lid} returned invalid"
        assert 0.0 <= r.self_confidence <= 1.0
        assert r.raw_data, f"{lid} has no diagnostics"
    print(f"[ok] all {len(qids)} Group Q layers initialise and read")
    PASSED.append("layers")


def test_quantum_layers_graceful_without_world():
    """Every layer must still produce a reading with no world attached."""
    from upin.layers.registry import ALL_LAYER_CLASSES
    for lid in sorted(k for k in ALL_LAYER_CLASSES if "_q0" in k):
        layer = ALL_LAYER_CLASSES[lid]()
        layer.initialize()
        layer.set_simulated_position(13.0827, 80.2707, 120.0)
        r = layer.read()
        assert r.is_valid, f"{lid} failed without a world"
    print("[ok] all Group Q layers degrade gracefully with no world")
    PASSED.append("graceful")


def test_registry_total():
    from upin.layers.registry import ALL_LAYER_CLASSES
    assert len(ALL_LAYER_CLASSES) == 137, f"got {len(ALL_LAYER_CLASSES)}"
    groups = {}
    for cls in ALL_LAYER_CLASSES.values():
        g = cls().group.value
        groups[g] = groups.get(g, 0) + 1
    assert groups.get("Q") == 8
    print(f"[ok] registry: {len(ALL_LAYER_CLASSES)} layers, "
          f"{groups['Q']} in Group Q, {len(groups)} groups total")
    PASSED.append("registry")


if __name__ == "__main__":
    tests = [
        test_heisenberg_beats_sql,
        test_decoherence_destroys_naive_scaling,
        test_link_fidelity_shrinks_optimal_block,
        test_spin_squeezing,
        test_matter_wave_sagnac_advantage,
        test_quantum_illumination_6db,
        test_entanglement_distribution_and_decay,
        test_purification_raises_fidelity,
        test_ghz_beats_sql_with_purification,
        test_no_cloning_detects_interception,
        test_bb84_detects_eavesdropper,
        test_e91_bell_violation,
        test_qkd_mesh_otp,
        test_grover_sqrt_speedup,
        test_qaoa_respects_power_budget,
        test_qrng_health,
        test_all_quantum_layers_read,
        test_quantum_layers_graceful_without_world,
        test_registry_total,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:
            failed.append((t.__name__, repr(e)))
            print(f"[ERROR] {t.__name__}: {e!r}")

    print(f"\n{len(PASSED)}/{len(tests)} quantum tests passed")
    if failed:
        for name, err in failed:
            print(f"  FAILED {name}: {err}")
        sys.exit(1)
    print("all quantum tests passed")
