"""Tests for RF-DETR vision feature extractor."""

import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, ".")


class TestRFDETRImport(unittest.TestCase):
    """Test that RFDETRExtractor can be imported without rfdetr installed."""

    def test_import_does_not_raise(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        self.assertIsNotNone(RFDETRExtractor)

    def test_init_does_not_import_rfdetr(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        self.assertEqual(ext._model_size, "nano")
        self.assertIsNone(ext._model)

    def test_restricted_model_raises(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        with self.assertRaises(ValueError):
            RFDETRExtractor(model_size="xl")
        with self.assertRaises(ValueError):
            RFDETRExtractor(model_size="2xl")

    def test_invalid_model_raises(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        with self.assertRaises(ValueError):
            RFDETRExtractor(model_size="nonexistent")


class TestRFDETRAvailability(unittest.TestCase):
    """Test is_available() when rfdetr is NOT installed."""

    def test_not_available_without_rfdetr(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        ext._available = None  # reset cache
        with patch.dict(sys.modules, {"rfdetr": None}):
            result = ext.is_available()
        self.assertFalse(result)

    def test_load_model_returns_false(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        ext._available = False
        self.assertFalse(ext.load_model())

    def test_detect_returns_empty_without_model(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        result = ext.detect_objects(None)
        self.assertEqual(result, [])

    def test_extract_features_returns_empty(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        result = ext.extract_features(None)
        self.assertEqual(result["feature_count"], 0)
        self.assertEqual(result["detections"], [])


class TestRFDETROutputFormat(unittest.TestCase):
    """Test that the standard output format is enforced."""

    def test_detection_format(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        results = [
            {"class": "car", "confidence": 0.9, "bbox": (10, 20, 100, 200)},
            {"label": "person", "score": 0.8, "box": (30, 40, 80, 160)},
        ]
        formatted = ext._format_detections(results)
        self.assertEqual(len(formatted), 2)
        for det in formatted:
            self.assertIn("class", det)
            self.assertIn("confidence", det)
            self.assertIn("bbox", det)
            self.assertIn("id", det)
            self.assertIsInstance(det["confidence"], float)
            self.assertEqual(len(det["bbox"]), 4)

    def test_status_format(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="base")
        status = ext.get_status()
        self.assertEqual(status["model_size"], "base")
        self.assertIn("available", status)
        self.assertIn("loaded", status)
        self.assertIn("config", status)


class TestLayerBackwardCompatibility(unittest.TestCase):
    """Test that layers still work without rfdetr_extractor."""

    def test_vslam_without_extractor(self):
        from upin.layers.optical.layers import VisualSLAMLayer
        layer = VisualSLAMLayer()
        layer.initialize()
        self.assertIsNone(layer._rfdetr)
        reading = layer.read()
        self.assertTrue(reading.is_valid)

    def test_vio_without_extractor(self):
        from upin.layers.optical.layers import VisualOdometryLayer
        layer = VisualOdometryLayer()
        layer.initialize()
        self.assertIsNone(layer._rfdetr)
        reading = layer.read()
        self.assertTrue(reading.is_valid)

    def test_eagle_without_extractor(self):
        from upin.layers.biological.layers import EagleThermalVisionLayer
        layer = EagleThermalVisionLayer()
        layer.initialize()
        self.assertIsNone(layer._rfdetr)
        reading = layer.read()
        self.assertTrue(reading.is_valid)

    def test_vslam_with_extractor_param(self):
        from upin.layers.optical.layers import VisualSLAMLayer
        from upin.vision.rf_detr_extractor import RFDETRExtractor
        ext = RFDETRExtractor(model_size="nano")
        layer = VisualSLAMLayer(rfdetr_extractor=ext)
        layer.initialize()
        self.assertIs(layer._rfdetr, ext)
        reading = layer.read()
        self.assertTrue(reading.is_valid)


class TestAllModelSizes(unittest.TestCase):
    """Test all Apache-licensed model sizes can be instantiated."""

    def test_all_sizes(self):
        from upin.vision.rf_detr_extractor import RFDETRExtractor, MODEL_CONFIGS
        for size in MODEL_CONFIGS:
            ext = RFDETRExtractor(model_size=size)
            self.assertEqual(ext._model_size, size)
            status = ext.get_status()
            self.assertEqual(status["model_size"], size)


if __name__ == "__main__":
    unittest.main(verbosity=2)
