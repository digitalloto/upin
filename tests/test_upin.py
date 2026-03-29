"""
UPIN Test Suite — run with: python tests/test_upin.py
"""
import sys, time, unittest
sys.path.insert(0, '.')
class TestPosition(unittest.TestCase):
    def test_position_creation(self):
        from upin.core.position import Position
        p = Position(13.08, 80.27, 100)
        self.assertEqual(p.latitude, 13.08)
    def test_position_distance(self):
        from upin.core.position import Position
        p1 = Position(13.08, 80.27, 0)
        p2 = Position(13.09, 80.27, 0)
        self.assertAlmostEqual(p1.distance_to(p2), 1111, delta=100)
class TestWorld(unittest.TestCase):
    def test_world_creates(self):
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        w.step(0.1)
        lat, lon, alt = w.true_position
        self.assertAlmostEqual(lat, 13.08, delta=1.0)
class TestLayers(unittest.TestCase):
    def test_layers_load(self):
        from upin.layers.registry import LayerRegistry
        r = LayerRegistry()
        layers = r.create_all()
        self.assertGreater(len(layers), 40)
    def test_layers_read(self):
        from upin.layers.registry import LayerRegistry
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        w.step(0.1)
        r = LayerRegistry()
        layers = r.create_minimal()
        valid = 0
        for l in layers:
            l.set_world(w)
            l.initialize()
            reading = l.read()
            if reading and reading.is_valid:
                valid += 1
        self.assertGreater(valid, 3)
class TestFusion(unittest.TestCase):
    def test_cycle_runs(self):
        from upin.core.fusion_engine import FusionEngine
        e = FusionEngine()
        e.initialize()
        out = e.cycle()
        self.assertIsNotNone(out)
        self.assertGreaterEqual(out.confidence_score, 0.0)
        self.assertLessEqual(out.confidence_score, 1.0)
class TestSpoofing(unittest.TestCase):
    def test_jam_makes_invalid(self):
        from upin.layers.registry import LayerRegistry
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        w.step(0.1)
        r = LayerRegistry()
        layers = r.create_minimal()
        l = layers[0]
        l.set_world(w)
        l.initialize()
        l.simulate_jamming(True)
        reading = l.read()
        if reading:
            self.assertFalse(reading.is_valid)
class TestComputerVision(unittest.TestCase):
    def test_detector_runs(self):
        from upin.sensors.computer_vision import ObjectDetector, VideoFrame
        det = ObjectDetector()
        results = det.detect(VideoFrame())
        self.assertIsInstance(results, list)
    def test_classifier_always_needs_auth(self):
        from upin.sensors.computer_vision import TargetClassifier, DetectedObject, ObjectClass
        clf = TargetClassifier()
        for cls in ObjectClass:
            result = clf.classify(DetectedObject(object_class=cls, confidence=0.8))
            self.assertTrue(result["requires_human_authorisation"])
    def test_structure_needs_auth(self):
        from upin.sensors.computer_vision import StructureAnalyser, ObjectClass
        result = StructureAnalyser().analyse(ObjectClass.STRUCTURE_MIL, "tactical", "generator")
        self.assertTrue(result["requires_human_authorisation"])
class TestThermal(unittest.TestCase):
    def test_camera_captures(self):
        from upin.sensors.thermal_imaging import ThermalCamera
        frame = ThermalCamera().capture_frame()
        self.assertEqual(frame.pixel_temps.shape, (512, 640))
    def test_detector_finds_signatures(self):
        from upin.sensors.thermal_imaging import ThermalCamera, HeatSignatureDetector
        frame = ThermalCamera().capture_frame()
        sigs = HeatSignatureDetector().detect(frame)
        self.assertIsInstance(sigs, list)
    def test_classifier_needs_auth(self):
        from upin.sensors.thermal_imaging import ThermalCamera, HeatSignatureDetector, ThreatHeatClassifier
        frame = ThermalCamera().capture_frame()
        sigs = HeatSignatureDetector().detect(frame)
        clf = ThreatHeatClassifier()
        for sig in sigs[:3]:
            self.assertTrue(clf.classify_threat(sig)["requires_human_authorisation"])
