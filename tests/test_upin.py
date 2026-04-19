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

class TestDroneRecognition(unittest.TestCase):
    """Tests for vision AI drone recognition."""

    def setUp(self):
        from upin.vision.drone_recognition import DroneRecognizer
        import numpy as np
        self.DroneRecognizer = DroneRecognizer
        self.np = np

    def test_recognizer_initializes(self):
        recognizer = self.DroneRecognizer()
        self.assertEqual(len(recognizer.detection_history), 0)
        self.assertEqual(len(recognizer.active_tracks), 0)

    def test_frame_processing(self):
        recognizer = self.DroneRecognizer()
        frame = self.np.random.randint(0, 255, (720, 1280, 3), dtype=self.np.uint8)
        camera_params = {'position_lat': 13.0827, 'position_lon': 80.2707}

        detections = recognizer.process_frame(frame, camera_params)
        self.assertIsInstance(detections, list)

    def test_threat_assessment(self):
        recognizer = self.DroneRecognizer()
        threats = recognizer.get_current_threats()
        self.assertIsInstance(threats, list)

    def test_detection_summary(self):
        recognizer = self.DroneRecognizer()
        summary = recognizer.get_detection_summary()
        self.assertIn('total_detections_1min', summary)
        self.assertIn('active_tracks', summary)


class TestFishSchooling(unittest.TestCase):
    """Tests for fish schooling fusion algorithm."""

    def setUp(self):
        from upin.swarm_fusion.fish_schooling import FishSchoolingFusion
        from upin.core.layer_base import LayerReading
        from upin.core.position import Position
        self.FishSchoolingFusion = FishSchoolingFusion
        self.LayerReading = LayerReading
        self.Position = Position

    def test_fusion_with_readings(self):
        fusion = self.FishSchoolingFusion()
        readings = [
            self.LayerReading(layer_id='test1', position=self.Position(latitude=13.0827, longitude=80.2707, accuracy_m=5.0), self_confidence=0.95),
            self.LayerReading(layer_id='test2', position=self.Position(latitude=13.0825, longitude=80.2709, accuracy_m=10.0), self_confidence=0.85),
        ]

        position, metadata = fusion.fuse_readings(readings)
        self.assertIsNotNone(position)
        self.assertIn('algorithm', metadata)
        self.assertEqual(metadata['algorithm'], 'Fish_Schooling')

    def test_empty_readings(self):
        fusion = self.FishSchoolingFusion()
        position, metadata = fusion.fuse_readings([])
        self.assertEqual(position.accuracy_m, 1000.0)

    def test_bad_sensor_rejection(self):
        fusion = self.FishSchoolingFusion()
        readings = [
            self.LayerReading(layer_id='good', position=self.Position(latitude=13.0827, longitude=80.2707, accuracy_m=5.0), self_confidence=0.95),
            self.LayerReading(layer_id='bad', position=self.Position(latitude=13.1000, longitude=80.3000, accuracy_m=100.0), self_confidence=0.20),
        ]

        position, metadata = fusion.fuse_readings(readings)
        # Should be closer to good sensor
        self.assertLess(abs(position.latitude - 13.0827), 0.01)


class TestMultiFusion(unittest.TestCase):
    """Tests for multi-algorithm fusion engine."""

    def setUp(self):
        from upin.fusion.multi_fusion_engine import MultiFusionEngine
        from upin.core.layer_base import LayerReading
        from upin.core.position import Position
        self.MultiFusionEngine = MultiFusionEngine
        self.LayerReading = LayerReading
        self.Position = Position

    def test_multiple_algorithms_run(self):
        engine = self.MultiFusionEngine()
        readings = [
            self.LayerReading(layer_id='test', position=self.Position(latitude=13.0827, longitude=80.2707, accuracy_m=5.0), self_confidence=0.95),
        ]

        results = engine.fuse_all_algorithms(readings)
        self.assertGreater(len(results), 0)

    def test_best_result_selection(self):
        engine = self.MultiFusionEngine()
        readings = [
            self.LayerReading(layer_id='test1', position=self.Position(latitude=13.0827, longitude=80.2707, accuracy_m=5.0), self_confidence=0.95),
            self.LayerReading(layer_id='test2', position=self.Position(latitude=13.0825, longitude=80.2709, accuracy_m=10.0), self_confidence=0.85),
        ]

        position, metadata = engine.get_consensus_position(readings)
        self.assertIsNotNone(position)
        self.assertIn('best_algorithm', metadata)


