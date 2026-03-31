"""
Real WiFi Positioning Agent — UPIN

Uses actual WiFi network scans and Mozilla Location Service (MLS) API
to determine position from surrounding WiFi access points.

MLS is free, no API key required for basic usage.

On platforms without WiFi scanning (e.g. headless servers), falls back
to simulated WiFi data for testing.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from upin.agents.base_agent import BaseAgent


@dataclass
class WiFiNetwork:
    """One detected WiFi network."""
    bssid: str              # MAC address (AA:BB:CC:DD:EE:FF)
    ssid: str               # Network name
    signal_dbm: int         # Signal strength in dBm
    channel: int = 0
    frequency_mhz: int = 0


@dataclass
class WiFiPosition:
    """Position result from WiFi-based positioning."""
    latitude: float
    longitude: float
    accuracy_m: float
    source: str             # "mls" | "simulated" | "cached"
    networks_used: int
    timestamp: float


class RealWiFiPositioningAgent(BaseAgent):
    """
    Real WiFi positioning using device WiFi scan + Mozilla Location Service.

    Workflow:
      1. Scan WiFi networks on the device (platform-specific)
      2. Send BSSIDs + signal strengths to MLS API
      3. Receive lat/lon/accuracy from MLS
      4. Cache result and integrate with UPIN fusion

    Supports: Linux (nmcli / iwlist), macOS (airport), Windows (netsh).
    Falls back to simulation when scanning is unavailable.
    """

    MLS_URL = "https://location.services.mozilla.com/v1/geolocate?key=test"

    def __init__(self, agent_id: str = "wifi_real"):
        super().__init__(agent_id, "WIFI_REAL")
        self.status = "ACTIVE"
        self._last_scan: List[WiFiNetwork] = []
        self._last_position: Optional[WiFiPosition] = None
        self._cache_ttl_s = 10.0
        self._scan_count = 0
        self._api_call_count = 0
        self._platform = sys.platform

    # ── BaseAgent interface ────────────────────────────────────────

    def get_reading(self) -> Dict:
        pos = self.get_position()
        if pos:
            return {
                "agent_id": self.agent_id,
                "agent_type": self.agent_type,
                "lat": pos.latitude,
                "lon": pos.longitude,
                "accuracy_m": pos.accuracy_m,
                "confidence": max(0.1, min(0.95, 1.0 - pos.accuracy_m / 200.0)),
                "source": pos.source,
                "networks": pos.networks_used,
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
        return True  # Always available (falls back to simulation)

    def calibrate(self) -> bool:
        self._last_position = None
        self._last_scan = []
        return True

    # ── Public API ─────────────────────────────────────────────────

    def get_position(self) -> Optional[WiFiPosition]:
        """Get position from WiFi. Uses cache if fresh enough."""
        # Return cached if fresh
        if (self._last_position and
                time.time() - self._last_position.timestamp < self._cache_ttl_s):
            return self._last_position

        # Scan networks
        networks = self.scan_wifi()
        if not networks:
            # Fallback to simulated networks for testing
            networks = self._simulate_networks()

        self._last_scan = networks

        if not networks:
            return None

        # Query MLS
        position = self._query_mls(networks)

        if position:
            self._last_position = position
            return position

        # If MLS fails, return simulated position
        return self._simulate_position(networks)

    def scan_wifi(self) -> List[WiFiNetwork]:
        """Scan for WiFi networks using platform-specific tools."""
        self._scan_count += 1

        if self._platform.startswith("linux"):
            return self._scan_linux()
        elif self._platform == "darwin":
            return self._scan_macos()
        elif self._platform == "win32":
            return self._scan_windows()
        else:
            return []

    # ── Platform-specific scanners ─────────────────────────────────

    def _scan_linux(self) -> List[WiFiNetwork]:
        """Scan WiFi on Linux using nmcli or iwlist."""
        networks = []

        # Try nmcli first
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "BSSID,SSID,SIGNAL,CHAN,FREQ", "dev", "wifi", "list"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split(":")
                    if len(parts) >= 5:
                        bssid = ":".join(parts[:6]).strip().upper()
                        ssid = parts[6] if len(parts) > 6 else ""
                        try:
                            signal_pct = int(parts[-3]) if parts[-3].isdigit() else 50
                            signal_dbm = int(signal_pct * -0.5 - 30)  # Rough conversion
                            channel = int(parts[-2]) if parts[-2].isdigit() else 0
                            freq = int(parts[-1]) if parts[-1].isdigit() else 0
                        except (ValueError, IndexError):
                            signal_dbm, channel, freq = -65, 0, 0

                        if len(bssid) == 17:  # Valid MAC
                            networks.append(WiFiNetwork(
                                bssid=bssid, ssid=ssid, signal_dbm=signal_dbm,
                                channel=channel, frequency_mhz=freq,
                            ))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback to iwlist
        if not networks:
            try:
                result = subprocess.run(
                    ["iwlist", "scan"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    current_bssid = ""
                    current_signal = -70
                    current_ssid = ""
                    for line in result.stdout.split("\n"):
                        line = line.strip()
                        if "Address:" in line:
                            if current_bssid:
                                networks.append(WiFiNetwork(
                                    bssid=current_bssid, ssid=current_ssid,
                                    signal_dbm=current_signal,
                                ))
                            current_bssid = line.split("Address:")[-1].strip().upper()
                            current_signal = -70
                            current_ssid = ""
                        elif "Signal level=" in line:
                            try:
                                sig_part = line.split("Signal level=")[-1].split(" ")[0]
                                current_signal = int(sig_part)
                            except ValueError:
                                pass
                        elif "ESSID:" in line:
                            current_ssid = line.split("ESSID:")[-1].strip('"')
                    if current_bssid:
                        networks.append(WiFiNetwork(
                            bssid=current_bssid, ssid=current_ssid,
                            signal_dbm=current_signal,
                        ))
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return networks

    def _scan_macos(self) -> List[WiFiNetwork]:
        """Scan WiFi on macOS using airport utility."""
        networks = []
        try:
            airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            result = subprocess.run(
                [airport, "-s"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            bssid = parts[-3].upper()
                            signal = int(parts[-2])
                            ssid = " ".join(parts[:-6]) if len(parts) > 6 else parts[0]
                            if len(bssid) == 17 and ":" in bssid:
                                networks.append(WiFiNetwork(
                                    bssid=bssid, ssid=ssid, signal_dbm=signal,
                                ))
                        except (ValueError, IndexError):
                            pass
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return networks

    def _scan_windows(self) -> List[WiFiNetwork]:
        """Scan WiFi on Windows using netsh."""
        networks = []
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=Bssid"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                current_ssid = ""
                current_bssid = ""
                current_signal = -70
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if line.startswith("SSID") and "BSSID" not in line:
                        current_ssid = line.split(":", 1)[-1].strip()
                    elif "BSSID" in line:
                        if current_bssid:
                            networks.append(WiFiNetwork(
                                bssid=current_bssid, ssid=current_ssid,
                                signal_dbm=current_signal,
                            ))
                        current_bssid = line.split(":", 1)[-1].strip().upper()
                        current_signal = -70
                    elif "Signal" in line:
                        try:
                            pct = int(line.split(":")[-1].strip().rstrip("%"))
                            current_signal = int(pct * -0.5 - 30)
                        except ValueError:
                            pass
                if current_bssid:
                    networks.append(WiFiNetwork(
                        bssid=current_bssid, ssid=current_ssid,
                        signal_dbm=current_signal,
                    ))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return networks

    # ── Mozilla Location Service API ───────────────────────────────

    def _query_mls(self, networks: List[WiFiNetwork]) -> Optional[WiFiPosition]:
        """Query Mozilla Location Service for position."""
        if len(networks) < 2:
            return None

        self._api_call_count += 1

        # Build MLS request body
        wifi_towers = []
        for net in networks[:20]:  # MLS accepts up to ~20 APs
            wifi_towers.append({
                "macAddress": net.bssid,
                "signalStrength": net.signal_dbm,
                "channel": net.channel if net.channel else None,
                "frequency": net.frequency_mhz if net.frequency_mhz else None,
            })

        payload = json.dumps({
            "wifiAccessPoints": wifi_towers,
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
            acc = data.get("accuracy", 100.0)

            if lat != 0 and lng != 0:
                return WiFiPosition(
                    latitude=lat, longitude=lng, accuracy_m=acc,
                    source="mls", networks_used=len(wifi_towers),
                    timestamp=time.time(),
                )
        except (urllib.error.URLError, urllib.error.HTTPError, Exception):
            pass

        return None

    # ── Simulation fallbacks ───────────────────────────────────────

    def _simulate_networks(self) -> List[WiFiNetwork]:
        """Generate simulated WiFi networks for testing."""
        import random
        count = random.randint(3, 8)
        networks = []
        for i in range(count):
            bssid = ":".join(f"{random.randint(0,255):02X}" for _ in range(6))
            networks.append(WiFiNetwork(
                bssid=bssid,
                ssid=f"UPIN_SIM_{i}",
                signal_dbm=random.randint(-85, -40),
                channel=random.choice([1, 6, 11]),
                frequency_mhz=random.choice([2412, 2437, 2462, 5180, 5240]),
            ))
        return networks

    def _simulate_position(self, networks: List[WiFiNetwork]) -> WiFiPosition:
        """Return simulated position when MLS is unavailable."""
        import random
        # Simulate around Chennai with noise proportional to signal quality
        avg_signal = sum(n.signal_dbm for n in networks) / len(networks) if networks else -70
        noise_scale = max(0.0001, (abs(avg_signal) - 30) / 500.0)

        return WiFiPosition(
            latitude=13.0827 + random.gauss(0, noise_scale),
            longitude=80.2707 + random.gauss(0, noise_scale),
            accuracy_m=max(10, abs(avg_signal) * 1.5),
            source="simulated",
            networks_used=len(networks),
            timestamp=time.time(),
        )

    # ── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "platform": self._platform,
            "scan_count": self._scan_count,
            "api_calls": self._api_call_count,
            "last_networks": len(self._last_scan),
            "last_source": self._last_position.source if self._last_position else None,
            "cache_ttl_s": self._cache_ttl_s,
        }
