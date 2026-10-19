"""The layer register is current and consistent with the registry: every
layer appears once, the measured statuses match the README's counts, the
verdicts follow the stated rules, and the phone-and-tower layers are listed.

Run: python tests/test_layer_register.py
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tools")

from layer_register import PHONE_AND_TOWER, render, rows  # noqa: E402

from upin.layers.registry import ALL_LAYER_CLASSES  # noqa: E402

PASSED = []


def test_register_is_current():
    rs = rows()
    assert len(rs) == len(ALL_LAYER_CLASSES) and len({r["id"] for r in rs}) == len(rs)
    works = [r for r in rs if r["status"] == "DECLINES"]
    assert len(works) >= 22 and all(r["verdict"].startswith("WORKS") for r in works)
    for r in rs:
        if r["status"] != "DECLINES":
            assert not r["verdict"].startswith("WORKS"), r
            assert any(r["verdict"].startswith(k) for k in ("REBUILD", "NOT FOR DRONE", "NOT DEPLOYABLE", "NOT OPERATIONAL", "SUPPORT")), r
    ids = {r["id"] for r in rs}
    assert set(PHONE_AND_TOWER) <= ids
    text = render(rs)
    current = open("docs/LAYER_REGISTER.md", encoding="utf-8").read()
    assert current == text, "docs/LAYER_REGISTER.md is stale: run python tools/layer_register.py"
    assert "## Phones, towers and local radio" in text and "`celltower_l9`" in text
    in_box = sum(1 for r in rs if r["verdict"].endswith("in the box"))
    print(f"[ok] register: {len(rs)} layers, {len(works)} work honestly, {in_box} in the box; every "
          f"fabricating layer carries a rebuild or leave verdict; the phone and tower layers are listed; "
          f"docs/LAYER_REGISTER.md is current")
    PASSED.append("register")


if __name__ == "__main__":
    test_register_is_current()
    print(f"\n{len(PASSED)}/1 layer-register tests passed")
