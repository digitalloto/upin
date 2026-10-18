#!/usr/bin/env python
"""
Summarise a box log: the receiver, the two receivers compared, UPIN's
decisions and checks, and every software denial measured against the
receiver's own fix. Markdown out; every number computed.

    python tools/flight_summary.py /var/log/upin/box-20261020-101500.jsonl
    python tools/flight_summary.py box.jsonl --report flight.md
    python tools/flight_summary.py a.jsonl b.jsonl --report day.md     # one section per run
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from upin.box.flight_summary import read_runs, render, summarize  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--report", default=None, help="write Markdown here instead of printing")
    a = ap.parse_args(argv)
    parts = []
    for path in a.logs:
        runs = read_runs(path)
        if not runs:
            parts.append(f"# {os.path.basename(path)}\n\nempty log\n")
            continue
        for k, run in enumerate(runs):
            title = os.path.basename(path) + (f" (run {k + 1} of {len(runs)})" if len(runs) > 1 else "")
            parts.append(render(summarize(run["records"], run["start"]), title))
    text = "\n".join(parts)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"report written to {a.report}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