class TestEncryption(unittest.TestCase):
    """Tests for encrypted communications."""

    def setUp(self):
        from upin.security.encryption import SecureComm, ClassificationLevel
        self.SecureComm = SecureComm
        self.ClassificationLevel = ClassificationLevel

    def test_encryption_decryption(self):
        alice = self.SecureComm("alice")
        bob = self.SecureComm("bob")

        # Establish session
        alice.establish_session("bob")
        bob.session_keys["alice"] = alice.session_keys["bob"]

        # Encrypt message
        test_data = {"lat": 13.0827, "lon": 80.2707, "confidence": 0.95}
        encrypted_msg = alice.encrypt_message(test_data, "bob", self.ClassificationLevel.CONFIDENTIAL)

        # Decrypt message
        decrypted_data = bob.decrypt_message(encrypted_msg)
        self.assertEqual(decrypted_data["lat"], 13.0827)

    def test_security_status(self):
        comm = self.SecureComm("test_node")
        status = comm.get_security_status()
        self.assertIn('node_id', status)
        self.assertIn('active_sessions', status)


class TestCalibrationManager(unittest.TestCase):
    """Tests for calibration system."""

    def setUp(self):
        from upin.calibration.calibration_manager import CalibrationManager, SensorType
        self.CalibrationManager = CalibrationManager
        self.SensorType = SensorType

    def test_calibration_manager_init(self):
        manager = self.CalibrationManager("test_device")
        self.assertEqual(manager.device_id, "test_device")

    def test_sensor_compensation(self):
        manager = self.CalibrationManager("test_device")
        readings = {self.SensorType.GPS: 13.0830}
        compensated = manager.apply_all_compensations(readings)
        self.assertIn(self.SensorType.GPS, compensated)

    def test_calibration_status(self):
        manager = self.CalibrationManager("test_device")
        status = manager.get_calibration_status()
        self.assertIn('device_id', status)
        self.assertIn('auto_calibration', status)


class TestWiFiCSISensor(unittest.TestCase):
    """Tests for WiFi CSI through-wall sensor."""

    def test_sensor_init(self):
        from upin.sensors.wifi_csi_sensor import WiFiCSISensor, WallMaterial
        sensor = WiFiCSISensor("test", WallMaterial.DRYWALL)
        self.assertEqual(sensor.sensor_id, "test")

    def test_scan_returns_roomscan(self):
        from upin.sensors.wifi_csi_sensor import WiFiCSISensor, WallMaterial
        sensor = WiFiCSISensor("test", WallMaterial.DRYWALL)
        sensor.set_position(13.08, 80.27, 0)
        sensor.add_simulated_nodes(4)
        scan = sensor.scan()
        self.assertIsNotNone(scan)
        self.assertGreaterEqual(scan.person_count, 0)

    def test_stats(self):
        from upin.sensors.wifi_csi_sensor import WiFiCSISensor, WallMaterial
        sensor = WiFiCSISensor("test", WallMaterial.CONCRETE)
        stats = sensor.get_stats()
        self.assertEqual(stats["wall_material"], "concrete")


class TestDriftCompensation(unittest.TestCase):
    """Tests for sensor drift compensation."""

    def test_compensator_init(self):
        from upin.calibration.drift_compensation import DriftCompensator
        comp = DriftCompensator("dev-001")
        self.assertEqual(comp.device_id, "dev-001")

    def test_add_calibration_points(self):
        from upin.calibration.drift_compensation import DriftCompensator, SensorType
        comp = DriftCompensator("dev-001")
        comp.add_calibration_point(SensorType.GPS, 13.083, 13.0827, 25.0, 13.08, 80.27)
        comp.add_calibration_point(SensorType.GPS, 13.084, 13.0827, 26.0, 13.08, 80.27)
        bias = comp.get_bias(SensorType.GPS)
        self.assertIsNotNone(bias)

    def test_no_compensation_without_data(self):
        from upin.calibration.drift_compensation import DriftCompensator, SensorType
        comp = DriftCompensator("dev-001")
        corrected, applied = comp.apply_compensation(SensorType.GPS, 13.083)
        self.assertFalse(applied)


