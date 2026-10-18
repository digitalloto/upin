"""
Ground truth from tags: how far off was every other source?

  python tools/tag_truth.py /var/log/upin/box.jsonl

Reads the box log. Every epoch where layer 149 saw a surveyed tag and the
filter accepted the fix is a moment of known position, with no GNSS
involved. For each such epoch the tool measures the receiver's fix, the
flight controller's own GPS and UPIN's output against the tag fix and
reports the error statistics per source. The tag fix's own stated sigma is
reported beside them: an error under it is not resolvable by the tag.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict

DEG_M = 111_320.0


def distance_m(lat1, lon1, lat2, lon2):
    return math.hypot((lat2 - lat1) * DEG_M,
                      (lon2 - lon1) * DEG_M * math.cos(math.radians(lat1)))


def analyse(lines, max_age_s=1.0):
    errors = defaultdict(list)
    sigmas = []
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        if "run_start" in rec:
            continue
        fx = (rec.get("fixes") or {}).get("fiducial")
        if not fx or not fx.get("accepted") or abs(rec["t"] - fx["t"]) > max_age_s:
            continue
        sigmas.append(fx["sigma_m"])
        r = rec.get("receiver")
        if r and r.get("fix_type", 0) >= 3:
            errors["receiver"].append(distance_m(fx["lat"], fx["lon"], r["lat"], r["lon"]))
        g = rec.get("fc_gps")
        if g and g.get("fix_type", 0) >= 3:
            errors["flight controller GPS"].append(distance_m(fx["lat"], fx["lon"], g["lat"], g["lon"]))
        if rec.get("lat") is not None:
            errors["UPIN output"].append(distance_m(fx["lat"], fx["lon"], rec["lat"], rec["lon"]))
    return errors, sigmas


def report(errors, sigmas):
    if not sigmas:
        return "no epochs with an accepted tag fix in this log"
    out = [f"{len(sigmas)} epochs with a tag fix; tag fix sigma: median "
           f"{statistics.median(sigmas):.2f} m (errors below this are not resolvable)",
           "", "| source | epochs | median error | rms | max |", "|---|---:|---:|---:|---:|"]
    for src, e in errors.items():
        rms = math.sqrt(sum(x * x for x in e) / len(e))
        out.append(f"| {src} | {len(e)} | {statistics.median(e):.2f} m | {rms:.2f} m | {max(e):.2f} m |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log")
    a = ap.parse_args(argv)
    with open(a.log, encoding="utf-8") as f:
        print(report(*analyse(f)))


if __name__ == "__main__":
    main()
