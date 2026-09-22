"""
The no-fabrication contract.

An audit of this codebase found 396 places where a layer, given no real
sensor input, still returns a position — `_sim_lat + gaussian_noise`, with a
hardcoded Chennai default underneath. That is fine for exercising a
simulation. It is dangerous in a navigation system, because a fabricated
position is indistinguishable downstream from a measured one: the fusion
engine weights it, the operator sees it, and nothing in the data says it was
invented.

This module defines the stricter standard that new layers are held to, and
gives the audit a mechanical way to check it rather than a stylistic one.

THE CONTRACT

  1. NO INPUT, NO POSITION
     A layer with insufficient real input returns is_valid=False and states
     why in raw_data["no_fix_reason"]. It does not guess.

  2. EVERY NUMBER TRACES TO AN INPUT
     A returned position is a deterministic function of data the caller
     actually supplied — commands, detections, ranges, a calibration fitted
     to real flight logs. Nothing is conjured.

  3. NO RANDOMNESS IN THE POSITION PATH
     Sensor noise belongs in a simulator, injected by the test harness at the
     input. It does not belong inside a layer, because a layer that adds its
     own noise is manufacturing precision it does not have.

  4. CONFIDENCE REFLECTS EVIDENCE
     Confidence is computed from the geometry and quality of the actual
     measurements. It is not a constant chosen to look plausible.

WHY DETERMINISM IS THE TEST

Rules 2 and 3 have an observable consequence: feed a compliant layer the
same inputs twice and it must return bit-identical output. A layer that
fabricates cannot pass that, because the fabrication is what varies. So the
audit does not read the source and judge style — it runs the layer twice and
compares. That is a proof, not an opinion.

Compliant layers declare themselves by setting NO_FABRICATION = True and are
then held to it by tests. Existing layers are untouched; this is a standard
for what gets built from here, not a retrofit.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from upin.core.layer_base import LayerReading


class NoFixReason:
    """Why a compliant layer declined to produce a position.

    These strings appear in raw_data["no_fix_reason"] and are part of the
    contract: an operator reading a log can tell a missing sensor from a
    missing calibration from a geometry that was simply too poor to solve.
    """
    NO_CALIBRATION = "no_calibration"          # model never fitted to real data
    NO_INPUT = "no_input"                      # nothing supplied this cycle
    INSUFFICIENT_INPUT = "insufficient_input"  # some data, not enough to solve
    NO_ANCHOR = "no_anchor"                    # no known starting position
    STALE_INPUT = "stale_input"                # data too old to trust
    POOR_GEOMETRY = "poor_geometry"            # solvable in principle, ill-conditioned
    DIVERGED = "diverged"                      # solver failed to converge
    SENSOR_UNAVAILABLE = "sensor_unavailable"  # hardware absent or failed


@dataclass
class ComplianceResult:
    """Outcome of auditing one layer against the contract."""
    layer_id: str
    declares_contract: bool
    deterministic: Optional[bool]        # None when it could not be tested
    declines_without_input: Optional[bool]
    states_reason: Optional[bool]
    compliant: bool
    detail: str = ""


def no_fix(layer_id: str, reason: str, detail: str = "",
           **extra: Any) -> LayerReading:
    """Build the reading a compliant layer returns when it cannot solve.

    is_valid=False and position=None, so the fusion engine drops it rather
    than weighting an invented number. The reason travels with it.
    """
    raw: Dict[str, Any] = {"no_fix_reason": reason, "fabricated": False}
    if detail:
        raw["detail"] = detail
    raw.update(extra)
    return LayerReading(
        layer_id=layer_id,
        position=None,
        self_confidence=0.0,
        is_valid=False,
        raw_data=raw,
    )


def audit_layer(layer, sample_inputs: Optional[Dict] = None) -> ComplianceResult:
    """Check one layer against the contract by running it, not by reading it.

    Two mechanical checks:

      declines_without_input   a freshly initialised layer with nothing fed
                               to it must return is_valid=False

      deterministic            given identical inputs, two reads must be
                               bit-identical — which a fabricating layer
                               cannot manage

    `sample_inputs` is unused for layers whose state is loaded through their
    own methods; the caller primes the layer before passing it in.
    """
    layer_id = getattr(layer, "layer_id", layer.__class__.__name__)
    declares = bool(getattr(layer, "NO_FABRICATION", False))

    try:
        layer.initialize()
    except Exception as exc:  # pragma: no cover - defensive
        return ComplianceResult(layer_id, declares, None, None, None, False,
                                f"initialize() raised {exc!r}")

    # Check 1: does it decline when it has nothing?
    declines: Optional[bool]
    states_reason: Optional[bool]
    try:
        bare = layer.read()
        declines = (bare is not None and not bare.is_valid
                    and bare.position is None)
        states_reason = bool(bare is not None and bare.raw_data
                             and bare.raw_data.get("no_fix_reason"))
    except NotImplementedError:
        declines, states_reason = None, None
    except Exception as exc:  # pragma: no cover - defensive
        return ComplianceResult(layer_id, declares, None, False, False, False,
                                f"read() raised {exc!r} on an empty layer")

    # Check 2: is it deterministic given identical state?
    deterministic: Optional[bool]
    try:
        a = layer.read()
        b = layer.read()
        deterministic = _readings_match(a, b)
    except NotImplementedError:
        deterministic = None
    except Exception:  # pragma: no cover - defensive
        deterministic = False

    compliant = bool(declares and declines and states_reason
                     and deterministic is not False)

    bits = []
    if not declares:
        bits.append("does not declare NO_FABRICATION")
    if declines is False:
        bits.append("returns a position with no input")
    if states_reason is False:
        bits.append("declines without saying why")
    if deterministic is False:
        bits.append("non-deterministic on identical input")

    return ComplianceResult(
        layer_id=layer_id,
        declares_contract=declares,
        deterministic=deterministic,
        declines_without_input=declines,
        states_reason=states_reason,
        compliant=compliant,
        detail="; ".join(bits) if bits else "compliant",
    )


def fields_that_changed(a: Optional[LayerReading],
                        b: Optional[LayerReading]) -> List[str]:
    """Which measured fields differ between two reads of the same state.

    This is the mechanical test the whole contract rests on. Nothing varied
    on the way in, so whatever varied on the way out was manufactured inside
    the layer.

    It deliberately looks past the position. A layer reporting a velocity of
    49.68 m/s having been given nothing is fabricating exactly as surely as
    one reporting a latitude, and for a long time the audits only looked at
    latitude and let the velocity layers through.
    """
    if a is None or b is None:
        return [] if a is b else ["reading"]
    changed: List[str] = []
    if (a.position is None) != (b.position is None):
        changed.append("position")
    elif a.position is not None and b.position is not None:
        if (a.position.latitude != b.position.latitude
                or a.position.longitude != b.position.longitude
                or a.position.altitude != b.position.altitude
                or a.position.accuracy_m != b.position.accuracy_m):
            changed.append("position")
    if a.velocity != b.velocity:
        changed.append("velocity")
    if a.heading != b.heading:
        changed.append("heading")
    if a.self_confidence != b.self_confidence:
        changed.append("confidence")
    if a.is_valid != b.is_valid:
        changed.append("validity")
    return changed


def probe_determinism(layer, reads: int = 3) -> List[str]:
    """Read a layer several times unchanged and report what refused to hold still.

    Two reads is the minimum, but it is not enough. A layer drawing from a
    coarse distribution can return the same value twice by luck, and then a
    fabricator is recorded as a placeholder. Reading three times and comparing
    every read against the first makes that coincidence much less likely
    without making the check any less mechanical.

    Returns the union of fields that varied. Empty means the layer held still.
    """
    first = layer.read()
    changed: List[str] = []
    for _ in range(max(1, reads - 1)):
        for f in fields_that_changed(first, layer.read()):
            if f not in changed:
                changed.append(f)
    return changed


def describe_reading(r: Optional[LayerReading]) -> str:
    """The measured parts of a reading, in words."""
    if r is None:
        return "nothing"
    bits = []
    if r.position is not None:
        bits.append(f"{r.position.latitude:.5f}, {r.position.longitude:.5f}")
    if r.velocity is not None:
        bits.append(f"{r.velocity:.2f} m/s")
    if r.heading is not None:
        bits.append(f"heading {r.heading:.1f} deg")
    return ", ".join(bits) if bits else "a reading with no measured field"


def _readings_match(a: Optional[LayerReading],
                    b: Optional[LayerReading]) -> bool:
    """Bit-identical comparison of the parts that matter."""
    if a is None or b is None:
        return a is b
    if a.is_valid != b.is_valid:
        return False
    if (a.position is None) != (b.position is None):
        return False
    if a.position is not None and b.position is not None:
        if (a.position.latitude != b.position.latitude
                or a.position.longitude != b.position.longitude
                or a.position.altitude != b.position.altitude
                or a.position.accuracy_m != b.position.accuracy_m):
            return False
    if a.self_confidence != b.self_confidence:
        return False
    if a.velocity != b.velocity or a.heading != b.heading:
        return False
    return True