class TestReferencePoints(unittest.TestCase):
    """Tests for reference points database."""

    def test_global_db_loads(self):
        from upin.calibration.reference_points import reference_db
        all_points = reference_db.list_all_points()
        self.assertGreater(len(all_points), 30)

    def test_nearby_search(self):
        from upin.calibration.reference_points import reference_db
        nearby = reference_db.find_nearby(18.922, 72.835, 500)
        self.assertGreater(len(nearby), 0)

    def test_city_points(self):
        from upin.calibration.reference_points import reference_db
        mumbai = reference_db.get_city_points("mumbai")
        self.assertGreater(len(mumbai), 0)
        paris = reference_db.get_city_points("paris")
        self.assertGreater(len(paris), 0)


class TestMissionRecorder(unittest.TestCase):
    """Tests for mission data recorder."""

    def test_recorder_init(self):
        from upin.logging.mission_recorder import MissionRecorder
        rec = MissionRecorder("M001", "D001")
        self.assertEqual(rec.mission_id, "M001")

    def test_record_events(self):
        from upin.logging.mission_recorder import MissionRecorder
        rec = MissionRecorder("M001", "D001")
        rec.record_sensor_reading("GPS", 13.08, 0.95)
        rec.record_threat_detection("SPOOFING", "HIGH", "mahalanobis", {})
        self.assertEqual(len(rec.get_mission_timeline()), 2)

    def test_mission_summary(self):
        from upin.logging.mission_recorder import MissionRecorder
        rec = MissionRecorder("M001", "D001")
        rec.record_sensor_reading("GPS", 13.08, 0.95)
        summary = rec.get_mission_summary()
        self.assertEqual(summary["total_events"], 1)

    def test_ai_export_filters_classified(self):
        from upin.logging.mission_recorder import MissionRecorder
        rec = MissionRecorder("M001", "D001")
        rec.record_sensor_reading("GPS", 13.08, 0.95)
        rec.record_jammer_triangulation(13.08, 80.27, 0.94, 5, "GPS_SPOOFER")
        export = rec.export_for_ai_training(classification_filter=1)
        # Jammer event is classified SECRET (level 3), should be filtered out
        self.assertLess(len(export["events"]), 2)


class TestFusionMicroservice(unittest.TestCase):
    """Tests for fusion microservices."""

    def test_orchestrator_init(self):
        from upin.services.fusion_microservice import ServiceOrchestrator
        orch = ServiceOrchestrator()
        self.assertEqual(len(orch.services), 0)

    def test_register_and_process(self):
        from upin.services.fusion_microservice import (
            ServiceOrchestrator, ServiceConfig, KalmanMicroservice
        )
        from upin.core.layer_base import LayerReading
        from upin.core.position import Position
        orch = ServiceOrchestrator()
        config = ServiceConfig(
            service_id="k1", algorithm_name="Kalman",
            parameters={"process_noise": 0.1, "measurement_noise": 1.0, "min_readings": 1},
        )
        orch.register_service(config, KalmanMicroservice)
        readings = [
            LayerReading(layer_id="gps", position=Position(latitude=13.08, longitude=80.27, accuracy_m=5.0), self_confidence=0.9),
        ]
        results = orch.process_parallel(readings)
        self.assertGreater(len(results), 0)

    def test_system_health(self):
        from upin.services.fusion_microservice import ServiceOrchestrator
        orch = ServiceOrchestrator()
        health = orch.get_system_health()
        self.assertIn("total_services", health)


class TestRestServer(unittest.TestCase):
    """Tests for REST API server."""

    def test_server_init(self):
        from upin.api.rest_server import UPINApiServer
        server = UPINApiServer(None, port=9999)
        self.assertEqual(server.port, 9999)

    def test_routes_listed(self):
        from upin.api.rest_server import UPINApiServer
        server = UPINApiServer(None)
        routes = server.get_routes()
        self.assertEqual(len(routes), 6)


