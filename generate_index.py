"""
UPIN Codebase Index Generator

Run this script to generate LAYER_INDEX.md — a complete reference
of every layer, module, and class in the UPIN codebase.

Usage:
    python generate_index.py

Output:
    LAYER_INDEX.md — auto-generated reference with:
    - Every NavigationLayer (ID, number, group, file, line numbers)
    - Every core module (class name, purpose, file, lines)
    - Every swarm tactic (file, status: implemented/stub)
    - Every detection module
    - Every API integration
    - Total counts and architecture summary
"""

import ast
import os
import re
import sys
from pathlib import Path


def find_python_files(root: str):
    """Find all .py files under root."""
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith(".py") and not f.startswith("__"):
                yield os.path.join(dirpath, f)


def extract_classes(filepath: str):
    """Extract class names, line numbers, and docstrings from a Python file."""
    try:
        with open(filepath, "r") as f:
            source = f.read()
        tree = ast.parse(source)
    except Exception:
        return []

    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            first_line = doc.split("\n")[0].strip() if doc else ""
            end_line = node.end_lineno or node.lineno
            classes.append({
                "name": node.name,
                "line_start": node.lineno,
                "line_end": end_line,
                "docstring_first_line": first_line,
            })
    return classes


def extract_module_docstring(filepath: str) -> str:
    """Get the module-level docstring."""
    try:
        with open(filepath, "r") as f:
            source = f.read()
        tree = ast.parse(source)
        doc = ast.get_docstring(tree) or ""
        return doc.split("\n")[0].strip()
    except Exception:
        return ""


def count_lines(filepath: str) -> int:
    try:
        with open(filepath, "r") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def is_stub(filepath: str) -> bool:
    """Check if a file is just a docstring stub."""
    return count_lines(filepath) <= 3


