"""
REST API Server — UPIN External Interface

HTTP endpoints for external systems to interact with UPIN.
Provides position queries, threat alerts, configuration management,
and integration with fleet command systems.

Uses only stdlib http.server for zero-dependency deployment.
For production, wrap with gunicorn or replace with Flask/FastAPI.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs


class UPINRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for UPIN API endpoints."""

    # The upin_core reference is set on the class by UPINApiServer
    upin_core = None
    api_version = "v1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        routes = {
            "/api/v1/position": self._handle_position,
            "/api/v1/threats": self._handle_threats,
            "/api/v1/status": self._handle_status,
            "/api/v1/layers": self._handle_layers,
            "/api/v1/config": self._handle_config_get,
        }

        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._send_json({"status": "error", "message": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/v1/config":
            self._handle_config_post()
        else:
            self._send_json({"status": "error", "message": "Not found"}, 404)

    # ── Route handlers ─────────────────────────────────────────────

    def _handle_position(self):
        try:
            position, metadata = self.upin_core.get_current_position()
            self._send_json({
                "status": "success",
                "position": {
                    "latitude": position.latitude,
                    "longitude": position.longitude,
                    "accuracy_m": position.accuracy_m,
                },
                "metadata": metadata,
                "timestamp": time.time(),
            })
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_threats(self):
        try:
            threats = self.upin_core.get_active_threats()
            self._send_json({
                "status": "success",
                "threats": [
                    {
                        "threat_id": getattr(t, "threat_id", "unknown"),
                        "threat_type": getattr(t, "threat_type", "unknown"),
                        "confidence": getattr(t, "confidence", 0.0),
                    }
                    for t in threats
                ],
                "threat_count": len(threats),
            })
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_status(self):
        try:
            status = self.upin_core.get_system_status()
            self._send_json({
                "status": "success",
                "system_status": status,
                "api_version": self.api_version,
                "uptime": time.time() - getattr(self.upin_core, "start_time", time.time()),
            })
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_layers(self):
        try:
            layers = self.upin_core.get_layer_status()
            self._send_json({
                "status": "success",
                "layers": layers,
                "total_layers": len(layers),
                "active_layers": len([l for l in layers if l.get("active", False)]),
            })
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_config_get(self):
        try:
            config = self.upin_core.get_configuration()
            self._send_json({"status": "success", "configuration": config})
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_config_post(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            new_config = json.loads(body)
            success = self.upin_core.update_configuration(new_config)
            if success:
                self._send_json({"status": "success", "message": "Configuration updated"})
            else:
                self._send_json({"status": "error", "message": "Update failed"}, 400)
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, 500)

    # ── Helpers ────────────────────────────────────────────────────

    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


class UPINApiServer:
    """REST API server for UPIN external interface (stdlib only)."""

    def __init__(self, upin_core: Any, port: int = 5000):
        self.upin_core = upin_core
        self.port = port
        self.api_version = "v1.0"

        # Attach core reference to the handler class
        UPINRequestHandler.upin_core = upin_core
        UPINRequestHandler.api_version = self.api_version

    def start_server(self, debug: bool = False):
        """Start the API server (blocking)."""
        server = HTTPServer(("0.0.0.0", self.port), UPINRequestHandler)
        server.serve_forever()

    def get_routes(self) -> List[str]:
        """List available API routes."""
        return [
            "GET  /api/v1/position  — Current UPIN position",
            "GET  /api/v1/threats   — Active threat detections",
            "GET  /api/v1/status    — System health status",
            "GET  /api/v1/layers    — Positioning layer status",
            "GET  /api/v1/config    — Get configuration",
            "POST /api/v1/config    — Update configuration",
        ]
