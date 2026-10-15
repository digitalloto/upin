# Patch map (layer 154): map matching against ground the drone surveyed itself

The map-matching rung of the three-concept stack, made honest. The
concept documents put satellite tiles on the edge computer and match the
live camera against them to reset the drift. UPIN's rule is Indian map
sources only, and imagery licences are unconfirmed, so the **first map is
the one the drone makes itself**: on a flight with trusted GNSS (or the
trusted leg of this one), every 15 m the downward frame is rectified to a
north-up, metre-scaled square of ground and stored with the fix it was
stamped with and that fix's sigma. In a denied flight over the same
ground, live frames are matched against those patches for an **absolute
fix that resets the drift** of every velocity source.

> **Status: simulation only.** Simulated ground seen by a simulated
> leaning camera, through the real layer and the real box. Thresholds are
> assumptions until flown over real ground. Nothing is flight-proven.

## How it works

- **Rectify.** Each frame is turned into a north-up patch, 24 m across at
  0.5 m per pixel (assumptions), by projecting every patch pixel through
  the attitude onto the frame: the exact inverse of the tag layer's ray
  geometry, so a leaning drone's frame lands on the right ground. The
  patch is centred on the ground the camera **looks at** (the boresight,
  offset from the nadir by the lean), and the stamp carries that offset.
- **Build.** A patch is stored only when the fix is **trusted and tighter
  than 5 m** (the breadcrumb rule: a patch stamped with a guess would
  poison every later fix), the ground is textured, and no patch already
  covers the spot. The map is saved at the end of the flight
  (`patch_map`) and loaded at the next start, or built from a recording
  with `tools/build_patch_map.py` (`docs/RECORDING.md`).
- **Match.** The patches within the prior's radius (three sigmas plus a
  patch, at most 100 m) are painted into one local mosaic and the centre
  of the live patch is slid over it with normalised cross-correlation,
  coarse then fine. The best peak gives the position; its height says how
  sure, its sharpness how precise, the second-best peak whether the ground
  repeats. The fix's sigma folds in the peak's width, the stamp sigma of
  the patches matched, and the height's scale error.
- **Into the filter.** An accepted match goes through the filter's gate
  and re-anchors the reachable region, like a tag, beacon or formation
  fix. The console draws every stored patch as a faint square.

## Where it refuses, and says so

| Reason | Words |
|---|---|
| no map, no frame, no height, no attitude | |
| night | "frame too dark" |
| water, uniform sand, haze | "no texture to match" |
| the lean puts the patch outside the frame, or the camera looks off the corridor | "only N% of the patch is in the frame", "no map patch within R m" |
| off the surveyed corridor | "no map patch within R m of the prior" |
| the ground does not match (changed, or never surveyed) | "best correlation below 0.7" |
| the ground repeats (rows of crops, tiles) | "ambiguous: a second peak rivals the best" |
| a loose or untrusted fix while building | not stored, with the reason |

## Measured in simulation

Simulated ground (a pure function of position), a 40° camera at 50 m,
stamps from fixes 1.5 m off the truth.

| Scenario | Result |
|---|---|
| Pass 1 along a weaving 600 m track; pass 2 flown back the other way with a lean, 5° heading jitter and up to 5 m off the track, prior ±8 m | 33 patches stored; 78 of 83 frames fixed, **1.6 m rms** with a stated ±1.6 m, the 95% circle covering 100%, mean peak 0.93; the rest declined as ambiguous or below the threshold |
| Water (flat), night (dark), off the corridor, a 40° roll that looks off the corridor | each declined with its reason |
| Unrelated ground under the same prior | peak 0.60: declined (the threshold is 0.7) |
| Half-changed ground | peak 0.74: a fix, just above the threshold (the stated limit: seasons, shadows and crops lower the peak until it declines) |
| A checkerboard world | declined as ambiguous |
| Through the box on the console circuit, one lap trusted | 35 patches stored (stamps ≤ 1.5 m) and saved at close; `tools/build_patch_map.py` rebuilt the same 35 from the recording; a box loads the map |
| The console: lap 1 builds, lap 2 in the far-straight jammer with beacons, formation and crumbs off | 98 patches stored on lap 1; inside the jam 10 of the 11 epochs without a fix got a patch-map fix, worst error vs the simulated truth 1 m |
| A foreign map source | refused at construction and on load |

`python tests/test_patch_map.py` reproduces every row.

## What it needs

- a downward camera and a downward rangefinder (height scales the frame),
  the flight controller's attitude (already read);
- `patch_map = "<file>"` to load and save, `patch_map_build = true` to
  store patches while trusted, `patch_spacing_m` (15 m);
- **a flight over the same ground**: the map is the flown corridor, 24 m
  wide; fly back along the track, or survey on a lawnmower pattern;
- daylight and textured ground.

## An Indian-source orthophoto, later

The same patch format can hold tiles from Bhuvan, Cartosat or the
operator's own survey (`validate_map_source` refuses anything else). An
importer from a georeferenced image is the next step, after the
provider's licence for this use is confirmed. Nothing here loads tiles
from the internet.

## Limits, stated

- Day only; needs texture and a known height.
- The map is only as good as the fixes it was built with; it carries
  their sigmas and every fix carries them on.
- Seasons, shadows, crops and water levels change the ground; the peak
  falls and the layer declines rather than guessing.
- The corridor is 24 m wide; a parallel track 30 m away has no map.
- The patch size, the sampling distance, the peak threshold and the
  ambiguity ratio are assumptions until flown.
- Memory: 9 KB per patch; a kilometre of corridor is about 600 KB.

## Files

| | |
|---|---|
| `upin/vision/patch_map.py` | rectification, the map file, the mosaic and the match |
| `upin/layers/optical/patch_map.py` | the layer: build rules, declines, the fix |
| `upin/box/service.py` | `patch_map`, `patch_map_build`, `patch_spacing_m`; `step_patch_map` |
| `tools/build_patch_map.py` | a map from a flight recording |
| `upin/simulation/markers.py` | the simulated camera now leans with the airframe |
| `tests/test_patch_map.py` | every figure above |
