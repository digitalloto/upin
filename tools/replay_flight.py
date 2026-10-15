#!/usr/bin/env python
"""
Re-run the whole box on a flight recording, deny GNSS in software from any
moment, and measure UPIN against the receiver's own logged fix.

    python tools/replay_flight.py --config box.toml --log inputs.jsonl --frames frames/
    python tools/replay_flight.py --config box.toml --log inputs.jsonl --deny-after 60 --deny-for 120
    python tools/replay_flight.py --config box.toml --log inputs.jsonl --deny-from 250 --report out.md

The recording comes from the box with input_log_path and frames_dir set
(docs/RECORDING.md). The report is Markdown: a summary of the denial and
one row per epoch. Every number is computed; nothing is flight-proven.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from upin.box.flight_replay import is_input_log, replay  # noqa: E402
from upin.box.service import load_config  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, help="box.toml the flight was flown with")
    ap.add_argument("--log", required=True, help="the recorder's input log (inputs.jsonl)")
    ap.add_argument("--frames", default=None, help="the recorder's frames folder")
    ap.add_argument("--deny-from", type=float, default=None,
                    help="recording time (s) from which GNSS is denied in software")
    ap.add_argument("--deny-after", type=float, default=None,
                    help="deny after this many seconds of TRUSTED (as the live --deny-after)")
    ap.add_argument("--deny-for", type=float, default=60.0)
    ap.add_argument("--report", default=None, help="write the Markdown report here")
    a = ap.parse_args(argv)
    if not is_input_log(a.log):
        print(f"{a.log} is not a recorder input log (no header line); for a plain epoch log use "
              f"python -m upin.box.replay", file=sys.stderr)
        return 2
    cfg = load_config(a.config)
    rep = replay(cfg, a.config, a.log, a.frames, deny_from=a.deny_from, deny_after=a.deny_after,
                 deny_for=a.deny_for)
    text = rep.render()
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"report written to {a.report}")
    s = rep.summary()
    print(f"{s['epochs']} epochs replayed, modes {s['modes']}, frames {s['frames_replayed']}/"
          f"{s['frames_recorded']} recorded")
    if rep.denial:
        print(f"denied {s['denied_epochs']} epochs ({s['denied_seconds']:.0f} s): error vs the receiver's "
              f"logged fix mean {s['denied_error_mean_m']}, worst {s['denied_error_max_m']}; velocity "
              f"sources {s['velocity_sources_during_denial']}; fixes {s['fixes_accepted_during_denial']}")
    if not a.report:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
