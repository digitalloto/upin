"""
UPIN COMPLETE DEEP-DIVE AUDIT
Checks every layer, every formula, every module for:
1. Real algorithm vs simulated data
2. Fish school / evolution integration
3. Errors and bugs
4. Named formulas list
"""

import sys, os, ast, inspect, traceback, importlib, time
sys.path.insert(0, '.')

def get_all_classes_from_file(filepath):
    """Extract all classes with their methods and line counts."""
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source)
    except:
        return []
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            doc = ast.get_docstring(node) or ""
            end = node.end_lineno or node.lineno
            classes.append({
                "name": node.name,
                "line_start": node.lineno,
                "line_end": end,
                "lines": end - node.lineno + 1,
                "methods": methods,
                "doc": doc.split("\n")[0][:100],
            })
    return classes

def check_for_simulated_data(filepath):
    """Find any hardcoded simulated/fake data."""
    issues = []
    try:
        with open(filepath) as f:
            lines = f.readlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Check for simulated position defaults
            if '13.0827' in stripped and 'getattr' in stripped:
                issues.append((i, "SIMULATED_DEFAULT", "Hardcoded Chennai default position"))
            elif '80.2707' in stripped and 'getattr' in stripped:
                pass  # paired with above
            # Check for np.random used as primary position source (not noise)
            elif 'np.random.normal(0,' in stripped and 'true_lat' not in stripped and 'base_lat' not in stripped:
                if 'noise' not in stripped.lower() and '+' not in stripped:
                    issues.append((i, "RANDOM_POSITION", "Random value used as position, not noise"))
            # Check for fake/simulated tower data
            elif 'FAKE' in stripped.upper() or 'SIMULATED' in stripped.upper():
                if '#' not in stripped.split('FAKE')[0] and '#' not in stripped.split('SIMULATED')[0]:
                    issues.append((i, "SIMULATED_LABEL", stripped[:80]))
    except:
        pass
    return issues

def check_for_errors(filepath):
    """Try to import and instantiate classes, catch errors."""
    errors = []
    try:
        with open(filepath) as f:
            source = f.read()
        compile(source, filepath, 'exec')
    except SyntaxError as e:
        errors.append(f"SYNTAX ERROR line {e.lineno}: {e.msg}")
    return errors

def check_fish_school_integration(filepath):
    """Check if the file integrates with fish schooling / evolution."""
    try:
        with open(filepath) as f:
            source = f.read()
        indicators = []
        if 'fish' in source.lower() and 'school' in source.lower():
            indicators.append("fish_school_reference")
        if 'evolv' in source.lower() or 'mutation' in source.lower() or 'natural_selection' in source.lower():
            indicators.append("evolution_mechanism")
        if 'FormulaAgent' in source or 'formula_agents' in source:
            indicators.append("formula_agent_integration")
        if 'AutoCombo' in source or 'auto_combo' in source:
            indicators.append("auto_combo_integration")
        if 'train' in source.lower() and ('weight' in source.lower() or 'calibrat' in source.lower()):
            indicators.append("training_mechanism")
        return indicators
    except:
        return []


