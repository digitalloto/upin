"""
Fabrication audit — find every place UPIN invents a number and report what
that invention would do to a real flight.

Two passes, because neither alone is enough.

STATIC PASS reads the source with Python's own parser and asks, for every
read() that a navigation layer exposes: does a random number reach the
latitude and longitude this layer reports? Is there a hardcoded coordinate
standing in for a real one? Does the layer have any path at all that uses a
sensor? Parsing is exact where grep is not — it can tell a random draw that
lands in a Position from one that lands in a log message.

DYNAMIC PASS runs every registered layer with nothing connected to it and
watches what comes back. A layer that returns a valid position when no
sensor has said anything is fabricating, whatever the source looks like.
Reading twice and comparing catches the rest: a layer whose answer changes
while its inputs do not is manufacturing the difference.

SEVERITY is about consequence, not about tidiness.

  CRITICAL  an invented position reaches the fusion engine, which cannot
            tell it from a measured one and weights it accordingly
  HIGH      a hardcoded coordinate is reported as a fix, so the system
            claims to know where it is when it does not
  MEDIUM    the position is real enough but the confidence or accuracy
            beside it is invented, which corrupts how it is weighted
  LOW       invented numbers appear in raw_data only, where they mislead an
            operator reading a log but do not move the aircraft
  OK        randomness that belongs: the simulator, a quantum RNG, a
            stochastic algorithm that needs it

Run: python tools/fabrication_audit.py [--markdown FABRICATION_AUDIT.md]

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RANDOM_ATTRS = {
    "normal", "uniform", "gauss", "randint", "random", "choice", "rand",
    "randn", "poisson", "exponential", "lognormal", "shuffle", "sample",
    "triangular", "betavariate", "standard_normal", "integers", "binomial",
}

# Coordinates that appear as stand-ins for a position nobody measured.
HARDCODED_COORDS = {
    13.0827: "Chennai latitude",
    80.2707: "Chennai longitude",
    19.0760: "Mumbai latitude",
    72.8777: "Mumbai longitude",
    28.6139: "Delhi latitude",
    77.2090: "Delhi longitude",
}

# Modules where randomness is the job rather than a defect.
LEGITIMATE_MODULES = {
    "upin/simulation/world.py": "the simulator — inventing a world is its purpose",
    "upin/quantum/algorithms.py": "quantum RNG and stochastic optimisation",
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "OK"]


# ---------------------------------------------------------------------------
# Static pass
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """One place that invents a number, and what it costs."""
    file: str
    line: int
    layer_id: str
    class_name: str
    function: str
    severity: str
    category: str
    snippet: str
    effect: str
    fix: str

    def key(self):
        return (SEVERITY_ORDER.index(self.severity), self.file, self.line)


def _is_random_call(node: ast.AST) -> bool:
    """Is this expression a draw from a random number generator?"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in RANDOM_ATTRS:
        # np.random.normal(...), rng.uniform(...), random.gauss(...)
        owner = func.value
        chain = []
        while isinstance(owner, ast.Attribute):
            chain.append(owner.attr)
            owner = owner.value
        if isinstance(owner, ast.Name):
            chain.append(owner.id)
        return any(c in ("random", "np", "numpy", "rng", "_rng") for c in chain)
    return False


def _contains_random(node: ast.AST) -> bool:
    return any(_is_random_call(n) for n in ast.walk(node))


def _hardcoded_coords_in(node: ast.AST) -> Set[float]:
    found = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, float):
            if round(n.value, 4) in {round(k, 4) for k in HARDCODED_COORDS}:
                for k in HARDCODED_COORDS:
                    if abs(n.value - k) < 1e-4:
                        found.add(k)
    return found