class TestTargetLock(unittest.TestCase):
    def test_acquire(self):
        from upin.sensors.ai_target_lock import TargetLock
        state = TargetLock().acquire((13.08, 80.27, 0), "vehicle")
        self.assertEqual(state.classification, "vehicle")
    def test_no_auth_by_default(self):
        from upin.sensors.ai_target_lock import MultiTargetManager
        t = MultiTargetManager().add_target((13.08, 80.27, 0), "vehicle", 0.9)
        self.assertFalse(t.human_authorised)
    def test_max_20_targets(self):
        from upin.sensors.ai_target_lock import MultiTargetManager
        mtm = MultiTargetManager()
        for i in range(25):
            mtm.add_target((13.08+i*0.001, 80.27, 0), "v", 0.5)
        self.assertLessEqual(mtm.get_summary()["active_targets"], 20)
    def test_audit_trail(self):
        from upin.sensors.ai_target_lock import TargetLock, EngagementAuthoriser
        state = TargetLock().acquire((13.08, 80.27, 0), "vehicle")
        auth = EngagementAuthoriser("officer_001")
        req = auth.request_engagement_auth(state)
        self.assertEqual(req["status"], "PENDING_HUMAN_AUTHORISATION")
        res = auth.authorise(req["request_id"], "colonel", "AUTH1")
        self.assertEqual(res["status"], "AUTHORISED")
class TestSwarm(unittest.TestCase):
    def test_beehive_init(self):
        from upin.swarm.beehive import DistributedBeehiveIntelligence
        dbi = DistributedBeehiveIntelligence()
        self.assertTrue(dbi.initialize())
    def test_offensive_needs_auth(self):
        from upin.swarm.beehive import OffensivePostureMode
        opm = OffensivePostureMode()
        opm.initialize()
        plan = opm.request_authorization({"type": "structure"})
        self.assertEqual(plan["status"], "AWAITING_AUTHORIZATION")
        self.assertTrue(plan["requires_human_auth"])
    def test_formation_count(self):
        from upin.swarm.beehive import AdaptiveFormationIntelligence
        from upin.core.position import Position
        afi = AdaptiveFormationIntelligence()
        afi.initialize()
        afi.select_formation("isr", 0)
        positions = afi.get_formation_positions(Position(13.08, 80.27, 100), 6)
        self.assertEqual(len(positions), 6)
class TestIntegration(unittest.TestCase):
    def test_full_pipeline(self):
        from upin.sensors.computer_vision import ObjectDetector, VideoFrame
        from upin.sensors.thermal_imaging import ThermalCamera, HeatSignatureDetector
        from upin.sensors.ai_target_lock import MultiTargetManager, SensorInput
        detections = ObjectDetector().detect(VideoFrame(camera_position=(13.08, 80.27, 200)))
        sigs = HeatSignatureDetector().detect(ThermalCamera().capture_frame())
        mtm = MultiTargetManager()
        if detections:
            t = mtm.add_target(detections[0].position_geo, detections[0].object_class.value, 0.8)
            mtm.update_target(t.target_id, detections[0].position_geo, SensorInput.THERMAL, 0.85)
        self.assertEqual(mtm.get_summary()["human_authorised"], 0)
    def test_fusion_full_cycle(self):
        from upin.core.fusion_engine import FusionEngine
        from upin.simulation.world import SimulationWorld
        from upin.layers.registry import LayerRegistry
        w = SimulationWorld()
        w.step(0.1)
        layers = LayerRegistry().create_all()
        for l in layers:
            l.set_world(w)
            l.initialize()
        e = FusionEngine()
        e.initialize()
        out = e.cycle()
        self.assertGreaterEqual(out.confidence_score, 0.0)
        self.assertLessEqual(out.confidence_score, 1.0)

