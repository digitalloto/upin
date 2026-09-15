"""Tests for the quantum mesh security overlay (CP4). Run: python tests/test_quantum_mesh.py"""
import sys

sys.path.insert(0, ".")

from upin.quantum.mesh_security import (
    QKD_CAPABLE_RADIOS, RF_IMMUNE_RADIOS, QuantumMeshSecurity,
)
from upin.swarm.multi_radio_mesh import MultiRadioMesh, RadioType

PASSED = []


def _pair(a="D1", b="D2", radios=None):
    s = QuantumMeshSecurity()
    s.register_node(a, 13.0800, 80.2700, radios=radios)
    s.register_node(b, 13.0805, 80.2705, radios=radios)
    return s


def test_key_distributes_over_an_optical_path():
    s = _pair()
    r = s.distribute_key("D1", "D2", has_los=True)
    assert r["keyed"], r
    assert r["key_radio"] == RadioType.IR_LASER.value
    assert r["key_bits"] > 0
    assert r["qber"] < 0.11
    assert r["rf_immune_key_path"], "IR must be RF-immune"
    print(f"[ok] key over {r['key_radio']}: {r['key_bits']} bits at "
          f"QBER {r['qber']:.4f}, RF-immune path")
    PASSED.append("distribute")


def test_key_path_and_data_path_are_independent():
    """The point of the overlay: key over one radio, spend it over another."""
    s = _pair()
    assert s.distribute_key("D1", "D2", has_los=True)["keyed"]
    snd = s.send_secure("D1", "D2", b"POSITION 13.0827 80.2707",
                        distance_m=12_000, has_los=False)
    assert snd["sent"], snd
    assert snd["key_radio"] == RadioType.IR_LASER.value
    assert snd["data_radio"] == RadioType.LORA_900.value
    assert snd["paths_differ"], "key and data should be on different radios here"
    assert snd["security"] == "information_theoretic"
    print(f"[ok] decoupled: keyed over {snd['key_radio']} at close range, "
          f"sent over {snd['data_radio']} at 12 km")
    PASSED.append("decoupled")


def test_eavesdropper_on_the_key_channel_is_caught_before_use():
    s = _pair("E1", "E2")
    r = s.distribute_key("E1", "E2", eavesdropper=True)
    assert not r["keyed"]
    assert r["reason"] == "EAVESDROPPER_DETECTED"
    assert r["qber"] > 0.11, f"intercept-resend should raise QBER, got {r['qber']}"
    # and no key was stored, so nothing can be sent with it
    snd = s.send_secure("E1", "E2", b"secret", distance_m=100)
    assert not snd["sent"] and snd["reason"] == "NO_SECURE_KEY"
    print(f"[ok] eavesdropper: QBER {r['qber']:.3f} -> key discarded before use, "
          f"send refused")
    PASSED.append("eavesdropper")


def test_no_optical_path_downgrades_honestly():
    """Without a QKD-capable radio the overlay must say so, not pretend."""
    s = _pair("F1", "F2", radios=[RadioType.LORA_900, RadioType.BLE_5])
    r = s.distribute_key("F1", "F2")
    assert not r["keyed"]
    assert r["reason"] == "NO_QKD_CAPABLE_RADIO"
    assert r["fallback"] == "classical_encryption"
    assert s.get_status()["classical_downgrades"] == 1
    print("[ok] no optical path -> honest downgrade to classical, counted")
    PASSED.append("downgrade")


def test_ir_needs_line_of_sight():
    s = _pair()
    r = s.distribute_key("D1", "D2", has_los=False)
    assert not r["keyed"]
    assert r["reason"] == "NO_LINE_OF_SIGHT"
    print("[ok] IR QKD refused without line of sight")
    PASSED.append("los")


def test_jamming_rf_does_not_kill_key_distribution():
    """The whole point: an adversary owning the RF spectrum cannot stop QKD."""
    s = _pair()
    for band in (RadioType.WIFI_DIRECT, RadioType.LORA_900,
                 RadioType.BLE_5, RadioType.ISM_915):
        res = s.report_jamming(band)
        assert not res["qkd_capability_lost"], f"{band} should not carry QKD"
        assert RadioType.IR_LASER.value in res["rf_immune_paths_remaining"]

    r = s.distribute_key("D1", "D2", has_los=True)
    assert r["keyed"], "IR must still key with the RF bands jammed"
    print(f"[ok] 4 RF bands jammed, key still distributed over "
          f"{r['key_radio']}; immune paths: acoustic, ir_laser")
    PASSED.append("rf_jamming")


def test_jamming_the_optical_path_is_reported_as_capability_loss():
    s = _pair()
    assert s.distribute_key("D1", "D2", has_los=True)["keyed"]
    res = s.report_jamming(RadioType.IR_LASER)
    assert res["qkd_capability_lost"]
    assert "existing key material still protects" in res["consequence"]
    # existing key still works
    snd = s.send_secure("D1", "D2", b"still-protected", distance_m=500)
    assert snd["sent"], "stored key must survive loss of the QKD channel"
    # but no new key can be made
    assert not s.distribute_key("D1", "D2", has_los=True)["keyed"]
    print("[ok] optical jammed: no new keys, existing key material still spends")
    PASSED.append("optical_jamming")


