"""
RF-DETR Vision Feature Extractor — UPIN

Roboflow's open-source real-time object detection model (Apache 2.0).
Feeds the existing vision layers:
  - L31 Visual SLAM (vslam_l31) — landmark detection for map building
  - L32 Visual Odometry (vio_l32) — feature tracking between frames
  - L72 Eagle Thermal Vision (eagle_e12) — threat detection + visual SLAM

Lazy import: rfdetr is NOT imported at module load. Only imported inside
load_model() so missing rfdetr does not break UPIN. If rfdetr is not
installed, is_available() returns False and layers fall back to their
existing behaviour.

Apache-licensed model sizes only:
  nano, small, medium, base, large
  (XL and 2XL are PML 1.0 — do NOT use without commercial license)

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


MODEL_CONFIGS = {
    "nano":   {"variant": "rf-detr-nano",   "params_m": 3.0,  "fps_jetson": 45},
    "small":  {"variant": "rf-detr-small",  "params_m": 7.0,  "fps_jetson": 30},
    "medium": {"variant": "rf-detr-medium", "params_m": 15.0, "fps_jetson": 20},
    "base":   {"variant": "rf-detr-base",   "params_m": 29.0, "fps_jetson": 12},
    "large":  {"variant": "rf-detr-large",  "params_m": 60.0, "fps_jetson": 6},
}

RESTRICTED_MODELS = {"xl", "2xl"}


@dataclass
class Detection:
    """A single object detection result."""
    class_name: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (xyxy)
    detection_id: int


class RFDETRExtractor:
    """RF-DETR feature extractor with lazy loading and graceful fallback.

    Usage:
        extractor = RFDETRExtractor(model_size='nano')
        if extractor.is_available():
            extractor.load_model()
            detections = extractor.detect_objects(image)
            features = extractor.extract_features(image)
    """

    def __init__(self, model_size: str = "nano",
                 confidence_threshold: float = 0.5):
        if model_size in RESTRICTED_MODELS:
            raise ValueError(
                f"Model size '{model_size}' requires PML 1.0 license. "
                f"Use one of: {list(MODEL_CONFIGS.keys())}")
        if model_size not in MODEL_CONFIGS:
            raise ValueError(
                f"Unknown model size '{model_size}'. "
                f"Available: {list(MODEL_CONFIGS.keys())}")

        self._model_size = model_size
        self._config = MODEL_CONFIGS[model_size]
        self._confidence_threshold = confidence_threshold
        self._model: Any = None
        self._rfdetr_module: Any = None
        self._available: Optional[bool] = None
        self._load_time_ms: float = 0.0
        self._inference_count: int = 0

    def is_available(self) -> bool:
        """Check if rfdetr package is installed. Does NOT load the model."""
        if self._available is not None:
            return self._available
        try:
            import importlib
            importlib.import_module("rfdetr")
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def load_model(self) -> bool:
        """Lazy-load the RF-DETR model. Returns True if successful."""
        if not self.is_available():
            return False
        if self._model is not None:
            return True

        try:
            import rfdetr
            self._rfdetr_module = rfdetr
            t0 = time.time()
            self._model = rfdetr.RFDETRBase(
                model_id=self._config["variant"],
            )
            self._load_time_ms = (time.time() - t0) * 1000
            return True
        except Exception:
            self._model = None
            self._available = False
            return False

    def detect_objects(self, image: Any) -> List[Dict]:
        """Run object detection on an image.

        Args:
            image: numpy array (H, W, 3) BGR or RGB, or PIL Image.

        Returns:
            List of dicts with keys: 'class', 'confidence', 'bbox', 'id'
            bbox is in xyxy format (x1, y1, x2, y2).
            Returns empty list if model not loaded or rfdetr unavailable.
        """
        if self._model is None:
            return []

        try:
            results = self._model.predict(image, threshold=self._confidence_threshold)
            self._inference_count += 1
            return self._format_detections(results)
        except Exception:
            return []

    def extract_features(self, image: Any) -> Dict:
        """Extract visual features for SLAM/VIO use.

        Returns feature count, landmark positions, and detection summary
        that vision layers can use for positioning.
        """
        detections = self.detect_objects(image)

        landmarks = []
        for det in detections:
            cx = (det["bbox"][0] + det["bbox"][2]) / 2
            cy = (det["bbox"][1] + det["bbox"][3]) / 2
            landmarks.append({
                "x": cx, "y": cy,
                "class": det["class"],
                "size": ((det["bbox"][2] - det["bbox"][0])
                         * (det["bbox"][3] - det["bbox"][1])),
            })

        return {
            "feature_count": len(detections),
            "landmarks": landmarks,
            "detections": detections,
            "model_size": self._model_size,
            "inference_count": self._inference_count,
        }

    def _format_detections(self, results: Any) -> List[Dict]:
        """Convert rfdetr results to standard UPIN format."""
        detections = []
        try:
            if hasattr(results, "xyxy"):
                boxes = results.xyxy
                confs = results.confidence if hasattr(results, "confidence") else []
                classes = results.data.get("class_name", []) if hasattr(results, "data") else []

                for i in range(len(boxes)):
                    det = {
                        "class": str(classes[i]) if i < len(classes) else "unknown",
                        "confidence": float(confs[i]) if i < len(confs) else 0.0,
                        "bbox": tuple(float(v) for v in boxes[i][:4]),
                        "id": i,
                    }
                    detections.append(det)
            elif isinstance(results, list):
                for i, r in enumerate(results):
                    det = {
                        "class": str(r.get("class", r.get("label", "unknown"))),
                        "confidence": float(r.get("confidence", r.get("score", 0))),
                        "bbox": tuple(r.get("bbox", r.get("box", (0, 0, 0, 0)))),
                        "id": i,
                    }
                    detections.append(det)
        except Exception:
            pass
        return detections

    def get_status(self) -> Dict:
        """Get extractor status for diagnostics."""
        return {
            "model_size": self._model_size,
            "available": self.is_available(),
            "loaded": self._model is not None,
            "load_time_ms": round(self._load_time_ms, 1),
            "inference_count": self._inference_count,
            "config": self._config,
            "confidence_threshold": self._confidence_threshold,
        }