class TestJammerTriangulation(unittest.TestCase):
    """Tests for the jammer triangulation module."""

    def setUp(self):
        from upin.intelligence.jammer_triangulation import JammerTriangulator, SensorReading
        self.JammerTriangulator = JammerTriangulator
        self.SensorReading = SensorReading

    def _make_readings(self):
        return [
            self.SensorReading("s1", 13.0827, 80.2707, -45.0, 1000.0, 1575.42),
            self.SensorReading("s2", 13.0900, 80.2707, -52.0, 1003.2, 1575.42),
            self.SensorReading("s3", 13.0827, 80.2800, -58.0, 1006.8, 1575.42),
            self.SensorReading("s4", 13.0750, 80.2750, -61.0, 1009.1, 1575.42),
        ]

    def test_triangulates_location(self):
        t = self.JammerTriangulator()
        result = t.triangulate(self._make_readings())
        self.assertIsNotNone(result)
        self.assertGreater(result.confidence, 0.5)
        self.assertIsInstance(result.lat, float)
        self.assertIsInstance(result.lon, float)

    def test_requires_minimum_three_sensors(self):
        t = self.JammerTriangulator()
        result = t.triangulate(self._make_readings()[:2])
        self.assertIsNone(result)

    def test_not_actionable_without_auth(self):
        t = self.JammerTriangulator()
        result = t.triangulate(self._make_readings())
        self.assertFalse(result.is_actionable())

    def test_actionable_after_auth(self):
        t = self.JammerTriangulator()
        t.authorise(True)
        result = t.triangulate(self._make_readings())
        self.assertTrue(result.human_authorised)

    def test_audit_log_exists(self):
        t = self.JammerTriangulator()
        result = t.triangulate(self._make_readings())
        self.assertGreater(len(result.audit_log), 0)

    def test_history_grows(self):
        t = self.JammerTriangulator()
        t.triangulate(self._make_readings())
        t.triangulate(self._make_readings())
        self.assertEqual(len(t.get_history()), 2)


class TestMissionModes(unittest.TestCase):
    """Tests for the mission mode controller."""

    def setUp(self):
        from upin.missions.mission_modes import MissionModeController, MissionMode
        self.MissionModeController = MissionModeController
        self.MissionMode = MissionMode

    def test_default_mode_is_ghost_recon(self):
        ctrl = self.MissionModeController()
        self.assertEqual(ctrl.current_mode, self.MissionMode.GHOST_RECON)

    def test_ghost_recon_blocks_engagement(self):
        ctrl = self.MissionModeController()
        self.assertFalse(ctrl.can("engage"))
        self.assertFalse(ctrl.can("emit"))
        self.assertFalse(ctrl.can("lethal"))

    def test_autonomous_always_blocked(self):
        ctrl = self.MissionModeController()
        for mode in self.MissionMode:
            ctrl.set_mode(mode, "test", "test")
            self.assertFalse(ctrl.can("autonomous"))

    def test_hunter_allows_lethal(self):
        ctrl = self.MissionModeController()
        ctrl.set_mode(self.MissionMode.HUNTER, "CO", "test")
        self.assertTrue(ctrl.can("lethal"))

    def test_rescue_support_blocks_engagement(self):
        ctrl = self.MissionModeController()
        ctrl.set_mode(self.MissionMode.RESCUE_SUPPORT, "CO", "test")
        self.assertFalse(ctrl.can("engage"))
        self.assertFalse(ctrl.can("lethal"))

    def test_covert_isr_blocks_emission(self):
        ctrl = self.MissionModeController()
        ctrl.set_mode(self.MissionMode.COVERT_ISR, "CO", "test")
        self.assertFalse(ctrl.can("emit"))

    def test_mode_transitions_logged(self):
        ctrl = self.MissionModeController()
        ctrl.set_mode(self.MissionMode.GUARDIAN, "Commander", "threat")
        ctrl.set_mode(self.MissionMode.HUNTER, "CO", "engage")
        self.assertEqual(len(ctrl.get_history()), 3)

    def test_auth_always_required(self):
        ctrl = self.MissionModeController()
        for mode in self.MissionMode:
            ctrl.set_mode(mode, "test", "test")
            self.assertTrue(ctrl.require_auth())


