"""
Signal Identifier — UPIN

Classifies unknown RF/acoustic/EM signals by analysing:
- Frequency (what band is it in?)
- Modulation pattern (AM, FM, PSK, chirp, pulse, CW?)
- Power level (how strong? → how close?)
- Timing pattern (continuous, pulsed, burst, coded?)
- Direction of arrival (where is it coming from?)

When an unknown signal is detected, the identifier classifies it as:
- FRIENDLY: known beacon, friendly comms, UPIN mesh signal
- NEUTRAL: FM broadcast, cell tower, commercial WiFi
- HOSTILE: jammer, spoofer, targeting radar, enemy comms
- OPPORTUNITY: unknown beacon that could be used for positioning

Hostile signals trigger anti-spoof/anti-jam responses.
Opportunity signals get fed to the universal beacon engine for
triangulation — free positioning from enemy transmitters!

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple


class SignalClassification(Enum):
    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"
    OPPORTUNITY = "opportunity"
    UNKNOWN = "unknown"


class ModulationType(Enum):
    CW = "cw"                # continuous wave (unmodulated carrier)
    AM = "am"                # amplitude modulation
    FM = "fm"                # frequency modulation
    PSK = "psk"              # phase shift keying (digital comms)
    FSK = "fsk"              # frequency shift keying (LoRa, etc.)
    CHIRP = "chirp"          # linear frequency sweep (radar)
    PULSE = "pulse"          # pulsed (radar)
    SPREAD = "spread"        # spread spectrum (CDMA, FHSS)
    NOISE = "noise"          # wideband noise (jammer)
    UNKNOWN = "unknown"


@dataclass
class SignalSignature:
    """Complete signature of a detected signal."""
    signal_id: str
    frequency_mhz: float
    bandwidth_mhz: float
    power_dbm: float
    modulation: ModulationType
    timing_pattern: str       # continuous, pulsed, burst, coded
    pulse_rate_hz: float      # 0 for continuous
    direction_deg: float      # bearing to source
    first_detected: float
    last_detected: float
    classification: SignalClassification = SignalClassification.UNKNOWN
    threat_level: str = "UNKNOWN"
    usable_for_positioning: bool = False
    estimated_source_range_m: float = 0.0
    notes: str = ""


# Known signal fingerprints for classification
KNOWN_SIGNATURES = [
    # Friendly
    {"freq_range": (860, 930), "mod": ModulationType.FSK,
     "class": SignalClassification.FRIENDLY, "name": "LoRa beacon",
     "positioning": True},
    {"freq_range": (2400, 2500), "mod": ModulationType.SPREAD,
     "class": SignalClassification.FRIENDLY, "name": "UPIN mesh WiFi",
     "positioning": True},
    {"freq_range": (3100, 10600), "mod": ModulationType.PULSE,
     "class": SignalClassification.FRIENDLY, "name": "UWB ranging",
     "positioning": True},

    # Neutral (existing infrastructure — usable for positioning)
    {"freq_range": (88, 108), "mod": ModulationType.FM,
     "class": SignalClassification.NEUTRAL, "name": "FM broadcast",
     "positioning": True},
    {"freq_range": (0.53, 1.7), "mod": ModulationType.AM,
     "class": SignalClassification.NEUTRAL, "name": "AM broadcast",
     "positioning": True},
    {"freq_range": (700, 900), "mod": ModulationType.PSK,
     "class": SignalClassification.NEUTRAL, "name": "LTE cell tower",
     "positioning": True},
    {"freq_range": (1800, 2100), "mod": ModulationType.PSK,
     "class": SignalClassification.NEUTRAL, "name": "Cell tower 3G/4G",
     "positioning": True},
    {"freq_range": (2400, 2500), "mod": ModulationType.PSK,
     "class": SignalClassification.NEUTRAL, "name": "WiFi AP",
     "positioning": True},

    # Hostile
    {"freq_range": (1560, 1590), "mod": ModulationType.SPREAD,
     "class": SignalClassification.HOSTILE, "name": "GPS spoofer",
     "positioning": False, "threat": "CRITICAL"},
    {"freq_range": (1560, 1590), "mod": ModulationType.NOISE,
     "class": SignalClassification.HOSTILE, "name": "GPS jammer",
     "positioning": False, "threat": "CRITICAL"},
    {"freq_range": (2000, 4000), "mod": ModulationType.CHIRP,
     "class": SignalClassification.HOSTILE, "name": "S-band search radar",
     "positioning": True, "threat": "HIGH"},
    {"freq_range": (8000, 12000), "mod": ModulationType.PULSE,
     "class": SignalClassification.HOSTILE, "name": "X-band fire control radar",
     "positioning": True, "threat": "CRITICAL"},
    {"freq_range": (0, 6000), "mod": ModulationType.NOISE,
     "class": SignalClassification.HOSTILE, "name": "Wideband jammer",
     "positioning": False, "threat": "HIGH"},
]


class SignalIdentifier:
    """Classify unknown signals by frequency, modulation, power, timing.

    Maintains a database of detected signals. Classifies each as
    friendly/neutral/hostile/opportunity. Hostile triggers defense.
    Opportunity feeds to beacon engine for free positioning.
    """

    def __init__(self):
        self._detected: Dict[str, SignalSignature] = {}
        self._history: deque = deque(maxlen=500)
        self._signal_counter = 0

    def identify(self, frequency_mhz: float, bandwidth_mhz: float,
                 power_dbm: float, modulation: ModulationType,
                 timing_pattern: str = "continuous",
                 pulse_rate_hz: float = 0.0,
                 direction_deg: float = 0.0) -> SignalSignature:
        """Identify and classify an unknown signal."""
        self._signal_counter += 1
        sig_id = f"SIG-{self._signal_counter:04d}"
        now = time.time()

        # Classify against known signatures
        classification = SignalClassification.UNKNOWN
        threat_level = "UNKNOWN"
        usable = False
        name = "unidentified"

        for known in KNOWN_SIGNATURES:
            freq_lo, freq_hi = known["freq_range"]
            if freq_lo <= frequency_mhz <= freq_hi:
                if known["mod"] == modulation or modulation == ModulationType.UNKNOWN:
                    classification = known["class"]
                    name = known["name"]
                    usable = known.get("positioning", False)
                    threat_level = known.get("threat", "NONE")
                    break

        # Wideband noise at high power = jammer
        if (modulation == ModulationType.NOISE
                and bandwidth_mhz > 10
                and power_dbm > -50):
            classification = SignalClassification.HOSTILE
            threat_level = "HIGH"
            name = "broadband jammer"
            usable = False

        # Unknown signal at usable frequency = opportunity
        if classification == SignalClassification.UNKNOWN and power_dbm > -100:
            classification = SignalClassification.OPPORTUNITY
            usable = True
            name = "unknown beacon (opportunity)"

        # Hostile radar/comms can still be used for positioning!
        # We know WHERE the signal comes from → free position fix
        if (classification == SignalClassification.HOSTILE
                and modulation in (ModulationType.CHIRP, ModulationType.PULSE)):
            usable = True  # enemy radar = free position source

        # Estimate source range from power
        estimated_range = 0.0
        if power_dbm < 0:
            estimated_range = 10.0 ** ((-30 - power_dbm) / (10 * 2.5))
            estimated_range = min(100_000, estimated_range)

        sig = SignalSignature(
            signal_id=sig_id,
            frequency_mhz=frequency_mhz,
            bandwidth_mhz=bandwidth_mhz,
            power_dbm=power_dbm,
            modulation=modulation,
            timing_pattern=timing_pattern,
            pulse_rate_hz=pulse_rate_hz,
            direction_deg=direction_deg,
            first_detected=now,
            last_detected=now,
            classification=classification,
            threat_level=threat_level,
            usable_for_positioning=usable,
            estimated_source_range_m=estimated_range,
            notes=name,
        )
        self._detected[sig_id] = sig
        self._history.append(sig)
        return sig

    def get_positioning_signals(self) -> List[SignalSignature]:
        """Get all signals usable for triangulation (friendly + neutral + opportunity + hostile radar)."""
        return [s for s in self._detected.values() if s.usable_for_positioning]

    def get_threats(self) -> List[SignalSignature]:
        """Get all hostile signals sorted by threat level."""
        threats = [s for s in self._detected.values()
                   if s.classification == SignalClassification.HOSTILE]
        priority = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        threats.sort(key=lambda s: priority.get(s.threat_level, 9))
        return threats

    def get_environment_summary(self) -> Dict:
        """Summarise the current RF/signal environment."""
        by_class = {}
        for s in self._detected.values():
            cls = s.classification.value
            by_class[cls] = by_class.get(cls, 0) + 1
        return {
            "total_signals": len(self._detected),
            "by_classification": by_class,
            "usable_for_positioning": len(self.get_positioning_signals()),
            "threats": len(self.get_threats()),
            "frequency_range_mhz": (
                min((s.frequency_mhz for s in self._detected.values()), default=0),
                max((s.frequency_mhz for s in self._detected.values()), default=0),
            ),
        }

    def get_status(self) -> Dict:
        return {
            "signals_detected": len(self._detected),
            "total_classified": self._signal_counter,
            "environment": self.get_environment_summary(),
        }
