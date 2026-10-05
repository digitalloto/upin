"""Repo-wide integrity checks.

The other suites test what layers do. This one tests that the repo tells the
truth about itself and keeps doing so: every layer documents what it needs,
declared input methods exist, every README page is complete, nothing
confidential or secret is tracked, and the fabrication count never quietly
rises.

Run: python tests/test_repo_integrity.py
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")

from upin.core.sensor_requirements import requirement_of
from upin.layers.registry import ALL_LAYER_CLASSES
from upin.layers.requirements_catalog import CATALOG, CLASS_MEANING, operating_class

PASSED = []
REPO = Path(__file__).resolve().parent.parent

STATIC_FINDINGS_BASELINE = 263
"""Fabrication audit static findings when this check was added. Lower it as
layers are converted; it must never go up."""


def test_every_layer_documents_what_it_needs():
    missing = [k for k, c in ALL_LAYER_CLASSES.items() if requirement_of(c()) is None]
    unclassified = [k for k in ALL_LAYER_CLASSES if operating_class(k) not in CLASS_MEANING]
    assert not missing, f"no sensor requirement: {missing}"
    assert not unclassified, f"no operating class: {unclassified}"
    print(f"[ok] all {len(ALL_LAYER_CLASSES)} layers declare sensors and an operating class")
    PASSED.append("requirements")


def test_catalogue_names_only_real_layers():
    stray = [k for k in CATALOG if k not in ALL_LAYER_CLASSES]
    assert not stray, f"catalogue entries for unregistered layers: {stray}"
    print(f"[ok] {len(CATALOG)} catalogue entries, all for registered layers")
    PASSED.append("catalogue")


def test_layer_ids_match_registry_keys():
    bad = [(k, c().layer_id) for k, c in ALL_LAYER_CLASSES.items() if c().layer_id != k]
    assert not bad, f"layer_id differs from registry key: {bad}"
    print("[ok] every layer reports the id it is registered under")
    PASSED.append("ids")


def test_declared_feed_methods_exist():
    broken = []
    for k, c in ALL_LAYER_CLASSES.items():
        layer = c()
        req = requirement_of(layer)
        gaps = req.missing_from(layer) if req else []
        if gaps:
            broken.append((k, gaps))
    assert not broken, f"declared input methods that do not exist: {broken}"
    print("[ok] every declared input method exists on its layer")
    PASSED.append("feeds")


def test_every_readme_page_is_complete():
    pages = sorted((REPO / "docs" / "layers").glob("*.md"))
    assert len(pages) == len(ALL_LAYER_CLASSES), (len(pages), len(ALL_LAYER_CLASSES))
    incomplete = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        for needed in ("## Current status", "## Operating class",
                       "## Sensors and data it needs", "### Hardware",
                       "## How to run it"):
            if needed not in text:
                incomplete.append((p.name, needed))
        if "Not yet declared" in text:
            incomplete.append((p.name, "undeclared"))
    assert not incomplete, incomplete[:10]
    root = (REPO / "README.md").read_text(encoding="utf-8")
    assert root.count("](docs/layers/") == len(ALL_LAYER_CLASSES)
    print(f"[ok] {len(pages)} layer READMEs, each with status, class, sensors, "
          f"hardware and how to run it; root index links all of them")
    PASSED.append("readmes")


def test_plans_are_in_the_repo():
    roadmap = (REPO / "ROADMAP.md").read_text(encoding="utf-8")
    for needed in ("Layered Navigation Spec", "Raspberry Pi", "INSLIB",
                   "Recommended hardware"):
        assert needed in roadmap, needed
    print("[ok] ROADMAP.md carries the spec plan, the Pi plan and the decisions")
    PASSED.append("roadmap")


def _tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    return [REPO / f for f in out.stdout.split()]


def test_no_secrets_tracked():
    bad = [str(f.relative_to(REPO)) for f in _tracked_files()
           if re.search(r"recovery[-_]?code|secret|credential|\.pem$|\.key$",
                        f.name, re.I)]
    assert not bad, bad
    print("[ok] no credential or recovery-code files tracked")
    PASSED.append("secrets")


def test_no_partner_names():
    pattern = re.compile(r"algobotix|\bzipi\b|elena\s*geo|\bubix\b|stigmergix|\bishan\b",
                         re.I)
    hits = []
    this_file = Path(__file__).resolve()
    for f in _tracked_files():
        if f.suffix not in (".py", ".md", ".txt", ".html", ".js", ".json"):
            continue
        # This file holds the pattern itself. It passed on first run only
        # because it was not yet tracked; once committed it matched itself.
        if f.resolve() == this_file:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if pattern.search(text):
            hits.append(str(f.relative_to(REPO)))
    assert not hits, hits
    print("[ok] no partner names in tracked code or docs")
    PASSED.append("partners")


def test_fabrication_never_rises():
    sys.path.insert(0, str(REPO / "tools"))
    from fabrication_audit import collect_static
    n = len([f for f in collect_static() if f.severity != "OK"])
    assert n <= STATIC_FINDINGS_BASELINE, (
        f"{n} static fabrication findings, baseline {STATIC_FINDINGS_BASELINE}")
    print(f"[ok] {n} static fabrication findings (baseline {STATIC_FINDINGS_BASELINE})")
    PASSED.append("audit")


if __name__ == "__main__":
    tests = [
        test_every_layer_documents_what_it_needs,
        test_catalogue_names_only_real_layers,
        test_layer_ids_match_registry_keys,
        test_declared_feed_methods_exist,
        test_every_readme_page_is_complete,
        test_plans_are_in_the_repo,
        test_no_secrets_tracked,
        test_no_partner_names,
        test_fabrication_never_rises,
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
    print(f"\n{len(PASSED)}/{len(tests)} integrity checks passed")
    if failed:
        sys.exit(1)
    print("all integrity checks passed")
