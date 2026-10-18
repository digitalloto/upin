"""Tests for the flight summary (upin/box/flight_summary.py,
tools/flight_summary.py): a console-sim log with a software denial in the
middle gives a report whose numbers are computed and finite; a log whose
flight controller reports no accuracy says so; runs are split on their
run_start records.

Run: python tests/test_flight_summary.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")

from upin.box.flight_summary import read_runs, render, summarize  # noqa: E402
from upin.console.sources import SimSource  # noqa: E402
from upin.console.state import ConsoleState  # noqa: E402

PASSED = []


def sim_log(seconds=90, deny=(40, 60)):
    st = ConsoleState("sim", "SIMULATION", True, SimSource.controls)
    sim = SimSource(st, 13.0827, 80.2707, seed=9)
    sim.box.log = io.StringIO()
    sim.box.sending = False
    for k in range(seconds):
        sim.box.deny_gnss = deny[0] <= k < deny[1]
        sim.step()
    return sim.box.log.getvalue()


def test_summary_of_a_denied_run():
    text = sim_log()
    start = json.dumps({"run_start": 1.7e9, "flags": {"send": False, "deny_after": None}, "upin_version": "0.1.0",
                        "python": "3.11", "host": "test"})
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "box.jsonl")
        with open(path, "w") as f:
            f.write(start + "\n" + text + start + "\n" + text)
        runs = read_runs(path)
        assert len(runs) == 2 and runs[0]["start"]["host"] == "test"
        s = summarize(runs[0]["records"], runs[0]["start"])
        assert s["epochs"] == 90 and s["sending"] == {"False": 90}
        r = s["receiver"]
        assert r["fix_3d_fraction"] > 0.9 and r["satellites_mean"] > 5 and 0 < r["h_acc_mean_m"] < 10
        assert r["utc_first"] is None or isinstance(r["utc_first"], str)
        p = s["signal_power"]
        assert p["epochs"] > 50 and p["cn0_mean_dbhz"] and 30 < p["cn0_mean_dbhz"] < 50
        tw = s["two_receivers"]
        assert tw["epochs_both_3d"] >= 60 and 0 < tw["difference_mean_m"] < 15 and tw["fc_reports_accuracy_fraction"] == 1.0
        assert tw["cross_check"].get("PASS", 0) > 50
        u = s["upin"]
        assert u["modes"]["DEGRADED"] >= 20 and 0.5 < u["trusted_fraction"] < 1.0
        assert "receiver has no 3-D fix" in " ".join(u["reasons_when_not_trusted"])
        assert u["checks"]["physically reachable"]["PASS"] > 50
        assert u["fixes_accepted"] and u["velocity_sources"]
        den = s["denials"]
        assert len(den) == 1 and den[0]["epochs"] == 20 and den[0]["from_t"] == 41.0
        assert den[0]["error_mean_m"] is not None and den[0]["error_max_m"] < 60
        assert den[0]["modes"].get("DEGRADED", 0) == 20
        md = render(s, "box.jsonl")
        assert "## Software denials" in md and "+30 s" in md and "| cross-check |" in md
        assert "computed from the log" in md
        out = subprocess.run([sys.executable, "tools/flight_summary.py", path, "--report",
                              os.path.join(d, "r.md")], capture_output=True, text=True)
        assert out.returncode == 0 and os.path.exists(os.path.join(d, "r.md"))
        assert "(run 1 of 2)" in open(os.path.join(d, "r.md")).read()
    # a flight controller that reports no accuracy
    recs = [json.loads(l) for l in text.splitlines()]
    for rec in recs:
        if rec.get("fc_gps"):
            rec["fc_gps"]["h_acc_m"] = None
    s2 = summarize(recs)
    assert s2["two_receivers"]["fc_reports_accuracy_fraction"] == 0.0
    assert "GPS_TYPE" in render(s2, "x")
    print(f"[ok] a 90 s simulated run with a 20 s software denial: receiver {r['satellites_mean']:.0f} satellites, "
          f"hAcc {r['h_acc_mean_m']:.1f} m; the two receivers {tw['difference_mean_m']:.1f} m apart on average; "
          f"UPIN TRUSTED {u['trusted_fraction']:.0%}; denial error mean {den[0]['error_mean_m']:.1f} m; "
          f"two runs split on run_start; a flight controller without accuracy is named")
    PASSED.append("summary")


if __name__ == "__main__":
    test_summary_of_a_denied_run()
    print(f"\n{len(PASSED)}/1 flight-summary tests passed")