def _position_calls(node: ast.AST) -> List[ast.Call]:
    """Every Position(...) constructed inside this node."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "Position":
            out.append(n)
    return out


def _layer_id_of(cls: ast.ClassDef) -> str:
    """Pull layer_id="..." out of the super().__init__ call."""
    for n in ast.walk(cls):
        if isinstance(n, ast.keyword) and n.arg == "layer_id":
            if isinstance(n.value, ast.Constant):
                return str(n.value.value)
    return ""


def _declares_no_fabrication(cls: ast.ClassDef) -> bool:
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == "NO_FABRICATION":
                    return bool(getattr(stmt.value, "value", False))
    return False


def _source_line(lines: List[str], lineno: int) -> str:
    if 0 < lineno <= len(lines):
        return lines[lineno - 1].strip()[:110]
    return ""


def scan_file(path: Path) -> List[Finding]:
    rel = str(path.relative_to(REPO))
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError):
        return []
    lines = src.splitlines()
    findings: List[Finding] = []

    legit_reason = LEGITIMATE_MODULES.get(rel)

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        layer_id = _layer_id_of(cls)
        if _declares_no_fabrication(cls):
            continue                     # already held to the contract

        for fn in [n for n in cls.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            reports_position = fn.name in ("read", "get_position", "get_reading")

            # -- randomness that reaches a reported position ---------------
            for pos_call in _position_calls(fn):
                lat_lon_random = False
                for kw in pos_call.keywords:
                    if kw.arg in ("latitude", "longitude", "altitude") \
                            and _contains_random(kw.value):
                        lat_lon_random = True
                if lat_lon_random:
                    findings.append(Finding(
                        rel, pos_call.lineno, layer_id, cls.name, fn.name,
                        "OK" if legit_reason else "CRITICAL",
                        "random_position",
                        _source_line(lines, pos_call.lineno),
                        legit_reason or
                        "The reported latitude/longitude is a random draw. The "
                        "fusion engine cannot distinguish it from a measured "
                        "fix, so it is weighted, averaged in, and shown to the "
                        "operator as a position.",
                        "Return no_fix(layer_id, NoFixReason.SENSOR_UNAVAILABLE) "
                        "when no sensor is attached; move the noise into the "
                        "simulator and inject it at the input.",
                    ))

                # -- invented accuracy on a position ------------------------
                for kw in pos_call.keywords:
                    if kw.arg == "accuracy_m" and isinstance(kw.value, ast.Constant):
                        findings.append(Finding(
                            rel, pos_call.lineno, layer_id, cls.name, fn.name,
                            "OK" if legit_reason else "MEDIUM",
                            "constant_accuracy",
                            _source_line(lines, pos_call.lineno),
                            legit_reason or
                            "accuracy_m is a literal, not a computed "
                            "uncertainty. Fusion weights layers by their stated "
                            "accuracy, so a flattering constant makes this layer "
                            "outvote layers that report honestly.",
                            "Compute accuracy from the geometry and noise of the "
                            "actual measurement, as landmark_chain does from the "
                            "solve covariance.",
                        ))

            # -- hardcoded coordinates -------------------------------------
            coords = _hardcoded_coords_in(fn)
            if coords and reports_position:
                for n in ast.walk(fn):
                    if isinstance(n, ast.Constant) and isinstance(n.value, float) \
                            and any(abs(n.value - c) < 1e-4 for c in coords):
                        findings.append(Finding(
                            rel, n.lineno, layer_id, cls.name, fn.name,
                            "OK" if legit_reason else "HIGH",
                            "hardcoded_coordinate",
                            _source_line(lines, n.lineno),
                            legit_reason or
                            f"A literal coordinate ({HARDCODED_COORDS.get(round(n.value, 4), 'known city')}) "
                            "stands in for a position nobody measured. In the "
                            "field this makes the aircraft claim to be in a city "
                            "it is not in, with no indication the value was "
                            "invented.",
                            "Delete the default. With no anchor the layer must "
                            "return no_fix(NoFixReason.NO_ANCHOR).",
                        ))
                        break

            # -- invented confidence ---------------------------------------
            if reports_position:
                for n in ast.walk(fn):
                    if isinstance(n, ast.keyword) and n.arg == "self_confidence" \
                            and isinstance(n.value, ast.Constant):
                        findings.append(Finding(
                            rel, n.value.lineno, layer_id, cls.name, fn.name,
                            "OK" if legit_reason else "MEDIUM",
                            "constant_confidence",
                            _source_line(lines, n.value.lineno),
                            legit_reason or
                            "self_confidence is a fixed number chosen to look "
                            "plausible. It does not fall when the measurement is "
                            "poor, so the fusion engine keeps trusting this layer "
                            "exactly as much when it is wrong.",
                            "Derive confidence from evidence — residuals, "
                            "geometry, signal quality — so it drops when the "
                            "measurement degrades.",
                        ))

            # -- invented telemetry in raw_data ----------------------------
            if reports_position:
                for n in ast.walk(fn):
                    if isinstance(n, ast.keyword) and n.arg == "raw_data" \
                            and _contains_random(n.value):
                        findings.append(Finding(
                            rel, n.value.lineno, layer_id, cls.name, fn.name,
                            "OK" if legit_reason else "LOW",
                            "random_telemetry",
                            _source_line(lines, n.value.lineno),
                            legit_reason or
                            "Invented sensor telemetry in raw_data. It does not "
                            "move the aircraft, but an operator or a downstream "
                            "diagnostic reading these values is being shown "
                            "measurements that were never taken.",
                            "Tag the dict with fabricated=True while the layer "
                            "is still simulated, or omit the field.",
                        ))
                        break
    return findings


# ---------------------------------------------------------------------------
# Dynamic pass
# ---------------------------------------------------------------------------

@dataclass
class Behaviour:
    """What a layer actually did when run with nothing connected."""
    layer_id: str
    class_name: str
    answered_with_no_input: bool
    deterministic: Optional[bool]
    declines_cleanly: bool
    raises: str = ""
    position: str = ""
    live_mode: str = ""      # what it does with simulation switched off

    @property
    def severity(self) -> str:
        if self.answered_with_no_input and self.deterministic is False:
            return "CRITICAL"
        if self.answered_with_no_input:
            return "HIGH"
        if self.raises:
            return "MEDIUM"
        return "OK"

    @property
    def fix_effort(self) -> str:
        """How much work this layer's cleanup actually is.

        A layer that already raises in live mode has the hard part done: it
        has a path that knows it has no sensor. Swapping a raise for a
        no_fix() is mechanical. A layer that fabricates in live mode too has
        no such path and needs one written.
        """
        if self.live_mode == "raises NotImplementedError":
            return "mechanical"
        if self.live_mode == "declines properly":
            return "done"
        if self.live_mode == "returns a position":
            return "needs a real sensor path"
        return "inspect"


def run_dynamic() -> List[Behaviour]:
    """Run every registered layer with no sensors and record what it returns."""
    from upin.layers.registry import ALL_LAYER_CLASSES

    out: List[Behaviour] = []
    for layer_id, cls in sorted(ALL_LAYER_CLASSES.items()):
        answered = False
        deterministic: Optional[bool] = None
        declines = False
        raises = ""
        pos_str = ""
        try:
            layer = cls()
            layer.initialize()
            a = layer.read()
            b = layer.read()
            if a is not None and getattr(a, "position", None) is not None \
                    and getattr(a, "is_valid", True):
                answered = True
                p = a.position
                pos_str = f"{p.latitude:.5f},{p.longitude:.5f}"
                if b is not None and b.position is not None:
                    deterministic = (a.position.latitude == b.position.latitude
                                     and a.position.longitude == b.position.longitude)
            elif a is not None and not getattr(a, "is_valid", True):
                declines = bool(a.raw_data and a.raw_data.get("no_fix_reason"))
        except NotImplementedError:
            raises = "NotImplementedError"
        except Exception as exc:
            raises = type(exc).__name__

        # Second run with simulation switched off. This is what decides how
        # much work each cleanup is: a layer that already raises here has a
        # path that knows it has no sensor, and only needs that path to
        # decline politely instead of throwing.
        live = ""
        try:
            layer = cls()
            layer.initialize()
            layer.set_simulation_mode(False)
            r = layer.read()
            if r is None:
                live = "returns None"
            elif getattr(r, "position", None) is not None \
                    and getattr(r, "is_valid", True):
                live = "returns a position"
            elif not getattr(r, "is_valid", True):
                live = "declines properly"
            else:
                live = "valid but no position"
        except NotImplementedError:
            live = "raises NotImplementedError"
        except Exception as exc:
            live = f"raises {type(exc).__name__}"

        out.append(Behaviour(layer_id, cls.__name__, answered, deterministic,
                             declines, raises, pos_str, live))
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def collect_static() -> List[Finding]:
    findings: List[Finding] = []
    for path in sorted((REPO / "upin").rglob("*.py")):
        findings.extend(scan_file(path))
    findings.sort(key=lambda f: f.key())
    return findings


def print_report(findings: List[Finding], behaviours: List[Behaviour]):
    by_sev = Counter(f.severity for f in findings)
    by_cat = Counter(f.category for f in findings)
    by_file: Dict[str, int] = defaultdict(int)
    for f in findings:
        if f.severity != "OK":
            by_file[f.file] += 1

    print("=" * 74)
    print("UPIN FABRICATION AUDIT")
    print("=" * 74)
    print(f"\nStatic findings: {len(findings)}")
    for sev in SEVERITY_ORDER:
        if by_sev[sev]:
            print(f"  {sev:<9} {by_sev[sev]:>4}")
    print("\nBy kind:")
    for cat, n in by_cat.most_common():
        print(f"  {cat:<22} {n:>4}")

    print("\nWorst files:")
    for f, n in sorted(by_file.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {n:>4}  {f}")

    dyn = Counter(b.severity for b in behaviours)
    answered = [b for b in behaviours if b.answered_with_no_input]
    nondet = [b for b in answered if b.deterministic is False]
    declined = [b for b in behaviours if b.declines_cleanly]
    raised = [b for b in behaviours if b.raises]
    print(f"\nDynamic: {len(behaviours)} layers run with nothing connected")
    print(f"  returned a position anyway      {len(answered):>4}")
    print(f"    ... and it changed on re-read {len(nondet):>4}  (proof of invention)")
    print(f"  declined and said why           {len(declined):>4}")
    print(f"  raised instead of declining     {len(raised):>4}")
    for sev in SEVERITY_ORDER:
        if dyn[sev]:
            print(f"  {sev:<9} {dyn[sev]:>4}")

    if behaviours:
        print("\nWith simulation switched off:")
        for mode, n in Counter(b.live_mode for b in behaviours).most_common():
            print(f"  {n:>4}  {mode}")
        print("\nHow much work each cleanup is:")
        for eff, n in Counter(b.fix_effort for b in behaviours).most_common():
            print(f"  {n:>4}  {eff}")
    return by_sev, by_cat, by_file, answered, nondet, declined, raised


def write_markdown(path: Path, findings: List[Finding],
                   behaviours: List[Behaviour]):
    by_sev = Counter(f.severity for f in findings)
    answered = [b for b in behaviours if b.answered_with_no_input]
    nondet = [b for b in answered if b.deterministic is False]
    declined = [b for b in behaviours if b.declines_cleanly]
    raised = [b for b in behaviours if b.raises]

    L: List[str] = []
    L.append("# UPIN fabrication audit\n")
    L.append("Generated by `tools/fabrication_audit.py`. Re-run it after every "
             "stage of the cleanup; the counts here are the baseline to beat.\n")
    L.append("## What this measures\n")
    L.append("A navigation layer is supposed to turn a sensor reading into a "
             "position. Where there is no sensor, some layers return a position "
             "anyway — a default coordinate with random noise added. Nothing in "
             "the returned data marks it as invented, so the fusion engine "
             "weights it like a real fix and the operator sees it like a real "
             "fix. This audit finds those places and grades them by what the "
             "invention would actually cost in flight.\n")
    L.append("## Summary\n")
    L.append("| Severity | Count | Meaning |")
    L.append("|---|---:|---|")
    meanings = {
        "CRITICAL": "An invented position reaches the fusion engine",
        "HIGH": "A hardcoded coordinate is reported as a fix",
        "MEDIUM": "Position may be real; the confidence or accuracy beside it is invented",
        "LOW": "Invented telemetry in raw_data only — misleads a log reader, not the aircraft",
        "OK": "Randomness that belongs (simulator, quantum RNG, stochastic algorithm)",
    }
    for sev in SEVERITY_ORDER:
        if by_sev[sev]:
            L.append(f"| {sev} | {by_sev[sev]} | {meanings[sev]} |")
    L.append(f"\n**Static findings: {len(findings)}** across "
             f"{len({f.file for f in findings})} files.\n")
    L.append("## Behaviour when nothing is connected\n")
    L.append(f"All {len(behaviours)} registered layers were constructed, "
             "initialised and read twice with no sensor, no world and no "
             "calibration.\n")
    L.append("| Outcome | Layers |")
    L.append("|---|---:|")
    L.append(f"| Returned a position anyway | {len(answered)} |")
    L.append(f"| ...and the answer changed between two reads | {len(nondet)} |")
    L.append(f"| Declined and stated a reason | {len(declined)} |")
    L.append(f"| Raised an exception instead of declining | {len(raised)} |")
    L.append("\nA layer whose answer changes while its inputs do not is "
             "manufacturing the difference. That is the mechanical proof of "
             "fabrication, and it needs no reading of the source.\n")

    L.append("## With simulation switched off\n")
    L.append("Every layer was then run again with `set_simulation_mode(False)`. "
             "This is the number that decides how much work the cleanup is.\n")
    L.append("| In live mode the layer | Layers | Cleanup |")
    L.append("|---|---:|---|")
    effort_of = {
        "raises NotImplementedError": "mechanical — swap the raise for a `no_fix()`",
        "declines properly": "already done",
        "returns a position": "needs a real sensor path written",
    }
    for mode, n in Counter(b.live_mode for b in behaviours).most_common():
        L.append(f"| {mode} | {n} | {effort_of.get(mode, 'inspect individually')} |")
    L.append("\nThe good news is in that table. Most layers already have a path "
             "that knows it has no sensor — it just throws instead of saying so. "
             "Turning a `raise NotImplementedError` into "
             "`no_fix(layer_id, NoFixReason.SENSOR_UNAVAILABLE)` is a "
             "line-for-line change that cannot alter any working behaviour, "
             "because that path currently cannot return at all.\n")

    by_effort: Dict[str, List[Behaviour]] = defaultdict(list)
    for b in behaviours:
        by_effort[b.fix_effort].append(b)
    for eff in ("needs a real sensor path", "inspect"):
        group = by_effort.get(eff, [])
        if group:
            L.append(f"### Layers whose cleanup is: {eff}\n")
            L.append("| Layer | Class | In live mode |")
            L.append("|---|---|---|")
            for b in sorted(group, key=lambda b: b.layer_id):
                L.append(f"| `{b.layer_id}` | {b.class_name} | {b.live_mode} |")
            L.append("")

    if nondet:
        L.append("### Layers proven to invent their position\n")
        L.append("| Layer | Class | First read |")
        L.append("|---|---|---|")
        for b in sorted(nondet, key=lambda b: b.layer_id):
            L.append(f"| `{b.layer_id}` | {b.class_name} | {b.position} |")
        L.append("")

    if raised:
        L.append("### Layers that raise instead of declining\n")
        L.append("These are safer than the fabricators — they do not invent "
                 "anything — but an exception is not an answer. A caller that "
                 "does not catch it loses the whole fusion cycle.\n")
        L.append("| Layer | Raises |")
        L.append("|---|---|")
        for b in sorted(raised, key=lambda b: b.layer_id):
            L.append(f"| `{b.layer_id}` | {b.raises} |")
        L.append("")

    L.append("## Staged remediation plan\n")
    L.append("Ordered so that nothing downstream breaks. Each stage ends with "
             "the full test suite green and this audit re-run, so the numbers "
             "above move in one direction only.\n")
    L.append("| Stage | What changes | Risk | Why this order |")
    L.append("|---|---|---|---|")
    L.append("| **0. Make it visible** | Every simulated reading gets "
             "`raw_data['fabricated'] = True` and `simulated = True`. Nothing "
             "else changes. | None — additive only | Until an invented number "
             "is labelled, no downstream code *can* defend itself. This is the "
             "one change that makes every later stage safe. |")
    L.append("| **1. Teach fusion to distrust** | The fusion engine refuses, or "
             "heavily discounts, any reading tagged `fabricated`. | Low — "
             "behaviour change is gated on a flag that stage 0 just added | "
             "Once fusion ignores invented data, the remaining stages cannot "
             "cause a bad fix even half-finished. |")
    L.append("| **2. Replace the raises** | The 128 layers that "
             "`raise NotImplementedError` in live mode return "
             "`no_fix(..., SENSOR_UNAVAILABLE)` instead. | Very low — that path "
             "currently cannot return at all, so nothing depends on it | Turns "
             "a crash into a clean refusal. Mechanical, testable, bulk-appliable. |")
    L.append("| **3. Kill the default coordinate** | Remove every hardcoded "
             "Chennai/Mumbai/Delhi fallback. No anchor means "
             "`no_fix(NO_ANCHOR)`. | Medium — some demos rely on the default | "
             "This is the finding that would actually fly an aircraft to the "
             "wrong city. Do it once fusion is already defended. |")
    L.append("| **4. Earn the confidence numbers** | Replace constant "
             "`self_confidence` and `accuracy_m` with values computed from the "
             "measurement. | Medium — changes fusion weights, so accuracy "
             "results shift | Needs per-layer physics work. Worth doing only "
             "after the layer has real input to compute from. |")
    L.append("| **5. Flip the default** | `self._simulated` defaults to "
             "`False`. A layer simulates only when explicitly asked. | High — "
             "touches every layer at once | The real fix, and the last one. "
             "Safe only after stages 0-4, because until then flipping this "
             "default turns 128 layers into exceptions. |")
    L.append("\n### The single most important line in the codebase\n")
    L.append("`upin/core/layer_base.py`: `self._simulated = True  "
             "# Default to simulation mode`\n")
    L.append("Every layer inherits this. Fabrication is the default state and "
             "honesty is opt-in, which is backwards for a navigation system. "
             "Stage 5 inverts it. Everything before stage 5 exists to make that "
             "inversion survivable.\n")

    L.append("## Every static finding\n")
    for sev in SEVERITY_ORDER:
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        L.append(f"### {sev} — {len(group)} finding(s)\n")
        if group:
            L.append(f"**What it costs:** {group[0].effect}\n")
            L.append(f"**How it is fixed:** {group[0].fix}\n")
        L.append("| File | Line | Layer | Function | Code |")
        L.append("|---|---:|---|---|---|")
        for f in group:
            code = f.snippet.replace("|", "\\|")
            lid = f"`{f.layer_id}`" if f.layer_id else f.class_name
            L.append(f"| `{f.file}` | {f.line} | {lid} | `{f.function}` | `{code}` |")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", help="write the full report here")
    ap.add_argument("--static-only", action="store_true")
    args = ap.parse_args()

    findings = collect_static()
    behaviours = [] if args.static_only else run_dynamic()
    print_report(findings, behaviours)
    if args.markdown:
        write_markdown(REPO / args.markdown, findings, behaviours)
        print(f"\nfull report written to {args.markdown}")


if __name__ == "__main__":
    main()
