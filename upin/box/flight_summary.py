"""
One flight, summarised from the box's epoch log: what the receiver gave,
how it compared with the flight controller's GPS, what UPIN decided and
why, and how UPIN did during every software denial against the receiver's
own fix. Every number is computed from the log; nothing is stated.

    python tools/flight_summary.py /var/log/upin/box-20261020-101500.jsonl --report flight.md

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from upin.detection.reachability import DEG_M


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    dn = (lat2 - lat1) * DEG_M
    de = (lon2 - lon1) * DEG_M * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dn, de)


def read_runs(path: str) -> List[dict]:
    """Split a log into runs on its run_start records: [{"start": rec or
    None, "records": [...]}]."""
    runs: List[dict] = []
    cur = {"start": None, "records": []}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if "run_start" in rec:
                if cur["records"] or cur["start"] is not None:
                    runs.append(cur)
                cur = {"start": rec, "records": []}
            else:
                cur["records"].append(rec)
    if cur["records"] or cur["start"] is not None:
        runs.append(cur)
    return runs


def _pct(x: List[float], q: float) -> Optional[float]:
    return float(np.percentile(x, q)) if x else None


def summarize(records: List[dict], start: Optional[dict] = None) -> dict:
    s: dict = {"epochs": len(records)}
    if not records:
        return s
    t = [r["t"] for r in records]
    s["duration_s"] = t[-1] - t[0]
    s["rate_hz"] = (len(records) - 1) / (t[-1] - t[0]) if t[-1] > t[0] else None
    s["start"] = None if start is None else {k: start.get(k) for k in
                                             ("run_start", "flags", "upin_version", "python", "host")}
    s["sending"] = Counter(str(r.get("sending")) for r in records)

    # the receiver
    rx = [r["receiver"] for r in records if r.get("receiver")]
    fix = Counter(r["fix_type"] for r in rx)
    sv = [r["num_sv"] for r in rx if r["fix_type"] >= 3]
    hacc = [r["h_acc_m"] for r in rx if r["fix_type"] >= 3 and r["h_acc_m"] is not None]
    s["receiver"] = {
        "epochs_with_receiver": len(rx), "fix_types": dict(fix),
        "fix_3d_fraction": (sum(v for k, v in fix.items() if k >= 3) / len(rx)) if rx else None,
        "satellites_mean": float(np.mean(sv)) if sv else None, "satellites_min": min(sv) if sv else None,
        "h_acc_mean_m": float(np.mean(hacc)) if hacc else None, "h_acc_p95_m": _pct(hacc, 95),
        "jamming_states": dict(Counter(r.get("jamming") for r in rx)),
        "utc_first": next((r.get("utc") for r in rx if r.get("utc")), None),
    }
    # signal power from the epoch's power_check, if the receiver gave NAV-SAT
    cn0, agc, verdicts = [], [], Counter()
    for r in records:
        pc = (r.get("epoch") or {}).get("power_check") or {}
        if not pc:
            continue
        verdicts[pc.get("verdict")] += 1
        sats = pc.get("satellites") or []
        vals = [x[1] for x in sats if isinstance(x, (list, tuple)) and len(x) > 1 and x[1]]
        if vals:
            cn0.append(float(np.mean(vals)))
        if pc.get("agc") is not None:
            agc.append(pc["agc"])
    s["signal_power"] = {"epochs": sum(verdicts.values()), "verdicts": dict(verdicts),
                         "cn0_mean_dbhz": float(np.mean(cn0)) if cn0 else None,
                         "agc_mean": float(np.mean(agc)) if agc else None,
                         "agc_min": min(agc) if agc else None, "agc_max": max(agc) if agc else None}

    # the two receivers
    both, fc_acc = [], 0
    fc_seen = 0
    for r in records:
        g, x = r.get("fc_gps"), r.get("receiver")
        if g:
            fc_seen += 1
            if g.get("h_acc_m") is not None:
                fc_acc += 1
        if g and x and g["fix_type"] >= 3 and x["fix_type"] >= 3 and (g.get("age_s") or 0) <= 1.0:
            both.append(_dist_m(x["lat"], x["lon"], g["lat"], g["lon"]))
    cross = Counter()
    for r in records:
        for c in r.get("checks") or []:
            if c["check"] == "cross-check":
                cross[c["status"]] += 1
    s["two_receivers"] = {
        "epochs_with_fc_gps": fc_seen, "fc_reports_accuracy_fraction": (fc_acc / fc_seen) if fc_seen else None,
        "epochs_both_3d": len(both), "difference_mean_m": float(np.mean(both)) if both else None,
        "difference_p95_m": _pct(both, 95), "difference_max_m": max(both) if both else None,
        "cross_check": dict(cross),
    }

    # UPIN's decisions
    modes = Counter(r["mode"] for r in records)
    reasons = Counter()
    warnings = Counter()
    for r in records:
        for why in r.get("reasons") or []:
            if why.startswith("warning:"):
                warnings[why[9:].strip()[:80]] += 1
            elif r["mode"] != "TRUSTED":
                reasons[why[:80]] += 1
    checks: Dict[str, Counter] = {}
    for r in records:
        for c in r.get("checks") or []:
            checks.setdefault(c["check"], Counter())[c["status"]] += 1
    fixes = Counter()
    vsrc = Counter()
    curve = 0
    for r in records:
        for src, f in (r.get("fixes") or {}).items():
            if f.get("accepted") and abs(f.get("t", -1e9) - r["t"]) <= 1.0:
                fixes[src] += 1
        w = r.get("wind_dr") or {}
        if w.get("fed"):
            vsrc["wind DR"] += 1
        curve = max(curve, w.get("curve_samples") or 0)
        cf = r.get("camera_flow") or {}
        if cf.get("fed"):
            vsrc["camera flow"] += 1
        if (r.get("flow") or {}).get("quality"):
            vsrc["flow chip present"] += 1
    s["upin"] = {"modes": dict(modes), "trusted_fraction": modes.get("TRUSTED", 0) / len(records),
                 "reasons_when_not_trusted": dict(reasons.most_common(12)),
                 "warnings": dict(warnings.most_common(8)),
                 "checks": {k: dict(v) for k, v in checks.items()},
                 "fixes_accepted": dict(fixes), "velocity_sources": dict(vsrc),
                 "tilt_curve_samples": curve}

    # software denials: the receiver kept logging, so UPIN is measured against it
    denials = []
    i = 0
    while i < len(records):
        if records[i].get("deny_gnss"):
            j = i
            while j < len(records) and records[j].get("deny_gnss"):
                j += 1
            win = records[i:j]
            t0 = win[0]["t"]
            errs = []
            for r in win:
                x = r.get("receiver")
                if r.get("lat") is not None and x and x["fix_type"] >= 3:
                    errs.append((r["t"] - t0, _dist_m(r["lat"], r["lon"], x["lat"], x["lon"])))
            at = {}
            for k in (30, 60, 120):
                c = [e for dt, e in errs if dt >= k]
                at[f"error_at_{k}s_m"] = c[0] if c else None
            denials.append({"from_t": t0, "seconds": win[-1]["t"] - t0, "epochs": len(win),
                            "modes": dict(Counter(r["mode"] for r in win)),
                            "error_mean_m": float(np.mean([e for _, e in errs])) if errs else None,
                            "error_max_m": max(e for _, e in errs) if errs else None, **at,
                            "wind_dr_fed": sum(1 for r in win if (r.get("wind_dr") or {}).get("fed")),
                            "fixes_accepted": dict(Counter(
                                src for r in win for src, f in (r.get("fixes") or {}).items()
                                if f.get("accepted") and abs(f.get("t", -1e9) - r["t"]) <= 1.0))})
            i = j
        else:
            i += 1
    s["denials"] = denials
    return s


def _f(x, unit="", nd=1) -> str:
    return "-" if x is None else f"{x:.{nd}f}{unit}"


def render(s: dict, title: str) -> str:
    L = [f"# {title}", ""]
    if s.get("epochs", 0) == 0:
        return "\n".join(L + ["No epochs in this run.", ""])
    st = s.get("start") or {}
    L += [f"{s['epochs']} epochs over {s['duration_s']:.0f} s at {_f(s.get('rate_hz'), ' Hz')}; "
          f"sending: {dict(s['sending'])}; UPIN {st.get('upin_version') or '?'} on "
          f"{st.get('host') or '?'}; flags {st.get('flags') or '?'}", ""]
    r = s["receiver"]
    L += ["## The receiver", "",
          f"- fix types {r['fix_types']}; 3-D fraction {_f(r['fix_3d_fraction'], '', 2)}",
          f"- satellites mean {_f(r['satellites_mean'])}, min {r['satellites_min']}",
          f"- stated accuracy (hAcc) mean {_f(r['h_acc_mean_m'], ' m')}, 95th percentile {_f(r['h_acc_p95_m'], ' m')}",
          f"- jamming states {r['jamming_states']}; first UTC {r['utc_first'] or '(not logged)'}"]
    p = s["signal_power"]
    if p["epochs"]:
        L += [f"- signal power (layer 146) over {p['epochs']} epochs: verdicts {p['verdicts']}, mean C/N0 "
              f"{_f(p['cn0_mean_dbhz'], ' dB-Hz')}, AGC mean {_f(p['agc_mean'], '', 0)} "
              f"(min {p['agc_min']}, max {p['agc_max']})"]
    else:
        L += ["- no per-satellite signal data (NAV-SAT not received): the signal-power check did not run"]
    L.append("")
    tw = s["two_receivers"]
    L += ["## Box receiver against the flight controller's GPS", ""]
    if tw["epochs_both_3d"]:
        L += [f"- both had a 3-D fix on {tw['epochs_both_3d']} epochs: horizontal difference mean "
              f"{_f(tw['difference_mean_m'], ' m')}, 95% {_f(tw['difference_p95_m'], ' m')}, "
              f"max {_f(tw['difference_max_m'], ' m')}"]
    else:
        L += ["- never both with a 3-D fix: no comparison possible"]
    L += [f"- the flight controller's GPS reported an accuracy on "
          f"{_f((tw['fc_reports_accuracy_fraction'] or 0) * 100, '%', 0)} of {tw['epochs_with_fc_gps']} epochs"
          + ("" if (tw["fc_reports_accuracy_fraction"] or 0) > 0.5 else
             " -- without it the cross-check cannot run (GPS_TYPE on the flight controller)"),
          f"- cross-check verdicts {tw['cross_check'] or 'none'}", ""]
    u = s["upin"]
    L += ["## UPIN's decisions", "",
          f"- modes {u['modes']}; TRUSTED {u['trusted_fraction']:.0%} of epochs",
          f"- reasons when not trusted: {u['reasons_when_not_trusted'] or 'none'}",
          f"- warnings: {u['warnings'] or 'none'}",
          f"- fixes accepted by source: {u['fixes_accepted'] or 'none'}; velocity sources: {u['velocity_sources'] or 'none'}; "
          f"tilt curve samples learned: {u['tilt_curve_samples']}", "",
          "| check | " + " | ".join(("PASS", "WARN", "FAIL", "NOT RUN")) + " |", "|---|---:|---:|---:|---:|"]
    for name, c in u["checks"].items():
        L.append(f"| {name} | {c.get('PASS', 0)} | {c.get('WARN', 0)} | {c.get('FAIL', 0)} | {c.get('NOT RUN', 0)} |")
    if not u["checks"]:
        L.append("| (no per-check results in this log: an older box) | | | | |")
    L.append("")
    L += ["## Software denials (UPIN against the receiver's own fix, which kept logging)", ""]
    if not s["denials"]:
        L.append("none in this run")
    for d in s["denials"]:
        L += [f"- from t = {d['from_t']:.0f} s for {d['seconds']:.0f} s ({d['epochs']} epochs): modes {d['modes']}; "
              f"error mean {_f(d['error_mean_m'], ' m')}, max {_f(d['error_max_m'], ' m')}; at +30 s "
              f"{_f(d.get('error_at_30s_m'), ' m')}, +60 s {_f(d.get('error_at_60s_m'), ' m')}, +120 s "
              f"{_f(d.get('error_at_120s_m'), ' m')}; wind DR fed {d['wind_dr_fed']} epochs; fixes "
              f"{d['fixes_accepted'] or 'none'}"]
    L += ["", "Every number above is computed from the log. The receiver's own stated accuracy is the "
          "reference's; nothing here is flight-proven.", ""]
    return "\n".join(L)
