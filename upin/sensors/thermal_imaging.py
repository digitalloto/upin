"""
UPIN Thermal Imaging Module.
FLIR-style thermal processing, heat signature detection,
thermal overlay with visual SLAM, threat classification.
Inspired by snake pit viper: 0.003 degree C discrimination.
"""
from __future__ import annotations
import time
import uuid
import math
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import numpy as np


class ThermalClass(Enum):
    BACKGROUND       = "background"
    HUMAN_BODY       = "human_body"
    ANIMAL           = "animal"
    VEHICLE_COLD     = "vehicle_cold"
    VEHICLE_WARM     = "vehicle_warm"
    VEHICLE_HOT      = "vehicle_hot"
    AIRCRAFT_EXHAUST = "aircraft_exhaust"
    FIRE             = "fire"
    EQUIPMENT        = "equipment"
    STRUCTURE_HEATED = "structure_heated"
    UNKNOWN_HOT      = "unknown_hot"


@dataclass
class ThermalSignature:
    signature_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    thermal_class: ThermalClass = ThermalClass.BACKGROUND
    peak_temp_c: float = 20.0
    mean_temp_c: float = 20.0
    area_px: int = 0
    position_px: tuple = (0, 0)
    position_geo: tuple = (0.0, 0.0, 0.0)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    is_threat: bool = False

    def temp_delta_c(self, ambient_c: float = 20.0) -> float:
        return self.peak_temp_c - ambient_c

    def to_dict(self) -> dict:
        return {
            "id": self.signature_id,
            "class": self.thermal_class.value,
            "peak_temp_c": round(self.peak_temp_c, 3),
            "mean_temp_c": round(self.mean_temp_c, 3),
            "temp_delta_c": round(self.temp_delta_c(), 3),
            "area_px": self.area_px,
            "position_geo": self.position_geo,
            "confidence": round(self.confidence, 3),
            "is_threat": self.is_threat,
        }


@dataclass
class ThermalFrame:
    frame_id: int = 0
    timestamp: float = field(default_factory=time.time)
    width: int = 640
    height: int = 512
    ambient_temp_c: float = 28.0
    min_temp_c: float = 20.0
    max_temp_c: float = 45.0
    sensitivity_c: float = 0.003
    camera_position: tuple = (0.0, 0.0, 100.0)
    pixel_temps: Optional[np.ndarray] = None

    def __post_init__(self):
        if self.pixel_temps is None:
            base = np.full((self.height, self.width),
                           self.ambient_temp_c, dtype=np.float32)
            noise = np.random.normal(0, 0.5,
                                     (self.height, self.width)).astype(np.float32)
            self.pixel_temps = base + noise

    def get_temp_at(self, px: int, py: int) -> float:
        if (0 <= py < self.height and 0 <= px < self.width
                and self.pixel_temps is not None):
            return float(self.pixel_temps[py, px])
        return self.ambient_temp_c

    def get_hotspots(self, threshold_delta_c: float = 3.0) -> list:
        if self.pixel_temps is None:
            return []
        threshold = self.ambient_temp_c + threshold_delta_c
        hot_y, hot_x = np.where(self.pixel_temps > threshold)
        return list(zip(hot_x.tolist(), hot_y.tolist()))


