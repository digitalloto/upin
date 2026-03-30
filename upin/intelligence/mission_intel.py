"""
Mission Intelligence Manager — UPIN

Manages pre-mission intelligence inputs that improve positioning accuracy.
Operators can upload known threat zones, spoofing areas, satellite imagery
reference points, target locations, patrol routes, and special circumstances.

The fusion engine and Fish Schooling algorithm use this intel to:
- Pre-weight layers based on known threat environments
- Avoid known spoofing zones
- Calibrate against satellite reference imagery
- Optimise patrol routes around threat areas

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Any, Dict, List, Optional, Tuple


class IntelType(Enum):
    SPOOFING_ZONE = auto()       # Known GPS spoofing area
    JAMMING_ZONE = auto()        # Known RF jamming area
    THREAT_LOCATION = auto()     # Known hostile position
    SAFE_ROUTE = auto()          # Verified safe corridor
    DANGER_ROUTE = auto()        # Route with known threats
    REFERENCE_POINT = auto()     # Satellite-verified ground truth
    TARGET = auto()              # Mission target location
    PATROL_ROUTE = auto()        # Planned patrol waypoints
    NO_FLY_ZONE = auto()         # Restricted airspace
    OBSERVATION_POST = auto()    # Known enemy observation point
    SATELLITE_MAP = auto()       # Satellite imagery reference
    CUSTOM = auto()              # Operator-defined intel


@dataclass
class IntelEntry:
    """One piece of mission intelligence."""
    intel_id: str
    intel_type: IntelType
    name: str
    description: str
    latitude: float
    longitude: float
    radius_m: float              # Area of effect
    severity: float              # 0.0-1.0 how critical
    data: Dict[str, Any]         # Type-specific data
    timestamp: float
    source: str                  # Who provided this intel
    confidence: float            # 0.0-1.0 how reliable
    active: bool = True
    expires: Optional[float] = None  # When this intel expires


class MissionIntelManager:
    """
    Manages mission intelligence that feeds into UPIN's positioning.

    Operators upload intel before and during missions. The fusion engine
    and algorithms use this data to improve accuracy and avoid threats.
    """

    def __init__(self):
        self._intel: Dict[str, IntelEntry] = {}
        self._history: List[Dict] = []

    def add_intel(
        self,
        intel_type: str,
        name: str,
        latitude: float,
        longitude: float,
        radius_m: float = 500.0,
        severity: float = 0.5,
        description: str = "",
        source: str = "operator",
        confidence: float = 0.8,
        data: Optional[Dict] = None,
        expires_minutes: Optional[float] = None,
    ) -> str:
        """Add a piece of intelligence. Returns intel_id."""
        intel_id = str(uuid.uuid4())[:8]

        try:
            itype = IntelType[intel_type.upper()]
        except KeyError:
            itype = IntelType.CUSTOM

        entry = IntelEntry(
            intel_id=intel_id,
            intel_type=itype,
            name=name,
            description=description,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            severity=severity,
            data=data or {},
            timestamp=time.time(),
            source=source,
            confidence=confidence,
            active=True,
            expires=time.time() + expires_minutes * 60 if expires_minutes else None,
        )

        self._intel[intel_id] = entry
        self._history.append({
            "action": "ADD",
            "intel_id": intel_id,
            "type": itype.name,
            "name": name,
            "timestamp": time.time(),
        })
        return intel_id

    def remove_intel(self, intel_id: str) -> bool:
        if intel_id in self._intel:
            del self._intel[intel_id]
            self._history.append({"action": "REMOVE", "intel_id": intel_id, "timestamp": time.time()})
            return True
        return False

    def get_active_intel(self) -> List[Dict]:
        """Get all active (non-expired) intel entries."""
        now = time.time()
        result = []
        for entry in self._intel.values():
            if not entry.active:
                continue
            if entry.expires and now > entry.expires:
                entry.active = False
                continue
            result.append({
                "intel_id": entry.intel_id,
                "type": entry.intel_type.name,
                "name": entry.name,
                "description": entry.description,
                "lat": entry.latitude,
                "lon": entry.longitude,
                "radius_m": entry.radius_m,
                "severity": entry.severity,
                "confidence": entry.confidence,
                "source": entry.source,
                "age_minutes": (now - entry.timestamp) / 60,
                "data": entry.data,
            })
        return result

    def get_threats_near(self, lat: float, lon: float, radius_m: float = 5000) -> List[Dict]:
        """Get threat intel near a position."""
        import math
        threats = []
        for entry in self._intel.values():
            if not entry.active:
                continue
            if entry.intel_type not in (IntelType.SPOOFING_ZONE, IntelType.JAMMING_ZONE,
                                         IntelType.THREAT_LOCATION, IntelType.OBSERVATION_POST):
                continue
            dlat = (lat - entry.latitude) * 111320
            dlon = (lon - entry.longitude) * 111320 * math.cos(math.radians(lat))
            dist = math.sqrt(dlat**2 + dlon**2)
            if dist <= radius_m:
                threats.append({
                    "intel_id": entry.intel_id,
                    "type": entry.intel_type.name,
                    "name": entry.name,
                    "distance_m": round(dist),
                    "severity": entry.severity,
                })
        return threats

    def get_layer_adjustments(self, lat: float, lon: float) -> Dict[str, float]:
        """
        Get recommended layer weight adjustments based on nearby intel.

        Returns dict of layer_id -> weight_multiplier.
        Used by fusion engine to pre-adjust for known threats.
        """
        import math
        adjustments: Dict[str, float] = {}

        for entry in self._intel.values():
            if not entry.active:
                continue
            dlat = (lat - entry.latitude) * 111320
            dlon = (lon - entry.longitude) * 111320 * math.cos(math.radians(lat))
            dist = math.sqrt(dlat**2 + dlon**2)

            if dist > entry.radius_m:
                continue

            proximity = 1.0 - (dist / entry.radius_m)  # 1.0 at center, 0.0 at edge

            if entry.intel_type == IntelType.SPOOFING_ZONE:
                # Downweight GPS layers in known spoofing zones
                adjustments["gps_l1"] = min(adjustments.get("gps_l1", 1.0), 0.2 * (1 - proximity))
                adjustments["navic_l2"] = min(adjustments.get("navic_l2", 1.0), 0.3 * (1 - proximity))
                # Boost non-GPS layers
                adjustments["ins_l3"] = max(adjustments.get("ins_l3", 1.0), 1.0 + proximity * 0.5)
                adjustments["vslam_l31"] = max(adjustments.get("vslam_l31", 1.0), 1.0 + proximity * 0.5)

            elif entry.intel_type == IntelType.JAMMING_ZONE:
                # Downweight all RF layers
                for rf_layer in ["gps_l1", "navic_l2", "wifi_l8", "celltower_l9", "lora_d07"]:
                    adjustments[rf_layer] = min(adjustments.get(rf_layer, 1.0), 0.1)
                # Boost internal-only layers
                for internal in ["ins_l3", "magano_l6", "gravgrad_l28a", "muon_l40"]:
                    adjustments[internal] = max(adjustments.get(internal, 1.0), 1.5)

        return adjustments

    def get_summary(self) -> Dict:
        active = [e for e in self._intel.values() if e.active]
        type_counts: Dict[str, int] = {}
        for e in active:
            t = e.intel_type.name
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total_entries": len(self._intel),
            "active_entries": len(active),
            "type_counts": type_counts,
            "history_count": len(self._history),
        }
