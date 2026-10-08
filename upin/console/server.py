"""
The UPIN console: a web page served by UPIN itself, showing what the box
computes as it computes it.

  python -m upin.console --source sim                       # simulated drone
  python -m upin.console --source browser                   # this device's location
  python -m upin.console --source board --config box.toml   # flight controller on USB
  python -m upin.console --source live  --config box.toml   # the full box
  python -m upin.console --source replay --log box.jsonl --config box.toml

Then open http://localhost:8080. From another device on the network, start
with --host 0.0.0.0 and open http://<computer-name>.local:8080. A browser
shares its location only on localhost or https, so the browser source
works on the computer running the console.

No internet needed: the page, its map and its scripts are all served from
here. Standard library only.

MAPS: by the project's rule, no Google Maps and no non-Indian map sources.
The map is drawn without a basemap by default: a grid in metres. An Indian
tile source (e.g. Bhuvan) can be given with --tiles once its licence for
this use is confirmed.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from upin.box.service import BoxConfig, load_config
from upin.console.sources import (BrowserSource, LiveSource, ReplaySource,
                                  SimSource, Source)
from upin.console.state import ConsoleState

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
         ".css": "text/css"}

LABELS = {
    "sim": ("SIMULATION", True,
            "Simulated sensors. UPIN's processing of them is real."),
    "browser": ("THIS DEVICE'S LOCATION", False,
                "Real location from this browser: phone or laptop positioning, "
                "not a GNSS receiver. Its accuracy is what the browser reports."),
    "board": ("FLIGHT CONTROLLER", False,
              "Real data from the flight controller; its own GPS is the input. "
              "Listen only."),
    "live": ("LIVE BOX", False,
             "Real data: the box's receiver and the flight controller."),
    "replay": ("REPLAY", False,
               "A recorded log re-decided by today's code. GNSS decisions only."),
}


def make_handler(state: ConsoleState, source: Source, config: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):          # quiet
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, allow_nan=False).encode())

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/state":
                return self._json(state.get())
            if path == "/api/config":
                return self._json(config)
            name = "index.html" if path == "/" else path.lstrip("/")
            f = STATIC / name
            if "/" in name or not f.is_file():
                return self._send(404, b"not found", "text/plain")
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, "text/plain"))

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad JSON"}, 400)
            if self.path == "/api/control":
                action = str(body.get("action", ""))
                if action not in source.controls:
                    return self._json({"error": f"'{action}' not allowed here"}, 403)
                return self._json({"result": source.control(action)})
            if self.path == "/api/browser_fix":
                if not isinstance(source, BrowserSource):
                    return self._json({"error": "not the browser source"}, 403)
                return self._json({"result": source.fix(body)})
            self._json({"error": "unknown"}, 404)

    return Handler


def build(args) -> tuple:
    cfg: Optional[BoxConfig] = load_config(args.config) if args.config else None
    label, simulated, note = LABELS[args.source]
    if args.source == "sim":
        lat, lon = (float(x) for x in args.start.split(","))
        state = ConsoleState("sim", label, True, SimSource.controls, note)
        src = SimSource(state, lat, lon, speed=args.speed, cfg=cfg)
    elif args.source == "browser":
        state = ConsoleState("browser", label, False, BrowserSource.controls, note)
        src = BrowserSource(state, cfg)
    elif args.source in ("board", "live"):
        if cfg is None:
            raise SystemExit("--config is required for board and live")
        controls = ["deny"] if args.allow_control else []
        state = ConsoleState(args.source, label, False, controls, note)
        src = LiveSource(state, cfg, "fc" if args.source == "board" else "receiver",
                         send=args.source == "live" and not args.no_send,
                         allow_control=args.allow_control)
    else:
        if cfg is None or not args.log:
            raise SystemExit("--config and --log are required for replay")
        state = ConsoleState("replay", label, False, [], note)
        src = ReplaySource(state, args.log, cfg, args.speed)
    config = {"tiles": args.tiles, "tiles_attribution": args.tiles_attribution,
              "source": args.source}
    return state, src, config


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="UPIN console")
    ap.add_argument("--source", required=True,
                    choices=["sim", "browser", "board", "live", "replay"])
    ap.add_argument("--config", help="box config (TOML); required for board/live/replay")
    ap.add_argument("--log", help="box log to replay")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--speed", type=float, default=1.0,
                    help="sim/replay speed-up (1 = real time)")
    ap.add_argument("--start", default="13.0827,80.2707",
                    help="sim start point lat,lon (default: Chennai)")
    ap.add_argument("--tiles", default=None,
                    help="XYZ tile URL template with {z}/{x}/{y}, Indian source only")
    ap.add_argument("--tiles-attribution", default="")
    ap.add_argument("--allow-control", action="store_true",
                    help="live/board: allow the page to deny GNSS in software")
    ap.add_argument("--no-send", action="store_true",
                    help="live: do not send GPS_INPUT")
    a = ap.parse_args(argv)
    state, src, config = build(a)
    src.start()
    server = ThreadingHTTPServer((a.host, a.port), make_handler(state, src, config))
    print(f"UPIN console ({LABELS[a.source][0]}) on http://"
          f"{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:"
          f"{server.server_address[1]}  -- Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        src.stop()
        server.server_close()
