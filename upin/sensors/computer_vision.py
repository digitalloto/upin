"""
UPIN Computer Vision Module.
Object detection, target classification, visual tracking, structure analysis.
All simulation mode — hardware interfaces added later.
"""
from __future__ import annotations
import time
import uuid
import math
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import numpy as np


class ObjectClass(Enum):
    UNKNOWN          = "unknown"
    PERSON           = "person"
    VEHICLE_LIGHT    = "vehicle_light"
    VEHICLE_HEAVY    = "vehicle_heavy"
    VEHICLE_ARMOURED = "vehicle_armoured"
    AIRCRAFT         = "aircraft"
    BOAT             = "boat"
    STRUCTURE_CIVIL  = "structure_civil"
    STRUCTURE_MIL    = "structure_mil"
    WEAPON_SYSTEM    = "weapon_system"


class ThreatLevel(Enum):
    NONE     = 0
    LOW      = 1
    MODERATE = 2
    HIGH     = 3
    CRITICAL = 4


@dataclass
class DetectedObject:
    object_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    object_class: ObjectClass = ObjectClass.UNKNOWN
    confidence: float = 0.0
    position_px: tuple = (0, 0)
    position_geo: tuple = (0.0, 0.0, 0.0)
    bounding_box: tuple = (0, 0, 0, 0)
    threat_level: ThreatLevel = ThreatLevel.NONE
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    is_military: bool = False
    notes: str = ""

    def age_seconds(self) -> float:
        return time.time() - self.first_seen

    def to_dict(self) -> dict:
        return {
            "id": self.object_id,
            "class": self.object_class.value,
            "confidence": round(self.confidence, 3),
            "position_geo": self.position_geo,
            "threat_level": self.threat_level.name,
            "is_military": self.is_military,
            "age_s": round(self.age_seconds(), 1),
            "notes": self.notes,
        }


@dataclass
class VideoFrame:
    frame_id: int = 0
    timestamp: float = field(default_factory=time.time)
    width: int = 1920
    height: int = 1080
    camera_position: tuple = (0.0, 0.0, 100.0)
    camera_heading: float = 0.0
    camera_fov_deg: float = 60.0
    pixel_data: Optional[np.ndarray] = None

    def pixel_to_geo(self, px: int, py: int) -> tuple:
        gsd_m = (self.camera_position[2] *
                 math.tan(math.radians(self.camera_fov_deg / 2)) * 2) / self.width
        dx_m = (px - self.width / 2) * gsd_m
        dy_m = (py - self.height / 2) * gsd_m
        deg_per_m = 1.0 / 111_000
        lat = self.camera_position[0] + dy_m * deg_per_m
        lon = self.camera_position[1] + dx_m * deg_per_m
        return (lat, lon, 0.0)


