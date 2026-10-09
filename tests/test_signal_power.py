"""Tests for layer 146, the GNSS signal-power spoof check (cn0spoof_a20).

The honest sky is a SYNTHETIC MODEL: C/N0 = 30 + 0.2 x elevation + 2 dB
noise, rounded to whole dB-Hz as a u-blox reports it. These tests check the
logic and its stated limits. They are not detection rates for a real
receiver, which must come from logs of the receiver and antenna flown.

Run: python tests/test_signal_power.py
"""
import random
import sys

sys.path.insert(0, ".")

from upin.box.gateway import Gateway, GnssEpoch  # noqa: E402
from upin.box.gnss_parser import RfBlock, SatInfo  # noqa: E402
from upin.core.no_fabrication import audit_layer  # noqa: E402
from upin.detection.reachability import Envelope  # noqa: E402
from upin.layers.satellite.signal_power import (CLEAR, JAMMING, NOT_RUN,  # noqa: E402
                                                SUSPECT, SignalPowerCheckLayer)

PASSED = []


def honest(elevs, rng, offset=0.0):
    return [SatInfo("gps", i, round(30 + 0.2 * e + rng.gauss(0, 2.0) + offset), round(e), 0, True)
            for i, e in enumerate(elevs)]


def uniform(elevs, rng, level=46.0):
    return [SatInfo("gps", i, round(level + rng.gauss(0, 0.8)), round(e), 0, True)
            for i, e in enumerate(elevs)]


def rf(agc):
    return [RfBlock(0, "ok", 90, round(agc), 10)]


def warmed(rng, elevs, epochs=80):
    """A layer that has learned this sky on trusted epochs."""
    layer = SignalPowerCheckLayer()
    for k in range(epochs):
        layer.feed_nav_sat(honest(elevs, rng), float(k))
        layer.feed_rf(rf(3000 + rng.gauss(0, 20)), float(k))
        layer.check(float(k))
        layer.learn(True)
    return layer


def test_contract():
    layer = SignalPowerCheckLayer()
    res = audit_layer(layer)
    assert res.compliant, res
    r = layer.read()
    assert r.position is None and not r.is_valid
    print("[ok] contract: declines with nothing fed, says why, never a position")
    PASSED.append("contract")


def test_honest_false_alarm_rate():
    rng = random.Random(1)
    alarms = epochs = 0
    for run in range(30):
        n = rng.randint(7, 12)
        base = sorted(rng.uniform(5, 85) for _ in range(n))
        layer = SignalPowerCheckLayer()
        for k in range(120):
            elevs = [e + 0.02 * k for e in base]
            layer.feed_nav_sat(honest(elevs, rng), float(k))
            layer.feed_rf(rf(3000 + rng.gauss(0, 20)), float(k))
            v = layer.check(float(k))
            layer.learn(True)
            epochs += 1
            alarms += v["verdict"] not in (CLEAR, NOT_RUN)
    rate = alarms / epochs
    assert rate < 0.005, (alarms, epochs)
    print(f"[ok] synthetic honest sky: {alarms}/{epochs} false alarms "
          f"(model only; real rate must come from receiver logs)")
    PASSED.append("honest")


def test_simple_spoofer_flagged():
    rng = random.Random(2)
    elevs = [12, 20, 31, 40, 49, 57, 66, 78]
    layer = SignalPowerCheckLayer()
    layer.feed_nav_sat(uniform(elevs, rng), 0.0)
    v = layer.check(0.0)
    fired = [t["test"] for t in v["tests"] if t["fired"]]
    assert v["verdict"] == SUSPECT and "too uniform" in fired and "no elevation dependence" in fired
    layer.feed_nav_sat(uniform(elevs, rng, level=53.0), 1.0)
    assert any(t["test"] == "too strong" and t["fired"] for t in layer.check(1.0)["tests"])
    print(f"[ok] one transmitter, uniform power: SUSPECT ({', '.join(fired)}); "
          f"at 53 dB-Hz 'too strong' fires too")
    PASSED.append("simple")


def test_rising_together():
    rng = random.Random(3)
    elevs = [12, 20, 31, 40, 49, 57, 66, 78]
    layer = SignalPowerCheckLayer()
    layer.feed_nav_sat(honest(elevs, rng), 0.0)
    layer.check(0.0)
    layer.feed_nav_sat(honest(elevs, rng, offset=8.0), 1.0)
    v = layer.check(1.0)
    assert any(t["test"] == "all rising together" and t["fired"] for t in v["tests"])
    layer2 = SignalPowerCheckLayer()
    layer2.feed_nav_sat(honest(elevs, rng), 0.0)
    layer2.check(0.0)
    layer2.feed_nav_sat(honest(elevs, rng, offset=-8.0), 1.0)
    v2 = layer2.check(1.0)
    assert not any(t["test"] == "all rising together" and t["fired"] for t in v2["tests"])
    print("[ok] all satellites +8 dB at once: flagged; -8 dB (banking, "
          "obstruction): not flagged as spoofing")
    PASSED.append("jump")


