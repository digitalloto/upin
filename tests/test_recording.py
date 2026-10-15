"""Tests for the flight recorder and the offline replay.

A console-sim run (every sensor simulated) is recorded; the recording is
replayed through a fresh box and must reproduce the live decisions epoch
for epoch; a software denial is injected into the replay and measured
against the receiver's logged fix; a recording from another airframe is
refused; the disk cap stops the recorder, not the box.

Run: python tests/test_recording.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, ".")

import numpy as np  # noqa: E402

from upin.box.flight_replay import is_input_log, read_input_log, replay  # noqa: E402
from upin.box.recorder import FlightRecorder  # noqa: E402
from upin.box.service import BoxConfig  # noqa: E402
from upin.console.sources import ReplaySource, SimSource  # noqa: E402
from upin.console.state import ConsoleState  # noqa: E402

PASSED = []
LAT0, LON0 = 13.0827, 80.2707


def sim_cfg(tmp):
    return BoxConfig(max_accel_ms2=6.0, max_airspeed_ms=20.0, camera_flow=True, breadcrumbs=True,
                     breadcrumb_spacing_m=150.0, formation=True, drone_id="lead",
                     formation_check_action="distrust", wind_dr=True, airframe_id="sim-circuit-quad",
                     input_log_path=os.path.join(tmp, "inputs.jsonl"),
                     frames_dir=os.path.join(tmp, "frames"), frame_record_hz=10.0)


def replay_cfg(tmp, cfg, sim):
    """The recording box had its tag map and secret set in code; the replay
    box gets them from files, as a real one would."""
    L, R = SimSource.STRAIGHT_M, SimSource.RADIUS_M
    lat7, lon7 = sim._ll(-R, -L / 2)
    tags = os.path.join(tmp, "tags.json")
    with open(tags, "w") as f:
        json.dump({"tags": [{"tag_id": 7, "latitude": lat7, "longitude": lon7, "size_m": SimSource.TAG_SIZE_M,
                             "source": "field_survey", "position_accuracy_m": 0.3, "altitude_m": 0.0,
                             "name": "start tag"}]}, f)
    secret = os.path.join(tmp, "beacon.key")
    with open(secret, "wb") as f:
        f.write(SimSource.BEACON_SECRET)
    return BoxConfig(**{**cfg.__dict__, "input_log_path": "", "frames_dir": "", "tag_map": tags,
                        "beacon_secret_file": secret})


def record_run(tmp, seconds=70, actions=None):
    cfg = sim_cfg(tmp)
    st = ConsoleState("sim", "SIMULATION", True, SimSource.controls)
    sim = SimSource(st, LAT0, LON0, seed=6, cfg=cfg)
    outs = []
    for k in range(seconds):
        if actions and k in actions:
            sim.control(actions[k])
        for out, sent in sim.step():
            fixes = sorted(s for s, f in sim.box.gateway.last_fixes.items()
                           if f.get("accepted") and abs(f.get("t", -1e9) - out.t) <= 1.0)
            outs.append((out.t, out.mode, out.lat, out.lon, out.h_acc_m, fixes))
    done = sim.box.close()
    return cfg, sim, outs, done


def toml_for(cfg, path):
    lines = ["[box]"]
    for k, v in cfg.__dict__.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v!r}")
        else:
            lines.append(f'{k} = "{v}"')
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def test_record_and_replay_exactly():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, sim, live, done = record_run(tmp, actions={30: "spoof_jump", 34: "spoof_jump", 45: "deny"})
        r = done["recorder"]
        assert r["counts"]["epoch"] == len(live) and r["counts"]["fc"] > 500 and r["counts"]["radio"] > 100
        assert r["frames_saved"] == r["frames_seen_live"] == sim.box.frames_seen, r
        assert is_input_log(cfg.input_log_path)
        kinds = [x["kind"] for x in read_input_log(cfg.input_log_path)]
        assert kinds[0] == "header" and "frame" in kinds and "epoch" in kinds
        # frames are named by their own time: the pair at t-0.2 and t
        names = sorted(float(f[:-4]) for f in os.listdir(cfg.frames_dir))
        gaps = np.diff(names)
        assert np.allclose(sorted(set(np.round(gaps, 3))), [0.2, 0.8]), sorted(set(np.round(gaps, 3)))
        cfg2 = replay_cfg(tmp, cfg, sim)
        rep = replay(cfg2, "", cfg.input_log_path, cfg.frames_dir)
        assert len(rep.rows) == len(live) and rep.frames_replayed == r["frames_saved"]
        worst = 0.0
        for row, (t, mode, lat, lon, h_acc, fixes) in zip(rep.rows, live):
            assert row.t == t and row.mode == mode, (row.t, row.mode, t, mode)
            if lat is not None:
                d = math.hypot((row.lat - lat) * 111320, (row.lon - lon) * 111320)
                worst = max(worst, d)
                assert d < 0.05 and abs(row.h_acc_m - h_acc) < 1e-3, (t, d, row.h_acc_m, h_acc)
            assert row.fixes_accepted == fixes or set(row.fixes_accepted) == set(fixes), (t, row.fixes_accepted, fixes)
        modes = {m: sum(1 for x in live if x[1] == m) for m in ("TRUSTED", "DEGRADED", "NO_FIX")}
        assert modes["DEGRADED"] > 0 and modes["TRUSTED"] > 0
        print(f"[ok] recorded {r['counts']} and {r['frames_saved']} frames ({r['megabytes']:.0f} MB) from a "
              f"{len(live)} s run with a spoof and a denial; the replay reproduced every mode "
              f"({modes}) and every accepted fix, positions within {worst * 100:.1f} cm (float32 frames)")
        PASSED.append("exact")


def test_denial_injected_offline():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, sim, live, done = record_run(tmp, seconds=80)
        trusted = sum(1 for x in live[10:] if x[1] == "TRUSTED")
        assert trusted >= 0.8 * len(live[10:]), trusted     # the start tag's first fixes aside
        cfg2 = replay_cfg(tmp, cfg, sim)
        rep = replay(cfg2, "", cfg.input_log_path, cfg.frames_dir, deny_from=40.0, deny_for=30.0)
        den = rep.denied_rows()
        assert [r.t for r in den] == [float(t) for t in range(40, 70)], [r.t for r in den][:5]
        assert all(r.mode == "DEGRADED" for r in den), {r.mode for r in den}
        assert all(r.error_m is not None and math.isfinite(r.error_m) for r in den)
        s = rep.summary()
        assert s["denied_error_max_m"] < 30.0, s
        assert "camera flow" in s["velocity_sources_during_denial"] or "flow chip" in s["velocity_sources_during_denial"], s
        assert s["fixes_accepted_during_denial"], s
        text = rep.render()
        assert "GNSS denied in software" in text and "computed by re-running the box" in text
        # the live-style schedule: after N seconds of TRUSTED
        rep2 = replay(cfg2, "", cfg.input_log_path, cfg.frames_dir, deny_after=20.0, deny_for=10.0)
        den2 = rep2.denied_rows()
        assert len(den2) == 10 and den2[0].t >= 20.0, [r.t for r in den2]
        # a different airframe's config is refused: its curves would not match
        try:
            replay(BoxConfig(**{**cfg2.__dict__, "airframe_id": "other-quad"}), "", cfg.input_log_path)
            raise AssertionError("another airframe's config was accepted")
        except ValueError as exc:
            assert "airframe_id" in str(exc)
        # the tool, end to end
        toml = os.path.join(tmp, "box.toml")
        toml_for(cfg2, toml)
        report = os.path.join(tmp, "report.md")
        out = subprocess.run([sys.executable, "tools/replay_flight.py", "--config", toml, "--log",
                              cfg.input_log_path, "--frames", cfg.frames_dir, "--deny-from", "40",
                              "--deny-for", "20", "--report", report], capture_output=True, text=True)
        assert out.returncode == 0 and os.path.exists(report), out.stderr[-800:]
        assert "denied 20 epochs" in out.stdout, out.stdout
        print(f"[ok] denial injected offline at t = 40 s for 30 s: {len(den)} DEGRADED epochs, error vs the "
              f"receiver's logged fix mean {s['denied_error_mean_m']:.1f} m, worst {s['denied_error_max_m']:.1f} m, "
              f"velocity from {s['velocity_sources_during_denial']}, fixes {s['fixes_accepted_during_denial']}; "
              f"'after 20 s of TRUSTED' schedule works; another airframe refused; tools/replay_flight.py "
              f"writes the report")
        PASSED.append("denial")


def test_disk_cap_and_console_replay():
    with tempfile.TemporaryDirectory() as tmp:
        rec = FlightRecorder(os.path.join(tmp, "in.jsonl"), os.path.join(tmp, "fr"), frame_hz=10.0,
                             min_free_mb=1e12, header={"airframe_id": "x"})
        assert rec.frame(np.zeros((8, 8)), 1.0) is None and rec.stopped and "below" in rec.stopped
        rec.epoch(json.dumps({"t": 1.0, "fix_type": 0}), 1.0, 0.0)      # the box carries on
        rec.close()
        kinds = [x["kind"] for x in read_input_log(os.path.join(tmp, "in.jsonl"))]
        assert kinds == ["header", "note", "epoch"], kinds
        assert rec.status()["frames_saved"] == 0 and rec.status()["frames_seen"] == 1
        # the console replays a recording through the whole box
        cfg, sim, live, done = record_run(tmp, seconds=12)
        cfg2 = replay_cfg(tmp, cfg, sim)
        st = ConsoleState("replay", "REPLAY", False, [])
        src = ReplaySource(st, cfg.input_log_path, cfg2, speed=1000.0, frames_dir=cfg.frames_dir)
        assert src.full
        src.start()
        for _ in range(200):
            if any(e["text"] == "replay finished" for e in st.get()["events"]):
                break
            time.sleep(0.05)
        s = st.get()
        assert s["epochs"] == len(live) and s["mode"] == live[-1][1], (s["epochs"], len(live))
        assert any("whole box" in e["text"] for e in s["events"])
        print(f"[ok] disk cap: frames stop with a reason, the log and the box carry on; the console "
              f"replays a recording through the whole box ({s['epochs']} epochs, mode {s['mode']})")
        PASSED.append("console")


if __name__ == "__main__":
    tests = [test_record_and_replay_exactly, test_denial_injected_offline,
             test_disk_cap_and_console_replay]
    for t in tests:
        t()
    print(f"\n{len(PASSED)}/{len(tests)} recording tests passed")
