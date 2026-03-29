"""
Vision AI Drone Recognition Layer — UPIN

Real-time drone detection, classification, and tracking from camera feeds.
Integrates with UPIN's fusion system to provide visual confirmation of
aerial targets and enhance threat detection capabilities.

Modular design allows adding more vision layers for different use cases.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Dict, List, Optional, Tuple

import numpy as np


class DroneType(Enum):
    UNKNOWN = auto()
    QUADCOPTER = auto()
    FIXED_WING = auto()
    HELICOPTER = auto()
    MILITARY_UAV = auto()
    COMMERCIAL_DRONE = auto()
    FPV_RACING = auto()
    TOY_DRONE = auto()


class ThreatLevel(Enum):
    BENIGN = auto()      # Toy drone, clearly harmless
    SUSPICIOUS = auto()  # Unknown drone in sensitive area
    HOSTILE = auto()     # Military drone or aggressive behavior
    CONFIRMED = auto()   # Verified threat through other means


@dataclass
class DroneDetection:
    """One detected drone from vision analysis."""
    detection_id: str
    timestamp: float

    # Visual properties
    bounding_box: Tuple[int, int, int, int]  # x, y, width, height
    confidence: float                        # 0.0-1.0 detection confidence
    drone_type: DroneType
    estimated_size_cm: float                # Estimated physical size

    # Position and movement
    pixel_x: int
    pixel_y: int
    estimated_distance_m: Optional[float] = None
    estimated_altitude_m: Optional[float] = None
    velocity_estimate: Optional[Tuple[float, float]] = None  # (speed_ms, heading_deg)

    # Classification details
    threat_level: ThreatLevel = ThreatLevel.BENIGN
    classification_features: Dict[str, float] = field(default_factory=dict)
    tracking_id: Optional[str] = None        # For multi-frame tracking

    # Integration with UPIN
    affects_navigation: bool = False          # Does this drone interfere with sensors?
    requires_human_review: bool = False       # Flag for operator attention


class DroneRecognizer:
    """
    Vision AI system for real-time drone recognition.

    Processes camera feeds to detect, classify, and track drones.
    Integrates with UPIN's threat detection and IFF systems.
    """

    def __init__(self):
        self.detection_history: List[DroneDetection] = []
        self.active_tracks: Dict[str, List[DroneDetection]] = {}
        self.classification_enabled = True
        self.threat_assessment_enabled = True

        # Detection parameters
        self.confidence_threshold = 0.7
        self.max_detection_distance_m = 2000.0
        self.track_timeout_seconds = 10.0

        # Classification thresholds
        self.threat_thresholds = {
            'military_confidence': 0.8,
            'large_size_cm': 100.0,
            'high_speed_ms': 25.0,
            'sensitive_area_proximity_m': 200.0
        }

    def process_frame(self, frame: np.ndarray, camera_params: Dict) -> List[DroneDetection]:
        """
        Process one camera frame and return detected drones.

        Args:
            frame: Camera image as numpy array
            camera_params: Camera calibration and position info
        """
        detections = []

        # Simulate drone detection (in real implementation, this would use
        # a trained neural network like YOLOv8 or custom drone detection model)
        mock_detections = self._simulate_drone_detection(frame, camera_params)

        for detection in mock_detections:
            # Enhance detection with classification
            enhanced_detection = self._classify_drone(detection, frame)

            # Assess threat level
            enhanced_detection = self._assess_threat_level(enhanced_detection, camera_params)

            # Update tracking
            enhanced_detection = self._update_tracking(enhanced_detection)

            detections.append(enhanced_detection)

        # Clean up old tracks
        self._cleanup_old_tracks()

        # Store in history
        self.detection_history.extend(detections)

        return detections

    def _simulate_drone_detection(self, frame: np.ndarray, camera_params: Dict) -> List[DroneDetection]:
        """
        Simulate drone detection (replace with real AI model).
        In production, this would be YOLOv8, custom CNN, or similar.
        """
        detections = []

        # Simulate finding 0-2 drones in frame
        num_drones = np.random.choice([0, 0, 0, 1, 2], p=[0.6, 0.2, 0.1, 0.08, 0.02])

        for i in range(num_drones):
            # Random detection parameters (simulated)
            x = np.random.randint(50, frame.shape[1] - 150)
            y = np.random.randint(50, frame.shape[0] - 100)
            w = np.random.randint(80, 200)
            h = np.random.randint(60, 150)

            confidence = np.random.uniform(0.75, 0.98)

            # Estimate distance from object size (larger = closer)
            estimated_distance = max(50.0, 5000.0 / max(w, h))  # Rough inverse relationship

            detection = DroneDetection(
                detection_id=f"drone_{int(time.time() * 1000)}_{i}",
                timestamp=time.time(),
                bounding_box=(x, y, w, h),
                confidence=confidence,
                drone_type=DroneType.UNKNOWN,
                estimated_size_cm=40.0,  # Will be classified later
                pixel_x=x + w//2,
                pixel_y=y + h//2,
                estimated_distance_m=estimated_distance
            )

            detections.append(detection)

        return detections

    def _classify_drone(self, detection: DroneDetection, frame: np.ndarray) -> DroneDetection:
        """Classify drone type from visual features."""
        if not self.classification_enabled:
            return detection

        # Simulate classification based on bounding box size and aspect ratio
        bbox = detection.bounding_box
        width, height = bbox[2], bbox[3]
        aspect_ratio = width / max(height, 1)
        size_pixels = width * height

        # Classification logic (simplified for simulation)
        features = {
            'aspect_ratio': aspect_ratio,
            'size_pixels': float(size_pixels),
            'symmetry_score': float(np.random.uniform(0.3, 0.9)),
            'rotor_visibility': float(np.random.uniform(0.1, 0.8)),
            'military_features': float(np.random.uniform(0.0, 0.3))
        }

        # Classify based on features
        if features['military_features'] > 0.7:
            drone_type = DroneType.MILITARY_UAV
            estimated_size = 200.0
        elif aspect_ratio > 2.0:
            drone_type = DroneType.FIXED_WING
            estimated_size = 120.0
        elif features['rotor_visibility'] > 0.6:
            if size_pixels > 15000:
                drone_type = DroneType.QUADCOPTER
                estimated_size = 60.0
            else:
                drone_type = DroneType.TOY_DRONE
                estimated_size = 25.0
        else:
            drone_type = DroneType.UNKNOWN
            estimated_size = 50.0

        detection.drone_type = drone_type
        detection.estimated_size_cm = estimated_size
        detection.classification_features = features

        return detection

    def _assess_threat_level(self, detection: DroneDetection, camera_params: Dict) -> DroneDetection:
        """Assess threat level based on classification and context."""
        if not self.threat_assessment_enabled:
            detection.threat_level = ThreatLevel.BENIGN
            return detection

        threat_score = 0.0

        # Size factor
        if detection.estimated_size_cm > self.threat_thresholds['large_size_cm']:
            threat_score += 0.3

        # Type factor
        if detection.drone_type == DroneType.MILITARY_UAV:
            threat_score += 0.5
        elif detection.drone_type == DroneType.TOY_DRONE:
            threat_score -= 0.2

        # Military features
        military_conf = detection.classification_features.get('military_features', 0.0)
        if military_conf > self.threat_thresholds['military_confidence']:
            threat_score += 0.4

        # Distance factor (closer = more threatening)
        if detection.estimated_distance_m and detection.estimated_distance_m < 500.0:
            threat_score += 0.2

        # Determine final threat level
        if threat_score >= 0.7:
            detection.threat_level = ThreatLevel.HOSTILE
            detection.requires_human_review = True
        elif threat_score >= 0.4:
            detection.threat_level = ThreatLevel.SUSPICIOUS
            detection.requires_human_review = True
        else:
            detection.threat_level = ThreatLevel.BENIGN

        return detection

    def _update_tracking(self, detection: DroneDetection) -> DroneDetection:
        """Update multi-frame tracking for this detection."""
        # Simple tracking based on position proximity
        best_match_id = None
        best_distance = float('inf')

        for track_id, track_history in self.active_tracks.items():
            if not track_history:
                continue

            last_detection = track_history[-1]
            time_gap = detection.timestamp - last_detection.timestamp

            if time_gap > self.track_timeout_seconds:
                continue

            # Calculate pixel distance
            dx = detection.pixel_x - last_detection.pixel_x
            dy = detection.pixel_y - last_detection.pixel_y
            pixel_distance = np.sqrt(dx**2 + dy**2)

            # Expected movement (pixels per second)
            expected_movement = time_gap * 30.0  # Assume max 30 pixels/second movement

            if pixel_distance < expected_movement and pixel_distance < best_distance:
                best_distance = pixel_distance
                best_match_id = track_id

        if best_match_id:
            # Continue existing track
            detection.tracking_id = best_match_id
            self.active_tracks[best_match_id].append(detection)
        else:
            # Start new track
            new_track_id = f"track_{len(self.active_tracks):04d}"
            detection.tracking_id = new_track_id
            self.active_tracks[new_track_id] = [detection]

        return detection

    def _cleanup_old_tracks(self) -> None:
        """Remove tracks that haven't been updated recently."""
        current_time = time.time()
        expired_tracks = []

        for track_id, track_history in self.active_tracks.items():
            if not track_history:
                expired_tracks.append(track_id)
                continue

            last_time = track_history[-1].timestamp
            if current_time - last_time > self.track_timeout_seconds:
                expired_tracks.append(track_id)

        for track_id in expired_tracks:
            del self.active_tracks[track_id]

    def get_current_threats(self) -> List[DroneDetection]:
        """Get currently tracked threats."""
        current_threats = []
        current_time = time.time()

        for track_history in self.active_tracks.values():
            if track_history:
                latest_detection = track_history[-1]
                if (current_time - latest_detection.timestamp < self.track_timeout_seconds and
                    latest_detection.threat_level in [ThreatLevel.SUSPICIOUS, ThreatLevel.HOSTILE]):
                    current_threats.append(latest_detection)

        return current_threats

    def get_detection_summary(self) -> Dict:
        """Get summary of recent detection activity."""
        recent_time = time.time() - 60.0  # Last 60 seconds
        recent_detections = [d for d in self.detection_history if d.timestamp > recent_time]

        threat_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}

        for detection in recent_detections:
            threat_counts[detection.threat_level.name] = threat_counts.get(detection.threat_level.name, 0) + 1
            type_counts[detection.drone_type.name] = type_counts.get(detection.drone_type.name, 0) + 1

        return {
            'total_detections_1min': len(recent_detections),
            'active_tracks': len(self.active_tracks),
            'current_threats': len(self.get_current_threats()),
            'threat_level_counts': threat_counts,
            'drone_type_counts': type_counts,
            'requires_human_review': len([d for d in recent_detections if d.requires_human_review])
        }
