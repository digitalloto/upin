"""Tests for the quantum map-search backend (CP5). Run: python tests/test_quantum_mapsearch.py"""
import math
import sys

sys.path.insert(0, ".")

from upin.layers.registry import ALL_LAYER_CLASSES
from upin.quantum.map_search import (
    GRID_SCAN_LAYERS, QuantumMapMatcher, grid_from_world,
)
from upin.simulation.world import SimulationWorld

PASSED = []


def _world():
    w = SimulationWorld()
    w.step(0.1)
    return w


def test_answer_is_bit_identical_to_the_linear_scan():
    """The core guarantee: Grover changes the cost, never the answer."""
    w = _world()
    m = QuantumMapMatcher(backend="grover", verify=True)
    c = QuantumMapMatcher(backend="classical")

    for kind, measured in (
            ("gravity", w.get_gravity()["anomaly_mgal"]),
            ("magnetic", w.get_magnetic_field()["intensity_nt"]),
            ("bathymetry", w.get_bathymetry_depth())):
        grid = grid_from_world(w, kind, half_span_deg=0.2, step_deg=0.01)
        g = m.match(measured, grid)
        l = c.match(measured, grid)
        assert g.cell == l.cell, f"{kind}: {g.cell} != {l.cell}"
        assert g.residual == l.residual, f"{kind}: residual differs"
        assert g.lat == l.lat and g.lon == l.lon
        assert g.identical_to_classical

    assert m.get_status()["answer_mismatches"] == 0
    print("[ok] gravity, magnetic and bathymetry all return the identical cell, "
          "residual and position as the linear scan")
    PASSED.append("identical")


def test_oracle_budget_follows_sqrt_n():
    w = _world()
    m = QuantumMapMatcher()
    for span, step in ((0.1, 0.01), (0.2, 0.01), (0.4, 0.01)):
        grid = grid_from_world(w, "gravity", half_span_deg=span, step_deg=step)
        r = m.match(w.get_gravity()["anomaly_mgal"], grid)
        expected = math.floor(math.pi / 4 * math.sqrt(r.grid_size)) + 1
        assert abs(r.oracle_calls - expected) <= 1, \
            f"N={r.grid_size}: {r.oracle_calls} calls, expected ~{expected}"
        assert r.classical_calls == r.grid_size
    print("[ok] oracle budget tracks floor(pi/4 * sqrt(N)) + 1 across three grid sizes")
    PASSED.append("sqrt_n")


def test_speedup_grows_with_grid_size():
    """The larger the map, the more the quadratic advantage is worth."""
    w = _world()
    m = QuantumMapMatcher()
    small = m.match(w.get_gravity()["anomaly_mgal"],
                    grid_from_world(w, "gravity", 0.1, 0.01))
    large = m.match(w.get_gravity()["anomaly_mgal"],
                    grid_from_world(w, "gravity", 1.0, 0.01))
    assert large.grid_size > small.grid_size * 50
    assert large.speedup > small.speedup
    assert large.speedup > 100, f"only {large.speedup:.0f}x on {large.grid_size} cells"
    print(f"[ok] speedup scales: {small.grid_size} cells {small.speedup:.0f}x -> "
          f"{large.grid_size} cells {large.speedup:.0f}x")
    PASSED.append("scaling")


def test_success_probability_is_near_certain():
    w = _world()
    m = QuantumMapMatcher()
    r = m.match(w.get_gravity()["anomaly_mgal"],
                grid_from_world(w, "gravity", 0.3, 0.01))
    assert r.success_probability > 0.95, f"p={r.success_probability}"
    assert r.grover_iterations > 0
    print(f"[ok] {r.grover_iterations} iterations give success probability "
          f"{r.success_probability:.4f}")
    PASSED.append("success_prob")


def test_classical_backend_reports_no_speedup():
    w = _world()
    c = QuantumMapMatcher(backend="classical")
    r = c.match(w.get_gravity()["anomaly_mgal"],
                grid_from_world(w, "gravity", 0.2, 0.01))
    assert r.backend == "classical"
    assert r.speedup == 1.0
    assert r.oracle_calls == r.classical_calls == r.grid_size
    assert r.grover_iterations == 0
    print(f"[ok] classical backend: {r.oracle_calls} calls for {r.grid_size} "
          f"cells, 1.0x — no inflated claim")
    PASSED.append("classical_backend")


