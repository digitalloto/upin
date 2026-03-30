"""
UPIN Full Dashboard Backend — Serves all UPIN capabilities via API.
"""
import json, os, sys, time, math, random
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

# Add parent dir so we can import upin modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# ── State stores (in-memory for demo) ─────────────────────────────
intel_store = []
swarm_units = []
iff_log = []
comms_log = []
recorder_log = []
geofence_violations = []

# ── UPIN Layer List ───────────────────────────────────────────────
GROUPS = {"A":"Satellite/Celestial","B":"Inertial/Timing","C":"Magnetic/Quantum",
          "D":"RF/Terrestrial","E":"Optical/Vision","F":"Acoustic","G":"Gravity",
          "H":"Chemical/Seismic","I":"Cosmic/Atmospheric","J":"Human/Crowd","K":"Systems Intelligence"}

try:
    from upin.layers.registry import ALL_LAYER_CLASSES
    LAYER_LIST = []
    for lid, cls in ALL_LAYER_CLASSES.items():
        inst = cls()
        LAYER_LIST.append({"id":lid,"name":inst.name,"group":inst.group.value,
                           "bio":inst.bio_inspiration,"novel":inst.is_novel,
                           "underwater":inst.is_underwater,"accuracy":inst.get_accuracy_rating(),"on":False})
    # Default some on
    for l in LAYER_LIST:
        if l["id"] in ("gps_l1","navic_l2","ins_l3","baro_l11","magano_l6","vslam_l31",
                        "wifi_l8","celltower_l9","doppler_l12","opticflow_l43","terrain_l5","rfanomaly_l16"):
            l["on"] = True
except Exception:
    LAYER_LIST = [{"id":"gps_l1","name":"GPS","group":"A","bio":"","novel":False,"underwater":False,"accuracy":0.9,"on":True}]

# ── Preset definitions ────────────────────────────────────────────
try:
    from upin.layers.layer_manager import LayerManager
    _lm = LayerManager()
    PRESETS = {k: v for k, v in _lm._get_all_presets().items()}
except Exception:
    PRESETS = {"all": [l["id"] for l in LAYER_LIST]}

