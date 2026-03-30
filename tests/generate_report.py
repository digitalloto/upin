"""
UPIN Test Report Generator

Generates a detailed HTML and text report of all test results
with module coverage, timing, and pass/fail statistics.

Run: python tests/generate_report.py
"""
import sys
import time
import unittest
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def generate_report():
    start_time = time.time()

    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName('tests.test_upin')
    runner = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, 'w'))
    result = runner.run(suite)

    elapsed = time.time() - start_time

    # Build set of failed/errored test IDs for quick lookup
    failed_ids = set()
    errored_ids = set()
    for test, _ in result.failures:
        failed_ids.add(str(test))
    for test, _ in result.errors:
        errored_ids.add(str(test))

    # Organise results by test class — use result object directly
    # Re-run with a custom result that records per-test info
    class_results = {}

    # Walk the suite to get all test instances
    all_tests = []
    def collect(s):
        try:
            for t in s:
                collect(t)
        except TypeError:
            all_tests.append(s)
    collect(loader.loadTestsFromName('tests.test_upin'))

    for test in all_tests:
        cls_name = test.__class__.__name__
        test_name = test._testMethodName
        test_id = str(test)

        if cls_name not in class_results:
            class_results[cls_name] = {"passed": 0, "failed": 0, "errors": 0, "tests": []}

        if test_id in failed_ids:
            status = "FAIL"
            class_results[cls_name]["failed"] += 1
        elif test_id in errored_ids:
            status = "ERROR"
            class_results[cls_name]["errors"] += 1
        else:
            status = "PASS"
            class_results[cls_name]["passed"] += 1

        class_results[cls_name]["tests"].append((test_name, status))

    # Module mapping
    module_map = {
        "TestPosition": "upin.core.position",
        "TestWorld": "upin.simulation.world",
        "TestLayers": "upin.layers.registry",
        "TestFusion": "upin.core.fusion_engine",
        "TestSpoofing": "upin.layers (jamming)",
        "TestComputerVision": "upin.sensors.computer_vision",
        "TestThermal": "upin.sensors.thermal_imaging",
        "TestTargetLock": "upin.sensors.ai_target_lock",
        "TestSwarm": "upin.swarm.beehive",
        "TestIntegration": "Integration (multi-module)",
        "TestJammerTriangulation": "upin.intelligence.jammer_triangulation",
        "TestMissionModes": "upin.missions.mission_modes",
        "TestIFFVerification": "upin.intelligence.iff_verification",
        "TestFalsePosition": "upin.intelligence.false_position",
        "TestDroneRecognition": "upin.vision.drone_recognition",
        "TestFishSchooling": "upin.swarm_fusion.fish_schooling",
        "TestMultiFusion": "upin.fusion.multi_fusion_engine",
        "TestEncryption": "upin.security.encryption",
        "TestCalibrationManager": "upin.calibration.calibration_manager",
    }

    # ── Text Report ───────────────────────────────────────────────
    lines = []
    lines.append("=" * 78)
    lines.append("  UPIN — UNIVERSAL POSITIONING INTELLIGENCE NETWORK")
    lines.append("  Test Suite Report")
    lines.append(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"  Total Tests:    {result.testsRun}")
    lines.append(f"  Passed:         {result.testsRun - len(result.failures) - len(result.errors)}")
    lines.append(f"  Failed:         {len(result.failures)}")
    lines.append(f"  Errors:         {len(result.errors)}")
    lines.append(f"  Time:           {elapsed:.2f}s")
    lines.append(f"  Status:         {'ALL PASSED' if result.wasSuccessful() else 'SOME FAILED'}")
    lines.append("")
    lines.append("-" * 78)
    lines.append(f"  {'Module':<45} {'Tests':>6} {'Pass':>6} {'Fail':>6} {'Status':>8}")
    lines.append("-" * 78)

    total_pass = 0
    total_fail = 0
    total_err = 0

    for cls_name in sorted(class_results.keys()):
        data = class_results[cls_name]
        module = module_map.get(cls_name, cls_name)
        total = data["passed"] + data["failed"] + data["errors"]
        total_pass += data["passed"]
        total_fail += data["failed"]
        total_err += data["errors"]

        status = "PASS" if data["failed"] == 0 and data["errors"] == 0 else "FAIL"
        lines.append(f"  {module:<45} {total:>6} {data['passed']:>6} {data['failed']+data['errors']:>6} {status:>8}")

    lines.append("-" * 78)
    lines.append(f"  {'TOTAL':<45} {result.testsRun:>6} {total_pass:>6} {total_fail+total_err:>6} {'PASS' if result.wasSuccessful() else 'FAIL':>8}")
    lines.append("")

    # Detailed results
    lines.append("=" * 78)
    lines.append("  DETAILED RESULTS BY MODULE")
    lines.append("=" * 78)

    for cls_name in sorted(class_results.keys()):
        data = class_results[cls_name]
        module = module_map.get(cls_name, cls_name)
        lines.append("")
        lines.append(f"  {cls_name} ({module})")
        lines.append(f"  {'-' * (len(cls_name) + len(module) + 3)}")
        for test_name, status in sorted(data["tests"]):
            icon = "PASS" if status == "PASS" else "FAIL"
            lines.append(f"    [{icon}] {test_name}")

    # Failures detail
    if result.failures:
        lines.append("")
        lines.append("=" * 78)
        lines.append("  FAILURE DETAILS")
        lines.append("=" * 78)
        for test, traceback in result.failures:
            lines.append(f"\n  {test}:")
            for line in traceback.strip().split('\n'):
                lines.append(f"    {line}")

    if result.errors:
        lines.append("")
        lines.append("=" * 78)
        lines.append("  ERROR DETAILS")
        lines.append("=" * 78)
        for test, traceback in result.errors:
            lines.append(f"\n  {test}:")
            for line in traceback.strip().split('\n'):
                lines.append(f"    {line}")

    # Coverage summary
    lines.append("")
    lines.append("=" * 78)
    lines.append("  MODULE COVERAGE SUMMARY")
    lines.append("=" * 78)
    lines.append("")

    covered_modules = [
        ("upin.core.position", True),
        ("upin.core.fusion_engine", True),
        ("upin.core.layer_base", True),
        ("upin.simulation.world", True),
        ("upin.layers.registry (60 layers)", True),
        ("upin.sensors.computer_vision", True),
        ("upin.sensors.thermal_imaging", True),
        ("upin.sensors.ai_target_lock", True),
        ("upin.sensors.wifi_csi_sensor", False),
        ("upin.swarm.beehive", True),
        ("upin.swarm_fusion.fish_schooling", True),
        ("upin.fusion.multi_fusion_engine", True),
        ("upin.intelligence.jammer_triangulation", True),
        ("upin.intelligence.iff_verification", True),
        ("upin.intelligence.false_position", True),
        ("upin.missions.mission_modes", True),
        ("upin.calibration.calibration_manager", True),
        ("upin.calibration.drift_compensation", False),
        ("upin.calibration.reference_points", False),
        ("upin.security.encryption", True),
        ("upin.vision.drone_recognition", True),
        ("upin.logging.mission_recorder", False),
        ("upin.services.fusion_microservice", False),
        ("upin.api.rest_server", False),
        ("upin.geofencing.boundary_manager", False),
        ("upin.power.power_manager", False),
        ("upin.detection.mahalanobis_detector", False),
    ]

    tested = sum(1 for _, t in covered_modules if t)
    total_mods = len(covered_modules)
    lines.append(f"  Modules with unit tests:    {tested}/{total_mods} ({tested/total_mods*100:.0f}%)")
    lines.append(f"  Modules without tests:      {total_mods - tested}/{total_mods}")
    lines.append("")
    for mod, has_test in covered_modules:
        icon = "TESTED " if has_test else "NO TEST"
        lines.append(f"    [{icon}] {mod}")

    lines.append("")
    lines.append("=" * 78)
    lines.append(f"  UPIN Test Report Complete — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Patent-pending. AIMCRS / Abheet Prem Manghnani.")
    lines.append("=" * 78)

    report_text = "\n".join(lines)

    # Write text report
    report_path = os.path.join(os.path.dirname(__file__), '..', 'test_report.txt')
    with open(report_path, 'w') as f:
        f.write(report_text)

    # Print to console
    print(report_text)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = generate_report()
    sys.exit(0 if success else 1)