def generate_index(upin_root: str) -> str:
    """Generate the complete codebase index as markdown."""
    lines = []
    lines.append("# UPIN Codebase Index")
    lines.append("")
    lines.append("Auto-generated reference for the entire UPIN codebase.")
    lines.append(f"Run `python generate_index.py` to regenerate.")
    lines.append("")

    # Collect all data
    all_layers = []
    core_modules = []
    swarm_modules = []
    detection_modules = []
    agent_modules = []
    vision_modules = []
    other_modules = []
    total_classes = 0
    total_lines = 0
    total_files = 0

    for filepath in sorted(find_python_files(upin_root)):
        rel_path = os.path.relpath(filepath, os.path.dirname(upin_root))
        file_lines = count_lines(filepath)
        total_lines += file_lines
        total_files += 1
        classes = extract_classes(filepath)
        total_classes += len(classes)
        module_doc = extract_module_docstring(filepath)
        stub = is_stub(filepath)

        # Categorise
        if "/layers/" in filepath:
            for cls in classes:
                if "Layer" in cls["name"]:
                    # Try to find layer_id and layer_number
                    layer_id = ""
                    layer_num = ""
                    try:
                        with open(filepath) as f:
                            src = f.read()
                        # Find layer_id in the class body
                        pattern = rf'class {cls["name"]}.*?layer_id="([^"]+)"'
                        m = re.search(pattern, src, re.DOTALL)
                        if m:
                            layer_id = m.group(1)
                        pattern2 = rf'class {cls["name"]}.*?layer_number=(\d+)'
                        m2 = re.search(pattern2, src, re.DOTALL)
                        if m2:
                            layer_num = m2.group(1)
                    except Exception:
                        pass
                    all_layers.append({
                        "class": cls["name"],
                        "layer_id": layer_id,
                        "layer_number": layer_num,
                        "description": cls["docstring_first_line"],
                        "file": rel_path,
                        "line_start": cls["line_start"],
                        "line_end": cls["line_end"],
                        "lines": file_lines,
                    })
            # Non-layer classes in layers/
            for cls in classes:
                if "Layer" not in cls["name"]:
                    other_modules.append({
                        "class": cls["name"],
                        "description": cls["docstring_first_line"],
                        "file": rel_path,
                        "line_start": cls["line_start"],
                        "line_end": cls["line_end"],
                    })

        elif "/core/" in filepath:
            for cls in classes:
                core_modules.append({
                    "class": cls["name"],
                    "description": cls["docstring_first_line"],
                    "file": rel_path,
                    "line_start": cls["line_start"],
                    "line_end": cls["line_end"],
                    "module_doc": module_doc,
                })

        elif "/swarm/" in filepath:
            for cls in classes:
                swarm_modules.append({
                    "class": cls["name"],
                    "description": cls["docstring_first_line"],
                    "file": rel_path,
                    "line_start": cls["line_start"],
                    "line_end": cls["line_end"],
                    "stub": stub,
                })
            if not classes and stub:
                swarm_modules.append({
                    "class": "(stub)",
                    "description": module_doc,
                    "file": rel_path,
                    "line_start": 1,
                    "line_end": file_lines,
                    "stub": True,
                })

        elif "/detection/" in filepath:
            for cls in classes:
                detection_modules.append({
                    "class": cls["name"],
                    "description": cls["docstring_first_line"],
                    "file": rel_path,
                    "line_start": cls["line_start"],
                    "line_end": cls["line_end"],
                })

        elif "/agents/" in filepath:
            for cls in classes:
                agent_modules.append({
                    "class": cls["name"],
                    "description": cls["docstring_first_line"],
                    "file": rel_path,
                    "line_start": cls["line_start"],
                    "line_end": cls["line_end"],
                })

        elif "/vision/" in filepath:
            for cls in classes:
                vision_modules.append({
                    "class": cls["name"],
                    "description": cls["docstring_first_line"],
                    "file": rel_path,
                    "line_start": cls["line_start"],
                    "line_end": cls["line_end"],
                })

    # ── Summary ──
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Navigation Layers**: {len(all_layers)}")
    lines.append(f"- **Core Modules**: {len(core_modules)} classes")
    lines.append(f"- **Swarm Modules**: {len(swarm_modules)} classes")
    lines.append(f"- **Detection Modules**: {len(detection_modules)} classes")
    lines.append(f"- **Agent Modules**: {len(agent_modules)} classes")
    lines.append(f"- **Vision Modules**: {len(vision_modules)} classes")
    lines.append(f"- **Total Classes**: {total_classes}")
    lines.append(f"- **Total Python Files**: {total_files}")
    lines.append(f"- **Total Lines of Code**: {total_lines:,}")
    lines.append("")

    # ── Navigation Layers ──
    lines.append("---")
    lines.append("## Navigation Layers")
    lines.append("")
    lines.append("| # | Layer ID | Class | Description | File | Lines |")
    lines.append("|---|----------|-------|-------------|------|-------|")
    all_layers.sort(key=lambda l: int(l["layer_number"]) if l["layer_number"] else 999)
    for l in all_layers:
        desc = l["description"][:60] + "..." if len(l["description"]) > 60 else l["description"]
        lines.append(
            f"| {l['layer_number']} | `{l['layer_id']}` | `{l['class']}` | "
            f"{desc} | `{l['file']}` | {l['line_start']}-{l['line_end']} |"
        )
    lines.append("")

    # ── Core Modules ──
    lines.append("---")
    lines.append("## Core Modules")
    lines.append("")
    lines.append("| Class | Description | File | Lines |")
    lines.append("|-------|-------------|------|-------|")
    for m in sorted(core_modules, key=lambda x: x["file"]):
        desc = m["description"][:70] + "..." if len(m["description"]) > 70 else m["description"]
        lines.append(
            f"| `{m['class']}` | {desc} | "
            f"`{m['file']}` | {m['line_start']}-{m['line_end']} |"
        )
    lines.append("")

    # ── Swarm Modules ──
    lines.append("---")
    lines.append("## Swarm & Nature Tactics")
    lines.append("")
    lines.append("| Class | Description | File | Lines | Status |")
    lines.append("|-------|-------------|------|-------|--------|")
    for m in sorted(swarm_modules, key=lambda x: x["file"]):
        status = "STUB" if m.get("stub") else "IMPLEMENTED"
        desc = m["description"][:60] + "..." if len(m["description"]) > 60 else m["description"]
        lines.append(
            f"| `{m['class']}` | {desc} | "
            f"`{m['file']}` | {m['line_start']}-{m['line_end']} | {status} |"
        )
    lines.append("")

    # ── Detection ──
    lines.append("---")
    lines.append("## Detection & Security")
    lines.append("")
    lines.append("| Class | Description | File | Lines |")
    lines.append("|-------|-------------|------|-------|")
    for m in sorted(detection_modules, key=lambda x: x["file"]):
        desc = m["description"][:70] + "..." if len(m["description"]) > 70 else m["description"]
        lines.append(
            f"| `{m['class']}` | {desc} | "
            f"`{m['file']}` | {m['line_start']}-{m['line_end']} |"
        )
    lines.append("")

    # ── Vision ──
    lines.append("---")
    lines.append("## Vision & Object Detection")
    lines.append("")
    lines.append("| Class | Description | File | Lines |")
    lines.append("|-------|-------------|------|-------|")
    for m in sorted(vision_modules, key=lambda x: x["file"]):
        desc = m["description"][:70] + "..." if len(m["description"]) > 70 else m["description"]
        lines.append(
            f"| `{m['class']}` | {desc} | "
            f"`{m['file']}` | {m['line_start']}-{m['line_end']} |"
        )
    lines.append("")

    # ── Agents ──
    lines.append("---")
    lines.append("## Sensor Agents & API Integrations")
    lines.append("")
    lines.append("| Class | Description | File | Lines |")
    lines.append("|-------|-------------|------|-------|")
    for m in sorted(agent_modules, key=lambda x: x["file"]):
        desc = m["description"][:70] + "..." if len(m["description"]) > 70 else m["description"]
        lines.append(
            f"| `{m['class']}` | {desc} | "
            f"`{m['file']}` | {m['line_start']}-{m['line_end']} |"
        )
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated automatically. {len(all_layers)} layers, "
                 f"{total_classes} classes, {total_lines:,} lines of code.*")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    upin_dir = os.path.join(root, "upin")
    if not os.path.isdir(upin_dir):
        upin_dir = os.path.join(os.path.dirname(root), "upin")

    index = generate_index(upin_dir)
    output_path = os.path.join(os.path.dirname(upin_dir), "LAYER_INDEX.md")
    with open(output_path, "w") as f:
        f.write(index)
    print(f"Generated {output_path}")

    # Print summary
    layer_count = index.count("| `") // 2  # rough count
    print(f"Index contains references to {layer_count}+ entries")
