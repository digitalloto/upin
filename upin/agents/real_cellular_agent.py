"""
Real Cellular Positioning Agent — UPIN

Uses cell tower information and OpenCellID API to determine position
from surrounding cellular towers (2G/3G/4G/5G).

OpenCellID is the world's largest open database of cell tower locations.
Free API key available at opencellid.org.

On platforms without cell modem access, falls back to simulated data.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from upin.agents.base_agent import BaseAgent


@dataclass
class CellTower:
    """One detected cell tower."""
    mcc: int            # Mobile Country Code (e.g. 404 = India)
    mnc: int            # Mobile Network Code (e.g. 45 = Airtel)
    lac: int            # Location Area Code
    cid: int            # Cell ID
    signal_dbm: int     # Signal strength in dBm
    radio: str = "LTE"  # GSM, UMTS, LTE, NR (5G)
    psc: int = 0        # Primary Scrambling Code (UMTS) / PCI (LTE)
    arfcn: int = 0      # Absolute Radio Frequency Channel Number


@dataclass
class CellPosition:
    """Position result from cell tower positioning."""
    latitude: float
    longitude: float
    accuracy_m: float
    source: str         # "opencellid" | "mls" | "simulated"
    towers_used: int
    primary_radio: str
    timestamp: float


class RealCellularPositioningAgent(BaseAgent):
    """
    Real cellular positioning using tower scan + OpenCellID / MLS APIs.

    Workflow:
      1. Read cell tower info from the device modem (platform-specific)
      2. Query OpenCellID or Mozilla Location Service for tower positions
      3. Triangulate position from multiple towers
      4. Fall back to single-tower position or simulation

    Supports: Linux (mmcli / AT commands), Android (termux-telephony-cellinfo).
    """

    OPENCELLID_URL = "https://opencellid.org/cell/get"
    MLS_URL = "https://location.services.mozilla.com/v1/geolocate?key=test"

    def __init__(self, agent_id: str = "cellular_real",
                 opencellid_key: Optional[str] = None):
        super().__init__(agent_id, "CELLULAR_REAL")
        self.status = "ACTIVE"
        self._api_key = opencellid_key or os.environ.get("OPENCELLID_KEY", "")
        self._last_scan: List[CellTower] = []
        self._last_position: Optional[CellPosition] = None
        self._cache_ttl_s = 15.0
        self._scan_count = 0
        self._api_call_count = 0
        self._platform = sys.platform

        # Known tower location cache (avoids repeat API calls)
        self._tower_cache: Dict[str, Tuple[float, float, float]] = {}  # key -> (lat,lon,range_m)

    # ── BaseAgent interface ────────────────────────────────────────

    def get_reading(self) -> Dict:
        pos = self.get_position()
        if pos:
            # Cellular is less accurate than WiFi — cap confidence
            raw_conf = max(0.1, min(0.85, 1.0 - pos.accuracy_m / 500.0))
            return {
                "agent_id": self.agent_id,
                "agent_type": self.agent_type,
                "lat": pos.latitude,
                "lon": pos.longitude,
                "accuracy_m": pos.accuracy_m,
                "confidence": raw_conf,
                "source": pos.source,
                "towers": pos.towers_used,
                "radio": pos.primary_radio,
                "timestamp": pos.timestamp,
                "status": "ACTIVE",
            }
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "status": "NO_POSITION",
            "timestamp": time.time(),
        }

    def is_available(self) -> bool:
        return True

    def calibrate(self) -> bool:
        self._last_position = None
        self._last_scan = []
        return True

    # ── Public API ─────────────────────────────────────────────────

    def get_position(self) -> Optional[CellPosition]:
        """Get position from cellular towers. Uses cache if fresh."""
        if (self._last_position and
                time.time() - self._last_position.timestamp < self._cache_ttl_s):
            return self._last_position

        towers = self.scan_cell_towers()
        if not towers:
            towers = self._simulate_towers()

        self._last_scan = towers
        if not towers:
            return None

        # Try MLS first (accepts cell towers directly)
        position = self._query_mls(towers)

        # Try OpenCellID per-tower if MLS failed and we have a key
        if not position and self._api_key:
            position = self._query_opencellid(towers)

        # Try triangulation from cached tower positions
        if not position:
            position = self._triangulate_from_cache(towers)

        # Fallback to simulation
        if not position:
            position = self._simulate_position(towers)

        self._last_position = position
        return position

    def scan_cell_towers(self) -> List[CellTower]:
        """Scan cell towers using platform-specific tools."""
        self._scan_count += 1

        if self._platform.startswith("linux"):
            towers = self._scan_linux_mmcli()
            if not towers:
                towers = self._scan_linux_termux()
            return towers
        return []

    # ── Platform-specific scanners ─────────────────────────────────

    def _scan_linux_mmcli(self) -> List[CellTower]:
        """Scan using ModemManager (mmcli) on Linux."""
        towers = []
        try:
            # List modems
            result = subprocess.run(
                ["mmcli", "-L"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []

            # Get first modem path
            for line in result.stdout.strip().split("\n"):
                if "/Modem/" in line:
                    modem_path = line.split()[0]
                    break
            else:
                return []

            # Get signal and location info
            result = subprocess.run(
                ["mmcli", "-m", modem_path, "--output-json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                modem = data.get("modem", {})

                # Extract 3GPP info
                threegpp = modem.get("3gpp", {})
                operator_code = threegpp.get("operator-code", "")
                if len(operator_code) >= 5:
                    mcc = int(operator_code[:3])
                    mnc = int(operator_code[3:])
                else:
                    mcc, mnc = 0, 0

                # Try to get cell info from signal quality
                signal = modem.get("generic", {}).get("signal-quality", {})
                signal_pct = int(signal.get("value", 50))
                signal_dbm = int(signal_pct * -0.7 - 30)

                if mcc > 0:
                    towers.append(CellTower(
                        mcc=mcc, mnc=mnc, lac=0, cid=0,
                        signal_dbm=signal_dbm, radio="LTE",
                    ))

        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError,
                ValueError, KeyError):
            pass

        return towers

    def _scan_linux_termux(self) -> List[CellTower]:
        """Scan using Termux API on Android."""
        towers = []
        try:
            result = subprocess.run(
                ["termux-telephony-cellinfo"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                cells = json.loads(result.stdout)
                for cell in cells:
                    ctype = cell.get("type", "").upper()
                    radio = "LTE" if "LTE" in ctype else "UMTS" if "WCDMA" in ctype else "GSM"

                    mcc = cell.get("mcc", 0)
                    mnc = cell.get("mnc", 0)
                    lac = cell.get("lac", cell.get("tac", 0))
                    cid = cell.get("cid", cell.get("ci", 0))
                    sig = cell.get("signal_strength", cell.get("rsrp", -85))

                    if mcc > 0 and cid > 0:
                        towers.append(CellTower(
                            mcc=mcc, mnc=mnc, lac=lac, cid=cid,
                            signal_dbm=sig, radio=radio,
                        ))
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

        return towers

    # ── API Queries ────────────────────────────────────────────────

    def _query_mls(self, towers: List[CellTower]) -> Optional[CellPosition]:
        """Query Mozilla Location Service with cell tower data."""
        if not towers:
            return None

        self._api_call_count += 1

        cell_towers = []
        for t in towers[:10]:
            entry: Dict = {
                "radioType": t.radio.lower(),
                "mobileCountryCode": t.mcc,
                "mobileNetworkCode": t.mnc,
                "signalStrength": t.signal_dbm,
            }
            if t.lac > 0:
                entry["locationAreaCode"] = t.lac
            if t.cid > 0:
                entry["cellId"] = t.cid
            cell_towers.append(entry)

        payload = json.dumps({
            "cellTowers": cell_towers,
            "fallbacks": {"lacf": True, "ipf": True},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                self.MLS_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            loc = data.get("location", {})
            lat = loc.get("lat", 0.0)
            lng = loc.get("lng", 0.0)
            acc = data.get("accuracy", 500.0)

            if lat != 0 and lng != 0:
                return CellPosition(
                    latitude=lat, longitude=lng, accuracy_m=acc,
                    source="mls", towers_used=len(cell_towers),
                    primary_radio=towers[0].radio,
                    timestamp=time.time(),
                )
        except (urllib.error.URLError, urllib.error.HTTPError, Exception):
            pass

        return None

    def _query_opencellid(self, towers: List[CellTower]) -> Optional[CellPosition]:
        """Query OpenCellID for individual tower positions, then triangulate."""
        if not self._api_key or not towers:
            return None

        located_towers: List[Tuple[float, float, float, float]] = []  # lat,lon,range,signal

        for t in towers[:5]:
            cache_key = f"{t.mcc}:{t.mnc}:{t.lac}:{t.cid}"

            # Check cache
            if cache_key in self._tower_cache:
                lat, lon, rng = self._tower_cache[cache_key]
                located_towers.append((lat, lon, rng, t.signal_dbm))
                continue

            if t.cid <= 0 or t.lac <= 0:
                continue

            self._api_call_count += 1

            try:
                url = (f"{self.OPENCELLID_URL}"
                       f"?key={self._api_key}"
                       f"&mcc={t.mcc}&mnc={t.mnc}"
                       f"&lac={t.lac}&cellid={t.cid}"
                       f"&format=json")

                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = json.loads(resp.read())

                lat = data.get("lat", 0.0)
                lon = data.get("lon", 0.0)
                rng = data.get("range", 1000)

                if lat != 0 and lon != 0:
                    self._tower_cache[cache_key] = (lat, lon, rng)
                    located_towers.append((lat, lon, rng, t.signal_dbm))

            except (urllib.error.URLError, urllib.error.HTTPError, Exception):
                pass

        if not located_towers:
            return None

        return self._triangulate(located_towers, towers[0].radio)

    def _triangulate_from_cache(self, towers: List[CellTower]) -> Optional[CellPosition]:
        """Triangulate using cached tower positions."""
        located = []
        for t in towers:
            key = f"{t.mcc}:{t.mnc}:{t.lac}:{t.cid}"
            if key in self._tower_cache:
                lat, lon, rng = self._tower_cache[key]
                located.append((lat, lon, rng, t.signal_dbm))

        if not located:
            return None

        return self._triangulate(located, towers[0].radio)

    def _triangulate(self, located: List[Tuple[float, float, float, float]],
                     radio: str) -> CellPosition:
        """Triangulate position from tower locations weighted by signal strength."""
        total_w = 0.0
        w_lat = 0.0
        w_lon = 0.0

        for lat, lon, rng, sig in located:
            # Weight: stronger signal = closer = more weight
            weight = 1.0 / max(1.0, abs(sig) - 30)
            w_lat += lat * weight
            w_lon += lon * weight
            total_w += weight

        if total_w == 0:
            return CellPosition(
                latitude=located[0][0], longitude=located[0][1],
                accuracy_m=located[0][2],
                source="opencellid", towers_used=1,
                primary_radio=radio, timestamp=time.time(),
            )

        est_lat = w_lat / total_w
        est_lon = w_lon / total_w

        # Accuracy: weighted average of tower ranges
        avg_range = sum(rng for _, _, rng, _ in located) / len(located)
        accuracy = max(50.0, avg_range * 0.5)  # Conservative estimate

        return CellPosition(
            latitude=est_lat, longitude=est_lon, accuracy_m=accuracy,
            source="opencellid", towers_used=len(located),
            primary_radio=radio, timestamp=time.time(),
        )

    # ── Simulation fallbacks ───────────────────────────────────────

    def _simulate_towers(self) -> List[CellTower]:
        """Generate simulated cell towers for testing."""
        import random
        count = random.randint(2, 5)
        towers = []
        for i in range(count):
            towers.append(CellTower(
                mcc=404,  # India
                mnc=random.choice([10, 40, 45, 49, 86]),  # Airtel/Voda/Jio/BSNL
                lac=random.randint(1000, 9999),
                cid=random.randint(10000, 99999),
                signal_dbm=random.randint(-100, -55),
                radio=random.choice(["LTE", "UMTS", "NR"]),
            ))
        return towers

    def _simulate_position(self, towers: List[CellTower]) -> CellPosition:
        """Return simulated position when APIs are unavailable."""
        import random
        avg_sig = sum(t.signal_dbm for t in towers) / len(towers) if towers else -80
        noise = max(0.0002, (abs(avg_sig) - 40) / 300.0)

        return CellPosition(
            latitude=13.0827 + random.gauss(0, noise),
            longitude=80.2707 + random.gauss(0, noise),
            accuracy_m=max(50, abs(avg_sig) * 3.0),
            source="simulated",
            towers_used=len(towers),
            primary_radio=towers[0].radio if towers else "LTE",
            timestamp=time.time(),
        )

    # ── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "platform": self._platform,
            "has_api_key": bool(self._api_key),
            "scan_count": self._scan_count,
            "api_calls": self._api_call_count,
            "cached_towers": len(self._tower_cache),
            "last_towers": len(self._last_scan),
            "last_source": self._last_position.source if self._last_position else None,
            "cache_ttl_s": self._cache_ttl_s,
        }