class TestBoundaryManager(unittest.TestCase):
    """Tests for geofencing boundary manager."""

    def test_default_boundaries_loaded(self):
        from upin.geofencing.boundary_manager import BoundaryManager
        mgr = BoundaryManager()
        self.assertEqual(len(mgr.boundaries), 3)

    def test_point_inside_chennai(self):
        from upin.geofencing.boundary_manager import BoundaryManager
        from upin.core.position import Position
        mgr = BoundaryManager()
        pos = Position(latitude=13.08, longitude=80.27, accuracy_m=10.0)
        violations = mgr.check_position(pos)
        # Chennai position is inside chennai_ops but outside mumbai_ops
        chennai_exits = [v for v in violations
                         if v.boundary.boundary_id == "chennai_ops" and v.violation_type.name == "EXIT"]
        self.assertEqual(len(chennai_exits), 0)

    def test_boundary_status(self):
        from upin.geofencing.boundary_manager import BoundaryManager
        mgr = BoundaryManager()
        status = mgr.get_boundary_status()
        self.assertEqual(status["total_boundaries"], 3)


class TestPowerManager(unittest.TestCase):
    """Tests for power management."""

    def test_full_battery_all_layers(self):
        from upin.power.power_manager import PowerManager
        pm = PowerManager()
        pm.update_battery_level(100.0)
        active = pm.get_active_layers()
        self.assertGreater(len(active), 5)

    def test_emergency_battery_fewer_layers(self):
        from upin.power.power_manager import PowerManager
        pm = PowerManager()
        pm.update_battery_level(3.0)
        active = pm.get_active_layers()
        full_pm = PowerManager()
        full_pm.update_battery_level(100.0)
        full_active = full_pm.get_active_layers()
        self.assertLess(len(active), len(full_active))

    def test_power_status(self):
        from upin.power.power_manager import PowerManager
        pm = PowerManager()
        pm.update_battery_level(65.0)
        status = pm.get_power_status()
        self.assertEqual(status["power_state"], "NORMAL")


class TestMahalanobisDetector(unittest.TestCase):
    """Tests for Mahalanobis distance spoofing detection."""

    def test_detector_init(self):
        from upin.detection.mahalanobis_detector import MahalanobisDetector
        det = MahalanobisDetector(sensitivity=3.0)
        self.assertEqual(det.sensitivity, 3.0)

    def test_baseline_update(self):
        from upin.detection.mahalanobis_detector import MahalanobisDetector
        from upin.core.layer_base import LayerReading
        from upin.core.position import Position
        det = MahalanobisDetector()
        readings = [
            LayerReading(layer_id="gps", position=Position(latitude=13.08, longitude=80.27, accuracy_m=5.0), self_confidence=0.9),
            LayerReading(layer_id="wifi", position=Position(latitude=13.08, longitude=80.27, accuracy_m=15.0), self_confidence=0.7),
        ]
        det.update_baseline(readings)
        self.assertIsNotNone(det.baseline_mean)
        self.assertEqual(det.baseline_samples, 2)

    def test_detection_summary(self):
        from upin.detection.mahalanobis_detector import MahalanobisDetector
        det = MahalanobisDetector()
        summary = det.get_detection_summary()
        self.assertIn("baseline_established", summary)
        self.assertFalse(summary["baseline_established"])

class TestEagleEye(unittest.TestCase):
    def test_eagle_eye_reads(self):
        from upin.layers.optical.eagle_eye import EagleEyeStereoLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = EagleEyeStereoLayer()
        layer.set_world(w)
        layer.initialize()
        reading = layer.read()
        self.assertTrue(reading.is_valid)
        self.assertIsNotNone(reading.position)
        self.assertIn("stereo_altitude_m", reading.raw_data)

    def test_enc_layer(self):
        from upin.layers.optical.eagle_eye import ENCChartMatchingLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = ENCChartMatchingLayer()
        layer.set_world(w)
        layer.initialize()
        reading = layer.read()
        self.assertTrue(reading.is_valid)
        self.assertTrue(layer.is_underwater)

    def test_dted_layer(self):
        from upin.layers.optical.eagle_eye import DTEDMatchingLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = DTEDMatchingLayer()
        layer.set_world(w)
        layer.initialize()
        reading = layer.read()
        self.assertTrue(reading.is_valid)
        self.assertIn("terrain_elevation_m", reading.raw_data)

