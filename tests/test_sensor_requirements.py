"""Tests for the sensor requirement declarations.

A declaration is only worth having if it is checkable. These tests hold it
to that: the feed methods it names must actually exist on the layer, the
refusal text it produces must name the missing thing, and a layer that
claims to need only common hardware must not be hiding a cold-atom
interferometer in its list.

Run: python tests/test_sensor_requirements.py
"""
import sys

sys.path.insert(0, ".")

from upin.core.sensor_requirements import (
    DataInput, Hardware, ReferenceData, SensorRequirement, requirement_of,
)
from upin.layers.inertial.command_dr import CommandDeadReckoningLayer
from upin.layers.optical.landmark_chain import LandmarkChainLayer

PASSED = []

DECLARED = [CommandDeadReckoningLayer, LandmarkChainLayer]


def test_declared_feed_methods_exist():
    """A requirement naming a method the layer lacks is a broken declaration."""
    for cls in DECLARED:
        layer = cls()
        req = requirement_of(layer)
        assert req is not None, f"{cls.__name__} declares no requirement"
        gaps = req.missing_from(layer)
        assert not gaps, f"{cls.__name__} names feed methods it lacks: {gaps}"
    print(f"[ok] all feed methods declared by {len(DECLARED)} layers exist on them")
    PASSED.append("feeds_exist")


def test_refusal_names_what_is_missing():
    """'sensor_unavailable' is a shrug; the refusal must be an instruction."""
    layer = LandmarkChainLayer()
    layer.load_map([])
    text = layer.REQUIRES.describe_missing()
    assert "camera" in text
    assert "observe()" in text, f"no feed method named: {text}"
    assert "charted landmark positions" in text
    print(f"[ok] refusal text: {text}")
    PASSED.append("names_missing")


def test_describe_missing_drops_what_is_supplied():
    req = SensorRequirement(inputs=[
        DataInput("bearings", feed_method="observe"),
        DataInput("ranges", feed_method="observe_range"),
    ])
    both = req.describe_missing()
    assert "bearings" in both and "ranges" in both
    one = req.describe_missing(have=["bearings"])
    assert "bearings" not in one and "ranges" in one
    print("[ok] supplying an input removes it from the missing list")
    PASSED.append("drops_supplied")


def test_unstated_requirement_says_so():
    """Silence must not read as 'nothing needed'."""
    assert SensorRequirement().describe_missing() == "requirements unstated"
    print("[ok] an empty declaration reports itself as unstated, not satisfied")
    PASSED.append("unstated")


def test_build_cost_needs_every_price():
    priced = SensorRequirement(hardware=[
        Hardware("camera", approx_cost_usd=400),
        Hardware("AHRS", approx_cost_usd=800),
    ])
    assert priced.build_cost_usd == 1200.0
    partial = SensorRequirement(hardware=[
        Hardware("camera", approx_cost_usd=400),
        Hardware("mystery box"),
    ])
    assert partial.build_cost_usd is None, "guessed a total from a missing price"
    print("[ok] build cost is None unless every piece carries a price")
    PASSED.append("cost")


def test_common_hardware_flag_is_strict():
    common = SensorRequirement(hardware=[
        Hardware("camera", already_on_most_drones=True),
        Hardware("IMU", already_on_most_drones=True),
    ])
    exotic = SensorRequirement(hardware=[
        Hardware("camera", already_on_most_drones=True),
        Hardware("cold-atom gravimeter", approx_cost_usd=2_000_000),
    ])
    assert common.needs_only_common_hardware is True
    assert exotic.needs_only_common_hardware is False
    assert SensorRequirement().needs_only_common_hardware is False, (
        "a layer declaring no hardware must not pass as buildable today")
    print("[ok] one exotic component is enough to fail the common-hardware flag")
    PASSED.append("common")


def test_both_clean_layers_are_buildable_today():
    """These two were chosen to need nothing a drone does not already carry."""
    for cls in DECLARED:
        req = requirement_of(cls())
        assert req.needs_only_common_hardware, (
            f"{cls.__name__} needs uncommon hardware")
        cost = req.build_cost_usd
        print(f"      {cls.__name__}: ${cost:,.0f} of common kit")
    print("[ok] both no-fabrication layers run on hardware a drone already has")
    PASSED.append("buildable")


def test_reference_data_provenance_is_carried():
    req = requirement_of(LandmarkChainLayer())
    refs = req.reference_data
    assert refs, "landmark layer must declare its chart requirement"
    text = refs[0].describe()
    assert "Survey of India" in text
    assert "must be supplied" in text, "a chart nobody ships must say so"
    print(f"[ok] provenance carried: {text[:78]}...")
    PASSED.append("provenance")


def test_as_dict_round_trips_for_the_doc_generator():
    d = requirement_of(LandmarkChainLayer()).as_dict()
    assert set(d) == {"hardware", "inputs", "reference_data",
                      "preconditions", "notes"}
    assert d["hardware"] and d["inputs"] and d["preconditions"]
    assert all(isinstance(h["name"], str) for h in d["hardware"])
    print(f"[ok] as_dict gives the generator {len(d['hardware'])} hardware, "
          f"{len(d['inputs'])} inputs, {len(d['preconditions'])} preconditions")
    PASSED.append("as_dict")


def test_layers_without_a_declaration_return_none():
    class Bare:
        pass
    assert requirement_of(Bare()) is None

    class Wrong:
        REQUIRES = "a camera, probably"
    assert requirement_of(Wrong()) is None, (
        "a string is not a declaration and must not be treated as one")
    print("[ok] undeclared and malformed requirements both return None")
    PASSED.append("undeclared")


if __name__ == "__main__":
    tests = [
        test_declared_feed_methods_exist,
        test_refusal_names_what_is_missing,
        test_describe_missing_drops_what_is_supplied,
        test_unstated_requirement_says_so,
        test_build_cost_needs_every_price,
        test_common_hardware_flag_is_strict,
        test_both_clean_layers_are_buildable_today,
        test_reference_data_provenance_is_carried,
        test_as_dict_round_trips_for_the_doc_generator,
        test_layers_without_a_declaration_return_none,
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

    print(f"\n{len(PASSED)}/{len(tests)} sensor-requirement tests passed")
    if failed:
        for n, e in failed:
            print(f"  FAILED {n}: {e}")
        sys.exit(1)
    print("all sensor-requirement tests passed")
