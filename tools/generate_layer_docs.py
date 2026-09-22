"""
Generate a README for every navigation layer, and the root index over them.

The point is not tidiness. A repo with 139 layers, most of which cannot
currently produce a position because the hardware does not exist yet, is
indistinguishable from a repo with 139 broken layers unless something says
which is which, per layer, truthfully.

So each page is built from three sources, none of them prose someone has to
remember to update:

  metadata       the layer's own declared identity -- number, group,
                 capabilities, accuracy rating -- read off the instance

  requirements   its SensorRequirement, if it has declared one: the hardware,
                 the live inputs and the reference data it needs, with costs
                 and provenance

  behaviour      what the layer actually does right now when constructed and
                 read with nothing attached, measured by running it

That last one is what makes these pages worth reading. A page that says a
layer is clean because someone typed that it was clean is worthless. A page
that says it because the layer was just run twice and returned the same
answer both times is evidence.

Pages are regenerated, never hand-edited. Anything written into one by hand
is lost on the next run, which is the correct trade: a stale page that lies
about a layer's status is worse than no page.

Run: python tools/generate_layer_docs.py
Out: docs/layers/<layer_id>.md, one per layer, plus README.md at the root.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import inspect
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from upin.core.no_fabrication import (  # noqa: E402
    describe_reading, probe_determinism,
)
from upin.core.sensor_requirements import (  # noqa: E402
    SensorRequirement, requirement_of,
)

DOCS = REPO / "docs" / "layers"

GROUP_NAMES = {
    "A": "Satellite & Celestial",
    "B": "Inertial & Timing",
    "C": "Magnetic & Quantum",
    "D": "RF & Terrestrial",
    "E": "Optical & Vision",
    "F": "Acoustic",
    "G": "Gravity",
    "H": "Chemical, Seismic & Flow",
    "I": "Cosmic & Atmospheric",
    "J": "Human & Crowd",
    "K": "Systems Intelligence",
    "Q": "Quantum Navigation",
}

# Status, worst first. The wording is deliberately plain; these strings end up
# in front of anyone deciding what to trust.
STATUS = {
    "FABRICATES": (
        "Invents a reading when nothing is connected, and invents a different "
        "one each time it is read."),
    "PLACEHOLDER": (
        "Returns the same fixed reading whenever nothing is connected. Not "
        "random, but not measured either."),
    "DECLINES": (
        "Reports no fix when it has no input, and says what is missing. "
        "Honours the no-fabrication contract."),
    "UNKNOWN": "Could not be run.",
}

# A layer that reports a velocity of 49.68 m/s having been given nothing is
# fabricating just as surely as one that reports a latitude. The probe checks
# every field a reading can carry, not only the position.
_MEASURED_FIELDS = ("position", "velocity", "heading")


@dataclass
class LayerFacts:
    layer_id: str
    class_name: str
    number: int
    group: str
    name: str
    description: str
    capabilities: List[str]
    accuracy_rating: float
    is_novel: bool
    bio_inspiration: str
    docstring: str
    source_file: str
    declares_contract: bool
    requirement: Optional[SensorRequirement]
    status: str
    behaviour_detail: str
    live_mode: str


def probe(layer_id: str, cls) -> LayerFacts:
    """Build a layer's facts by inspecting it and then running it."""
    layer = cls()
    try:
        source_file = str(Path(inspect.getfile(cls)).relative_to(REPO))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        source_file = "unknown"

    status, detail = "UNKNOWN", "layer could not be constructed or read"
    try:
        layer.initialize()
        a = layer.read()
        drifted = probe_determinism(layer, reads=3)
        if a is None:
            status, detail = "UNKNOWN", "read() returned None"
        elif not getattr(a, "is_valid", True):
            status = "DECLINES"
            why = (a.raw_data or {}).get("no_fix_reason", "unstated")
            says = (a.raw_data or {}).get("detail", "")
            detail = f"declines with `{why}`" + (f" — {says}" if says else "")
        else:
            reported = describe_reading(a)
            if drifted:
                status = "FABRICATES"
                detail = (f"returned {reported}, then a different "
                          f"{' and '.join(drifted)} on the very next read, "
                          f"from the same (absent) input")
            else:
                status = "PLACEHOLDER"
                detail = f"returns {reported} every time, with no input"
    except NotImplementedError:
        status, detail = "UNKNOWN", "read() raises NotImplementedError"
    except Exception as exc:
        status, detail = "UNKNOWN", f"read() raised {type(exc).__name__}"

    live = ""
    try:
        probe_layer = cls()
        probe_layer.initialize()
        probe_layer.set_simulation_mode(False)
        r = probe_layer.read()
        if r is None:
            live = "returns None"
        elif r.position is not None and getattr(r, "is_valid", True):
            live = "still returns a position"
        elif not getattr(r, "is_valid", True):
            live = "declines cleanly"
        else:
            live = "valid but positionless"
    except NotImplementedError:
        live = "raises NotImplementedError"
    except Exception as exc:
        live = f"raises {type(exc).__name__}"

    return LayerFacts(
        layer_id=layer_id,
        class_name=cls.__name__,
        number=getattr(layer, "layer_number", 0),
        group=getattr(layer.group, "value", "?"),
        name=getattr(layer, "name", cls.__name__),
        description=getattr(layer, "description", ""),
        capabilities=[c.name for c in getattr(layer, "capabilities", [])],
        accuracy_rating=float(getattr(layer, "_accuracy_rating", 0.0) or 0.0),
        is_novel=bool(getattr(layer, "is_novel", False)),
        bio_inspiration=getattr(layer, "bio_inspiration", ""),
        docstring=inspect.getdoc(cls) or "",
        source_file=source_file,
        declares_contract=bool(getattr(cls, "NO_FABRICATION", False)),
        requirement=requirement_of(layer),
        status=status,
        behaviour_detail=detail,
        live_mode=live,
    )