class TestNauticalLayers(unittest.TestCase):
    def test_bathymetry(self):
        from upin.layers.acoustic.bathymetry import BathymetricMatchingLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = BathymetricMatchingLayer()
        layer.set_world(w)
        layer.initialize()
        for _ in range(10):
            layer.read()
        reading = layer.read()
        self.assertTrue(reading.is_valid)
        self.assertIn("current_depth_m", reading.raw_data)
        self.assertTrue(layer.is_underwater)

    def test_ocean_current(self):
        from upin.layers.chemical.nautical import OceanCurrentDriftLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = OceanCurrentDriftLayer()
        layer.set_world(w)
        layer.initialize()
        reading = layer.read()
        self.assertTrue(reading.is_valid)
        self.assertIsNotNone(reading.velocity)
        self.assertTrue(layer.is_underwater)

    def test_tidal_timing(self):
        from upin.layers.chemical.nautical import TidalTimingPositionLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = TidalTimingPositionLayer()
        layer.set_world(w)
        layer.initialize()
        reading = layer.read()
        self.assertTrue(reading.is_valid)
        self.assertTrue(layer.is_underwater)

class TestTerrainFingerprint(unittest.TestCase):
    def test_fp_map_records_and_matches(self):
        from upin.core.terrain_fingerprint import TerrainFingerprint, TerrainFingerprintMap
        m = TerrainFingerprintMap(sample_interval_m=1.0)
        for i in range(5):
            m.record(TerrainFingerprint(
                lat=13.08 + i * 0.001, lon=80.27, timestamp=i,
                mag_intensity_nt=45000 + i * 100, baro_pressure_hpa=1013,
            ))
        self.assertEqual(m.map_size, 5)
        query = TerrainFingerprint(
            lat=0, lon=0, timestamp=0,
            mag_intensity_nt=45250, baro_pressure_hpa=1013,
        )
        est = m.estimate_position(query)
        self.assertIsNotNone(est)
        self.assertIn("lat", est)

    def test_fp_layer(self):
        from upin.layers.systems.terrain_fp_layer import TerrainFingerprintLayer
        from upin.simulation.world import SimulationWorld
        w = SimulationWorld()
        layer = TerrainFingerprintLayer()
        layer.set_world(w)
        layer.initialize()
        for _ in range(5):
            w.step(0.1)
            layer.read()
        reading = layer.read()
        self.assertTrue(reading.is_valid)

class TestPUEConstraint(unittest.TestCase):
    def test_radius_grows_with_time(self):
        from upin.core.pue_constraint import PositionUncertaintyEnvelope
        import time
        pue = PositionUncertaintyEnvelope(max_accel_ms2=5.0, max_speed_ms=50.0)
        pue.set_known_fix(13.08, 80.27, speed_ms=10.0)
        time.sleep(0.05)
        r1 = pue.get_max_radius()
        time.sleep(0.05)
        r2 = pue.get_max_radius()
        self.assertGreater(r2, r1)

    def test_smart_constraint_engine(self):
        from upin.core.pue_constraint import (
            PositionUncertaintyEnvelope, SmartConstraintEngine,
        )
        pue = PositionUncertaintyEnvelope()
        pue.set_known_fix(13.08, 80.27, speed_ms=5.0)
        sce = SmartConstraintEngine(pue)
        result = sce.update_sensors(accel_magnitude_ms2=0.1,
                                     cell_accuracy_m=20.0)
        self.assertIn("final_radius_m", result)
        self.assertIn("winner", result)

class TestRouteDTW(unittest.TestCase):
    def test_record_and_match(self):
        from upin.core.route_dtw import RouteDTWLearning, RouteSample
        r = RouteDTWLearning(sample_interval_m=1.0)
        r.start_recording("route1", "test")
        for i in range(5):
            r.record_sample(RouteSample(
                lat=13.08 + i * 0.001, lon=80.27, timestamp=i,
                heading_deg=45, mag_intensity_nt=45000 + i * 50,
                baro_pressure_hpa=1013,
            ))
        route = r.stop_recording()
        self.assertIsNotNone(route)
        self.assertEqual(len(route.samples), 5)
        live = [
            RouteSample(lat=0, lon=0, timestamp=0, heading_deg=45,
                         mag_intensity_nt=45050, baro_pressure_hpa=1013),
            RouteSample(lat=0, lon=0, timestamp=1, heading_deg=45,
                         mag_intensity_nt=45100, baro_pressure_hpa=1013),
        ]
        result = r.match_live(live)
        self.assertIsNotNone(result)
        self.assertIn("lat", result)

