"""
What a layer needs before it can produce a position.

A navigation layer that reports nothing is not obviously different from a
navigation layer that is broken. Both are silent. The difference matters
enormously to whoever has to get the aircraft flying: one needs a
magnetometer plugged in, the other needs fixing.

So every layer declares its requirements as data rather than describing them
in a docstring nobody parses. One declaration feeds three things that would
otherwise drift apart:

  the refusal      no_fix() can say *what* is missing, not merely that
                   something is. "needs a magnetometer (none attached)" is
                   an instruction; "sensor_unavailable" is a shrug.

  the README       each layer's generated page lists its hardware, its live
                   inputs and its reference data, so the repo answers "what
                   would it take to make this work?" without reading code.

  the dashboard    readiness across all layers, computed rather than
                   claimed, so nobody has to maintain a spreadsheet that
                   goes stale the moment a layer changes.

WHY THIS IS NOT JUST DOCUMENTATION

A layer whose requirements are declared can be *asked* whether they are met.
`missing_from()` takes whatever the layer has actually been given and returns
the gap. That turns a comment into a check, and a check is the thing that
stops a layer quietly deciding it has enough to guess with.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class Hardware:
    """One piece of physical kit a layer cannot work without.

    `typical_part` and `approx_cost_usd` are there because "needs a
    gravimeter" and "needs a 2 million dollar cold-atom gravimeter" are very
    different sentences to an operator planning a build.
    """
    name: str
    why: str = ""
    typical_part: str = ""
    approx_cost_usd: Optional[float] = None
    already_on_most_drones: bool = False

    def describe(self) -> str:
        detail = []
        if self.typical_part:
            detail.append(f"e.g. {self.typical_part}")
        if self.approx_cost_usd is not None:
            detail.append(f"~${self.approx_cost_usd:,.0f}")
        return f"{self.name} ({', '.join(detail)})" if detail else self.name


@dataclass(frozen=True)
class DataInput:
    """A live input the layer consumes each cycle, and how it arrives.

    `feed_method` names the method a caller uses to supply it. That is what
    makes this checkable rather than decorative: the simulation harness and
    any real driver both drive a layer through the same named door.
    """
    name: str
    feed_method: str = ""
    units: str = ""
    why: str = ""

    def describe(self) -> str:
        s = self.name
        if self.units:
            s += f" [{self.units}]"
        if self.feed_method:
            s += f" via {self.feed_method}()"
        return s


@dataclass(frozen=True)
class ReferenceData:
    """A map, chart, almanac or database the layer matches against.

    `source` carries provenance. For UPIN that is a hard constraint, not a
    nicety: Indian sources only, and a layer that needs a basemap has to say
    which one.
    """
    name: str
    source: str = ""
    why: str = ""
    bundled: bool = False        # ships with the repo, or must be supplied

    def describe(self) -> str:
        s = self.name
        if self.source:
            s += f" from {self.source}"
        s += " (bundled)" if self.bundled else " (must be supplied)"
        return s


@dataclass
class SensorRequirement:
    """Everything one layer needs before it can honestly report a position."""

    hardware: Sequence[Hardware] = field(default_factory=tuple)
    inputs: Sequence[DataInput] = field(default_factory=tuple)
    reference_data: Sequence[ReferenceData] = field(default_factory=tuple)
    preconditions: Sequence[str] = field(default_factory=tuple)
    """Geometric or environmental conditions that must hold, e.g. "at least
    two bearings with a cut angle above 15 degrees" or "clear sky". These are
    the things that make a layer decline even with every sensor attached."""

    notes: str = ""

    # -- querying ---------------------------------------------------

    @property
    def feed_methods(self) -> List[str]:
        """The named doors through which real or simulated data arrives."""
        return [i.feed_method for i in self.inputs if i.feed_method]

    def missing_from(self, layer) -> List[str]:
        """Which declared inputs this layer has no way to receive.

        Checks that every declared feed_method actually exists on the layer.
        A requirement naming a method the layer does not have is a broken
        declaration, and it is better to find that here than in the field.
        """
        return [i.feed_method for i in self.inputs
                if i.feed_method and not callable(getattr(layer, i.feed_method, None))]

    def describe_missing(self, have: Optional[Iterable[str]] = None) -> str:
        """One sentence naming what is not yet present.

        `have` is the set of input names the caller has actually supplied.
        Passing nothing means nothing has been supplied, which is the common
        case for a layer with no hardware attached.
        """
        supplied = set(have or ())
        wanted = [i for i in self.inputs if i.name not in supplied]

        parts: List[str] = []
        if self.hardware:
            parts.append("needs " + ", ".join(h.name for h in self.hardware))
        if wanted:
            parts.append("no " + ", ".join(i.describe() for i in wanted))
        if self.reference_data:
            unbundled = [r for r in self.reference_data if not r.bundled]
            if unbundled:
                parts.append("requires " + ", ".join(r.name for r in unbundled))
        if not parts:
            return "requirements unstated"
        return "; ".join(parts)

    def as_dict(self) -> Dict:
        """Flat form, for the doc generator and the readiness dashboard."""
        return {
            "hardware": [
                {"name": h.name, "why": h.why, "typical_part": h.typical_part,
                 "approx_cost_usd": h.approx_cost_usd,
                 "already_on_most_drones": h.already_on_most_drones}
                for h in self.hardware
            ],
            "inputs": [
                {"name": i.name, "feed_method": i.feed_method,
                 "units": i.units, "why": i.why}
                for i in self.inputs
            ],
            "reference_data": [
                {"name": r.name, "source": r.source, "why": r.why,
                 "bundled": r.bundled}
                for r in self.reference_data
            ],
            "preconditions": list(self.preconditions),
            "notes": self.notes,
        }

    @property
    def build_cost_usd(self) -> Optional[float]:
        """What the hardware would cost, when every piece has a price on it."""
        costs = [h.approx_cost_usd for h in self.hardware]
        if not costs or any(c is None for c in costs):
            return None
        return float(sum(costs))

    @property
    def needs_only_common_hardware(self) -> bool:
        """True when every piece of kit is already on a typical drone.

        The layers for which this holds are the ones that could be brought up
        today, and they are worth knowing apart from the ones waiting on a
        cold-atom interferometer.
        """
        return bool(self.hardware) and all(
            h.already_on_most_drones for h in self.hardware)


def requirement_of(layer) -> Optional[SensorRequirement]:
    """The declaration on a layer, or None if it has not made one yet."""
    req = getattr(layer, "REQUIRES", None)
    return req if isinstance(req, SensorRequirement) else None
