"""
UPIN Mobile Real-Time Interface Server

Real-time positioning interface with:
- Intel markers with SQLite persistence
- Multi-device triangulation
- Sensor data relay from phone to UPIN layers
- Anti-spoofing alerts
- Layer status broadcasting

Uses stdlib http.server + SSE (Server-Sent Events) for real-time.
No external dependencies required.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs


# ── SQLite Persistence ────────────────────────────────────────────

class UPINMobileDatabase:
    """SQLite storage for intel markers, triangulation, calibration."""

    def __init__(self, db_path: str = "upin_mobile.db"):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS intel_markers (
                id TEXT PRIMARY KEY,
                lat REAL, lon REAL, alt REAL,
                marker_type TEXT, threat_level TEXT,
                description TEXT, timestamp REAL,
                source_layer INTEGER, confidence REAL,
                metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS triangulation_points (
                id TEXT PRIMARY KEY,
                devices TEXT,
                lat REAL, lon REAL, alt REAL,
                accuracy_radius REAL, confidence REAL,
                timestamp REAL
            );
            CREATE TABLE IF NOT EXISTS sensor_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT, sensor_type TEXT,
                data TEXT, timestamp REAL
            );
            CREATE TABLE IF NOT EXISTS layer_config (
                layer_id TEXT PRIMARY KEY,
                enabled INTEGER, parameters TEXT,
                last_modified REAL
            );
        """)
        self.db.commit()

    def add_intel_marker(self, marker: Dict) -> str:
        mid = marker.get("id", str(uuid.uuid4())[:8])
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO intel_markers VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (mid, marker.get("lat", 0), marker.get("lon", 0), marker.get("alt", 0),
                 marker.get("type", "unknown"), marker.get("threat_level", "low"),
                 marker.get("description", ""), time.time(),
                 marker.get("source_layer", 0), marker.get("confidence", 0.5),
                 json.dumps(marker.get("metadata", {}))))
            self.db.commit()
        return mid

    def get_intel_markers(self) -> List[Dict]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM intel_markers ORDER BY timestamp DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]

    def remove_intel_marker(self, mid: str):
        with self._lock:
            self.db.execute("DELETE FROM intel_markers WHERE id=?", (mid,))
            self.db.commit()

    def add_triangulation(self, tri: Dict) -> str:
        tid = tri.get("id", str(uuid.uuid4())[:8])
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO triangulation_points VALUES (?,?,?,?,?,?,?,?)",
                (tid, json.dumps(tri.get("devices", [])),
                 tri.get("lat", 0), tri.get("lon", 0), tri.get("alt", 0),
                 tri.get("accuracy_radius", 100), tri.get("confidence", 0.5),
                 time.time()))
            self.db.commit()
        return tid

    def get_triangulations(self) -> List[Dict]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM triangulation_points ORDER BY timestamp DESC LIMIT 50").fetchall()
        return [dict(r) for r in rows]

    def log_sensor(self, device_id: str, sensor_type: str, data: Dict):
        with self._lock:
            self.db.execute(
                "INSERT INTO sensor_log (device_id, sensor_type, data, timestamp) VALUES (?,?,?,?)",
                (device_id, sensor_type, json.dumps(data), time.time()))
            self.db.commit()


# ── Triangulation Engine ──────────────────────────────────────────

class TriangulationEngine:
    """Multi-device bearing-based triangulation."""

    @staticmethod
    def triangulate_from_bearings(
        observations: List[Dict],
    ) -> Optional[Dict]:
        """
        Triangulate target position from multiple device bearings.
        Each observation: {"lat", "lon", "bearing_deg", "device_id"}
        Needs 2+ observations.
        """
        if len(observations) < 2:
            return None

        # Convert bearings to intersection point (simplified)
        # Use first two observations for basic intersection
        a = observations[0]
        b = observations[1]

        lat1, lon1, brg1 = a["lat"], a["lon"], math.radians(a["bearing_deg"])
        lat2, lon2, brg2 = b["lat"], b["lon"], math.radians(b["bearing_deg"])

        # Project lines from each observer along bearing
        # Find approximate intersection (planar approximation)
        d = 1000  # projection distance in metres
        ax = lon1 + d * math.sin(brg1) / (111320 * math.cos(math.radians(lat1)))
        ay = lat1 + d * math.cos(brg1) / 111320
        bx = lon2 + d * math.sin(brg2) / (111320 * math.cos(math.radians(lat2)))
        by = lat2 + d * math.cos(brg2) / 111320

        # Line intersection
        denom = (lon1 - ax) * (lat2 - by) - (lat1 - ay) * (lon2 - bx)
        if abs(denom) < 1e-12:
            return None  # Parallel bearings

        t = ((lon1 - lon2) * (lat2 - by) - (lat1 - lat2) * (lon2 - bx)) / denom
        int_lon = lon1 + t * (ax - lon1)
        int_lat = lat1 + t * (ay - lat1)

        # Accuracy estimate from angle between bearings
        angle_diff = abs(math.degrees(brg1 - brg2)) % 180
        accuracy = max(10, 500 / max(1, angle_diff / 10))

        return {
            "lat": round(int_lat, 6),
            "lon": round(int_lon, 6),
            "accuracy_radius": round(accuracy, 1),
            "confidence": round(min(0.95, angle_diff / 90), 3),
            "devices": [o["device_id"] for o in observations],
            "timestamp": time.time(),
        }