class TestManeuverRecognition(unittest.TestCase):
    def test_turn_detection(self):
        from upin.core.maneuver_recognition import ManeuverRecognizer
        import time
        mr = ManeuverRecognizer()
        mr.feed_imu(gyro_z_rad_s=0.02, accel_magnitude_ms2=0.5)
        for _ in range(30):
            mr.feed_imu(gyro_z_rad_s=1.6, accel_magnitude_ms2=2.0,
                         heading_deg=90)
            time.sleep(0.02)
        event = mr.feed_imu(gyro_z_rad_s=0.05, accel_magnitude_ms2=0.5)
        self.assertIsNotNone(event)
        self.assertIn("type", event)

    def test_library_stats(self):
        from upin.core.maneuver_recognition import ManeuverRecognizer
        mr = ManeuverRecognizer()
        stats = mr.get_library_stats()
        self.assertIn("total", stats)
        self.assertEqual(stats["total"], 0)

class TestFormulaAgents(unittest.TestCase):
    def test_agent_params_mutation(self):
        from upin.core.formula_agents import AgentParams
        p = AgentParams.random()
        child = p.mutate()
        self.assertIsInstance(child, AgentParams)
        self.assertGreaterEqual(child.accel_scale, 0.5)
        self.assertLessEqual(child.accel_scale, 1.5)

    def test_pool_evolution(self):
        from upin.core.formula_agents import FormulaAgentManager
        fam = FormulaAgentManager(agents_per_formula=5)
        fam.register_formula("kalman")
        pool = fam.get_pool("kalman")
        # Score with predictions around truth
        preds = [(13.08 + i * 0.0001, 80.27) for i in range(5)]
        for _ in range(12):
            pool.score_all(13.08, 80.27, preds)
        best = pool.best_agent()
        self.assertIsNotNone(best)

class TestAutoCombo(unittest.TestCase):
    def test_combo_discovery(self):
        from upin.core.auto_combo import AutoComboDiscovery
        ac = AutoComboDiscovery(
            ["vel_sma", "kalman", "step", "macd"],
            population_size=10,
            evolution_interval=5,
        )
        outputs = {
            "vel_sma": (13.08, 80.27),
            "kalman": (13.081, 80.271),
            "step": (13.079, 80.269),
            "macd": (13.082, 80.272),
        }
        for _ in range(10):
            ac.score_and_evolve((13.08, 80.27), outputs)
        stats = ac.get_stats()
        self.assertGreater(stats["generation"], 0)
        best = ac.best_combo()
        self.assertTrue(len(best.formula_names) >= 2)

class TestTrainingConstraint(unittest.TestCase):
    def test_leash_pulls_outliers(self):
        from upin.core.training_constraint import TrainingConstraint
        tc = TrainingConstraint(leash_radius_m=10.0)
        lat, lon, pulled = tc.apply(13.08, 80.27, 13.09, 80.28)
        self.assertTrue(pulled)
        lat, lon, pulled = tc.apply(13.08, 80.27, 13.08001, 80.27001)
        self.assertFalse(pulled)

class TestNLLSTrilateration(unittest.TestCase):
    def test_nlls_converges(self):
        from upin.core.nlls_trilateration import NLLSTrilateration
        import math
        nlls = NLLSTrilateration()
        # Tower configs around truth at (13.08, 80.27)
        true_lat, true_lon = 13.08, 80.27
        # 4 towers — non-symmetric layout avoids mirror ambiguity
        towers = [(13.07, 80.26), (13.09, 80.26), (13.09, 80.28), (13.07, 80.28)]
        obs = []
        for tl, tn in towers:
            d = math.sqrt(((true_lat - tl) * 111320) ** 2
                          + ((true_lon - tn) * 111320
                             * math.cos(math.radians(true_lat))) ** 2)
            obs.append((tl, tn, d))
        result = nlls.solve(obs, initial_guess=(true_lat + 0.001,
                                                   true_lon + 0.001))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["lat"], true_lat, places=3)
        self.assertAlmostEqual(result["lon"], true_lon, places=3)

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
