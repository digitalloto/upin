"""Tests for the balloon physics and the carry-and-release report, and the
tethered aerostat beacon in the simulator.

Run: python tests/test_balloon_carry.py
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from upin.simulation.balloon_physics import (aerostat_blowdown, balloon_for_payload,  # noqa: E402
                                             blowdown_sigma_m, gas_cylinder_mass_kg,
                                             helium_net_lift_kg_per_m3, sphere_drag_n)

PASSED = []


def test_physics_hand_checks():
    assert abs(helium_net_lift_kg_per_m3() - 1.046) < 0.01
    assert abs(sphere_drag_n(1.0, 10.0) - 0.5 * 1.225 * 100 * 0.47 * math.pi / 4) < 1e-9   # ~22.6 N
    b = balloon_for_payload(0.3, 5.0)
    # radiosonde practice is 1.2-1.5 m at launch; the model's sphere drag at
    # Cd 0.47 asks a little more, and says so in the report's assumptions
    assert 0.9 < b["diameter_m"] < 2.0, b
    lift = helium_net_lift_kg_per_m3() * b["volume_m3"] * 9.80665
    need = (0.3 + b["envelope_kg"]) * 9.80665 + sphere_drag_n(b["diameter_m"], 5.0)
    assert abs(lift - need) < 0.05 * lift
    c = gas_cylinder_mass_kg(1.0)
    assert abs(c["cylinder_litres"] - 5.0) < 1e-9 and c["cylinder_kg"] > 5.0
    off, h, ang = aerostat_blowdown(300.0, 3.0, 60.0, 8.0)
    assert 0 < off < 300 and h < 300 and 0 < ang < 90
    # the lean saturates toward 90 degrees, so sensitivity to wind is not
    # monotonic; it must simply be a positive, finite figure
    for v in (2.0, 8.0):
        sg = blowdown_sigma_m(300.0, 3.0, 60.0, v, 2.0)
        assert 0 < sg < 300 and math.isfinite(sg), (v, sg)
    print(f"[ok] physics: 1 m³ of helium lifts {helium_net_lift_kg_per_m3():.2f} kg; a 1 m sphere "
          f"at 10 m/s drags {sphere_drag_n(1.0, 10.0):.1f} N; a 0.3 kg beacon needs a "
          f"{b['diameter_m']:.2f} m balloon; the aerostat leans {ang:.0f}° in 8 m/s")
    PASSED.append("physics")


def test_report_writes_with_assumptions():
    from compare_balloon_carry import main
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "BALLOON_CARRY.md")
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--out", out])
        text = open(out, encoding="utf-8").read()
    for needed in ("## Assumptions", "Carrying it inflated", "Released inside a jammer",
                   "balloon-lifted drone", "tethered aerostat", "## Comparison", "Breadcrumbs"):
        assert needed in text, needed
    assert "kg/m³" in text and "Verdict" in text
    print("[ok] BALLOON_CARRY.md writes with its assumptions, the four options and a verdict")
    PASSED.append("report")


def test_tethered_aerostat_beacon_states_its_uncertainty():
    from upin.simulation.beacons import BeaconSim, SimBeacon
    calm = SimBeacon("aero", 13.0827, 80.2707, 10.0, 2.0, kind="tethered", tether_m=300.0,
                     wind_ne_ms=(0.0, 2.0), wind_sigma_ms=0.5)
    windy = SimBeacon("aero", 13.0827, 80.2707, 10.0, 2.0, kind="tethered", tether_m=300.0,
                      wind_ne_ms=(0.0, 9.0), wind_sigma_ms=3.0)
    mast = SimBeacon("mast", 13.0827, 80.2707, 100.0, 2.0)
    p_calm, p_windy = calm.position(0.0), windy.position(0.0)
    assert p_windy[2] < p_calm[2] < 310.0                    # leans more, flies lower
    assert windy.stated_sigma_m() > calm.stated_sigma_m() > mast.stated_sigma_m()
    sim = BeaconSim([windy], b"k")
    assert abs(sim.messages(1.0)[0]["sigma_m"] - windy.stated_sigma_m()) < 1e-9
    print(f"[ok] tethered aerostat: calm wind ±{calm.stated_sigma_m():.0f} m, strong uncertain "
          f"wind ±{windy.stated_sigma_m():.0f} m (a mast ±{mast.stated_sigma_m():.0f} m); the "
          f"broadcast carries that sigma")
    PASSED.append("aerostat")


if __name__ == "__main__":
    for t in (test_physics_hand_checks, test_report_writes_with_assumptions,
              test_tethered_aerostat_beacon_states_its_uncertainty):
        t()
    print(f"\n{len(PASSED)}/3 balloon tests passed")