# ── HTTP Handler ──────────────────────────────────────────────────

class MobileInterfaceHandler(BaseHTTPRequestHandler):
    """HTTP handler for mobile interface — REST + SSE."""

    db: UPINMobileDatabase = None
    triangulator = TriangulationEngine()

    # Shared state
    current_position = (13.0827, 80.2707, 10.0)
    spoofing_detected = False
    active_layers = {}
    sensor_data = {}
    connected_devices = {}

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "" or path == "/":
            self._serve_file("mobile_interface.html", "text/html")
        elif path == "/api/mobile/state":
            self._json({
                "position": self.current_position,
                "spoofing_detected": self.spoofing_detected,
                "active_layers": self.active_layers,
                "devices": len(self.connected_devices),
                "timestamp": time.time(),
            })
        elif path == "/api/mobile/intel":
            self._json({"markers": self.db.get_intel_markers() if self.db else []})
        elif path == "/api/mobile/triangulations":
            self._json({"points": self.db.get_triangulations() if self.db else []})
        elif path == "/api/mobile/sensors":
            self._json({"sensors": self.sensor_data})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        body = self._read_body()

        if path == "/api/mobile/sensor_data":
            d = json.loads(body)
            device_id = d.get("device_id", "unknown")
            self.sensor_data[device_id] = d
            self.connected_devices[device_id] = time.time()
            if self.db:
                self.db.log_sensor(device_id, d.get("type", "multi"), d)
            self._json({"status": "ok"})

        elif path == "/api/mobile/intel/add":
            d = json.loads(body)
            mid = self.db.add_intel_marker(d) if self.db else "no_db"
            self._json({"status": "ok", "id": mid})

        elif path == "/api/mobile/intel/remove":
            d = json.loads(body)
            if self.db:
                self.db.remove_intel_marker(d.get("id", ""))
            self._json({"status": "ok"})

        elif path == "/api/mobile/triangulate":
            d = json.loads(body)
            observations = d.get("observations", [])
            result = self.triangulator.triangulate_from_bearings(observations)
            if result and self.db:
                self.db.add_triangulation(result)
            self._json(result or {"error": "insufficient observations"})

        elif path == "/api/mobile/share_position":
            d = json.loads(body)
            device_id = d.get("device_id", "unknown")
            self.connected_devices[device_id] = time.time()
            self._json({"status": "ok", "devices": len(self.connected_devices)})

        else:
            self._json({"error": "not found"}, 404)

    def _read_body(self) -> str:
        cl = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(cl).decode() if cl > 0 else "{}"

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filename, content_type):
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        if not os.path.exists(filepath):
            # Serve from replit_demo if available
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "replit_demo", "index.html")
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._json({"error": "file not found"}, 404)

    def do_OPTIONS(self):
        self._json({})

    def log_message(self, *a):
        pass


# ── Server Startup ────────────────────────────────────────────────

def start_mobile_server(port: int = 8080, db_path: str = "upin_mobile.db"):
    """Start the UPIN mobile interface server."""
    db = UPINMobileDatabase(db_path)
    MobileInterfaceHandler.db = db

    server = HTTPServer(("0.0.0.0", port), MobileInterfaceHandler)
    print(f"UPIN Mobile Interface on http://0.0.0.0:{port}")
    print(f"Database: {db_path}")
    server.serve_forever()


if __name__ == "__main__":
    start_mobile_server()
