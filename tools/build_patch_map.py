#!/usr/bin/env python
"""
Build a patch map (layer 154) from a flight recording: the box is re-run
over the recording with patch_map_build on, so patches are stored only at
epochs the box itself trusted, exactly as it would have in flight.

    python tools/build_patch_map.py --config box.toml --log inputs.jsonl --frames frames/ --out map.npz

The map carries the stamp sigma of every patch and the source
"field_survey" (the drone's own survey). docs/PATCH_MAP.md.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from upin.box.flight_replay import is_input_log, replay  # noqa: E402
from upin.box.service import BoxConfig, load_config  # noqa: E402
from upin.vision.patch_map import PatchMap  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--log", required=True, help="the recorder's input log")
    ap.add_argument("--frames", required=True, help="the recorder's frames folder")
    ap.add_argument("--out", required=True, help="patch map file to write (.npz)")
    ap.add_argument("--spacing", type=float, default=None, help="metres between patches")
    a = ap.parse_args(argv)
    if not is_input_log(a.log):
        print(f"{a.log} is not a recorder input log", file=sys.stderr)
        return 2
    cfg = load_config(a.config)
    cfg = BoxConfig(**{**cfg.__dict__, "patch_map": a.out, "patch_map_build": True,
                       **({"patch_spacing_m": a.spacing} if a.spacing else {})})
    if os.path.exists(a.out):
        os.remove(a.out)                      # build fresh, never append to an old map
    rep = replay(cfg, a.config, a.log, a.frames)
    if not os.path.exists(a.out):
        print("no patch stored: no epoch was trusted with a textured frame in view", file=sys.stderr)
        return 1
    m = PatchMap.load(a.out)
    print(f"{len(m)} patches stored over {len(rep.rows)} epochs, stamp sigma "
          f"{min(m.sigma_m):.1f}-{max(m.sigma_m):.1f} m, source {m.source}: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