def test_agc_spoofing_vs_jamming():
    rng = random.Random(4)
    elevs = [12, 20, 31, 40, 49, 57, 66, 78]
    layer = warmed(rng, elevs)
    layer.feed_nav_sat(honest(elevs, rng, offset=1.0), 100.0)
    layer.feed_rf(rf(2300), 100.0)
    v = layer.check(100.0)
    assert v["verdict"] == SUSPECT and any(t["test"] == "AGC drop" and t["kind"] == "spoofing"
                                           for t in v["tests"]), v
    layer = warmed(rng, elevs)
    layer.feed_nav_sat(honest(elevs, rng, offset=-6.0), 100.0)
    layer.feed_rf(rf(2300), 100.0)
    v = layer.check(100.0)
    assert v["verdict"] == JAMMING, v
    layer.feed_nav_sat(honest(elevs[:3], rng, offset=-10.0), 101.0)
    layer.feed_rf(rf(1800), 101.0)
    assert layer.check(101.0)["verdict"] == JAMMING
    print("[ok] AGC drops with C/N0 holding or rising: spoofing; AGC drops "
          "with C/N0 falling or satellites lost: JAMMING, not spoofing")
    PASSED.append("agc")


def test_smart_spoofer_passes_stated_limit():
    """A spoofer shaping power by elevation at realistic levels, with no
    AGC change, is NOT caught. Asserted so the limit cannot be forgotten."""
    rng = random.Random(5)
    elevs = [12, 20, 31, 40, 49, 57, 66, 78]
    layer = warmed(rng, elevs)
    caught = 0
    for k in range(100, 160):
        layer.feed_nav_sat(honest(elevs, rng, offset=2.0), float(k))
        layer.feed_rf(rf(3000 + rng.gauss(0, 20)), float(k))
        caught += layer.check(float(k))["verdict"] != CLEAR
    assert caught <= 1, caught
    print(f"[ok] smart spoofer (elevation-shaped power, +2 dB, no AGC change): "
          f"not caught ({caught}/60) -- the stated limit")
    PASSED.append("smart")


def test_not_run_reasons():
    rng = random.Random(6)
    layer = SignalPowerCheckLayer()
    assert layer.check(0.0)["verdict"] == NOT_RUN
    layer.feed_nav_sat(honest([20, 40, 60, 80], rng), 0.0)
    v = layer.check(0.0)
    assert v["verdict"] == NOT_RUN and "only 4 satellites" in v["reason"]
    layer.feed_nav_sat(honest([12, 20, 31, 40, 49, 57], rng), 0.0)
    assert "old" in layer.check(10.0)["reason"]
    print("[ok] NOT_RUN with the reason: no data, too few satellites, stale data")
    PASSED.append("notrun")


def test_profile_learned_only_when_trusted():
    rng = random.Random(7)
    elevs = [12, 20, 31, 40, 49, 57, 66, 78]
    layer = SignalPowerCheckLayer()
    for k in range(80):
        layer.feed_nav_sat(honest(elevs, rng), float(k))
        layer.check(float(k))
        layer.learn(False)
    assert not layer.profile_learned
    layer = warmed(rng, elevs)
    assert layer.profile_learned
    layer.feed_nav_sat(honest(elevs, rng, offset=6.0), 200.0)
    v = layer.check(200.0)
    assert any(t["test"] == "stronger than this antenna's profile" and t["fired"]
               for t in v["tests"]), v
    print("[ok] profile learned only from trusted epochs; afterwards +6 dB "
          "across the sky is flagged")
    PASSED.append("profile")


def test_gateway_warn_vs_distrust():
    sus = {"verdict": SUSPECT, "reason": "looks like one transmitter: too uniform"}
    for action, expect in (("warn", "TRUSTED"), ("distrust", "DEGRADED")):
        gw = Gateway(Envelope(6.0, 20.0), power_check_action=action)
        for k in range(5):
            gw.process(GnssEpoch(t=float(k), fix_type=3, lat=13.0, lon=80.0, h_acc_m=2.0))
        out = gw.process(GnssEpoch(t=5.0, fix_type=3, lat=13.0, lon=80.0, h_acc_m=2.0,
                                   power_check=sus))
        c = [x for x in gw.last_checks if x["check"] == "signal power pattern"][0]
        assert out.mode == expect, (action, out.mode)
        assert c["status"] == ("WARN" if action == "warn" else "FAIL")
        if action == "warn":
            assert any(r.startswith("warning: signal power") for r in out.reasons)
    print("[ok] gateway: 'warn' shows WARN and stays TRUSTED (reason says so); "
          "'distrust' makes it a hard check")
    PASSED.append("gateway")


def test_through_the_box_in_simulation():
    from upin.console.sources import SimSource
    from upin.console.state import ConsoleState
    st = ConsoleState("sim", "S", True, SimSource.controls)
    sim = SimSource(st, 13.08, 80.27, seed=9)
    for _ in range(90):
        sim.step()
    c = [x for x in st.get()["checks"] if x["check"] == "signal power pattern"][0]
    assert c["status"] == "PASS"
    sim.control("spoof_jump")
    sim.step()
    c = [x for x in st.get()["checks"] if x["check"] == "signal power pattern"][0]
    assert c["status"] == "WARN" and "spoofing" in c["detail"]
    print("[ok] simulated sky through the real box: honest PASS; simple spoofer WARN")
    PASSED.append("sim")


if __name__ == "__main__":
    tests = [test_contract, test_honest_false_alarm_rate, test_simple_spoofer_flagged,
             test_rising_together, test_agc_spoofing_vs_jamming,
             test_smart_spoofer_passes_stated_limit, test_not_run_reasons,
             test_profile_learned_only_when_trusted, test_gateway_warn_vs_distrust,
             test_through_the_box_in_simulation]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} signal-power tests passed")
