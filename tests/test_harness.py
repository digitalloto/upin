"""Tests for the simulation harness and the real/simulation split.

The harness is the one place that decides what feeds a layer. These tests
hold it to three things: that a fed layer computes, that an unfed layer
declines, and that the "real" path cannot be tricked into passing invented
data off as measured.

That last one is not hypothetical. The agents named "real" in this repo fall
back to simulation when no hardware is present and still report ACTIVE;
RealWiFiPositioningAgent.is_available() is literally
`return True  # Always available (falls back to simulation)`. A feed that
trusted them would launder fake data through the honest path.

Run: python tests/test_harness.py
"""
import math
import sys

sys.path.insert(0, ".")

import numpy as np

from upin.core.fusion_engine import FusionEngine
from upin.layers.registry import LayerRegistry
from upin.simulation.adapters import ADAPTERS, adapter_for
from upin.simulation.feeds import (
    AgentFeed, NullFeed, Observation, WorldFeed,
)
from upin.simulation.harness import Mode, NavigationHarness
from upin.simulation.world import SimulationWorld

PASSED = []

DEG_M = 111_320.0
START = (13.0827, 80.2707, 120.0)


def fresh_world():
    return SimulationWorld(start_lat=START[0], start_lon=START[1],
                           start_alt=START[2])


def fresh_harness(mode=Mode.SIMULATION, world=None, **kw):
    world = world if world is not None else fresh_world()
    return NavigationHarness(LayerRegistry().create_all(), mode,
                             world=world, seed=7, **kw)


def error_from(world, position):
    dn = (position.latitude - world.true_lat) * DEG_M
    de = ((position.longitude - world.true_lon) * DEG_M
          * math.cos(math.radians(world.true_lat)))
    return math.hypot(dn, de)


# ------------------------------------------------------------- the feeds

def test_world_feed_produces_every_observation_it_claims():
    feed = WorldFeed(fresh_world())
    kinds = feed.kinds()
    missing = [k for k in kinds if feed.observation(k) is None]
    assert not missing, f"claimed but did not produce: {missing}"
    assert len(kinds) >= 20, f"only {len(kinds)} observations"
    print(f"[ok] world feed produces all {len(kinds)} observations it advertises")
    PASSED.append("world_feed")


def test_agent_feed_rejects_simulated_readings():
    """The whole point: the 'real' agents are not reliably real."""
    feed = AgentFeed()
    rejections = feed.rejections()
    assert feed.available() is False, (
        "agent feed claims real data is available on a machine with no radios")
    assert feed.readings() == []
    assert len(rejections) >= 3, rejections
    joined = " ".join(rejections.values())
    assert "simulated" in joined or "no provenance" in joined, joined
    print(f"[ok] agent feed rejected all {len(rejections)} agents:")
    for agent_id, why in sorted(rejections.items()):
        print(f"      {agent_id}: {why}")
    PASSED.append("agent_rejects")


def test_agent_feed_accepts_a_genuinely_sourced_reading():
    """Default-deny must not mean deny-everything."""
    class RealAgent:
        agent_id = "honest"
        def is_available(self): return True
        def get_reading(self):
            return {"status": "ACTIVE", "source": "mls",
                    "lat": 13.08, "lon": 80.27, "accuracy_m": 40.0}

    feed = AgentFeed(agents=[RealAgent()])
    assert feed.available() is True
    readings = feed.readings()
    assert len(readings) == 1
    assert readings[0]["provenance"] == "mls"
    assert feed.rejections() == {}
    print("[ok] a reading stamped with a real source (mls) is accepted")
    PASSED.append("agent_accepts")


def test_provenance_rules():
    p = AgentFeed.provenance_of
    assert p({"status": "ACTIVE", "source": "mls"}) == "mls"
    assert p({"status": "ACTIVE", "source": "opencellid"}) == "opencellid"
    assert p({"status": "ACTIVE", "source": "simulated"}).startswith("rejected")
    assert p({"status": "ACTIVE", "source": "SIMULATED"}).startswith("rejected")
    assert p({"status": "ACTIVE"}).startswith("rejected")          # no marker
    assert p({"status": "NO_POSITION", "source": "mls"}).startswith("rejected")
    assert p({"status": "ACTIVE",
              "sensors_available": ["gps_sim"]}).startswith("rejected")
    assert p({"status": "ACTIVE", "sensors_available": ["gps"]}) == "device"
    print("[ok] provenance is default-deny: unknown and unstamped both rejected")
    PASSED.append("provenance")