# ── Handler ───────────────────────────────────────────────────────
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        p = urlparse(self.path).path.rstrip("/")
        if p == "/api/layers/list":       self._j({"layers":LAYER_LIST,"groups":GROUPS})
        elif p == "/api/presets/list":     self._j({"presets":{k:len(v) for k,v in PRESETS.items()}})
        elif p.startswith("/api/presets/load/"):
            name = p.split("/")[-1]
            ids = PRESETS.get(name, [])
            for l in LAYER_LIST: l["on"] = l["id"] in ids
            self._j({"preset":name,"count":len(ids),"layers":ids})
        elif p == "/api/intel/list":       self._j({"intel":intel_store})
        elif p == "/api/swarm/list":       self._j({"units":swarm_units})
        elif p == "/api/swarm/formations": self._j({"formations":["diamond","line","vee","circle","grid","isr","perimeter"]})
        elif p == "/api/iff/log":          self._j({"log":iff_log[-20:]})
        elif p == "/api/comms/log":        self._j({"log":comms_log[-20:]})
        elif p == "/api/recorder/log":     self._j({"log":recorder_log[-30:]})
        elif p == "/api/geofence/status":  self._j({"violations":geofence_violations,"boundaries":3})
        elif p == "/api/power/status":
            batt = random.uniform(60,95)
            state = "FULL" if batt>80 else "NORMAL" if batt>50 else "LOW"
            active = sum(1 for l in LAYER_LIST if l["on"])
            power_mw = active * 150
            runtime = (batt/100*18500) / max(power_mw,1) * 60
            self._j({"battery":round(batt,1),"state":state,"active_layers":active,
                      "power_mw":power_mw,"runtime_min":round(runtime,1)})
        elif p == "/api/confidence/status":
            active = [l["id"] for l in LAYER_LIST if l["on"]]
            has_gps = any("gps" in a for a in active)
            conf = min(95, len(active)*5 + (30 if has_gps else 0))
            rec = "CONTINUE" if conf>80 else "MONITOR" if conf>60 else "RETURN" if conf>40 else "HOLD"
            drift = 0.1 if has_gps else 2.0
            self._j({"confidence":conf,"recommendation":rec,"degradation_rate":drift,
                      "active_agents":len(active),"has_gps":has_gps})
        elif p == "/api/sensors/wifi_csi":
            self._j({"person_count":random.randint(0,3),"movement":"civilian",
                      "wall":"drywall","confidence":round(random.uniform(0.6,0.9),2),
                      "armed_count":0,"nodes":4})
        elif p == "/api/sensors/thermal":
            sigs = [{"temp_c":round(36+random.uniform(-1,2),1),"size":"human","conf":round(random.uniform(0.7,0.95),2)} for _ in range(random.randint(0,3))]
            self._j({"signatures":sigs,"frame_size":"512x640"})
        elif p == "/api/sensors/drone":
            det = random.random() > 0.7
            self._j({"detected":det,"type":"QUADCOPTER" if det else "NONE",
                      "threat":"SUSPICIOUS" if det else "CLEAR",
                      "distance_m":round(random.uniform(200,1500)) if det else None,
                      "confidence":round(random.uniform(0.7,0.95),2) if det else 0})
        elif p == "/api/sensors/target_lock":
            self._j({"targets":len([u for u in swarm_units if u.get("role")=="strike"]),
                      "human_authorised":0,"max_targets":20})
        elif p == "/api/calibration/status":
            self._j({"device":"demo-001","auto_calibration":True,
                      "reference_points":38,"global_coverage":"6 continents",
                      "last_calibration":"2 min ago","drift_compensation":"active"})
        elif p == "/api/hardening/spec":
            self._j({"groups":{
                "GROUP_1":{"weight":"<1.5kg","agents":4,"hardening":"NONE"},
                "GROUP_2":{"weight":"1.5-25kg","agents":8,"hardening":"Basic EMI"},
                "GROUP_3":{"weight":"25-150kg","agents":13,"hardening":"Partial Faraday"},
                "GROUP_4":{"weight":"150-600kg","agents":22,"hardening":"Full MIL-STD"},
                "GROUP_5":{"weight":">600kg","agents":63,"hardening":"Maximum"},
            }})
        elif p == "/api/status":
            self._j({"status":"operational","layers":sum(1 for l in LAYER_LIST if l["on"]),
                      "total_layers":len(LAYER_LIST),"algorithms":7,"presets":len(PRESETS),
                      "intel_entries":len(intel_store),"swarm_units":len(swarm_units)})
        else:
            if p in ("", "/"): self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        p = urlparse(self.path).path.rstrip("/")
        body = self._body()
        if p == "/api/intel/add":
            d = json.loads(body)
            d["intel_id"] = f"I{len(intel_store)+1:03d}"
            d["timestamp"] = time.time()
            intel_store.append(d)
            self._j({"status":"ok","entry":d})
        elif p == "/api/intel/remove":
            d = json.loads(body)
            iid = d.get("intel_id")
            intel_store[:] = [e for e in intel_store if e.get("intel_id") != iid]
            self._j({"status":"ok"})
        elif p == "/api/swarm/add":
            d = json.loads(body)
            d["unit_id"] = f"U{len(swarm_units)+1:03d}"
            d["status"] = "ACTIVE"
            d["timestamp"] = time.time()
            swarm_units.append(d)
            self._j({"status":"ok","unit":d})
        elif p == "/api/swarm/remove":
            d = json.loads(body)
            uid = d.get("unit_id")
            swarm_units[:] = [u for u in swarm_units if u.get("unit_id") != uid]
            self._j({"status":"ok"})
        elif p == "/api/swarm/formation":
            d = json.loads(body)
            for u in swarm_units: u["formation"] = d.get("formation","diamond")
            self._j({"status":"ok","formation":d.get("formation"),"units":len(swarm_units)})
        elif p == "/api/swarm/mission":
            d = json.loads(body)
            for u in swarm_units: u["mission"] = d.get("mission","patrol")
            self._j({"status":"ok","mission":d.get("mission")})
        elif p == "/api/iff/check":
            d = json.loads(body)
            factors = random.randint(0,7)
            verdict = "FRIENDLY" if factors==7 else "SUSPECT" if factors>=4 else "HOSTILE"
            result = {"target":d.get("target","unknown"),"factors_passed":factors,
                       "verdict":verdict,"timestamp":time.time()}
            iff_log.append(result)
            self._j(result)
        elif p == "/api/comms/send":
            d = json.loads(body)
            entry = {"from":d.get("from","node-1"),"to":d.get("to","node-2"),
                      "classification":d.get("classification","RESTRICTED"),
                      "encrypted":True,"timestamp":time.time(),"size_bytes":random.randint(64,512)}
            comms_log.append(entry)
            self._j({"status":"ok","entry":entry})
        elif p == "/api/recorder/event":
            d = json.loads(body)
            d["timestamp"] = time.time()
            d["event_id"] = f"E{len(recorder_log)+1:04d}"
            recorder_log.append(d)
            self._j({"status":"ok","event":d})
        elif p == "/api/geofence/check":
            d = json.loads(body)
            lat, lon = d.get("lat",13.08), d.get("lon",80.27)
            # Simple check against Mumbai airport NFZ
            in_nfz = 19.08<=lat<=19.10 and 72.86<=lon<=72.88
            result = {"position":{"lat":lat,"lon":lon},"violation":in_nfz,
                       "zone":"Mumbai Airport NFZ" if in_nfz else "CLEAR"}
            if in_nfz: geofence_violations.append(result)
            self._j(result)
        elif p == "/api/false_position/start":
            d = json.loads(body)
            self._j({"status":"broadcasting","strategy":d.get("strategy","MIRROR"),
                      "true_lat":d.get("true_lat",13.08),"true_lon":d.get("true_lon",80.27),
                      "false_lat":d.get("true_lat",13.08)+0.02,"false_lon":d.get("true_lon",80.27)-0.015,
                      "authorised":True})
        elif p == "/api/layers/toggle":
            d = json.loads(body)
            lid = d.get("layer_id")
            for l in LAYER_LIST:
                if l["id"]==lid: l["on"] = not l["on"]
            self._j({"status":"ok","layer_id":lid})
        else:
            self._j({"error":"not found"},404)

    def _body(self):
        cl = int(self.headers.get("Content-Length",0))
        return self.rfile.read(cl).decode() if cl>0 else "{}"
    def _j(self, data, status=200):
        b = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()
        self.wfile.write(b)
    def do_OPTIONS(self):
        self._j({})
    def log_message(self, *a): pass

def main():
    port = int(os.environ.get("PORT", 5000))
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = HTTPServer(("0.0.0.0", port), H)
    print(f"UPIN Dashboard on http://0.0.0.0:{port}")
    print(f"Layers: {len(LAYER_LIST)} | Presets: {len(PRESETS)} | Algorithms: 7")
    server.serve_forever()

if __name__ == "__main__":
    main()