class TestIFFVerification(unittest.TestCase):
    """Tests for the seven-factor IFF verification module."""

    def setUp(self):
        import time
        from upin.intelligence.iff_verification import IFFVerifier, IFFVerdict
        self.IFFVerifier = IFFVerifier
        self.IFFVerdict = IFFVerdict
        self.friendly_data = {
            "transponder_code": "IFF-ALPHA-7749",
            "rf_signature": 0.847,
            "speed_ms": 180.0,
            "altitude_m": 3000.0,
            "heading_deg": 45.0,
            "formation_lat": 13.0830,
            "formation_lon": 80.2710,
            "timing_token": int(time.time()) // 30,
            "iff_token": "TOK-X7K9QP--",
            "thermal_signature": 0.72,
            "visual_signature": 0.68,
        }
        self.hostile_data = {
            "transponder_code": "IFF-ALPHA-7749",
            "rf_signature": 0.100,
            "speed_ms": 10.0,
            "altitude_m": 20.0,
            "heading_deg": 200.0,
            "formation_lat": 18.0,
            "formation_lon": 85.0,
            "timing_token": 0,
            "iff_token": "BAD",
            "thermal_signature": 0.10,
            "visual_signature": 0.10,
        }

    def test_genuine_friendly_passes_all_seven(self):
        v = self.IFFVerifier()
        result = v.verify("ALPHA-1", self.friendly_data)
        self.assertEqual(result.factors_passed, 7)
        self.assertEqual(result.verdict, self.IFFVerdict.FRIENDLY)

    def test_spoofed_transponder_detected_as_hostile(self):
        v = self.IFFVerifier()
        result = v.verify("SPOOF-X", self.hostile_data)
        self.assertIn(result.verdict, [self.IFFVerdict.HOSTILE, self.IFFVerdict.SUSPECT])
        self.assertLess(result.factors_passed, 4)

    def test_confirmed_friendly_method(self):
        v = self.IFFVerifier()
        result = v.verify("ALPHA-1", self.friendly_data)
        self.assertTrue(result.is_confirmed_friendly())

    def test_hostile_not_confirmed_friendly(self):
        v = self.IFFVerifier()
        result = v.verify("SPOOF-X", self.hostile_data)
        self.assertFalse(result.is_confirmed_friendly())

    def test_covert_mode_suppresses_active_factors(self):
        v = self.IFFVerifier(covert_mode=True)
        result = v.verify("SHADOW", self.friendly_data)
        self.assertTrue(result.covert_mode)

    def test_audit_log_present(self):
        v = self.IFFVerifier()
        result = v.verify("ALPHA-1", self.friendly_data)
        self.assertGreater(len(result.audit_log), 0)

    def test_history_recorded(self):
        v = self.IFFVerifier()
        v.verify("A", self.friendly_data)
        v.verify("B", self.hostile_data)
        self.assertEqual(len(v.get_history()), 2)


class TestFalsePosition(unittest.TestCase):
    """Tests for the false position broadcasting module."""

    def setUp(self):
        from upin.intelligence.false_position import FalsePositionBroadcaster, DecoyStrategy
        self.FalsePositionBroadcaster = FalsePositionBroadcaster
        self.DecoyStrategy = DecoyStrategy
        self.TRUE_LAT = 13.0827
        self.TRUE_LON = 80.2707

    def test_blocked_without_authorisation(self):
        b = self.FalsePositionBroadcaster()
        result = b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.STATIONARY)
        self.assertIsNone(result)

    def test_broadcasts_after_authorisation(self):
        b = self.FalsePositionBroadcaster()
        b.authorise(True, "Commander")
        result = b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.RETREATING)
        self.assertIsNotNone(result)
        self.assertTrue(result.human_authorised)

    def test_false_position_differs_from_true(self):
        b = self.FalsePositionBroadcaster()
        b.authorise(True, "Commander")
        result = b.start_broadcast(
            self.TRUE_LAT, self.TRUE_LON,
            self.DecoyStrategy.RETREATING, offset_km=5.0
        )
        self.assertGreater(result.deception_distance_km(), 0.4)

    def test_revoke_stops_broadcast(self):
        b = self.FalsePositionBroadcaster()
        b.authorise(True, "Commander")
        b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.STATIONARY)
        self.assertTrue(b.is_active())
        b.authorise(False)
        self.assertFalse(b.is_active())

    def test_blocked_when_emissions_blocked(self):
        b = self.FalsePositionBroadcaster()
        b.authorise(True, "Commander")
        b.block_emissions(True)
        result = b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.STATIONARY)
        self.assertIsNone(result)

    def test_audit_log_on_broadcast(self):
        b = self.FalsePositionBroadcaster()
        b.authorise(True, "Commander")
        result = b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.MIRROR)
        self.assertGreater(len(result.audit_log), 0)

    def test_history_tracked(self):
        b = self.FalsePositionBroadcaster()
        b.authorise(True, "Commander")
        b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.STATIONARY)
        b.start_broadcast(self.TRUE_LAT, self.TRUE_LON, self.DecoyStrategy.MIRROR)
        self.assertEqual(len(b.get_history()), 2)

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print(f"\n{'='*50}")
    print(f"Tests: {result.testsRun} | Failures: {len(result.failures)} | Errors: {len(result.errors)}")
    print(f"STATUS: {'ALL PASSED' if result.wasSuccessful() else 'SOME FAILED'}")
    print(f"{'='*50}")
    sys.exit(0 if result.wasSuccessful() else 1)
