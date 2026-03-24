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