def test_null_feed_is_honest():
    feed = NullFeed()
    assert feed.available() is False
    assert feed.kinds() == []
    assert feed.observation(Observation.TRUE_STATE) is None
    print("[ok] the null feed reports nothing and produces nothing")
    PASSED.append("null_feed")


# ----------------------------------------------------------- the harness

def test_simulation_mode_feeds_converted_layers():
    h = fresh_harness()
    for _ in range(20):
        cov = h.tick(0.1)
    assert set(cov.native) == set(ADAPTERS), (
        f"expected {set(ADAPTERS)} fed natively, got {cov.native}")
    print(f"[ok] {cov.summary()}")
    PASSED.append("sim_feeds")


def test_fed_layers_actually_compute_a_position():
    world = fresh_world()
    h = fresh_harness(world=world)
    for _ in range(20):
        h.tick(0.1)
    for layer_id in ADAPTERS:
        r = h.layer(layer_id).read()
        assert r.is_valid and r.position is not None, (
            f"{layer_id} fed but produced no fix: "
            f"{(r.raw_data or {}).get('no_fix_reason')}")
        err = error_from(world, r.position)
        assert err < 60.0, f"{layer_id} is {err:.1f} m out"
        print(f"      {layer_id}: {err:.2f} m error, "
              f"claims {r.position.accuracy_m:.2f} m")
    print("[ok] every natively-fed layer computes a position near truth")
    PASSED.append("compute")


def test_claimed_accuracy_is_not_flattering():
    """A layer must not claim to be better than it is."""
    world = fresh_world()
    h = fresh_harness(world=world)
    for _ in range(60):
        h.tick(0.1)
    for layer_id in ADAPTERS:
        r = h.layer(layer_id).read()
        err = error_from(world, r.position)
        assert err <= r.position.accuracy_m * 3.0, (
            f"{layer_id} is {err:.2f} m out while claiming "
            f"{r.position.accuracy_m:.2f} m")
        print(f"      {layer_id}: {err:.2f} m actual vs "
              f"{r.position.accuracy_m:.2f} m claimed")
    print("[ok] claimed accuracy covers the real error for every fed layer")
    PASSED.append("not_flattering")


def test_unfed_layers_decline():
    """OFF mode: nothing is fed, and the converted layers say so."""
    h = fresh_harness(mode=Mode.OFF)
    cov = h.tick(0.1)
    assert cov.native == [], cov.native
    assert cov.legacy == [], "legacy bridge should not run with the feed off"
    for layer_id in ADAPTERS:
        r = h.layer(layer_id).read()
        assert not r.is_valid and r.position is None
        assert (r.raw_data or {}).get("no_fix_reason")
    print(f"[ok] OFF mode: {cov.summary()}, converted layers all decline")
    PASSED.append("unfed")


def test_legacy_bridge_keeps_unconverted_layers_running():
    h = fresh_harness()
    cov = h.tick(0.1)
    assert len(cov.legacy) > 100, f"only {len(cov.legacy)} on the bridge"
    assert len(cov.legacy) + len(cov.native) + len(cov.unfed) == 139
    print(f"[ok] {len(cov.legacy)} unconverted layers still driven by the "
          f"bridge — the number left to convert")
    PASSED.append("legacy")


def test_mode_switch_reconfigures_layers():
    h = fresh_harness()
    assert len(h.tick(0.1).legacy) > 100
    h.set_mode(Mode.REAL)
    cov = h.coverage()
    assert cov.legacy == [], "bridge still running in REAL mode"
    assert h.feed.name == "real"
    h.set_mode(Mode.SIMULATION)
    assert len(h.coverage().legacy) > 100, "bridge did not come back"
    print("[ok] switching modes reconfigures every layer, and back again")
    PASSED.append("mode_switch")


def test_real_mode_yields_no_fix_from_the_engine():
    """Real mode with no hardware must produce no position, not a guess."""
    h = fresh_harness(mode=Mode.REAL)
    engine = FusionEngine()
    for layer in h.layers:
        engine.register_layer(layer)
    engine.initialize()
    out = None
    for _ in range(7):        # let the unhealthy-marking settle
        h.tick(0.1)
        out = engine.cycle()
    assert out.position is None, (
        f"real mode with no hardware still produced {out.position}")
    assert out.has_fix is False
    print(f"[ok] real mode, no hardware -> engine reports no fix: "
          f"{out.no_fix_reason[:80]}")
    PASSED.append("real_no_fix")


