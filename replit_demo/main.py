"""
UPIN Live Demo — Python backend for Replit deployment.

Serves the frontend files and provides API endpoints.
Uses only stdlib http.server (no Flask required).
"""

import json
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse


class UPINDemoHandler(SimpleHTTPRequestHandler):
    """Handler that serves static files and API endpoints."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/upin/status":
            self._send_json({
                "status": "operational",
                "active_layers": 7,
                "accuracy_m": 8.5,
                "threat_level": "low",
                "algorithms": {
                    "kalman":   {"confidence": 0.78, "accuracy": 12.3},
                    "particle": {"confidence": 0.94, "accuracy": 6.8},
                    "fish":     {"confidence": 0.89, "accuracy": 8.1},
                },
                "position": {"lat": 13.082734, "lon": 80.270542},
            })
        elif path.startswith("/api/upin/simulate/"):
            attack_type = path.split("/")[-1]
            self._handle_simulate(attack_type)
        else:
            # Serve static files from current directory
            if path == "" or path == "/":
                self.path = "/index.html"
            super().do_GET()

    def _handle_simulate(self, attack_type):
        if attack_type == "spoofing":
            self._send_json({
                "attack": "gps_spoofing",
                "status": "detected",
                "false_position": {"lat": 13.263895, "lon": 80.492137},
                "upin_response": "switched_to_non_gps_sensors",
            })
        elif attack_type == "jamming":
            self._send_json({
                "attack": "gps_jamming",
                "status": "detected",
                "jammer_location": {"lat": 13.0850, "lon": 80.2750},
                "confidence": 0.94,
                "upin_response": "triangulated_jammer_position",
            })
        else:
            self._send_json({"error": "Unknown attack type"}, 400)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Only log errors, not every request
        if args and "200" not in str(args[0]):
            super().log_message(fmt, *args)


def main():
    port = int(os.environ.get("PORT", 5000))

    # Change to the directory containing this script
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    server = HTTPServer(("0.0.0.0", port), UPINDemoHandler)
    print(f"UPIN Live Demo running on http://0.0.0.0:{port}")
    print("Open in browser to view the interactive demo.")
    server.serve_forever()


if __name__ == "__main__":
    main()