def test_one_time_pad_consumes_key_material():
    s = _pair()
    s.distribute_key("D1", "D2", has_los=True)
    start = s.get_status()["total_key_bytes"]
    msg = b"X" * 64
    snd = s.send_secure("D1", "D2", msg, distance_m=200)
    assert snd["sent"]
    assert snd["remaining_key_bytes"] == start - len(msg), \
        "OTP must burn exactly one key byte per plaintext byte"
    print(f"[ok] OTP: {start} key bytes -> {snd['remaining_key_bytes']} "
          f"after a {len(msg)}-byte message")
    PASSED.append("otp")


def test_key_exhaustion_is_refused_not_reused():
    """Reusing one-time-pad material destroys its security — it must refuse."""
    s = _pair()
    s.distribute_key("D1", "D2", has_los=True)
    budget = s.get_status()["total_key_bytes"]
    over = s.send_secure("D1", "D2", b"Y" * (budget + 64), distance_m=200)
    assert not over["sent"]
    assert over["reason"] == "KEY_EXHAUSTED"
    assert over["required_bits"] > over["remaining_bits"]
    assert s.get_status()["key_exhaustions"] == 1
    print(f"[ok] exhaustion refused: needed {over['required_bits']} bits, "
          f"had {over['remaining_bits']} — no reuse")
    PASSED.append("exhaustion")


def test_rekey_refreshes_depleted_links():
    s = _pair()
    s.distribute_key("D1", "D2", has_los=True)
    budget = s.get_status()["total_key_bytes"]
    s.send_secure("D1", "D2", b"Z" * (budget - 8), distance_m=200)
    depleted = s.get_status()["total_key_bytes"]
    assert depleted < 256, "link should now be low on key material"

    # Too little key left to carry this message
    before = s.send_secure("D1", "D2", b"W" * 64, distance_m=200)
    assert not before["sent"] and before["reason"] == "KEY_EXHAUSTED"

    res = s.rekey_all()
    assert res["refreshed"] == 1, res
    restored = s.get_status()["total_key_bytes"]
    assert restored > depleted, f"key material {depleted} -> {restored}"

    # and the same message now goes through
    after = s.send_secure("D1", "D2", b"W" * 64, distance_m=200)
    assert after["sent"], "rekeyed link must carry the message"
    print(f"[ok] rekey: {depleted} bytes left -> refused; after rekey "
          f"{restored} bytes -> message sent")
    PASSED.append("rekey")


def test_underlying_mesh_is_not_modified():
    """MultiRadioMesh must behave identically whether or not the overlay exists."""
    bare = MultiRadioMesh()
    bare.register_node("A", [RadioType.LORA_900, RadioType.IR_LASER])
    bare.register_node("B", [RadioType.LORA_900, RadioType.IR_LASER])
    bare_link = bare.establish_link("A", "B", distance_m=800)

    s = QuantumMeshSecurity()
    s.register_node("A", 13.08, 80.27, radios=[RadioType.LORA_900, RadioType.IR_LASER])
    s.register_node("B", 13.085, 80.27, radios=[RadioType.LORA_900, RadioType.IR_LASER])
    over_link = s._mesh.establish_link("A", "B", distance_m=800)

    assert bare_link.radio is over_link.radio, "radio selection must be unchanged"
    print(f"[ok] underlying mesh unchanged: both select {bare_link.radio.value}")
    PASSED.append("unmodified")


def test_radio_capability_sets_are_sane():
    assert RadioType.IR_LASER in QKD_CAPABLE_RADIOS
    assert QKD_CAPABLE_RADIOS <= RF_IMMUNE_RADIOS, \
        "every QKD-capable radio here should also be RF-immune"
    assert RadioType.LORA_900 not in QKD_CAPABLE_RADIOS, \
        "LoRa cannot carry single photons"
    assert RadioType.ACOUSTIC in RF_IMMUNE_RADIOS
    print(f"[ok] capability sets: QKD-capable {sorted(r.value for r in QKD_CAPABLE_RADIOS)}, "
          f"RF-immune {sorted(r.value for r in RF_IMMUNE_RADIOS)}")
    PASSED.append("capabilities")


if __name__ == "__main__":
    tests = [
        test_key_distributes_over_an_optical_path,
        test_key_path_and_data_path_are_independent,
        test_eavesdropper_on_the_key_channel_is_caught_before_use,
        test_no_optical_path_downgrades_honestly,
        test_ir_needs_line_of_sight,
        test_jamming_rf_does_not_kill_key_distribution,
        test_jamming_the_optical_path_is_reported_as_capability_loss,
        test_one_time_pad_consumes_key_material,
        test_key_exhaustion_is_refused_not_reused,
        test_rekey_refreshes_depleted_links,
        test_underlying_mesh_is_not_modified,
        test_radio_capability_sets_are_sane,
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

    print(f"\n{len(PASSED)}/{len(tests)} mesh-security tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all mesh-security tests passed")
