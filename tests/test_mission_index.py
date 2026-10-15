"""Tests for the mission catalogue and index: it names only real, honest,
tested components; its config lines exist; its READMEs exist; it never
recommends a fabricating layer; and the generated index is current.

Run: python tests/test_mission_index.py
"""
import os
import subprocess
import sys
from dataclasses import fields

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from upin.box.service import BoxConfig  # noqa: E402
from upin.layers.mission_catalog import (BY_ID, ENTRIES, HARDWARE_TAGS, LADDERS,  # noqa: E402
                                         PROFILES, SITUATIONS, recommend)
from upin.layers.registry import ALL_LAYER_CLASSES  # noqa: E402
from upin.layers.requirements_catalog import operating_class  # noqa: E402

PASSED = []


def test_entries_are_real_and_honest():
    cfg_keys = {f.name for f in fields(BoxConfig)}
    for e in ENTRIES:
        if not e.layer_id.startswith("box:"):
            cls = ALL_LAYER_CLASSES[e.layer_id]
            assert getattr(cls, "NO_FABRICATION", False), e.layer_id
        assert e.needs <= set(HARDWARE_TAGS), (e.layer_id, e.needs - set(HARDWARE_TAGS))
        assert set(e.works) == set(SITUATIONS), e.layer_id
        assert os.path.exists(e.readme), (e.layer_id, e.readme)
        for line in e.enable.splitlines():
            if "=" in line and not line.startswith(("not in", "automatic", "always", "max_accel", "receiver_port")):
                key = line.split("=")[0].strip()
                assert key in cfg_keys, (e.layer_id, key)
    # every honest layer that is usable outside a laboratory has an entry
    for k, cls in ALL_LAYER_CLASSES.items():
        if getattr(cls, "NO_FABRICATION", False) and operating_class(k) != "laboratory":
            assert k in BY_ID, f"honest layer {k} missing from the mission catalogue"
    for rungs in LADDERS.values():
        for rid, _ in rungs:
            assert rid in BY_ID, rid
    print(f"[ok] {len(ENTRIES)} entries: all registered and honest, hardware tags and situations "
          f"valid, config keys exist, READMEs exist; every non-laboratory honest layer listed")
    PASSED.append("entries")


def test_recommendations_never_fabricate():
    fab = {k for k, c in ALL_LAYER_CLASSES.items() if not getattr(c, "NO_FABRICATION", False)}
    for name, sit, have in PROFILES:
        for e, verdict, why in recommend(sorted(have), sit):
            assert e.layer_id not in fab and e.in_box, (name, e.layer_id)
            assert verdict in ("yes", "limited")
    recs = {e.layer_id for e, _, _ in recommend(
        ["flight_controller", "gnss_receiver", "camera", "rangefinder", "tags_surveyed"], "jammed")}
    assert {"camflow_e24", "fiducial_e25"} <= recs, recs
    assert "box:receiver_fix" not in recs                      # no fix when jammed
    night = {e.layer_id for e, _, _ in recommend(["flight_controller", "camera", "rangefinder"], "night")}
    assert "camflow_e24" not in night and "fiducial_e25" not in night
    try:
        recommend(["flight_controller", "laser_cannon"], "jammed")
        raise AssertionError("unknown tag accepted")
    except ValueError:
        pass
    print("[ok] recommendations use only honest, box-wired components; camera layers drop out at "
          "night; the receiver's fix drops out when jammed; unknown tags refused")
    PASSED.append("recommend")


def test_generated_index_is_current():
    from mission_index import render
    current = open("docs/MISSION_INDEX.md", encoding="utf-8").read()
    assert current == render(), "docs/MISSION_INDEX.md is stale: run python tools/mission_index.py"
    assert "## Not usable on real hardware yet" in current and "invents readings" in current
    out = subprocess.run([sys.executable, "tools/mission_index.py", "--have",
                          "flight_controller,gnss_receiver,sdr", "--situation", "long_denial"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "LEO Doppler" in out.stdout and "box.toml fragment" in out.stdout
    print("[ok] docs/MISSION_INDEX.md is current; the query mode answers with a box.toml fragment")
    PASSED.append("index")


if __name__ == "__main__":
    for t in (test_entries_are_real_and_honest, test_recommendations_never_fabricate,
              test_generated_index_is_current):
        t()
    print(f"\n{len(PASSED)}/3 mission-index tests passed")