def requirements_section(req: Optional[SensorRequirement]) -> List[str]:
    if req is None:
        return [
            "## What this layer needs",
            "",
            "**Not yet declared.** This layer has no `REQUIRES` declaration, so "
            "the repo cannot say what hardware or data would bring it to life. "
            "Adding one is part of cleaning the layer up — see "
            "[`FABRICATION_AUDIT.md`](../../FABRICATION_AUDIT.md).",
            "",
        ]

    L = ["## What this layer needs", ""]

    if req.hardware:
        L += ["### Hardware", "",
              "| Component | Why | Typical part | Approx cost | Common on drones |",
              "|---|---|---|---|---|"]
        for h in req.hardware:
            cost = f"${h.approx_cost_usd:,.0f}" if h.approx_cost_usd is not None else "—"
            L.append(f"| {h.name} | {h.why or '—'} | {h.typical_part or '—'} | "
                     f"{cost} | {'yes' if h.already_on_most_drones else 'no'} |")
        total = req.build_cost_usd
        if total is not None:
            L += ["", f"**Approximate hardware cost: ${total:,.0f}.**"
                      + ("  Every component is already carried by a typical "
                         "drone, so this layer could be brought up today."
                         if req.needs_only_common_hardware else "")]
        L.append("")

    if req.inputs:
        L += ["### Live inputs", "",
              "| Input | Units | Supplied via | Why |", "|---|---|---|---|"]
        for i in req.inputs:
            feed = f"`{i.feed_method}()`" if i.feed_method else "—"
            L.append(f"| {i.name} | {i.units or '—'} | {feed} | {i.why or '—'} |")
        L.append("")

    if req.reference_data:
        L += ["### Reference data", "",
              "| Data | Source | Ships with the repo | Why |", "|---|---|---|---|"]
        for r in req.reference_data:
            L.append(f"| {r.name} | {r.source or '—'} | "
                     f"{'yes' if r.bundled else '**no — must be supplied**'} | "
                     f"{r.why or '—'} |")
        L.append("")

    if req.preconditions:
        L += ["### Conditions that must hold", "",
              "Even with every sensor attached, this layer declines unless:", ""]
        L += [f"- {c}" for c in req.preconditions]
        L.append("")

    if req.notes:
        L += ["### Notes", "", req.notes, ""]

    return L


def render_layer(f: LayerFacts) -> str:
    L: List[str] = []
    L.append(f"# {f.name}")
    L.append("")
    L.append(f"`{f.layer_id}` · Layer {f.number} · "
             f"Group {f.group} — {GROUP_NAMES.get(f.group, 'Unclassified')}")
    L.append("")
    if f.description:
        L += [f"> {f.description}", ""]

    L += ["## Current status", "",
          f"**{f.status}** — {STATUS.get(f.status, '')}", "",
          f"Measured by constructing this layer with nothing attached and "
          f"reading it three times: {f.behaviour_detail}.", ""]
    if f.live_mode:
        L += [f"With simulation switched off it {f.live_mode}.", ""]
    if f.declares_contract:
        L += ["This layer declares `NO_FABRICATION = True` and is held to the "
              "contract in [`upin/core/no_fabrication.py`]"
              "(../../upin/core/no_fabrication.py) by tests.", ""]

    L += requirements_section(f.requirement)

    L += ["## Details", "",
          "| | |", "|---|---|",
          f"| Class | `{f.class_name}` |",
          f"| Source | [`{f.source_file}`](../../{f.source_file}) |",
          f"| Capabilities | {', '.join(f.capabilities) or '—'} |",
          f"| Accuracy rating | {f.accuracy_rating:.2f} |",
          f"| Novel | {'yes' if f.is_novel else 'no'} |"]
    if f.bio_inspiration:
        L.append(f"| Bio-inspiration | {f.bio_inspiration} |")
    L.append("")

    if f.docstring:
        L += ["## How it works", "", "```", f.docstring.strip(), "```", ""]

    L += ["---", "",
          "*Generated by `tools/generate_layer_docs.py`. Do not edit by hand — "
          "regenerate instead. The status above is measured at generation "
          "time, not asserted.*"]
    return "\n".join(L) + "\n"