class ThermalCamera:
    """
    Simulated FLIR-class thermal camera.
    0.003 degree C discrimination inspired by snake pit viper.
    Spectral range: 7.5-13.5 micrometres LWIR.
    In live mode: replace with FLIR SDK or Seek Thermal API.
    """

    TEMP_PROFILES = {
        ThermalClass.HUMAN_BODY:       (36.5, 37.2),
        ThermalClass.ANIMAL:           (35.0, 40.0),
        ThermalClass.VEHICLE_COLD:     (20.0, 25.0),
        ThermalClass.VEHICLE_WARM:     (30.0, 50.0),
        ThermalClass.VEHICLE_HOT:      (60.0, 120.0),
        ThermalClass.AIRCRAFT_EXHAUST: (200.0, 600.0),
        ThermalClass.FIRE:             (300.0, 900.0),
        ThermalClass.EQUIPMENT:        (35.0, 65.0),
        ThermalClass.STRUCTURE_HEATED: (28.0, 40.0),
        ThermalClass.UNKNOWN_HOT:      (45.0, 80.0),
    }

    def __init__(self, sensitivity_c: float = 0.003,
                 fov_deg: float = 45.0):
        self.sensitivity_c = sensitivity_c
        self.fov_deg = fov_deg
        self._frame_count = 0
        self._is_simulation = True
        self._ambient_c = 28.0

    def set_ambient_temperature(self, temp_c: float):
        self._ambient_c = temp_c

    def capture_frame(self, camera_position: tuple = (0.0, 0.0, 100.0),
                      inject_targets: list = None) -> ThermalFrame:
        self._frame_count += 1
        frame = ThermalFrame(
            frame_id=self._frame_count,
            ambient_temp_c=self._ambient_c,
            sensitivity_c=self.sensitivity_c,
            camera_position=camera_position,
        )
        targets = inject_targets or self._generate_random_targets()
        for target in targets:
            self._inject_target(frame, target)
        return frame

    def _generate_random_targets(self) -> list:
        targets = []
        n = np.random.randint(0, 5)
        classes = [ThermalClass.HUMAN_BODY, ThermalClass.VEHICLE_WARM,
                   ThermalClass.VEHICLE_HOT, ThermalClass.EQUIPMENT]
        for _ in range(n):
            tc = np.random.choice(classes)
            t_range = self.TEMP_PROFILES[tc]
            targets.append({
                "class": tc,
                "temp_c": np.random.uniform(*t_range),
                "px": np.random.randint(50, 590),
                "py": np.random.randint(50, 462),
                "radius_px": np.random.randint(5, 30),
            })
        return targets

    def _inject_target(self, frame: ThermalFrame, target: dict):
        if frame.pixel_temps is None:
            return
        px, py = target["px"], target["py"]
        radius = target["radius_px"]
        temp = target["temp_c"]
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx*dx + dy*dy <= radius*radius:
                    y, x = py + dy, px + dx
                    if 0 <= y < frame.height and 0 <= x < frame.width:
                        dist = math.sqrt(dx*dx + dy*dy)
                        factor = math.exp(-0.5 * (dist / max(radius, 1))**2)
                        frame.pixel_temps[y, x] = (
                            frame.ambient_temp_c +
                            (temp - frame.ambient_temp_c) * factor)

    def get_stats(self) -> dict:
        return {
            "sensitivity_c": self.sensitivity_c,
            "fov_deg": self.fov_deg,
            "frames_captured": self._frame_count,
            "ambient_c": self._ambient_c,
            "simulation_mode": self._is_simulation,
            "spectral_range": "7.5-13.5 um LWIR",
        }


class HeatSignatureDetector:
    """
    Detects and classifies heat signatures from thermal frames.
    Distinguishes genuine threats from environmental noise.
    """

    HUMAN_TEMP_RANGE   = (35.5, 38.5)
    VEHICLE_WARM_RANGE = (28.0, 60.0)
    VEHICLE_HOT_RANGE  = (60.0, 150.0)
    FIRE_RANGE         = (200.0, 1000.0)

    def __init__(self, min_delta_c: float = 2.0):
        self.min_delta_c = min_delta_c
        self._detection_count = 0

    def detect(self, frame: ThermalFrame) -> list:
        if frame.pixel_temps is None:
            return []
        signatures = []
        hotspots = frame.get_hotspots(self.min_delta_c)
        clusters = self._cluster_hotspots(hotspots)
        for cluster in clusters:
            sig = self._classify_cluster(cluster, frame)
            if sig:
                signatures.append(sig)
                self._detection_count += 1
        return signatures

    def _cluster_hotspots(self, hotspots: list,
                           max_gap_px: int = 20) -> list:
        if not hotspots:
            return []
        clusters = []
        used = set()
        for i, pt in enumerate(hotspots):
            if i in used:
                continue
            cluster = [pt]
            used.add(i)
            for j, other in enumerate(hotspots):
                if j in used:
                    continue
                dist = math.sqrt((pt[0]-other[0])**2 + (pt[1]-other[1])**2)
                if dist <= max_gap_px:
                    cluster.append(other)
                    used.add(j)
            clusters.append(cluster)
        return clusters

    def _classify_cluster(self, cluster: list,
                           frame: ThermalFrame) -> Optional[ThermalSignature]:
        if not cluster or frame.pixel_temps is None:
            return None
        temps = [frame.get_temp_at(px, py) for px, py in cluster]
        if not temps:
            return None
        peak_temp = max(temps)
        mean_temp = sum(temps) / len(temps)
        cx = int(sum(p[0] for p in cluster) / len(cluster))
        cy = int(sum(p[1] for p in cluster) / len(cluster))

        if peak_temp >= self.FIRE_RANGE[0]:
            tc, confidence, is_threat = ThermalClass.FIRE, 0.95, True
        elif peak_temp >= self.VEHICLE_HOT_RANGE[0]:
            tc, confidence, is_threat = ThermalClass.VEHICLE_HOT, 0.88, True
        elif self.HUMAN_TEMP_RANGE[0] <= peak_temp <= self.HUMAN_TEMP_RANGE[1]:
            tc, confidence, is_threat = ThermalClass.HUMAN_BODY, 0.82, False
        elif peak_temp >= self.VEHICLE_WARM_RANGE[0]:
            tc, confidence, is_threat = ThermalClass.VEHICLE_WARM, 0.70, False
        else:
            tc, confidence, is_threat = ThermalClass.UNKNOWN_HOT, 0.50, False

        geo = (
            frame.camera_position[0] + (cy - frame.height/2) / 111_000,
            frame.camera_position[1] + (cx - frame.width/2) / 111_000,
            0.0,
        )

        return ThermalSignature(
            thermal_class=tc,
            peak_temp_c=peak_temp,
            mean_temp_c=mean_temp,
            area_px=len(cluster),
            position_px=(cx, cy),
            position_geo=geo,
            confidence=confidence,
            is_threat=is_threat,
        )

    def get_stats(self) -> dict:
        return {
            "total_detections": self._detection_count,
            "min_delta_c": self.min_delta_c,
        }


