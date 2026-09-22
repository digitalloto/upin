"""Tests for the fusion engine's no-fix output.

The engine used to answer a cycle in which no layer had ever measured
anything by handing back its filter's uninitialised state: latitude 0,
longitude 0, dressed in a Position object with a 200 m accuracy claim. That
is a coordinate in the Gulf of Guinea, and nothing downstream could tell it
from a real fix — the mission modules would happily steer to it.

These tests hold the engine to the same standard as a layer: when it does
not know where it is, it says so.

Run: python tests/test_fusion_no_fix.py
"""
import sys
import time

sys.path.insert(0, ".")

from upin.core.fusion_engine import FusionEngine
from upin.core.layer_base import (
    LayerCapability, LayerGroup, LayerReading, NavigationLayer,
)
from upin.core.no_fabrication import NoFixReason, no_fix
from upin.core.position import Position
from upin.layers.inertial.command_dr import CommandDeadReckoningLayer
from upin.layers.optical.landmark_chain import LandmarkChainLayer

PASSED = []

CHENNAI = (13.0827, 80.2707)


class MeasuringLayer(NavigationLayer):
    """A layer that reports a real position, to prove the engine still fuses."""

    def __init__(self, lat=CHENNAI[0], lon=CHENNAI[1], accuracy_m=5.0):
        super().__init__(
            layer_id="stub_measuring", layer_number=900, name="Stub Measuring",
            group=LayerGroup.B_INERTIAL_TIMING,
            capabilities=[LayerCapability.POSITION],
        )
        self.lat, self.lon, self.accuracy_m = lat, lon, accuracy_m
        self.silent = False

    def initialize(self):
        self.status.is_active = True
        self.status.is_healthy = True
        return True

    def get_accuracy_rating(self):
        return 0.9

    def read(self):
        if self.silent:
            return no_fix(self.layer_id, NoFixReason.SENSOR_UNAVAILABLE,
                          "stub told to go quiet")
        return LayerReading(
            layer_id=self.layer_id,
            position=Position(latitude=self.lat, longitude=self.lon,
                              altitude=100.0, accuracy_m=self.accuracy_m,
                              timestamp=time.time()),
            self_confidence=0.9, is_valid=True, raw_data={},
        )


class DecliningLayer(NavigationLayer):
    """A layer with no sensor attached, which says so."""

    def __init__(self, layer_id="stub_declining"):
        super().__init__(
            layer_id=layer_id, layer_number=901, name="Stub Declining",
            group=LayerGroup.D_RF_TERRESTRIAL,
            capabilities=[LayerCapability.POSITION],
        )

    def initialize(self):
        self.status.is_active = True
        self.status.is_healthy = True     # healthy, just unfed
        return True

    def get_accuracy_rating(self):
        return 0.5

    def read(self):
        return no_fix(self.layer_id, NoFixReason.SENSOR_UNAVAILABLE,
                      "no receiver attached")


def engine_with(*layers):
    e = FusionEngine()
    for L in layers:
        e.register_layer(L)
    e.initialize()
    return e


# ------------------------------------------------------- the original bug

def test_no_layers_measuring_gives_no_position():
    """The Gulf of Guinea bug: 0N 0E must never be reported as a fix."""
    out = engine_with(DecliningLayer("a"), DecliningLayer("b")).cycle()
    assert out.position is None, f"expected no position, got {out.position}"
    assert out.has_fix is False
    assert out.confidence_score == 0.0
    assert out.num_active_layers == 0
    print("[ok] no measurements -> position is None, not 0N 0E")
    PASSED.append("no_position")


def test_real_layers_that_decline_produce_no_fix():
    """The two contract layers, unfed, must not produce a fused position."""
    out = engine_with(CommandDeadReckoningLayer(), LandmarkChainLayer()).cycle()
    assert out.position is None
    assert out.has_fix is False
    print("[ok] the two no-fabrication layers, unfed -> engine reports no fix")
    PASSED.append("contract_layers")


def test_no_fix_output_explains_itself():
    """A no-fix output is a diagnosis, not a blank."""
    out = engine_with(DecliningLayer("a"), DecliningLayer("b")).cycle()
    assert out.no_fix_reason, "no reason given"
    assert "2 layers" in out.no_fix_reason, out.no_fix_reason
    assert NoFixReason.SENSOR_UNAVAILABLE in out.no_fix_reason, out.no_fix_reason
    print(f"[ok] reason: {out.no_fix_reason}")
    PASSED.append("explains")


def test_unhealthy_layers_are_counted_not_lost():
    """A layer skipped as unhealthy is never read, so the engine counts it."""
    # CommandDeadReckoningLayer marks itself unhealthy without a calibration.
    out = engine_with(CommandDeadReckoningLayer()).cycle()
    assert "layer_unhealthy" in out.no_fix_reason, out.no_fix_reason
    print(f"[ok] skipped layers still appear in the diagnosis: "
          f"{out.no_fix_reason}")
    PASSED.append("unhealthy_counted")