def render_root(facts: List[LayerFacts]) -> str:
    by_group: Dict[str, List[LayerFacts]] = defaultdict(list)
    for f in facts:
        by_group[f.group].append(f)

    counts = defaultdict(int)
    for f in facts:
        counts[f.status] += 1
    declared = sum(1 for f in facts if f.requirement is not None)

    L = ["# UPIN — Universal Positioning Intelligence Network", "",
         "GPS-denied navigation built from many independent layers, each "
         "computing a position from a different physical principle, fused and "
         "cross-checked against each other.", "",
         "Patent-pending. AIMCRS / Abheet Prem Manghnani.", "",
         "## Honest status", "",
         "This table is measured, not claimed. Every layer below was "
         "constructed with nothing attached and read three times; what it did "
         "is what is recorded.", "",
         "| Status | Layers | Meaning |", "|---|---:|---|"]
    for key in ("DECLINES", "PLACEHOLDER", "FABRICATES", "UNKNOWN"):
        if counts[key]:
            L.append(f"| **{key}** | {counts[key]} | {STATUS[key]} |")
    L += ["",
          f"**{counts['DECLINES']} of {len(facts)} layers** currently refuse to "
          f"invent a position. **{declared} of {len(facts)}** have declared what "
          f"hardware and data they need.", "",
          "The gap between those numbers and the total is the work tracked in "
          "[`FABRICATION_AUDIT.md`](FABRICATION_AUDIT.md), which explains what "
          "each fabricating layer does and what it would cost in flight.", "",
          "> **Not flight-proven.** No claim of jamming resistance or field "
          "performance is made here. Layers that cannot yet produce a position "
          "say so, per layer, on their own page.", "",
          "## Documents", "",
          "| | |", "|---|---|",
          "| [`FABRICATION_AUDIT.md`](FABRICATION_AUDIT.md) | Every place the "
          "code invents a number, what it costs, and the staged plan to remove it |",
          "| [`UPIN_MASTER.md`](UPIN_MASTER.md) | The full project document |",
          "| [`QUANTUM.md`](QUANTUM.md) | Group Q hardware readiness and patent "
          "sequencing |",
          "| [`LAYER_GUIDE.md`](LAYER_GUIDE.md) | Layer-by-layer narrative guide |",
          "| [`LAYER_INDEX.md`](LAYER_INDEX.md) | Generated code index |", "",
          "## The layers", ""]

    badge = {"DECLINES": "clean", "PLACEHOLDER": "placeholder",
             "FABRICATES": "fabricates", "UNKNOWN": "unknown"}

    for g in sorted(by_group):
        group_layers = sorted(by_group[g], key=lambda f: f.number)
        clean = sum(1 for f in group_layers if f.status == "DECLINES")
        L += [f"### Group {g} — {GROUP_NAMES.get(g, 'Unclassified')} "
              f"({len(group_layers)} layers, {clean} clean)", "",
              "| # | Layer | ID | Status | Needs declared |",
              "|---:|---|---|---|---|"]
        for f in group_layers:
            L.append(f"| {f.number} | [{f.name}](docs/layers/{f.layer_id}.md) | "
                     f"`{f.layer_id}` | {badge[f.status]} | "
                     f"{'yes' if f.requirement else 'no'} |")
        L.append("")

    L += ["---", "",
          "*The layer table and every page under `docs/layers/` are generated "
          "by `tools/generate_layer_docs.py`. Re-run it after changing any "
          "layer.*"]
    return "\n".join(L) + "\n"


def main():
    from upin.layers.registry import ALL_LAYER_CLASSES

    DOCS.mkdir(parents=True, exist_ok=True)
    facts: List[LayerFacts] = []
    for layer_id, cls in sorted(ALL_LAYER_CLASSES.items()):
        f = probe(layer_id, cls)
        facts.append(f)
        (DOCS / f"{layer_id}.md").write_text(render_layer(f), encoding="utf-8")

    (REPO / "README.md").write_text(render_root(facts), encoding="utf-8")

    counts = defaultdict(int)
    for f in facts:
        counts[f.status] += 1
    print(f"wrote {len(facts)} layer pages to docs/layers/ and README.md")
    for k in ("DECLINES", "PLACEHOLDER", "FABRICATES", "UNKNOWN"):
        if counts[k]:
            print(f"  {k:<12} {counts[k]:>4}")
    print(f"  requirements declared: "
          f"{sum(1 for f in facts if f.requirement is not None)}/{len(facts)}")


if __name__ == "__main__":
    main()