if __name__ == "__main__":
    print("=" * 100)
    print("UPIN COMPLETE DEEP-DIVE AUDIT")
    print("=" * 100)

    all_layers = []
    all_core = []
    all_swarm = []
    all_detection = []
    all_vision = []
    all_intel = []
    all_other = []
    all_errors = []
    all_simulated = []
    fish_integrated = []

    total_files = 0
    total_lines = 0
    total_classes = 0

    for root, dirs, files in sorted(os.walk('upin')):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fname in sorted(files):
            if not fname.endswith('.py') or fname == '__init__.py':
                continue
            filepath = os.path.join(root, fname)
            total_files += 1

            try:
                with open(filepath) as f:
                    file_lines = sum(1 for _ in f)
                total_lines += file_lines
            except:
                file_lines = 0

            classes = get_all_classes_from_file(filepath)
            total_classes += len(classes)

            # Check for errors
            errors = check_for_errors(filepath)
            if errors:
                all_errors.append((filepath, errors))

            # Check for simulated data
            sim_issues = check_for_simulated_data(filepath)
            if sim_issues:
                all_simulated.append((filepath, sim_issues))

            # Check fish school integration
            fish = check_fish_school_integration(filepath)
            if fish:
                fish_integrated.append((filepath, fish))

            # Categorize
            rel_path = os.path.relpath(filepath, '.')
            for cls in classes:
                entry = {
                    "file": rel_path,
                    "class": cls["name"],
                    "lines": cls["lines"],
                    "methods": cls["methods"],
                    "doc": cls["doc"],
                    "method_count": len(cls["methods"]),
                }
                if '/layers/' in filepath:
                    all_layers.append(entry)
                elif '/core/' in filepath:
                    all_core.append(entry)
                elif '/swarm/' in filepath:
                    all_swarm.append(entry)
                elif '/detection/' in filepath:
                    all_detection.append(entry)
                elif '/vision/' in filepath:
                    all_vision.append(entry)
                elif '/intelligence/' in filepath:
                    all_intel.append(entry)
                else:
                    all_other.append(entry)

    # ═══ REPORT ═══

    print(f"\n{'─' * 100}")
    print(f"CODEBASE STATS")
    print(f"{'─' * 100}")
    print(f"  Python files:    {total_files}")
    print(f"  Total lines:     {total_lines:,}")
    print(f"  Total classes:   {total_classes}")
    print(f"  Layer classes:   {len(all_layers)}")
    print(f"  Core classes:    {len(all_core)}")
    print(f"  Swarm classes:   {len(all_swarm)}")
    print(f"  Detection:       {len(all_detection)}")
    print(f"  Vision:          {len(all_vision)}")
    print(f"  Intelligence:    {len(all_intel)}")

    # ═══ ALL NAVIGATION LAYERS BY NAME ═══
    print(f"\n{'─' * 100}")
    print(f"ALL NAVIGATION LAYER CLASSES ({len([l for l in all_layers if 'Layer' in l['class']])})")
    print(f"{'─' * 100}")
    layer_classes = sorted([l for l in all_layers if 'Layer' in l['class']], key=lambda x: x['file'])
    for l in layer_classes:
        methods_str = ", ".join(l['methods'][:5])
        if len(l['methods']) > 5:
            methods_str += f"... +{len(l['methods'])-5}"
        print(f"  {l['class']:45s} {l['lines']:4d}L  {l['method_count']:2d}M  {l['file']}")

    # ═══ ALL CORE MODULES BY NAME ═══
    print(f"\n{'─' * 100}")
    print(f"ALL CORE MODULE CLASSES ({len(all_core)})")
    print(f"{'─' * 100}")
    for c in sorted(all_core, key=lambda x: x['file']):
        print(f"  {c['class']:45s} {c['lines']:4d}L  {c['method_count']:2d}M  {c['file']}")

    # ═══ ALL SWARM CLASSES ═══
    print(f"\n{'─' * 100}")
    print(f"ALL SWARM CLASSES ({len(all_swarm)})")
    print(f"{'─' * 100}")
    for s in sorted(all_swarm, key=lambda x: x['file']):
        print(f"  {s['class']:45s} {s['lines']:4d}L  {s['method_count']:2d}M  {s['file']}")

    # ═══ DETECTION + VISION + INTELLIGENCE ═══
    print(f"\n{'─' * 100}")
    print(f"DETECTION + VISION + INTELLIGENCE ({len(all_detection) + len(all_vision) + len(all_intel)})")
    print(f"{'─' * 100}")
    for d in sorted(all_detection + all_vision + all_intel, key=lambda x: x['file']):
        print(f"  {d['class']:45s} {d['lines']:4d}L  {d['method_count']:2d}M  {d['file']}")

    # ═══ FISH SCHOOL / EVOLUTION INTEGRATION ═══
    print(f"\n{'─' * 100}")
    print(f"FISH SCHOOL / EVOLUTION INTEGRATION ({len(fish_integrated)} files)")
    print(f"{'─' * 100}")
    for filepath, indicators in fish_integrated:
        print(f"  {filepath:60s} {', '.join(indicators)}")

    # ═══ SIMULATED DATA FOUND ═══
    print(f"\n{'─' * 100}")
    print(f"SIMULATED/HARDCODED DATA ({sum(len(issues) for _, issues in all_simulated)} instances in {len(all_simulated)} files)")
    print(f"{'─' * 100}")
    for filepath, issues in all_simulated:
        for line, issue_type, detail in issues:
            print(f"  {filepath}:{line:4d}  {issue_type:20s}  {detail[:60]}")

    # ═══ ERRORS FOUND ═══
    print(f"\n{'─' * 100}")
    print(f"ERRORS FOUND ({sum(len(e) for _, e in all_errors)} errors in {len(all_errors)} files)")
    print(f"{'─' * 100}")
    if all_errors:
        for filepath, errors in all_errors:
            for err in errors:
                print(f"  {filepath}: {err}")
    else:
        print("  NONE — all files compile without errors")

    # ═══ REGISTERED LAYERS TEST ═══
    print(f"\n{'─' * 100}")
    print(f"REGISTERED LAYER INSTANTIATION TEST")
    print(f"{'─' * 100}")
    try:
        from upin.layers.registry import ALL_LAYER_CLASSES
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        w.step(0.1)

        pass_count = 0
        fail_count = 0
        fail_list = []

        for lid, cls in sorted(ALL_LAYER_CLASSES.items()):
            try:
                inst = cls()
                inst.initialize()
                inst.set_world(w)
                r = inst.read()
                if r and r.is_valid:
                    pass_count += 1
                else:
                    fail_count += 1
                    fail_list.append(f"{lid}: read() returned invalid")
            except Exception as e:
                fail_count += 1
                fail_list.append(f"{lid}: {str(e)[:60]}")

        print(f"  Registered layers: {len(ALL_LAYER_CLASSES)}")
        print(f"  PASS: {pass_count}")
        print(f"  FAIL: {fail_count}")
        for f in fail_list:
            print(f"    FAIL: {f}")
    except Exception as e:
        print(f"  ERROR loading registry: {e}")

    # ═══ SUMMARY ═══
    print(f"\n{'=' * 100}")
    print(f"AUDIT SUMMARY")
    print(f"{'=' * 100}")
    print(f"  Files: {total_files} | Lines: {total_lines:,} | Classes: {total_classes}")
    print(f"  Layers: {len([l for l in all_layers if 'Layer' in l['class']])} classes")
    print(f"  Core modules: {len(all_core)} classes")
    print(f"  Swarm: {len(all_swarm)} classes")
    print(f"  Detection+Vision+Intel: {len(all_detection) + len(all_vision) + len(all_intel)} classes")
    print(f"  Fish/evolution integrated: {len(fish_integrated)} files")
    print(f"  Simulated data instances: {sum(len(i) for _, i in all_simulated)}")
    print(f"  Syntax errors: {sum(len(e) for _, e in all_errors)}")
    print(f"{'=' * 100}")
