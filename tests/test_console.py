"""Tests for the UPIN console: nothing made up reaches the page.

- The page's files contain no random-number calls, no Google, and load
  nothing from the internet.
- Missing sensors come through as missing (None), never as numbers.
- Truth exists only for the simulated source.
- The simulator drives the real box: a spoof jump is caught as physically
  impossible; jamming gives DEGRADED, not a made-up fix.
- The browser source converts the browser's 95% accuracy to 1-sigma, and
  refuses a location with no accuracy.
- The web server serves the page and state, and refuses controls the source
  does not offer.

Run: python tests/test_console.py
"""
import json
import math
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, ".")

from upin.box.fc_reader import FcGps  # noqa: E402
from upin.box.service import Box, BoxConfig  # noqa: E402
from upin.box.gateway import GnssEpoch  # noqa: E402
from upin.console.server import make_handler  # noqa: E402
from upin.console.sources import (W3C_95_TO_SIGMA, BrowserSource,  # noqa: E402
                                  ReplaySource, SimSource)
from upin.console.state import ConsoleState, clean  # noqa: E402

PASSED = []
STATIC = Path("upin/console/static")
CFG = BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0)


def test_page_has_nothing_made_up():
    for f in STATIC.iterdir():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"Math\.random|crypto\.getRandomValues", text), f
        assert "google" not in text.lower(), f
        urls = re.findall(r"https?://[^\s\"')]+", text)
        assert all("www.w3.org/2000/svg" in u for u in urls), (f, urls)
    print("[ok] page files: no random numbers, no Google, nothing loaded from "
          "the internet")
    PASSED.append("static")


def test_missing_stays_missing():
    st = ConsoleState("browser", "X", False, [])
    box = Box(CFG)
    out, sent = box.process(GnssEpoch(t=0.0, fix_type=0), 0.0)
    st.update(box, out, sent, sending=False)
    s = st.get()
    assert s["mode"] == "NO_FIX" and s["output"] is None
    assert all(s["sensors"][k] is None for k in ("heading", "baro", "flow", "range", "fc_gps"))
    assert s["truth"] is None and s["region"] is None and s["estimate"] is None
    assert s["signal_power"] is None    # no NAV-SAT: the chart stays empty
    assert clean({"a": float("inf"), "b": [float("nan"), 1.0]}) == {"a": None, "b": [None, 1.0]}
    json.dumps(s, allow_nan=False)
    try:
        st.update(box, out, sent, sending=False, truth={"lat": 0, "lon": 0})
        raise AssertionError("truth accepted for a real source")
    except ValueError:
        pass
    print("[ok] no sensors -> every sensor field is None; NO_FIX has no "
          "position; truth refused for a real source; state is strict JSON")
    PASSED.append("missing")


def test_sim_drives_the_real_box():
    st = ConsoleState("sim", "SIMULATION", True, SimSource.controls)
    sim = SimSource(st, 13.0827, 80.2707, seed=3)
    for _ in range(60):
        sim.step()
    assert st.get()["mode"] == "TRUSTED"
    sim.control("spoof_jump")
    sim.step()
    s = st.get()
    reach = [c for c in s["checks"] if c["check"] == "physically reachable"][0]
    cross = [c for c in s["checks"] if c["check"] == "cross-check"][0]
    assert s["mode"] == "DEGRADED" and reach["status"] == "FAIL"
    assert cross["status"] == "PASS"     # both receivers spoofed together
    sim.control("spoof_jump")
    for _ in range(10):
        sim.step()
    sim.control("deny")
    for _ in range(30):
        sim.step()
    s = st.get()
    assert s["mode"] == "DEGRADED" and s["input"]["jamming_state"] == "critical"
    o, tr = s["output"], s["truth"]
    d = math.hypot((o["lat"] - tr["lat"]) * 111320,
                   (o["lon"] - tr["lon"]) * 111320 * math.cos(math.radians(o["lat"])))
    assert abs(d - tr["error_m"]) < 0.01 and tr["label"] == "simulated truth"
    print(f"[ok] simulation through the real box: 500 m jump fails 'physically "
          f"reachable' (the cross-check passes: both receivers spoofed); 30 s "
          f"jammed -> DEGRADED, error vs simulated truth {tr['error_m']:.1f} m, "
          f"computed not stated")
    PASSED.append("sim")


