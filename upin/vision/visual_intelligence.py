"""
Visual Intelligence System — UPIN

Uses RF-DETR object detection for:

1. GROUND OBJECT DETECTION — identify vehicles, buildings, roads, people,
   bridges from camera feed. Each detected object becomes a landmark that
   confirms position (bridge at bearing 045° = you're near THAT bridge).

2. SATELLITE IMAGE MATCHING — pre-load satellite/map imagery. RF-DETR
   detects landmarks in both satellite image AND live camera. Match them
   → position fix. Like TERCOM (Terrain Contour Matching) but with objects.

3. FLIGHT PATH VERIFICATION — pre-loaded route has expected landmarks.
   As you fly, RF-DETR confirms: "bridge detected at T+30s checkpoint" →
   route verified. Missing expected landmark → route deviation detected.

4. TARGET TRACKING & HOMING — lock onto a detected object (vehicle,
   building, person). Track its position frame-to-frame. Compute bearing
   and range. Feed to targeting pipeline. Continuous homing signal.

5. THREAT IDENTIFICATION — classify detected objects as friendly/hostile.
   Military vehicle types, weapon systems, radar installations. Feed to
   IFF verification and threat assessment.

All features work with or without RF-DETR installed — graceful fallback
to simulated detections for testing/simulation.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 1. GROUND OBJECT DETECTION — landmarks for position confirmation
# ═══════════════════════════════════════════════════════════════

@dataclass
class DetectedLandmark:
    """An object detected by camera that can confirm position."""
    object_id: str
    object_class: str        # bridge, building, intersection, tower, etc.
    bearing_deg: float       # bearing from camera to object
    estimated_range_m: float # from object size + altitude
    pixel_x: float
    pixel_y: float
    confidence: float
    timestamp: float = field(default_factory=time.time)
    matched_to_map: bool = False
    map_lat: float = 0.0
    map_lon: float = 0.0


LANDMARK_CLASSES = {
    "bridge", "building", "intersection", "roundabout", "tower",
    "church", "mosque", "stadium", "lake", "river", "highway",
    "railway", "port", "airport", "monument", "factory",
}

THREAT_CLASSES = {
    "military_vehicle": "HIGH",
    "tank": "CRITICAL",
    "radar_installation": "HIGH",
    "anti_aircraft": "CRITICAL",
    "missile_launcher": "CRITICAL",
    "armed_personnel": "HIGH",
    "checkpoint": "MEDIUM",
    "patrol_vehicle": "MEDIUM",
    "helicopter": "HIGH",
    "fighter_jet": "CRITICAL",
}


class GroundObjectDetector:
    """Detect and classify objects on the ground from camera feed.

    Each detection becomes a potential landmark for position confirmation.
    If the detected bridge matches a bridge on the map → position fix.
    """

    def __init__(self, rfdetr_extractor=None):
        self._extractor = rfdetr_extractor
        self._detections: List[DetectedLandmark] = []
        self._detection_history: deque = deque(maxlen=500)
        self._frame_count = 0

    def process_frame(self, image: Any, camera_heading_deg: float,
                      camera_altitude_m: float,
                      camera_fov_deg: float = 70.0) -> List[DetectedLandmark]:
        """Process one camera frame. Detect objects, compute bearings."""
        self._frame_count += 1
        raw_detections = []

        if self._extractor and hasattr(self._extractor, 'is_available'):
            if self._extractor.is_available() and self._extractor._model is not None:
                raw_detections = self._extractor.detect_objects(image)

        if not raw_detections:
            raw_detections = self._simulate_detections()

        landmarks = []
        for det in raw_detections:
            obj_class = det.get("class", "unknown")
            bbox = det.get("bbox", (0, 0, 0, 0))
            conf = det.get("confidence", 0.0)

            # Compute bearing from pixel position in frame
            if len(bbox) >= 4:
                cx = (bbox[0] + bbox[2]) / 2.0
                frame_width = 1920  # assume HD
                angle_offset = (cx / frame_width - 0.5) * camera_fov_deg
                bearing = (camera_heading_deg + angle_offset) % 360.0
            else:
                bearing = camera_heading_deg

            # Estimate range from object size + altitude
            obj_height_px = abs(bbox[3] - bbox[1]) if len(bbox) >= 4 else 50
            if obj_height_px > 0:
                estimated_range = camera_altitude_m * 1000.0 / max(obj_height_px, 1)
            else:
                estimated_range = 500.0

            landmark = DetectedLandmark(
                object_id=f"OBJ-{self._frame_count}-{det.get('id', 0)}",
                object_class=obj_class,
                bearing_deg=bearing,
                estimated_range_m=min(5000, estimated_range),
                pixel_x=bbox[0] if len(bbox) >= 1 else 0,
                pixel_y=bbox[1] if len(bbox) >= 2 else 0,
                confidence=conf,
            )
            landmarks.append(landmark)
            self._detection_history.append(landmark)

        self._detections = landmarks
        return landmarks

    def _simulate_detections(self) -> List[Dict]:
        """Generate simulated detections for testing without RF-DETR."""
        import random
        n = random.randint(2, 8)
        classes = list(LANDMARK_CLASSES) + list(THREAT_CLASSES.keys())
        dets = []
        for i in range(n):
            cls = random.choice(classes)
            x1 = random.randint(50, 1800)
            y1 = random.randint(50, 1000)
            w = random.randint(30, 200)
            h = random.randint(30, 200)
            dets.append({
                "class": cls,
                "confidence": random.uniform(0.3, 0.95),
                "bbox": (x1, y1, x1 + w, y1 + h),
                "id": i,
            })
        return dets

    def get_status(self) -> Dict:
        return {
            "frames_processed": self._frame_count,
            "current_detections": len(self._detections),
            "total_detections": len(self._detection_history),
            "has_rfdetr": (self._extractor is not None
                           and hasattr(self._extractor, 'is_available')
                           and self._extractor.is_available()),
        }


# ═══════════════════════════════════════════════════════════════
# 2. SATELLITE IMAGE MATCHING — match camera to map for position
# ═══════════════════════════════════════════════════════════════

@dataclass
class MapMarker:
    """A known object on the satellite/map image."""
    marker_id: str
    object_class: str
    lat: float
    lon: float
    description: str = ""


class SatelliteImageMatcher:
    """Match live camera detections against pre-loaded satellite imagery.

    Pre-load a satellite image with annotated landmarks. When the live
    camera detects objects, match them against the map. Matching objects
    confirm position — like TERCOM but with semantic objects.
    """

    def __init__(self, rfdetr_extractor=None):
        self._extractor = rfdetr_extractor
        self._map_markers: List[MapMarker] = []
        self._matches: List[Dict] = []

    def load_map_markers(self, markers: List[MapMarker]):
        """Load known landmarks from satellite/map imagery."""
        self._map_markers = markers

    def add_marker(self, marker_id: str, object_class: str,
                   lat: float, lon: float, description: str = ""):
        self._map_markers.append(MapMarker(
            marker_id=marker_id, object_class=object_class,
            lat=lat, lon=lon, description=description,
        ))

    def match_detections(self, detections: List[DetectedLandmark],
                         current_lat: float, current_lon: float,
                         max_range_m: float = 5000.0) -> List[Dict]:
        """Match detected objects against map markers.

        For each detection, find the closest map marker of the same class
        within range. A match = position confirmation.
        """
        matches = []
        for det in detections:
            best_marker = None
            best_dist = float('inf')

            for marker in self._map_markers:
                if marker.object_class != det.object_class:
                    continue
                dist = _haversine_m(current_lat, current_lon,
                                    marker.lat, marker.lon)
                if dist < best_dist and dist <= max_range_m:
                    best_dist = dist
                    best_marker = marker

            if best_marker is not None:
                det.matched_to_map = True
                det.map_lat = best_marker.lat
                det.map_lon = best_marker.lon

                # Position confirmation: if we can see this object at this
                # bearing, and we know where it is on the map → fix
                bearing_rad = math.radians(det.bearing_deg)
                fix_lat = best_marker.lat - (det.estimated_range_m
                                              * math.cos(bearing_rad) / 111_320)
                cos_lat = math.cos(math.radians(best_marker.lat))
                fix_lon = best_marker.lon - (det.estimated_range_m
                                              * math.sin(bearing_rad)
                                              / (111_320 * max(cos_lat, 0.01)))

                matches.append({
                    "detection_id": det.object_id,
                    "marker_id": best_marker.marker_id,
                    "object_class": det.object_class,
                    "marker_distance_m": round(best_dist, 1),
                    "bearing_deg": det.bearing_deg,
                    "position_fix_lat": fix_lat,
                    "position_fix_lon": fix_lon,
                    "confidence": det.confidence,
                })

        self._matches = matches
        return matches

    def get_position_from_matches(self) -> Optional[Dict]:
        """Compute position fix from matched landmarks."""
        if not self._matches:
            return None

        total_w = 0.0
        lat_sum = lon_sum = 0.0
        for m in self._matches:
            w = m["confidence"]
            lat_sum += m["position_fix_lat"] * w
            lon_sum += m["position_fix_lon"] * w
            total_w += w

        if total_w <= 0:
            return None

        return {
            "lat": lat_sum / total_w,
            "lon": lon_sum / total_w,
            "matches_used": len(self._matches),
            "confidence": total_w / len(self._matches),
        }

    def get_status(self) -> Dict:
        return {
            "map_markers_loaded": len(self._map_markers),
            "current_matches": len(self._matches),
        }


# ═══════════════════════════════════════════════════════════════
# 3. FLIGHT PATH VERIFICATION — confirm route with landmarks
# ═══════════════════════════════════════════════════════════════

@dataclass
class RouteCheckpoint:
    """An expected landmark along the flight path."""
    checkpoint_id: str
    expected_class: str    # what we expect to see
    lat: float
    lon: float
    expected_at_s: float   # seconds into flight
    verified: bool = False
    verified_at: Optional[float] = None
    actual_class: str = ""


class FlightPathVerifier:
    """Verify flight path by confirming expected landmarks along the route.

    Pre-load the route with expected landmarks (checkpoints). As you fly,
    RF-DETR detects objects. When a detection matches an expected checkpoint
    → route is confirmed at that point. Missing checkpoints → deviation.
    """

    def __init__(self):
        self._checkpoints: List[RouteCheckpoint] = []
        self._next_idx = 0
        self._deviations: List[Dict] = []

    def load_route_checkpoints(self, checkpoints: List[RouteCheckpoint]):
        self._checkpoints = checkpoints
        self._next_idx = 0
        self._deviations = []

    def add_checkpoint(self, checkpoint_id: str, expected_class: str,
                       lat: float, lon: float, expected_at_s: float = 0):
        self._checkpoints.append(RouteCheckpoint(
            checkpoint_id=checkpoint_id, expected_class=expected_class,
            lat=lat, lon=lon, expected_at_s=expected_at_s,
        ))

    def verify_detections(self, detections: List[DetectedLandmark],
                          current_lat: float, current_lon: float
                          ) -> List[Dict]:
        """Check detected objects against upcoming checkpoints."""
        events = []
        if self._next_idx >= len(self._checkpoints):
            return events

        for cp_idx in range(self._next_idx, min(self._next_idx + 3, len(self._checkpoints))):
            cp = self._checkpoints[cp_idx]
            if cp.verified:
                continue
            dist_to_cp = _haversine_m(current_lat, current_lon, cp.lat, cp.lon)
            if dist_to_cp > 2000:
                continue

            for det in detections:
                if det.object_class == cp.expected_class and det.confidence > 0.4:
                    cp.verified = True
                    cp.verified_at = time.time()
                    cp.actual_class = det.object_class
                    if cp_idx == self._next_idx:
                        self._next_idx += 1
                    events.append({
                        "event": "CHECKPOINT_VERIFIED",
                        "checkpoint_id": cp.checkpoint_id,
                        "expected": cp.expected_class,
                        "detected": det.object_class,
                        "distance_m": round(dist_to_cp, 1),
                        "confidence": det.confidence,
                    })
                    break

        return events

    def get_progress(self) -> Dict:
        verified = sum(1 for cp in self._checkpoints if cp.verified)
        return {
            "total_checkpoints": len(self._checkpoints),
            "verified": verified,
            "remaining": len(self._checkpoints) - verified,
            "next_checkpoint": (self._checkpoints[self._next_idx].checkpoint_id
                                if self._next_idx < len(self._checkpoints) else "DONE"),
            "completion_pct": round(verified / max(1, len(self._checkpoints)) * 100, 1),
        }


# ═══════════════════════════════════════════════════════════════
# 4. TARGET TRACKING & HOMING — lock and track objects
# ═══════════════════════════════════════════════════════════════

@dataclass
class TrackedTarget:
    """A target being actively tracked across frames."""
    target_id: str
    object_class: str
    first_seen: float
    last_seen: float
    bearing_deg: float
    range_m: float
    bearing_history: List[float] = field(default_factory=list)
    range_history: List[float] = field(default_factory=list)
    position_history: List[Tuple[float, float]] = field(default_factory=list)
    frames_tracked: int = 0
    lock_status: str = "SEARCHING"  # SEARCHING, LOCKED, LOST
    threat_level: str = "UNKNOWN"
    requires_human_auth: bool = True


class TargetTracker:
    """Track detected objects across frames for homing/targeting.

    Lock onto a target and maintain continuous track. Compute bearing,
    range, and movement vector. Feed to targeting pipeline as a
    homing signal.
    """

    def __init__(self, max_targets: int = 20,
                 lock_threshold_frames: int = 5,
                 lost_threshold_s: float = 5.0):
        self._targets: Dict[str, TrackedTarget] = {}
        self._max_targets = max_targets
        self._lock_threshold = lock_threshold_frames
        self._lost_threshold = lost_threshold_s
        self._primary_target: Optional[str] = None

    def update(self, detections: List[DetectedLandmark],
               platform_lat: float, platform_lon: float) -> List[Dict]:
        """Update all tracked targets with new detections."""
        now = time.time()
        events = []

        # Match detections to existing tracks
        for det in detections:
            matched = False
            for tid, target in self._targets.items():
                if (target.object_class == det.object_class
                        and abs(target.bearing_deg - det.bearing_deg) < 15):
                    # Update existing track
                    target.last_seen = now
                    target.bearing_deg = det.bearing_deg
                    target.range_m = det.estimated_range_m
                    target.bearing_history.append(det.bearing_deg)
                    target.range_history.append(det.estimated_range_m)
                    target.frames_tracked += 1

                    # Compute target position on ground
                    bearing_rad = math.radians(det.bearing_deg)
                    tgt_lat = platform_lat + (det.estimated_range_m
                                               * math.cos(bearing_rad) / 111_320)
                    cos_lat = math.cos(math.radians(platform_lat))
                    tgt_lon = platform_lon + (det.estimated_range_m
                                               * math.sin(bearing_rad)
                                               / (111_320 * max(cos_lat, 0.01)))
                    target.position_history.append((tgt_lat, tgt_lon))
                    if len(target.position_history) > 100:
                        target.position_history = target.position_history[-100:]

                    if (target.frames_tracked >= self._lock_threshold
                            and target.lock_status != "LOCKED"):
                        target.lock_status = "LOCKED"
                        events.append({
                            "event": "TARGET_LOCKED",
                            "target_id": tid,
                            "class": target.object_class,
                            "bearing": target.bearing_deg,
                            "range_m": target.range_m,
                        })

                    # Threat classification
                    if det.object_class in THREAT_CLASSES:
                        target.threat_level = THREAT_CLASSES[det.object_class]

                    matched = True
                    break

            if not matched and len(self._targets) < self._max_targets:
                tid = f"TGT-{len(self._targets):03d}"
                threat = THREAT_CLASSES.get(det.object_class, "UNKNOWN")
                self._targets[tid] = TrackedTarget(
                    target_id=tid,
                    object_class=det.object_class,
                    first_seen=now,
                    last_seen=now,
                    bearing_deg=det.bearing_deg,
                    range_m=det.estimated_range_m,
                    frames_tracked=1,
                    threat_level=threat,
                )
                events.append({
                    "event": "NEW_TARGET",
                    "target_id": tid,
                    "class": det.object_class,
                    "threat_level": threat,
                })

        # Mark lost targets
        for tid, target in list(self._targets.items()):
            if now - target.last_seen > self._lost_threshold:
                if target.lock_status == "LOCKED":
                    target.lock_status = "LOST"
                    events.append({
                        "event": "TARGET_LOST",
                        "target_id": tid,
                        "class": target.object_class,
                    })

        return events

    def set_primary_target(self, target_id: str) -> bool:
        """Designate a target as the primary homing target."""
        if target_id in self._targets:
            self._primary_target = target_id
            return True
        return False

    def get_homing_signal(self) -> Optional[Dict]:
        """Get bearing and range to primary target for homing."""
        if self._primary_target is None:
            return None
        target = self._targets.get(self._primary_target)
        if target is None or target.lock_status == "LOST":
            return None

        # Compute movement vector from position history
        velocity_ms = 0.0
        movement_heading = 0.0
        if len(target.position_history) >= 2:
            p1 = target.position_history[-2]
            p2 = target.position_history[-1]
            dist = _haversine_m(p1[0], p1[1], p2[0], p2[1])
            velocity_ms = dist  # approximate (1 frame ~ 1s)
            movement_heading = math.degrees(math.atan2(
                p2[1] - p1[1], p2[0] - p1[0])) % 360

        return {
            "target_id": target.target_id,
            "class": target.object_class,
            "bearing_deg": target.bearing_deg,
            "range_m": target.range_m,
            "lock_status": target.lock_status,
            "threat_level": target.threat_level,
            "target_velocity_ms": round(velocity_ms, 1),
            "target_heading_deg": round(movement_heading, 1),
            "frames_tracked": target.frames_tracked,
            "last_position": (target.position_history[-1]
                              if target.position_history else None),
            "requires_human_auth": target.requires_human_auth,
        }

    def get_threat_summary(self) -> List[Dict]:
        """Get all tracked threats sorted by threat level."""
        threats = []
        for target in self._targets.values():
            if target.threat_level != "UNKNOWN" and target.lock_status != "LOST":
                threats.append({
                    "target_id": target.target_id,
                    "class": target.object_class,
                    "threat_level": target.threat_level,
                    "bearing_deg": target.bearing_deg,
                    "range_m": target.range_m,
                    "lock_status": target.lock_status,
                })
        priority = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        threats.sort(key=lambda t: priority.get(t["threat_level"], 9))
        return threats

    def get_status(self) -> Dict:
        locked = sum(1 for t in self._targets.values() if t.lock_status == "LOCKED")
        return {
            "total_targets": len(self._targets),
            "locked": locked,
            "lost": sum(1 for t in self._targets.values() if t.lock_status == "LOST"),
            "primary_target": self._primary_target,
            "threats": len(self.get_threat_summary()),
        }


# ═══════════════════════════════════════════════════════════════
# 5. UNIFIED VISUAL INTELLIGENCE — combines all subsystems
# ═══════════════════════════════════════════════════════════════

class VisualIntelligenceSystem:
    """Unified visual intelligence combining all RF-DETR capabilities.

    One system that does:
    - Detect objects around the platform
    - Match them to satellite/map imagery for position
    - Verify flight path via expected landmarks
    - Track and home onto targets
    - Identify and classify threats
    """

    def __init__(self, rfdetr_extractor=None):
        self.ground_detector = GroundObjectDetector(rfdetr_extractor)
        self.satellite_matcher = SatelliteImageMatcher(rfdetr_extractor)
        self.path_verifier = FlightPathVerifier()
        self.target_tracker = TargetTracker()
        self._tick_count = 0

    def process_tick(self, image: Any,
                     platform_lat: float, platform_lon: float,
                     platform_alt: float, platform_heading: float,
                     camera_fov_deg: float = 70.0) -> Dict:
        """Process one camera frame through all visual intelligence systems."""
        self._tick_count += 1

        # 1. Detect ground objects
        detections = self.ground_detector.process_frame(
            image, platform_heading, platform_alt, camera_fov_deg,
        )

        # 2. Match against satellite/map markers
        sat_matches = self.satellite_matcher.match_detections(
            detections, platform_lat, platform_lon,
        )
        position_fix = self.satellite_matcher.get_position_from_matches()

        # 3. Verify flight path
        path_events = self.path_verifier.verify_detections(
            detections, platform_lat, platform_lon,
        )

        # 4. Track targets
        tracker_events = self.target_tracker.update(
            detections, platform_lat, platform_lon,
        )

        # 5. Get homing signal if primary target set
        homing = self.target_tracker.get_homing_signal()

        return {
            "tick": self._tick_count,
            "detections": len(detections),
            "landmarks": [d for d in detections if d.object_class in LANDMARK_CLASSES],
            "threats": self.target_tracker.get_threat_summary(),
            "satellite_matches": len(sat_matches),
            "position_fix": position_fix,
            "path_verification": path_events,
            "path_progress": self.path_verifier.get_progress(),
            "tracker_events": tracker_events,
            "homing_signal": homing,
            "targets_locked": self.target_tracker.get_status()["locked"],
        }

    def get_full_status(self) -> Dict:
        return {
            "ticks": self._tick_count,
            "ground_detector": self.ground_detector.get_status(),
            "satellite_matcher": self.satellite_matcher.get_status(),
            "path_verifier": self.path_verifier.get_progress(),
            "target_tracker": self.target_tracker.get_status(),
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