class ObjectDetector:
    """
    AI-powered object detector.
    In live mode: replace _simulate_detection with YOLOv8 or RT-DETR inference.
    """

    DETECTION_PROFILES = {
        "urban":    [ObjectClass.PERSON, ObjectClass.VEHICLE_LIGHT,
                     ObjectClass.VEHICLE_HEAVY, ObjectClass.STRUCTURE_CIVIL],
        "rural":    [ObjectClass.PERSON, ObjectClass.VEHICLE_LIGHT,
                     ObjectClass.VEHICLE_HEAVY],
        "military": [ObjectClass.VEHICLE_ARMOURED, ObjectClass.WEAPON_SYSTEM,
                     ObjectClass.STRUCTURE_MIL, ObjectClass.PERSON],
        "maritime": [ObjectClass.BOAT, ObjectClass.PERSON],
        "aerial":   [ObjectClass.AIRCRAFT],
    }

    def __init__(self, model_name: str = "upin-detect-v1",
                 confidence_threshold: float = 0.65):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self._detection_count = 0
        self._frame_count = 0
        self._environment = "urban"
        self._is_simulation = True

    def set_environment(self, env: str):
        if env in self.DETECTION_PROFILES:
            self._environment = env

    def detect(self, frame: VideoFrame) -> list:
        self._frame_count += 1
        if self._is_simulation:
            return self._simulate_detection(frame)
        raise NotImplementedError("Connect real model inference here")

    def _simulate_detection(self, frame: VideoFrame) -> list:
        detections = []
        profile = self.DETECTION_PROFILES.get(
            self._environment, self.DETECTION_PROFILES["urban"])

        n_detections = np.random.randint(0, 6)
        for _ in range(n_detections):
            obj_class = np.random.choice(profile)
            confidence = np.random.uniform(0.55, 0.98)
            if confidence < self.confidence_threshold:
                continue

            px = np.random.randint(0, frame.width)
            py = np.random.randint(0, frame.height)
            geo = frame.pixel_to_geo(px, py)
            w = np.random.randint(20, 150)
            h = np.random.randint(20, 150)

            obj = DetectedObject(
                object_class=obj_class,
                confidence=confidence,
                position_px=(px, py),
                position_geo=geo,
                bounding_box=(max(0, px - w//2), max(0, py - h//2), w, h),
                is_military=obj_class in [
                    ObjectClass.VEHICLE_ARMOURED,
                    ObjectClass.WEAPON_SYSTEM,
                    ObjectClass.STRUCTURE_MIL],
            )
            detections.append(obj)
            self._detection_count += 1
        return detections

    def get_stats(self) -> dict:
        return {
            "model": self.model_name,
            "frames_processed": self._frame_count,
            "total_detections": self._detection_count,
            "environment": self._environment,
            "confidence_threshold": self.confidence_threshold,
            "simulation_mode": self._is_simulation,
        }


class TargetClassifier:
    """
    Classifies detected objects as civilian or military.
    Outputs confidence score ONLY — never a verdict.
    Human operator makes all final decisions.
    """

    MILITARY_INDICATORS = {
        ObjectClass.VEHICLE_ARMOURED: 0.90,
        ObjectClass.WEAPON_SYSTEM:    0.95,
        ObjectClass.STRUCTURE_MIL:    0.80,
        ObjectClass.AIRCRAFT:         0.50,
        ObjectClass.BOAT:             0.30,
        ObjectClass.VEHICLE_HEAVY:    0.25,
        ObjectClass.VEHICLE_LIGHT:    0.10,
        ObjectClass.PERSON:           0.05,
        ObjectClass.STRUCTURE_CIVIL:  0.02,
        ObjectClass.UNKNOWN:          0.50,
    }

    def __init__(self):
        self._classification_count = 0

    def classify(self, obj: DetectedObject,
                 thermal_score: float = 0.0,
                 wifi_movement_detected: bool = False,
                 acoustic_score: float = 0.0) -> dict:
        self._classification_count += 1

        base_mil_score = self.MILITARY_INDICATORS.get(obj.object_class, 0.5)

        thermal_factor = thermal_score * 0.25
        wifi_factor = 0.15 if wifi_movement_detected else 0.0
        acoustic_factor = acoustic_score * 0.20

        combined = min(1.0, base_mil_score + thermal_factor +
                       wifi_factor + acoustic_factor)

        if combined >= 0.85:
            threat = ThreatLevel.CRITICAL
        elif combined >= 0.70:
            threat = ThreatLevel.HIGH
        elif combined >= 0.50:
            threat = ThreatLevel.MODERATE
        elif combined >= 0.30:
            threat = ThreatLevel.LOW
        else:
            threat = ThreatLevel.NONE

        return {
            "object_id": obj.object_id,
            "military_confidence": round(combined, 3),
            "civilian_confidence": round(1.0 - combined, 3),
            "threat_level": threat.name,
            "factors": {
                "visual_base": round(base_mil_score, 3),
                "thermal": round(thermal_factor, 3),
                "wifi_radar": round(wifi_factor, 3),
                "acoustic": round(acoustic_factor, 3),
            },
            "requires_human_authorisation": True,
            "classification_note": (
                "AI confidence score only. "
                "Human operator must authorise any action."
            ),
        }


class VisualTracker:
    """
    Tracks detected objects across video frames.
    Maintains history, velocity estimates, predicted positions.
    """

    def __init__(self, max_lost_frames: int = 30):
        self.max_lost_frames = max_lost_frames
        self._tracks: dict = {}
        self._next_track_id = 1

    def update(self, detections: list) -> list:
        current_time = time.time()
        matched_track_ids = set()

        for det in detections:
            best_track = self._find_best_match(det)
            if best_track:
                self._update_track(best_track, det, current_time)
                matched_track_ids.add(best_track)
            else:
                self._create_track(det, current_time)

        for tid in list(self._tracks.keys()):
            if tid not in matched_track_ids:
                self._tracks[tid]["lost_frames"] += 1
                if self._tracks[tid]["lost_frames"] > self.max_lost_frames:
                    del self._tracks[tid]

        return self.get_active_tracks()

    def predict_position(self, track_id: str,
                         seconds_ahead: float = 5.0) -> Optional[tuple]:
        track = self._tracks.get(track_id)
        if not track or len(track["history"]) < 2:
            return None
        vx = track.get("velocity_lat", 0.0)
        vy = track.get("velocity_lon", 0.0)
        last_pos = track["history"][-1]["position_geo"]
        return (last_pos[0] + vx * seconds_ahead,
                last_pos[1] + vy * seconds_ahead,
                last_pos[2])

    def get_active_tracks(self) -> list:
        return [
            {
                "track_id": tid,
                "object_class": t["object_class"].value,
                "last_position": t["history"][-1]["position_geo"]
                    if t["history"] else None,
                "velocity_mps": t.get("velocity_mps", 0.0),
                "lost_frames": t["lost_frames"],
                "age_s": time.time() - t["created_at"],
                "history_len": len(t["history"]),
                "predicted_5s": self.predict_position(tid, 5.0),
            }
            for tid, t in self._tracks.items()
            if t["lost_frames"] == 0
        ]

    def _find_best_match(self, det: DetectedObject) -> Optional[str]:
        best_id = None
        best_dist = 200.0
        for tid, track in self._tracks.items():
            if not track["history"]:
                continue
            last = track["history"][-1]
            dist = math.sqrt(
                (det.position_px[0] - last["position_px"][0]) ** 2 +
                (det.position_px[1] - last["position_px"][1]) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_id = tid
        return best_id

    def _create_track(self, det: DetectedObject, ts: float):
        tid = f"T{self._next_track_id:04d}"
        self._next_track_id += 1
        self._tracks[tid] = {
            "object_class": det.object_class,
            "created_at": ts,
            "lost_frames": 0,
            "history": [{"position_px": det.position_px,
                         "position_geo": det.position_geo,
                         "timestamp": ts}],
            "velocity_lat": 0.0,
            "velocity_lon": 0.0,
            "velocity_mps": 0.0,
        }

    def _update_track(self, track_id: str, det: DetectedObject, ts: float):
        track = self._tracks[track_id]
        track["lost_frames"] = 0
        history = track["history"]
        history.append({"position_px": det.position_px,
                        "position_geo": det.position_geo,
                        "timestamp": ts})
        if len(history) > 100:
            track["history"] = history[-50:]
        if len(history) >= 2:
            prev = history[-2]
            curr = history[-1]
            dt = curr["timestamp"] - prev["timestamp"]
            if dt > 0:
                dlat = curr["position_geo"][0] - prev["position_geo"][0]
                dlon = curr["position_geo"][1] - prev["position_geo"][1]
                track["velocity_lat"] = dlat / dt
                track["velocity_lon"] = dlon / dt
                track["velocity_mps"] = math.sqrt(
                    (dlat * 111_000) ** 2 + (dlon * 111_000) ** 2) / dt


class StructureAnalyser:
    """
    Classifies structures using WiFi radar, visual, thermal, acoustic, seismic.
    ALL outputs require human authorisation before any action.
    """

    def __init__(self):
        self._analysis_count = 0

    def analyse(self,
                visual_class: ObjectClass,
                wifi_movement_pattern: str = "none",
                thermal_signature: str = "none",
                acoustic_signature: str = "ambient",
                seismic_activity: float = 0.0) -> dict:
        self._analysis_count += 1

        scores = {}

        if visual_class == ObjectClass.STRUCTURE_MIL:
            scores["visual"] = 0.80
        elif visual_class == ObjectClass.STRUCTURE_CIVIL:
            scores["visual"] = 0.15
        else:
            scores["visual"] = 0.40

        scores["wifi_radar"] = {
            "none": 0.10, "civilian": 0.15, "organised": 0.55,
            "high_density": 0.70, "tactical": 0.85,
        }.get(wifi_movement_pattern, 0.30)

        scores["thermal"] = {
            "none": 0.10, "residential": 0.15, "vehicle_heat": 0.60,
            "equipment": 0.70, "generator": 0.75,
        }.get(thermal_signature, 0.20)

        scores["acoustic"] = {
            "ambient": 0.10, "civilian": 0.10, "machinery": 0.50,
            "military": 0.80, "weapons": 0.90,
        }.get(acoustic_signature, 0.20)

        scores["seismic"] = min(1.0, seismic_activity * 2.0)

        weights = {"visual": 0.30, "wifi_radar": 0.25,
                   "thermal": 0.20, "acoustic": 0.15, "seismic": 0.10}

        combined = sum(scores[k] * weights[k] for k in scores)

        if combined >= 0.75:
            classification = "MILITARY_HIGH_CONFIDENCE"
        elif combined >= 0.55:
            classification = "MILITARY_POSSIBLE"
        elif combined >= 0.35:
            classification = "AMBIGUOUS"
        else:
            classification = "CIVILIAN_LIKELY"

        return {
            "classification": classification,
            "military_confidence": round(combined, 3),
            "sensor_scores": {k: round(v, 3) for k, v in scores.items()},
            "requires_human_authorisation": True,
            "analysis_note": (
                "Multi-sensor structural analysis only. "
                "No action may be taken without explicit human authorisation."
            ),
            "analysis_count": self._analysis_count,
        }
