"""
Base Agent — UPIN Agent Architecture

Abstract base class for all UPIN positioning agents.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

from upin.core.position import Position


class BaseAgent(ABC):
    """Abstract base class for all UPIN agents."""

    def __init__(self, agent_id: str, agent_type: str):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.status = "INITIALIZING"
        self.last_reading_time = 0.0

    @abstractmethod
    def get_reading(self) -> Dict:
        """Get a reading from this agent."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if agent is available."""
        ...

    @abstractmethod
    def calibrate(self) -> bool:
        """Calibrate the agent."""
        ...

    def get_status_report(self) -> Dict:
        """Get agent status."""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "status": self.status,
            "last_reading_time": self.last_reading_time,
        }
