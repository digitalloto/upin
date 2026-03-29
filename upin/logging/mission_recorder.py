"""
Mission Data Recorder — UPIN AI Learning Pipeline

Records every sensor reading, fusion decision, threat detection, and
human authorization with millisecond precision. This data trains the
AI to get smarter and provides complete audit trails for legal and
military accountability.

Like an aircraft black box, but for positioning intelligence.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import auto, Enum
from typing import Any, Dict, List, Optional

import numpy as np


class EventType(Enum):
    SENSOR_READING = auto()
    FUSION_DECISION = auto()
    THREAT_DETECTED = auto()
    HUMAN_AUTH = auto()
    MODE_CHANGE = auto()
    CALIBRATION = auto()
    JAMMER_TRIANGULATED = auto()
    IFF_CHECK = auto()
    FALSE_POSITION = auto()
    SYSTEM_ERROR = auto()


class Severity(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    CRITICAL = auto()
    ALERT = auto()


@dataclass
class MissionEvent:
    """One recorded event in the mission timeline."""
    event_id: str
    timestamp: float          # microsecond precision
    event_type: EventType
    severity: Severity
    description: str
    data: Dict[str, Any]      # event-specific data
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    confidence: Optional[float] = None
    human_involved: bool = False
    classified_level: int = 0  # 0=unclass, 1=restricted, 2=confidential, 3=secret

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d["event_type"] = self.event_type.name
        d["severity"] = self.severity.name
        return d


@dataclass
class PerformanceMetric:
    """Performance measurement over time."""
    metric_name: str
    timestamp: float
    value: float
    unit: str
    context: Dict[str, Any] = field(default_factory=dict)


class MissionRecorder:
    """
    Records all mission events with microsecond precision.

    Captures:
    - Every sensor reading and fusion decision
    - All threat detections and responses
    - Human authorizations and mode changes
    - Performance metrics and errors
    - Complete timeline for AI training
    """

    def __init__(self, mission_id: str, device_id: str):
        self.mission_id = mission_id
        self.device_id = device_id
        self.start_time = time.time()

        self._events: List[MissionEvent] = []
        self._performance_metrics: List[PerformanceMetric] = []
        self._recording_enabled = True
        self._max_events_in_memory = 10000
        self._classification_level = 0

    def record_sensor_reading(
        self,
        sensor_name: str,
        reading: float,
        confidence: float,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """Record a sensor reading."""
        return self._record_event(
            event_type=EventType.SENSOR_READING,
            severity=Severity.DEBUG,
            description=f"Sensor {sensor_name} reading",
            data={
                "sensor_name": sensor_name,
                "reading": reading,
                "metadata": metadata or {}
            },
            location_lat=lat,
            location_lon=lon,
            confidence=confidence
        )

    def record_fusion_decision(
        self,
        input_layers: List[str],
        output_position: Dict[str, float],
        confidence: float,
        reasoning: str,
        lat: float,
        lon: float
    ) -> str:
        """Record a fusion engine decision."""
        return self._record_event(
            event_type=EventType.FUSION_DECISION,
            severity=Severity.INFO,
            description="Fusion engine position calculation",
            data={
                "input_layers": input_layers,
                "output_position": output_position,
                "reasoning": reasoning,
                "layer_count": len(input_layers)
            },
            location_lat=lat,
            location_lon=lon,
            confidence=confidence
        )

    def record_threat_detection(
        self,
        threat_type: str,
        threat_level: str,
        source_sensor: str,
        details: Dict[str, Any],
        lat: Optional[float] = None,
        lon: Optional[float] = None
    ) -> str:
        """Record a threat detection event."""
        return self._record_event(
            event_type=EventType.THREAT_DETECTED,
            severity=Severity.WARNING if threat_level == "LOW" else Severity.CRITICAL,
            description=f"{threat_type} threat detected by {source_sensor}",
            data={
                "threat_type": threat_type,
                "threat_level": threat_level,
                "source_sensor": source_sensor,
                "details": details
            },
            location_lat=lat,
            location_lon=lon,
            classified_level=2  # Confidential
        )

    def record_human_authorization(
        self,
        action: str,
        authorized: bool,
        authorized_by: str,
        reason: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None
    ) -> str:
        """Record a human authorization decision."""
        return self._record_event(
            event_type=EventType.HUMAN_AUTH,
            severity=Severity.ALERT,
            description=f"Human {'authorized' if authorized else 'denied'}: {action}",
            data={
                "action": action,
                "authorized": authorized,
                "authorized_by": authorized_by,
                "reason": reason
            },
            location_lat=lat,
            location_lon=lon,
            human_involved=True,
            classified_level=2  # Confidential
        )

    def record_jammer_triangulation(
        self,
        jammer_lat: float,
        jammer_lon: float,
        confidence: float,
        sensor_count: int,
        jammer_type: str
    ) -> str:
        """Record successful jammer triangulation."""
        return self._record_event(
            event_type=EventType.JAMMER_TRIANGULATED,
            severity=Severity.CRITICAL,
            description=f"Jammer triangulated: {jammer_type}",
            data={
                "jammer_lat": jammer_lat,
                "jammer_lon": jammer_lon,
                "jammer_type": jammer_type,
                "sensor_count": sensor_count,
                "triangulation_method": "TDOA"
            },
            confidence=confidence,
            classified_level=3  # Secret
        )

    def record_iff_verification(
        self,
        target_id: str,
        verdict: str,
        factors_passed: int,
        total_factors: int,
        confidence: float
    ) -> str:
        """Record IFF verification result."""
        return self._record_event(
            event_type=EventType.IFF_CHECK,
            severity=Severity.INFO,
            description=f"IFF check: {target_id} = {verdict}",
            data={
                "target_id": target_id,
                "verdict": verdict,
                "factors_passed": factors_passed,
                "total_factors": total_factors
            },
            confidence=confidence,
            classified_level=2  # Confidential
        )

    def record_performance_metric(
        self,
        metric_name: str,
        value: float,
        unit: str,
        context: Optional[Dict] = None
    ) -> None:
        """Record a performance measurement."""
        metric = PerformanceMetric(
            metric_name=metric_name,
            timestamp=time.time(),
            value=value,
            unit=unit,
            context=context or {}
        )
        self._performance_metrics.append(metric)

    def record_mode_change(
        self,
        from_mode: str,
        to_mode: str,
        authorized_by: str,
        reason: str
    ) -> str:
        """Record mission mode change."""
        return self._record_event(
            event_type=EventType.MODE_CHANGE,
            severity=Severity.INFO,
            description=f"Mode change: {from_mode} → {to_mode}",
            data={
                "from_mode": from_mode,
                "to_mode": to_mode,
                "authorized_by": authorized_by,
                "reason": reason
            },
            human_involved=True,
            classified_level=1  # Restricted
        )

    def _record_event(
        self,
        event_type: EventType,
        severity: Severity,
        description: str,
        data: Dict[str, Any],
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        confidence: Optional[float] = None,
        human_involved: bool = False,
        classified_level: int = 0
    ) -> str:
        """Internal method to record any event."""
        if not self._recording_enabled:
            return ""

        event_id = str(uuid.uuid4())[:8]  # Short unique ID

        event = MissionEvent(
            event_id=event_id,
            timestamp=time.time(),
            event_type=event_type,
            severity=severity,
            description=description,
            data=data,
            location_lat=location_lat,
            location_lon=location_lon,
            confidence=confidence,
            human_involved=human_involved,
            classified_level=max(classified_level, self._classification_level)
        )

        self._events.append(event)

        # Memory management
        if len(self._events) > self._max_events_in_memory:
            self._events = self._events[-self._max_events_in_memory:]

        return event_id

    def get_mission_timeline(self, since_timestamp: Optional[float] = None) -> List[MissionEvent]:
        """Get chronological mission timeline."""
        if since_timestamp is None:
            return list(self._events)

        return [e for e in self._events if e.timestamp >= since_timestamp]

    def get_events_by_type(self, event_type: EventType) -> List[MissionEvent]:
        """Get all events of a specific type."""
        return [e for e in self._events if e.event_type == event_type]

    def get_human_decisions(self) -> List[MissionEvent]:
        """Get all events involving human decisions."""
        return [e for e in self._events if e.human_involved]

    def get_mission_summary(self) -> Dict[str, Any]:
        """Generate mission summary statistics."""
        duration = time.time() - self.start_time

        event_counts = {}
        for event_type in EventType:
            event_counts[event_type.name] = len([e for e in self._events if e.event_type == event_type])

        severity_counts = {}
        for severity in Severity:
            severity_counts[severity.name] = len([e for e in self._events if e.severity == severity])

        human_decisions = len(self.get_human_decisions())

        # Performance metrics summary
        recent_metrics = [m for m in self._performance_metrics if (time.time() - m.timestamp) < 3600]

        return {
            "mission_id": self.mission_id,
            "device_id": self.device_id,
            "duration_minutes": duration / 60.0,
            "total_events": len(self._events),
            "events_by_type": event_counts,
            "events_by_severity": severity_counts,
            "human_decisions": human_decisions,
            "classification_level": self._classification_level,
            "recent_metrics_1h": len(recent_metrics),
            "recording_enabled": self._recording_enabled
        }

    def export_for_ai_training(self, classification_filter: int = 1) -> Dict[str, Any]:
        """Export data suitable for AI training (filtered by classification)."""

        # Filter events by classification level
        training_events = [
            e.to_dict() for e in self._events
            if e.classified_level <= classification_filter
        ]

        # Remove sensitive fields
        for event in training_events:
            if 'authorized_by' in event.get('data', {}):
                event['data']['authorized_by'] = '[REDACTED]'
            if event.get('classified_level', 0) > 0:
                event['location_lat'] = None
                event['location_lon'] = None

        return {
            "mission_metadata": {
                "mission_id": f"[TRAINING-{self.mission_id[:8]}]",
                "duration_minutes": (time.time() - self.start_time) / 60.0,
                "device_type": "training_data",
                "classification_level": classification_filter
            },
            "events": training_events,
            "performance_metrics": [asdict(m) for m in self._performance_metrics]
        }

    def enable_recording(self, enabled: bool) -> None:
        """Enable or disable event recording."""
        self._recording_enabled = enabled

    def set_classification_level(self, level: int) -> None:
        """Set minimum classification level for all new events."""
        self._classification_level = max(0, min(3, level))
