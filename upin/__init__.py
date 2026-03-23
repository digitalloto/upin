"""
UPIN - Universal Positioning Intelligence Network

Multi-layer sensor fusion with real-time confidence scoring,
adaptive threat detection, autonomous flight path planning,
targeting intelligence, and casualty evacuation routing.

Patent Applications: IN202541120892 | IN202641025685 | IN202641029346
Inventor: Abheet Prem Manghnani
"""

__version__ = "0.1.0"
__author__ = "Abheet Prem Manghnani"

from upin.core.fusion_engine import FusionEngine
from upin.core.confidence import ConfidenceScorer
from upin.core.position import Position, NavigationOutput

__all__ = [
    "FusionEngine",
    "ConfidenceScorer",
    "Position",
    "NavigationOutput",
]