def test_browser_source():
    st = ConsoleState("browser", "X", False, BrowserSource.controls)
    src = BrowserSource(st)
    assert src.fix({"lat": 13.0, "lon": 80.0}).startswith("refused")
    assert src.fix({"lat": 13.0, "lon": 80.0, "accuracy": 24.48}) == "TRUSTED"
    s = st.get()
    assert abs(s["input"]["h_acc_m"] - 24.48 * W3C_95_TO_SIGMA) < 1e-9
    src.control("deny")
    assert src.fix({"lat": 13.0, "lon": 80.0, "accuracy": 24.48}) == "DEGRADED"
    print("[ok] browser location: 95% accuracy 24.5 m -> 10.0 m 1-sigma; no "
          "accuracy -> refused; software denial works")
    PASSED.append("browser")


def test_board_only_epoch():
    box = Box(CFG)
    ep = box.epoch_from_fc_gps(FcGps(1.0, 3, 13.0, 80.0, 50.0, None, 10), 1.0)
    out, _ = box.process(ep, 0.0)
    assert out.mode == "NO_FIX" and any("accuracy" in r for r in out.reasons), out.reasons
    ep = box.epoch_from_fc_gps(FcGps(2.0, 3, 13.0, 80.0, 50.0, 2.0, 10, (1.0, 2.0), 0.3), 2.0)
    out, _ = box.process(ep, 0.0)
    assert out.mode == "TRUSTED" and ep.vel_ned_ms == (1.0, 2.0, 0.0)
    print("[ok] board-only: a fix without stated accuracy is refused and says "
          "why; with accuracy it is used")
    PASSED.append("board")


def test_replay_redecides():
    with tempfile.TemporaryDirectory() as d:
        log_path = os.path.join(d, "box.jsonl")
        with open(log_path, "w") as log:
            box = Box(CFG, log=log)
            for k in range(20):
                box.process(GnssEpoch(t=float(k), fix_type=3, lat=13.0, lon=80.0,
                                      h_acc_m=2.0), 0.0)
        st = ConsoleState("replay", "REPLAY", False, [])
        src = ReplaySource(st, log_path, CFG, speed=1000.0)
        src.start()
        for _ in range(200):
            if st.get()["epochs"] == 20:
                break
            threading.Event().wait(0.01)
        assert st.get()["epochs"] == 20 and st.get()["mode"] == "TRUSTED"
    print("[ok] replay re-decides a box log with today's code")
    PASSED.append("replay")


def _req(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server():
    st = ConsoleState("sim", "SIMULATION", True, SimSource.controls)
    sim = SimSource(st, 13.0827, 80.2707, seed=1)
    sim.step()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(st, sim, {"tiles": None}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        code, page = _req(base + "/")
        assert code == 200 and b"UPIN Console" in page
        assert _req(base + "/app.js")[0] == 200
        assert _req(base + "/../server.py")[0] == 404
        code, body = _req(base + "/api/state")
        s = json.loads(body)
        assert code == 200 and s["source"]["simulated"] is True
        assert _req(base + "/api/control", {"action": "spoof_jump"})[0] == 200
        assert _req(base + "/api/control", {"action": "format_disk"})[0] == 403
        assert _req(base + "/api/browser_fix", {"lat": 1, "lon": 1, "accuracy": 5})[0] == 403
    finally:
        srv.shutdown()
    print("[ok] server: page and state served; path escape refused; unknown "
          "control and wrong-source location refused")
    PASSED.append("server")


if __name__ == "__main__":
    tests = [test_page_has_nothing_made_up, test_missing_stays_missing,
             test_sim_drives_the_real_box, test_browser_source,
             test_board_only_epoch, test_replay_redecides, test_server]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} console tests passed")