class ThermalOverlay:
    """
    Fuses thermal signatures onto the visual SLAM map.
    Enables operators to see thermal overlaid on the position map.
    """

    def __init__(self):
        self._overlay_map: dict = {}

    def register_signature(self, sig: ThermalSignature,
                            slam_confidence: float = 1.0):
        self._overlay_map[sig.signature_id] = {
            **sig.to_dict(),
            "slam_confidence": slam_confidence,
            "registered_at": time.time(),
        }

    def get_overlay_map(self) -> dict:
        return dict(self._overlay_map)

    def get_threats_on_map(self) -> list:
        return [v for v in self._overlay_map.values() if v.get("is_threat")]

    def clear_expired(self, max_age_s: float = 300.0):
        now = time.time()
        self._overlay_map = {
            k: v for k, v in self._overlay_map.items()
            if now - v.get("registered_at", now) < max_age_s
        }


class ThreatHeatClassifier:
    """
    Classifies heat signatures by threat level.
    Output is a confidence score only — human decides action.
    """

    def classify_threat(self, sig: ThermalSignature,
                         is_moving: bool = False,
                         group_size: int = 1) -> dict:
        if sig.thermal_class == ThermalClass.FIRE:
            base = 0.90
        elif sig.thermal_class == ThermalClass.AIRCRAFT_EXHAUST:
            base = 0.85
        elif sig.thermal_class == ThermalClass.VEHICLE_HOT:
            base = 0.75
        elif sig.thermal_class == ThermalClass.EQUIPMENT:
            base = 0.40
        elif sig.thermal_class == ThermalClass.VEHICLE_WARM:
            base = 0.45
        elif sig.thermal_class == ThermalClass.HUMAN_BODY:
            base = 0.30
        else:
            base = 0.20

        movement_bonus = 0.15 if is_moving else 0.0
        group_bonus = min(0.20, (group_size - 1) * 0.05)
        final_score = min(1.0, base + movement_bonus + group_bonus)

        if final_score >= 0.80:
            level = "CRITICAL"
        elif final_score >= 0.60:
            level = "HIGH"
        elif final_score >= 0.40:
            level = "MODERATE"
        elif final_score >= 0.20:
            level = "LOW"
        else:
            level = "NEGLIGIBLE"

        return {
            "signature_id": sig.signature_id,
            "threat_score": round(final_score, 3),
            "threat_level": level,
            "thermal_class": sig.thermal_class.value,
            "peak_temp_c": sig.peak_temp_c,
            "is_moving": is_moving,
            "group_size": group_size,
            "requires_human_authorisation": True,
            "assessment_note": (
                "Thermal threat assessment only. "
                "Human must authorise any response."
            ),
        }