def test_diagnostics_survive_a_no_fix():
    out = engine_with(DecliningLayer("a"), DecliningLayer("b")).cycle()
    assert len(out.layer_diagnostics) > 0, "no-fix output threw away diagnostics"
    print(f"[ok] {len(out.layer_diagnostics)} layer diagnostics retained on a no-fix")
    PASSED.append("diagnostics")


# ------------------------------------------------------ still fuses properly

def test_a_measuring_layer_produces_a_fix():
    """The gate must not block real measurements."""
    out = engine_with(MeasuringLayer()).cycle()
    assert out.position is not None, f"no fix: {out.no_fix_reason}"
    assert out.has_fix is True
    assert abs(out.position.latitude - CHENNAI[0]) < 0.01
    assert abs(out.position.longitude - CHENNAI[1]) < 0.01
    assert out.seconds_since_measurement == 0.0
    print(f"[ok] a measuring layer fuses to "
          f"{out.position.latitude:.4f},{out.position.longitude:.4f}")
    PASSED.append("measures")


def test_one_measurer_among_decliners_still_fixes():
    out = engine_with(DecliningLayer("a"), MeasuringLayer(),
                      DecliningLayer("b")).cycle()
    assert out.position is not None, f"no fix: {out.no_fix_reason}"
    print("[ok] one real measurement among decliners still gives a fix")
    PASSED.append("mixed")


# -------------------------------------------------- propagation vs invention

def test_going_silent_propagates_rather_than_refusing():
    """Once measured, the filter may coast. That is a filter, not a fabrication."""
    stub = MeasuringLayer()
    e = engine_with(stub)
    first = e.cycle()
    assert first.has_fix and not first.is_propagated

    stub.silent = True
    time.sleep(0.05)
    later = e.cycle()
    assert later.position is not None, "coasting is legitimate, should not refuse"
    assert later.is_propagated is True
    assert later.seconds_since_measurement > 0
    print(f"[ok] after the sensor goes quiet the fix is flagged propagated "
          f"({later.seconds_since_measurement*1000:.0f} ms stale)")
    PASSED.append("propagates")


def test_propagated_accuracy_widens_with_time():
    """A frozen accuracy would claim precision the engine stopped earning."""
    stub = MeasuringLayer()
    e = engine_with(stub)
    measured = e.cycle()
    stub.silent = True
    time.sleep(0.10)
    a = e.cycle()
    time.sleep(0.30)
    b = e.cycle()
    assert b.position.accuracy_m > a.position.accuracy_m > measured.position.accuracy_m, (
        f"{measured.position.accuracy_m} -> {a.position.accuracy_m} "
        f"-> {b.position.accuracy_m}")
    print(f"[ok] accuracy widens while coasting: "
          f"{measured.position.accuracy_m:.2f} -> {a.position.accuracy_m:.2f} "
          f"-> {b.position.accuracy_m:.2f} m")
    PASSED.append("widens")


# ------------------------------------------------- downstream survives a None

def test_mission_modules_survive_a_no_fix():
    """Nothing downstream may crash, and nothing may act on a position it lacks."""
    out = engine_with(DecliningLayer("a")).cycle()
    assert out.position is None

    from upin.missions.waypoint_nav import WaypointNavigationModule
    from upin.missions.recon_patterns import PatternGenerator
    from upin.missions.flight_planning import FlightPlanningModule

    for mod, name in ((WaypointNavigationModule(), "waypoint_nav"),
                      (PatternGenerator(), "recon_patterns"),
                      (FlightPlanningModule(), "flight_planning")):
        res = mod.execute(out, {})
        assert res.get("position_available") is False, (
            f"{name} did not report the missing position: {res}")
    print("[ok] waypoint_nav, recon_patterns and flight_planning all refuse "
          "to act and say why")
    PASSED.append("missions")


def test_intelligence_report_carries_no_phantom_coordinate():
    out = engine_with(DecliningLayer("a")).cycle()
    from upin.missions.intelligence import IntelligenceEcosystem
    report = IntelligenceEcosystem().process_local(out)
    assert report.data["position"] is None, (
        f"phantom coordinate in report: {report.data['position']}")
    assert report.data["position_available"] is False
    print("[ok] intelligence report carries position=None, not (0.0, 0.0)")
    PASSED.append("intel")


if __name__ == "__main__":
    tests = [
        test_no_layers_measuring_gives_no_position,
        test_real_layers_that_decline_produce_no_fix,
        test_no_fix_output_explains_itself,
        test_unhealthy_layers_are_counted_not_lost,
        test_diagnostics_survive_a_no_fix,
        test_a_measuring_layer_produces_a_fix,
        test_one_measurer_among_decliners_still_fixes,
        test_going_silent_propagates_rather_than_refusing,
        test_propagated_accuracy_widens_with_time,
        test_mission_modules_survive_a_no_fix,
        test_intelligence_report_carries_no_phantom_coordinate,
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

    print(f"\n{len(PASSED)}/{len(tests)} fusion no-fix tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all fusion no-fix tests passed")