def test_empty_and_single_cell_grids():
    m = QuantumMapMatcher()
    assert m.match(1.0, {}) is None, "empty grid must return None, not crash"
    one = m.match(5.0, {(1308, 8027): 5.5})
    assert one is not None
    assert one.cell == (1308, 8027)
    assert abs(one.residual - 0.5) < 1e-12
    assert one.grid_size == 1
    print("[ok] empty grid returns None; single-cell grid returns that cell")
    PASSED.append("edge_cases")


def test_cell_scale_converts_to_degrees():
    m = QuantumMapMatcher()
    r = m.match(42.0, {(1308, 8027): 42.0}, cell_scale=100.0)
    assert abs(r.lat - 13.08) < 1e-9
    assert abs(r.lon - 80.27) < 1e-9
    r2 = m.match(42.0, {(13080, 80270): 42.0}, cell_scale=1000.0)
    assert abs(r2.lat - 13.08) < 1e-9
    print("[ok] cell_scale maps integer keys back to degrees at 100 and 1000")
    PASSED.append("cell_scale")


def test_handles_a_plateau_of_equally_good_cells():
    """Several cells can tie. Grover marks them all and still converges."""
    grid = {(i, 0): 10.0 for i in range(64)}      # every cell identical
    grid[(99, 0)] = 99.0
    m = QuantumMapMatcher()
    r = m.match(10.0, grid)
    assert r.residual == 0.0
    assert r.cell in [(i, 0) for i in range(64)]
    # more marked items means fewer iterations are needed
    assert r.grover_iterations < math.floor(math.pi / 4 * math.sqrt(len(grid)))
    print(f"[ok] 64-way tie: {r.grover_iterations} iterations "
          f"(fewer than the single-target {math.floor(math.pi/4*math.sqrt(len(grid)))})")
    PASSED.append("plateau")


def test_resolution_gain_is_the_operational_argument():
    """A sqrt speedup on cost is a quadratic gain in affordable grid cells."""
    m = QuantumMapMatcher()
    g = m.resolution_gain(grid_size=40_000, oracle_budget=200)
    assert g["classical_cells_affordable"] == 200
    assert g["grover_cells_affordable"] == 40_000
    assert g["cells_gain"] == 200
    assert abs(g["linear_resolution_gain"] - math.sqrt(200)) < 0.1
    print(f"[ok] same 200-call budget: 200 cells classical vs "
          f"{g['grover_cells_affordable']:,} Grover "
          f"({g['linear_resolution_gain']:.0f}x finer spacing)")
    PASSED.append("resolution")


def test_covers_the_real_grid_scan_layers():
    missing = [lid for lid in GRID_SCAN_LAYERS if lid not in ALL_LAYER_CLASSES]
    assert not missing, f"backend references layers not in registry: {missing}"
    assert set(GRID_SCAN_LAYERS) == {
        "gravgrad_l28a", "gravimeter_l28b", "magmap_l23", "bathymetry_f04"}
    print(f"[ok] all {len(GRID_SCAN_LAYERS)} grid-scan layers exist in the registry")
    PASSED.append("coverage")


def test_those_layers_still_work_untouched():
    """The four layers must behave exactly as before — this is a backend, not an edit."""
    w = _world()
    for lid in GRID_SCAN_LAYERS:
        layer = ALL_LAYER_CLASSES[lid]()
        layer.initialize()
        layer.set_world(w)
        r = layer.read()
        assert r.is_valid, f"{lid} broke"
        assert r.position is not None
    print(f"[ok] all {len(GRID_SCAN_LAYERS)} layers still read normally with no "
          f"backend attached")
    PASSED.append("untouched")


def test_rejects_an_unknown_backend():
    try:
        QuantumMapMatcher(backend="magic")
    except ValueError as e:
        assert "magic" in str(e)
        print("[ok] unknown backend rejected at construction")
        PASSED.append("bad_backend")
        return
    raise AssertionError("should have rejected an unknown backend")


if __name__ == "__main__":
    tests = [
        test_answer_is_bit_identical_to_the_linear_scan,
        test_oracle_budget_follows_sqrt_n,
        test_speedup_grows_with_grid_size,
        test_success_probability_is_near_certain,
        test_classical_backend_reports_no_speedup,
        test_empty_and_single_cell_grids,
        test_cell_scale_converts_to_degrees,
        test_handles_a_plateau_of_equally_good_cells,
        test_resolution_gain_is_the_operational_argument,
        test_covers_the_real_grid_scan_layers,
        test_those_layers_still_work_untouched,
        test_rejects_an_unknown_backend,
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

    print(f"\n{len(PASSED)}/{len(tests)} map-search tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all map-search tests passed")
