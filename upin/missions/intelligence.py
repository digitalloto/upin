"""
MC4 — Living Intelligence Ecosystem.

Five-level national intelligence network:
Level 1: Individual platform — processes locally with full autonomy
Level 2: Local mesh — adjacent platforms share intelligence
Level 3: Regional — local swarms share distilled summaries
Level 4: National Master Brain — synthesises from all platforms
Level 5: Historical Archive — permanent, inherited by new generations
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Any

import numpy as np

from upin.core.layer_base import MissionModule
from upin.core.position import NavigationOutput


class IntelligenceLevel(Enum):
    """Five levels of the intelligence ecosystem."""
    L1_PLATFORM = 1
    L2_LOCAL_MESH = 2
    L3_REGIONAL = 3
    L4_NATIONAL_MASTER = 4
    L5_HISTORICAL_ARCHIVE = 5


@dataclass
class IntelligenceReport:
    """A piece of intelligence at any level."""
    report_id: str
    level: IntelligenceLevel
    source_platform: str
    timestamp: float
    category: str  # navigation, threat, environmental, operational
    summary: str
    data: dict = field(default_factory=dict)
    confidence: float = 0.5
    classification: str = "RESTRICTED"


@dataclass
class PlatformExperience:
    """Operational experience from a single platform."""
    platform_id: str
    mission_type: str
    duration_s: float
    layers_used: list[str]
    threats_detected: int
    spoofing_events: int
    confidence_avg: float
    lessons: list[str] = field(default_factory=list)


class IntelligenceEcosystem(MissionModule):
    """MC4 — Living Intelligence Ecosystem.

    Five-level national intelligence network where each platform
    contributes to collective knowledge. New generations inherit
    accumulated wisdom of all previous generations.
    """

    def __init__(self):
        super().__init__(
            module_id="MC4",
            name="Living Intelligence Ecosystem",
            description="5-level national intelligence network",
        )
        # Level 1: Local platform intelligence
        self._local_reports: list[IntelligenceReport] = []
        # Level 2: Mesh intelligence from adjacent platforms
        self._mesh_reports: list[IntelligenceReport] = []
        # Level 3: Regional summaries
        self._regional_summaries: list[dict] = []
        # Level 4: National-level intelligence
        self._national_intelligence: list[dict] = []
        # Level 5: Historical archive
        self._historical_archive: list[PlatformExperience] = []

        self._platform_id = f"UPIN-{np.random.randint(1000, 9999)}"

    def initialize(self) -> bool:
        self.is_active = True
        return True

    # ── Level 1: Platform ─────────────────────────────────────────

    def process_local(self, nav_output: NavigationOutput) -> IntelligenceReport:
        """Level 1: Process local intelligence from navigation output."""
        report = IntelligenceReport(
            report_id=f"L1-{int(time.time())}",
            level=IntelligenceLevel.L1_PLATFORM,
            source_platform=self._platform_id,
            timestamp=time.time(),
            category="operational",
            summary=f"Position confidence {nav_output.confidence_score:.1f}%, "
                    f"{nav_output.num_agreeing_layers}/{nav_output.num_active_layers} layers",
            data={
                "position": (nav_output.position.latitude,
                             nav_output.position.longitude),
                "confidence": nav_output.confidence_score,
                "threats": len(nav_output.threat_alerts),
                "spoofing": nav_output.spoofing_detected,
            },
            confidence=nav_output.confidence_score / 100,
        )
        self._local_reports.append(report)
        if len(self._local_reports) > 1000:
            self._local_reports = self._local_reports[-500:]
        return report

    # ── Level 2: Local Mesh ───────────────────────────────────────

    def receive_mesh_intelligence(self, report: IntelligenceReport):
        """Level 2: Receive intelligence from adjacent platform."""
        report.level = IntelligenceLevel.L2_LOCAL_MESH
        self._mesh_reports.append(report)
        if len(self._mesh_reports) > 500:
            self._mesh_reports = self._mesh_reports[-250:]

    def share_to_mesh(self) -> list[IntelligenceReport]:
        """Level 2: Share recent intelligence to mesh."""
        recent = [r for r in self._local_reports
                  if time.time() - r.timestamp < 60]
        return recent

    # ── Level 3: Regional ─────────────────────────────────────────

    def generate_regional_summary(self) -> dict:
        """Level 3: Distil local + mesh into regional summary."""
        all_reports = self._local_reports + self._mesh_reports
        recent = [r for r in all_reports if time.time() - r.timestamp < 300]

        summary = {
            "level": 3,
            "timestamp": time.time(),
            "platform": self._platform_id,
            "reports_processed": len(recent),
            "avg_confidence": np.mean([r.confidence for r in recent]) if recent else 0,
            "threat_count": sum(
                r.data.get("threats", 0) for r in recent
            ),
            "spoofing_detected": any(
                r.data.get("spoofing", False) for r in recent
            ),
            "area_coverage_km2": len(recent) * 10,  # Rough estimate
        }
        self._regional_summaries.append(summary)
        return summary

    # ── Level 4: National Master Brain ────────────────────────────

    def upload_to_national(self) -> dict:
        """Level 4: Upload regional summary to National Master Brain."""
        if self._regional_summaries:
            latest = self._regional_summaries[-1]
            return {
                "source": self._platform_id,
                "regional_summary": latest,
                "experiences": len(self._historical_archive),
                "timestamp": time.time(),
            }
        return {}

    def receive_national_update(self, update: dict):
        """Level 4: Receive synthesised intelligence from Master Brain."""
        self._national_intelligence.append(update)

    # ── Level 5: Historical Archive ───────────────────────────────

    def archive_mission(self, mission_type: str, duration_s: float,
                        layers_used: list[str], threats: int,
                        spoofing_events: int, avg_confidence: float,
                        lessons: list[str] = None):
        """Level 5: Archive mission experience permanently.

        This archive is inherited by every new platform generation.
        """
        exp = PlatformExperience(
            platform_id=self._platform_id,
            mission_type=mission_type,
            duration_s=duration_s,
            layers_used=layers_used,
            threats_detected=threats,
            spoofing_events=spoofing_events,
            confidence_avg=avg_confidence,
            lessons=lessons or [],
        )
        self._historical_archive.append(exp)

    def inherit_archive(self, archive: list[PlatformExperience]):
        """Level 5: New platform inherits accumulated knowledge."""
        self._historical_archive.extend(archive)

    def get_archived_lessons(self, mission_type: str = None) -> list[str]:
        """Retrieve lessons from historical archive."""
        lessons = []
        for exp in self._historical_archive:
            if mission_type is None or exp.mission_type == mission_type:
                lessons.extend(exp.lessons)
        return lessons

    def execute(self, nav_output: NavigationOutput, mission_params: dict) -> dict:
        self.process_local(nav_output)
        return {
            "module": "MC4",
            "local_reports": len(self._local_reports),
            "mesh_reports": len(self._mesh_reports),
            "regional_summaries": len(self._regional_summaries),
            "national_updates": len(self._national_intelligence),
            "archived_missions": len(self._historical_archive),
            "intelligence_levels_active": 5,
        }
