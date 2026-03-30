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

# All 63 UPIN layers for the layer browser
LAYER_LIST = [
    {"id":"gps_l1","name":"GPS","group":"A","on":True},
    {"id":"navic_l2","name":"NavIC","group":"A","on":True},
    {"id":"leo_l19","name":"LEO Authenticated","group":"A","on":False},
    {"id":"xnav_l29","name":"X-Ray Pulsar","group":"A","on":False},
    {"id":"stellar_l46","name":"Stellar Constellation","group":"A","on":False},
    {"id":"skygrad_l47","name":"Diffuse Sky","group":"A","on":False},
    {"id":"ins_l3","name":"INS Dead Reckoning","group":"B","on":True},
    {"id":"baro_l11","name":"Barometric Altitude","group":"B","on":True},
    {"id":"doppler_l12","name":"Doppler Velocity","group":"B","on":True},
    {"id":"laserdop_l18","name":"Laser Doppler","group":"B","on":False},
    {"id":"qclock_l27","name":"Quantum Clock","group":"B","on":False},
    {"id":"opticflow_l43","name":"Optic Flow","group":"B","on":True},
    {"id":"nmrgyro_l57","name":"NMR Gyroscope","group":"B","on":False},
    {"id":"serfgyro_l58","name":"SERF Gyroscope","group":"B","on":False},
    {"id":"radaralt_b09","name":"Radar Altimeter","group":"B","on":True},
    {"id":"depthpres_b10","name":"Depth Pressure","group":"B","on":False},
    {"id":"magano_l6","name":"Magnetic Anomaly","group":"C","on":True},
    {"id":"dualqmag_l17","name":"Dual Quantum Mag","group":"C","on":False},
    {"id":"magmap_l23","name":"Magnetic Map Match","group":"C","on":False},
    {"id":"eminduct_l24","name":"EM Induction","group":"C","on":False},
    {"id":"nvdiamond_l30","name":"NV Diamond Mag","group":"C","on":False},
    {"id":"bicoord_l44","name":"Biocoordinate GeoChem","group":"C","on":False},
    {"id":"efield_c07","name":"Electric Field (Eel)","group":"C","on":False},
    {"id":"groundrf_l7","name":"Ground Emitters","group":"D","on":False},
    {"id":"wifi_l8","name":"WiFi Military Nav","group":"D","on":True},
    {"id":"celltower_l9","name":"Cell Tower","group":"D","on":True},
    {"id":"eloran_l41","name":"eLORAN","group":"D","on":False},
    {"id":"soop_l42","name":"Commercial SOOP","group":"D","on":False},
    {"id":"uwb_d06","name":"UWB Positioning","group":"D","on":False},
    {"id":"lora_d07","name":"LoRaWAN","group":"D","on":False},
    {"id":"startrack_l4","name":"Star Tracking","group":"E","on":False},
    {"id":"terrain_l5","name":"Terrain Matching","group":"E","on":True},
    {"id":"polsky_l25a","name":"Polarised Sky","group":"E","on":False},
    {"id":"polwater_l25b","name":"Underwater Polarised","group":"E","on":False},
    {"id":"vslam_l31","name":"Visual SLAM","group":"E","on":True},
    {"id":"vio_l32","name":"Visual Odometry","group":"E","on":False},
    {"id":"lidar_l33","name":"LiDAR SLAM","group":"E","on":False},
    {"id":"thermal_l38","name":"Thermal IR","group":"E","on":False},
    {"id":"hyperspec_l39","name":"Hyperspectral","group":"E","on":False},
    {"id":"monarch_e10","name":"Monarch Sun Compass","group":"E","on":False},
    {"id":"acoustic_l10","name":"Passive Acoustic","group":"F","on":False},
    {"id":"sonar_l34","name":"Active Sonar","group":"F","on":False},
    {"id":"focsonar_l35","name":"Focused Sonar","group":"F","on":False},
    {"id":"gravgrad_l28a","name":"Gravity Gradiometer","group":"G","on":False},
    {"id":"gravimeter_l28b","name":"Dual Gravimeter","group":"G","on":False},
    {"id":"chemgrad_l26","name":"Chemical Gradient","group":"H","on":False},
    {"id":"seismic_l36","name":"Seismic Infrasound","group":"H","on":False},
    {"id":"hydrowake_l37","name":"Hydrodynamic Wake","group":"H","on":False},
    {"id":"tactile_l45","name":"Tactile Pressure","group":"H","on":False},
    {"id":"latline_l48","name":"Lateral Line","group":"H","on":False},
    {"id":"odometer_l60","name":"Locomotion Odometer","group":"H","on":False},
    {"id":"ionosphere_l49","name":"Ionospheric Density","group":"H","on":False},
    {"id":"muon_l40","name":"Muon Navigation","group":"I","on":False},
    {"id":"pulsar_l29b","name":"Pulsar Extended","group":"I","on":False},
    {"id":"schumann_l59","name":"Schumann Resonance","group":"I","on":False},
    {"id":"beacon_l20","name":"Human Beacon Network","group":"J","on":False},
    {"id":"spoofmap_l21","name":"Crowdsourced Spoof Map","group":"J","on":False},
    {"id":"radius_l22","name":"Radius Containment","group":"J","on":False},
    {"id":"antenna_l13","name":"Antenna Stabilisation","group":"K","on":False},
    {"id":"cascade_l14","name":"Cascade Prevention","group":"K","on":False},
    {"id":"swarmrel_l15","name":"Swarm Relative Position","group":"K","on":False},
    {"id":"rfanomaly_l16","name":"RF Anomaly Detection","group":"K","on":True},
    {"id":"tern_k05","name":"Arctic Tern Multi-Cue","group":"K","on":False},
]


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
        elif path == "/api/intel/list":
            self._send_json({"status": "ok", "intel": getattr(self.server, 'intel_store', [])})
        elif path == "/api/layers/list":
            self._send_json({"status": "ok", "layers": LAYER_LIST})
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

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        if path == "/api/intel/add":
            self._handle_add_intel(body)
        elif path == "/api/intel/remove":
            self._handle_remove_intel(body)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_add_intel(self, body):
        try:
            data = json.loads(body)
            intel_store = self.server.intel_store
            intel_id = str(len(intel_store) + 1).zfill(4)
            entry = {
                "intel_id": intel_id,
                "type": data.get("type", "CUSTOM"),
                "name": data.get("name", "Unnamed"),
                "lat": data.get("lat", 0),
                "lon": data.get("lon", 0),
                "radius_m": data.get("radius_m", 500),
                "severity": data.get("severity", 0.5),
                "description": data.get("description", ""),
                "timestamp": time.time(),
            }
            intel_store.append(entry)
            self._send_json({"status": "ok", "intel_id": intel_id, "entry": entry})
        except Exception as e:
            self._send_json({"error": str(e)}, 400)

    def _handle_remove_intel(self, body):
        try:
            data = json.loads(body)
            intel_id = data.get("intel_id")
            store = self.server.intel_store
            self.server.intel_store = [e for e in store if e["intel_id"] != intel_id]
            self._send_json({"status": "ok", "removed": intel_id})
        except Exception as e:
            self._send_json({"error": str(e)}, 400)

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
    server.intel_store = []  # Shared intel storage
    print(f"UPIN Live Demo running on http://0.0.0.0:{port}")
    print("Open in browser to view the interactive demo.")
    server.serve_forever()


if __name__ == "__main__":
    main()
