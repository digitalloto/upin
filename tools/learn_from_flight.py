"""
After each test flight: teach the AI motion predictor (layer 147) from it.

  python tools/learn_from_flight.py flight.bin --airframe my-quad-1
  python tools/learn_from_flight.py flight.bin --airframe my-quad-1 --notes notes.json
  python tools/learn_from_flight.py --simulate 8          # SIMULATED library, to try it

The flight is scored by the current model BEFORE it is learned from, then
used to train a new version, which goes live only if it is no worse on the
validation flights. Everything goes in the library folder (default
./upin_flights): the flight data, its measured weather, every model version,
and LEARNED_IO.md, the learning record to read after each flight.

notes.json is anything the operator wants kept with the flight, e.g.
  {"payload_kg": 0.4, "site": "Test range A", "imd_weather": "NW 15 km/h, 31 C"}

The live model for the box is <library>/models/v<N>.npz, where N is "live"
in <library>/manifest.json. Set learned_io_model in box.toml to that path.

Reading real .bin logs is UNTESTED until the first real log: ArduPilot's
field names can differ between firmware versions.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from upin.learned.flight_library import (FlightLibrary, read_dataflash,  # noqa: E402
                                         record_from_messages)


def summary(r: dict) -> str:
    lines = [f"{r['flight']}: role {r['role']}" + (f" ({r['role_why']})" if r["role_why"] else "")]
    w = r["conditions"]["wind"]
    lines.append("  weather: " + (f"wind {w['speed_ms']:.1f} m/s, gusts {w['gust_sigma_ms']:.2f}"
                                  if w else "wind not measured"))
    b = r.get("before_learning")
    if b and "stretches" in b:
        lines.append(f"  live model v{b['model']} on this unseen flight: velocity "
                     f"{b['velocity_rms_ms']:.2f} m/s rms; " + ", ".join(
                         f"{k}s drift {s['median_drift_m']:.0f} m (coasting "
                         f"{s['median_coast_drift_m']:.0f} m)"
                         for k, s in b["stretches"].items()))
    m = r.get("model")
    if m:
        lines.append(f"  new v{m['version']}: {'PROMOTED' if m['promoted'] else 'not promoted'}"
                     f" -- {m['reason']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("logs", nargs="*", help="ArduPilot .bin logs, oldest first")
    ap.add_argument("--airframe", help="airframe id (required for real logs)")
    ap.add_argument("--notes", help="JSON file of operator notes for these flights")
    ap.add_argument("--library", default="upin_flights")
    ap.add_argument("--simulate", type=int, default=0,
                    help="instead of logs: add N SIMULATED flights (separate library!)")
    ap.add_argument("--epochs", type=int, default=200)
    a = ap.parse_args(argv)
    lib = FlightLibrary(a.library)
    notes = json.loads(Path(a.notes).read_text()) if a.notes else None
    if a.simulate:
        from upin.learned.sim_flights import simulate_flight
        start = len(lib.flights())
        for i in range(start, start + a.simulate):
            rec = simulate_flight(f"sim{i + 1:03d}", 1000 + i, 300,
                                  wind_ms=1 + (i * 1.7) % 6, wind_toward_deg=(37 * i) % 360)
            print(summary(lib.learn_from_flight(rec, notes, a.epochs)))
    else:
        if not a.logs or not a.airframe:
            ap.error("give .bin logs and --airframe (or --simulate N)")
        for path in a.logs:
            rec = record_from_messages(read_dataflash(path), Path(path).stem,
                                       a.airframe, f"ardupilot log: {Path(path).name}")
            print(summary(lib.learn_from_flight(rec, notes, a.epochs)))
    print(f"\nlearning record: {Path(a.library) / 'LEARNED_IO.md'}")
    if lib.m["live"]:
        print(f"live model: {Path(a.library) / 'models' / ('v%d.npz' % lib.m['live'])}")


if __name__ == "__main__":
    main()