# --------------------------------------------------- keeping it honest

def test_audit_passes_honest_adapters():
    assert fresh_harness().audit_adapters() == {}
    print("[ok] the cheat audit clears the real adapters")
    PASSED.append("audit_clean")


def test_audit_catches_an_adapter_that_hands_over_the_answer():
    """The bug this audit exists to catch, planted deliberately."""
    from upin.layers.inertial.command_dr import MotorCommand
    from upin.simulation import adapters as A

    original = A.ADAPTERS["cmddr_b12"].drive

    def cheat(layer, feed, dt, rng):
        state = feed.observation(Observation.TRUE_STATE)
        if state is None:
            return False
        layer.set_anchor(state.latitude, state.longitude, state.altitude,
                         (0.0, 0.0, 0.0))
        layer.log_command(MotorCommand(state.timestamp,
                                       layer._model.hover_throttle,
                                       0.0, 0.0, 0.0, dt))
        return True

    A.ADAPTERS["cmddr_b12"].drive = cheat
    try:
        found = fresh_harness().audit_adapters()
        assert "cmddr_b12" in found, "the audit missed an adapter handing over truth"
        assert "not a measurement" in found["cmddr_b12"]
        print(f"[ok] cheat caught: {found['cmddr_b12'][:96]}...")
    finally:
        A.ADAPTERS["cmddr_b12"].drive = original
    PASSED.append("audit_catches")


def test_seeded_runs_are_reproducible():
    """Noise lives in the harness, so a seed pins the whole run."""
    def run(seed):
        world = fresh_world()
        h = NavigationHarness(LayerRegistry().create_all(), Mode.SIMULATION,
                              world=world, seed=seed)
        for _ in range(15):
            h.tick(0.1)
        r = h.layer("lmkchain_e23").read()
        return (r.position.latitude, r.position.longitude)

    a, b = run(11), run(11)
    assert a == b, f"same seed gave different answers: {a} vs {b}"
    assert run(12) != a, "different seeds gave identical noise"
    print("[ok] a seeded run reproduces exactly; a different seed does not")
    PASSED.append("seeded")


def test_provisioning_is_reported_and_idempotent():
    h = fresh_harness()
    assert set(h.provisioned) == set(ADAPTERS), h.provisioned
    again = h.provision()
    assert again == [], f"re-provisioned layers that were already set up: {again}"
    print(f"[ok] provisioned {h.provisioned} once, and not again")
    PASSED.append("provision")


def test_status_is_enough_to_drive_a_ui_toggle():
    h = fresh_harness()
    h.tick(0.1)
    s = h.status()
    for key in ("mode", "feed", "feed_available", "is_simulated",
                "native_count", "legacy_count", "unfed_count", "total"):
        assert key in s, f"status missing {key}"
    assert s["is_simulated"] is True
    h.set_mode(Mode.REAL)
    s = h.status()
    assert s["is_simulated"] is False
    assert "rejected_agents" in s, "real mode must explain what it rejected"
    print(f"[ok] status carries mode, counts and rejections: "
          f"{sorted(s)[:6]}...")
    PASSED.append("status")


if __name__ == "__main__":
    tests = [
        test_world_feed_produces_every_observation_it_claims,
        test_agent_feed_rejects_simulated_readings,
        test_agent_feed_accepts_a_genuinely_sourced_reading,
        test_provenance_rules,
        test_null_feed_is_honest,
        test_simulation_mode_feeds_converted_layers,
        test_fed_layers_actually_compute_a_position,
        test_claimed_accuracy_is_not_flattering,
        test_unfed_layers_decline,
        test_legacy_bridge_keeps_unconverted_layers_running,
        test_mode_switch_reconfigures_layers,
        test_real_mode_yields_no_fix_from_the_engine,
        test_audit_passes_honest_adapters,
        test_audit_catches_an_adapter_that_hands_over_the_answer,
        test_seeded_runs_are_reproducible,
        test_provisioning_is_reported_and_idempotent,
        test_status_is_enough_to_drive_a_ui_toggle,
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

    print(f"\n{len(PASSED)}/{len(tests)} harness tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all harness tests passed")
